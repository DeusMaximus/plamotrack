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
    "upgrade_applications, retailers, orders, order_items"
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
        await session.commit()


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
async def retailer(client) -> dict:
    resp = await client.post("/retailers", json={"name": "Hobby Link Japan"})
    assert resp.status_code == 201
    return resp.json()
