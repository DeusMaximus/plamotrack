"""MCP order reading and correction (#97) — the last gap in the rule-1 class
#92/#55 closed: an agent could record a purchase but never inspect or fix one.

The design decision under test: `update_order`'s items list keeps REST's
full-replacement semantics (one service, rule 1), but the MCP surface refuses an
items list that OMITS stored lines unless the agent passes
remove_missing_lines=true. The gate lives in the service, under the order's
FOR UPDATE lock — not in the wrapper, where a read-then-check would race a
concurrent line addition. The state axis is the §3.9 diff itself: a line added,
a line changed, a line removed are three different branches, and removal is the
one that destroys purchase records.
"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp
from tests.test_order_lifecycle import (
    consumable_line,
    kit_line,
    make_consumable,
    make_order,
)

BACKDATE = "2026-05-04T14:30:00+10:00"


def restated(item: dict, **overrides) -> dict:
    """A stored line echoed back the way an agent would after get_order: id,
    dispatch fields and kit details — without the converted snapshot, which an
    editor that never had the entry-time rate must not restate."""
    kit = item["kits"][0] if item["kits"] else None
    line = {
        "id": item["id"],
        "item_type": item["item_type"],
        "quantity": item["quantity"],
        "unit_price_minor": item["unit_price_minor"],
        "currency_code": item["currency_code"],
    }
    if kit is not None:
        line["kit"] = {"name": kit["name"], "grade": kit["grade"]}
    else:
        line["catalog_ref_id"] = item["catalog_ref_id"]
    line.update(overrides)
    return line


# --- get_order -------------------------------------------------------------------


async def test_get_order_returns_lines_with_ids_and_kits(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    async with Client(mcp) as mcp_client:
        fetched = (await mcp_client.call_tool("get_order", {"order_id": order["id"]})).data
    assert fetched["id"] == order["id"]
    (item,) = fetched["items"]
    assert item["id"] == order["items"][0]["id"]
    assert len(item["kits"]) == 2


async def test_get_order_unknown_id_and_bad_uuid_are_tool_errors():
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="not found"):
            await mcp_client.call_tool(
                "get_order", {"order_id": "00000000-0000-0000-0000-000000000000"}
            )
        with pytest.raises(ToolError, match="not a valid UUID"):
            await mcp_client.call_tool("get_order", {"order_id": "series"})


# --- header edits ----------------------------------------------------------------


async def test_header_edit_leaves_lines_and_kits_alone(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    kit_ids = set(order["items"][0]["spawned_kit_ids"])
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_order",
                {"order_id": order["id"], "changes": {"tracking_number": "TRACK-42"}},
            )
        ).data
    assert edited["tracking_number"] == "TRACK-42"
    assert set(edited["items"][0]["spawned_kit_ids"]) == kit_ids  # same kits, no respawn


# --- the three diff branches -----------------------------------------------------


async def test_quantity_increase_spawns_through_mcp(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {"items": [restated(order["items"][0], quantity=3)]},
                },
            )
        ).data
    assert len(edited["items"][0]["spawned_kit_ids"]) == 3


async def test_added_line_spawns_alongside_restated_one(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    new_line = kit_line(quantity=1, name="MG Zaku II 2.0")
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {"items": [restated(order["items"][0]), new_line]},
                },
            )
        ).data
    assert len(edited["items"]) == 2
    names = {kit["name"] for item in edited["items"] for kit in item["kits"]}
    assert "MG Zaku II 2.0" in names


async def test_omitting_a_stored_line_is_refused_by_default_and_nothing_is_deleted(
    client, retailer
):
    keep, drop = kit_line(quantity=1), kit_line(quantity=1, name="MG Zaku II 2.0")
    order = await make_order(client, retailer, [keep, drop])
    dropped_item = order["items"][1]
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match=str(dropped_item["id"])):
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {"items": [restated(order["items"][0])]},
                },
            )
        # The refusal names the flag an agent needs, and the transaction rolled back.
        with pytest.raises(ToolError, match="remove_missing_lines"):
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {"items": [restated(order["items"][0])]},
                },
            )
        fresh = (await mcp_client.call_tool("get_order", {"order_id": order["id"]})).data
    assert len(fresh["items"]) == 2
    assert len((await client.get("/kits")).json()) == 2


async def test_opting_in_removes_the_line_and_reverses_its_dispatch(client, retailer):
    marker = await make_consumable(client)
    order = await make_order(
        client,
        retailer,
        [kit_line(quantity=1), consumable_line(marker["id"], quantity=5)],
        received=True,
    )
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 5
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {"items": [restated(order["items"][0])]},
                    "remove_missing_lines": True,
                },
            )
        ).data
    assert len(edited["items"]) == 1
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 0


async def test_an_explicit_quantity_decrease_needs_no_flag(client, retailer):
    # The gate is about OMISSION — silent deletion. A stated smaller quantity is
    # the agent asserting a number, and stays as cheap as it is on REST.
    order = await make_order(client, retailer, [kit_line(quantity=3)])
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {"items": [restated(order["items"][0], quantity=1)]},
                },
            )
        ).data
    assert len(edited["items"][0]["spawned_kit_ids"]) == 1


# --- the §6 snapshot -------------------------------------------------------------


async def test_an_edit_that_omits_the_snapshot_preserves_it(client, retailer):
    line = kit_line(quantity=1)
    line["currency_code"] = "JPY"
    line["unit_price_minor"] = 4400
    line["converted_price_minor"] = 4999
    line["converted_currency_code"] = "AUD"
    order = await make_order(client, retailer, [line])
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {
                        "items": [
                            restated(
                                order["items"][0],
                                quantity=2,
                                currency_code="JPY",
                                unit_price_minor=4400,
                            )
                        ]
                    },
                },
            )
        ).data
    (item,) = edited["items"]
    assert item["converted_price_minor"] == 4999
    assert item["converted_currency_code"] == "AUD"


async def test_an_explicit_null_clears_the_snapshot(client, retailer):
    # The other half of the pair's contract (issue #3): omission preserves —
    # asserted above — and an explicit null is the one way to clear. Driven
    # through MCP because both rest on FastMCP rebuilding the nested line model
    # with the right fields_set; a wrapper that flattened it would break the
    # null half first.
    line = kit_line(quantity=1)
    line["converted_price_minor"] = 4999
    line["converted_currency_code"] = "AUD"
    order = await make_order(client, retailer, [line])
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {
                        "items": [
                            restated(
                                order["items"][0],
                                converted_price_minor=None,
                                converted_currency_code=None,
                            )
                        ]
                    },
                },
            )
        ).data
    (item,) = edited["items"]
    assert item["converted_price_minor"] is None
    assert item["converted_currency_code"] is None


# --- guards ----------------------------------------------------------------------


async def test_removal_blocked_by_a_progressed_kit_even_with_the_flag(client, retailer):
    keep, drop = kit_line(quantity=1), kit_line(quantity=1, name="MG Zaku II 2.0")
    order = await make_order(client, retailer, [keep, drop])
    progressed_kit = order["items"][1]["spawned_kit_ids"][0]
    assert (
        await client.patch(f"/kits/{progressed_kit}", json={"status": "building"})
    ).status_code == 200
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="building"):
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {"items": [restated(order["items"][0])]},
                    "remove_missing_lines": True,
                },
            )
        fresh = (await mcp_client.call_tool("get_order", {"order_id": order["id"]})).data
    assert len(fresh["items"]) == 2


async def test_removal_blocked_by_consumed_stock_even_with_the_flag(client, retailer):
    marker = await make_consumable(client)
    order = await make_order(
        client,
        retailer,
        [kit_line(quantity=1), consumable_line(marker["id"], quantity=5)],
        received=True,
    )
    async with Client(mcp) as mcp_client:
        await mcp_client.call_tool(
            "adjust_stock",
            {"catalog_id": marker["id"], "delta": -3, "reason": "used on a build"},
        )
        with pytest.raises(ToolError, match="on hand"):
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {"items": [restated(order["items"][0])]},
                    "remove_missing_lines": True,
                },
            )
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 2


# --- received_at parity (#111) ---------------------------------------------------


async def test_receipt_correction_flows_through_the_tool(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)], received=True)
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_order",
                {"order_id": order["id"], "changes": {"received_at": BACKDATE}},
            )
        ).data
        assert edited["received_at"].startswith("2026-05-04T04:30:00")
        (kit,) = edited["items"][0]["kits"]
        assert kit["status_updated_at"] == edited["received_at"]

        pending = await make_order(client, retailer, [kit_line(quantity=1)])
        with pytest.raises(ToolError, match="not received yet"):
            await mcp_client.call_tool(
                "update_order",
                {"order_id": pending["id"], "changes": {"received_at": BACKDATE}},
            )


async def test_update_order_kit_omitted_leaves_details_alone():
    """The #67 posture on this surface: an agent restating a line it is not
    changing kit details on omits `kit`, and what it does not state it cannot
    revert — one schema and one service under both surfaces (rule 1)."""
    async with Client(mcp) as mcp_client:
        order = (
            await mcp_client.call_tool(
                "create_order",
                {
                    "retailer": "Kit Omission Works",
                    "order_date": "2026-08-02",
                    "items": [
                        {
                            "item_type": "kit",
                            "quantity": 1,
                            "unit_price_minor": 4500,
                            "currency_code": "AUD",
                            "kit": {"name": "HG Barbatos", "grade": "HG"},
                        }
                    ],
                },
            )
        ).data
        kit_id = order["items"][0]["spawned_kit_ids"][0]
        # Out-of-band, as another writer: the kit gains a number.
        await mcp_client.call_tool(
            "update_kit", {"kit_id": kit_id, "changes": {"kit_number": "ASW-G-08"}}
        )
        updated = (
            await mcp_client.call_tool(
                "update_order",
                {
                    "order_id": order["id"],
                    "changes": {
                        "items": [
                            {
                                "id": order["items"][0]["id"],
                                "item_type": "kit",
                                "quantity": 1,
                                "unit_price_minor": 4999,
                                "currency_code": "AUD",
                            }
                        ]
                    },
                },
            )
        ).data
        assert updated["items"][0]["unit_price_minor"] == 4999  # the edit landed
        kit = (await mcp_client.call_tool("get_kit", {"kit_id": kit_id})).data
        assert kit["kit_number"] == "ASW-G-08"  # untouched by the silent line
