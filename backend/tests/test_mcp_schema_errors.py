"""A value that fails a request schema built inside an MCP tool's body is refused
with a `ToolError` naming the argument (#354; rule 1).

FastMCP validates a tool's arguments before the body runs and names the field when
one fails. A `ValidationError` the *body* raises it treats as the server's fault, and
the SDK answered it as "Invalid request parameters", naming nothing. `create_order`
builds `OrderCreate` from its flat arguments in its body, so a bad `currency_code`,
an empty `items` or a NUL in `order_number` got that answer, where REST's 422 names
the field. `app.mcp._build` is the one way a tool body builds a request schema; the
scan at the end of this file fails on a construction that skips it.

The kit tools build `KitCreate` / `KitUpdate` in their bodies too, from values their
own argument model has already accepted, so no value reaches those schemas failing:
their cases here pass on the base and are the evidence that the arguments are named
there already, at argument validation.
"""

from __future__ import annotations

import ast
import inspect
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app import mcp as mcp_module
from app.auth.principal import Scope
from app.main import app
from app.mcp import mcp
from app.schemas.base import RequestModel
from app.schemas.kits import KitCreate, KitUpdate
from app.schemas.orders import OrderCreate
from tests.test_auth_tokens import _mcp_call_tool, _mint_direct
from tests.test_mcp_eras import modern_headers, modern_request, rpc

ZERO_ID = "00000000-0000-0000-0000-000000000000"
LINE = {
    "item_type": "kit",
    "quantity": 1,
    "unit_price_minor": 100,
    "currency_code": "AUD",
    "kit": {"name": "Zaku", "grade": "HG"},
}
ORDER = {"order_date": "2026-01-01", "retailer": "Shop", "currency_code": "AUD", "items": [LINE]}

#: (argument, value): every flat argument of `create_order` that reaches
#: `OrderCreate` unchecked by the tool and can fail there. The SDK's own argument
#: validation already names `shipping_cost_minor`, `received_at` and the rest.
BAD_FLAT_ARGUMENTS = [
    pytest.param("currency_code", "nope", id="currency_code: not a code"),
    pytest.param("currency_code", "aud", id="currency_code: lower case"),
    pytest.param("currency_code", "A\x00D", id="currency_code: NUL"),
    pytest.param("items", [], id="items: empty"),
    pytest.param("order_number", "a\x00b", id="order_number: NUL"),
    pytest.param("delivery_service", "a\x00b", id="delivery_service: NUL"),
    pytest.param("tracking_number", "\x00", id="tracking_number: NUL alone"),
    pytest.param("tracking_url", "a\x00b", id="tracking_url: NUL"),
    pytest.param("notes", " \x00 ", id="notes: NUL inside whitespace"),
]


async def _nothing_stored(http_client) -> None:
    assert (await http_client.get("/orders")).json() == []
    assert (await http_client.get("/kits")).json() == []
    # The shop named in the same call was created in the same transaction.
    assert (await http_client.get("/retailers")).json() == []


def _names(message: str, argument: str) -> None:
    """The refusal is the helper's, naming this argument and no other field."""
    assert message.startswith(f"invalid {argument}: "), message
    named = {part.split(":", 1)[0].removeprefix("invalid ") for part in message.split("; ")}
    assert named == {argument}, message
    assert "Invalid request parameters" not in message


# --- create_order: in memory, over HTTP, and against REST ------------------------------


@pytest.mark.parametrize(("argument", "value"), BAD_FLAT_ARGUMENTS)
async def test_create_order_names_the_argument(http_client, argument, value):
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as refused:
            await client.call_tool("create_order", {**ORDER, argument: value})
    _names(str(refused.value), argument)
    await _nothing_stored(http_client)


async def test_create_order_names_the_argument_by_retailer_id_too(http_client):
    """The other way to name a shop: the stored one survives, and nothing is added."""
    shop = (await http_client.post("/retailers", json={"name": "Shop"})).json()
    arguments = {**ORDER, "retailer_id": shop["id"], "currency_code": "nope"}
    del arguments["retailer"]
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as refused:
            await client.call_tool("create_order", arguments)
    _names(str(refused.value), "currency_code")
    assert (await http_client.get("/orders")).json() == []
    assert [r["id"] for r in (await http_client.get("/retailers")).json()] == [shop["id"]]


@pytest.mark.parametrize("era", ["modern", "legacy"])
async def test_create_order_names_the_argument_over_http(http_client, era):
    """The Streamable HTTP transport, through the real bearer and scope check: the
    refusal is a tool result marked as an error, not the JSON-RPC invalid-params
    error the body's `ValidationError` used to become."""
    arguments = {**ORDER, "currency_code": "nope"}
    async with app.router.lifespan_context(app):
        token, _ = await _mint_direct(scopes=(Scope.WRITE,))
        if era == "modern":
            response = await http_client.post(
                "/mcp/",
                json=modern_request("tools/call", {"name": "create_order", "arguments": arguments}),
                headers=modern_headers("tools/call", token=token, name="create_order"),
            )
            assert response.status_code == 200, response.text
            body = rpc(response)
            assert "error" not in body, body
            result = body["result"]
        else:
            result = await _mcp_call_tool(
                http_client,
                {"Host": "localhost", "Authorization": f"Bearer {token}"},
                "create_order",
                arguments,
            )
    assert result["isError"] is True, result
    [content] = result["content"]
    _names(content["text"], "currency_code")
    await _nothing_stored(http_client)


@pytest.mark.parametrize(("argument", "value"), BAD_FLAT_ARGUMENTS)
async def test_rest_names_the_same_field(http_client, argument, value):
    """Rule 1's other half: the field MCP names is the field REST's 422 names."""
    shop = (await http_client.post("/retailers", json={"name": "Shop"})).json()
    body = {**ORDER, "retailer_id": shop["id"], argument: value}
    del body["retailer"]
    resp = await http_client.post("/orders", json=body)
    assert resp.status_code == 422, resp.text
    assert {e["field"] for e in resp.json()["params"]["errors"]} == {argument}, resp.text


# --- the kit tools: swept, named already at argument validation ------------------------


@pytest.mark.parametrize(
    ("tool", "arguments", "named"),
    [
        ("create_kit", {"kit": {"name": "", "grade": "HG"}}, "kit.name"),
        ("create_kit", {"kit": {"name": "Zaku", "grade": ""}}, "kit.grade"),
        ("create_kit", {"kit": {"name": "Zaku", "grade": "HG", "status": "nope"}}, "status"),
        ("update_kit", {"kit_id": ZERO_ID, "changes": {"rating": 9}}, "changes.rating"),
        ("update_kit", {"kit_id": ZERO_ID, "changes": {"name": ""}}, "changes.name"),
        ("update_kit", {"kit_id": "nope", "changes": {}}, "kit_id"),
        ("update_kit_status", {"kit_id": ZERO_ID, "status": "nope"}, "status"),
        ("update_kit_status", {"kit_id": "nope", "status": "backlog"}, "kit_id"),
    ],
)
async def test_the_kit_tools_name_the_argument(http_client, tool, arguments, named):
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as refused:
            await client.call_tool(tool, arguments)
    assert named in str(refused.value), str(refused.value)
    assert (await http_client.get("/kits")).json() == []


@pytest.mark.parametrize(
    ("schema", "argument", "fields", "named"),
    [
        (KitCreate, "kit", {"name": "", "grade": "HG"}, {"kit.name"}),
        (KitUpdate, "changes", {"rating": 9, "grade": ""}, {"changes.rating", "changes.grade"}),
        (KitUpdate, None, {"status": "nope"}, {"status"}),
    ],
)
def test_the_helper_names_the_argument_a_field_came_from(schema, argument, fields, named):
    """What no kit tool can reach today, since its argument model refuses first: a
    field the tool unpacked from one argument is named under that argument."""
    with pytest.raises(ToolError) as refused:
        mcp_module._build(schema, argument, **fields)
    message = str(refused.value)
    found = {part.split(":", 1)[0].removeprefix("invalid ") for part in message.split("; ")}
    assert found == named, message


def test_a_model_level_finding_is_its_message_alone():
    with pytest.raises(ToolError) as refused:
        mcp_module._build(
            OrderCreate,
            None,
            retailer_id=ZERO_ID,
            order_date="2026-01-01",
            currency_code="AUD",
            items=[LINE],
            received_at="2026-01-01T00:00:00+00:00",
        )
    assert str(refused.value).startswith("received_at asserts the order arrived"), str(
        refused.value
    )


# --- the class: no request schema built in a tool body but through `_build` ------------


def _request_schemas_called() -> tuple[list[str], set[type]]:
    """Every call in `app/mcp.py` of a name bound there to a `RequestModel`
    subclass, directly or by `.model_validate` / `.model_construct`; and the
    schemas handed to `_build` as its first argument."""
    tree = ast.parse(inspect.getsource(mcp_module))
    direct, through_build = [], set()

    def request_schema(node: ast.expr) -> type | None:
        if isinstance(node, ast.Name):
            bound = getattr(mcp_module, node.id, None)
            if isinstance(bound, type) and issubclass(bound, RequestModel):
                return bound
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "_build":
            schema = request_schema(node.args[0])
            assert schema is not None, ast.unparse(node)
            through_build.add(schema)
        elif request_schema(func) is not None or (
            isinstance(func, ast.Attribute)
            and func.attr in {"model_validate", "model_validate_json", "model_construct"}
            and request_schema(func.value) is not None
        ):
            direct.append(f"line {node.lineno}: {ast.unparse(node)[:80]}")
    return direct, through_build


def test_every_request_schema_a_tool_builds_goes_through_build():
    direct, through_build = _request_schemas_called()
    assert direct == [], "built outside _build:\n" + "\n".join(direct)
    # Not vacuous: the four sites the #354 sweep found are what the scan sees.
    assert through_build == {KitCreate, KitUpdate, OrderCreate}, through_build


def test_the_refusals_are_json_safe():
    """The message carries no input, so a surrogate in the value cannot reach it."""
    with pytest.raises(ToolError) as refused:
        mcp_module._build(KitCreate, "kit", name="a\ud800b", grade="HG")
    json.dumps(str(refused.value)).encode()
    str(refused.value).encode("utf-8")
