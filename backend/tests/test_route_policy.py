"""The route policy registry's enumeration guard (§5.5, §5.8 T1's precursor; #187).

The registry is "default deny, explicit allow, declared once, enumerated by
test". This file is the enumeration: it fails naming any effective route or MCP
tool the registry does not declare, so a new router or tool lands with a policy
or not at all — the mechanism that makes the M8 `/public/*` handlers a
deliberate act (§5.5). The full (family, method, principal, mode) → status
matrix (T1) arrives with the enforcement dependency (#187 phase C); this file
proves the registry the matrix will be generated from is total and pins the
security-relevant classifications.

The principal/scope algebra is unit-tested here too — `write` implies `read`,
admin implies nothing — because the dependency's allow/deny reduces to it.
"""

import re

import pytest
from fastapi import FastAPI
from fastmcp import Client
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.auth.dependency import RouteBinding, allow_header, method_not_allowed
from app.auth.principal import (
    Principal,
    PrincipalKind,
    Scope,
    anonymous,
    internal,
    mcp,
    owner,
    pat,
)
from app.auth.registry import (
    MCP_TOOL_SCOPES,
    MCP_TRANSPORT_POLICY,
    CredentialPolicy,
    DuplicateRouteError,
    RoutePolicy,
    UndeclaredRouteError,
    build_route_index,
    dispatch_pattern,
    iter_effective_routes,
    iter_mounted_routes,
)
from app.main import app, create_app
from app.mcp import mcp as mcp_server

# --- the enumeration ------------------------------------------------------------


def test_every_effective_route_is_declared():
    """`build_route_index` raises `UndeclaredRouteError` naming any route no rule
    classifies. The whole point: an undeclared route fails here, at build, not at
    a first anonymous request that quietly gets the wrong answer."""
    index = build_route_index(app)
    routes = list(iter_effective_routes(app))
    assert routes, "no effective routes resolved — the walk is broken, not the app"
    # One policy per route, keyed by endpoint; no route left unclassified and no
    # two routes silently collapsed onto one endpoint.
    assert len(index.by_endpoint) == len(routes)
    for route in routes:
        assert index.policy_for(route.endpoint) is not None, route.path
    # And the child surface: every route under the mount is declared too, in its
    # own map — the REST dependency's `policy_for` does not know it, because the
    # dependency never runs there; the route binding reads `mounted_by_endpoint`.
    mounted = list(iter_mounted_routes(app))
    assert mounted, "no mounted routes resolved — the walk lost the /mcp child"
    assert len(index.mounted_by_endpoint) == len(mounted)
    for route in mounted:
        assert index.policy_for(route.endpoint) is None, route.path
        assert index.mounted_by_endpoint[route.endpoint] is not None, route.path


def test_an_undeclared_route_fails_the_build():
    """The guard actually guards: a route the rules do not classify makes the
    build raise. Proven by handing the classifier an app with a bare route no tag
    or name matches, rather than trusting that the real app happens to be total."""
    from fastapi import FastAPI

    probe = FastAPI()

    @probe.get("/unclassified-probe")
    async def _probe():  # pragma: no cover - never called
        return {}

    with pytest.raises(UndeclaredRouteError) as excinfo:
        build_route_index(probe)
    assert "/unclassified-probe" in str(excinfo.value)


# --- the effective HTTP surface, snapshotted (Codex #198 f2) ---------------------
# The enumeration's independent declaration: every REST leaf as
# (path, methods) -> (family, credential), and every route under the /mcp mount as
# (path, methods) -> name. Observed against these, so an added route, an added
# HTTP method, a reclassification, or a NEW route under the mount all fail here —
# `build_route_index` copying `route.methods` into the policy cannot notice a
# method change on its own, and `iter_effective_routes` does not descend the mount.
# Regenerate deliberately when a route legitimately changes.

_REST_SURFACE: dict[tuple[str, str], tuple[int, str]] = {
    ("/auth/login", "POST"): (3, "anonymous"),
    ("/auth/logout", "POST"): (3, "anonymous"),
    ("/auth/oidc/callback", "GET"): (3, "anonymous"),
    ("/auth/oidc/start", "POST"): (3, "anonymous"),
    ("/auth/session", "GET"): (2, "anonymous"),
    ("/auth/setup", "POST"): (3, "anonymous"),
    # Personal access token management (#189): family 6, the owner's session only.
    ("/auth/tokens", "GET"): (6, "admin"),
    ("/auth/tokens", "POST"): (6, "admin"),
    ("/auth/tokens/{token_id}", "DELETE"): (6, "admin"),
    ("/catalog/search", "GET"): (4, "read"),
    ("/catalog/{catalog_id}/adjust", "POST"): (5, "write"),
    ("/consumables", "GET"): (4, "read"),
    ("/consumables", "POST"): (5, "write"),
    ("/consumables/categories", "GET"): (4, "read"),
    ("/consumables/{consumable_id}", "DELETE"): (5, "write"),
    ("/consumables/{consumable_id}", "PATCH"): (5, "write"),
    ("/display-items", "GET"): (4, "read"),
    ("/display-items", "POST"): (5, "write"),
    ("/display-items/categories", "GET"): (4, "read"),
    ("/display-items/{display_item_id}", "DELETE"): (5, "write"),
    ("/display-items/{display_item_id}", "PATCH"): (5, "write"),
    ("/docs", "GET"): (11, "read"),
    ("/export/archive", "GET"): (4, "read"),
    ("/export/starter-sheet.csv", "GET"): (4, "read"),
    ("/export/templates", "GET"): (4, "read"),
    ("/export/{table_key}.csv", "GET"): (4, "read"),
    ("/healthz", "GET"): (9, "anonymous"),
    ("/import/apply", "POST"): (5, "write"),
    ("/import/preview", "POST"): (5, "write"),
    ("/kits", "GET"): (4, "read"),
    ("/kits", "POST"): (5, "write"),
    ("/kits/series", "GET"): (4, "read"),
    ("/kits/{kit_id}", "DELETE"): (5, "write"),
    ("/kits/{kit_id}", "GET"): (4, "read"),
    ("/kits/{kit_id}", "PATCH"): (5, "write"),
    ("/kits/{kit_id}/applications", "GET"): (4, "read"),
    ("/meta", "GET"): (4, "read"),
    ("/openapi.json", "GET"): (11, "read"),
    ("/orders", "GET"): (4, "read"),
    ("/orders", "POST"): (5, "write"),
    ("/orders/{order_id}", "DELETE"): (5, "write"),
    ("/orders/{order_id}", "GET"): (4, "read"),
    ("/orders/{order_id}", "PATCH"): (5, "write"),
    ("/orders/{order_id}/receive", "POST"): (5, "write"),
    ("/orders/{order_id}/ship", "POST"): (5, "write"),
    ("/readyz", "GET"): (10, "internal"),
    ("/redoc", "GET"): (11, "read"),
    ("/retailers", "GET"): (4, "read"),
    ("/retailers", "POST"): (5, "write"),
    ("/retailers/{retailer_id}", "DELETE"): (5, "write"),
    ("/retailers/{retailer_id}", "PATCH"): (5, "write"),
    ("/settings", "GET"): (4, "read"),
    ("/settings", "PATCH"): (6, "admin"),
    ("/tools", "GET"): (4, "read"),
    ("/tools", "POST"): (5, "write"),
    ("/tools/categories", "GET"): (4, "read"),
    ("/tools/{tool_id}", "DELETE"): (5, "write"),
    ("/tools/{tool_id}", "PATCH"): (5, "write"),
    ("/upgrades", "GET"): (4, "read"),
    ("/upgrades", "POST"): (5, "write"),
    ("/upgrades/{upgrade_id}", "DELETE"): (5, "write"),
    ("/upgrades/{upgrade_id}", "PATCH"): (5, "write"),
    ("/upgrades/{upgrade_id}/applications/{application_id}", "DELETE"): (5, "write"),
    ("/upgrades/{upgrade_id}/apply", "POST"): (5, "write"),
}

_MOUNTED_SURFACE: dict[tuple[str, str], str] = {
    # The bearer gate (#189) is the endpoint the enumeration sees; the SDK's
    # transport sits inside it. `*`: the registry's binding is the verb boundary,
    # not the route's metadata (`build_mcp_app`).
    ("/mcp/", "*"): "RequireAuthMiddleware",
}


def _observed_rest_surface() -> dict[tuple[str, str], tuple[int, str]]:
    index = build_route_index(app)
    entries: list[tuple[tuple[str, str], tuple[int, str]]] = []
    for route in index.routes:
        policy = index.policy_for(route.endpoint)
        assert policy is not None
        entries.append(
            ((route.path, ",".join(sorted(route.methods))), (policy.family, policy.credential))
        )
    # Multiplicity is preserved on the way into the dictionary: two leaves on one
    # key would collapse to the later one, hiding a shadowed route (Codex #198
    # round 2, f2A). The build refuses that graph first; this is the test's own
    # independent check, so the snapshot cannot read green through a collapse.
    keys = [key for key, _ in entries]
    assert len(set(keys)) == len(keys), sorted(k for k in keys if keys.count(k) > 1)
    return dict(entries)


def _observed_mounted_surface() -> dict[tuple[str, str], str]:
    return {
        (route.path, ",".join(sorted(route.methods)) or "*"): route.name
        for route in iter_mounted_routes(app)
    }


def test_the_rest_surface_matches_the_snapshot():
    """A new route, an added HTTP method, or a changed family/credential all move
    the observed surface off this pinned declaration. The method half is why the
    snapshot exists: the policy copies `route.methods`, so nothing else compares
    the observed methods against an independent set (Codex #198 f2)."""
    assert _observed_rest_surface() == _REST_SURFACE


def test_the_mounted_surface_matches_the_snapshot():
    """The `/mcp` child is enumerated too, so a route added under the mount fails
    here — `iter_effective_routes` does not descend the mount, and the static MCP
    policy plus the tool map do not enumerate the child HTTP surface (Codex
    #198 f2). This does not wrap the child in the REST dependency; it only sees
    it."""
    assert _observed_mounted_surface() == _MOUNTED_SURFACE


# --- the route graphs the build refuses (Codex #198 round 2, f2A) ---------------
# The snapshot compares the observed graph with a declaration; these prove the
# build itself refuses a graph no declaration can describe, so the guard does not
# depend on the snapshot noticing — each probe is a graph shape, built fresh.


async def _transport(scope, receive, send):  # pragma: no cover - never called
    pass


def test_two_routes_on_one_dispatch_entry_fail_the_build():
    """Starlette serves the first route matching a (path, method); a second on the
    same entry is unreachable and its declared policy describes nothing — the
    shadow the observed-surface dictionary collapsed (round 2, f2A: a probe
    `GET /tools` named `healthz` ahead of the real one answered anonymously).
    The build refuses it, naming both, before any snapshot is compared."""
    probe = FastAPI()

    async def shadow():  # pragma: no cover - never called
        return {"review_probe": "shadow handler"}

    async def genuine():  # pragma: no cover - never called
        return {}

    probe.add_api_route("/tools", shadow, methods=["GET"], name="healthz")
    probe.add_api_route("/tools", genuine, methods=["GET"], tags=["inventory"])
    with pytest.raises(DuplicateRouteError) as excinfo:
        build_route_index(probe)
    assert "GET /tools" in str(excinfo.value)
    assert "healthz" in str(excinfo.value)


def test_a_renamed_path_parameter_is_the_same_dispatch_entry():
    """`/kits/{kit_id}` and `/kits/{id}` compile to the same matcher, so the second
    is as unreachable as an exact duplicate — the key is the pattern, not the
    spelling."""
    assert dispatch_pattern("/kits/{kit_id}") == dispatch_pattern("/kits/{id}") == "/kits/{}"
    assert dispatch_pattern("/kits/{kit_id}") != dispatch_pattern("/kits/series")
    probe = FastAPI()

    async def first(kit_id: str):  # pragma: no cover - never called
        return {}

    async def second(id: str):  # pragma: no cover - never called
        return {}

    probe.add_api_route("/kits/{kit_id}", first, methods=["GET"], tags=["kits"])
    probe.add_api_route("/kits/{id}", second, methods=["GET"], tags=["kits"])
    with pytest.raises(DuplicateRouteError):
        build_route_index(probe)


def test_one_endpoint_on_two_routes_fails_the_build():
    """The index is keyed on the endpoint callable, so one function registered on
    two routes could carry only one policy — refused rather than resolved to
    whichever route came last. Two different, individually declared families,
    so the collapse would have been a wrong policy, not merely a lost one."""
    probe = FastAPI()

    async def shared():  # pragma: no cover - never called
        return {}

    probe.add_api_route("/kits", shared, methods=["GET"], tags=["kits"])
    probe.add_api_route("/settings", shared, methods=["PATCH"], tags=["settings"])
    with pytest.raises(DuplicateRouteError) as excinfo:
        build_route_index(probe)
    assert "shares its endpoint" in str(excinfo.value)


def test_a_wildcard_route_beside_a_method_route_fails_the_build():
    """A raw ASGI route (`methods=None`, every verb) on the same pattern as a
    method-specific one leaves one of them partly unreachable, whichever is first
    — refused as the same ambiguity."""
    child = Starlette(
        routes=[
            Route("/", endpoint=_transport),
            Route("/", endpoint=_transport.__class__, methods=["GET"]),
        ]
    )
    probe = FastAPI()
    probe.mount("/mcp", child)
    with pytest.raises(DuplicateRouteError):
        build_route_index(probe)


def test_an_unrecognised_route_type_fails_the_build():
    """The walk refuses what it cannot enumerate rather than skipping it: a
    WebSocket route passed over silently would be the same hole as an
    undeclared route."""
    probe = FastAPI()

    async def socket(websocket):  # pragma: no cover - never called
        pass

    probe.add_api_websocket_route("/ws", socket)
    with pytest.raises(UndeclaredRouteError) as excinfo:
        build_route_index(probe)
    assert "WebSocketRoute" in str(excinfo.value)
    assert "/ws" in str(excinfo.value)


def test_a_route_added_under_the_mount_fails_the_build():
    """Round 1's probe (`/mcp/review-undeclared`), refused at build and not only
    by the snapshot: the child surface is declared (`_classify_mounted`), so an
    extra route under `/mcp` — or under a mount nested inside it, which the
    walk descends — is undeclared. The transport alone is declared and builds."""

    async def handler(request):  # pragma: no cover - never called
        pass

    async def nested_handler(request):  # pragma: no cover - never called
        pass

    child = Starlette(
        routes=[
            Route("/", endpoint=_transport),
            Route("/review-undeclared", endpoint=handler),
            Mount("/nested", app=Starlette(routes=[Route("/leaf", endpoint=nested_handler)])),
        ]
    )
    probe = FastAPI()
    probe.mount("/mcp", child)
    with pytest.raises(UndeclaredRouteError) as excinfo:
        build_route_index(probe)
    assert "/mcp/review-undeclared" in str(excinfo.value)
    assert "/mcp/nested/leaf" in str(excinfo.value)

    alone = FastAPI()
    alone.mount("/mcp", Starlette(routes=[Route("/", endpoint=_transport)]))
    index = build_route_index(alone)
    assert index.mounted_by_endpoint[_transport] is MCP_TRANSPORT_POLICY
    assert index.policy_for(_transport) is None


def test_a_bare_asgi_mount_is_a_leaf_of_its_own():
    """A mount whose app has no route table (a raw callable) is itself the leaf —
    Starlette puts that app in `scope["endpoint"]` — and, undeclared, fails the
    build naming the mount's path."""
    probe = FastAPI()
    probe.mount("/raw", _transport)
    with pytest.raises(UndeclaredRouteError) as excinfo:
        build_route_index(probe)
    assert "/raw" in str(excinfo.value)


# --- the accepted methods, behaviourally (Codex #198 round 2, f2B) ---------------
# Route metadata declares the methods of a REST route and nothing for a raw ASGI
# endpoint (`methods=None`): which verbs `/mcp/` accepts only its implementation
# knows, so no snapshot of the metadata can see a transport that starts answering
# PUT. The method axis is therefore pinned by asking: every verb in a literal
# universe, against the real app, is 405 exactly when the declaration does not
# hold it. The declaration is the literal snapshot above, not `route.methods`.

_METHOD_UNIVERSE = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT")
#: One verb outside every registry, so the boundary is shown to be an allowlist
#: and not a longer denylist (Codex #198 round 3, f2).
_EXTENSION_METHOD = "REVIEW198"


def _probe_path(path: str) -> str:
    # A parameter's value is irrelevant to dispatch: any segment matches, and a
    # bad one earns a 404/422 from the handler's side — never a 405.
    return re.sub(r"\{[^}]*\}", "probe", path)


def _matches(pattern: str, url: str) -> bool:
    # The snapshot's own matcher: a parameter is one non-empty segment, as it is
    # for Starlette's default convertor — so `/kits/series` is matched by both
    # `/kits/series` and `/kits/{kit_id}`, and a verb the literal route lacks is
    # served by the parameter route, not refused. Derived from the literal
    # snapshot, never from `app.routes`.
    literal = re.split(r"\{[^}]*\}", pattern)
    return re.fullmatch("[^/]+".join(re.escape(part) for part in literal), url) is not None


def _declared_methods_for(url: str) -> set[str]:
    return {
        verb
        for path, methods in _REST_SURFACE
        if _matches(path, url)
        for verb in methods.split(",")
    }


@pytest.mark.parametrize("path", sorted({path for path, _ in _REST_SURFACE}))
async def test_every_rest_path_is_405_exactly_off_its_declared_methods(path, http_client):
    """A probe URL for each REST path answers 405 for every verb no declared
    route matching that URL holds, and something other than 405 for every verb
    one does — and never advertises in `Allow` a verb the snapshot lacks. A
    route gaining a method, or a method the snapshot names that the app stopped
    serving, fails here on behaviour, independently of the metadata comparison."""
    url = _probe_path(path)
    declared = _declared_methods_for(url)
    assert declared, url
    for method in _METHOD_UNIVERSE:
        resp = await http_client.request(method, url)
        if method in declared:
            assert resp.status_code != 405, (method, url, resp.status_code)
        else:
            assert resp.status_code == 405, (method, url, resp.status_code)
            allowed = {verb.strip() for verb in resp.headers["allow"].split(",")}
            assert allowed <= declared, (method, url, allowed)


_TRANSPORT_DECLARED = {"GET", "POST", "DELETE"}  # the literal; the registry must agree


def _transport_route(live):
    mount = next(r for r in live.routes if isinstance(r, Mount) and r.path == "/mcp")
    return next(r for r in mount.routes if r.path == "/")


async def _live_client(live):
    transport = ASGITransport(app=live, client=("127.0.0.1", 123), raise_app_exceptions=False)
    return AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000", headers={"Host": "localhost"}
    )


async def test_the_mcp_transport_accepts_exactly_the_declared_methods():
    """`/mcp/` is a raw ASGI endpoint — its Starlette metadata is `methods=None`,
    so no snapshot of it can see which verbs the implementation accepts (round
    2, f2B). On the enforced app the registry's declared set is the dispatch
    boundary (`RouteBinding`): every verb outside it — the universe, plus an
    extension verb no registry holds — is 405 with `Allow` naming exactly the
    declared set, and every declared verb reaches the transport (a 406/400 for
    a bare request, never 405 or 404)."""
    assert MCP_TRANSPORT_POLICY.methods == frozenset(_TRANSPORT_DECLARED)
    live = create_app(authorization=True)
    async with live.router.lifespan_context(live):
        async with await _live_client(live) as client:
            for method in (*_METHOD_UNIVERSE, _EXTENSION_METHOD):
                resp = await client.request(method, "/mcp/")
                if method in _TRANSPORT_DECLARED:
                    assert resp.status_code not in (404, 405), (method, resp.status_code)
                else:
                    assert resp.status_code == 405, (method, resp.status_code)
                    allowed = {verb.strip() for verb in resp.headers["allow"].split(",")}
                    assert allowed == _TRANSPORT_DECLARED, (method, allowed)


async def test_the_transport_binding_refuses_undeclared_verbs_before_the_sdk_runs():
    """Round 3, f2: the boundary is in front of the implementation, not a finite
    list of verbs the test happens to try. The SDK's callable inside the binding
    is replaced by a stub that accepts *everything*; every undeclared verb —
    PUT, CONNECT, the extension verb — is still refused by the binding with the
    SDK-shaped protocol error, and the stub is never invoked for them, while a
    declared verb reaches the stub."""
    live = create_app(authorization=True)
    binding = _transport_route(live).app
    assert isinstance(binding, RouteBinding)
    reached: list[str] = []

    async def accepts_everything(scope, receive, send):
        reached.append(scope["method"])
        await JSONResponse({"review_probe": "accepted"})(scope, receive, send)

    binding.app = accepts_everything
    async with live.router.lifespan_context(live):
        async with await _live_client(live) as client:
            for method in ("PUT", "CONNECT", _EXTENSION_METHOD):
                resp = await client.request(method, "/mcp/")
                assert resp.status_code == 405, (method, resp.status_code)
                assert resp.json()["error"]["message"] == "Method Not Allowed"
                assert resp.headers["allow"] == "GET, POST, DELETE"
                assert resp.headers.get_list("cache-control") == ["no-store"]
            assert reached == []
            accepted = await client.post("/mcp/")
            assert accepted.status_code == 200 and accepted.json() == {"review_probe": "accepted"}
            assert reached == ["POST"]


async def test_the_binding_refusal_is_the_sdk_protocol_error():
    """The boundary preserves the transport's own refusal: status, `Allow`,
    content type and the JSON-RPC body of the binding's 405 equal what the SDK
    itself answers for a verb it knows how to refuse (PUT on the unenforced app,
    where the SDK is reached). The one difference is deliberate: no
    `mcp-session-id`, because a refused verb creates no session."""
    plain = create_app()
    async with plain.router.lifespan_context(plain):
        async with await _live_client(plain) as client:
            sdk = await client.put("/mcp/")
    assert sdk.status_code == 405 and "mcp-session-id" in sdk.headers  # the SDK was reached
    ours = method_not_allowed(MCP_TRANSPORT_POLICY)
    assert ours.status_code == sdk.status_code
    assert ours.headers["allow"] == sdk.headers["allow"]
    assert ours.headers["content-type"] == sdk.headers["content-type"]
    assert ours.body == sdk.content
    assert "mcp-session-id" not in ours.headers
    assert allow_header({"DELETE", "POST", "GET", "REVIEW198", "PATCH"}) == (
        "GET, POST, PATCH, DELETE, REVIEW198"
    )


def test_every_mounted_route_is_bound_on_the_enforced_app_and_none_on_the_unenforced():
    """The binding is the outermost callable of every mounted route on an enforced
    app, carrying that route's declared policy — so a wrapper installed above it,
    or a route left unbound, is a graph the enforced app does not have. An
    unenforced app (`create_app()` with the default off — what the ingress and
    packaged-stack harnesses build) binds nothing. The shipped `app` is enforced
    since M6-3, so it is *not* the unenforced case here."""
    live = create_app(authorization=True)
    index = live.state.route_index
    assert index.mounted_routes, "no mounted routes — the walk lost the /mcp child"
    for mounted in index.mounted_routes:
        assert isinstance(mounted.route.app, RouteBinding), mounted.path
        assert mounted.route.app.policy is index.mounted_by_endpoint[mounted.endpoint]
    for mounted in build_route_index(create_app()).mounted_routes:
        assert not isinstance(mounted.route.app, RouteBinding), mounted.path


def test_the_mcp_tool_scope_map_matches_the_live_registry():
    """Every registered MCP tool has a declared scope, and every declared scope
    names a live tool — so a new tool cannot ship unscoped and a removed one
    cannot leave a dangling declaration (§5.6, scope escalation)."""

    async def _live_tools() -> set[str]:
        async with Client(mcp_server) as client:
            return {tool.name for tool in await client.list_tools()}

    import asyncio

    live = asyncio.run(_live_tools())
    declared = set(MCP_TOOL_SCOPES)
    assert live - declared == set(), f"MCP tools with no declared scope: {live - declared}"
    assert declared - live == set(), f"declared scopes for tools that are gone: {declared - live}"


def test_every_mutating_tool_holds_write_and_reads_hold_read():
    """The scope map's shape, not just its coverage: a tool whose name says it
    mutates (create/update/delete/adjust/apply/mark/withdraw) must require
    `collection:write`, and the read tools must require `collection:read` — the
    invariant a `pat:read`/`mcp` read grant relies on to be unable to mutate."""
    write_verbs = ("create", "update", "delete", "adjust", "apply", "mark", "withdraw")
    for name, scope in MCP_TOOL_SCOPES.items():
        mutating = name.startswith(write_verbs)
        expected = Scope.WRITE if mutating else Scope.READ
        assert scope is expected, f"{name} declared {scope}, expected {expected}"


# --- the security-relevant classifications --------------------------------------
# Not a full snapshot (that is T1, phase C) — the handful of routes where a wrong
# family is a real exposure, pinned so a refactor that misclassifies one is red.


def _policy(path: str, method: str) -> RoutePolicy:
    index = build_route_index(app)
    for route in index.routes:
        if route.path == path and method in route.methods:
            policy = index.policy_for(route.endpoint)
            assert policy is not None, f"{method} {path} unclassified"
            return policy
    raise AssertionError(f"no route {method} {path}")


@pytest.mark.parametrize(
    "path,method,family,credential",
    [
        ("/meta", "GET", 4, CredentialPolicy.READ),
        ("/settings", "GET", 4, CredentialPolicy.READ),
        # PATCH /settings reconfigures the instance — admin, not write (§5.5 fam 6).
        ("/settings", "PATCH", 6, CredentialPolicy.ADMIN),
        ("/kits", "GET", 4, CredentialPolicy.READ),
        ("/kits", "POST", 5, CredentialPolicy.WRITE),
        ("/export/archive", "GET", 4, CredentialPolicy.READ),
        # import/apply enters as write; the admin escalation is on the plan, in
        # the service — the static policy must be write, not admin or read.
        ("/import/preview", "POST", 5, CredentialPolicy.WRITE),
        ("/import/apply", "POST", 5, CredentialPolicy.WRITE),
        ("/healthz", "GET", 9, CredentialPolicy.ANONYMOUS),
        ("/readyz", "GET", 10, CredentialPolicy.INTERNAL),
        ("/openapi.json", "GET", 11, CredentialPolicy.READ),
    ],
)
def test_sensitive_routes_are_classified_as_intended(path, method, family, credential):
    policy = _policy(path, method)
    assert (policy.family, policy.credential) == (family, credential)


def test_no_store_on_collection_and_admin_reads_not_on_liveness():
    """T10's structural half: every family-4/5/6/11 response carries
    `Cache-Control: no-store`; liveness and readiness do not."""
    assert _policy("/kits", "GET").response.no_store is True
    assert _policy("/settings", "PATCH").response.no_store is True
    assert _policy("/openapi.json", "GET").response.no_store is True
    assert _policy("/healthz", "GET").response.no_store is False
    assert _policy("/readyz", "GET").response.no_store is False


# --- the principal/scope algebra ------------------------------------------------


def test_write_implies_read_admin_implies_nothing():
    assert pat(write=True).has_scope(Scope.READ)
    assert pat(write=True).has_scope(Scope.WRITE)
    assert not pat(write=False).has_scope(Scope.WRITE)
    assert pat(write=False).has_scope(Scope.READ)
    # The owner holds all three explicitly; admin does not conjure read/write.
    holder = owner()
    assert holder.has_scope(Scope.READ) and holder.has_scope(Scope.ADMIN)
    admin_only = internal().__class__(kind=PrincipalKind.OWNER, scopes=frozenset({Scope.ADMIN}))
    assert admin_only.has_scope(Scope.ADMIN)
    assert not admin_only.has_scope(Scope.READ)


def test_a_write_only_scope_set_reads_through_the_implication():
    """The implication itself, not the factory. `pat(write=True)` holds both
    scopes, so `has_scope(READ)` is answered by direct membership and never needs
    the `write ⇒ read` branch — which is why the mutant that makes that branch a
    no-op survived (Codex #198 f3). A principal holding ONLY `collection:write`
    (which no factory produces — the pat factory always adds read) must still
    satisfy a read requirement, and does so only through the implication."""
    write_only = Principal(kind=PrincipalKind.PAT, scopes=frozenset({Scope.WRITE}))
    assert write_only.has_scope(Scope.READ) is True  # False under the mutant
    assert write_only.has_scope(Scope.WRITE) is True
    # Negative controls, so the assertion is the implication and not a tautology:
    read_only = Principal(kind=PrincipalKind.PAT, scopes=frozenset({Scope.READ}))
    assert read_only.has_scope(Scope.WRITE) is False
    admin_only = Principal(kind=PrincipalKind.OWNER, scopes=frozenset({Scope.ADMIN}))
    assert admin_only.has_scope(Scope.READ) is False
    # And through the read policy the dependency reduces to: a write-only grant is
    # permitted on a read route.
    assert RoutePolicy(family=4, credential=CredentialPolicy.READ).permits(write_only) is True


def test_labels_match_the_matrix_names():
    assert anonymous().label == "anon"
    assert owner().label == "owner"
    assert internal().label == "internal"
    assert pat(write=False).label == "pat:read"
    assert pat(write=True).label == "pat:write"
    assert mcp(write=False).label == "mcp:read"
    assert mcp(write=True).label == "mcp:write"


@pytest.mark.parametrize(
    "principal,credential,allowed",
    [
        (anonymous(), CredentialPolicy.ANONYMOUS, True),
        (anonymous(), CredentialPolicy.READ, False),
        (pat(write=False), CredentialPolicy.READ, True),
        (pat(write=False), CredentialPolicy.WRITE, False),
        (pat(write=True), CredentialPolicy.WRITE, True),
        (pat(write=True), CredentialPolicy.ADMIN, False),
        (owner(), CredentialPolicy.ADMIN, True),
        (mcp(write=True), CredentialPolicy.WRITE, True),
        (mcp(write=True), CredentialPolicy.ADMIN, False),
    ],
)
def test_route_policy_permits_matches_the_scope_algebra(principal, credential, allowed):
    policy = RoutePolicy(family=0, credential=credential)
    assert policy.permits(principal) is allowed
