"""The pre-routing gate (§5.5 family 13; §5.9 item 3(b); #204).

Two disclosures the app-level dependency cannot close, because it runs only
after Starlette has routed the request and FastAPI has decoded its body:

- **an unrouted path or a wrong verb** answered 404 / 405 to everyone — with
  an `Allow` header naming the route's real verbs — so an anonymous client
  could map the route table without a credential (the family-13 row says 401);
- **a malformed JSON body** to a scoped route answered the parser's 422 before
  the dependency ran, so an anonymous client learned that the route exists and
  takes JSON (field validation already landed *after* the dependency; only the
  decode stage ran ahead of it).

This middleware sits between the innermost response-profile layer and the
ingress guards (`create_app`), resolves the principal **once** for every request
the REST app owns, stashes it on the request state for the dependency to reuse,
and refuses an anonymous caller *before* the router runs wherever the router
would have answered 404, 405 or a scoped route's 401 — reading what the request
would reach from the registry's own dispatch walk (`iter_dispatch_order`),
never from the URL string (rule 13).

What it does not do, deliberately:

- **It never grants.** The dependency stays the authority on every matched
  route (scope, CSRF, `bearer_refused`); the gate only moves the anonymous
  refusal earlier. If its view of dispatch and the router's ever diverged, the
  worst case is a disclosure the dependency's own 401 still bounds, never an
  allow — `tests/test_auth_unrouted.py` pins the two agree route by route.
- **The `/mcp` mount is left to its child** (family 7): FastMCP's bearer
  middleware owns that credential, a cookie never authenticates there, and the
  `RouteBinding` is its verb boundary (#198 round 3). The gate does not resolve
  a principal for a request the mount claims.
- **Family 8's namespace is the protocol's** (`PROTOCOL_NAMESPACES`, the same
  declaration the ingress alias rejection reads): under `/.well-known/` with no
  route registered — local mode — the router's 404 stands for everyone, because
  discovery is anonymous by protocol and a `Bearer` challenge on a discovery
  URL would be a claim about the resource. No principal is resolved there
  either; in OIDC mode (M6-7) the routes FastMCP installs carry `PROTOCOL` and
  are admitted the same way.
- **Anonymous routes keep their own 405 and 422** — a wrong verb on `/healthz`,
  a malformed login body — because there is no credential to gate on: a path
  whose every matching route is `ANONYMOUS` passes through untouched.
- **The resolver's contract is unchanged**: a presented-and-failed bearer is
  its 401 (`auth.bearer_invalid`, `invalid_token` challenge) here as it was in
  the dependency, on an unrouted path as on a routed one; a stale session
  cookie is `anon` (#188 call (a)), and so earns the bare-`Bearer` 401.

The principal is resolved on a short session of the gate's own, closed before
the handler's transaction opens — the resolver's warning about a second
concurrent session (a read lock held across the handler, found by the test
teardown's TRUNCATE) is about overlap, and there is none: the gate's session
commits and closes before the router runs, and the dependency reads the stashed
principal instead of opening a second resolution. The `last_used_at` touch a
bearer makes is committed by that session.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from re import Pattern

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match, Mount, compile_path, get_route_path
from starlette.types import ASGIApp, Receive, Scope, Send

from app import error_codes
from app.auth.dependency import BEARER_CHALLENGE, REQUEST_PRINCIPAL_ATTR
from app.auth.principal import PrincipalKind
from app.auth.registry import (
    PROTOCOL_NAMESPACES,
    UNROUTED_PROFILE,
    CredentialPolicy,
    RouteIndex,
    iter_dispatch_order,
)
from app.auth.resolver import resolve_principal
from app.db import session_scope
from app.exceptions import DomainError, UnauthenticatedError

#: How the gate renders a refusal: the app's own envelope handler, passed in by
#: `create_app` so the envelope has one author and this module does not import
#: `app.main`.
Renderer = Callable[[Request, DomainError], Awaitable[Response]]

_UNAUTHENTICATED = "You need to sign in to do that."


# --- what the request would reach ------------------------------------------------


class Dispatch(Enum):
    """What Starlette's router would do with the request."""

    MOUNT = "mount"  # a `Mount` claims it; the child decides everything
    PROTOCOL = "protocol"  # under a family-8 namespace with no route: anonymous by protocol
    FULL = "full"  # a route matches path and method
    PARTIAL = "partial"  # a route matches the path, none the method → 405
    NONE = "none"  # nothing matches → 404


@dataclass(frozen=True)
class Outcome:
    kind: Dispatch
    #: The endpoint(s) involved: the one route for FULL, every path-matching
    #: route for PARTIAL (Starlette answers with the first, but the gate asks
    #: whether *any* of them needs a credential), none for MOUNT, PROTOCOL and
    #: NONE.
    endpoints: tuple[object, ...] = ()


@dataclass(frozen=True)
class _Leaf:
    regex: Pattern[str]
    methods: frozenset[str]
    endpoint: object


class DispatchTable:
    """The registry's dispatch walk compiled for matching: each effective
    leaf's path regex (Starlette's own `compile_path`, so `{param}` and
    `{path:path}` mean what they mean to the router) and its **declared**
    method set — exactly the set the registry pins, with no `HEAD` added for a
    `GET` the way Starlette's `Route` would, because FastAPI's `APIRoute` adds
    none and the gate must not pass a verb the router will refuse. Mounts are
    the mount objects themselves, matched through their own `matches`."""

    def __init__(self, entries: tuple[_Leaf | Mount, ...]) -> None:
        self._entries = entries

    @classmethod
    def from_app(cls, app: FastAPI) -> DispatchTable:
        entries: list[_Leaf | Mount] = []
        for entry in iter_dispatch_order(app):
            if isinstance(entry, Mount):
                entries.append(entry)
            else:
                regex, _, _ = compile_path(entry.path)
                entries.append(_Leaf(regex=regex, methods=entry.methods, endpoint=entry.endpoint))
        return cls(tuple(entries))

    def resolve(self, scope: Scope) -> Outcome:
        route_path = get_route_path(scope)
        method = scope["method"]
        partial: list[object] = []
        for entry in self._entries:
            if isinstance(entry, Mount):
                match, _ = entry.matches(scope)
                if match == Match.FULL:
                    return Outcome(Dispatch.MOUNT)
                continue
            if entry.regex.match(route_path) is None:
                continue
            if not entry.methods or method in entry.methods:
                return Outcome(Dispatch.FULL, (entry.endpoint,))
            partial.append(entry.endpoint)
        if partial:
            return Outcome(Dispatch.PARTIAL, tuple(partial))
        if any(route_path.startswith(prefix) for prefix in PROTOCOL_NAMESPACES):
            # Family 8's namespace with nothing registered (local mode): the
            # router's 404 is the protocol's answer, not the gate's 401.
            return Outcome(Dispatch.PROTOCOL)
        return Outcome(Dispatch.NONE)


def refuses_anonymous(index: RouteIndex, outcome: Outcome) -> bool:
    """Whether an anonymous caller is refused before the router runs. A mount
    is the child's; a family-8 namespace with no route is the protocol's 404.
    A full match is refused unless its declared policy admits `anon`
    (`ANONYMOUS`; `INTERNAL` self-guards on the peer; `PROTOCOL` is anonymous
    by protocol). A partial match — the router's 405 — is refused unless
    *every* route on that path is anonymous (or protocol), because an `Allow`
    header on a scoped path is the route table. No match — the router's 404 —
    is refused. An endpoint the registry does not know (impossible after
    `build_route_index`) fails closed."""
    if outcome.kind in (Dispatch.MOUNT, Dispatch.PROTOCOL):
        return False
    if outcome.kind is Dispatch.NONE:
        return True
    admitted = (
        {CredentialPolicy.ANONYMOUS, CredentialPolicy.INTERNAL, CredentialPolicy.PROTOCOL}
        if outcome.kind is Dispatch.FULL
        else {CredentialPolicy.ANONYMOUS, CredentialPolicy.PROTOCOL}
    )
    for endpoint in outcome.endpoints:
        policy = index.policy_for(endpoint)
        if policy is None or policy.credential not in admitted:
            return True
    return False


# --- the middleware -------------------------------------------------------------


class PreRoutingAuthMiddleware:
    def __init__(
        self, app: ASGIApp, *, index: RouteIndex, table: DispatchTable, render: Renderer
    ) -> None:
        self.app = app
        self.index = index
        self.table = table
        self.render = render

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        outcome = self.table.resolve(scope)
        if outcome.kind in (Dispatch.MOUNT, Dispatch.PROTOCOL):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        try:
            async with session_scope() as session:
                principal = await resolve_principal(request, session)
        except UnauthenticatedError as exc:
            await self._refuse(request, exc, scope, receive, send)
            return
        setattr(request.state, REQUEST_PRINCIPAL_ATTR, principal)

        if principal.kind is PrincipalKind.ANON and refuses_anonymous(self.index, outcome):
            refusal = UnauthenticatedError(
                _UNAUTHENTICATED,
                code=error_codes.AUTH_UNAUTHENTICATED,
                challenge=BEARER_CHALLENGE,
            )
            await self._refuse(request, refusal, scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _refuse(
        self, request: Request, exc: DomainError, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """The envelope the exception handler would have rendered — rendered
        here because this layer sits above `ExceptionMiddleware` — with the
        family-13 profile stamped on, since the router never recorded an
        endpoint for the innermost middleware to read."""
        response = await self.render(request, exc)
        cache_control = UNROUTED_PROFILE.cache_control
        if cache_control is not None:
            response.headers["Cache-Control"] = cache_control
        await response(scope, receive, send)
