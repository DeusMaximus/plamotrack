"""The client records' bounds (#221 item 2; §5.6 resource exhaustion).

`POST /mcp/register` is anonymous by protocol and used to mint a permanent row
per request; FastMCP's CIMD path persisted a record per URL ever presented as a
client id and cached the document in an unbounded dict; the key-value adapter
never physically deleted the rows whose TTL had passed. Now a client record
lives `UNLINKED_CLIENT_TTL_SECONDS` until a grant links it, the collection is
capped, an address has a registration quota, expired rows are culled from the
two anonymous entry points, and the document cache is bounded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastmcp.server.auth.cimd import CIMDFetcher
from sqlalchemy import text

from app import error_codes
from app.auth import mcp_oauth
from app.auth.mcp_oauth import (
    CIMD_CACHE_ENTRIES,
    MCP_OAUTH_ATTR,
    REGISTRATION_WINDOW_SECONDS,
    REGISTRATIONS_PER_ADDRESS,
    BoundedCache,
    ClientRecords,
    RegistrationQuota,
)
from app.auth.mcp_oauth_state import (
    CLIENT_COLLECTION,
    MAX_CLIENT_RECORDS,
    TRANSACTION_COLLECTION,
    UNLINKED_CLIENT_TTL_SECONDS,
)
from app.db import get_sessionmaker
from tests.oidc_fake import FakeIdp
from tests.test_mcp_oauth import _bind_owner, _cimd_document, link, oauth_app, register
from tests.test_mcp_oauth_clients import CIMD_ID, cimd, cimd_link, stored_client

pytestmark = pytest.mark.anyio


async def _rows(collection: str) -> list[tuple[str, datetime | None]]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            text("SELECT key, expires_at FROM mcp_oauth_state WHERE collection = :c ORDER BY key"),
            {"c": collection},
        )
        return [(row[0], row[1]) for row in rows]


async def _insert_expired(collection: str, key: str) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            text(
                "INSERT INTO mcp_oauth_state (collection, key, value, ttl, created_at, expires_at)"
                " VALUES (:c, :k, '{}'::jsonb, 1, :t, :t)"
            ),
            {"c": collection, "k": key, "t": datetime.now(UTC) - timedelta(days=1)},
        )
        await session.commit()


# --- lifetime ------------------------------------------------------------------------


async def test_a_registration_expires_unless_a_grant_links_it():
    """A fresh registration is stored with the unlinked lifetime; the link —
    issuance at `/mcp/token` — makes the record permanent."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        registered = await register(client)
        assert registered.status_code == 201, registered.text
        unlinked = registered.json()["client_id"]
        rows = dict(await _rows(CLIENT_COLLECTION))
        expires_at = rows[unlinked]
        assert expires_at is not None
        remaining = (expires_at - datetime.now(UTC)).total_seconds()
        assert UNLINKED_CLIENT_TTL_SECONDS - 60 < remaining <= UNLINKED_CLIENT_TTL_SECONDS
        linked = await link(client, fake)
        assert linked["status"] == 200, linked["body"]
        rows = dict(await _rows(CLIENT_COLLECTION))
        assert rows[linked["client_id"]] is None, "the linked client's record must be permanent"
        assert rows[unlinked] is not None, "the unlinked registration keeps its lifetime"


async def test_a_cimd_record_is_stored_with_the_lifetime_too(monkeypatch):
    """FastMCP persists a CIMD client on first lookup with no lifetime and
    re-puts it on every refresh; through `ClientRecords` every such write
    carries the unlinked lifetime."""
    cimd(monkeypatch, "none")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, _):
        found = await stored_client(live, CIMD_ID)
        assert found is not None and found.cimd_document is not None
        rows = dict(await _rows(CLIENT_COLLECTION))
        assert rows[CIMD_ID] is not None


async def test_a_refresh_does_not_put_a_linked_client_back_on_the_clock(monkeypatch):
    """FastMCP re-puts a CIMD client's record on every lookup that refreshes
    the document, with no lifetime of its own; through `ClientRecords` that
    write keeps a linked (permanent) record permanent, and an unlinked one on
    its lifetime."""
    cimd(monkeypatch, "none")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        await stored_client(live, CIMD_ID)  # the first lookup stores it, on the clock
        assert dict(await _rows(CLIENT_COLLECTION))[CIMD_ID] is not None
        await cimd_link(client, fake, None)  # issuance keeps it
        assert dict(await _rows(CLIENT_COLLECTION))[CIMD_ID] is None
        await stored_client(live, CIMD_ID)  # a refresh write
        assert dict(await _rows(CLIENT_COLLECTION))[CIMD_ID] is None


# --- the cap and the quota --------------------------------------------------------------


async def test_the_collection_is_capped_and_the_guard_answers_503_first(monkeypatch):
    monkeypatch.setattr(mcp_oauth, "MAX_CLIENT_RECORDS", 2)
    monkeypatch.setattr("app.auth.mcp_oauth_state.MAX_CLIENT_RECORDS", 2)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        for _ in range(2):
            assert (await register(client)).status_code == 201
        refused = await register(client)
        assert refused.status_code == 503
        assert refused.headers["retry-after"] == str(UNLINKED_CLIENT_TTL_SECONDS)
        assert refused.headers["cache-control"] == "no-store"
        assert refused.json()["code"] == error_codes.AUTH_MCP_REGISTRATIONS_FULL
        assert len(await _rows(CLIENT_COLLECTION)) == 2


async def test_a_cimd_lookup_at_the_cap_is_not_a_client(monkeypatch):
    monkeypatch.setattr(mcp_oauth, "MAX_CLIENT_RECORDS", 1)
    monkeypatch.setattr("app.auth.mcp_oauth_state.MAX_CLIENT_RECORDS", 1)
    cimd(monkeypatch, "none")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        assert (await register(client)).status_code == 201
        assert await stored_client(live, CIMD_ID) is None
        assert [key for key, _ in await _rows(CLIENT_COLLECTION)] != [CIMD_ID]


async def test_an_address_has_a_registration_quota():
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        for _ in range(REGISTRATIONS_PER_ADDRESS):
            assert (await register(client)).status_code == 201
        refused = await register(client)
        assert refused.status_code == 429
        assert refused.json()["code"] == error_codes.INGRESS_RATE_LIMITED
        assert 1 <= int(refused.headers["retry-after"]) <= REGISTRATION_WINDOW_SECONDS
        assert refused.headers["cache-control"] == "no-store"
        assert len(await _rows(CLIENT_COLLECTION)) == REGISTRATIONS_PER_ADDRESS


def test_the_quota_rolls_over_and_forgets_expired_windows():
    now = {"t": 0.0}
    quota = RegistrationQuota(clock=lambda: now["t"])
    for _ in range(REGISTRATIONS_PER_ADDRESS):
        assert quota.admit("10.0.0.1") is None
    assert quota.admit("10.0.0.1") == int(REGISTRATION_WINDOW_SECONDS)
    assert quota.admit("10.0.0.2") is None
    now["t"] += REGISTRATION_WINDOW_SECONDS
    assert quota.admit("10.0.0.1") is None
    # The table is bounded: past its size, expired windows are dropped first.
    from app.auth.mcp_oauth import REGISTRATION_QUOTA_ENTRIES

    now["t"] += REGISTRATION_WINDOW_SECONDS
    for i in range(REGISTRATION_QUOTA_ENTRIES):
        quota.admit(f"10.1.{i // 256}.{i % 256}")
    assert len(quota._windows) <= REGISTRATION_QUOTA_ENTRIES


# --- the cull ----------------------------------------------------------------------------


async def test_expired_rows_are_culled_at_registration_and_authorization():
    """The adapter reads an expired row as absent and leaves it; the two
    anonymous entry points that create rows with a lifetime delete them."""
    await _insert_expired(TRANSACTION_COLLECTION, "stale-transaction")
    await _insert_expired(CLIENT_COLLECTION, "stale-client")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        assert (await register(client)).status_code == 201
    keys = {key for key, _ in await _rows(TRANSACTION_COLLECTION)}
    assert "stale-transaction" not in keys
    keys = {key for key, _ in await _rows(CLIENT_COLLECTION)}
    assert "stale-client" not in keys


async def test_the_demand_cull_runs_at_most_once_per_interval_and_the_record_cull_per_record(
    monkeypatch,
):
    """Two culls, two shapes: the all-collection demand cull from the anonymous
    entry points runs at most once per interval; the client-collection cull
    runs where a record is created, every time (Codex #222 round 1, f2)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        proxy = getattr(live.state, MCP_OAUTH_ATTR).proxy
        calls: list[str | None] = []
        store = proxy._state_store

        async def counted(collection: str | None = None) -> int:
            calls.append(collection)
            return 0

        monkeypatch.setattr(store, "cull_expired", counted)
        for _ in range(3):
            assert (await register(client)).status_code == 201
    assert calls.count(None) == 1
    assert calls.count(CLIENT_COLLECTION) == 3


# --- the in-memory document cache ---------------------------------------------------------


def test_the_cimd_document_cache_forgets_its_oldest_entry_past_its_capacity():
    cache = BoundedCache(3)
    for i in range(5):
        cache[f"https://client.example/{i}"] = i
    assert list(cache) == [
        "https://client.example/2",
        "https://client.example/3",
        "https://client.example/4",
    ]
    cache["https://client.example/4"] = "updated"  # an update evicts nothing
    assert len(cache) == 3


async def test_the_proxy_installs_the_bounded_cache_on_fastmcps_fetcher():
    fake = FakeIdp()
    async with oauth_app(fake) as (live, _):
        proxy = getattr(live.state, MCP_OAUTH_ATTR).proxy
        cache = proxy._cimd_manager._fetcher._cache
        assert isinstance(cache, BoundedCache)
        assert cache.capacity == CIMD_CACHE_ENTRIES
        assert isinstance(proxy._client_store, ClientRecords)
        assert proxy._client_store._default_collection == CLIENT_COLLECTION
        assert MAX_CLIENT_RECORDS >= 64


# --- Codex #222 round 1, f2: a client materialised by a lookup alone --------------------


def _any_cimd(monkeypatch) -> None:
    """Play the CIMD fetch for any https client id: the token and revocation
    endpoints materialise a record for whatever URL authenticates as a client."""

    async def fetch(self, client_id_url: str):
        base = client_id_url.rsplit("/", 1)[0]
        return _cimd_document(client_id=client_id_url, redirect_uris=[f"{base}/callback"])

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)


@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_a_client_materialised_by_a_lookup_alone_rolls_over_within_the_cap(
    monkeypatch, endpoint
):
    """Neither `/mcp/token` nor `/mcp/revoke` reaches the registration guard
    or `authorize`, and both look a client up — materialising a CIMD record —
    so the physical table grew by a capped batch per expiry with no cull ever
    reached (Codex #222 round 1, f2). The cull lives where a record is created
    now: with the cap at two, two rows expire and two more are materialised,
    and the table holds two, not four."""
    monkeypatch.setattr(mcp_oauth, "MAX_CLIENT_RECORDS", 2)
    _any_cimd(monkeypatch)
    fake = FakeIdp()
    await _bind_owner()

    def client_id(i: int) -> str:
        return f"https://client{i}.example/client.json"

    def form(i: int) -> dict[str, str]:
        if endpoint == "token":
            return {
                "grant_type": "refresh_token",
                "refresh_token": "bogus",
                "client_id": client_id(i),
            }
        return {"token": "bogus", "client_id": client_id(i)}

    async with oauth_app(fake) as (_, client):
        for i in (1, 2):
            response = await client.post(f"/mcp/{endpoint}", data=form(i))
            assert response.status_code != 500, response.text
        assert {key for key, _ in await _rows(CLIENT_COLLECTION)} == {client_id(1), client_id(2)}
        async with get_sessionmaker()() as session:
            await session.execute(
                text(
                    "UPDATE mcp_oauth_state SET expires_at = now() - interval '1 day'"
                    " WHERE collection = :c"
                ),
                {"c": CLIENT_COLLECTION},
            )
            await session.commit()
        for i in (3, 4):
            response = await client.post(f"/mcp/{endpoint}", data=form(i))
            assert response.status_code != 500, response.text
    assert {key for key, _ in await _rows(CLIENT_COLLECTION)} == {client_id(3), client_id(4)}
