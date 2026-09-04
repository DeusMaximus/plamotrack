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

The enumeration test (`tests/test_route_policy.py`) walks every effective route,
every route under a mount and every registered MCP tool and fails naming
anything the registry does not declare — which is what makes the M8 `/public/*`
handlers, or a new router, a deliberate act rather than an accident. The index
build itself refuses a route graph a declaration cannot describe: two routes on
one dispatch entry, one endpoint on two routes, a route type the walk does not
know (Codex #198 round 2, f2).

**What M6-2 populated.** Every route that existed then, plus the MCP tool scope
map. The family-2/3 auth routes arrived with #188 and the family-6 token routes
with #189 (their declarations are below, beside the routers that add them); the
family-8 OAuth routes (#192) and their protocol roles do not exist yet, and the
registry's job is to already own the shape they slot into. The
`CredentialPolicy` and `ResponseProfile` types carry the OAuth fields (protocol
role, redirect destinations, modes) so those items extend rather than reshape
this.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
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

    The profile is **enforced** on the final response, not defaulted: whatever
    `Cache-Control` a handler or a library set is replaced with the declaration —
    `no-transform` alone survives beside `no-store` — so nothing downstream can
    weaken it (Codex #198 round 2, f1). It is applied **adjacent to the router
    that selects the route** (round 3, f1): for the app's own routes by
    `ResponseProfileMiddleware`, the innermost middleware, which reads the
    endpoint FastAPI's router recorded in the very dict it holds; for every
    route under a mount by a `RouteBinding` on the route itself, below whatever
    middleware the child stacks above its routes — so a middleware that copies
    the scope, which the ASGI contract permits, can lose neither. A profile that
    makes no demand leaves the handler's header as it is.
    """

    no_store: bool = False
    #: `public, max-age=…` for discovery documents (#192). None → no explicit
    #: caching directive from the app.
    cache: str | None = None

    def __post_init__(self) -> None:
        if self.no_store and self.cache is not None:
            raise ValueError(
                "a response profile is no-store or declares a cache directive, not both"
            )

    @property
    def cache_control(self) -> str | None:
        """The `Cache-Control` value this profile requires on the final response,
        or None when it makes no demand and the response keeps whatever the
        handler set."""
        if self.no_store:
            return "no-store"
        return self.cache


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
    #: A bearer-borne principal is refused (403) even though the credential
    #: policy would admit it — the family-3 auth actions (§5.5): a token cannot
    #: log in, log out or claim the instance; those are a browser's, and a
    #: `pat:*` column in the matrix reads 403 there while family 2 admits it.
    bearer_refused: bool = False
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


class UndeclaredRouteError(RuntimeError):
    """An effective route no rule in this module classifies — or a route type the
    walk cannot enumerate. Raised at index build so a route lands with a policy
    or not at all: the enumeration test's failure, surfaced the moment the app
    is built rather than at first request."""


class DuplicateRouteError(RuntimeError):
    """Two effective routes that cannot both carry their declared policy: the same
    dispatch entry (path pattern and method) twice, where Starlette serves the
    first and the second's policy describes nothing a request can reach; or one
    endpoint callable on two routes, where the endpoint-keyed lookup could hold
    only one policy. Refused at build (Codex #198 round 2, f2A)."""


@dataclass(frozen=True)
class EffectiveRoute:
    """One resolved leaf route of the FastAPI app itself: the path a client sees
    at the app, the methods, the endpoint callable (the runtime match key), and
    the router tags used to classify it. The REST dependency runs for these."""

    path: str
    methods: frozenset[str]
    endpoint: object
    tags: tuple[str, ...]
    name: str


@dataclass(frozen=True)
class MountedRoute:
    """One leaf route under a `Mount` (the `/mcp` child): the full external path,
    its declared methods — empty for a raw ASGI endpoint, Starlette's
    `methods=None`, whose accepted verbs only its implementation knows, which is
    why `tests/test_route_policy.py` pins those behaviourally — the endpoint
    callable, and Starlette's name. The REST dependency does not wrap these (they
    are FastMCP's), but the enumeration must *see* and *declare* them, or a route
    added under the mount lands unlisted (Codex #198 f2), and the response
    middleware needs the endpoint to stamp the mount's declared profile."""

    path: str
    methods: frozenset[str]
    endpoint: object
    name: str
    #: The route (or bare-callable `Mount`) object whose `.app` Starlette invokes;
    #: `bind_route_policies` wraps it, so the child's own send carries the profile
    #: and the declared verbs are enforced before the child's implementation runs.
    route: object = field(default=None, compare=False, repr=False)


def _walk(
    routes: Sequence[BaseRoute], prefix: str, *, mounted: bool
) -> Iterator[EffectiveRoute | MountedRoute]:
    """Every leaf under `routes`: included routers expanded, mounts descended
    (nested ones too). A route type the walk does not know is refused, not
    skipped — a `WebSocketRoute` or a `Host` passed over silently would be the
    same hole as an undeclared route."""
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            # FastAPI's lazy include wrapper: the real routes live on the wrapped
            # APIRouter, offset by the include's prefix. Recurse so a nested
            # include is expanded too (there are none today; cheap insurance).
            context = route.include_context  # type: ignore[attr-defined]
            yield from _walk(
                route.original_router.routes,  # type: ignore[attr-defined]
                prefix + context.prefix,
                mounted=mounted,
            )
        elif isinstance(route, Mount):
            # `Mount.routes` is the mounted app's route table — empty when the
            # mounted app is a bare ASGI callable, in which case the mount itself
            # is the leaf and its app is what Starlette puts in `scope["endpoint"]`.
            sub_routes = route.routes
            if sub_routes:
                yield from _walk(sub_routes, prefix + route.path, mounted=True)
            else:
                yield MountedRoute(
                    path=prefix + route.path,
                    methods=frozenset(),
                    endpoint=route.app,
                    name=route.name or type(route.app).__name__,
                    route=route,
                )
        elif isinstance(route, Route):
            path = prefix + route.path
            methods = frozenset(route.methods or ())
            if mounted:
                yield MountedRoute(
                    path=path,
                    methods=methods,
                    endpoint=route.endpoint,
                    name=route.name,
                    route=route,
                )
            else:
                # An APIRoute carries its router's tags; the auto Starlette routes
                # (/openapi.json, /docs, /redoc, /docs/oauth2-redirect) carry none
                # and classify by name, as do /healthz and /readyz.
                tags = tuple(str(t) for t in route.tags) if isinstance(route, APIRoute) else ()
                yield EffectiveRoute(
                    path=path, methods=methods, endpoint=route.endpoint, tags=tags, name=route.name
                )
        else:
            raise UndeclaredRouteError(
                "route policy registry cannot enumerate a "
                f"{type(route).__name__} at {prefix}{getattr(route, 'path', '?')}"
            )


def iter_effective_routes(app: FastAPI) -> Iterator[EffectiveRoute]:
    """Every effective leaf route of the FastAPI app itself, included routers
    expanded — the routes the endpoint-keyed REST dependency runs for. Routes
    under a `Mount` are family 7/8, guarded by FastMCP and the tool wrappers;
    `iter_mounted_routes` enumerates those."""
    for leaf in _walk(app.routes, "", mounted=False):
        if isinstance(leaf, EffectiveRoute):
            yield leaf


def iter_dispatch_order(app: FastAPI) -> Iterator[EffectiveRoute | Mount]:
    """The app's own dispatch order, one entry per thing Starlette's router
    tries in turn: an included router expanded to its effective leaves in
    place, a plain route as a leaf, a `Mount` as itself — the child owns
    everything beneath it, so for dispatch the mount is the unit, not its
    routes. Read by the pre-routing gate (`app/auth/prerouting.py`, #204) to
    decide what a request *would* reach before the router runs; the same walk
    the registry enumerates, so the gate cannot describe a route the registry
    does not."""
    for route in app.routes:
        if isinstance(route, Mount):
            yield route
        else:
            for leaf in _walk([route], "", mounted=False):
                if isinstance(leaf, EffectiveRoute):
                    yield leaf


def iter_mounted_routes(app: FastAPI) -> Iterator[MountedRoute]:
    """Every leaf route under every `Mount`, nested mounts descended, so the
    enumeration covers the child HTTP surface as well as the REST leaves. The
    child owns its own auth (family 7/8); this enumerates it, it does not wrap
    it in the resource-bearer dependency."""
    for leaf in _walk(app.routes, "", mounted=False):
        if isinstance(leaf, MountedRoute):
            yield leaf


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

#: Family 13 (§5.5): everything else under `/api/` — an unrouted path, a wrong
#: verb, a scoped route reached with no credential. Not a route, so not a
#: `RoutePolicy`: the pre-routing gate (`app/auth/prerouting.py`, #204) refuses
#: an anonymous caller there with the dependency's own 401, and this is the
#: profile that refusal carries — the router never ran, so the innermost
#: middleware has no endpoint to stamp from.
UNROUTED_PROFILE = _NO_STORE


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

    if "auth" in tags:
        # Local authentication (§5.5 families 2–3; #188). Anonymous at the
        # dependency: `GET /auth/session` bootstraps the SPA and each action does
        # its own check (the setup token, the password, the presented session).
        # `no-store` — the session response carries the CSRF token. Family 2 is
        # the read, family 3 the actions; both are anonymous, so the split is
        # documentation the matrix asserts, not a scope difference.
        family = 2 if route.path == "/auth/session" else 3
        return RoutePolicy(
            family,
            CredentialPolicy.ANONYMOUS,
            route.methods,
            _NO_STORE,
            spellings=api_spelling,
            # A token is not a browser: the actions refuse a bearer (403), the
            # session read admits one and reports `anonymous` (§5.5, #189).
            bearer_refused=(family == 3),
        )

    if "auth-tokens" in tags:
        # Personal access token management (§5.5 family 6; #189): mint, list,
        # revoke — `instance:admin`, so only the owner's session reaches it and a
        # token cannot mint a token. `no-store`: a mint response carries the
        # secret, once.
        return RoutePolicy(
            6, CredentialPolicy.ADMIN, route.methods, _NO_STORE, spellings=api_spelling
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


def _classify_mounted(route: MountedRoute) -> RoutePolicy | None:
    """The policy for one route under a mount, or None if nothing declares it.
    Today the child surface is exactly the streamable-HTTP transport at `/mcp/`;
    #192's protocol routes (family 8) add their declarations here as they land.
    Until then anything else under a mount is undeclared and fails the build —
    the round-1 probe route (`/mcp/review-undeclared`) is refused here, not only
    by the test's snapshot."""
    if route.path == "/mcp/":
        return MCP_TRANSPORT_POLICY
    return None


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


_PATH_PARAMETER = re.compile(r"\{[^}]*\}")


def dispatch_pattern(path: str) -> str:
    """A route path with its parameter names (and convertors) erased:
    `/kits/{kit_id}` and `/kits/{id}` compile to the same matcher, so they are
    one dispatch entry and the second registered is unreachable."""
    return _PATH_PARAMETER.sub("{}", path)


def _method_label(methods: Iterable[str]) -> str:
    return ",".join(sorted(methods)) or "*"


class _DispatchTable:
    """The (path pattern, methods) entries and the endpoints claimed so far, so a
    second route on an entry — or a raw `*` route beside a method-specific one on
    the same pattern, either of which leaves the other partly or wholly
    unreachable — and a shared endpoint are named rather than absorbed."""

    def __init__(self) -> None:
        self._by_pattern: dict[str, list[tuple[frozenset[str], str]]] = {}
        self._by_endpoint: dict[object, str] = {}
        self.conflicts: list[str] = []

    def claim(self, path: str, methods: frozenset[str], endpoint: object, label: str) -> None:
        pattern = dispatch_pattern(path)
        for other_methods, other in self._by_pattern.get(pattern, ()):
            if not methods or not other_methods or methods & other_methods:
                self.conflicts.append(f"{label} shares dispatch entry {pattern} with {other}")
        self._by_pattern.setdefault(pattern, []).append((methods, label))
        if endpoint in self._by_endpoint:
            self.conflicts.append(f"{label} shares its endpoint with {self._by_endpoint[endpoint]}")
        else:
            self._by_endpoint[endpoint] = label


@dataclass(frozen=True)
class RouteIndex:
    """The resolved registry: every effective REST route's endpoint mapped to its
    policy (`by_endpoint` — what the dependency and the innermost middleware
    read), every mounted route's endpoint mapped to its policy
    (`mounted_by_endpoint` — what `bind_route_policies` binds onto the child's
    routes; the dependency never runs there), and the enumerated routes both
    were built from. The enumeration test walks
    these against the live routes and `MCP_TOOL_SCOPES` against the live tool
    registry."""

    by_endpoint: dict[object, RoutePolicy]
    routes: tuple[EffectiveRoute, ...]
    mounted_by_endpoint: dict[object, RoutePolicy] = field(default_factory=dict)
    mounted_routes: tuple[MountedRoute, ...] = ()
    mcp: RoutePolicy = MCP_TRANSPORT_POLICY

    def policy_for(self, endpoint: object) -> RoutePolicy | None:
        """The policy for one of the app's own routes — what the REST dependency
        enforces and the innermost middleware stamps. A mounted endpoint answers
        None here: the dependency does not wrap the child (its credential policy
        is FastMCP's to enforce) and its response profile is bound onto the
        route itself from `mounted_by_endpoint`."""
        return self.by_endpoint.get(endpoint)


def build_route_index(app: FastAPI) -> RouteIndex:
    """Resolve every effective route — REST leaves and the routes under every
    mount — to its declared policy, or raise. Called once at app build (the
    dependency and the response middleware read the result), so an undeclared
    route fails startup — and the test — rather than a request.

    Refused as well as an undeclared route, because each makes a declared policy
    a lie about what a request reaches (Codex #198 round 2, f2A): two routes on
    one dispatch entry, where Starlette serves the first and the second's policy
    describes nothing; and one endpoint callable on two routes, where the
    endpoint-keyed lookup could hold only one of their policies.
    """
    by_endpoint: dict[object, RoutePolicy] = {}
    routes: list[EffectiveRoute] = []
    mounted_by_endpoint: dict[object, RoutePolicy] = {}
    mounted: list[MountedRoute] = []
    undeclared: list[str] = []
    table = _DispatchTable()
    for leaf in _walk(app.routes, "", mounted=False):
        label = f"{_method_label(leaf.methods)} {leaf.path} (name={leaf.name})"
        table.claim(leaf.path, leaf.methods, leaf.endpoint, label)
        if isinstance(leaf, EffectiveRoute):
            routes.append(leaf)
            policy = _classify(leaf)
            target = by_endpoint
        else:
            mounted.append(leaf)
            policy = _classify_mounted(leaf)
            target = mounted_by_endpoint
        if policy is None:
            undeclared.append(label)
        else:
            target[leaf.endpoint] = policy
    if table.conflicts:
        raise DuplicateRouteError(
            "route policy registry refuses an ambiguous route graph: " + "; ".join(table.conflicts)
        )
    if undeclared:
        raise UndeclaredRouteError(
            "route policy registry declares no policy for: " + "; ".join(undeclared)
        )
    return RouteIndex(
        by_endpoint=by_endpoint,
        routes=tuple(routes),
        mounted_by_endpoint=mounted_by_endpoint,
        mounted_routes=tuple(mounted),
    )


# --- ingress: the /api/ alias rejection list (§5.5, rule 12) ----------------------
#
# The generic `/api/` rewrite in the nginx template makes every root path of the
# API process reachable under `/api/`, so a root-canonical family (its canonical
# spelling is not under `/api/`) has to be refused there before the generic
# location — otherwise the alias reaches the same handler under the same app
# policy while shedding that family's per-location settings (§5.5, "one spelling
# per family"). This is the source of that rejection list: `render_api_alias_
# rejections()` emits the nginx blocks, `scripts/render_ingress.py` writes them
# into the template between its markers, and `tests/test_ingress_generation.py`
# fails if the template drifts from this declaration or a new root-canonical
# route is added without a rejection here. Replaces item 1's hand-typed list.


@dataclass(frozen=True)
class ApiAliasRejection:
    """One root namespace whose `/api/<namespace>` alias nginx answers 404.

    `exact` chooses the nginx location operator: `=` for a single path
    (`/api/openapi.json`, `/api/readyz`), `^~` for a prefix that must also catch
    the namespace's children and encoded spellings (`/api/mcp`, `/api/mcp/…`,
    `/api//mcp/`, `/api/%6dcp/`). `note`, if given, is an explanatory comment
    emitted above the block."""

    namespace: str
    exact: bool
    family: int
    note: str | None = None


#: The root API namespaces rejected under `/api/`. `/.well-known` (family 8) is
#: declared ahead of its routes (#192): the root discovery documents do not exist
#: yet, but their `/api/` alias must be dark from the start, and a registry that
#: only listed live routes could not say so (§5.1 — the route table cannot supply
#: this). `test_ingress_generation.py` proves every root-canonical *live* route is
#: covered here, so a new one cannot slip in unlisted.
API_ALIAS_REJECTIONS: tuple[ApiAliasRejection, ...] = (
    ApiAliasRejection("/mcp", exact=False, family=7),
    ApiAliasRejection("/.well-known", exact=False, family=8),
    ApiAliasRejection("/openapi.json", exact=True, family=11),
    ApiAliasRejection(
        "/readyz",
        exact=True,
        family=10,
        note=(
            "Readiness is for the container healthcheck, which reaches the API from\n"
            "inside its own container (§5.5, family 10). The app answers 404 to any\n"
            "other peer; this is the same decision, duplicated, so a stranger cannot\n"
            "probe whether the database is up. Liveness (/api/healthz) stays open."
        ),
    ),
)

#: The nginx template lines between these markers are generated. Do not edit them
#: by hand — change `API_ALIAS_REJECTIONS` and run `scripts/render_ingress.py`.
NGINX_REJECTIONS_BEGIN = (
    "# >>> generated: /api alias rejections (app/auth/registry.py) — do not edit"
)
NGINX_REJECTIONS_END = "# <<< end generated"

_REJECTION_PREAMBLE = (
    "One spelling per family (§5.5). The generic /api/ rewrite below makes every\n"
    "root path of the API process reachable under /api/, so the families whose\n"
    "canonical spelling is elsewhere are refused here first — after nginx has\n"
    "merged slashes and percent-decoded, so /api//mcp/, /api/%6dcp/ and\n"
    "/api/mcp%2f land on these too. An alias would reach the same handler under\n"
    "the same app policy; what it would shed is this file's per-family settings\n"
    "(buffering, timeouts, the readiness block). Generated from the route policy\n"
    "registry — see the markers above."
)


def _as_comment(text: str, indent: str) -> list[str]:
    return [f"{indent}# {line}" if line else f"{indent}#" for line in text.split("\n")]


def render_api_alias_rejections(indent: str = "    ") -> str:
    """The nginx `location` blocks for `API_ALIAS_REJECTIONS`, as they appear
    between the markers in `frontend/nginx/default.conf.template`. Deterministic:
    the same declaration always renders the same text, byte for byte."""
    lines = list(_as_comment(_REJECTION_PREAMBLE, indent))
    for rejection in API_ALIAS_REJECTIONS:
        if rejection.note:
            lines.extend(_as_comment(rejection.note, indent))
        operator = "=" if rejection.exact else "^~"
        lines.append(f"{indent}location {operator} /api{rejection.namespace} {{")
        lines.append(f"{indent}    return 404;")
        lines.append(f"{indent}}}")
    return "\n".join(lines)
