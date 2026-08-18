"""Every integer that can reach a column is bounded by what the column holds (#74).

Three routes in, and they need different kinds of test because they fail in
different places:

1. **Request schemas.** A field with `ge=0` and no ceiling accepts 2,147,483,648 and
   the refusal arrives from Postgres as an `IntegrityError` at flush — a 500 naming
   a constraint, raised after other rows in the same transaction have been written.
   Covered systematically by the contract test below, plus a live case per front
   door, because REST and MCP share the schemas but not the tests.
2. **MCP tool signatures.** An MCP tool is a function signature, not a request
   model, so a bare `int` parameter carries no bound however well the REST side is
   covered — `apply_upgrade` has a REST route whose schema its MCP twin simply
   doesn't go through, and `adjust_stock` had no REST route at all until #55. The
   bound has to be in the service both callers reach (rule 1), and is declared on
   the parameter as well so the tool schema tells an agent the same thing. A door
   added later inherits the service guard for free and still needs its own bound:
   that is why `StockAdjustmentRequest` carries `Int4` rather than leaning on the
   service, and why both doors are driven below.
3. **Derived values.** Two legal numbers whose sum is not. No schema can see this
   one, and testing input alone will never reach it — it needs a stored row near the
   ceiling and an operation that crosses it.

This is the residual of #73, which fixed the same class on the CSV import path
only; that path stays out of scope and keeps its own guard test.
"""

import importlib
import inspect
import pkgutil
import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import BaseModel

import app.schemas
from app.db import session_scope
from app.exceptions import ConflictError, InvalidInputError
from app.mcp import mcp
from app.services import catalog as catalog_service
from app.services import upgrades as upgrades_service
from app.services.numeric import INT4_MAX

#: Schemas that describe a request body. `*Read` models serialize rows that are
#: already in the database and cannot carry an out-of-range value out of it.
_WRITE_SUFFIXES = ("Create", "Update", "Upsert", "Request")


def _write_schemas() -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    for module in pkgutil.iter_modules(app.schemas.__path__):
        imported = importlib.import_module(f"app.schemas.{module.name}")
        for _, obj in inspect.getmembers(imported, inspect.isclass):
            if (
                issubclass(obj, BaseModel)
                and obj.__module__ == imported.__name__
                and obj.__name__.endswith(_WRITE_SUFFIXES)
            ):
                found.append(obj)
    return sorted(set(found), key=lambda c: (c.__module__, c.__name__))


def _integer_nodes(schema: dict) -> list[dict]:
    """Every integer-typed leaf of one property's JSON schema, `anyOf` included —
    an optional field spells itself `{"anyOf": [{"type": "integer"}, ...]}`."""
    if schema.get("type") == "integer":
        return [schema]
    return [node for branch in schema.get("anyOf", []) for node in _integer_nodes(branch)]


def test_every_integer_a_request_can_set_declares_its_ceiling():
    """The systematic half, and the one that catches the *next* unbounded field.

    Asked of the generated JSON schema rather than the annotations, because that is
    what the field promises to a client: the same object OpenAPI publishes and
    Pydantic validates against. How the bound was spelled is this module's business;
    that there is one is the contract.
    """
    schemas = _write_schemas()
    assert schemas, "found no request schemas at all — this test is not looking anywhere"

    unbounded = []
    for model in schemas:
        for name, prop in model.model_json_schema().get("properties", {}).items():
            for node in _integer_nodes(prop):
                if "maximum" not in node and "exclusiveMaximum" not in node:
                    unbounded.append(f"{model.__module__.split('.')[-1]}.{model.__name__}.{name}")

    assert not unbounded, (
        "integer fields with no upper bound — a value past int4 reaches the database "
        f"and fails at flush as a 500 rather than a 422 naming the field: {unbounded}"
    )


async def test_every_integer_an_mcp_tool_takes_declares_its_ceiling():
    """The same contract, asked of the other front door.

    The Pydantic sweep above cannot see this one: an MCP tool is a function
    signature, not a request model, so `adjust_stock(delta: int)` is invisible to
    any test that walks `app.schemas`. That blind spot is not hypothetical — it is
    how `apply_upgrade(quantity: int)` survived the first cut of this branch, with
    REST answering 422 and MCP answering "insufficient stock … 2147483648
    requested" as a 409 for the same value.

    The service-level guard is what actually enforces the bound (rule 1 — both
    callers meet there). Declaring it on the parameter as well is what makes it
    visible to the agent reading the tool schema, and it is the only form the
    contract can be *tested* in, which is the point of asserting it here.
    """
    async with Client(mcp) as mcp_client:
        tools = await mcp_client.list_tools()
    assert tools, "no MCP tools listed — this test is not looking anywhere"

    unbounded = []
    for tool in tools:
        for name, prop in (tool.inputSchema or {}).get("properties", {}).items():
            for node in _integer_nodes(prop):
                if "maximum" not in node and "exclusiveMaximum" not in node:
                    unbounded.append(f"{tool.name}.{name}")

    assert not unbounded, (
        "MCP tool parameters with no upper bound — an agent is the caller most "
        f"likely to compute a number rather than type one: {unbounded}"
    )


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        pytest.param(
            "/tools",
            {"name": "Nippers", "category": "cutting"},
            "quantity_on_hand",
            id="tools.quantity_on_hand",
        ),
        pytest.param(
            "/consumables",
            {"name": "Panel liner", "category": "paint"},
            "low_stock_threshold",
            id="consumables.low_stock_threshold",
        ),
        pytest.param(
            "/upgrades",
            {"name": "Metal thrusters", "manufacturer": "Metal Build"},
            "quantity_on_hand",
            id="upgrades.quantity_on_hand",
        ),
    ],
)
async def test_rest_refuses_an_integer_the_column_cannot_hold(http_client, path, payload, field):
    """Just inside and just outside, one apart. The pair matters: a bound written
    with the wrong comparison passes every test that only drives a number far away
    from it."""
    inside = await http_client.post(path, json={**payload, field: INT4_MAX})
    assert inside.status_code == 201, inside.text
    assert inside.json()[field] == INT4_MAX

    outside = await http_client.post(path, json={**payload, field: INT4_MAX + 1})
    assert outside.status_code == 422, f"{outside.status_code}: {outside.text[:200]}"
    assert field in outside.text


async def test_rest_refuses_an_out_of_range_order_line(http_client):
    """The nested case: the bound has to survive being reached through a list of
    sub-models, which is how every price and quantity in the app arrives."""
    retailer = (await http_client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = {
        "retailer_id": retailer["id"],
        "order_date": "2026-08-16",
        "currency_code": "JPY",
        "items": [
            {
                "item_type": "kit",
                "quantity": 1,
                "unit_price_minor": INT4_MAX + 1,
                "currency_code": "JPY",
                "kit": {"name": "HG Zaku II", "grade": "HG"},
            }
        ],
    }
    resp = await http_client.post("/orders", json=order)
    assert resp.status_code == 422, f"{resp.status_code}: {resp.text[:200]}"
    assert "unit_price_minor" in resp.text
    assert (await http_client.get("/orders")).json() == []


async def test_mcp_refuses_an_out_of_range_order_line(client):
    """The second front door. MCP builds the same `OrderCreate`, so this is one
    defect with two entrances rather than two defects (rule 1) — but the schemas are
    shared and the tests are not, and an agent is the caller most likely to compute
    a number rather than type one."""
    await client.post("/retailers", json={"name": "Hobby Link Japan"})
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as raised:
            await mcp_client.call_tool(
                "create_order",
                {
                    "retailer": "Hobby Link Japan",
                    "order_date": "2026-08-16",
                    "items": [
                        {
                            "item_type": "consumable",
                            "quantity": 1,
                            "unit_price_minor": INT4_MAX + 1,
                            "currency_code": "JPY",
                            "new_item": {"name": "Mr Surfacer", "category": "paint"},
                        }
                    ],
                },
            )
    # Both halves are load-bearing, and the first alone is not enough: without the
    # bound this call *also* raises ToolError, because the value reaches Postgres and
    # the flush fails. That error stringifies with the whole INSERT statement in it,
    # column names included — so "unit_price_minor is in the message" passes against
    # the unfixed code. Measured, not guessed. What separates the two is which layer
    # spoke: Pydantic's phrasing, and no database error underneath it.
    message = str(raised.value)
    assert "less than or equal to" in message, message
    assert "sqlalchemy" not in message.lower(), (
        "the line reached the database — this is the flush failing at 500, not the "
        f"schema refusing it: {message[:200]}"
    )
    assert (await client.get("/orders")).json() == []


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        pytest.param(
            "/tools",
            {"name": "Nippers", "category": "cutting"},
            "quantity_on_hand",
            id="tools.quantity_on_hand",
        ),
        pytest.param(
            "/consumables",
            {"name": "Panel liner", "category": "paint"},
            "low_stock_threshold",
            id="consumables.low_stock_threshold",
        ),
    ],
)
@pytest.mark.parametrize("sent", [True, False], ids=["true", "false"])
async def test_a_boolean_is_not_a_number(http_client, path, payload, field, sent):
    """`bool` subclasses `int`, so lax Pydantic reads JSON `true` as 1 and `false`
    as 0 — on every integer field at once, which is why the refusal lives on the
    `Annotated` aliases rather than on the field that happened to surface it.

    Both values, because they fail differently: `true` is a plausible 1 that a
    caller might never notice, while `false` is a 0 that reads as "no change" and
    passes a `ge=0` bound cleanly. Found by the Cursor Grok 4.6 review of #100 on
    the new adjust route; the route was not the bug, the alias was.
    """
    refused = await http_client.post(path, json={**payload, field: sent})
    assert refused.status_code == 422, f"{refused.status_code}: {refused.text[:200]}"
    assert field in refused.text


async def test_a_boolean_quantity_cannot_conjure_a_purchase(http_client, retailer):
    """The case that makes the above more than tidiness. A line quantity of `true`
    is a quantity of 1, and a kit line at quantity 1 spawns a kit — so a JSON
    boolean writes a purchase record and a collection row that nobody entered.
    """
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-18",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "kit",
                    "quantity": True,
                    "unit_price_minor": 4500,
                    "currency_code": "AUD",
                    "kit": {"name": "HG Barbatos", "grade": "HG"},
                }
            ],
        },
    )
    assert resp.status_code == 422, f"{resp.status_code}: {resp.text[:200]}"
    assert (await http_client.get("/orders")).json() == []
    assert (await http_client.get("/kits")).json() == []


async def test_mcp_refuses_a_boolean_delta(client):
    """The other door. `adjust_stock` takes `Int4` on the tool signature, so the
    same alias carries the refusal to agents — the surface most likely to compute
    a value rather than type one."""
    tool = (await client.post("/tools", json={"name": "Nippers", "category": "cutting"})).json()
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError):
            await mcp_client.call_tool("adjust_stock", {"catalog_id": tool["id"], "delta": True})
    assert (await client.get("/tools")).json()[0]["quantity_on_hand"] == 0


async def test_an_out_of_range_delta_is_the_callers_mistake_not_a_conflict(client, http_client):
    """Route 2, now through both doors: `adjust_stock` gained a REST route in #55,
    so the bound is carried by `StockAdjustmentRequest` as well as by the service
    where both callers meet (rule 1).

    Asserted on the **error class**, at the service, because that is the only thing
    that distinguishes this route from the derived-sum guard below. Any delta past
    int4 also makes the *sum* past int4, so the sum check refuses it either way and
    every front-door test of this passes with the delta bound deleted — measured.
    What the bound actually buys is the honest answer: a three-billion delta is the
    caller mistyping (422), not the stored state refusing an otherwise reasonable
    request (409), and the two say very different things to whoever sent it.
    """
    tool = (await client.post("/tools", json={"name": "Nippers", "category": "cutting"})).json()
    tool_id = uuid.UUID(tool["id"])

    async with session_scope() as session:
        with pytest.raises(InvalidInputError):
            await catalog_service.adjust_stock(session, tool_id, INT4_MAX + 1)

    # And it is refused at both front doors: a ToolError on one, a 422 on the other
    # — the same judgement wearing each surface's clothes.
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError):
            await mcp_client.call_tool(
                "adjust_stock", {"catalog_id": tool["id"], "delta": INT4_MAX + 1}
            )

    refused = await http_client.post(f"/catalog/{tool['id']}/adjust", json={"delta": INT4_MAX + 1})
    assert refused.status_code == 422, f"{refused.status_code}: {refused.text[:200]}"
    assert "delta" in refused.text

    assert (await client.get("/tools")).json()[0]["quantity_on_hand"] == 0


async def test_stock_cannot_be_derived_past_the_ceiling(client, http_client):
    """Route 3, and the shape no schema can reach: both numbers are legal, their sum
    is not. A conflict, the same class of error as its opposite — "you cannot take 5
    from 3 on hand" and "you cannot add 1 to a number at the ceiling" are both the
    stored state refusing, not the caller mistyping. Pinned as `ConflictError`
    against the previous test's `InvalidInputError`, which is what keeps the two
    routes distinguishable at all.
    """
    tool = (
        await client.post(
            "/tools",
            json={"name": "Nippers", "category": "cutting", "quantity_on_hand": INT4_MAX},
        )
    ).json()
    tool_id = uuid.UUID(tool["id"])

    async with session_scope() as session:
        with pytest.raises(ConflictError):
            await catalog_service.adjust_stock(session, tool_id, 1)

    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as raised:
            await mcp_client.call_tool("adjust_stock", {"catalog_id": tool["id"], "delta": 1})
    assert "out of range" in str(raised.value)

    # The REST door reaches the same derived sum, and no schema can bound it there
    # either — a legal delta onto a legal quantity. It has to arrive as a conflict.
    overflowed = await http_client.post(f"/catalog/{tool['id']}/adjust", json={"delta": 1})
    assert overflowed.status_code == 409, f"{overflowed.status_code}: {overflowed.text[:200]}"

    assert (await client.get("/tools")).json()[0]["quantity_on_hand"] == INT4_MAX

    # ... and the same stock still adjusts normally in the other direction.
    async with Client(mcp) as mcp_client:
        await mcp_client.call_tool("adjust_stock", {"catalog_id": tool["id"], "delta": -1})
    assert (await client.get("/tools")).json()[0]["quantity_on_hand"] == INT4_MAX - 1


async def _received_order_for(http_client, consumable_id: str, quantity: int):
    retailer = (await http_client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    return await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-16",
            "currency_code": "AUD",
            "received": True,
            "items": [
                {
                    "item_type": "consumable",
                    "quantity": quantity,
                    "unit_price_minor": 500,
                    "currency_code": "AUD",
                    "catalog_ref_id": consumable_id,
                }
            ],
        },
    )


async def test_receiving_an_order_cannot_derive_stock_past_the_ceiling(http_client):
    """The same derivation, reached through the order dispatch instead — a different
    call site with its own arithmetic (`quantity_on_hand += line.quantity`), which
    the `adjust_stock` test above cannot speak for."""
    consumable = (
        await http_client.post(
            "/consumables",
            json={"name": "Panel liner", "category": "paint", "quantity_on_hand": INT4_MAX},
        )
    ).json()

    resp = await _received_order_for(http_client, consumable["id"], 1)
    assert resp.status_code == 409, f"{resp.status_code}: {resp.text[:200]}"
    assert (await http_client.get("/consumables")).json()[0]["quantity_on_hand"] == INT4_MAX
    assert (await http_client.get("/orders")).json() == [], "the order survived a failed dispatch"


async def test_editing_an_order_cannot_derive_stock_past_the_ceiling(http_client):
    """And the third site: the edit diff's `_adjust_ref`, which applies the delta
    between the stored line and the new one."""
    consumable = (
        await http_client.post(
            "/consumables",
            json={"name": "Panel liner", "category": "paint", "quantity_on_hand": INT4_MAX - 1},
        )
    ).json()
    order = (await _received_order_for(http_client, consumable["id"], 1)).json()
    assert (await http_client.get("/consumables")).json()[0]["quantity_on_hand"] == INT4_MAX

    resp = await http_client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": order["items"][0]["id"],
                    "item_type": "consumable",
                    "quantity": 3,  # +2 on a row already at the ceiling
                    "unit_price_minor": 500,
                    "currency_code": "AUD",
                    "catalog_ref_id": consumable["id"],
                }
            ]
        },
    )
    assert resp.status_code == 409, f"{resp.status_code}: {resp.text[:200]}"
    assert (await http_client.get("/consumables")).json()[0]["quantity_on_hand"] == INT4_MAX
    assert (await http_client.get("/orders")).json()[0]["items"][0]["quantity"] == 1


def test_the_bound_is_read_from_one_place():
    """`app/schemas/numeric.py` and the CSV importer's `require_int4` must agree, and
    the way that goes wrong is not one side forgetting to check — it is two sides
    checking against numbers that drifted apart (#73 → #74 is that story once
    already). Neither file writes the literal; both import it."""
    import app.schemas.numeric as schema_numeric

    assert schema_numeric.INT4_MAX == INT4_MAX == 2_147_483_647
    assert "2147483647" not in inspect.getsource(schema_numeric)


async def test_an_unstorable_upgrade_quantity_is_invalid_input_at_both_doors(client):
    """The gap external review found in this branch's first cut, and the reason the
    MCP contract test above exists.

    `UpgradeApplyRequest.quantity` bound the REST caller; the MCP tool passed a bare
    int straight to the service, which checked only the floor and stock. So the two
    front doors answered the *same value* differently — REST 422, MCP a 409 reading
    "insufficient stock … 2147483648 requested". Both refuse, which is why nothing
    caught it, but only one of them is right: an unstorable quantity is the caller's
    mistake at any stock level, not the stored state's.

    Driven at ordinary stock as well as at the ceiling, because the divergence was
    never about how much was on hand — the original repro used INT4_MAX and that
    detail is incidental.
    """
    kit = (await client.post("/kits", json={"name": "Zaku II", "grade": "HG"})).json()
    upgrade = (
        await client.post(
            "/upgrades",
            json={"name": "Metal thrusters", "manufacturer": "Metal Build", "quantity_on_hand": 5},
        )
    ).json()

    rest = await client.post(
        f"/upgrades/{upgrade['id']}/apply",
        json={"kit_id": kit["id"], "quantity": INT4_MAX + 1},
    )
    assert rest.status_code == 422, f"{rest.status_code}: {rest.text[:200]}"

    async with session_scope() as session:
        with pytest.raises(InvalidInputError):
            await upgrades_service.apply_upgrade(
                session, uuid.UUID(upgrade["id"]), uuid.UUID(kit["id"]), INT4_MAX + 1
            )
        # ... and the stock check still answers for what it is actually for.
        with pytest.raises(ConflictError):
            await upgrades_service.apply_upgrade(
                session, uuid.UUID(upgrade["id"]), uuid.UUID(kit["id"]), 6
            )

    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as raised:
            await mcp_client.call_tool(
                "apply_upgrade",
                {"upgrade_id": upgrade["id"], "kit_id": kit["id"], "quantity": INT4_MAX + 1},
            )
    assert "insufficient stock" not in str(raised.value), (
        "MCP still reports an unstorable quantity as a stock conflict: " + str(raised.value)[:200]
    )
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 5
