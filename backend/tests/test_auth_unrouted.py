"""The pre-routing gate (§5.5 family 13; §5.9 item 3(b); #204).

Two disclosures the app-level dependency could not close because it runs after
Starlette has routed and FastAPI has decoded the body: an unrouted path or a
wrong verb answered 404/405 to an anonymous caller (with an `Allow` header
naming the route's verbs), and a malformed JSON body to a scoped route answered
the parser's 422 before any dependency ran. The gate resolves the principal
once, ahead of both, and refuses `anon` wherever the router would have said
404, 405 or the dependency's 401.

Axes, per the checklist: the **request kind** (unrouted, non-canonical
spelling, wrong verb, malformed body, the mount, the anonymous families' own
refusals) × the **principal** (`anon`, the owner, both token scopes, a
presented-and-failed bearer, a stale cookie) — every anonymous refusal is the
401 envelope with the bare `Bearer` challenge and `no-store`, and every
authenticated principal keeps the framework's own 404/405/422/400, `Allow`
included. Then the two things a gate can get wrong without a status changing:
resolving the principal **twice** (pinned by counting where it happens), and disagreeing
with the router about what a request reaches (pinned route by route).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app import error_codes
from app.auth import Scope, anonymous, owner, pat
from app.auth.dependency import BEARER_CHALLENGE, ResponseProfileMiddleware
from app.auth.prerouting import (
    Dispatch,
    DispatchTable,
    PreRoutingAuthMiddleware,
    refuses_anonymous,
)
from app.auth.registry import CredentialPolicy, iter_effective_routes
from app.auth.resolver import INJECTED_PRINCIPAL_ATTR, INVALID_TOKEN_CHALLENGE
from app.auth.sessions import cookie_is_secure, cookie_name
from app.config import get_settings
from app.db import get_sessionmaker
from app.ingress import ForwardedClientMiddleware, HostOriginGuardMiddleware
from app.main import create_app
from app.models import AuditEvent
from app.services import audit
from app.services import tokens as token_service

pytestmark = pytest.mark.anyio

LOOPBACK = ("127.0.0.1", 12345)
OUTSIDE = ("198.51.100.7", 40000)
JSON = {"Content-Type": "application/json"}
NOT_JSON = b"{not json"

# One enforced app for the module; the lifespan is not entered (ASGITransport
# never runs it, and nothing here reaches the MCP transport proper — the one
# request under the mount is the child's own 404).
_APP = create_app(authorization=True)

HOLDERS = [owner(), pat(write=False), pat(write=True)]


async def _request(principal, method, path, *, peer=LOOPBACK, app=None, **kw):
    target = app or _APP
    if principal is None:
        if hasattr(target.state, INJECTED_PRINCIPAL_ATTR):
            delattr(target.state, INJECTED_PRINCIPAL_ATTR)
    else:
        setattr(target.state, INJECTED_PRINCIPAL_ATTR, principal)
    transport = ASGITransport(app=target, client=peer, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000", headers={"Host": "localhost"}
    ) as client:
        return await client.request(method, path, **kw)


def _assert_gate_refusal(
    resp, *, code=error_codes.AUTH_UNAUTHENTICATED, challenge=BEARER_CHALLENGE
):
    """The gate's refusal, whole: status, envelope, challenge, profile — and
    nothing the router would have added (no `Allow`, no `Location`)."""
    assert resp.status_code == 401, resp.text
    if resp.request.method != "HEAD":  # a HEAD carries the headers and no body
        body = resp.json()
        assert body["code"] == code
        assert set(body) == {"detail", "code", "params"}
    assert resp.headers.get("www-authenticate") == challenge
    assert resp.headers.get_list("cache-control") == ["no-store"]
    assert "allow" not in resp.headers
    assert "location" not in resp.headers


# --- unrouted paths ---------------------------------------------------------------

#: Paths nothing at the app matches: an unknown one, the non-canonical spellings
#: `redirect_slashes=False` refuses (§5.6), a suffix on a root route, and bare
#: `/mcp` — the ingress-only spelling the mount does not claim (family 7).
UNROUTED = ["/no-such-route", "/kits/", "/orders/?x=1", "/openapi.json/x", "/mcp"]


@pytest.mark.parametrize("path", UNROUTED)
async def test_an_unrouted_path_is_401_for_anon(path):
    _assert_gate_refusal(await _request(anonymous(), "GET", path))


@pytest.mark.parametrize("path", UNROUTED)
@pytest.mark.parametrize("holder", HOLDERS, ids=lambda p: p.label)
async def test_an_unrouted_path_stays_404_for_every_principal(path, holder):
    resp = await _request(holder, "GET", path)
    assert resp.status_code == 404, resp.text
    assert resp.json() == {"detail": "Not Found"}
    assert "location" not in resp.headers
    assert "www-authenticate" not in resp.headers


# --- wrong verbs ------------------------------------------------------------------

#: A verb no route on the path declares, on paths whose routes need a credential:
#: collection (family 4/5), instance settings (6), token management (6), the
#: re-registered schema (11), and readiness (10, `INTERNAL`) — a 405 there
#: would name the route's real verbs in `Allow`.
WRONG_VERB_SCOPED = [
    ("DELETE", "/kits"),
    ("OPTIONS", "/kits"),
    ("HEAD", "/kits"),
    ("PUT", "/settings"),
    ("DELETE", "/auth/tokens"),
    ("POST", "/openapi.json"),
    ("DELETE", "/readyz"),
]


@pytest.mark.parametrize(("method", "path"), WRONG_VERB_SCOPED)
async def test_a_wrong_verb_on_a_scoped_path_is_401_for_anon(method, path):
    _assert_gate_refusal(await _request(anonymous(), method, path))


@pytest.mark.parametrize(("method", "path"), WRONG_VERB_SCOPED)
@pytest.mark.parametrize("holder", HOLDERS, ids=lambda p: p.label)
async def test_a_wrong_verb_stays_405_with_allow_for_every_principal(method, path, holder):
    resp = await _request(holder, method, path)
    assert resp.status_code == 405, resp.text
    assert resp.headers.get("allow")
    assert "www-authenticate" not in resp.headers


#: The anonymous families' own paths (2, 3, 9): a wrong verb there discloses
#: nothing a credential would have hidden, so the router's 405 stands for
#: everyone, `Allow` included.
WRONG_VERB_ANONYMOUS = [
    ("DELETE", "/healthz"),
    ("PUT", "/auth/session"),
    ("GET", "/auth/login"),
    ("GET", "/auth/logout"),
    ("GET", "/auth/setup"),
]


@pytest.mark.parametrize(("method", "path"), WRONG_VERB_ANONYMOUS)
@pytest.mark.parametrize("principal", [anonymous(), owner()], ids=lambda p: p.label)
async def test_a_wrong_verb_on_an_anonymous_path_keeps_its_405(method, path, principal):
    resp = await _request(principal, method, path)
    assert resp.status_code == 405, resp.text
    assert resp.headers.get("allow")
    assert "www-authenticate" not in resp.headers


# --- malformed bodies -------------------------------------------------------------

#: Scoped writes across families 5 and 6. A body FastAPI cannot decode as JSON
#: was a 422 before the dependency ran; a multipart body with no boundary was
#: Starlette's 400 at the same stage.
MALFORMED_SCOPED = [
    ("POST", "/kits", NOT_JSON, JSON, 422, error_codes.REQUEST_VALIDATION),
    ("POST", "/retailers", NOT_JSON, JSON, 422, error_codes.REQUEST_VALIDATION),
    ("PATCH", "/settings", NOT_JSON, JSON, 422, error_codes.REQUEST_VALIDATION),
    (
        "POST",
        "/import/preview",
        b"--x--",
        {"Content-Type": "multipart/form-data"},
        400,
        error_codes.REQUEST_BODY_INVALID,
    ),
]


@pytest.mark.parametrize(("method", "path", "body", "headers", "_st", "_code"), MALFORMED_SCOPED)
async def test_a_malformed_body_on_a_scoped_route_is_401_for_anon(
    method, path, body, headers, _st, _code
):
    _assert_gate_refusal(await _request(anonymous(), method, path, content=body, headers=headers))


@pytest.mark.parametrize(("method", "path", "body", "headers", "status", "code"), MALFORMED_SCOPED)
@pytest.mark.parametrize("holder", HOLDERS, ids=lambda p: p.label)
async def test_a_malformed_body_still_earns_the_parser_status_for_every_principal(
    method, path, body, headers, status, code, holder
):
    """The parser stage is unchanged for an authenticated caller — including a
    `pat:read` on a write route, whose 403 the dependency would raise *after*
    the decode, exactly as before the gate."""
    resp = await _request(holder, method, path, content=body, headers=headers)
    assert resp.status_code == status, resp.text
    assert resp.json()["code"] == code


@pytest.mark.parametrize("path", ["/auth/login", "/auth/setup"])
async def test_a_malformed_body_on_an_anonymous_route_stays_422(path):
    """There is no credential to gate a family-3 action on, so the parser
    still answers — the client has to learn its body was unreadable."""
    resp = await _request(anonymous(), "POST", path, content=NOT_JSON, headers=JSON)
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == error_codes.REQUEST_VALIDATION


async def test_a_valid_body_on_a_scoped_route_is_still_the_dependency_s_answer():
    """The positive control beside the negatives: a well-formed anonymous write
    is refused the same way it always was, and the owner's goes through."""
    _assert_gate_refusal(await _request(anonymous(), "POST", "/retailers", json={"name": "x"}))
    created = await _request(owner(), "POST", "/retailers", json={"name": f"Gate {uuid.uuid4()}"})
    assert created.status_code == 201, created.text


# --- what the gate leaves alone ---------------------------------------------------


async def test_the_mount_is_the_child_s():
    """A request the `/mcp` mount claims is FastMCP's to answer (family 7): an
    unrouted path under it stays the child's own 404, because a cookie never
    authenticates there and the gate resolves no principal for it."""
    resp = await _request(anonymous(), "GET", "/mcp/no-such-route")
    assert resp.status_code == 404, resp.text
    assert "www-authenticate" not in resp.headers


#: Family 8's namespace (§5.5): the three root discovery documents M6-7 will
#: install, and an arbitrary sibling. Anonymous by protocol, absent in local
#: mode — the router's 404 for everyone, never a `Bearer` challenge (the CI
#: Integration run on PR #205's first head found the 401).
PROTOCOL_PATHS = [
    "/.well-known/openid-configuration/mcp",
    "/.well-known/oauth-authorization-server/mcp",
    "/.well-known/oauth-protected-resource/mcp/",
    "/.well-known/anything",
]


@pytest.mark.parametrize("path", PROTOCOL_PATHS)
@pytest.mark.parametrize("principal", [anonymous(), owner()], ids=lambda p: p.label)
async def test_the_protocol_namespace_is_the_router_s_404_in_local_mode(path, principal):
    resp = await _request(principal, "GET", path)
    assert resp.status_code == 404, resp.text
    assert resp.json() == {"detail": "Not Found"}
    assert "www-authenticate" not in resp.headers


async def test_readiness_is_still_decided_by_the_peer():
    """`INTERNAL` admits `anon` on a full match — the route self-guards on the
    raw peer (family 10): loopback answers, any other peer gets the 404 an
    unrouted path *used* to earn, not the gate's 401 (which would say a route
    is there)."""
    assert (await _request(anonymous(), "GET", "/readyz")).status_code == 200
    outside = await _request(anonymous(), "GET", "/readyz", peer=OUTSIDE)
    assert outside.status_code == 404
    assert "www-authenticate" not in outside.headers


async def test_an_app_built_without_authorization_has_no_gate():
    """`create_app()` — what the ingress and packaged-stack harnesses build —
    keeps the framework's 404 for everyone; the gate is installed only beside
    the dependency it fronts."""
    harness = create_app()
    assert all(m.cls is not PreRoutingAuthMiddleware for m in harness.user_middleware)
    resp = await _request(None, "GET", "/no-such-route", app=harness)
    assert resp.status_code == 404


# --- the resolver's contract holds at the gate ------------------------------------


@pytest.mark.parametrize(
    "authorization", ["Bearer nonsense", "Bearer ptk_0123456789ab_notthesecret", "Basic abc"]
)
@pytest.mark.parametrize(("method", "path"), [("GET", "/no-such-route"), ("DELETE", "/kits")])
async def test_a_failed_bearer_on_an_unrouted_path_is_the_resolver_s_401(
    authorization, method, path
):
    """Presented and failed is 401 `auth.bearer_invalid` with the RFC 6750
    challenge — on an unrouted path and a wrong verb as on a routed one — not
    the bare-`Bearer` 401 an absent credential earns. Strictness survives the
    move ahead of routing."""
    resp = await _request(None, method, path, headers={"Authorization": authorization})
    _assert_gate_refusal(
        resp, code=error_codes.AUTH_BEARER_INVALID, challenge=INVALID_TOKEN_CHALLENGE
    )


async def test_a_stale_session_cookie_on_an_unrouted_path_is_anon():
    """#188 call (a): a non-resolving cookie is `anon`, never 401-as-invalid —
    so the gate answers the bare challenge, and the browser's recovery through
    `GET /auth/session` (anonymous, so untouched by the gate) still works."""
    cookie = {"Cookie": f"{cookie_name(cookie_is_secure(get_settings()))}=not-a-session"}
    _assert_gate_refusal(await _request(None, "GET", "/no-such-route", headers=cookie))
    session = await _request(None, "GET", "/auth/session", headers=cookie)
    assert session.status_code == 200
    # The suite resets the instance to unclaimed between tests; either way the
    # stale cookie did not wedge the bootstrap and nobody is signed in.
    assert session.json()["state"] in {"unclaimed", "anonymous"}


async def test_a_real_bearer_reaches_the_dependency_with_its_scopes():
    """The stashed principal is the resolver's own: a real `pat:read` bearer
    is admitted by the gate, then refused by the dependency on a write route
    with the scope 403 — proof the gate hands the dependency what it resolved
    rather than a re-resolution or a default."""
    async with get_sessionmaker()() as session:
        raw, _ = await token_service.mint_token(session, name="gate", scopes={Scope.READ})
    headers = {"Authorization": f"Bearer {raw}"}
    assert (await _request(None, "GET", "/kits", headers=headers)).status_code == 200
    refused = await _request(None, "POST", "/retailers", json={"name": "x"}, headers=headers)
    assert refused.status_code == 403
    assert refused.json()["code"] == error_codes.AUTH_FORBIDDEN


# --- resolved once ----------------------------------------------------------------


async def _audit_count(event_type: str) -> int:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == event_type)
        )


async def test_a_revoked_token_writes_one_audit_row_per_request():
    """The resolver's audit contract holds at the gate: a revoked token
    presented with its correct secret writes `auth.token_use_after_revoke`
    exactly once, from the gate's own session (the commit-then-raise path in
    `_resolve_bearer`). A control, not a double-resolution witness — the gate
    refuses the token, so the dependency never runs for it; the once-per-request
    property is pinned by the resolution-count test below (Codex #205 round 1,
    f2)."""
    async with get_sessionmaker()() as session:
        raw, row = await token_service.mint_token(session, name="leaked", scopes={Scope.READ})
        await token_service.revoke_token(session, row.id)
    resp = await _request(None, "GET", "/kits", headers={"Authorization": f"Bearer {raw}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == error_codes.AUTH_BEARER_INVALID
    assert await _audit_count(audit.TOKEN_USE_AFTER_REVOKE) == 1


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/kits", {"gate": 1, "dependency": 0}),
        ("/healthz", {"gate": 1, "dependency": 0}),
        ("/no-such-route", {"gate": 1, "dependency": 0}),
        ("/mcp/no-such-route", {"gate": 0, "dependency": 0}),
        ("/.well-known/openid-configuration/mcp", {"gate": 0, "dependency": 0}),
    ],
)
async def test_the_principal_is_resolved_by_the_gate_and_reused_by_the_dependency(
    monkeypatch, path, expected
):
    """Which of the two places resolves: the gate once, the dependency never —
    on a scoped route, an anonymous one, and an unrouted path alike; and
    neither for a request the mount claims (a cookie is never even looked at
    on the way to FastMCP) nor for one under the protocol namespace."""
    from app.auth import dependency, prerouting

    calls: dict[str, int] = {"gate": 0, "dependency": 0}
    real = prerouting.resolve_principal

    async def gate_resolve(request, session):
        calls["gate"] += 1
        return await real(request, session)

    async def dependency_resolve(request, session):
        calls["dependency"] += 1
        return await real(request, session)

    monkeypatch.setattr(prerouting, "resolve_principal", gate_resolve)
    monkeypatch.setattr(dependency, "resolve_principal", dependency_resolve)
    await _request(owner(), "GET", path)
    assert calls == expected


async def test_the_dependency_still_denies_without_the_gate():
    """The gate never grants and the dependency never relies on it: with the
    gate taken out of the stack, an anonymous read is still the dependency's
    own 401 (resolved there, as the fallback), and an unrouted path is back to
    the framework's 404 — the pre-#204 shape, default-deny intact."""
    live = create_app(authorization=True)
    live.user_middleware[:] = [
        m for m in live.user_middleware if m.cls is not PreRoutingAuthMiddleware
    ]
    live.middleware_stack = None
    denied = await _request(anonymous(), "GET", "/kits", app=live)
    assert denied.status_code == 401
    assert denied.json()["code"] == error_codes.AUTH_UNAUTHENTICATED
    assert (await _request(anonymous(), "GET", "/no-such-route", app=live)).status_code == 404


# --- position and agreement with the router ---------------------------------------


def test_the_gate_sits_between_the_profile_layer_and_the_ingress_guards():
    """Starlette builds the stack outermost-first from `user_middleware`: the
    Host/Origin guard and the forwarded-client resolver wrap the gate (a hostile
    Host is 421 before any principal is resolved; the forwarded address is on
    the state the resolver reads), and the gate wraps the profile layer, which
    stays innermost (`test_the_profile_middleware_is_innermost`)."""
    live = create_app(authorization=True)
    assert [m.cls for m in live.user_middleware] == [
        HostOriginGuardMiddleware,
        ForwardedClientMiddleware,
        PreRoutingAuthMiddleware,
        ResponseProfileMiddleware,
    ]


class _RecordEndpoint:
    """Outermost; reads the endpoint the router recorded in the dict every layer
    below passes straight on (the round-3 reasoning behind the profile layer)."""

    def __init__(self, app):
        self.app = app
        self.seen: list[object] = []

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)
        self.seen.append(scope.get("endpoint"))


def _fill(path: str) -> str:
    """A concrete path for a route template: every `{param}` is a value the
    default `str` convertor accepts; FastAPI's own validation of it is the
    handler's business, not routing's."""
    out, depth = [], 0
    for ch in path:
        if ch == "{":
            depth += 1
            out.append(str(uuid.uuid4()))
        elif ch == "}":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


async def test_the_gate_and_the_router_agree_on_every_declared_route():
    """The gate never grants, so a disagreement could only cost disclosure —
    but the point of the gate *is* disclosure, so the two are pinned to agree
    on every effective route: a declared verb is a full match on the endpoint
    the router then records; an undeclared verb is a partial match naming it;
    and the router records nothing where the table says nothing matches."""
    live = create_app(authorization=True)
    recorder: list[_RecordEndpoint] = []

    def factory(app):
        recorder.append(_RecordEndpoint(app))
        return recorder[-1]

    live.add_middleware(factory)  # type: ignore[arg-type]
    setattr(live.state, INJECTED_PRINCIPAL_ATTR, owner())
    table = DispatchTable.from_app(live)
    transport = ASGITransport(app=live, client=LOOPBACK, raise_app_exceptions=False)
    routes = list(iter_effective_routes(live))
    assert routes

    def scope_for(method: str, path: str) -> dict:
        return {"type": "http", "method": method, "path": path, "root_path": ""}

    async with AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000", headers={"Host": "localhost"}
    ) as client:
        for route in routes:
            path = _fill(route.path)
            for method in sorted(route.methods):
                outcome = table.resolve(scope_for(method, path))
                assert outcome.kind is Dispatch.FULL, (method, path)
                assert outcome.endpoints == (route.endpoint,), (method, path)
                await client.request(method, path)
                assert recorder[-1].seen[-1] is route.endpoint, (method, path)
            # An undeclared verb — including `HEAD`, which Starlette's own
            # `Route` would add beside a `GET` and FastAPI's `APIRoute` does not.
            for method in [m for m in ("TRACE", "HEAD") if m not in route.methods]:
                outcome = table.resolve(scope_for(method, path))
                assert outcome.kind is Dispatch.PARTIAL, (method, path)
                assert route.endpoint in outcome.endpoints, (method, path)
                resp = await client.request(method, path)
                assert resp.status_code == 405, (method, path, resp.status_code)
                assert recorder[-1].seen[-1] in outcome.endpoints, (method, path)
        assert table.resolve(scope_for("GET", "/no-such-route")).kind is Dispatch.NONE
        await client.get("/no-such-route")
        assert recorder[-1].seen[-1] is None
        assert table.resolve(scope_for("POST", "/mcp/")).kind is Dispatch.MOUNT
        for path in PROTOCOL_PATHS:
            assert table.resolve(scope_for("GET", path)).kind is Dispatch.PROTOCOL, path
            await client.get(path)
            assert recorder[-1].seen[-1] is None, path


def test_refuses_anonymous_is_decided_by_policy_not_path():
    """The decision table, off the live index: a mount and the protocol
    namespace are never refused; a full match refuses unless the
    policy admits `anon` (`ANONYMOUS`, and `INTERNAL` which self-guards); a
    partial refuses unless *every* route on the path is `ANONYMOUS` (so
    `INTERNAL` is refused there — a 405 would name `/readyz`); no match and
    an endpoint the index does not know both refuse."""
    from app.auth.dependency import ROUTE_INDEX_ATTR
    from app.auth.prerouting import Outcome

    live = create_app(authorization=True)
    index = getattr(live.state, ROUTE_INDEX_ATTR)
    by_credential: dict[str, object] = {}
    for endpoint, policy in index.by_endpoint.items():
        by_credential.setdefault(policy.credential, endpoint)
    anonymous_ep = by_credential[CredentialPolicy.ANONYMOUS]
    internal_ep = by_credential[CredentialPolicy.INTERNAL]
    read_ep = by_credential[CredentialPolicy.READ]

    assert refuses_anonymous(index, Outcome(Dispatch.MOUNT)) is False
    assert refuses_anonymous(index, Outcome(Dispatch.PROTOCOL)) is False
    assert refuses_anonymous(index, Outcome(Dispatch.NONE)) is True
    assert refuses_anonymous(index, Outcome(Dispatch.FULL, (anonymous_ep,))) is False
    assert refuses_anonymous(index, Outcome(Dispatch.FULL, (internal_ep,))) is False
    assert refuses_anonymous(index, Outcome(Dispatch.FULL, (read_ep,))) is True
    assert refuses_anonymous(index, Outcome(Dispatch.FULL, (object(),))) is True
    assert refuses_anonymous(index, Outcome(Dispatch.PARTIAL, (anonymous_ep,))) is False
    assert refuses_anonymous(index, Outcome(Dispatch.PARTIAL, (internal_ep,))) is True
    assert refuses_anonymous(index, Outcome(Dispatch.PARTIAL, (anonymous_ep, read_ep))) is True
