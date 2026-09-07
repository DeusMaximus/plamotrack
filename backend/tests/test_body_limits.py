"""Body budgets on the anonymous routes (§5.6, resource exhaustion; #221 item 1).

Every anonymous route that takes a body declares one in the route policy
registry (`RoutePolicy.max_body_bytes`); the pre-routing gate enforces it for
the app's routes and the protocol guards for the mount's, before any parser
holds a byte past it — from `Content-Length` when there is one, else while
reading. The bundled nginx duplicates it as `client_max_body_size` on the same
routes (`tests/test_ingress_generation.py`); the packaged behaviour is the
matrix's (`ingress_matrix.py`, `body_budget_rows`).
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app import error_codes
from app.auth.registry import (
    AUTH_BODY_LIMIT,
    AUTH_BODY_ROUTES,
    MCP_OAUTH_ROUTES,
    PROTOCOL_BODY_LIMIT,
    CredentialPolicy,
    build_route_index,
)
from app.main import app
from tests.oidc_fake import FakeIdp, oidc_app

pytestmark = pytest.mark.anyio

ORIGIN = {"Origin": "http://test"}
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def _json_of_size(size: int) -> bytes:
    """A syntactically valid JSON object padded with whitespace to `size` bytes."""
    core = b'{"password": "nope"}'
    assert size >= len(core)
    return core + b" " * (size - len(core))


async def _anon():
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    )


# --- the declaration ----------------------------------------------------------------


def test_every_anonymous_route_that_takes_a_body_declares_a_budget():
    """The invariant a new anonymous route cannot forget: a family-3 route with
    an unsafe verb is in `AUTH_BODY_ROUTES` and carries the family's budget;
    a family-8 route with `POST` carries the protocol budget; nothing else
    declares one. The static tuple is what the ingress render reads, so it is
    held equal to the live route table here."""
    index = build_route_index(app)
    unsafe_family_3 = {
        route.path
        for route in index.routes
        if (policy := index.policy_for(route.endpoint)) is not None
        and policy.family == 3
        and route.methods - {"GET", "HEAD", "OPTIONS"}
    }
    assert unsafe_family_3 == set(AUTH_BODY_ROUTES)
    for route in index.routes:
        policy = index.policy_for(route.endpoint)
        assert policy is not None
        expected = AUTH_BODY_LIMIT if route.path in AUTH_BODY_ROUTES else None
        assert policy.max_body_bytes == expected, route.path
        if policy.credential is CredentialPolicy.ANONYMOUS and route.methods - {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            assert policy.max_body_bytes is not None, route.path
    for path, policy in MCP_OAUTH_ROUTES.items():
        expected = PROTOCOL_BODY_LIMIT if "POST" in policy.methods else None
        assert policy.max_body_bytes == expected, path
    assert AUTH_BODY_LIMIT % 1024 == 0 and PROTOCOL_BODY_LIMIT % 1024 == 0


# --- the gate (the app's routes) -----------------------------------------------------


async def test_a_declared_length_past_the_budget_is_413_before_the_body_is_read():
    async with await _anon() as client:
        response = await client.post(
            "/auth/login",
            content=_json_of_size(AUTH_BODY_LIMIT + 1),
            headers={**ORIGIN, "Content-Type": "application/json"},
        )
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["code"] == error_codes.INGRESS_BODY_TOO_LARGE
    assert body["params"] == {"limit": AUTH_BODY_LIMIT}
    assert str(AUTH_BODY_LIMIT) in body["detail"]


async def test_a_body_exactly_at_the_budget_reaches_the_route():
    """The bound is the budget itself: one byte more is refused, the budget
    is not. The route then answers as it would — a wrong password's 403."""
    async with await _anon() as client:
        exact = await client.post(
            "/auth/login",
            content=_json_of_size(AUTH_BODY_LIMIT),
            headers={**ORIGIN, "Content-Type": "application/json"},
        )
    assert exact.status_code == 403
    assert exact.json()["code"] == error_codes.AUTH_LOGIN_FAILED


async def test_a_chunked_body_is_judged_while_it_is_read():
    """No `Content-Length`: the reader stops at the first chunk past the budget
    and holds nothing more; within it, the body is replayed whole."""

    async def chunks(size: int, chunk: int = 4096):
        payload = _json_of_size(size)
        for start in range(0, len(payload), chunk):
            yield payload[start : start + chunk]

    async with await _anon() as client:
        over = await client.post(
            "/auth/login",
            content=chunks(AUTH_BODY_LIMIT + 1),
            headers={**ORIGIN, "Content-Type": "application/json"},
        )
        assert over.status_code == 413
        assert "content-length" not in over.request.headers
        within = await client.post(
            "/auth/login",
            content=chunks(AUTH_BODY_LIMIT),
            headers={**ORIGIN, "Content-Type": "application/json"},
        )
    assert within.status_code == 403
    assert within.json()["code"] == error_codes.AUTH_LOGIN_FAILED


async def test_the_budget_is_the_routes_not_the_callers(anon_client):
    """Signed in or not, a body past the route's budget is refused — and a
    route with no budget is untouched by this layer: the owner's oversized
    write to a collection route is the parser's or the service's answer, never
    a 413 from the gate."""
    from tests.test_auth_local import _claim

    csrf = await _claim(anon_client)
    logout = await anon_client.post(
        "/auth/logout",
        content=b" " * (AUTH_BODY_LIMIT + 1),
        headers={**ORIGIN, "X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert logout.status_code == 413
    big_name = json.dumps({"name": "x" * (AUTH_BODY_LIMIT + 1)}).encode()
    retailer = await anon_client.post(
        "/retailers",
        content=big_name,
        headers={**ORIGIN, "X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert retailer.status_code != 413


# --- the protocol guards (the mount's routes) ----------------------------------------


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/mcp/token", "application/x-www-form-urlencoded"),
        ("/mcp/revoke", "application/x-www-form-urlencoded"),
        ("/mcp/authorize", "application/x-www-form-urlencoded"),
        ("/mcp/consent", "application/x-www-form-urlencoded"),
        ("/mcp/register", "application/json"),
        # The budget is judged before the media type: a body the endpoint
        # would refuse anyway is still never read whole.
        ("/mcp/token", "multipart/form-data; boundary=x"),
        ("/mcp/register", "text/plain"),
    ],
)
async def test_a_protocol_body_past_the_budget_is_413_in_the_envelope(path, content_type):
    fake = FakeIdp()
    async with oidc_app(fake) as (_, client):
        response = await client.post(
            path,
            content=b"a=" + b"b" * PROTOCOL_BODY_LIMIT,
            headers={"Content-Type": content_type},
        )
    assert response.status_code == 413, path
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["code"] == error_codes.INGRESS_BODY_TOO_LARGE
    assert body["params"] == {"limit": PROTOCOL_BODY_LIMIT}


async def test_a_protocol_body_within_the_budget_reaches_the_guard():
    """Within the budget the guard judges the request as before: the wrong
    media type is its own 400, an unknown client the SDK's."""
    fake = FakeIdp()
    async with oidc_app(fake) as (_, client):
        wrong_type = await client.post(
            "/mcp/token",
            content=b"grant_type=authorization_code",
            headers={"Content-Type": "text/plain"},
        )
        assert wrong_type.status_code == 400
        assert wrong_type.json()["error"] == "invalid_request"
        registration = await client.post(
            "/mcp/register",
            content=b'{"redirect_uris": ["http://localhost:1/cb"]}'
            + b" " * (PROTOCOL_BODY_LIMIT - 60),
            headers={"Content-Type": "application/json"},
        )
    assert registration.status_code != 413


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_more_form_fields_than_the_cap_are_refused_not_enumerated(method):
    from app.auth.mcp_oauth import MAX_FORM_FIELDS

    fields = "&".join(f"x{i}=1" for i in range(MAX_FORM_FIELDS + 1))
    fake = FakeIdp()
    async with oidc_app(fake) as (_, client):
        if method == "GET":
            response = await client.get(f"/mcp/authorize?{fields}")
        else:
            response = await client.post("/mcp/token", content=fields.encode(), headers=FORM)
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
    assert str(MAX_FORM_FIELDS) in response.json()["error_description"]


# --- the reader itself ----------------------------------------------------------------


async def test_a_declared_length_over_the_budget_reads_nothing():
    """The cheap half: with `Content-Length` past the budget the reader never
    asks for a byte; without the header it reads up to the first chunk past
    the budget and no further."""
    from app.auth.body import read_bounded

    asked: list[int] = []

    async def receive() -> dict:
        asked.append(1)
        return {"type": "http.request", "body": b"x" * 1024, "more_body": True}

    declared = {"type": "http", "headers": [(b"content-length", b"9000")]}
    assert await read_bounded(declared, receive, 8192) is None
    assert asked == []
    undeclared = {"type": "http", "headers": []}
    assert await read_bounded(undeclared, receive, 8192) is None
    assert len(asked) == 9  # 8 KiB admitted, the ninth chunk is the one past it
    malformed = {"type": "http", "headers": [(b"content-length", b"lots")]}
    asked.clear()
    assert await read_bounded(malformed, receive, 8192) is None
    assert len(asked) == 9  # a length that is not a number declares nothing


# --- Codex #222 round 1, f3: a disconnect is not a body ---------------------------------


def _scope(method: str, path: str, headers: dict[str, str], *, host: str) -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in {"host": host, **headers}.items()],
        "client": ("127.0.0.1", 40000),
        "server": (host, 80),
        "state": {},
    }


async def _abandoned(target_app, scope: dict, prefix: bytes) -> list[dict]:
    """The raw ASGI call: a syntactically complete prefix, declared longer and
    marked non-terminal, then the client's disconnect. Returns every message the
    app sent — which must be none."""
    messages = [
        {"type": "http.request", "body": prefix, "more_body": True},
        {"type": "http.disconnect"},
    ]

    async def receive() -> dict:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    sent: list[dict] = []

    async def send(message: dict) -> None:
        sent.append(message)

    await target_app(scope, receive, send)
    return sent


async def _session_rows() -> int:
    from sqlalchemy import func, select

    from app.db import get_sessionmaker
    from app.models import Session as SessionRow

    async with get_sessionmaker()() as session:
        return await session.scalar(select(func.count()).select_from(SessionRow))


async def test_a_login_body_abandoned_mid_way_opens_no_session_and_answers_nothing(anon_client):
    """Codex #222 round 1, f3: a complete, correct-password JSON prefix declared
    100 bytes longer and then abandoned was replayed as the whole body — 200
    and a second session row. The reader now raises on the disconnect and the
    gate returns without a response; no state moves."""
    from tests.test_auth_local import PASSWORD, _claim

    await _claim(anon_client)
    before = await _session_rows()
    prefix = json.dumps({"password": PASSWORD}).encode()
    scope = _scope(
        "POST",
        "/auth/login",
        {
            "content-type": "application/json",
            "content-length": str(len(prefix) + 100),
            "origin": "http://test",
        },
        host="test",
    )
    assert await _abandoned(app, scope, prefix) == []
    assert await _session_rows() == before


async def test_a_setup_body_abandoned_mid_way_claims_nothing(anon_client):
    from tests.test_auth_local import _issue_setup_token

    token = _issue_setup_token()
    prefix = json.dumps({"token": token, "password": "a-password"}).encode()
    scope = _scope(
        "POST",
        "/auth/setup",
        {
            "content-type": "application/json",
            "content-length": str(len(prefix) + 100),
            "origin": "http://test",
        },
        host="test",
    )
    assert await _abandoned(app, scope, prefix) == []
    assert (await anon_client.get("/auth/session")).json()["state"] == "unclaimed"


@pytest.mark.parametrize(
    ("path", "prefix", "content_type"),
    [
        ("/mcp/token", b"grant_type=authorization_code&code=abc", FORM["Content-Type"]),
        ("/mcp/register", b'{"redirect_uris": ["http://localhost:1/cb"]}', "application/json"),
        ("/mcp/consent", b"action=approve", FORM["Content-Type"]),
    ],
)
async def test_a_protocol_body_abandoned_mid_way_is_answered_nothing(path, prefix, content_type):
    fake = FakeIdp()
    async with oidc_app(fake) as (live, _):
        scope = _scope(
            "POST",
            path,
            {"content-type": content_type, "content-length": str(len(prefix) + 50)},
            host="localhost",
        )
        assert await _abandoned(live, scope, prefix) == []


async def test_the_reader_raises_on_a_disconnect_and_trusts_the_servers_framing():
    from app.auth.body import Disconnected, read_bounded

    async def abandoned():
        yield {"type": "http.request", "body": b"abc", "more_body": True}
        yield {"type": "http.disconnect"}

    async def short_but_terminal():
        yield {"type": "http.request", "body": b"abc", "more_body": False}

    for messages, expected in ((abandoned(), Disconnected), (short_but_terminal(), b"abc")):
        receive = messages.__anext__
        scope = {"type": "http", "headers": [(b"content-length", b"200")]}
        if expected is Disconnected:
            with pytest.raises(Disconnected):
                await read_bounded(scope, receive, 8192)
        else:
            assert await read_bounded(scope, receive, 8192) == expected
