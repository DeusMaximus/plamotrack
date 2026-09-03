"""The route policy registry (§5.5, "default deny, explicit allow, declared once,
enumerated by test").

Nothing in the route table can supply an authorization policy: §5.1 counts
fifteen top-level entries, eight of them FastAPI's lazy `_IncludedRouter`
wrappers, expanding to the effective routes plus the MCP mount, and `/docs` and
`/openapi.json` are the same route type with the same flags yet want different
exposure. So the policy is *declared* here, once, and three things read it:

- the app-level default-deny dependency (`app/auth/dependency.py`, #187 phase C),
  matched on the **resolved endpoint** — never the URL string, so no encoding or
  doubled slash can select a different policy than the handler it reaches;
- the ingress template's rejection list (generated from the declared external
  spellings, replacing item 1's typed list — the phase that lands with the nginx
  generation);
- the T1/T2 authorization matrix, generated from the registry so a new route
  without a declaration fails the enumeration test rather than waiting for a
  reviewer.

The enumeration test (`tests/test_route_policy.py`) walks every effective route
and every registered MCP tool and fails naming anything the registry does not
declare — which is what makes the M8 `/public/*` handlers, or a new router, a
deliberate act rather than an accident.

**What M6-2 populates.** Every route that exists today, plus the MCP tool scope
map. The family-2/3 auth routes (#188), family-8 OAuth routes (#192) and their
protocol roles do not exist yet; their declarations arrive with the code that
adds the routes, and the registry's job then is to already own the shape they
slot into. The `CredentialPolicy` and `ResponseProfile` types carry the OAuth
fields (protocol role, redirect destinations, modes) so those items extend
rather than reshape this.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute, Mount, Route

from app.auth.principal import Principal, Scope

# --- the policy value ------------------------------------------------------------


class CredentialPolicy:
    """What the app-level dependency requires of a route's principal. A small
    closed set, because the dependency is a switch over exactly these:

    - `ANONYMOUS` — allowed with no credential (SPA, `/auth/session`, the auth
      actions, liveness). A presented-and-failed credential is still 401 (the
      resolver decides that before the dependency sees a principal).
    - `READ` / `WRITE` / `ADMIN` — the named scope is required; `anon` is 401 and
      an authenticated principal without the scope is 403.
    - `INTERNAL` — the raw TCP peer must be loopback; any other peer gets the
      same 404 an unrouted path earns (readiness is not something to hand to
      whoever can reach the port, §5.5 family 10).
    - `MCP_TRANSPORT` — bearer only, with the per-tool scope check inside the
      tool wrapper (the REST dependency does not wrap the mount); a cookie never
      authenticates here (§5.5 family 7).
    - `PROTOCOL` — FastMCP owns the route (family 8, OIDC mode only); the
      resource-bearer dependency does not wrap it.

    Values are the identifiers used in the matrix and audit; stable.
    """

    ANONYMOUS = "anonymous"
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    INTERNAL = "internal"
    MCP_TRANSPORT = "mcp_transport"
    PROTOCOL = "protocol"


#: The scope a `READ`/`WRITE`/`ADMIN` credential policy requires. `ANONYMOUS`,
#: `INTERNAL`, `MCP_TRANSPORT` and `PROTOCOL` are not scope decisions and map to
#: nothing here.
_POLICY_SCOPE: dict[str, Scope] = {
    CredentialPolicy.READ: Scope.READ,
    CredentialPolicy.WRITE: Scope.WRITE,
    CredentialPolicy.ADMIN: Scope.ADMIN,
}


@dataclass(frozen=True)
class ResponseProfile:
    """The non-authorization attributes of a route's response the registry pins,
    so the matrix asserts them and a library change that alters one is noticed
    (§5.5). M6-2 uses `no_store`; the cookie/challenge/caching fields are here
    for #188/#192 to fill without reshaping the type.

    `no_store` — `Cache-Control: no-store`. Every collection and auth response
    carries it (§5.6, credential leakage; T10): a read that a `no-store` header
    keeps out of a shared cache cannot leak the collection to the next user of a
    proxy. The SPA shell, liveness and readiness do not (static assets cache;
    `/healthz` and `/readyz` carry nothing worth withholding).
    """

    no_store: bool = False
    #: `public, max-age=…` for discovery documents (#192). None → no explicit
    #: caching directive from the app.
    cache: str | None = None


@dataclass(frozen=True)
class RoutePolicy:
    """The declared policy for one effective route (or the MCP mount).

    `family` is §5.5's route-family number. `credential` is the `CredentialPolicy`
    the dependency enforces. `methods` is the route's declared effective method
    set, pinned so a library release that adds `OPTIONS` or `HEAD` fails the
    enumeration test instead of being accepted silently. `spellings` is the set
    of external spellings the ingress forwards to this route — everything else is
    404 before the generic `/api/` location (§5.5, "one spelling per family").
    """

    family: int
    credential: str
    methods: frozenset[str] = field(default_factory=frozenset)
    response: ResponseProfile = field(default_factory=ResponseProfile)
    #: The external spellings nginx forwards here. For a family-4/5/6 route this
    #: is `/api/<path>`; for the root-canonical routes (`/openapi.json`, the MCP
    #: mount, `/.well-known/*`) it is the root spelling; `internal` marks a route
    #: reachable only from inside (readiness). Used by the ingress generation and
    #: T2; declared here so the rejection list is not hand-maintained.
    spellings: frozenset[str] = field(default_factory=frozenset)

    @property
    def required_scope(self) -> Scope | None:
        return _POLICY_SCOPE.get(self.credential)

    def permits(self, principal: Principal) -> bool:
        """Whether the app-level dependency lets this principal reach the route.
        The scope decision only; the resolver has already turned a
        presented-and-failed credential into a 401 before this runs, and the
        `INTERNAL`/`MCP_TRANSPORT`/`PROTOCOL` policies are decided outside the
        scope switch (peer for readiness, the tool wrapper for MCP)."""
        scope = self.required_scope
        if scope is None:
            # ANONYMOUS permits everyone; INTERNAL/MCP_TRANSPORT/PROTOCOL are not
            # this switch's decision and are handled by their own guards.
            return self.credential == CredentialPolicy.ANONYMOUS
        return principal.has_scope(scope)


# --- effective-route enumeration -------------------------------------------------


@dataclass(frozen=True)
class EffectiveRoute:
    """One resolved leaf route: the path a client sees at the app, the methods,
    the endpoint callable (the runtime match key), and the router tags used to
    classify it."""

    path: str
    methods: frozenset[str]
    endpoint: object
    tags: tuple[str, ...]
    name: str


def _iter_routes(routes: list[BaseRoute], prefix: str) -> Iterator[EffectiveRoute]:
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            # FastAPI's lazy include wrapper: the real routes live on the wrapped
            # APIRouter, offset by the include's prefix. Recurse so a nested
            # include is expanded too (there are none today; cheap insurance).
            context = route.include_context  # type: ignore[attr-defined]
            yield from _iter_routes(route.original_router.routes, prefix + context.prefix)  # type: ignore[attr-defined]
        elif isinstance(route, APIRoute):
            yield EffectiveRoute(
                path=prefix + route.path,
                methods=frozenset(route.methods or ()),
                endpoint=route.endpoint,
                tags=tuple(str(t) for t in route.tags),
                name=route.name,
            )
        elif isinstance(route, Route):
            # The auto Starlette routes: /openapi.json, /docs, /redoc,
            # /docs/oauth2-redirect, and /healthz /readyz (added as api routes but
            # arriving here as plain routes when include_in_schema is off).
            yield EffectiveRoute(
                path=prefix + route.path,
                methods=frozenset(route.methods or ()),
                endpoint=route.endpoint,
                tags=(),
                name=route.name,
            )
        # Mount (the /mcp sub-app) is handled by the caller: the REST dependency
        # does not wrap it, so it is not an endpoint-keyed route here.


def iter_effective_routes(app: FastAPI) -> Iterator[EffectiveRoute]:
    """Every effective leaf route of the FastAPI app, included routers expanded.
    The MCP mount is deliberately excluded — it is family 7, guarded by FastMCP
    and the tool wrappers, not by the endpoint-keyed REST dependency."""
    for route in app.routes:
        if isinstance(route, Mount):
            continue
        yield from _iter_routes([route], "")


# --- the declarations ------------------------------------------------------------
#
# Classification is by router tag and method, with the handful of per-route
# exceptions stated explicitly. Each effective route resolves to exactly one
# policy; `build_route_index` proves the totality and the enumeration test guards
# it. A new router picks up a family here or fails the test — it cannot land
# unclassified.

#: Routers whose GETs are collection reads (family 4) and whose other verbs are
#: collection writes (family 5).
_COLLECTION_TAGS = frozenset({"kits", "inventory", "catalog", "retailers", "orders"})

_SAFE = frozenset({"GET", "HEAD"})

_NO_STORE = ResponseProfile(no_store=True)


def _classify(route: EffectiveRoute) -> RoutePolicy | None:
    """The policy for one effective route, or None if nothing declares it (which
    the enumeration test turns into a failure naming the route)."""
    is_safe = route.methods <= _SAFE
    api_spelling = frozenset({f"/api{route.path}"})
    tags = set(route.tags)

    # Liveness and readiness — declared by endpoint name; they carry no tag.
    if route.name == "healthz":
        return RoutePolicy(9, CredentialPolicy.ANONYMOUS, route.methods, spellings=api_spelling)
    if route.name == "readyz":
        # Reachable only from inside; the ingress rejects /api/readyz (family 10).
        return RoutePolicy(
            10, CredentialPolicy.INTERNAL, route.methods, spellings=frozenset({"internal"})
        )

    # Schema and docs (family 11): FastAPI's generated handlers, root-canonical.
    # `collection:read` after the flip; #188 disables the generated handlers and
    # re-registers them guarded, and drops `/docs/oauth2-redirect` (declared here
    # for coverage until it does).
    if route.name in {"openapi", "swagger_ui_html", "redoc_html", "swagger_ui_redirect"}:
        root = {
            "openapi": "/openapi.json",
            "swagger_ui_html": "/api/docs",
            "redoc_html": "/api/redoc",
            "swagger_ui_redirect": "/api/docs/oauth2-redirect",
        }[route.name]
        return RoutePolicy(
            11, CredentialPolicy.READ, route.methods, _NO_STORE, spellings=frozenset({root})
        )

    if "meta" in tags:
        return RoutePolicy(
            4, CredentialPolicy.READ, route.methods, _NO_STORE, spellings=api_spelling
        )

    if "settings" in tags:
        # GET is a collection read (family 4); PATCH reconfigures the instance and
        # is admin (family 6). A write token cannot change settings via REST.
        credential = CredentialPolicy.READ if is_safe else CredentialPolicy.ADMIN
        family = 4 if is_safe else 6
        return RoutePolicy(family, credential, route.methods, _NO_STORE, spellings=api_spelling)

    if "import/export" in tags:
        # Exports are reads (family 4). Import preview and apply require
        # collection:write to enter (family 5); apply then escalates to admin on
        # the plan's mutations (an instance_settings UPDATE, or replace_all),
        # inside `apply_import` — the static route policy is write.
        credential = CredentialPolicy.READ if is_safe else CredentialPolicy.WRITE
        family = 4 if is_safe else 5
        return RoutePolicy(family, credential, route.methods, _NO_STORE, spellings=api_spelling)

    if tags & _COLLECTION_TAGS:
        credential = CredentialPolicy.READ if is_safe else CredentialPolicy.WRITE
        family = 4 if is_safe else 5
        return RoutePolicy(family, credential, route.methods, _NO_STORE, spellings=api_spelling)

    return None


#: The MCP mount (family 7). Declared separately because it is not an
#: endpoint-keyed FastAPI route: bearer only, the per-tool scope check lives in
#: the tool wrapper, and a cookie never authenticates here. `/mcp/` is the
#: canonical spelling; bare `/mcp` is an ingress-only rewrite (§5.5/§8).
MCP_TRANSPORT_POLICY = RoutePolicy(
    7,
    CredentialPolicy.MCP_TRANSPORT,
    frozenset({"GET", "POST", "DELETE"}),
    _NO_STORE,
    spellings=frozenset({"/mcp/", "/mcp"}),
)


# --- MCP tool scopes -------------------------------------------------------------
#
# The scope each MCP tool requires, read by the scope helper the tool wrappers
# call. Read tools hold `collection:read`; every mutating tool holds
# `collection:write`, so a `pat:read`/`mcp` read grant cannot mutate through a
# tool (§5.6, scope escalation). No tool holds `instance:admin` — import/export
# are deliberately not MCP tools (§12.7), and settings is not a tool. The
# enumeration test pairs this map against the live tool registry and fails on a
# tool that is registered but unlisted, or listed but gone.

MCP_TOOL_SCOPES: dict[str, Scope] = {
    # reads
    "get_meta": Scope.READ,
    "list_kits": Scope.READ,
    "list_kit_series": Scope.READ,
    "get_kit": Scope.READ,
    "search_catalog": Scope.READ,
    "list_catalog_items": Scope.READ,
    "list_catalog_categories": Scope.READ,
    "list_retailers": Scope.READ,
    "list_orders": Scope.READ,
    "get_order": Scope.READ,
    # writes
    "create_kit": Scope.WRITE,
    "update_kit_status": Scope.WRITE,
    "update_kit": Scope.WRITE,
    "create_catalog_tool": Scope.WRITE,
    "create_catalog_consumable": Scope.WRITE,
    "create_catalog_upgrade": Scope.WRITE,
    "create_catalog_display": Scope.WRITE,
    "create_retailer": Scope.WRITE,
    "update_retailer": Scope.WRITE,
    "create_order": Scope.WRITE,
    "update_order": Scope.WRITE,
    "mark_order_received": Scope.WRITE,
    "mark_order_shipped": Scope.WRITE,
    "adjust_stock": Scope.WRITE,
    "update_catalog_tool": Scope.WRITE,
    "update_catalog_consumable": Scope.WRITE,
    "update_catalog_upgrade": Scope.WRITE,
    "update_catalog_display": Scope.WRITE,
    "apply_upgrade": Scope.WRITE,
    "withdraw_upgrade_application": Scope.WRITE,
}


# --- the index -------------------------------------------------------------------


class UndeclaredRouteError(RuntimeError):
    """An effective route no rule in this module classifies. Raised at index
    build so a route lands with a policy or not at all — the enumeration test's
    failure, surfaced the moment the app is built rather than at first request."""


@dataclass(frozen=True)
class RouteIndex:
    """The resolved registry: every effective route's endpoint mapped to its
    policy, plus the MCP mount's policy. The dependency looks a request's
    `scope["endpoint"]` up here; the enumeration test walks `by_endpoint` against
    the live routes and `MCP_TOOL_SCOPES` against the live tool registry."""

    by_endpoint: dict[object, RoutePolicy]
    routes: tuple[EffectiveRoute, ...]
    mcp: RoutePolicy = MCP_TRANSPORT_POLICY

    def policy_for(self, endpoint: object) -> RoutePolicy | None:
        return self.by_endpoint.get(endpoint)


def build_route_index(app: FastAPI) -> RouteIndex:
    """Resolve every effective route to its declared policy, or raise. Called
    once at app build (the dependency reads the result), so an undeclared route
    fails startup — and the test — rather than a request."""
    by_endpoint: dict[object, RoutePolicy] = {}
    routes: list[EffectiveRoute] = []
    undeclared: list[str] = []
    for route in iter_effective_routes(app):
        routes.append(route)
        policy = _classify(route)
        if policy is None:
            undeclared.append(f"{sorted(route.methods)} {route.path} (name={route.name})")
            continue
        by_endpoint[route.endpoint] = policy
    if undeclared:
        raise UndeclaredRouteError(
            "route policy registry declares no policy for: " + "; ".join(undeclared)
        )
    return RouteIndex(by_endpoint=by_endpoint, routes=tuple(routes))
