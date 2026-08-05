import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp

EXPECTED_TOOLS = {
    "list_kits",
    "get_kit",
    "update_kit_status",
    "search_catalog",
    "create_order",
    "adjust_stock",
    "apply_upgrade",
}


async def test_all_doc_section_7_tools_exposed():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert {t.name for t in tools} == EXPECTED_TOOLS


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
