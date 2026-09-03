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
