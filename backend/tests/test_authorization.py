"""The authorization matrix, app layer (§5.5, §5.8 T1; #187).

Drives the **real route graph** — `create_app(authorization=True)`, every REST
route the shipped app has — through the default-deny dependency with an injected
principal, and asserts the status, the deny code and the `no-store` profile
§5.5 declares. This is T1's app-layer core, delivered with the foundation; the
shipped app keeps `authorization=False` until the credential mechanisms exist
(#188/#189), which is where the suite-wide switch and the ingress (T2) rows land.

Principal axis on REST scoped routes is `{anon, owner, pat:read, pat:write}`. The
matrix's `mcp → 401` and `internal → 401` cells on REST are the **resolver's**
audience/peer refusal (an MCP token is bound to `/mcp`; `internal` grants only
readiness), enforced in #189/#186 and covered by T5 and the readiness rows — not
the scope dependency, which is why they are not injected here.

The import-apply privilege (§5.5 family 6) is the plan-mutation axis: an
`instance_settings` UPDATE, or `replace_all`, needs admin; an unchanged sheet, a
skipped one (add_only never updates the singleton), or a collection-only plan
does not. Tested on the predicate the wiring will read.

A fresh enforced app is built per test with its lifespan entered — the FastMCP
session manager uses anyio cancel scopes that a module-scoped app would try to
exit in a different task (the same reason `test_ingress` builds per test).
"""

import uuid
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from app import error_codes
from app.auth import anonymous, owner, pat
from app.auth.dependency import ResponseProfileMiddleware
from app.auth.registry import CredentialPolicy, ResponseProfile, RouteIndex, RoutePolicy
from app.auth.resolver import INJECTED_PRINCIPAL_ATTR
from app.db import get_sessionmaker
from app.main import create_app
from app.schemas.portability import ImportMode, RowAction
from app.services.portability.importing import plan_import, plan_requires_admin
from app.services.portability.spec import INSTANCE_SETTINGS

LOOPBACK = ("127.0.0.1", 12345)
OUTSIDE = ("198.51.100.7", 40000)

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test_authorization", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}

# One enforced app for the module. The lifespan is deliberately not entered:
# ASGITransport never runs it, REST needs nothing from it, and the FastMCP
# session manager it would start uses anyio cancel scopes that a per-test async
# fixture exits in the wrong task. `/mcp` is not exercised here (it is family 7,
# #189); every route below is a plain REST route.
_APP = create_app(authorization=True)


async def _request(principal, method, path, *, peer=LOOPBACK, **kw):
    if principal is None:
        if hasattr(_APP.state, INJECTED_PRINCIPAL_ATTR):
            delattr(_APP.state, INJECTED_PRINCIPAL_ATTR)
    else:
        setattr(_APP.state, INJECTED_PRINCIPAL_ATTR, principal)
    transport = ASGITransport(app=_APP, client=peer, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000", headers={"Host": "localhost"}
    ) as client:
        return await client.request(method, path, **kw)


def _unique_retailer() -> dict:
    return {"name": f"Auth Matrix {uuid.uuid4().hex[:8]}"}


# --- reads (family 4): anon 401, every scope holder 200 -------------------------


@pytest.mark.parametrize("path", ["/kits", "/meta", "/settings", "/retailers", "/orders"])
async def test_reads_need_a_read_scope(path):
    assert (await _request(anonymous(), "GET", path)).status_code == 401
    for holder in (owner(), pat(write=False), pat(write=True)):
        resp = await _request(holder, "GET", path)
        assert resp.status_code == 200, (path, holder.label, resp.status_code)


async def test_an_anonymous_read_is_the_unauthenticated_envelope():
    resp = await _request(anonymous(), "GET", "/kits")
    assert resp.status_code == 401
    assert resp.json()["code"] == error_codes.AUTH_UNAUTHENTICATED


# --- writes (family 5): write scope, read is 403 --------------------------------


async def test_a_write_needs_write_scope():
    anon = await _request(anonymous(), "POST", "/retailers", json=_unique_retailer())
    assert anon.status_code == 401
    denied = await _request(pat(write=False), "POST", "/retailers", json=_unique_retailer())
    assert denied.status_code == 403
    assert denied.json()["code"] == error_codes.AUTH_FORBIDDEN
    for holder in (owner(), pat(write=True)):
        created = await _request(holder, "POST", "/retailers", json=_unique_retailer())
        assert created.status_code == 201, (holder.label, created.status_code)


# --- admin (family 6): PATCH /settings needs instance:admin ---------------------


async def test_settings_patch_is_admin_only():
    body = {"time_zone": "Australia/Sydney"}
    assert (await _request(anonymous(), "PATCH", "/settings", json=body)).status_code == 401
    for holder in (pat(write=False), pat(write=True)):
        denied = await _request(holder, "PATCH", "/settings", json=body)
        assert denied.status_code == 403, holder.label
        assert denied.json()["code"] == error_codes.AUTH_FORBIDDEN
    # The owner holds admin, so the request is authorized — it reaches the service
    # (a 2xx), not a 401/403.
    allowed = await _request(owner(), "PATCH", "/settings", json=body)
    assert allowed.status_code not in (401, 403)


# --- anonymous family (9): liveness open to everyone ----------------------------


@pytest.mark.parametrize("principal", [anonymous(), owner(), pat(write=False)])
async def test_liveness_is_anonymous(principal):
    assert (await _request(principal, "GET", "/healthz")).status_code == 200


# --- readiness (family 10): raw loopback peer only ------------------------------


async def test_readiness_answers_the_loopback_peer_and_404s_any_other():
    # The peer decides, not the principal — owner injected both times.
    assert (await _request(owner(), "GET", "/readyz", peer=LOOPBACK)).status_code == 200
    outside = await _request(owner(), "GET", "/readyz", peer=OUTSIDE)
    assert outside.status_code == 404


# --- the response profile: no-store on collection reads, not on liveness --------


async def test_no_store_on_a_collection_read_not_on_liveness():
    read = await _request(owner(), "GET", "/kits")
    assert read.headers.get("cache-control") == "no-store"
    live = await _request(owner(), "GET", "/healthz")
    assert live.headers.get("cache-control") != "no-store"


async def test_no_store_reaches_handler_returned_export_responses():
    """Exports return their own `Response` through `portability._attachment`, which
    a dependency's temporary response object never reaches — so the no-store
    profile is stamped by the response middleware on the way out (Codex #198 f1).
    Every export carries collection data and must not land in a shared cache."""
    await _request(owner(), "POST", "/retailers", json=_unique_retailer())
    for path in (
        "/export/archive",
        "/export/retailers.csv",
        "/export/templates",
        "/export/starter-sheet.csv",
    ):
        resp = await _request(owner(), "GET", path)
        assert resp.status_code == 200, path
        assert resp.headers.get("cache-control") == "no-store", path


async def test_no_store_on_the_deny_envelope_too():
    """A 401/403 on a no-store family carries the header as well — the middleware
    stamps the final response whatever produced it, so the deny path is not the
    gap it was when the dependency owned the header."""
    denied_401 = await _request(anonymous(), "GET", "/kits")
    assert denied_401.status_code == 401
    assert denied_401.headers.get("cache-control") == "no-store"
    denied_403 = await _request(pat(write=False), "POST", "/retailers", json=_unique_retailer())
    assert denied_403.status_code == 403
    assert denied_403.headers.get("cache-control") == "no-store"


# --- the profile is enforced, not defaulted (Codex #198 round 2, f1) ------------
# The real middleware around a synthetic downstream, so the handler's own
# `Cache-Control` is the axis: whatever it set — nothing, an empty value, a
# directive that permits storing, one that only revalidates, `no-store` already,
# the SDK's SSE value, mixed-case directives, two header lines, a capitalised raw
# key — the final header is the declaration. The unscoped negative controls sit
# beside it: a profile with no demand leaves the handler's header alone, and a
# declared cache directive is set verbatim.

_NO_STORE = ResponseProfile(no_store=True)
_PUBLIC = ResponseProfile(cache="public, max-age=3600")
_NO_DEMAND = ResponseProfile()


async def _through_middleware(profile, headers, *, endpoint_resolved=True):
    async def endpoint(scope, receive, send):  # pragma: no cover - the match key only
        pass

    policy = RoutePolicy(family=4, credential=CredentialPolicy.READ, response=profile)
    index = RouteIndex(by_endpoint={endpoint: policy}, routes=())

    async def downstream(scope, receive, send):
        if endpoint_resolved:
            scope["endpoint"] = endpoint
        start = {"type": "http.response.start", "status": 200}
        if headers is not None:
            start["headers"] = list(headers)
        await send(start)
        await send({"type": "http.response.body", "body": b"{}"})

    transport = ASGITransport(app=ResponseProfileMiddleware(downstream, index))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/probe")


@pytest.mark.parametrize(
    "existing,final",
    [
        ([], ["no-store"]),  # absent — the only state setdefault ever handled
        ([b""], ["no-store"]),  # empty value
        ([b"public, max-age=3600"], ["no-store"]),  # permits shared storing
        ([b"private, no-cache"], ["no-store"]),  # revalidates, still stores
        ([b"no-store"], ["no-store"]),  # already right
        ([b"no-cache, no-transform"], ["no-store, no-transform"]),  # the MCP SSE stream's
        ([b"Public, No-Transform, max-age=60"], ["no-store, no-transform"]),  # mixed case
        ([b"public", b"max-age=3600"], ["no-store"]),  # two header lines become one
        ([b"no-transform", b"no-transform"], ["no-store, no-transform"]),  # kept once
    ],
)
async def test_no_store_replaces_every_handler_cache_control_state(existing, final):
    headers = [(b"content-type", b"application/json")]
    headers += [(b"cache-control", value) for value in existing]
    resp = await _through_middleware(_NO_STORE, headers)
    assert resp.status_code == 200
    assert resp.headers.get_list("cache-control") == final
    assert resp.headers["content-type"] == "application/json"  # the rest is untouched


async def test_a_capitalised_raw_cache_control_key_is_replaced_too():
    """A raw ASGI endpoint may spell the key `Cache-Control`; header names are
    case-insensitive, so it is the same header and must not survive beside the
    stamped one (Starlette's `MutableHeaders` would have left it standing)."""
    resp = await _through_middleware(_NO_STORE, [(b"Cache-Control", b"public, max-age=3600")])
    assert resp.headers.get_list("cache-control") == ["no-store"]


async def test_a_start_message_without_headers_gets_the_profile():
    resp = await _through_middleware(_NO_STORE, None)
    assert resp.headers.get_list("cache-control") == ["no-store"]


@pytest.mark.parametrize("existing", [[], [b"public, max-age=3600"], [b"no-store"]])
async def test_a_profile_with_no_demand_leaves_the_handler_header_alone(existing):
    resp = await _through_middleware(_NO_DEMAND, [(b"cache-control", v) for v in existing])
    assert resp.headers.get_list("cache-control") == [v.decode() for v in existing]


@pytest.mark.parametrize("existing", [[], [b"no-store"], [b"private, no-transform"]])
async def test_a_declared_cache_directive_is_set_verbatim(existing):
    """The other declared state (#192's discovery documents): the profile's
    `cache` replaces the handler's value exactly, no retention."""
    resp = await _through_middleware(_PUBLIC, [(b"cache-control", v) for v in existing])
    assert resp.headers.get_list("cache-control") == ["public, max-age=3600"]


async def test_an_unresolved_endpoint_is_left_alone():
    resp = await _through_middleware(
        _NO_STORE, [(b"cache-control", b"public")], endpoint_resolved=False
    )
    assert resp.headers.get_list("cache-control") == ["public"]


def test_a_profile_cannot_be_no_store_and_cacheable():
    with pytest.raises(ValueError):
        ResponseProfile(no_store=True, cache="public, max-age=3600")


# --- the profile on the real graph: the status axis, and the mount ---------------


async def test_no_store_across_the_status_axis():
    """The stamp is on the final response whatever its status: a 405 for a wrong
    verb on a no-store path, a 422 the parser produced before any handler, a
    404 for a row that does not exist — while an unrouted 404 (no endpoint) and
    readiness for an outside peer (a declared no-demand profile) carry nothing."""
    wrong_verb = await _request(owner(), "PUT", "/kits")
    assert wrong_verb.status_code == 405
    assert wrong_verb.headers.get_list("cache-control") == ["no-store"]
    unparsable = await _request(
        owner(), "POST", "/retailers", content=b"{", headers={"Content-Type": "application/json"}
    )
    assert unparsable.status_code == 422
    assert unparsable.headers.get_list("cache-control") == ["no-store"]
    missing = await _request(owner(), "GET", f"/kits/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.headers.get_list("cache-control") == ["no-store"]
    unrouted = await _request(owner(), "GET", "/no-such-route")
    assert unrouted.status_code == 404
    assert "cache-control" not in unrouted.headers
    outside = await _request(owner(), "GET", "/readyz", peer=OUTSIDE)
    assert outside.status_code == 404
    assert "cache-control" not in outside.headers


@asynccontextmanager
async def _enforced_client(principal):
    """A fresh enforced app with its lifespan entered — the FastMCP session manager
    lives there — for the mount's rows; per test, for the cancel-scope reason in
    the module docstring."""
    live = create_app(authorization=True)
    setattr(live.state, INJECTED_PRINCIPAL_ATTR, principal)
    async with live.router.lifespan_context(live):
        transport = ASGITransport(app=live, client=LOOPBACK, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000", headers={"Host": "localhost"}
        ) as client:
            yield client


async def test_the_mcp_transport_carries_no_store_over_the_sdk_header():
    """The mount is declared no-store (tool results are collection data) and the
    dependency never runs there, so the middleware is the only thing that can
    say so — and before this it did not: the transport's endpoint was not in the
    index. The SDK's own SSE header, `no-cache, no-transform`, is exactly the
    handler-set state finding 1 was about: `no-cache` still permits storing, so
    it goes; `no-transform` is kept. Its JSON error responses carry no cache
    header at all and gain one."""
    async with _enforced_client(owner()) as client:
        stream = await client.post("/mcp/", json=INITIALIZE, headers=MCP_HEADERS)
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers.get_list("cache-control") == ["no-store, no-transform"]
        not_acceptable = await client.get("/mcp/")  # no Accept: text/event-stream
        assert not_acceptable.status_code == 406
        assert not_acceptable.headers.get_list("cache-control") == ["no-store"]
        wrong_verb = await client.put("/mcp/")
        assert wrong_verb.status_code == 405
        assert wrong_verb.headers.get_list("cache-control") == ["no-store"]


# --- the shipped app is not enforced (activation is deferred) -------------------


async def test_the_shipped_app_does_not_enforce_yet(client):
    """`create_app()` default is authorization off, so the module-level app the
    suite and uvicorn import still answers anonymously — the foundation ships
    without activating, and CI/e2e stay green until #188 (owner's call)."""
    assert (await client.get("/kits")).status_code == 200


# --- import-apply privilege: the plan-mutation axis (family 6) -------------------


def _settings_csv(**overrides) -> bytes:
    values = {
        "interface_language": "en-AU",
        "formatting_locale": "en-AU",
        "time_zone": "UTC",
        "date_style": "locale",
        "hour_cycle": "locale",
        "reference_currency": "AUD",
    }
    values.update(overrides)
    header = ",".join(INSTANCE_SETTINGS.header)
    row = ",".join(values[name] for name in INSTANCE_SETTINGS.header)
    return f"{header}\n{row}\n".encode()


async def _plan(filename: str, content: bytes, mode: ImportMode):
    async with get_sessionmaker()() as session:
        execution = await plan_import(session, filename, content, mode)
        return execution.plan


def _settings_actions(plan) -> list[RowAction]:
    return [
        row.action
        for table in plan.tables
        if table.table == "instance_settings"
        for row in table.rows
    ]


async def test_a_merge_that_updates_settings_requires_admin():
    plan = await _plan(
        "instance_settings.csv", _settings_csv(time_zone="Australia/Sydney"), ImportMode.MERGE
    )
    # The state axis: the row really is an UPDATE, or the predicate would pass for
    # the wrong reason.
    assert RowAction.UPDATE in _settings_actions(plan)
    assert plan_requires_admin(plan) is True


async def test_add_only_skips_a_settings_change_so_stays_write():
    # add_only never updates the singleton — the sheet is SKIPPED, nothing is
    # mutated, so it stays collection:write (§5.5). The mode axis, pinned.
    plan = await _plan(
        "instance_settings.csv", _settings_csv(time_zone="Australia/Sydney"), ImportMode.ADD_ONLY
    )
    assert RowAction.UPDATE not in _settings_actions(plan)
    assert plan_requires_admin(plan) is False


async def test_an_unchanged_settings_sheet_does_not_require_admin():
    plan = await _plan("instance_settings.csv", _settings_csv(), ImportMode.MERGE)
    assert RowAction.UPDATE not in _settings_actions(plan)
    assert plan_requires_admin(plan) is False


async def test_a_collection_only_merge_does_not_require_admin():
    plan = await _plan("retailers.csv", b"name\nAuth Matrix Import Retailer\n", ImportMode.MERGE)
    assert plan_requires_admin(plan) is False


async def test_replace_all_always_requires_admin():
    plan = await _plan(
        "retailers.csv", b"name\nAuth Matrix Import Retailer\n", ImportMode.REPLACE_ALL
    )
    assert plan_requires_admin(plan) is True
