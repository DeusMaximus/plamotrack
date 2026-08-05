import os

# Point the app at the test database BEFORE any app module is imported.
# Real env vars beat the .env file in pydantic-settings, so this wins.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://plamotrack:plamotrack@127.0.0.1:5432/plamotrack_test",
)
# Each test runs in its own event loop; pooled asyncpg connections are loop-bound,
# so disable pooling entirely for tests.
os.environ["DATABASE_POOL"] = "null"

import asyncio  # noqa: E402

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from alembic import command  # noqa: E402
from app.db import get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402

_TABLES = (
    "kits, kit_photos, tools, consumables, upgrades, "
    "upgrade_applications, retailers, orders, order_items"
)


async def _ensure_test_database() -> None:
    """Create the test database if missing, so `docker compose up -d db` +
    `pytest` works on a fresh checkout with no manual setup."""
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
        await session.commit()


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def retailer(client) -> dict:
    resp = await client.post("/retailers", json={"name": "Hobby Link Japan"})
    assert resp.status_code == 201
    return resp.json()
