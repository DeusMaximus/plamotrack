import asyncio
import os

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.config import Settings

# Point the app at a dedicated test database BEFORE app.db creates its engine.
# By default the connection follows the same .env/POSTGRES_* configuration as
# source development, but uses a sibling database that tests can safely reset.
_configured_url = make_url(Settings().database_url)
_default_test_url = _configured_url.set(
    database=f"{_configured_url.database}_test"
).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", _default_test_url)

# Each test runs in its own event loop; pooled asyncpg connections are loop-bound,
# so disable pooling entirely for tests.
os.environ["DATABASE_POOL"] = "null"

from app.db import get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.services.instance_settings import DEFAULTS as _SETTINGS_DEFAULTS  # noqa: E402

_TABLES = (
    "kits, kit_photos, tools, consumables, upgrades, display_items, "
    "upgrade_applications, retailers, orders, order_items, "
    # Auth tables (M6-3, #188). Never portable, so absent from the CSV spec, but
    # they still accumulate across tests: setup claims the owner and login/setup
    # write credentials, sessions and audit rows. `owner` is the exception — a
    # singleton like instance_settings, reset below rather than truncated.
    "credential, session, personal_access_token, audit_event, oidc_login, "
    # The MCP OAuth proxy's state store (M6-7, #192): registrations, transactions
    # and encrypted upstream tokens an OIDC-mode test leaves behind.
    "mcp_oauth_state"
)

#: The owner row is seeded once by the migration and cannot be recreated at
#: runtime (the singleton CHECK). Between tests it is reset to **unclaimed**, the
#: fresh-install state, so a setup test starts from the same place every time.
_RESET_OWNER = (
    "UPDATE owner SET claimed_at = NULL, oidc_issuer = NULL, oidc_subject = NULL, "
    "display_name = NULL"
)

# The instance_settings singleton is deliberately NOT in _TABLES — truncating it
# would delete the row migrations created, which nothing at runtime can do (#23).
# It is reset to its bootstrap values instead, the same shape the migration seeds.
_RESET_SETTINGS = (
    "INSERT INTO instance_settings "
    "(id, interface_language, formatting_locale, time_zone, date_style, hour_cycle, "
    " reference_currency) "
    "VALUES (1, :interface_language, :formatting_locale, :time_zone, :date_style, "
    " :hour_cycle, :reference_currency) "
    "ON CONFLICT (id) DO UPDATE SET "
    "interface_language = EXCLUDED.interface_language, "
    "formatting_locale = EXCLUDED.formatting_locale, "
    "time_zone = EXCLUDED.time_zone, "
    "date_style = EXCLUDED.date_style, "
    "hour_cycle = EXCLUDED.hour_cycle, "
    "reference_currency = EXCLUDED.reference_currency"
)


async def _ensure_test_database() -> None:
    """Create the configured test database if it is missing."""
    url = make_url(os.environ["DATABASE_URL"])
    admin = create_async_engine(
        url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database}
        )
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def apply_migrations():
    """Exercise the real migrations (both directions) on every test run."""
    asyncio.run(_ensure_test_database())
    cfg = Config("alembic.ini")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def clean_tables(apply_migrations):
    yield
    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE {_TABLES} CASCADE"))
        await session.execute(
            text(_RESET_SETTINGS),
            _SETTINGS_DEFAULTS | {"reference_currency": Settings().reference_currency},
        )
        await session.execute(text(_RESET_OWNER))
        await session.commit()


# The shipped `app` is default-deny since M6-3 (#188). The suite drives it with
# an injected **owner** principal by default (the in-process seam the shipped
# image never sets), so every pre-auth test keeps exercising its route without a
# real login; an injected principal is not cookie-borne, so the CSRF controls do
# not apply to it. Tests about authentication itself use `anon_client` (no
# principal) or build a real session; `test_authorization.py` manages injection
# per request on its own app.
from app.auth import owner  # noqa: E402
from app.auth.budget import FailureBudget  # noqa: E402
from app.auth.mcp_auth import INJECTED_MCP_PRINCIPAL_ATTR  # noqa: E402
from app.auth.resolver import INJECTED_PRINCIPAL_ATTR  # noqa: E402
from app.auth.setup_token import setup_token_state  # noqa: E402
from app.mcp import mcp as mcp_server  # noqa: E402
from app.routers.auth import BUDGET_ATTR  # noqa: E402


@pytest.fixture(autouse=True)
def _inject_owner():
    """Every test starts with an injected owner on the shipped app, cleared after
    so a test that removes it (the auth-flow tests) cannot leak anonymity into
    the next test. The process-level auth state that also lives on `app.state` —
    the login/setup failure budget and the announced setup token — is reset too,
    so one test's throttle or issued token cannot reach the next (both persist on
    the module app otherwise). The MCP server gets the same owner for in-memory
    tool calls (`Client(mcp)`), which carry no bearer — the seam the tool-scope
    middleware reads only when no HTTP request is in flight (#189)."""
    setattr(app.state, INJECTED_PRINCIPAL_ATTR, owner())
    setattr(mcp_server, INJECTED_MCP_PRINCIPAL_ATTR, owner())
    setattr(app.state, BUDGET_ATTR, FailureBudget())
    setup_token_state(app).consume()
    yield
    if hasattr(app.state, INJECTED_PRINCIPAL_ATTR):
        delattr(app.state, INJECTED_PRINCIPAL_ATTR)
    if hasattr(mcp_server, INJECTED_MCP_PRINCIPAL_ATTR):
        delattr(mcp_server, INJECTED_MCP_PRINCIPAL_ATTR)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def http_client():
    """`client`, but an unhandled exception comes back as a 500 response instead of
    being re-raised into the test.

    The default transport re-raises, so a test asserting `== 422` against a route
    that actually 500s fails as an *error* naming some internal exception. That
    still goes red, but it pins nothing about the status contract, and the next
    person to read it can't tell whether 500 or 422 is the agreed answer. Use this
    wherever the point of the test is which status a bad upload earns (rule 6).
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def anon_client():
    """The shipped app with **no** injected principal — a real anonymous caller.
    Used by the auth-flow tests, which then present real cookies. Clears the
    autouse owner injection for the duration."""
    had = hasattr(app.state, INJECTED_PRINCIPAL_ATTR)
    if had:
        delattr(app.state, INJECTED_PRINCIPAL_ATTR)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def retailer(client) -> dict:
    resp = await client.post("/retailers", json={"name": "Hobby Link Japan"})
    assert resp.status_code == 201
    return resp.json()
