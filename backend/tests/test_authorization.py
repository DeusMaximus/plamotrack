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

import pytest
from httpx import ASGITransport, AsyncClient

from app import error_codes
from app.auth import anonymous, owner, pat
from app.auth.resolver import INJECTED_PRINCIPAL_ATTR
from app.db import get_sessionmaker
from app.main import create_app
from app.schemas.portability import ImportMode, RowAction
from app.services.portability.importing import plan_import, plan_requires_admin
from app.services.portability.spec import INSTANCE_SETTINGS

LOOPBACK = ("127.0.0.1", 12345)
OUTSIDE = ("198.51.100.7", 40000)

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
