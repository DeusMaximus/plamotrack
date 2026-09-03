"""The app-level default-deny authorization dependency (§5.5).

One dependency, attached to every REST route (not a per-route decoration a new
router can forget — the #25 envelope lesson applied to auth), that reads the
route policy registry by the **resolved endpoint** and allows or denies from the
principal's scopes. Because it matches on `scope["endpoint"]` — the callable
Starlette resolved — and never on the URL string, no encoding, doubled slash or
traversal can select a different policy than the handler it reaches.

**Not yet installed on the shipped app.** `create_app(authorization=False)` is
the default, so the shipped instance keeps answering every route until the
credential mechanisms exist (#188 session, #189 bearer) — the "activate once
credentials work" sequencing (foundation first, M6-2). `create_app(
authorization=True)` installs it, and the authorization matrix
(`tests/test_authorization.py`) drives the real route graph through it with
injected principals. When #188 flips the default to True it also does the
suite-wide injection and the CI/e2e credential path; until then this is
exercised only where a test asks for it.

Statuses (§5.5):

- `ANONYMOUS` route → always allowed.
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
with `code` `auth.unauthenticated` / `auth.forbidden`.
"""

from __future__ import annotations

from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import error_codes
from app.auth.principal import Principal, PrincipalKind
from app.auth.registry import CredentialPolicy, RouteIndex
from app.auth.resolver import resolve_principal
from app.exceptions import ForbiddenError, UnauthenticatedError

#: Where `create_app` stores the resolved registry for the dependency to read.
ROUTE_INDEX_ATTR = "route_index"

#: Also stashed on `request.state` for downstream use (audit, #193).
REQUEST_PRINCIPAL_ATTR = "principal"

_UNAUTHENTICATED = "You need to sign in to do that."
_FORBIDDEN = "Your access doesn't allow that action."


async def enforce_route_policy(request: Request) -> Principal:
    index: RouteIndex = getattr(request.app.state, ROUTE_INDEX_ATTR)
    endpoint = request.scope.get("endpoint")
    policy = index.policy_for(endpoint) if endpoint is not None else None
    principal = resolve_principal(request)
    setattr(request.state, REQUEST_PRINCIPAL_ATTR, principal)

    if policy is None:
        # An app-level dependency runs only for a matched route, and every
        # declared route resolves — so this is defence in depth. Fail closed.
        raise UnauthenticatedError(_UNAUTHENTICATED, code=error_codes.AUTH_UNAUTHENTICATED)

    credential = policy.credential
    if credential == CredentialPolicy.ANONYMOUS:
        return principal
    if credential == CredentialPolicy.INTERNAL:
        # Readiness self-guards on the raw peer; let it answer its own 404.
        return principal

    scope = policy.required_scope
    if scope is None:
        # MCP_TRANSPORT / PROTOCOL do not belong on a REST route. Fail closed.
        raise UnauthenticatedError(_UNAUTHENTICATED, code=error_codes.AUTH_UNAUTHENTICATED)
    if principal.kind is PrincipalKind.ANON:
        raise UnauthenticatedError(_UNAUTHENTICATED, code=error_codes.AUTH_UNAUTHENTICATED)
    if not principal.has_scope(scope):
        raise ForbiddenError(_FORBIDDEN, code=error_codes.AUTH_FORBIDDEN)
    return principal


class ResponseProfileMiddleware:
    """Applies the registry's response profile to the **final outgoing response**,
    however the handler produced it — a value FastAPI serialises, an explicit
    `Response` (the CSV/zip exports go through `portability._attachment`), or a
    raised deny the exception handler renders.

    Why a middleware and not the dependency: FastAPI's temporary dependency
    `Response` only merges into responses it builds from a return value, so a
    handler that returns its own `Response` never receives those headers — the
    exports carry collection data and lost `Cache-Control: no-store` that way
    (PR #198 Codex finding 1). Reading `scope["endpoint"]` at response start —
    set by routing before any handler runs — lets this stamp every matched
    route uniformly. The declared liveness/readiness exceptions keep no header
    (their policy's `no_store` is False), and an unrouted path has no endpoint.
    Installed only when `authorization=True`; the shipped app is untouched.
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
                if policy is not None and policy.response.no_store:
                    headers = MutableHeaders(raw=message.setdefault("headers", []))
                    headers.setdefault("cache-control", "no-store")
            await send(message)

        await self.app(scope, receive, send_wrapper)
