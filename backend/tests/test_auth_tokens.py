"""Personal access tokens (§5.5 family 6 and the `pat:*` principals, §5.6; §5.8
T5/T6/T7/T10/T11; M6-4, #189).

Management runs under the suite's injected owner (`client`); the bearer tests
run on the **shipped** app as a real anonymous caller (`anon_client`) presenting
real tokens minted through the route, so the principal comes from the header
and nothing else. The MCP transport is exercised on a fresh enforced app with
its lifespan entered (the FastMCP session manager), driven by hand over the
streamable-HTTP protocol — initialize, initialized, tools/call — because the
transport is bearer-only and the in-memory client carries no header; the
in-memory client is used where the point is the tool-scope middleware alone,
with the pytest seam standing in for the bearer.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app import error_codes
from app.auth import credentials
from app.auth import tokens as token_format
from app.auth.budget import FailureBudget
from app.auth.mcp_auth import INJECTED_MCP_PRINCIPAL_ATTR
from app.auth.principal import Scope, pat
from app.auth.registry import MCP_TOOL_SCOPES
from app.auth.resolver import INVALID_TOKEN_CHALLENGE
from app.auth.setup_token import setup_token_state
from app.db import get_sessionmaker
from app.main import app, create_app
from app.mcp import mcp as mcp_server
from app.models import AuditEvent, PersonalAccessToken, Retailer
from app.routers.auth import BUDGET_ATTR
from app.services import audit
from app.services import tokens as token_service

pytestmark = pytest.mark.anyio

READ = ["collection:read"]
WRITE = ["collection:read", "collection:write"]
TOKEN_SHAPE = re.compile(r"^ptk_([0-9a-f]{12})_([A-Za-z0-9_-]{40,})$")
ORIGIN = {"Origin": "http://test"}
PASSWORD = "correct-horse-battery-staple"

LOOPBACK = ("127.0.0.1", 12345)
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


async def _mint(client, *, name="script", scopes=WRITE, expires_at=None) -> tuple[str, dict]:
    body = {"name": name, "scopes": scopes}
    if expires_at is not None:
        body["expires_at"] = expires_at
    resp = await client.post("/auth/tokens", json=body)
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    return payload["token"], payload


async def _audit_rows(event_type: str) -> list[AuditEvent]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.event_type == event_type)
            .order_by(AuditEvent.occurred_at)
        )
        return list(rows.scalars().all())


async def _row(token_id: str) -> PersonalAccessToken:
    async with get_sessionmaker()() as session:
        row = await session.get(PersonalAccessToken, uuid.UUID(token_id))
        assert row is not None
        return row


async def _mint_direct(*, name="script", scopes=(Scope.WRITE,), expires_at=None) -> tuple[str, str]:
    """Mint through the service — for tests on `anon_client`, which clears the
    injected owner the route-based `_mint` relies on. Returns `(raw, id)`."""
    async with get_sessionmaker()() as session:
        raw, row = await token_service.mint_token(
            session, name=name, scopes=set(scopes), expires_at=expires_at
        )
        return raw, str(row.id)


async def _revoke_direct(token_id: str) -> None:
    async with get_sessionmaker()() as session:
        await token_service.revoke_token(session, uuid.UUID(token_id))


async def _claim(client) -> str:
    """Claim the (reset-to-unclaimed) instance through the real route; the
    client keeps the owner cookie. Returns the CSRF token."""
    token = setup_token_state(app).issue()
    resp = await client.post(
        "/auth/setup", json={"token": token, "password": PASSWORD}, headers=ORIGIN
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]


# --- the token itself -------------------------------------------------------------


def test_the_token_shape_and_what_the_database_holds():
    public_id, raw = token_format.mint_raw()
    match = TOKEN_SHAPE.match(raw)
    assert match and match.group(1) == public_id
    assert token_format.public_id_of(raw) == public_id
    # The stored digest is of the whole token and never equals it.
    assert credentials.digest(raw) != raw and len(credentials.digest(raw)) == 64


@pytest.mark.parametrize(
    "raw",
    ["", "ptk", "ptk_", "ptk_abc_def", "ptk_0123456789ab", "ptk_0123456789ab_short", "nonsense"],
)
def test_a_string_not_shaped_like_a_token_names_no_public_id(raw):
    assert token_format.public_id_of(raw) is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("Bearer abc", "abc"),
        ("bearer abc", "abc"),  # the scheme is case-insensitive (RFC 7235 §2.1)
        ("BEARER  abc ", "abc"),
        ("Bearer", token_format.MALFORMED),
        ("Bearer ", token_format.MALFORMED),
        ("Basic dXNlcjpwYXNz", token_format.MALFORMED),
        ("Token abc", token_format.MALFORMED),
        ("", token_format.MALFORMED),
    ],
)
def test_only_a_bearer_header_carries_a_token(header, expected):
    headers = {} if header is None else {"authorization": header}
    assert token_format.bearer_from_headers(headers) is expected or (
        token_format.bearer_from_headers(headers) == expected
    )


def test_scopes_round_trip_and_write_implies_read_in_the_column():
    assert token_format.encode_scopes({Scope.READ}) == "collection:read"
    assert token_format.encode_scopes({Scope.WRITE}) == "collection:read,collection:write"
    assert token_format.decode_scopes("collection:read,collection:write") == frozenset(
        {Scope.READ, Scope.WRITE}
    )
    with pytest.raises(ValueError):
        token_format.decode_scopes("collection:read,everything")


# --- management (family 6): mint, list, revoke ------------------------------------


async def test_mint_shows_the_token_once_and_the_list_never_does(client):
    raw, minted = await _mint(client, name="  nightly sync  ", scopes=WRITE)
    match = TOKEN_SHAPE.match(raw)
    assert match, raw
    assert minted["token_prefix"] == match.group(1)
    assert minted["name"] == "nightly sync"  # trimmed
    assert minted["scopes"] == WRITE
    assert minted["expires_at"] is None and minted["revoked_at"] is None
    assert minted["last_used_at"] is None

    listed = await client.get("/auth/tokens")
    assert listed.status_code == 200
    assert listed.headers.get("cache-control") == "no-store"
    rows = listed.json()
    assert [r["id"] for r in rows] == [minted["id"]]
    assert "token" not in rows[0] and "secret_hash" not in rows[0]
    assert raw not in listed.text

    row = await _row(minted["id"])
    assert row.secret_hash == credentials.digest(raw)
    assert row.token_prefix == match.group(1)


async def test_the_mint_response_is_no_store(client):
    resp = await client.post("/auth/tokens", json={"name": "x", "scopes": READ})
    assert resp.status_code == 201
    assert resp.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize(
    ("requested", "stored"),
    [
        (["collection:read"], "collection:read"),
        (["collection:write"], "collection:read,collection:write"),
        (["collection:read", "collection:write"], "collection:read,collection:write"),
        (["collection:write", "collection:read"], "collection:read,collection:write"),
    ],
)
async def test_the_stored_grant_is_canonical(client, requested, stored):
    _raw, minted = await _mint(client, scopes=requested)
    assert (await _row(minted["id"])).scopes == stored
    assert minted["scopes"] == stored.split(",")


@pytest.mark.parametrize(
    ("scopes", "code"),
    [
        ([], error_codes.REQUEST_VALIDATION),  # the schema's min_length
        (["instance:admin"], error_codes.AUTH_TOKEN_SCOPE_INVALID),
        (["collection:read", "instance:admin"], error_codes.AUTH_TOKEN_SCOPE_INVALID),
        (["collection:write", "instance:admin"], error_codes.AUTH_TOKEN_SCOPE_INVALID),
        (["everything"], error_codes.REQUEST_VALIDATION),  # not a Scope at all
    ],
)
async def test_no_admin_and_no_unknown_scope_can_be_minted(client, scopes, code):
    resp = await client.post("/auth/tokens", json={"name": "x", "scopes": scopes})
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == code
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(func.count()).select_from(PersonalAccessToken)) == 0


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("", error_codes.REQUEST_VALIDATION),
        ("   ", error_codes.NAME_BLANK),
        ("\t\n", error_codes.NAME_BLANK),
        ("n" * 101, error_codes.VALUE_OUT_OF_RANGE),
    ],
)
async def test_a_token_needs_a_real_name(client, name, code):
    resp = await client.post("/auth/tokens", json={"name": name, "scopes": READ})
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == code


async def test_expiry_null_future_and_past(client):
    _raw, never = await _mint(client, expires_at=None)
    assert never["expires_at"] is None
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    _raw, dated = await _mint(client, expires_at=future)
    assert datetime.fromisoformat(dated["expires_at"]) == datetime.fromisoformat(future)
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    resp = await client.post("/auth/tokens", json={"name": "x", "scopes": READ, "expires_at": past})
    assert resp.status_code == 422
    assert resp.json()["code"] == error_codes.AUTH_TOKEN_EXPIRY_IN_PAST
    naive = await client.post(
        "/auth/tokens", json={"name": "x", "scopes": READ, "expires_at": "2099-01-01T00:00:00"}
    )
    assert naive.status_code == 422
    assert naive.json()["code"] == error_codes.SETTINGS_VALUE_INVALID


async def test_revoke_is_idempotent_and_an_unknown_id_is_404(client):
    _raw, minted = await _mint(client)
    first = await client.delete(f"/auth/tokens/{minted['id']}")
    assert first.status_code == 204
    revoked_at = (await _row(minted["id"])).revoked_at
    assert revoked_at is not None
    again = await client.delete(f"/auth/tokens/{minted['id']}")
    assert again.status_code == 204
    assert (await _row(minted["id"])).revoked_at == revoked_at  # not re-stamped
    listed = (await client.get("/auth/tokens")).json()
    assert listed[0]["revoked_at"] is not None
    missing = await client.delete(f"/auth/tokens/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == error_codes.AUTH_TOKEN_NOT_FOUND


async def test_mint_and_revoke_are_audited_without_the_secret(client):
    raw, minted = await _mint(client, scopes=READ)
    await client.delete(f"/auth/tokens/{minted['id']}")
    minted_rows = await _audit_rows(audit.TOKEN_MINTED)
    revoked_rows = await _audit_rows(audit.TOKEN_REVOKED)
    assert [(e.principal_kind, e.target, e.detail) for e in minted_rows] == [
        ("owner", "/auth/tokens", f"token={minted['id']} scopes=collection:read")
    ]
    assert [(e.principal_kind, e.target, e.detail) for e in revoked_rows] == [
        ("owner", f"/auth/tokens/{minted['id']}", f"token={minted['id']}")
    ]
    async with get_sessionmaker()() as session:
        for event in (await session.execute(select(AuditEvent))).scalars():
            assert raw not in (event.detail or "") and raw not in (event.target or "")


async def test_a_token_cannot_manage_tokens(anon_client):
    """Family 6 is `instance:admin` — the owner's session alone (T6). A write
    token, the strongest bearer there is, is 403 on every management route."""
    raw, token_id = await _mint_direct(scopes=(Scope.WRITE,))
    for method, path in (
        ("GET", "/auth/tokens"),
        ("POST", "/auth/tokens"),
        ("DELETE", f"/auth/tokens/{token_id}"),
    ):
        resp = await anon_client.request(
            method, path, headers=_bearer(raw), json={"name": "x", "scopes": READ}
        )
        assert resp.status_code == 403, (method, path, resp.text)
        assert resp.json()["code"] == error_codes.AUTH_FORBIDDEN
    # Nothing was minted or revoked by the attempt.
    assert (await _row(token_id)).revoked_at is None
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(func.count()).select_from(PersonalAccessToken)) == 1


# --- the bearer on REST (families 4/5/6, and 2/3) ---------------------------------


async def test_a_read_token_reads_and_cannot_write(anon_client):
    raw, _ = await _mint_direct(scopes=(Scope.READ,))
    assert (await anon_client.get("/kits", headers=_bearer(raw))).status_code == 200
    denied = await anon_client.post("/retailers", json={"name": "Read Only"}, headers=_bearer(raw))
    assert denied.status_code == 403
    assert denied.json()["code"] == error_codes.AUTH_FORBIDDEN
    settings = await anon_client.patch(
        "/settings", json={"time_zone": "Australia/Sydney"}, headers=_bearer(raw)
    )
    assert settings.status_code == 403
    assert settings.json()["code"] == error_codes.AUTH_FORBIDDEN


async def test_a_write_token_writes_without_origin_or_csrf_but_is_not_admin(anon_client):
    """A bearer-borne write owes neither an Origin nor the session-bound CSRF
    token (§5.6: those are the cookie's controls); and it is still not admin."""
    raw, _ = await _mint_direct(scopes=(Scope.WRITE,))
    created = await anon_client.post(
        "/retailers", json={"name": f"Bearer {uuid.uuid4().hex[:6]}"}, headers=_bearer(raw)
    )
    assert created.status_code == 201, created.text
    settings = await anon_client.patch(
        "/settings", json={"time_zone": "Australia/Sydney"}, headers=_bearer(raw)
    )
    assert settings.status_code == 403
    assert settings.json()["code"] == error_codes.AUTH_FORBIDDEN


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/auth/login"), ("POST", "/auth/logout"), ("POST", "/auth/setup")],
)
async def test_a_token_is_refused_on_the_auth_actions(anon_client, method, path):
    """Family 3 (§5.5): a token cannot log in, log out or claim — 403, not the
    action's own answer."""
    raw, _ = await _mint_direct(scopes=(Scope.WRITE,))
    resp = await anon_client.request(
        method,
        path,
        headers={**_bearer(raw), **ORIGIN},
        json={"password": PASSWORD, "token": "irrelevant"},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == error_codes.AUTH_FORBIDDEN


async def test_the_session_read_admits_a_token_and_reports_the_instance_state(anon_client):
    raw, _ = await _mint_direct(scopes=(Scope.WRITE,))
    resp = await anon_client.get("/auth/session", headers=_bearer(raw))
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "unclaimed"  # the suite's instance is unclaimed; never "owner"
    assert body["csrf_token"] is None
    await _claim(anon_client)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as fresh:
        body = (await fresh.get("/auth/session", headers=_bearer(raw))).json()
    assert body["state"] == "anonymous"
    assert body["csrf_token"] is None


async def test_liveness_admits_a_valid_bearer(anon_client):
    raw, _ = await _mint_direct(scopes=(Scope.READ,))
    assert (await anon_client.get("/healthz", headers=_bearer(raw))).status_code == 200


async def test_a_bearer_beside_a_cookie_is_decided_as_a_bearer(anon_client):
    raw, _ = await _mint_direct(scopes=(Scope.WRITE,))
    await _claim(anon_client)  # the client now carries the owner cookie
    # No CSRF token, no Origin — a cookie-borne write would be 403; the bearer
    # makes the request bearer-borne and the write lands.
    created = await anon_client.post(
        "/retailers", json={"name": f"Both {uuid.uuid4().hex[:6]}"}, headers=_bearer(raw)
    )
    assert created.status_code == 201, created.text
    # And a *failing* bearer beside a valid cookie is 401 — the cookie is not
    # consulted once a bearer was presented (§5.5, no silent downgrade).
    wrong = await anon_client.get("/kits", headers=_bearer(_wrong_secret(raw)))
    assert wrong.status_code == 401
    assert wrong.json()["code"] == error_codes.AUTH_BEARER_INVALID
    # The cookie alone still works: it was never revoked.
    assert (await anon_client.get("/kits")).status_code == 200


async def test_a_token_in_the_query_string_is_not_a_credential(anon_client):
    raw, _ = await _mint_direct(scopes=(Scope.WRITE,))
    resp = await anon_client.get("/kits", params={"access_token": raw})
    assert resp.status_code == 401
    assert resp.json()["code"] == error_codes.AUTH_UNAUTHENTICATED  # anon, not "invalid"
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_an_anonymous_401_carries_the_bearer_challenge(anon_client):
    resp = await anon_client.get("/kits")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


async def test_the_form_login_401s_carry_no_challenge(anon_client):
    """The challenge belongs to the bearer boundary. A wrong setup token and a
    wrong password are 401s from routes that *refuse* a bearer (family 3), so
    advertising `Bearer` there would name a credential the route cannot take
    (Codex #202 round 1, f2) — pinned as the decision, not left to a default."""
    setup_token_state(app).issue()
    wrong_token = await anon_client.post(
        "/auth/setup", json={"token": "not-it", "password": PASSWORD}, headers=ORIGIN
    )
    assert wrong_token.status_code == 401
    assert wrong_token.json()["code"] == error_codes.AUTH_SETUP_TOKEN_INVALID
    assert "www-authenticate" not in wrong_token.headers
    setattr(app.state, BUDGET_ATTR, FailureBudget())
    await _claim(anon_client)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as fresh:
        wrong_password = await fresh.post(
            "/auth/login", json={"password": "not-the-password"}, headers=ORIGIN
        )
    assert wrong_password.status_code == 401
    assert wrong_password.json()["code"] == error_codes.AUTH_LOGIN_FAILED
    assert "www-authenticate" not in wrong_password.headers


async def test_last_used_is_touched_on_use_and_not_on_failure(anon_client):
    raw, token_id = await _mint_direct(scopes=(Scope.READ,))
    assert (await _row(token_id)).last_used_at is None
    await anon_client.get("/kits", headers=_bearer(_wrong_secret(raw)))
    assert (await _row(token_id)).last_used_at is None
    before = datetime.now(UTC)
    assert (await anon_client.get("/kits", headers=_bearer(raw))).status_code == 200
    touched = (await _row(token_id)).last_used_at
    assert touched is not None and touched >= before - timedelta(seconds=5)


# --- presented and failed: one answer for every reason (T7, T11) --------------------


def _wrong_secret(raw: str) -> str:
    public_id = token_format.public_id_of(raw)
    return f"ptk_{public_id}_{'A' * 43}"


async def _expire(token_id: str) -> None:
    async with get_sessionmaker()() as session:
        row = await session.get(PersonalAccessToken, uuid.UUID(token_id))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def _failures() -> dict[str, dict[str, str]]:
    """Every failure kind as the headers a client would send: an unknown id
    (right shape, no row), a wrong secret (real id), malformed strings, the
    wrong scheme, an empty bearer, a revoked token and an expired one."""
    live, _ = await _mint_direct()
    revoked_raw, revoked_id = await _mint_direct()
    await _revoke_direct(revoked_id)
    expired_raw, expired_id = await _mint_direct()
    await _expire(expired_id)
    return {
        "unknown id": _bearer(f"ptk_{'0' * 12}_{'B' * 43}"),
        "wrong secret": _bearer(_wrong_secret(live)),
        "malformed": _bearer("ptk_not-a-token"),
        "not shaped at all": _bearer("nonsense"),
        "wrong scheme": {"Authorization": "Basic dXNlcjpwYXNz"},
        "empty bearer": {"Authorization": "Bearer "},
        "revoked": _bearer(revoked_raw),
        "expired": _bearer(expired_raw),
    }


@pytest.mark.parametrize("path", ["/kits", "/auth/session", "/healthz", "/auth/tokens"])
async def test_every_failed_bearer_is_the_same_401_on_every_route(anon_client, path):
    """Presented and failed → 401 with `error="invalid_token"`, the anonymous
    families included (§5.5), and byte-identical bodies across the reasons (T11)."""
    bodies = {}
    for reason, headers in (await _failures()).items():
        resp = await anon_client.get(path, headers=headers)
        assert resp.status_code == 401, (reason, path, resp.text)
        assert resp.headers["www-authenticate"] == INVALID_TOKEN_CHALLENGE, reason
        assert resp.headers.get("cache-control") == "no-store" or path == "/healthz"
        bodies[reason] = resp.json()
    assert len({json.dumps(b, sort_keys=True) for b in bodies.values()}) == 1, bodies
    assert next(iter(bodies.values()))["code"] == error_codes.AUTH_BEARER_INVALID


async def test_a_failed_bearer_is_not_a_login_attempt(anon_client):
    """A stale bearer on `POST /auth/login` is 401 `bearer_invalid` — and
    retrying without it enters the normal login flow (§5.5)."""
    raw, _ = await _mint_direct()
    stale = await anon_client.post(
        "/auth/login",
        json={"password": PASSWORD},
        headers={**_bearer(_wrong_secret(raw)), **ORIGIN},
    )
    assert stale.status_code == 401
    assert stale.json()["code"] == error_codes.AUTH_BEARER_INVALID
    assert await _audit_rows(audit.LOGIN_FAILED) == []
    # Without it: the instance is unclaimed, so the login's own 401 — a
    # different code, from the login flow.
    plain = await anon_client.post("/auth/login", json={"password": PASSWORD}, headers=ORIGIN)
    assert plain.status_code == 401
    assert plain.json()["code"] == error_codes.AUTH_LOGIN_FAILED


async def test_use_after_revoke_is_audited_even_though_the_request_is_refused(anon_client):
    raw, token_id = await _mint_direct(scopes=(Scope.WRITE,))
    await _revoke_direct(token_id)
    resp = await anon_client.post("/retailers", json={"name": "Ghost"}, headers=_bearer(raw))
    assert resp.status_code == 401
    rows = await _audit_rows(audit.TOKEN_USE_AFTER_REVOKE)
    assert [(e.principal_kind, e.principal_subject, e.target, e.detail) for e in rows] == [
        ("pat:write", token_id, "/retailers", f"token={token_id}")
    ]
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(func.count()).select_from(Retailer)) == 0
    # A wrong secret against the revoked id is a guess, not a leak: no row.
    await anon_client.get("/kits", headers=_bearer(_wrong_secret(raw)))
    assert len(await _audit_rows(audit.TOKEN_USE_AFTER_REVOKE)) == 1


async def test_an_expired_token_is_refused_without_a_leak_row(anon_client):
    raw, token_id = await _mint_direct(scopes=(Scope.WRITE,))
    await _expire(token_id)
    assert (await anon_client.get("/kits", headers=_bearer(raw))).status_code == 401
    assert await _audit_rows(audit.TOKEN_USE_AFTER_REVOKE) == []


async def test_a_future_expiry_still_admits(anon_client):
    future = datetime.now(UTC) + timedelta(hours=1)
    raw, _ = await _mint_direct(scopes=(Scope.READ,), expires_at=future)
    assert (await anon_client.get("/kits", headers=_bearer(raw))).status_code == 200


def _spy_compare_digest(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    real = credentials.hmac.compare_digest

    def spying(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(credentials.hmac, "compare_digest", spying)
    return calls


async def test_an_unknown_id_and_a_wrong_secret_do_the_same_compare(monkeypatch):
    """T11 by construction: the compare is `compare_digest` on the digests, and
    an id that names no row compares against `DUMMY_DIGEST` rather than
    returning early."""
    raw, token_id = await _mint_direct(scopes=(Scope.READ,))
    stored = (await _row(token_id)).secret_hash
    calls = _spy_compare_digest(monkeypatch)
    async with get_sessionmaker()() as session:
        unknown = await token_service.resolve_bearer(session, f"ptk_{'0' * 12}_{'B' * 43}")
        wrong = await token_service.resolve_bearer(session, _wrong_secret(raw))
        right = await token_service.resolve_bearer(session, raw)
    assert (unknown.ok, unknown.reason) == (False, "unknown")
    assert (wrong.ok, wrong.reason) == (False, "mismatch")
    assert right.ok and right.principal.label == "pat:read"
    assert [expected for _presented, expected in calls] == [
        token_format.DUMMY_DIGEST,
        stored,
        stored,
    ]


# --- MCP (T5: bearer only, never a cookie; T6: per-tool scope over HTTP) ------------


@asynccontextmanager
async def _enforced_mcp():
    """A fresh enforced app with its lifespan entered (the FastMCP session
    manager), as an ASGI client from a loopback peer with an allowed Host."""
    live = create_app(authorization=True)
    async with live.router.lifespan_context(live):
        transport = ASGITransport(app=live, client=LOOPBACK, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000", headers={"Host": "localhost"}
        ) as client:
            yield client


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test_auth_tokens", "version": "0"},
    },
}


def _sse_json(text: str) -> list[dict]:
    return [json.loads(line[5:].strip()) for line in text.splitlines() if line.startswith("data:")]


async def _mcp_call_tool(client, headers: dict[str, str], name: str, arguments: dict) -> dict:
    """Drive the streamable-HTTP protocol by hand: initialize, the initialized
    notification, then `tools/call`. Returns the JSON-RPC result."""
    init = await client.post("/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **headers})
    assert init.status_code == 200, init.text
    session_id = init.headers["mcp-session-id"]
    common = {**MCP_HEADERS, **headers, "mcp-session-id": session_id}
    ack = await client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=common,
    )
    assert ack.status_code == 202, ack.text
    call = await client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=common,
    )
    assert call.status_code == 200, call.text
    messages = [m for m in _sse_json(call.text) if m.get("id") == 2]
    assert messages, call.text
    return messages[-1]["result"]


async def test_mcp_takes_a_bearer_and_never_a_cookie(anon_client):
    """T5. No credential → the SDK's 401 with `WWW-Authenticate: Bearer`; the
    owner's valid session cookie (CSRF token and all) → the same 401 — the
    transport does not parse cookies; the same request with a PAT → 200."""
    raw, _ = await _mint_direct(scopes=(Scope.READ,))
    csrf = await _claim(anon_client)
    cookie = "; ".join(f"{k}={v}" for k, v in anon_client.cookies.items())
    assert cookie
    async with _enforced_mcp() as mcp_client:
        bare = await mcp_client.post("/mcp/", json=INITIALIZE, headers=MCP_HEADERS)
        assert bare.status_code == 401
        # RFC 6750 §3.1: an absent credential earns the bare challenge — the same
        # word the REST dependency answers with — and no error attribute.
        assert bare.headers["www-authenticate"] == "Bearer"
        assert bare.headers.get("cache-control") == "no-store"
        with_cookie = await mcp_client.post(
            "/mcp/",
            json=INITIALIZE,
            # Everything a same-origin browser write would carry — and the
            # Origin is one the guard admits (loopback to loopback).
            headers={
                **MCP_HEADERS,
                "Cookie": cookie,
                "X-CSRF-Token": csrf,
                "Origin": "http://127.0.0.1:8000",
            },
        )
        assert with_cookie.status_code == 401
        assert with_cookie.headers["www-authenticate"] == "Bearer"  # nothing was presented
        assert "mcp-session-id" not in with_cookie.headers
        with_token = await mcp_client.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(raw)}
        )
        assert with_token.status_code == 200
        assert with_token.headers["content-type"].startswith("text/event-stream")


@pytest.mark.parametrize(
    "form",
    ["Bearer {t}", "bearer {t}", "Bearer  {t}", "Bearer {t} ", "BEARER   {t}"],
)
async def test_every_accepted_header_form_is_accepted_on_both_surfaces(anon_client, form):
    """The single-parser invariant reaches the wire on both sides (Codex #202
    round 1, f1): FastMCP's bearer backend drops exactly one space after the
    scheme and hands the rest over, so `Bearer  <token>` was 200 on REST and 401
    on MCP until the shared helper normalised the value. Every form the REST
    parser accepts must open an MCP session too."""
    raw, _ = await _mint_direct(scopes=(Scope.READ,))
    headers = {"Authorization": form.format(t=raw)}
    assert (await anon_client.get("/kits", headers=headers)).status_code == 200, form
    async with _enforced_mcp() as mcp_client:
        resp = await mcp_client.post("/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **headers})
        assert resp.status_code == 200, (form, resp.status_code, resp.text)
        assert "mcp-session-id" in resp.headers


async def test_mcp_refuses_a_failed_bearer_the_same_way():
    async with _enforced_mcp() as mcp_client:
        for reason, headers in (await _failures()).items():
            resp = await mcp_client.post(
                "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **headers}
            )
            assert resp.status_code == 401, (reason, resp.text)
            # Presented and failed: the RFC 6750 `invalid_token` form, as on REST.
            assert resp.headers["www-authenticate"].startswith('Bearer error="invalid_token"'), (
                reason,
                resp.headers["www-authenticate"],
            )
            assert resp.headers.get("cache-control") == "no-store", reason


async def test_mcp_use_after_revoke_is_audited(client):
    raw, minted = await _mint(client, scopes=READ)
    await client.delete(f"/auth/tokens/{minted['id']}")
    async with _enforced_mcp() as mcp_client:
        resp = await mcp_client.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(raw)}
        )
        assert resp.status_code == 401
    rows = await _audit_rows(audit.TOKEN_USE_AFTER_REVOKE)
    assert [(e.principal_kind, e.principal_subject, e.target) for e in rows] == [
        ("pat:read", minted["id"], "/mcp/")
    ]


async def test_mcp_tool_scope_over_http(client):
    """T6 on the wire: a read token lists but cannot create; a write token
    creates. The refusal names the scope, before the service runs."""
    read_raw, _ = await _mint(client, scopes=READ)
    write_raw, _ = await _mint(client, scopes=WRITE)
    name = f"MCP Bearer {uuid.uuid4().hex[:6]}"
    async with _enforced_mcp() as mcp_client:
        listed = await _mcp_call_tool(mcp_client, _bearer(read_raw), "list_retailers", {})
        assert listed.get("isError") is not True
        refused = await _mcp_call_tool(
            mcp_client, _bearer(read_raw), "create_retailer", {"retailer": {"name": name}}
        )
        assert refused.get("isError") is True, refused
        text = " ".join(c.get("text", "") for c in refused["content"])
        assert "collection:write is required to call create_retailer" in text
        assert "collection:read" in text
        created = await _mcp_call_tool(
            mcp_client, _bearer(write_raw), "create_retailer", {"retailer": {"name": name}}
        )
        assert created.get("isError") is not True, created
    async with get_sessionmaker()() as session:
        names = (await session.execute(select(Retailer.name))).scalars().all()
    assert names == [name]


# --- the tool-scope middleware alone (in-memory, T6) --------------------------------

#: The write tools, as a literal: the matrix drives every one (rule 8 — not
#: derived from the map under test); the equality below is the drift guard.
WRITE_TOOLS = [
    "create_kit",
    "update_kit_status",
    "update_kit",
    "create_catalog_tool",
    "create_catalog_consumable",
    "create_catalog_upgrade",
    "create_catalog_display",
    "create_retailer",
    "update_retailer",
    "create_order",
    "update_order",
    "mark_order_received",
    "mark_order_shipped",
    "adjust_stock",
    "update_catalog_tool",
    "update_catalog_consumable",
    "update_catalog_upgrade",
    "update_catalog_display",
    "apply_upgrade",
    "withdraw_upgrade_application",
]

READ_CALLS = [
    ("get_meta", {}),
    ("list_kits", {}),
    ("list_kit_series", {}),
    ("search_catalog", {"query": "cement"}),
    ("list_catalog_items", {"item_type": "tool"}),
    ("list_catalog_categories", {"item_type": "tool"}),
    ("list_retailers", {}),
    ("list_orders", {}),
]


def test_the_literal_write_list_matches_the_registry():
    assert set(WRITE_TOOLS) == {n for n, s in MCP_TOOL_SCOPES.items() if s is Scope.WRITE}
    assert {n for n, _ in READ_CALLS} <= {n for n, s in MCP_TOOL_SCOPES.items() if s is Scope.READ}


def _inject_mcp(principal) -> None:
    if principal is None:
        if hasattr(mcp_server, INJECTED_MCP_PRINCIPAL_ATTR):
            delattr(mcp_server, INJECTED_MCP_PRINCIPAL_ATTR)
    else:
        setattr(mcp_server, INJECTED_MCP_PRINCIPAL_ATTR, principal)


@pytest.mark.parametrize("tool", WRITE_TOOLS)
async def test_every_write_tool_refuses_a_read_grant(tool):
    """`pat:read` on every write tool → a tool error naming the scope (T6) —
    raised before the arguments are even looked at, which the positive control
    shows: the same empty call under `pat:write` fails on its *arguments*, not
    on scope."""
    _inject_mcp(pat(write=False))
    async with Client(mcp_server) as c:
        with pytest.raises(ToolError) as refused:
            await c.call_tool(tool, {})
    assert f"collection:write is required to call {tool}" in str(refused.value)
    _inject_mcp(pat(write=True))
    async with Client(mcp_server) as c:
        with pytest.raises(ToolError) as control:
            await c.call_tool(tool, {})
    assert "collection:write is required" not in str(control.value)


@pytest.mark.parametrize(("tool", "arguments"), READ_CALLS)
async def test_every_read_tool_serves_a_read_grant(tool, arguments):
    _inject_mcp(pat(write=False))
    async with Client(mcp_server) as c:
        result = await c.call_tool(tool, arguments)
    assert result.is_error is False


async def test_a_refused_write_tool_touches_nothing():
    _inject_mcp(pat(write=False))
    async with Client(mcp_server) as c:
        with pytest.raises(ToolError):
            await c.call_tool("create_retailer", {"retailer": {"name": "Refused"}})
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(func.count()).select_from(Retailer)) == 0


async def test_in_memory_calls_with_no_principal_are_refused():
    """Fail closed: with neither a verified bearer nor the pytest seam, a tool
    call is refused — the seam is opt-in, never a default."""
    _inject_mcp(None)
    async with Client(mcp_server) as c:
        with pytest.raises(ToolError) as refused:
            await c.call_tool("list_kit_series", {})
    assert "Authentication required" in str(refused.value)


# --- T10: nothing secret in the logs -------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage() + " " + repr(record.args))


async def test_a_full_token_run_leaves_no_secret_in_the_logs(anon_client):
    """Every logger re-enabled (alembic's `fileConfig` disables the app's at
    session start), and the capture handler attached to **every** logger, not
    only root — uvicorn's `uvicorn` and `uvicorn.access` are non-propagating
    under the shipped configuration, so a root-only capture would read green
    past an access line (Codex #202 round 1, f3) — at DEBUG for the whole run:
    mint, a REST read, an MCP initialize and tool call, a failed bearer, a
    revoke, a use-after-revoke. Then: no line carries the token, the owner
    password or the session cookie, and no audit row does either.

    What this proves is bounded by the transport: under ASGITransport there is
    no uvicorn access log and no nginx, so the request line is not exercised
    here at all. The packaged-stack proof is CI's log scan after the matrix
    (`.github/workflows/ci.yml`), and the reason the matrix's query-string row
    carries a fake token."""
    loggers = [
        lg for lg in logging.root.manager.loggerDict.values() if isinstance(lg, logging.Logger)
    ]
    was_disabled = {lg: lg.disabled for lg in loggers}
    levels = {lg: lg.level for lg in loggers}
    capture = _Capture()
    for lg in loggers:
        lg.disabled = False
        lg.setLevel(logging.DEBUG)
        lg.addHandler(capture)
    root_level = logging.root.level
    logging.root.addHandler(capture)
    logging.root.setLevel(logging.DEBUG)
    try:
        raw, token_id = await _mint_direct(name="log grep", scopes=(Scope.WRITE,))
        csrf = await _claim(anon_client)
        cookie_values = list(anon_client.cookies.values())
        assert (await anon_client.get("/kits", headers=_bearer(raw))).status_code == 200
        async with _enforced_mcp() as mcp_client:
            result = await _mcp_call_tool(
                mcp_client, _bearer(raw), "create_retailer", {"retailer": {"name": "Logged"}}
            )
            assert result.get("isError") is not True
        assert (
            await anon_client.get("/kits", headers=_bearer(_wrong_secret(raw)))
        ).status_code == 401
        await _revoke_direct(token_id)
        assert (await anon_client.get("/kits", headers=_bearer(raw))).status_code == 401
    finally:
        logging.root.removeHandler(capture)
        logging.root.setLevel(root_level)
        for lg, disabled in was_disabled.items():
            lg.removeHandler(capture)
            lg.setLevel(levels[lg])
            lg.disabled = disabled
    assert capture.lines, "nothing was logged at all — the capture is broken"
    secrets_ = [raw, PASSWORD, csrf, *cookie_values]
    for line in capture.lines:
        for secret in secrets_:
            assert secret not in line, line
    async with get_sessionmaker()() as session:
        events = (await session.execute(select(AuditEvent))).scalars().all()
    assert events
    for event in events:
        for secret in secrets_:
            assert secret not in (event.detail or "")
            assert secret not in (event.target or "")


async def test_the_open_mount_still_refuses_tool_calls_without_a_bearer():
    """Fail closed on the wire even where no verifier sits in front: the pre-auth
    app (`create_app()`, the harnesses) mounts the transport open, so an HTTP
    request reaches the tool-scope middleware with no access token — and the
    pytest seam, set here to the owner, must not be consulted for a request
    that came over HTTP. Initialize succeeds (the mount is open); the call is
    refused."""
    from app.auth import owner

    _inject_mcp(owner())
    live = create_app()  # authorization off: the mount is open
    async with live.router.lifespan_context(live):
        transport = ASGITransport(app=live, client=LOOPBACK, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000", headers={"Host": "localhost"}
        ) as client:
            result = await _mcp_call_tool(client, {}, "list_kit_series", {})
    assert result.get("isError") is True, result
    text = " ".join(c.get("text", "") for c in result["content"])
    assert "Authentication required" in text
