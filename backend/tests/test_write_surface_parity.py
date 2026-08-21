"""REST and MCP reach the same service functions (#92, #55).

Architecture rule 1 says routers and MCP tools are thin wrappers over one service
layer and must never diverge. They had, in both directions: every edit the service
exposes was reachable from REST and not from MCP, and `adjust_stock` was reachable
from MCP and not from REST. Neither gap was a missing capability — both were a
missing wrapper.

What that costs, and so what these tests are really about:

- An agent could create a retailer as a side effect of an order and then never say
  anything about it. "The box arrived crushed" had no home.
- The browser could only express a stock change as an absolute `quantity_on_hand`,
  which is a read-then-write over a number three writer types can move (#35). A
  signed delta is the same operation without the race.

The PATCH semantics are the part worth testing hardest. An MCP tool is a function
signature, so the obvious spelling — one optional parameter per field, defaulting
to `None` — cannot tell "leave the notes alone" from "erase the notes"; both arrive
as `None`. These tools take a patch **model** instead, so `model_fields_set` keeps
the distinction the REST PATCH has always had. Every update test below therefore
drives three values per field, not one: absent, explicit null, and a new value.
"""

import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp


async def _tool(client, name: str, args: dict):
    async with Client(mcp) as mcp_client:
        return (await mcp_client.call_tool(name, args)).data


async def _tool_error(name: str, args: dict) -> str:
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as raised:
            await mcp_client.call_tool(name, args)
    return str(raised.value)


# --- #55: the delta adjustment REST never had ----------------------------------


async def _catalog_row(client, path: str, payload: dict) -> dict:
    resp = await client.post(path, json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.parametrize(
    ("path", "payload", "list_path"),
    [
        pytest.param(
            "/tools", {"name": "Godhand SPN-120", "category": "cutting"}, "/tools", id="tool"
        ),
        pytest.param(
            "/consumables",
            {"name": "Mr Cement S", "category": "glue"},
            "/consumables",
            id="consumable",
        ),
        pytest.param(
            "/upgrades",
            {"name": "Metal thrusters", "manufacturer": "Metal Build"},
            "/upgrades",
            id="upgrade",
        ),
        pytest.param(
            "/display-items",
            {"name": "Action Base 2", "category": "stand"},
            "/display-items",
            id="display",
        ),
    ],
)
async def test_rest_adjust_reaches_every_catalog_table(client, path, payload, list_path):
    """One case per table — and *every* table, which is the part that lapsed.

    `adjust_stock` resolves the id by walking `CATALOG_MODELS` in order and
    returning on the first hit, so a route that only ever reached `tools` — the
    first entry — passes any single-type test. Display items are last in that
    mapping, which makes them the case a short walk drops (#129 review, round 2).
    """
    row = await _catalog_row(client, path, {**payload, "quantity_on_hand": 5})

    up = await client.post(f"/catalog/{row['id']}/adjust", json={"delta": 3, "reason": "restock"})
    assert up.status_code == 200, up.text
    assert up.json()["quantity_on_hand"] == 8
    assert up.json()["id"] == row["id"]
    assert up.json()["reason"] == "restock"

    down = await client.post(f"/catalog/{row['id']}/adjust", json={"delta": -6})
    assert down.status_code == 200, down.text
    assert down.json()["quantity_on_hand"] == 2
    assert down.json()["reason"] is None

    assert (await client.get(list_path)).json()[0]["quantity_on_hand"] == 2


async def test_rest_adjust_and_mcp_adjust_are_the_same_operation(client):
    """The parity claim itself: alternating doors onto one running total. Asserted on
    the payloads as well as the stock, because two surfaces agreeing on the number
    while disagreeing on what they report is the divergence this rule is about."""
    tool = await _catalog_row(
        client, "/tools", {"name": "Nippers", "category": "cutting", "quantity_on_hand": 10}
    )

    rest = (await client.post(f"/catalog/{tool['id']}/adjust", json={"delta": -4})).json()
    assert rest["quantity_on_hand"] == 6

    via_mcp = await _tool(client, "adjust_stock", {"catalog_id": tool["id"], "delta": -4})
    assert via_mcp["quantity_on_hand"] == 2

    assert via_mcp["item_type"] == rest["item_type"] == "tool"
    assert via_mcp["name"] == rest["name"] == "Nippers"
    assert set(via_mcp) == set(rest)


async def test_rest_adjust_zero_is_a_legal_no_op(client):
    """MCP has always accepted it, so REST does too. A door that refuses what its
    twin allows is the same divergence in miniature."""
    tool = await _catalog_row(
        client, "/tools", {"name": "Files", "category": "sanding", "quantity_on_hand": 4}
    )
    resp = await client.post(f"/catalog/{tool['id']}/adjust", json={"delta": 0})
    assert resp.status_code == 200
    assert resp.json()["quantity_on_hand"] == 4


async def test_rest_adjust_below_zero_is_refused_and_changes_nothing(client):
    consumable = await _catalog_row(
        client, "/consumables", {"name": "Top coat", "category": "paint", "quantity_on_hand": 2}
    )
    resp = await client.post(f"/catalog/{consumable['id']}/adjust", json={"delta": -3})
    assert resp.status_code == 409
    assert "only 2 on hand" in resp.json()["detail"]
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 2


async def test_rest_adjust_unknown_id_is_not_found(http_client):
    """404, not 422: a well-formed uuid naming nothing is a missing row, and the
    three-table resolver is the only thing that can tell."""
    resp = await http_client.post(f"/catalog/{uuid.uuid4()}/adjust", json={"delta": 1})
    assert resp.status_code == 404, f"{resp.status_code}: {resp.text[:200]}"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="missing-delta"),
        pytest.param({"delta": "two"}, id="non-numeric-delta"),
        pytest.param({"delta": 1.5}, id="fractional-delta"),
        pytest.param({"delta": 1, "quantity_on_hand": 9}, id="extra-field"),
    ],
)
async def test_rest_adjust_refuses_a_malformed_body(http_client, client, body):
    """`extra="forbid"` earns its own case: `quantity_on_hand` is the field this
    route exists to stop callers writing directly, so a body carrying it is the
    mistake most worth naming rather than silently ignoring."""
    tool = await _catalog_row(
        client, "/tools", {"name": "Nippers", "category": "cutting", "quantity_on_hand": 3}
    )
    resp = await http_client.post(f"/catalog/{tool['id']}/adjust", json=body)
    assert resp.status_code == 422, f"{resp.status_code}: {resp.text[:200]}"
    assert (await client.get("/tools")).json()[0]["quantity_on_hand"] == 3


# --- #92: the edits MCP never had ----------------------------------------------


async def test_a_retailer_named_on_an_order_can_be_rated_without_touching_rest(client):
    """The motivating case. `create_order` matches a retailer by name and creates it
    if new, so an agent-entered order leaves a row holding nothing but a name — and
    until now an agent had no way to say anything else about it."""
    await _tool(
        client,
        "create_order",
        {
            "retailer": "Gundam Express Australia",
            "order_date": "2026-08-16",
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

    listed = await _tool(client, "list_retailers", {})
    assert [r["name"] for r in listed] == ["Gundam Express Australia"]
    assert listed[0]["rating"] is None

    rated = await _tool(
        client,
        "update_retailer",
        {
            "retailer_id": listed[0]["id"],
            "changes": {
                "rating": 2,
                "packing_quality": "poor",
                "notes": "box arrived crushed",
            },
        },
    )
    assert rated["rating"] == 2
    assert rated["packing_quality"] == "poor"

    # And the browser sees exactly what the agent wrote — one row, one service.
    from_rest = (await client.get("/retailers")).json()
    assert len(from_rest) == 1
    assert from_rest[0]["notes"] == "box arrived crushed"
    assert from_rest[0]["packing_quality"] == "poor"


async def test_mcp_retailer_patch_distinguishes_absent_from_null(client):
    """Three values per field: absent leaves it, null clears it, a value replaces it.

    An MCP tool taking one optional parameter per field cannot express the middle
    one — an omitted argument and an explicit null both arrive as `None` — which is
    why these tools take a patch model. A test that only ever sends new values
    passes against the spelling that silently erases everything it doesn't mention.
    """
    created = await _tool(
        client,
        "create_retailer",
        {
            "retailer": {
                "name": "Hobby Link Japan",
                "url": "https://hlj.com",
                "rating": 5,
                "shipping_speed": "fast",
                "would_order_again": "yes",
                "notes": "reliable",
            }
        },
    )
    assert created["rating"] == 5
    assert created["shipping_speed"] == "fast"

    # Absent: one field named, everything else survives.
    narrowed = await _tool(
        client,
        "update_retailer",
        {"retailer_id": created["id"], "changes": {"rating": 4}},
    )
    assert narrowed["rating"] == 4
    assert narrowed["notes"] == "reliable"
    assert narrowed["url"] == "https://hlj.com"
    assert narrowed["shipping_speed"] == "fast"

    # Null: the field named is cleared, and only that one.
    cleared = await _tool(
        client,
        "update_retailer",
        {"retailer_id": created["id"], "changes": {"notes": None}},
    )
    assert cleared["notes"] is None
    assert cleared["rating"] == 4
    assert cleared["url"] == "https://hlj.com"

    # An empty patch is a legal no-op rather than a wipe.
    untouched = await _tool(
        client, "update_retailer", {"retailer_id": created["id"], "changes": {}}
    )
    assert untouched["rating"] == 4
    assert untouched["url"] == "https://hlj.com"


async def test_mcp_retailer_patch_refuses_what_rest_refuses(client):
    retailer = (await client.post("/retailers", json={"name": "Amiami"})).json()

    nulled_name = await _tool_error(
        "update_retailer", {"retailer_id": retailer["id"], "changes": {"name": None}}
    )
    assert "name cannot be null" in nulled_name

    unknown_field = await _tool_error(
        "update_retailer", {"retailer_id": retailer["id"], "changes": {"ratings": 5}}
    )
    assert "ratings" in unknown_field

    out_of_range = await _tool_error(
        "update_retailer", {"retailer_id": retailer["id"], "changes": {"rating": 9}}
    )
    assert "rating" in out_of_range

    missing = await _tool_error(
        "update_retailer", {"retailer_id": str(uuid.uuid4()), "changes": {"rating": 3}}
    )
    assert "not found" in missing

    malformed = await _tool_error(
        "update_retailer", {"retailer_id": "not-a-uuid", "changes": {"rating": 3}}
    )
    assert "not a valid UUID" in malformed

    assert (await client.get("/retailers")).json()[0]["name"] == "Amiami"


async def test_mcp_update_kit_edits_metadata_without_restamping_the_pipeline(client):
    """The state axis, not just the values: `status_updated_at` is what a build
    duration will be read from (#94), and it moves only when the status does.

    A tool that widens `update_kit_status` is one careless `setattr` away from
    stamping it on every edit, and a rating-only edit is exactly the call that would
    hide it — nothing else in the payload changes, so nothing else can disagree.
    """
    kit = (await client.post("/kits", json={"name": "Sazabi Ver.Ka", "grade": "MG"})).json()
    stamped_at = kit["status_updated_at"]

    metadata_only = await _tool(
        client,
        "update_kit",
        {"kit_id": kit["id"], "changes": {"rating": 5, "build_notes": "candy coat"}},
    )
    assert metadata_only["rating"] == 5
    assert metadata_only["build_notes"] == "candy coat"
    assert metadata_only["status"] == "backlog"
    assert metadata_only["status_updated_at"] == stamped_at

    # Restating the status it already holds is not a transition either.
    restated = await _tool(
        client, "update_kit", {"kit_id": kit["id"], "changes": {"status": "backlog"}}
    )
    assert restated["status_updated_at"] == stamped_at

    # A real transition does move it — otherwise the assertions above prove nothing.
    # Spelled the way an agent would, to pin that this tool normalises status the
    # same way `update_kit_status` does rather than demanding the exact enum value.
    moved = await _tool(
        client, "update_kit", {"kit_id": kit["id"], "changes": {"status": "Building"}}
    )
    assert moved["status"] == "building"
    assert moved["status_updated_at"] != stamped_at
    assert moved["rating"] == 5


async def test_mcp_update_kit_patch_semantics_and_refusals(client):
    kit = (
        await client.post(
            "/kits",
            json={"name": "RG Nu Gundam", "grade": "RG", "build_notes": "waiting on decals"},
        )
    ).json()

    renamed = await _tool(
        client, "update_kit", {"kit_id": kit["id"], "changes": {"kit_number": "RG-31"}}
    )
    assert renamed["kit_number"] == "RG-31"
    assert renamed["build_notes"] == "waiting on decals"

    cleared = await _tool(
        client, "update_kit", {"kit_id": kit["id"], "changes": {"build_notes": None}}
    )
    assert cleared["build_notes"] is None
    assert cleared["kit_number"] == "RG-31"

    for field in ("name", "grade", "status"):
        message = await _tool_error("update_kit", {"kit_id": kit["id"], "changes": {field: None}})
        assert f"{field} cannot be null" in message

    bad_status = await _tool_error(
        "update_kit", {"kit_id": kit["id"], "changes": {"status": "half built"}}
    )
    assert "invalid status" in bad_status

    assert (await client.get(f"/kits/{kit['id']}")).json()["name"] == "RG Nu Gundam"


async def test_update_kit_status_remains_the_shortcut_for_the_same_service_call(client):
    """`update_kit_status` is kept rather than replaced — removing a tool a client may
    already call is a visible break, and the Kanban move is the frequent case. It has
    to stay the same operation, not a second implementation of one."""
    kit = (await client.post("/kits", json={"name": "MG Sinanju", "grade": "MG"})).json()

    via_shortcut = await _tool(
        client, "update_kit_status", {"kit_id": kit["id"], "status": "building"}
    )
    via_general = await _tool(
        client, "update_kit", {"kit_id": kit["id"], "changes": {"status": "complete"}}
    )
    assert via_shortcut["status"] == "building"
    assert via_general["status"] == "complete"
    assert set(via_shortcut) == set(via_general)


@pytest.mark.parametrize(
    ("tool_name", "path", "create", "id_arg", "nullable", "non_nullable"),
    [
        pytest.param(
            "update_catalog_tool",
            "/tools",
            {"name": "Godhand SPN-120", "category": "cutting", "condition_notes": "sharp"},
            "tool_id",
            "condition_notes",
            "category",
            id="tool",
        ),
        pytest.param(
            "update_catalog_consumable",
            "/consumables",
            {"name": "Mr Cement S", "category": "glue", "low_stock_threshold": 2},
            "consumable_id",
            "low_stock_threshold",
            "category",
            id="consumable",
        ),
        pytest.param(
            "update_catalog_upgrade",
            "/upgrades",
            {"name": "Metal thrusters", "manufacturer": "Metal Build"},
            "upgrade_id",
            None,
            "manufacturer",
            id="upgrade",
        ),
        pytest.param(
            "update_catalog_display",
            "/display-items",
            {"name": "Action Base 2", "category": "stand", "scale": "1/144"},
            "display_item_id",
            "scale",
            "category",
            id="display",
        ),
    ],
)
async def test_mcp_catalog_edits_cover_every_table(
    client, tool_name, path, create, id_arg, nullable, non_nullable
):
    """One case per table. They carry different fields — that is why they are
    separate tools taking the real PATCH schemas rather than one tool over a
    hand-written union of their columns, which would need editing again every time
    a column is added to any of them.

    *Every* table, not most of them. `update_catalog_display` shipped covered only
    by `test_all_doc_section_7_tools_exposed`, which proves a tool is registered and
    nothing about where it writes: changing its `ItemType.DISPLAY` to `ItemType.TOOL`
    left both suites green (#129 review, round 2). This row is what kills that —
    the dispatch is only observable through a call that reads the row back.
    """
    row = (await client.post(path, json={**create, "quantity_on_hand": 4})).json()

    renamed = await _tool(client, tool_name, {id_arg: row["id"], "changes": {"name": "Renamed"}})
    assert renamed["name"] == "Renamed"
    assert renamed["quantity_on_hand"] == 4
    assert renamed[non_nullable] == create[non_nullable]

    if nullable is not None:
        assert renamed[nullable] == create[nullable]
        cleared = await _tool(client, tool_name, {id_arg: row["id"], "changes": {nullable: None}})
        assert cleared[nullable] is None
        assert cleared["name"] == "Renamed"

    nulled = await _tool_error(tool_name, {id_arg: row["id"], "changes": {non_nullable: None}})
    assert f"{non_nullable} cannot be null" in nulled

    missing = await _tool_error(tool_name, {id_arg: str(uuid.uuid4()), "changes": {"name": "x"}})
    assert "not found" in missing

    assert (await client.get(path)).json()[0]["name"] == "Renamed"


async def test_mcp_tool_edit_still_enforces_the_money_pair(client):
    """§6's paired snapshot, through the new door. The service checks the *merged*
    row, so a patch naming one half of the pair is only wrong depending on what the
    row already holds — both states are driven here."""
    tool = (await client.post("/tools", json={"name": "Airbrush", "category": "spray"})).json()

    half = await _tool_error(
        "update_catalog_tool",
        {"tool_id": tool["id"], "changes": {"unit_cost_reference_minor": 12000}},
    )
    assert "must be set together" in half

    paired = await _tool(
        client,
        "update_catalog_tool",
        {
            "tool_id": tool["id"],
            "changes": {
                "unit_cost_reference_minor": 12000,
                "unit_cost_reference_currency": "AUD",
            },
        },
    )
    assert paired["unit_cost_reference_minor"] == 12000

    # Now that the row holds the other half, the same one-field patch is legal.
    corrected = await _tool(
        client,
        "update_catalog_tool",
        {"tool_id": tool["id"], "changes": {"unit_cost_reference_minor": 13500}},
    )
    assert corrected["unit_cost_reference_minor"] == 13500
    assert corrected["unit_cost_reference_currency"] == "AUD"


async def test_mcp_update_kit_refuses_an_unknown_field(client):
    """`_KitPatch` subclasses `KitUpdate` to widen `status` alone, and inherits
    `extra="forbid"` with everything else.

    Worth its own case because the kit path is the one that subclasses and then
    rebuilds the model from a dump, and nothing else in the suite sent it an
    unknown key — the retailer matrix did, the kit one did not. Raised by the
    Cursor Grok 4.6 review of #100.

    One correction to how that review framed it: a bare `model_config =
    ConfigDict()` on the subclass cannot cause the leak it describes, because
    Pydantic *merges* `model_config` along the MRO rather than replacing it —
    measured, and the mutant survives precisely because it changes nothing. What
    does reach it is an explicit `ConfigDict(extra="ignore")`, which wins over the
    parent, and that mutant this test kills. The distinction is worth keeping in
    the file: a test written against the unreachable version would look identical
    and prove less.
    """
    kit = (await client.post("/kits", json={"name": "MG Sazabi", "grade": "MG"})).json()

    message = await _tool_error("update_kit", {"kit_id": kit["id"], "changes": {"ratings": 5}})
    assert "ratings" in message

    # A near-miss on a real field, which is what an agent actually sends.
    typo = await _tool_error("update_kit", {"kit_id": kit["id"], "changes": {"build_note": "x"}})
    assert "build_note" in typo

    stored = (await client.get(f"/kits/{kit['id']}")).json()
    assert stored["rating"] is None
    assert stored["build_notes"] is None


async def test_mcp_tool_edit_refuses_to_unpair_a_filled_money_pair(client):
    """The `None` half of the §6 pair, which the neighbouring test never sends.

    That test drives a *missing* half onto an empty row and a *present* half onto
    a filled one. Neither can catch a check that skips `None`, which would leave
    `unit_cost_reference_minor` cleared and its currency behind — the unpaired
    state the CHECK constraint exists to make unrepresentable. Both directions of
    the clear are driven here, because they are different operations: one is
    illegal and one is routine. Raised by the Cursor Grok 4.6 review of #100.
    """
    tool = (
        await client.post(
            "/tools",
            json={
                "name": "Airbrush",
                "category": "spray",
                "unit_cost_reference_minor": 12000,
                "unit_cost_reference_currency": "AUD",
            },
        )
    ).json()

    for half in ("unit_cost_reference_minor", "unit_cost_reference_currency"):
        message = await _tool_error(
            "update_catalog_tool", {"tool_id": tool["id"], "changes": {half: None}}
        )
        assert "must be set together" in message

    unchanged = (await client.get("/tools")).json()[0]
    assert unchanged["unit_cost_reference_minor"] == 12000
    assert unchanged["unit_cost_reference_currency"] == "AUD"

    # Clearing the pair together is the legal way to say "no recorded cost".
    cleared = await _tool(
        client,
        "update_catalog_tool",
        {
            "tool_id": tool["id"],
            "changes": {
                "unit_cost_reference_minor": None,
                "unit_cost_reference_currency": None,
            },
        },
    )
    assert cleared["unit_cost_reference_minor"] is None
    assert cleared["unit_cost_reference_currency"] is None
