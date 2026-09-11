import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp
from app.services import orders

EXPECTED_TOOLS = {
    "get_meta",
    "get_summary",
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
    assert set(meta) == {"version", "reference_currency", "supported_interface_languages"}


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


async def test_an_omitted_currency_reads_the_settings_row(client):
    # The default the docstring points agents at is the instance-settings row
    # (#23) — a changed setting must reach the very next tool call, same
    # process, no restart.
    await client.patch("/settings", json={"reference_currency": "JPY"})
    async with Client(mcp) as mcp_client:
        order = (
            await mcp_client.call_tool(
                "create_order",
                {
                    "retailer": "Yodobashi",
                    "order_date": "2026-08-02",
                    "items": [
                        {
                            "item_type": "kit",
                            "quantity": 1,
                            "unit_price_minor": 2999,
                            "currency_code": "JPY",
                            "kit": {"name": "HG Nightingale", "grade": "HG"},
                        }
                    ],
                },
            )
        ).data
    assert order["currency_code"] == "JPY"


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


# --- sort and limit on the list tools (§13.4, #232) -------------------------------


async def test_list_orders_tool_reads_the_placement_date_in_the_instance_zone(client, retailer):
    """The order clock is the service's, instance zone included: an order placed on
    2 August against one shipped at 15:00Z on 1 August ranks under Brisbane's
    midnight (14:00Z on the 1st) the same way on the tool as on REST, and the
    other way under Los Angeles's (Codex #236 P2-1)."""
    for number, order_date, extra in (
        ("A", "2026-08-02", {}),
        ("B", "2026-07-31", {"shipped_at": "2026-08-01T15:00:00+00:00"}),
    ):
        resp = await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": order_date,
                "order_number": number,
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": f"Kit {number}", "grade": "HG"},
                    }
                ],
                **extra,
            },
        )
        assert resp.status_code == 201, resp.text

    for zone, expected in (("Australia/Brisbane", ["B", "A"]), ("America/Los_Angeles", ["A", "B"])):
        assert (await client.patch("/settings", json={"time_zone": zone})).status_code == 200
        async with Client(mcp) as mcp_client:
            tool = (await mcp_client.call_tool("list_orders", {"sort": "recent"})).data
        rest = (await client.get("/orders", params={"sort": "recent"})).json()
        assert [o["order_number"] for o in tool] == expected, zone
        assert [o["order_number"] for o in rest] == expected, zone


async def test_list_sort_and_limit_match_rest(client, retailer):
    """One service function, one vocabulary: the tool's `sort`/`limit` return
    the rows REST returns, in the same order, and refuse the same strangers."""
    zaku = (await client.post("/kits", json={"name": "Zaku II", "grade": "HG"})).json()
    await client.post("/kits", json={"name": "Gouf", "grade": "HG"})
    await client.post("/kits", json={"name": "Dom", "grade": "HG", "status": "building"})
    await client.patch(f"/kits/{zaku['id']}", json={"status": "building"})
    for number, order_date, extra in (
        ("R", "2026-01-10", {"received": True, "received_at": "2026-03-01T10:00:00+00:00"}),
        ("S", "2026-02-01", {"shipped_at": "2026-02-20T10:00:00+00:00"}),
        ("P", "2026-02-25", {}),
    ):
        resp = await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": order_date,
                "order_number": number,
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": f"Kit {number}", "grade": "HG"},
                    }
                ],
                **extra,
            },
        )
        assert resp.status_code == 201, resp.text

    async with Client(mcp) as mcp_client:
        kits_tool = (await mcp_client.call_tool("list_kits", {"sort": "recent", "limit": 2})).data
        orders_tool = (
            await mcp_client.call_tool("list_orders", {"sort": "recent", "pending_only": True})
        ).data
        # Both lists, because each service holds its own check — an unknown
        # sort must be refused, never quietly read as the default order.
        with pytest.raises(ToolError, match="sort must be one of"):
            await mcp_client.call_tool("list_kits", {"sort": "newest"})
        with pytest.raises(ToolError, match="sort must be one of"):
            await mcp_client.call_tool("list_orders", {"sort": "newest"})
        # `limit` is a PositiveInt4 on the tool (test_int4_bounds), so a zero is
        # refused by the schema before the service's own check — either way a
        # ToolError naming the parameter.
        with pytest.raises(ToolError, match="limit"):
            await mcp_client.call_tool("list_orders", {"limit": 0})

    kits_rest = (await client.get("/kits", params={"sort": "recent", "limit": 2})).json()
    orders_rest = (
        await client.get("/orders", params={"sort": "recent", "pending_only": "true"})
    ).json()
    assert [k["id"] for k in kits_tool] == [k["id"] for k in kits_rest]
    # "Kit P" first: the pending order spawned it just now, after Zaku moved.
    # The other two spawned kits sit at the back — a supplied shipped_at or
    # received_at is the kit's status clock (#120), and those were backdated.
    assert [k["name"] for k in kits_tool] == ["Kit P", "Zaku II"]
    assert [o["id"] for o in orders_tool] == [o["id"] for o in orders_rest]
    assert [o["order_number"] for o in orders_tool] == ["P", "S"]


# --- #56: create_order's description matches its schema -----------------------------------
#
# The tool's docstring once told an agent two false things and a validation
# failure followed (#56): that a per-line `currency_code` could be omitted (the
# item schema requires it), and to consult a `meta` resource that does not
# exist. These assert the description and the exposed input schema agree, so a
# regression of either is loud. The value axis is currency present/absent at the
# line level; the asymmetry (order-level optional, per-line required) is read
# from the schema an agent actually consumes.


async def test_create_order_description_points_only_at_real_surfaces():
    async with Client(mcp) as client:
        tools = {t.name: (t.description or "") for t in await client.list_tools()}
    description = tools["create_order"]
    lowered = description.lower()
    # #56 (2): the pointer for the instance currency is get_meta, a real tool —
    # never the phantom `meta` resource the old docstring named. The only "meta"
    # in the description must be get_meta: a plain, backticked or otherwise-spelled
    # `meta` resource reference is the phantom (Codex #250 F4 slipped a backticked
    # one past the old "meta resource" substring guard).
    assert "get_meta" in tools
    assert "get_meta" in lowered
    assert "meta" not in lowered.replace("get_meta", "")
    # Every other tool the description directs an agent to is real.
    for named in ("search_catalog", "list_catalog_categories", "mark_order_received"):
        assert named in description, named
        assert named in tools, named


async def test_create_order_description_and_schema_agree_on_the_currency_asymmetry():
    # #56 (1): the exposed input schema makes the order-level currency optional
    # and each line's required; the *description* must say the same, or it lies
    # to an agent. The old wording ("omit currency_code …") did not scope the
    # omission to the order header, so both the schema and the description are
    # checked here (Codex #250 F4 — the schema-only test passed on the misleading
    # wording).
    async with Client(mcp) as client:
        tool = next(t for t in await client.list_tools() if t.name == "create_order")
    schema = tool.input_schema
    assert "currency_code" in schema["properties"]
    assert "currency_code" not in schema["required"]  # order level: optional
    item = schema["properties"]["items"]["items"]
    assert "currency_code" in item["properties"]
    assert "currency_code" in item["required"]  # per line: required
    # Normalise whitespace: the docstring wraps clauses across lines.
    normalized = " ".join((tool.description or "").lower().split())
    assert "item line's currency_code is required" in normalized  # per line: required
    assert "order-level currency_code" in normalized  # the omission is scoped to it
    assert "omit" in normalized


async def test_create_order_rejects_a_line_without_a_currency():
    # The behaviour behind the schema: a line omitting currency_code is refused
    # by the MCP boundary (a ToolError naming the field), which is exactly what
    # the old docstring wrongly told an agent to do.
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as raised:
            await client.call_tool(
                "create_order",
                {
                    "retailer": "USA Gundam Store",
                    "order_date": "2026-08-02",
                    "currency_code": "USD",
                    "items": [
                        {
                            "item_type": "kit",
                            "quantity": 1,
                            "unit_price_minor": 2999,
                            # currency_code omitted — required per line
                            "kit": {"name": "RG Sazabi", "grade": "RG"},
                        }
                    ],
                },
            )
    assert "currency_code" in str(raised.value)
