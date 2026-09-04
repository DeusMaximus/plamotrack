"""The app-level default-deny authorization dependency (§5.5).

One dependency, attached to every REST route (not a per-route decoration a new
router can forget — the #25 envelope lesson applied to auth), that reads the
route policy registry by the **resolved endpoint** and allows or denies from the
principal's scopes. Because it matches on `scope["endpoint"]` — the callable
Starlette resolved — and never on the URL string, no encoding, doubled slash or
traversal can select a different policy than the handler it reaches.

**Installed on the shipped app since M6-3 (#188).** `create_app(authorization=
True)` installs it and the module-level `app` runs with it on: local owner
authentication (#188) is what makes default-deny usable, so the sequencing "build
the foundation (M6-2), activate once a credential exists (M6-3)" completes here.
`create_app()` (the default off) is still what the ingress and packaged-stack
harnesses build, and the suite drives the shipped app with an injected owner
(`tests/conftest.py`); the authorization matrix (`tests/test_authorization.py`)
injects each principal against the real route graph. The resolver's credentials
are the session cookie (#188) and the personal access token as a bearer (#189);
a presented-and-failed bearer is the resolver's 401 before this runs.

Statuses (§5.5):

- `ANONYMOUS` route → always allowed — except that a family-3 action refuses a
  bearer-borne principal with **403** (`bearer_refused`): a token cannot log in,
  log out or claim.
- scoped route (`READ`/`WRITE`/`ADMIN`) → `anon` is **401**, an authenticated
  principal without the scope is **403**, otherwise allowed.
- `INTERNAL` route (readiness) → allowed through here; the route self-guards on
  the raw loopback peer and answers the same 404 an unrouted path earns, so a
  non-internal peer is not told the database's state (§5.5, family 10).
- `MCP_TRANSPORT` / `PROTOCOL` never reach this dependency (they are the mounted
  child, guarded by FastMCP and the tool wrappers); a REST route carrying one
  would be a bug, so it fails closed.

The 401/403 travel in the #25 envelope: the dependency raises the domain errors
`UnauthenticatedError` / `ForbiddenError`, which the registered handler renders
with `code` `auth.unauthenticated` / `auth.forbidden`. Every 401 carries a
`WWW-Authenticate: Bearer` challenge (RFC 7235 §3.1): bare for an absent
credential, `error="invalid_token"` for a presented bearer that failed.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI, Request
from mcp.server.streamable_http import CONTENT_TYPE_JSON
from mcp.types import INVALID_REQUEST, ErrorData, JSONRPCError
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import error_codes
from app.auth.credentials import csrf_tokens_match
from app.auth.principal import Principal, PrincipalKind
from app.auth.registry import CredentialPolicy, ResponseProfile, RouteIndex, RoutePolicy
from app.auth.resolver import RAW_SESSION_TOKEN_ATTR, resolve_principal
from app.auth.sessions import CSRF_HEADER
from app.db import SessionDep
from app.exceptions import ForbiddenError, UnauthenticatedError

#: Where `create_app` stores the resolved registry for the dependency to read.
ROUTE_INDEX_ATTR = "route_index"

#: Also stashed on `request.state` for downstream use (audit, #193).
REQUEST_PRINCIPAL_ATTR = "principal"

#: The challenge an absent credential earns on a scoped route (RFC 7235 §3.1;
#: RFC 6750 §3). A browser does not prompt on `Bearer`, so the SPA's 401s are
#: unaffected; a script sees which scheme the API takes.
BEARER_CHALLENGE = "Bearer"

#: Methods that carry no CSRF risk — a cross-site GET is unreadable by the page
#: that sent it (mirrors `ingress.SAFE_METHODS`).
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_UNAUTHENTICATED = "You need to sign in to do that."
_FORBIDDEN = "Your access doesn't allow that action."
_CSRF_FAILED = "This request didn't carry a valid session token. Reload the page and try again."
_ORIGIN_REQUIRED = "This request didn't say where it came from, so it was refused."


def _enforce_csrf(request: Request, principal: Principal) -> None:
    """The session's CSRF controls (§5.6, CSRF; #188). They apply to a
    **cookie-borne** unsafe request only — a bearer request (#189) skips both, a
    browser never attaching a bearer cross-site without a CORS preflight no
    allow-origin will ever grant. Two independent conditions, either enough to
    stop a simple forgery:

    - **an Origin (or Referer) must be present.** The ingress guard already
      validated its *value* when present (`app/ingress.py`); this closes the
      absent case for a cookie-borne write, the tightening §5.6 deferred to this
      item — a browser cannot omit `Origin` on a cross-site unsafe request.
    - **the session-bound CSRF token** in `X-CSRF-Token`, from `GET /auth/session`
      (`csrf_tokens_match`), which only a holder of the `HttpOnly` cookie value
      can compute.
    """
    if request.method in _SAFE_METHODS or not principal.cookie_borne:
        return
    if request.headers.get("origin") is None and request.headers.get("referer") is None:
        raise ForbiddenError(_ORIGIN_REQUIRED, code=error_codes.AUTH_ORIGIN_REQUIRED)
    raw_token = getattr(request.state, RAW_SESSION_TOKEN_ATTR, None)
    presented = request.headers.get(CSRF_HEADER)
    if raw_token is None or not csrf_tokens_match(presented, raw_token):
        raise ForbiddenError(_CSRF_FAILED, code=error_codes.AUTH_CSRF_FAILED)


async def enforce_route_policy(request: Request, session: SessionDep) -> Principal:
    index: RouteIndex = getattr(request.app.state, ROUTE_INDEX_ATTR)
    endpoint = request.scope.get("endpoint")
    policy = index.policy_for(endpoint) if endpoint is not None else None
    principal = await resolve_principal(request, session)
    setattr(request.state, REQUEST_PRINCIPAL_ATTR, principal)

    if policy is None:
        # An app-level dependency runs only for a matched route, and every
        # declared route resolves — so this is defence in depth. Fail closed.
        raise UnauthenticatedError(
            _UNAUTHENTICATED, code=error_codes.AUTH_UNAUTHENTICATED, challenge=BEARER_CHALLENGE
        )

    # CSRF applies to any cookie-borne unsafe request, whatever the route's
    # credential policy — a family-3 logout is anonymous-classified but still
    # cookie-borne, so the check lives here, before the scope switch.
    _enforce_csrf(request, principal)

    # A token is not a browser (§5.5 family 3): the auth actions refuse a
    # bearer-borne principal whatever the credential policy admits.
    if policy.bearer_refused and principal.bearer_borne:
        raise ForbiddenError(_FORBIDDEN, code=error_codes.AUTH_FORBIDDEN)

    credential = policy.credential
    if credential == CredentialPolicy.ANONYMOUS:
        return principal
    if credential == CredentialPolicy.INTERNAL:
        # Readiness self-guards on the raw peer; let it answer its own 404.
        return principal

    scope = policy.required_scope
    if scope is None:
        # MCP_TRANSPORT / PROTOCOL do not belong on a REST route. Fail closed.
        raise UnauthenticatedError(
            _UNAUTHENTICATED, code=error_codes.AUTH_UNAUTHENTICATED, challenge=BEARER_CHALLENGE
        )
    if principal.kind is PrincipalKind.ANON:
        raise UnauthenticatedError(
            _UNAUTHENTICATED, code=error_codes.AUTH_UNAUTHENTICATED, challenge=BEARER_CHALLENGE
        )
    if not principal.has_scope(scope):
        raise ForbiddenError(_FORBIDDEN, code=error_codes.AUTH_FORBIDDEN)
    return principal


# --- the response profile, enforced on the final response ------------------------

#: The one `Cache-Control` directive a handler may keep beside a required
#: `no-store`: `no-transform` forbids intermediaries from re-encoding the payload
#: and says nothing about storing (RFC 9111 §5.2.2.6). The MCP SDK sets it on the
#: SSE stream so a proxy does not transform the event stream; stripping it would
#: trade one leak for another. Every other directive a handler set — `public`,
#: `private`, `max-age`, `s-maxage`, `no-cache`, `must-revalidate`, `immutable`,
#: the `stale-*` extensions — either permits storing or is redundant beside
#: `no-store`, and is replaced.
KEPT_BESIDE_NO_STORE = frozenset({"no-transform"})

_CACHE_CONTROL = b"cache-control"


def final_cache_control(profile: ResponseProfile, existing: Iterable[str]) -> str | None:
    """The `Cache-Control` value the final response carries for `profile`, given
    the value(s) the handler set. None when the profile makes no demand (the
    handler's header stands, whatever it is); the declared `cache` verbatim; or
    `no-store` — with `no-transform` retained if the handler had it — replacing
    everything else. The header-value axis (Codex #198 round 2, f1): absent,
    empty, a directive that permits storing, one that merely revalidates, or
    `no-store` already, all end as the declaration. `setdefault` only ever
    covered the first of those."""
    required = profile.cache_control
    if required is None:
        return None
    if not profile.no_store:
        return required
    directives = [part.strip().lower() for value in existing for part in value.split(",")]
    kept = [d for d in directives if d and d.split("=", 1)[0].strip() in KEPT_BESIDE_NO_STORE]
    return ", ".join([required, *dict.fromkeys(kept)])


def _stamp_cache_control(message: Message, profile: ResponseProfile) -> None:
    """Replace every `Cache-Control` line in a response-start message with the
    profile's final value. Header names are case-insensitive, and a raw ASGI
    endpoint may spell the key `Cache-Control`, which Starlette's
    `MutableHeaders` would not match and would leave standing beside the
    stamped one — so every spelling goes and one comes back."""
    raw = [(bytes(k), bytes(v)) for k, v in (message.get("headers") or ())]
    existing = [v.decode("latin-1") for k, v in raw if k.lower() == _CACHE_CONTROL]
    value = final_cache_control(profile, existing)
    if value is None:
        return
    message["headers"] = [(k, v) for k, v in raw if k.lower() != _CACHE_CONTROL] + [
        (_CACHE_CONTROL, value.encode("latin-1"))
    ]


class ResponseProfileMiddleware:
    """Applies the registry's response profile to the **final outgoing response**
    of every route of the app itself, however the route produced it — a value
    FastAPI serialises, an explicit `Response` (the CSV/zip exports go through
    `portability._attachment`), a raised deny the exception handler renders, a
    parser 422 raised before any dependency ran, Starlette's 405 for a wrong
    verb on a matched path.

    Why a middleware and not the dependency: FastAPI's temporary dependency
    `Response` only merges into responses it builds from a return value, so a
    handler that returns its own `Response` never receives those headers — the
    exports carry collection data and lost `Cache-Control: no-store` that way
    (PR #198 Codex finding 1); and the dependency runs after the body is parsed,
    so a 422 from the parser would report nothing.

    Why reading `scope["endpoint"]` here is sound (round 3, f1): a middleware may
    legally hand a *copy* of the scope downstream, and a router then records the
    selected endpoint in the copy. This layer is installed **first**, so it is the
    innermost user middleware: between it and FastAPI's router sit only
    Starlette's `ExceptionMiddleware` and FastAPI's `AsyncExitStackMiddleware`,
    both of which add keys to the dict they were handed and pass that same dict
    on. The router therefore writes the selection into the very dict this layer
    holds, and a copy made anywhere *above* is simply the dict the router
    receives (`test_a_scope_copy_above_the_middleware_changes_nothing`); the
    position is pinned by `test_the_profile_middleware_is_innermost`. What this
    reasoning cannot cover is a *mounted* child, whose own middleware may sit
    between its router and this layer — so `policy_for` answers only for the
    app's own routes, and every mounted route carries a `RouteBinding` on the
    route itself instead. A response produced before any route is matched — the
    unrouted 404, the outer 500 — has no endpoint and carries nothing.

    Why *replace* and not default (round 2, f1): a handler- or library-set
    `Cache-Control` — `public`, `private, no-cache` — would otherwise stand, and
    none of those means "do not store". The declaration wins; `no-transform`
    alone survives beside it (`KEPT_BESIDE_NO_STORE`). Installed only when
    `authorization=True`; the shipped app is untouched.
    """

    def __init__(self, app: ASGIApp, index: RouteIndex) -> None:
        self.app = app
        self.index = index

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                endpoint = scope.get("endpoint")
                policy = self.index.policy_for(endpoint) if endpoint is not None else None
                if policy is not None:
                    _stamp_cache_control(message, policy.response)
            await send(message)

        await self.app(scope, receive, send_wrapper)


# --- binding a policy onto a route the dependency cannot reach ---------------------

#: The order `Allow` lists verbs in — the SDK's own for its transport
#: (`GET, POST, DELETE`), so the binding's refusal reads the same as the SDK's.
_METHOD_ORDER = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT")


def allow_header(methods: Iterable[str]) -> str:
    declared = set(methods)
    ordered = [m for m in _METHOD_ORDER if m in declared]
    return ", ".join(ordered + sorted(declared - set(_METHOD_ORDER)))


def method_not_allowed(policy: RoutePolicy) -> Response:
    """The refusal for a verb the policy does not declare. For the MCP transport
    it is the SDK's own protocol error — the same JSON-RPC document, status,
    `Allow` and content type its `_handle_unsupported_request` produces (built
    from the SDK's types, so a serialisation change follows) — without an
    `mcp-session-id`, because a refused verb creates no session. Any other route
    gets the framework's plain 405."""
    headers = {"Allow": allow_header(policy.methods)}
    if policy.credential == CredentialPolicy.MCP_TRANSPORT:
        error = JSONRPCError(
            jsonrpc="2.0",
            id="server-error",
            error=ErrorData(code=INVALID_REQUEST, message="Method Not Allowed"),
        )
        return Response(
            error.model_dump_json(by_alias=True, exclude_none=True),
            status_code=405,
            headers={**headers, "Content-Type": CONTENT_TYPE_JSON},
        )
    return JSONResponse({"detail": "Method Not Allowed"}, status_code=405, headers=headers)


class RouteBinding:
    """A declared policy bound onto one mounted route's ASGI app — the app
    Starlette's `Route.handle` (or a bare-callable `Mount`) invokes — for every
    route under a mount (§5.5 family 7/8), which the app-level dependency never
    runs for and whose child app may stack middleware of its own above it.

    Two things, both decided from the declaration and nothing else:

    - **the accepted verbs** (round 3, f2): a request whose method the policy does
      not declare is refused here, before the wrapped implementation runs. For a
      REST route Starlette's own metadata is that boundary; the MCP transport's
      metadata is `methods=None` (the SDK dispatches on the verb inside), so the
      registry's declared set is enforced in front of it — an SDK release
      accepting a new verb, registered or extension, cannot widen the surface.
      The refusal is the SDK's own protocol error (`method_not_allowed`);
    - **the response profile** (round 3, f1): stamped on this route's own send,
      below whatever middleware the child app stacks above its routes, so a
      copied scope upstream cannot lose it.

    Idempotent per app: `bind_route_policies` skips a route already bound. The
    REST dependency still never wraps these — a binding enforces verbs and the
    response profile, not a credential.
    """

    def __init__(self, app: ASGIApp, policy: RoutePolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                _stamp_cache_control(message, self.policy.response)
            await send(message)

        if self.policy.methods and scope["method"] not in self.policy.methods:
            await method_not_allowed(self.policy)(scope, receive, send_wrapper)
            return
        await self.app(scope, receive, send_wrapper)


def bind_route_policies(app: FastAPI, index: RouteIndex) -> None:
    """Wrap every mounted route in a `RouteBinding` for its declared policy. The
    mounted child is built per `create_app`, so its route objects are this app's
    own and binding them touches no other app. The app's own routes are not
    bound: FastAPI re-derives an included router's routes per app from the
    router's originals (the original's `.app` is never what runs), and the
    innermost middleware covers them by position instead."""
    for mounted in index.mounted_routes:
        policy = index.mounted_by_endpoint.get(mounted.endpoint)
        route = mounted.route
        if policy is not None and not isinstance(route.app, RouteBinding):  # type: ignore[attr-defined]
            route.app = RouteBinding(route.app, policy)  # type: ignore[attr-defined]
