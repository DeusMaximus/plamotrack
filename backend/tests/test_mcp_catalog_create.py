"""The MCP create and list half of the catalog surface (#98).

#92 gave MCP the edit half of rule 1's parity and left creation reachable only
through `create_order` — which insists on a retailer, a date and a price, so a
gift kit or a first stocktake could only be recorded by inventing a purchase
that never happened (§6). These tools are thin wrappers over the same service
functions the REST routes call, so every test here reads its result back over
REST: identical read-back is the parity claim itself, not a convenience.

`search_catalog` is the other half: it takes a query and caps results per type,
so it was never a listing. `list_catalog_items` is — the cap test drives more
rows than the cap precisely so the two calls can never silently be the same.
"""

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp


async def _tool(name: str, args: dict):
    async with Client(mcp) as mcp_client:
        return (await mcp_client.call_tool(name, args)).data


_CREATE_CASES = [
    pytest.param(
        "create_catalog_tool",
        "tool",
        {
            "name": "Godhand SPN-120",
            "category": "Cutting",
            "quantity_on_hand": 2,
            "unit_cost_reference_minor": 4500,
            "unit_cost_reference_currency": "AUD",
            "condition_notes": "still sharp",
        },
        "/tools",
        id="tool",
    ),
    pytest.param(
        "create_catalog_consumable",
        "consumable",
        {
            "name": "Mr Cement S",
            "category": "Glue",
            "quantity_on_hand": 3,
            "low_stock_threshold": 1,
        },
        "/consumables",
        id="consumable",
    ),
    pytest.param(
        "create_catalog_upgrade",
        "upgrade",
        {"name": "Metal thrusters", "manufacturer": "Metal Build", "quantity_on_hand": 1},
        "/upgrades",
        id="upgrade",
    ),
    pytest.param(
        "create_catalog_display",
        "display_item",
        {
            "name": "Action Base 2",
            "category": "Stand",
            "scale": "1/144",
            "manufacturer": "Bandai",
            "quantity_on_hand": 4,
            "notes": "clear sprue",
        },
        "/display-items",
        id="display",
    ),
]


@pytest.mark.parametrize(("tool_name", "arg_name", "payload", "rest_path"), _CREATE_CASES)
async def test_mcp_create_reads_back_identically_over_rest(
    client, tool_name, arg_name, payload, rest_path
):
    created = await _tool(tool_name, {arg_name: payload})
    for key, value in payload.items():
        assert created[key] == value

    (rest_row,) = (await client.get(rest_path)).json()
    assert rest_row == created


@pytest.mark.parametrize(("tool_name", "arg_name", "payload", "rest_path"), _CREATE_CASES)
async def test_mcp_create_refuses_a_duplicate_name(client, tool_name, arg_name, payload, rest_path):
    await _tool(tool_name, {arg_name: payload})
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="already exists"):
            await mcp_client.call_tool(
                tool_name, {arg_name: {**payload, "name": payload["name"].upper()}}
            )
    # The refusal refused — one row, not two (the §3.9 de-dup claim, not just an error).
    assert len((await client.get(rest_path)).json()) == 1


async def test_mcp_create_quantity_defaults_to_zero(client):
    # "Physically on hand" starts at nothing unless stated — the tool must not
    # infer a 1 from the item's existence the way a purchase line would.
    created = await _tool(
        "create_catalog_tool", {"tool": {"name": "Glass file", "category": "Filing"}}
    )
    assert created["quantity_on_hand"] == 0


async def test_mcp_create_folds_category_like_every_other_writer(client):
    await _tool("create_catalog_tool", {"tool": {"name": "Godhand SPN-120", "category": "Cutting"}})
    row = await _tool(
        "create_catalog_tool", {"tool": {"name": "Glass file", "category": "cutting"}}
    )
    assert row["category"] == "Cutting"


# --- create_kit ------------------------------------------------------------------


async def test_mcp_create_kit_derives_scale_and_reads_back_over_rest(client):
    created = await _tool("create_kit", {"kit": {"name": "Sazabi Ver.Ka", "grade": "MG"}})
    # The derivation is the part a thin wrapper can lose (§3.1): the service
    # derives scale from the grade, and the wrapper must not have its own idea.
    assert created["scale"] == "1/100"
    assert created["status"] == "backlog"

    rest_row = (await client.get(f"/kits/{created['id']}")).json()
    assert rest_row == created


async def test_mcp_create_kit_keeps_an_explicit_scale(client):
    created = await _tool(
        "create_kit", {"kit": {"name": "Big Zam", "grade": "MG", "scale": "1/550"}}
    )
    assert created["scale"] == "1/550"


async def test_mcp_create_kit_takes_the_tolerant_status_vocabulary(client):
    transit = await _tool(
        "create_kit", {"kit": {"name": "Nu Gundam", "grade": "RG", "status": "In Transit"}}
    )
    assert transit["status"] == "in_transit"
    arrived = await _tool(
        "create_kit", {"kit": {"name": "Zeta", "grade": "HG", "status": "arrived"}}
    )
    assert arrived["status"] == "backlog"

    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="valid statuses"):
            await mcp_client.call_tool(
                "create_kit", {"kit": {"name": "Kshatriya", "grade": "HG", "status": "wishlist"}}
            )


async def test_mcp_create_kit_backfill_dates_are_kept_not_derived(client):
    created = await _tool(
        "create_kit",
        {
            "kit": {
                "name": "RX-78-2",
                "grade": "MG",
                "status": "complete",
                "build_started_at": "2026-01-10T09:00:00+10:00",
            }
        },
    )
    # Compared as instants: timestamptz keeps the point in time, not the offset
    # it was written in, so the string may legitimately come back UTC-rendered.
    from datetime import datetime

    assert datetime.fromisoformat(created["build_started_at"]) == datetime.fromisoformat(
        "2026-01-10T09:00:00+10:00"
    )
    # Created already-complete: no live transition happened, so nothing stamps
    # the completion date — the no-invention rule the importer follows (#94).
    assert created["build_completed_at"] is None

    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="[Tt]imezone"):
            await mcp_client.call_tool(
                "create_kit",
                {
                    "kit": {
                        "name": "Naive",
                        "grade": "HG",
                        "build_started_at": "2026-01-10T09:00:00",
                    }
                },
            )


# --- list_catalog_items ----------------------------------------------------------


async def test_listing_spans_more_rows_than_the_search_cap(client):
    for n in range(25):
        resp = await client.post(
            "/consumables", json={"name": f"Paint {n:02d}", "category": "Paint"}
        )
        assert resp.status_code == 201

    search = await _tool("search_catalog", {"query": "Paint"})
    assert len(search) == 20  # the per-type cap — a search, not a listing

    listing = await _tool("list_catalog_items", {"item_type": "consumable"})
    assert len(listing) == 25
    # Full per-type fields, not the search projection: this row can answer
    # "what am I low on?", which the search result cannot.
    assert all("low_stock_threshold" in row for row in listing)


async def test_an_empty_catalog_lists_as_empty(client):
    assert await _tool("list_catalog_items", {"item_type": "tool"}) == []


async def test_list_item_type_is_tolerant_and_kits_are_refused(client):
    resp = await client.post("/display-items", json={"name": "Action Base 2", "category": "Stand"})
    assert resp.status_code == 201

    rows = await _tool("list_catalog_items", {"item_type": "Display Items"})
    assert [row["name"] for row in rows] == ["Action Base 2"]

    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="list_kits"):
            await mcp_client.call_tool("list_catalog_items", {"item_type": "kit"})
        with pytest.raises(ToolError, match="valid types"):
            await mcp_client.call_tool("list_catalog_items", {"item_type": "gundam"})
