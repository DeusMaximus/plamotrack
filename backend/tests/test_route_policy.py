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

import pytest
from fastmcp import Client

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
    CredentialPolicy,
    RoutePolicy,
    UndeclaredRouteError,
    build_route_index,
    iter_effective_routes,
    iter_mounted_routes,
)
from app.main import app
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
    ("/docs", "GET,HEAD"): (11, "read"),
    ("/docs/oauth2-redirect", "GET,HEAD"): (11, "read"),
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
    ("/openapi.json", "GET,HEAD"): (11, "read"),
    ("/orders", "GET"): (4, "read"),
    ("/orders", "POST"): (5, "write"),
    ("/orders/{order_id}", "DELETE"): (5, "write"),
    ("/orders/{order_id}", "GET"): (4, "read"),
    ("/orders/{order_id}", "PATCH"): (5, "write"),
    ("/orders/{order_id}/receive", "POST"): (5, "write"),
    ("/orders/{order_id}/ship", "POST"): (5, "write"),
    ("/readyz", "GET"): (10, "internal"),
    ("/redoc", "GET,HEAD"): (11, "read"),
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
    ("/mcp/", "*"): "StreamableHTTPASGIApp",
}


def _observed_rest_surface() -> dict[tuple[str, str], tuple[int, str]]:
    index = build_route_index(app)
    surface: dict[tuple[str, str], tuple[int, str]] = {}
    for route in index.routes:
        policy = index.policy_for(route.endpoint)
        assert policy is not None
        surface[(route.path, ",".join(sorted(route.methods)))] = (policy.family, policy.credential)
    return surface


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
