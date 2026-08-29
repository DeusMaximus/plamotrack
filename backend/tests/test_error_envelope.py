"""The REST error envelope (#25): {detail, code, params}, additive over the old body.

`detail` is the pre-#25 contract, unchanged — string for a domain refusal,
FastAPI's list for request validation, and the whole pre-existing suite passing
untouched is the standing proof nothing about it moved. What this file pins is
the *additive* half and the registries that keep the two sides honest:

- the wire matrix: one endpoint per exception class + the FastAPI 422, each
  asserting the full body (which also pins the envelope's key set), the exact
  code, and params equal to the fixture's declaration for that code;
- the registry: `app/error_codes.py` == the shared fixture
  `frontend/src/lib/__fixtures__/api-error-codes.json` (money-cases.json's
  pattern — the catalogue suite reads the same file from its side);
- code shape: exactly two snake_case segments, because the catalogue key is
  `api.<domain>.<condition>` and the catalogue caps nesting at three levels,
  refusing plural-suffixed leaves that aren't plurals;
- MCP: a ToolError still carries the bare English sentence — no code, no JSON.

`http_client` throughout the wire matrix: the point is which status and body a
failure earns, and a broken handler must read as a 500 body, not a re-raised
exception (rule 6).
"""

import json
import re
import uuid
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app import error_codes
from app.main import app
from app.mcp import mcp

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "frontend/src/lib/__fixtures__/api-error-codes.json"
)
_FIXTURE = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))["codes"]

# i18next's plural suffixes — a code leaf ending in one would collide with the
# catalogue's plural handling for its own `api.*` entry.
_PLURAL_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")


# --- the registry ---------------------------------------------------------------


def test_fixture_and_module_hold_the_same_codes():
    module = set(error_codes.all_codes())
    fixture = set(_FIXTURE)
    assert module == fixture, (
        f"only in app/error_codes.py: {sorted(module - fixture)}; "
        f"only in api-error-codes.json: {sorted(fixture - module)}"
    )


def test_codes_are_exactly_two_snake_case_segments():
    for code in error_codes.all_codes():
        assert re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", code), code


def test_no_two_constants_share_a_code():
    codes = error_codes.all_codes()
    assert len(codes) == len(set(codes))


def test_no_code_leaf_wears_a_plural_suffix():
    for code in error_codes.all_codes():
        leaf = code.rsplit(".", 1)[1]
        assert not leaf.endswith(_PLURAL_SUFFIXES), code


def test_declared_params_are_snake_case_identifiers():
    for code, entry in _FIXTURE.items():
        for param in entry["params"]:
            assert re.fullmatch(r"[a-z0-9_]+", param), f"{code}: {param}"


# --- the wire matrix ------------------------------------------------------------


def _declared(code: str) -> set[str]:
    return set(_FIXTURE[code]["params"])


async def test_404_carries_the_full_envelope(http_client):
    kit_id = uuid.uuid4()
    resp = await http_client.get(f"/kits/{kit_id}")
    assert resp.status_code == 404
    # Full-body equality: this is what pins the envelope's key set to exactly
    # {detail, code, params}, and the params to the fixture's declaration.
    assert resp.json() == {
        "detail": f"kit {kit_id} not found",
        "code": "kit.not_found",
        "params": {"kit_id": str(kit_id)},
    }


async def test_409_with_params_names_the_stock_it_refused(http_client):
    tool = (
        await http_client.post("/tools", json={"name": "Envelope Nippers", "category": "cutting"})
    ).json()
    resp = await http_client.post(f"/catalog/{tool['id']}/adjust", json={"delta": -5})
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "stock.insufficient"
    assert isinstance(body["detail"], str)
    assert body["params"] == {"name": "Envelope Nippers", "on_hand": 0, "requested": 5}
    assert set(body["params"]) == _declared("stock.insufficient")


async def test_409_with_no_params_sends_an_empty_object(http_client, retailer):
    order = (
        await http_client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-08-01",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "tool",
                        "quantity": 1,
                        "unit_price_minor": 100,
                        "currency_code": "AUD",
                        "new_item": {"name": "Envelope Side Cutters", "category": "cutting"},
                    }
                ],
            },
        )
    ).json()
    assert (await http_client.post(f"/orders/{order['id']}/ship")).status_code == 200
    resp = await http_client.post(f"/orders/{order['id']}/ship")
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "order.already_shipped"
    assert body["params"] == {}
    assert _declared("order.already_shipped") == set()


async def test_422_from_the_service_keeps_the_string_detail(http_client):
    resp = await http_client.patch("/settings", json={"date_style": None})
    assert resp.status_code == 422
    body = resp.json()
    # The string-vs-list shape is the pre-#25 discriminator between "the
    # service refused" and "the schema spoke" — both halves pinned, here and below.
    assert isinstance(body["detail"], str)
    assert body["code"] == "settings.field_required"
    assert body["params"] == {"field": "date_style"}


async def test_422_from_request_validation_keeps_the_list_detail(http_client):
    resp = await http_client.post("/kits", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "request.validation"
    assert isinstance(body["detail"], list) and body["detail"]
    for finding in body["detail"]:
        # FastAPI's own finding shape, byte-compatible with the default body.
        assert {"type", "loc", "msg"} <= set(finding)
    assert set(body["params"]) == _declared("request.validation")
    for entry in body["params"]["errors"]:
        assert set(entry) == {"field", "type"}
        # loc[0] (the source, "body") is stripped — the field path stands alone.
        assert not entry["field"].startswith("body")


# --- MCP stays English text -----------------------------------------------------


async def test_tool_error_is_the_bare_sentence():
    kit_id = uuid.uuid4()
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as excinfo:
            await client.call_tool("get_kit", {"kit_id": str(kit_id)})
    # Exact equality: no code prefix, no JSON envelope — the English sentence is
    # the whole MCP surface, exactly as before #25.
    assert str(excinfo.value) == f"kit {kit_id} not found"


# --- OpenAPI --------------------------------------------------------------------


def test_openapi_documents_the_envelope():
    schema = app.openapi()
    components = schema["components"]["schemas"]
    # All three members required, both envelopes: the handlers always emit all
    # three, and a weaker generated client is a contract drift (#169 review, P3).
    assert set(components["ErrorEnvelope"]["required"]) == {"detail", "code", "params"}
    assert set(components["ValidationErrorEnvelope"]["required"]) == {"detail", "code", "params"}
    # Sampled route: the shared responses actually landed on the routers.
    kit_get = schema["paths"]["/kits/{kit_id}"]["get"]
    assert "404" in kit_get["responses"]
    ref = json.dumps(kit_get["responses"]["404"])
    assert "ErrorEnvelope" in ref
    # The parser-stage 400 is discoverable too — a generated client must see
    # that an upload route can answer request.body_invalid (#169 round 2, P3).
    preview_post = schema["paths"]["/import/preview"]["post"]["responses"]
    assert "400" in preview_post
    assert "ErrorEnvelope" in json.dumps(preview_post["400"])


# --- parser-stage 400s (#169 review, P2) ----------------------------------------


async def test_multipart_with_no_boundary_gets_the_envelope(http_client):
    resp = await http_client.post(
        "/import/preview", content=b"broken", headers={"content-type": "multipart/form-data"}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == {"detail", "code", "params"}
    assert body["code"] == "request.body_invalid"
    assert body["params"] == {}
    # The wording belongs to the framework — assert its presence, not its bytes.
    assert isinstance(body["detail"], str) and body["detail"]


async def test_unreadable_multipart_body_gets_the_envelope(http_client):
    resp = await http_client.post(
        "/import/preview",
        content=b"broken",
        headers={"content-type": "multipart/form-data; boundary=foo"},
    )
    assert resp.status_code == 400
    body = resp.json()
    assert set(body) == {"detail", "code", "params"}
    assert body["code"] == "request.body_invalid"


async def test_unrouted_paths_keep_the_stock_body(http_client):
    """The delegation half of the 400 branch: Starlette's own 404/405 for paths
    that aren't the API stay deliberately outside the machine contract."""
    resp = await http_client.get("/no/such/route")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


# --- the raise-site audit (#169 review, P3) -------------------------------------

# Codes emitted by handlers in main.py rather than raised by a service.
_HANDLER_CODES = {"request.validation", "request.body_invalid"}

# The two bridge helpers whose `Diagnostic(code=exc.code, params={**...})` the
# AST cannot see through. Each borrows a `DomainError`'s own code and params, so
# the raise site it borrows from is already audited above — the allowlist is
# named, not inferred, and counted so a third bridge can't slip in unaudited.
_DIAGNOSTIC_BRIDGES = {"_borrowed_diagnostic", "_row_problem"}


def _extract_code_and_params(call) -> tuple[str | None, set[str] | None]:
    """The resolved `code=` and the keys of a literal `params=` dict (None when
    params isn't a literal dict) from one Call node."""
    import ast

    code: str | None = None
    params_keys: set[str] | None = set()
    for keyword in call.keywords:
        if keyword.arg == "code":
            value = keyword.value
            if isinstance(value, ast.Attribute):
                code = getattr(error_codes, value.attr, None)
            elif isinstance(value, ast.Constant):
                code = value.value
        elif keyword.arg == "params":
            if isinstance(keyword.value, ast.Dict) and all(
                isinstance(key, ast.Constant) for key in keyword.value.keys
            ):
                params_keys = {key.value for key in keyword.value.keys}
            else:
                params_keys = None
    return code, params_keys


def _walk_app():
    import ast

    app_dir = Path(__file__).resolve().parents[1] / "app"
    for path in sorted(app_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Which bridge helper encloses each line, so a bridge's own internal
        # Diagnostic() construction is recognised as the one sanctioned
        # non-literal site rather than a violation.
        bridge_spans = [
            (node.lineno, max(child.lineno for child in ast.walk(node) if hasattr(child, "lineno")))
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name in _DIAGNOSTIC_BRIDGES
        ]
        yield path, app_dir, tree, bridge_spans


def _raise_sites() -> list[tuple[str, str | None, set[str] | None]]:
    """Every domain-error raise in app/, with its resolved code and the keys of
    its literal params dict (None when params isn't a literal dict)."""
    import ast

    sites: list[tuple[str, str | None, set[str] | None]] = []
    for path, app_dir, tree, _ in _walk_app():
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            func = node.exc.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name not in ("NotFoundError", "ConflictError", "InvalidInputError", "DomainError"):
                continue
            code, params_keys = _extract_code_and_params(node.exc)
            sites.append((f"{path.relative_to(app_dir)}:{node.lineno}", code, params_keys))
    return sites


def _diagnostic_sites() -> list[tuple[str, str | None, set[str] | None, bool]]:
    """Every `Diagnostic(...)` construction in app/ (#26): location, resolved
    code, literal params keys, and whether the site sits inside a named bridge
    helper (where code and params are the borrowed exception's own)."""
    import ast

    sites: list[tuple[str, str | None, set[str] | None, bool]] = []
    for path, app_dir, tree, bridge_spans in _walk_app():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "Diagnostic":
                continue
            code, params_keys = _extract_code_and_params(node)
            in_bridge = any(start <= node.lineno <= end for start, end in bridge_spans)
            sites.append(
                (f"{path.relative_to(app_dir)}:{node.lineno}", code, params_keys, in_bridge)
            )
    return sites


def test_every_raise_site_supplies_its_codes_declared_params():
    """The runtime matrix above exercises a handful of codes; this audits all of
    them: each site's literal params dict must carry at least the fixture's
    guaranteed keys, so no writer of a shared code can quietly stop sending
    what a translation is allowed to interpolate (#169 review, P3 — the order
    writer's stock.insufficient raise could drop its params undetected)."""
    sites = _raise_sites()
    # Vacuity guard: an audit that finds nothing must fail, not pass (rule 8).
    assert len(sites) >= 81, f"only {len(sites)} raise sites found — the walker broke"
    for where, code, params_keys in sites:
        assert code in _FIXTURE, f"{where}: code {code!r} is not in api-error-codes.json"
        assert params_keys is not None, (
            f"{where}: params must be a literal dict with constant keys — "
            "the audit cannot see through anything else"
        )
        declared = set(_FIXTURE[code]["params"])
        assert declared <= params_keys, (
            f"{where}: {code} guarantees {sorted(declared)} but sends {sorted(params_keys)}"
        )


def _diagnostic_param_violations(
    sites: list[tuple[str, str | None, set[str] | None, bool]],
    declared_by_code: dict[str, list[str]],
) -> list[tuple[str, str]]:
    """Exact-set comparison of Diagnostic sites against the registry — pure, so
    the checks themselves have negative controls on synthetic sites below.

    Exactness, not the raise-site audit's superset: an import diagnostic's
    params are what the catalogue is allowed to interpolate, so a param emitted
    beyond the declaration is a message the browser silently drops — that is
    how `matched_by` rode `import.match_ambiguous` undeclared and the order
    matcher's disambiguation hint never rendered (#178). It also makes one code
    shared by emitters with incompatible param sets impossible: at most one of
    them can equal the declaration.

    A bridge site is exempt (its params are dynamic); each bridge's output is
    pinned by a runtime matrix in `test_import_diagnostics.py` instead.
    """
    violations: list[tuple[str, str]] = []
    for where, code, params_keys, in_bridge in sites:
        if in_bridge:
            continue
        if code not in declared_by_code:
            violations.append((where, f"code {code!r} is not in api-error-codes.json"))
            continue
        if params_keys is None:
            violations.append((where, "params is not a literal dict with constant keys"))
            continue
        declared = set(declared_by_code[code])
        missing = declared - params_keys
        extra = params_keys - declared
        if missing:
            violations.append((where, f"{code} omits declared params {sorted(missing)}"))
        if extra:
            violations.append((where, f"{code} emits undeclared params {sorted(extra)}"))
    return violations


def test_import_diagnostic_sites_send_exactly_their_declared_params():
    """The #26 mirror of the raise-site audit, tightened to exact equality by
    #178: every `Diagnostic(...)` built in app/ names a fixture code and sends
    exactly its declared params. The two bridge helpers are the sanctioned
    exception — they forward an audited raise's own code and params, and are
    counted, so a new unauditable construction can't hide among them.

    The walker matches the bare name, so the assumed discipline is: construct
    diagnostics only as `Diagnostic(...)` with a literal params dict — an
    aliased import or `model_construct`/`model_validate` would be invisible
    here (#171 review, P3-2). Nothing in app/ does either today.
    """
    sites = _diagnostic_sites()
    # Vacuity guards: an audit that inspected nothing must fail, not pass
    # (rule 8) — and it has to have seen a meaningful spread of codes, not one.
    assert len(sites) >= 50, f"only {len(sites)} Diagnostic sites found — the walker broke"
    distinct = {code for _, code, _, in_bridge in sites if not in_bridge}
    assert len(distinct) >= 30, f"only {len(distinct)} distinct codes audited — the walker broke"
    bridged = [site for site in sites if site[3]]
    assert len(bridged) == len(_DIAGNOSTIC_BRIDGES), (
        f"expected exactly one construction per bridge helper, found {bridged}"
    )
    declared_by_code = {code: entry["params"] for code, entry in _FIXTURE.items()}
    assert _diagnostic_param_violations(sites, declared_by_code) == []


def test_the_diagnostic_audit_detects_each_violation_class():
    """The audit's own negative controls, on synthetic sites — every expected
    set here is a literal, never derived from the walker or the fixture (rule
    8). Each violation class #178 names must be caught, and the exact-match
    site must not be."""
    declared = {"import.probe": ["count", "table"]}

    exact = [("a.py:1", "import.probe", {"count", "table"}, False)]
    assert _diagnostic_param_violations(exact, declared) == []

    bridge = [("a.py:2", None, None, True)]
    assert _diagnostic_param_violations(bridge, declared) == []

    undeclared = [("a.py:3", "import.probe", {"count", "table", "matched_by"}, False)]
    assert _diagnostic_param_violations(undeclared, declared) == [
        ("a.py:3", "import.probe emits undeclared params ['matched_by']"),
    ]

    omitted = [("a.py:4", "import.probe", {"count"}, False)]
    assert _diagnostic_param_violations(omitted, declared) == [
        ("a.py:4", "import.probe omits declared params ['table']"),
    ]

    unknown = [("a.py:5", "import.mystery", {"count"}, False)]
    assert _diagnostic_param_violations(unknown, declared) == [
        ("a.py:5", "code 'import.mystery' is not in api-error-codes.json"),
    ]

    unauditable = [("a.py:6", "import.probe", None, False)]
    assert _diagnostic_param_violations(unauditable, declared) == [
        ("a.py:6", "params is not a literal dict with constant keys"),
    ]

    # One code, two emitters, incompatible param sets — the #178 shape. At
    # most one emitter can equal the declaration, so the drift is always named.
    reused = [
        ("a.py:7", "import.probe", {"count", "table"}, False),
        ("a.py:8", "import.probe", {"count", "table", "matched_by"}, False),
    ]
    assert _diagnostic_param_violations(reused, declared) == [
        ("a.py:8", "import.probe emits undeclared params ['matched_by']"),
    ]


def test_every_wire_code_is_raised_or_handler_emitted():
    """The other direction: a fixture code nothing emits is either dead or a
    handler's — and the handler set is named, not inferred. Since #26 a code
    reaches the wire two ways, so diagnostic constructions count alongside
    raises; the bridge helpers add nothing here because every code they borrow
    has the raise site it borrows from."""
    raised = {code for _, code, _ in _raise_sites()}
    emitted = {code for _, code, _, in_bridge in _diagnostic_sites() if not in_bridge}
    assert raised | emitted | _HANDLER_CODES == set(_FIXTURE)
    assert (raised | emitted) & _HANDLER_CODES == set()
