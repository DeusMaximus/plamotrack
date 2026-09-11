"""The client records' bounds (#221 item 2; §5.6 resource exhaustion), and the
contract restated for FastMCP 4 (#242): the bounds describe dynamically
registered clients only.

`POST /mcp/register` is anonymous by protocol and used to mint a permanent row
per request, and the key-value adapter never physically deleted the rows whose
TTL had passed. Now a registration's record lives `UNLINKED_CLIENT_TTL_SECONDS`
until a grant links it, the collection is capped, an address has a registration
quota, and expired rows are culled from the anonymous entry points and where a
record is created. A CIMD client (Claude web, ChatGPT web) has no record to
bound: FastMCP 3 persisted one per URL ever presented as a client id, rewritten
on every lookup; FastMCP 4 resolves the client through its in-process document
cache on every lookup and stores nothing (`OAuthProxy.get_client`), so the
lifetime, the cap and the cull count registrations only, and what bounds the
CIMD side is the document cache, at `CIMD_CACHE_ENTRIES`. Two things follow,
probed at the end: a row a 0.4.0 instance stored for a CIMD client is a fallback
until its document is refreshed, then deleted; and once no row stands behind a
web client, the client's own exchanges wait for its document — a live grant
does not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastmcp.server.auth.cimd import CIMDFetcher, CIMDFetchError
from fastmcp.server.auth.oauth_proxy.models import ProxyDCRClient
from fastmcp.server.auth.ssrf import SSRFFetchError, SSRFFetchResponse
from pydantic import AnyUrl
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
from app.services import audit
from tests.oidc_fake import FakeIdp
from tests.test_mcp_oauth import (
    CIMD_CB,
    CIMD_ID,
    NATIVE_CB,
    _bind_owner,
    _cimd_document,
    _events,
    _pkce,
    _provider_refresh,
    _query,
    _state_rows,
    authorize,
    consent,
    idp_return,
    initialize,
    link,
    oauth_app,
    refresh,
    register,
    revoke,
)
from tests.test_mcp_oauth_clients import cimd, cimd_link, grant_records, stored_client

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


async def _expire_every_client_row() -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            text(
                "UPDATE mcp_oauth_state SET expires_at = now() - interval '1 day'"
                " WHERE collection = :c"
            ),
            {"c": CLIENT_COLLECTION},
        )
        await session.commit()


def _registration(client_id: str) -> ProxyDCRClient:
    """A registration's record, the shape `register_client` stores."""
    return ProxyDCRClient(
        client_id=client_id,
        client_secret=None,
        redirect_uris=[AnyUrl(NATIVE_CB)],
        grant_types=["authorization_code", "refresh_token"],
        scope="openid",
        token_endpoint_auth_method="none",
    )


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


async def test_a_cimd_client_is_stored_nowhere_before_or_after_its_link(monkeypatch):
    """A CIMD client is resolved from its document on every lookup and is a row
    nowhere (#242): not on the first lookup, not once a grant links it — the
    link keeps a *record*, and there is none to keep — and not on a lookup
    after that. FastMCP 3 wrote a row on the first lookup and rewrote it on
    every refresh; the lifetime and the cap below therefore describe
    registrations only."""
    cimd(monkeypatch, "none")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        found = await stored_client(live, CIMD_ID)
        assert found is not None and found.cimd_document is not None
        assert await _rows(CLIENT_COLLECTION) == []
        linked = await cimd_link(client, fake, None)
        assert linked["access_token"]
        assert grant_records(await _state_rows()), "the grant is recorded"
        assert await _rows(CLIENT_COLLECTION) == []
        found = await stored_client(live, CIMD_ID)
        assert found is not None and found.cimd_document is not None
        assert await _rows(CLIENT_COLLECTION) == []


async def test_a_permanent_record_stays_permanent_through_a_later_write():
    """The adapter's rule over the record's three states — absent, on the
    clock, permanent — for a writer that supplies no lifetime: a new record
    goes on the clock; a record on the clock stays on one; a permanent record
    stays permanent. FastMCP 4 has no such writer today (its registration is
    the new-record case, its only other write a delete), so this holds the rule
    at the seam for one it has not enumerated — the `GrantRecords` shape — where
    FastMCP 3's CIMD refresh used to be the writer that put a linked client's
    record back on the clock."""
    fake = FakeIdp()
    async with oauth_app(fake) as (live, _):
        records = getattr(live.state, MCP_OAUTH_ATTR).proxy._client_store
        assert isinstance(records, ClientRecords)
        await records.put(key="dcr-1", value=_registration("dcr-1"))
        assert dict(await _rows(CLIENT_COLLECTION))["dcr-1"] is not None, "new: on the clock"
        await records.put(key="dcr-1", value=_registration("dcr-1"))
        assert dict(await _rows(CLIENT_COLLECTION))["dcr-1"] is not None, "on the clock: still"
        await records.keep("dcr-1")
        assert dict(await _rows(CLIENT_COLLECTION))["dcr-1"] is None, "linked: permanent"
        await records.put(key="dcr-1", value=_registration("dcr-1"))
        assert dict(await _rows(CLIENT_COLLECTION))["dcr-1"] is None, "permanent: still"
        await records.put(key="dcr-2", value=_registration("dcr-2"))
        rows = dict(await _rows(CLIENT_COLLECTION))
        assert rows["dcr-2"] is not None, "a new record beside a permanent one: on the clock"
        await records.keep("dcr-3")
        assert "dcr-3" not in dict(await _rows(CLIENT_COLLECTION)), "keep creates nothing"


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


async def test_a_cimd_client_resolves_and_links_at_the_cap(monkeypatch):
    """The cap is the registrations' (#242): with the collection full, a
    further registration is refused and a CIMD client still resolves, still
    links, and adds no row. FastMCP 3's lookup wrote a row and met the cap
    there, so a flood of registrations locked the web clients out; the flood
    now costs them nothing."""
    monkeypatch.setattr(mcp_oauth, "MAX_CLIENT_RECORDS", 1)
    monkeypatch.setattr("app.auth.mcp_oauth_state.MAX_CLIENT_RECORDS", 1)
    cimd(monkeypatch, "none")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        registered = await register(client)
        assert registered.status_code == 201, registered.text
        assert (await register(client)).status_code == 503
        found = await stored_client(live, CIMD_ID)
        assert found is not None and found.cimd_document is not None
        linked = await cimd_link(client, fake, None)
        assert linked["access_token"]
        assert [key for key, _ in await _rows(CLIENT_COLLECTION)] == [
            registered.json()["client_id"]
        ]


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


def _any_cimd(monkeypatch) -> None:
    """Play the CIMD fetch for any https client id: the token and revocation
    endpoints resolve whatever URL authenticates as a client."""

    async def fetch(self, client_id_url: str):
        base = client_id_url.rsplit("/", 1)[0]
        return _cimd_document(client_id=client_id_url, redirect_uris=[f"{base}/callback"])

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)


@pytest.mark.parametrize(
    ("endpoint", "answer"),
    [("token", (401, "invalid_grant")), ("revoke", (200, None))],
    ids=["token", "revoke"],
)
async def test_a_lookup_alone_materialises_no_record(monkeypatch, endpoint, answer):
    """Neither `/mcp/token` nor `/mcp/revoke` reaches the registration guard
    or `authorize`, and both look a client up. Under FastMCP 3 that lookup
    wrote a CIMD record, so the physical table grew by a capped batch per
    expiry with no cull ever reached (Codex #222 round 1, f2), and the cull
    moved to where a record is created. Under FastMCP 4 the lookup writes
    nothing (#242): the client authenticates from its document, the endpoint
    answers on the token — `401 invalid_grant` for a refresh token this
    server never issued (FastMCP's token handler: the MCP specification's 401
    for an invalid or expired token, over RFC 6749 §5.2's 400); RFC 7009's
    200 for a revocation of one — and the collection is empty behind it. The
    cull at creation has one caller now, the registration (next)."""
    _any_cimd(monkeypatch)
    fake = FakeIdp()
    await _bind_owner()

    def form(i: int) -> dict[str, str]:
        client_id = f"https://client{i}.example/client.json"
        if endpoint == "token":
            return {"grant_type": "refresh_token", "refresh_token": "bogus", "client_id": client_id}
        return {"token": "bogus", "client_id": client_id}

    async with oauth_app(fake) as (_, client):
        for i in (1, 2):
            response = await client.post(f"/mcp/{endpoint}", data=form(i))
            assert response.status_code == answer[0], response.text
            if answer[1] is not None:
                assert response.json()["error"] == answer[1], response.text
        assert await _rows(CLIENT_COLLECTION) == []


async def test_a_registration_rolls_expired_records_over_within_the_cap(monkeypatch):
    """The cull where a record is created, on its one caller: with the cap at
    two and the demand cull already spent for the interval (the first
    registration ran it), two expired rows and two more registrations leave
    two rows in the table, not four — the expired ones went before the new
    ones were written (`ClientRecords.put`), so the physical size never
    exceeds the live cap."""
    monkeypatch.setattr(mcp_oauth, "MAX_CLIENT_RECORDS", 2)
    monkeypatch.setattr("app.auth.mcp_oauth_state.MAX_CLIENT_RECORDS", 2)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        first = []
        for _ in (1, 2):
            registered = await register(client)
            assert registered.status_code == 201, registered.text
            first.append(registered.json()["client_id"])
        assert {key for key, _ in await _rows(CLIENT_COLLECTION)} == set(first)
        await _expire_every_client_row()
        second = []
        for _ in (3, 4):
            registered = await register(client)
            assert registered.status_code == 201, registered.text
            second.append(registered.json()["client_id"])
    assert {key for key, _ in await _rows(CLIENT_COLLECTION)} == set(second)


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
    """The bound on the CIMD side is the document cache (#242): FastMCP 4
    bounds the fetcher's own store too (`MAX_CACHE_SIZE`), looser; the bound
    here is the tighter one, and the fetcher's store path writes through it."""
    fake = FakeIdp()
    async with oauth_app(fake) as (live, _):
        proxy = getattr(live.state, MCP_OAUTH_ATTR).proxy
        fetcher = proxy._cimd_manager._fetcher
        cache = fetcher._cache
        assert isinstance(cache, BoundedCache)
        assert cache.capacity == CIMD_CACHE_ENTRIES
        assert CIMD_CACHE_ENTRIES <= CIMDFetcher.MAX_CACHE_SIZE
        for i in range(CIMD_CACHE_ENTRIES + 1):
            fetcher._store_cache_entry(f"https://client.example/{i}", object())
        assert len(cache) == CIMD_CACHE_ENTRIES
        assert isinstance(proxy._client_store, ClientRecords)
        assert proxy._client_store._default_collection == CLIENT_COLLECTION
        assert MAX_CLIENT_RECORDS >= 64


# --- the transition: a row a 0.4.0 instance stored for a CIMD client (#242) ---------------

#: What a 0.4.0 instance wrote to `mcp_oauth_state` for a CIMD client on its
#: first lookup — `ProxyDCRClient.model_dump(mode="json")`, the adapter's
#: serialisation, under FastMCP 3.4.5 (captured 11/09/2026 in a 3.4.5 venv):
#: this suite's document, its name changed so the row and a fresh fetch can be
#: told apart. FastMCP 4.0.3's model adds `application_type`, with a default,
#: and nothing else, so the row validates as it is — through the adapter's
#: `raise_on_validation_error=True`, where a field the new model required
#: would have been a 500 on that client's every request.
ROW_FROM_0_4_0 = {
    "redirect_uris": None,
    "token_endpoint_auth_method": "none",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "scope": "openid",
    "client_name": "Some web client, as 0.4.0 fetched it",
    "client_uri": None,
    "logo_uri": None,
    "contacts": None,
    "tos_uri": None,
    "policy_uri": None,
    "jwks_uri": None,
    "jwks": None,
    "software_id": None,
    "software_version": None,
    "client_id": CIMD_ID,
    "client_secret": None,
    "client_id_issued_at": None,
    "client_secret_expires_at": None,
    "issuer": None,
    "allowed_redirect_uri_patterns": None,
    "cimd_document": {
        "client_id": CIMD_ID,
        "client_name": "Some web client, as 0.4.0 fetched it",
        "client_uri": None,
        "logo_uri": None,
        "redirect_uris": [CIMD_CB],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": "openid",
        "contacts": None,
        "tos_uri": None,
        "policy_uri": None,
        "jwks_uri": None,
        "jwks": None,
        "software_id": None,
        "software_version": None,
    },
    "cimd_fetched_at": 1757548800.0,
}


async def _seed_row_from_0_4_0(live, *, ttl: float | None) -> None:
    """The row as 0.4.0 left it: through the same encrypting storage, permanent
    when a grant had linked it, on the clock otherwise."""
    proxy = getattr(live.state, MCP_OAUTH_ATTR).proxy
    await proxy._client_storage.put(
        key=CIMD_ID, value=ROW_FROM_0_4_0, collection=CLIENT_COLLECTION, ttl=ttl
    )


def _unreachable(monkeypatch) -> None:
    """The fetcher failing as it does when the document's host cannot be
    reached (its cache holding nothing)."""

    async def fetch(self, client_id_url: str):
        raise CIMDFetchError(f"Failed to fetch CIMD document from {client_id_url}")

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)


@pytest.mark.parametrize("lifetime", ["linked", "unlinked"])
async def test_a_row_from_0_4_0_is_a_fallback_until_its_document_is_refreshed(
    monkeypatch, lifetime
):
    """Real 0.4.0 state loaded by this version, in the row's two lifetimes.
    While the document cannot be fetched the row answers — the client resolves
    from it, links on it, and the row stays; the first successful fetch answers
    from the document and deletes the row; and from then on an unreachable
    document leaves the client unknown, no row standing behind it. Bounded
    either way: a permanent row goes at the first refresh, a row on the clock
    at the first refresh or its expiry, whichever comes first."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        ttl = None if lifetime == "linked" else UNLINKED_CLIENT_TTL_SECONDS
        await _seed_row_from_0_4_0(live, ttl=ttl)
        _unreachable(monkeypatch)
        found = await stored_client(live, CIMD_ID)
        assert found is not None, "the row is the fallback"
        assert found.client_name == ROW_FROM_0_4_0["client_name"]
        rows = dict(await _rows(CLIENT_COLLECTION))
        assert CIMD_ID in rows
        assert (rows[CIMD_ID] is None) == (lifetime == "linked")
        linked = await cimd_link(client, fake, None)
        assert linked["access_token"], "the client links on the fallback"
        assert CIMD_ID in dict(await _rows(CLIENT_COLLECTION))
        cimd(monkeypatch, "none")
        found = await stored_client(live, CIMD_ID)
        assert found is not None
        assert found.client_name == "Some web client", "the fresh document answers"
        assert CIMD_ID not in dict(await _rows(CLIENT_COLLECTION)), "and the row is gone"
        _unreachable(monkeypatch)
        assert await stored_client(live, CIMD_ID) is None, "no row stands behind it now"


async def test_an_expired_row_from_0_4_0_is_no_fallback(monkeypatch):
    """The adapter reads an expired row as absent (#221 item 2), so a 0.4.0 row
    past its unlinked lifetime backs nothing: unreachable, the client is
    unknown; reachable, the fresh document answers and the row waits for the
    cull, which the next registration runs."""
    await _insert_expired(CLIENT_COLLECTION, CIMD_ID)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        _unreachable(monkeypatch)
        assert await stored_client(live, CIMD_ID) is None
        cimd(monkeypatch, "none")
        found = await stored_client(live, CIMD_ID)
        assert found is not None and found.client_name == "Some web client"
        assert CIMD_ID in {key for key, _ in await _rows(CLIENT_COLLECTION)}
        assert (await register(client)).status_code == 201
        assert CIMD_ID not in {key for key, _ in await _rows(CLIENT_COLLECTION)}


# --- a web client with no row behind it: its document's outage (#242) ---------------------


def _serve_document(monkeypatch, headers: dict[str, str] | None = None) -> None:
    """FastMCP's fetch primitive answering the document, with the real fetcher
    — its cache and its cache policy — in front of it."""
    body = _cimd_document().model_dump_json().encode()

    async def fetch_response(url: str, **_: object) -> SSRFFetchResponse:
        assert url == CIMD_ID
        return SSRFFetchResponse(content=body, status_code=200, headers=dict(headers or {}))

    monkeypatch.setattr("fastmcp.server.auth.cimd.ssrf_safe_fetch_response", fetch_response)


def _host_unreachable(monkeypatch) -> None:
    """The fetch primitive failing as it does when the document's host cannot
    be reached; the fetcher's cache decides whether that is seen."""

    async def fetch_response(url: str, **_: object) -> SSRFFetchResponse:
        raise SSRFFetchError(f"Failed to fetch {url}")

    monkeypatch.setattr("fastmcp.server.auth.cimd.ssrf_safe_fetch_response", fetch_response)


async def _cimd_link(client, fake: FakeIdp, **token_kw) -> dict:
    """The CIMD client's link with the provider's token response under the
    test's control (`expires_in` bounds the grant and decides the transparent
    refresh)."""
    verifier, challenge = _pkce()
    started = await authorize(client, CIMD_ID, CIMD_CB, challenge=challenge)
    assert started.status_code == 302, started.text
    approved = await consent(client, started.headers["location"])
    assert approved.status_code == 302, approved.text
    returned = await idp_return(client, fake, approved.headers["location"], **token_kw)
    assert returned.status_code == 302, returned.text
    exchanged = await client.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": _query(returned.headers["location"])["code"],
            "redirect_uri": CIMD_CB,
            "client_id": CIMD_ID,
            "code_verifier": verifier,
        },
    )
    assert exchanged.status_code == 200, exchanged.text
    return exchanged.json()


@pytest.mark.parametrize(
    ("headers", "during_outage"),
    [({}, 200), ({"Cache-Control": "no-store"}, 401)],
    ids=["kept-an-hour", "no-store"],
)
async def test_the_documents_own_cache_policy_decides_what_a_brief_outage_costs(
    monkeypatch, headers, during_outage
):
    """FastMCP's fetcher keeps a document for the freshness its response
    declared — an hour when the response declares nothing — and answers a
    lookup inside that window from memory; a document served `no-store` is
    never kept. So whether an outage of the document's host shorter than that
    window reaches the client's own exchanges in a running process is the
    document's call, not this server's: the field's value space is HTTP's, and
    its two ends are driven."""
    _serve_document(monkeypatch, headers)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await _cimd_link(client, fake)
        assert await _rows(CLIENT_COLLECTION) == []
        _host_unreachable(monkeypatch)
        fake.next_refresh = _provider_refresh(fake)
        refreshed = await refresh(client, CIMD_ID, tokens["refresh_token"])
        assert refreshed.status_code == during_outage, refreshed.text
        if during_outage != 200:
            assert refreshed.json()["error"] == "invalid_client"


async def test_after_a_restart_an_unreachable_document_refuses_the_clients_own_exchanges_only(
    monkeypatch,
):
    """No row stands behind a web client, and a fresh process holds no
    document, so while the document's host is unreachable the client cannot be
    resolved: its refresh exchange and its revocation are `401 invalid_client`
    at the client-authentication step — before any token is read, the provider
    asked nothing — spending nothing and ending nothing. The grant itself does
    not depend on the document: the access token keeps working and the
    transparent refresh behind a request goes to the provider, because that
    path never looks the client up. When the host answers again, the same
    refresh token and the same revocation succeed."""
    _serve_document(monkeypatch)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        # The upstream token inside the refresh threshold: the next request
        # behind this access token refreshes transparently.
        tokens = await _cimd_link(client, fake, expires_in=20)
    _host_unreachable(monkeypatch)
    fake.next_refresh = _provider_refresh(fake)
    async with oauth_app(fake) as (_, fresh):
        refused = await refresh(fresh, CIMD_ID, tokens["refresh_token"])
        assert refused.status_code == 401, refused.text
        assert refused.json()["error"] == "invalid_client"
        assert refused.headers.get_list("cache-control") == ["no-store"]
        refused = await revoke(fresh, CIMD_ID, tokens["refresh_token"])
        assert refused.status_code == 401, refused.text
        assert refused.json()["error"] == "invalid_client"
        assert not [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        assert grant_records(await _state_rows()), "the grant stands"
        assert not await _events(audit.MCP_GRANT_REVOKED)
        ok = await initialize(fresh, tokens["access_token"])
        assert ok.status_code == 200, ok.text[:300]
        transparent = [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        assert transparent, "the transparent refresh reached the provider"
        _serve_document(monkeypatch)
        fake.next_refresh = _provider_refresh(fake)
        refreshed = await refresh(fresh, CIMD_ID, tokens["refresh_token"])
        assert refreshed.status_code == 200, refreshed.text
        revoked = await revoke(fresh, CIMD_ID, refreshed.json()["refresh_token"])
        assert revoked.status_code == 200, revoked.text
    assert not grant_records(await _state_rows())
    assert len(await _events(audit.MCP_GRANT_REVOKED)) == 1
