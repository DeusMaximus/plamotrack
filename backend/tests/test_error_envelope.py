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
    assert "ErrorEnvelope" in components
    assert "ValidationErrorEnvelope" in components
    envelope = components["ErrorEnvelope"]
    assert set(envelope["required"]) >= {"detail", "code"}
    # Sampled route: the shared responses actually landed on the routers.
    kit_get = schema["paths"]["/kits/{kit_id}"]["get"]
    assert "404" in kit_get["responses"]
    ref = json.dumps(kit_get["responses"]["404"])
    assert "ErrorEnvelope" in ref
