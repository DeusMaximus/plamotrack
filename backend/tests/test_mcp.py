import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp
from app.services import orders

EXPECTED_TOOLS = {
    "get_meta",
    "list_kits",
    "list_kit_series",
    "get_kit",
    "create_kit",
    "update_kit_status",
    "update_kit",
    "search_catalog",
    "list_catalog_items",
    "list_catalog_categories",
    "create_catalog_tool",
    "create_catalog_consumable",
    "create_catalog_upgrade",
    "create_catalog_display",
    "list_retailers",
    "create_retailer",
    "update_retailer",
    "create_order",
    "list_orders",
    "get_order",
    "update_order",
    "mark_order_received",
    "mark_order_shipped",
    "adjust_stock",
    "update_catalog_tool",
    "update_catalog_consumable",
    "update_catalog_upgrade",
    "update_catalog_display",
    "apply_upgrade",
    "withdraw_upgrade_application",
}


async def test_all_doc_section_7_tools_exposed():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == EXPECTED_TOOLS


async def test_get_meta_matches_rest(client):
    # One function serves both surfaces (#99) — the parity is an equality, and
    # the create_order docstring's pointer at get_meta points at something real.
    async with Client(mcp) as mcp_client:
        meta = (await mcp_client.call_tool("get_meta", {})).data
    assert meta == (await client.get("/meta")).json()
    assert set(meta) == {"version", "reference_currency"}


async def test_create_order_fans_out_like_rest():
    async with Client(mcp) as client:
        result = await client.call_tool(
            "create_order",
            {
                "retailer": "USA Gundam Store",
                "order_date": "2026-08-02",
                "currency_code": "USD",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 2,
                        "unit_price_minor": 2999,
                        "currency_code": "USD",
                        "kit": {"name": "RG Nu Gundam", "grade": "RG"},
                    }
                ],
            },
        )
        order = result.data
        assert len(order["items"][0]["spawned_kit_ids"]) == 2

        kits = (await client.call_tool("list_kits", {"status": "ordered"})).data
        assert len(kits) == 2
        assert all(k["grade"] == "RG" for k in kits)


async def test_retailer_get_or_create_is_case_insensitive(client):
    async with Client(mcp) as mcp_client:
        for retailer_name in ("Gundam Express Australia", "gundam express australia"):
            await mcp_client.call_tool(
                "create_order",
                {
                    "retailer": retailer_name,
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
    retailers = (await client.get("/retailers")).json()
    assert len(retailers) == 1


async def test_update_kit_status_normalizes_input():
    async with Client(mcp) as client:
        order = (
            await client.call_tool(
                "create_order",
                {
                    "retailer": "HLJ",
                    "order_date": "2026-08-02",
                    "items": [
                        {
                            "item_type": "kit",
                            "quantity": 1,
                            "unit_price_minor": 2800,
                            "currency_code": "JPY",
                            "kit": {"name": "HG Ground Type", "grade": "HG"},
                        }
                    ],
                },
            )
        ).data
        kit_id = order["items"][0]["spawned_kit_ids"][0]

        kit = (
            await client.call_tool("update_kit_status", {"kit_id": kit_id, "status": "In Transit"})
        ).data
        assert kit["status"] == "in_transit"

        with pytest.raises(ToolError, match="valid statuses"):
            await client.call_tool("update_kit_status", {"kit_id": kit_id, "status": "teleported"})


async def test_search_and_adjust_stock(client):
    consumable = (
        await client.post(
            "/consumables",
            json={"name": "Mr. Cement SP", "category": "cement", "quantity_on_hand": 3},
        )
    ).json()

    async with Client(mcp) as mcp_client:
        results = (await mcp_client.call_tool("search_catalog", {"query": "cement"})).data
        assert results[0]["id"] == consumable["id"]
        assert results[0]["item_type"] == "consumable"

        adjusted = (
            await mcp_client.call_tool(
                "adjust_stock",
                {"catalog_id": consumable["id"], "delta": -1, "reason": "used up on Sazabi"},
            )
        ).data
        assert adjusted["quantity_on_hand"] == 2

        with pytest.raises(ToolError, match="on hand"):
            await mcp_client.call_tool(
                "adjust_stock", {"catalog_id": consumable["id"], "delta": -5}
            )


async def test_receive_flow_via_mcp(client):
    consumable = (
        await client.post(
            "/consumables",
            json={"name": "Top Coat", "category": "paint", "quantity_on_hand": 1},
        )
    ).json()

    async with Client(mcp) as mcp_client:
        order = (
            await mcp_client.call_tool(
                "create_order",
                {
                    "retailer": "HLJ",
                    "order_date": "2026-08-02",
                    "items": [
                        {
                            "item_type": "consumable",
                            "quantity": 3,
                            "unit_price_minor": 550,
                            "currency_code": "JPY",
                            "catalog_ref_id": consumable["id"],
                        }
                    ],
                },
            )
        ).data
        assert order["received_at"] is None
        # stock untouched while in transit
        assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 1

        pending = (await mcp_client.call_tool("list_orders", {"pending_only": True})).data
        assert [o["id"] for o in pending] == [order["id"]]

        received = (
            await mcp_client.call_tool("mark_order_received", {"order_id": order["id"]})
        ).data
        assert received["received_at"] is not None
        assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 4

        assert (await mcp_client.call_tool("list_orders", {"pending_only": True})).data == []

        with pytest.raises(ToolError, match="already"):
            await mcp_client.call_tool("mark_order_received", {"order_id": order["id"]})


async def test_apply_upgrade_stock_guard(client):
    upgrade = (
        await client.post(
            "/upgrades",
            json={"name": "Waterslide decals", "manufacturer": "Bandai", "quantity_on_hand": 1},
        )
    ).json()
    kit = (await client.post("/kits", json={"name": "MG Freedom", "grade": "MG"})).json()

    async with Client(mcp) as mcp_client:
        applied = (
            await mcp_client.call_tool(
                "apply_upgrade", {"upgrade_id": upgrade["id"], "kit_id": kit["id"]}
            )
        ).data
        assert applied["quantity_used"] == 1

        with pytest.raises(ToolError, match="insufficient stock"):
            await mcp_client.call_tool(
                "apply_upgrade", {"upgrade_id": upgrade["id"], "kit_id": kit["id"]}
            )


async def test_create_order_is_held_to_the_same_line_ceiling_as_rest(client):
    """Rule 1 in the one place it is cheapest to break: the ceiling lives in the
    service, so the tool inherits it rather than declaring a second number (#43)."""
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="at most"):
            await mcp_client.call_tool(
                "create_order",
                {
                    "retailer": "USA Gundam Store",
                    "order_date": "2026-08-02",
                    "currency_code": "USD",
                    "items": [
                        {
                            "item_type": "kit",
                            "quantity": orders.MAX_LINE_QUANTITY + 1,
                            "unit_price_minor": 2999,
                            "currency_code": "USD",
                            "kit": {"name": "RG Nu Gundam", "grade": "RG"},
                        }
                    ],
                },
            )
        assert (await mcp_client.call_tool("list_kits", {})).data == []


async def test_create_order_is_held_to_the_aggregate_fanout_ceiling_too(client):
    """#77's aggregate mate of the test above, same rule-1 reasoning: eleven lines,
    each within its own ceiling, refused by the shared aggregate as a ToolError."""
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="add up to 10,001"):
            await mcp_client.call_tool(
                "create_order",
                {
                    "retailer": "USA Gundam Store",
                    "order_date": "2026-08-02",
                    "currency_code": "USD",
                    "items": [
                        {
                            "item_type": "kit",
                            "quantity": quantity,
                            "unit_price_minor": 2999,
                            "currency_code": "USD",
                            "kit": {"name": f"RG Nu Gundam {i}", "grade": "RG"},
                        }
                        for i, quantity in enumerate([1_000] * 10 + [1])
                    ],
                },
            )
        assert (await mcp_client.call_tool("list_kits", {})).data == []


# --- Withdrawing an upgrade application (#61, §3.6) ---------------------------------


async def _seed_upgrade_and_kit(client, quantity: int) -> tuple[dict, dict]:
    upgrade = (
        await client.post(
            "/upgrades",
            json={
                "name": "Metal thrusters",
                "manufacturer": "Metal Build",
                "quantity_on_hand": quantity,
            },
        )
    ).json()
    kit = (await client.post("/kits", json={"name": "Sazabi Ver.Ka", "grade": "MG"})).json()
    return upgrade, kit


async def test_get_kit_embeds_upgrade_applications(client):
    """Both state axes: the list is present-and-empty before any application, and
    carries the application id + upgrade name after — the id is what
    withdraw_upgrade_application takes."""
    upgrade, kit = await _seed_upgrade_and_kit(client, 5)
    async with Client(mcp) as mcp_client:
        empty = (await mcp_client.call_tool("get_kit", {"kit_id": kit["id"]})).data
        assert empty["upgrade_applications"] == []

        applied = (
            await mcp_client.call_tool(
                "apply_upgrade",
                {"upgrade_id": upgrade["id"], "kit_id": kit["id"], "quantity": 2},
            )
        ).data
        loaded = (await mcp_client.call_tool("get_kit", {"kit_id": kit["id"]})).data
        (application,) = loaded["upgrade_applications"]
        assert application["id"] == applied["id"]
        assert application["upgrade_name"] == "Metal thrusters"
        assert application["quantity_used"] == 2


async def test_withdraw_tool_restores_or_keeps_stock_as_told(client):
    upgrade, kit = await _seed_upgrade_and_kit(client, 5)
    async with Client(mcp) as mcp_client:
        applied = (
            await mcp_client.call_tool(
                "apply_upgrade",
                {"upgrade_id": upgrade["id"], "kit_id": kit["id"], "quantity": 2},
            )
        ).data
        result = (
            await mcp_client.call_tool(
                "withdraw_upgrade_application",
                {"application_id": applied["id"], "restore_stock": True},
            )
        ).data
        assert result["stock_restored"] is True
        assert result["quantity_on_hand"] == 5

        applied = (
            await mcp_client.call_tool(
                "apply_upgrade",
                {"upgrade_id": upgrade["id"], "kit_id": kit["id"], "quantity": 1},
            )
        ).data
        result = (
            await mcp_client.call_tool(
                "withdraw_upgrade_application",
                {"application_id": applied["id"], "restore_stock": False},
            )
        ).data
        assert result["stock_restored"] is False
        assert result["quantity_on_hand"] == 4
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 4


async def test_withdraw_tool_requires_the_restore_choice(client):
    """No default on the MCP surface either (#61): an agent is not allowed to
    guess whether the part physically survived."""
    upgrade, kit = await _seed_upgrade_and_kit(client, 5)
    async with Client(mcp) as mcp_client:
        applied = (
            await mcp_client.call_tool(
                "apply_upgrade",
                {"upgrade_id": upgrade["id"], "kit_id": kit["id"], "quantity": 2},
            )
        ).data
        # match pins the refusal to the missing argument — a bare ToolError is
        # also what an unknown tool raises, which is what this call does on a
        # tree without the tool, and that must not read as the control working.
        with pytest.raises(ToolError, match="restore_stock"):
            await mcp_client.call_tool(
                "withdraw_upgrade_application", {"application_id": applied["id"]}
            )
    # Nothing happened: the application survives and the stock stays spent.
    assert len((await client.get(f"/kits/{kit['id']}/applications")).json()) == 1
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 3
