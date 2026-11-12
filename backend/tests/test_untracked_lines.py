"""An order line the collection does not track (#349), through every writer.

`item_type: "other"` is a line with a description and a price and nothing else: a
non-model item in a mixed basket, an add-on. It exists so an order's lines add up
to its receipt. What every writer has to agree on is what it is *not*: it spawns no
kit, points at no catalog row and moves no stock, at entry, on receipt, on an edit
and on delete. And the description belongs to it alone.

REST and MCP share `OrderItemCreate`; the importer shares neither (rule 1), so it
is driven beside them here and in the shared matrix in `test_order_invariants.py`.

Most refusals below are paired with a neighbour that is *allowed*, or with the
catalog line that is refused where the `other` line is not, because a refusal on
its own proves only that something said no.
"""

import io
import json
import zipfile

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp
from tests.diag import codes
from tests.test_order_invariants import archive, sheet
from tests.test_order_lifecycle import (
    consumable_line,
    kit_line,
    make_consumable,
    make_order,
)
from tests.test_portability import actions, apply, make_csv, preview, read_archive

pytestmark = pytest.mark.anyio

BAG = "Carry bag"
CATALOG_PATHS = ("tools", "consumables", "upgrades", "display-items")


def other_line(description: str | None = BAG, quantity: int = 2, **extra) -> dict:
    line = {
        "item_type": "other",
        "quantity": quantity,
        "unit_price_minor": 350,
        "currency_code": "AUD",
        **extra,
    }
    if description is not None:
        line["description"] = description
    return line


async def _create_rest(client, retailer, items, **extra) -> dict:
    return await make_order(client, retailer, items, **extra)


async def _create_mcp(client, retailer, items, **extra) -> dict:
    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "create_order",
            {
                "order_date": "2026-08-01",
                "retailer_id": retailer["id"],
                "currency_code": "AUD",
                "items": items,
                **extra,
            },
        )
    return result.data


async def _update_rest(client, order_id: str, changes: dict) -> dict:
    resp = await client.patch(f"/orders/{order_id}", json=changes)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _update_mcp(client, order_id: str, changes: dict) -> dict:
    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "update_order",
            {"order_id": order_id, "changes": changes, "remove_missing_lines": True},
        )
    return result.data


CREATES = [pytest.param(_create_rest, id="REST"), pytest.param(_create_mcp, id="MCP")]
UPDATES = [pytest.param(_update_rest, id="REST"), pytest.param(_update_mcp, id="MCP")]


async def _stored(client, order_id: str) -> dict:
    """Read back, not the write's own response: what was stored is the question."""
    resp = await client.get(f"/orders/{order_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _line(order: dict, item_type: str) -> dict:
    [line] = [item for item in order["items"] if item["item_type"] == item_type]
    return line


async def _catalog_rows(client) -> dict[str, int]:
    return {path: len((await client.get(f"/{path}")).json()) for path in CATALOG_PATHS}


async def _stock(client, consumable_id: str) -> int:
    rows = (await client.get("/consumables")).json()
    return next(row["quantity_on_hand"] for row in rows if row["id"] == consumable_id)


async def _nothing_stored(client) -> None:
    assert (await client.get("/orders")).json() == []
    assert (await client.get("/kits")).json() == []
    assert await _catalog_rows(client) == dict.fromkeys(CATALOG_PATHS, 0)


def _restated(line: dict, **overrides) -> dict:
    """A stored line as an editor sends it back, with `overrides` changed. A kit
    line says nothing about its kits, which an id-bearing one may (#67)."""
    payload = {
        "id": line["id"],
        "item_type": line["item_type"],
        "quantity": line["quantity"],
        "unit_price_minor": line["unit_price_minor"],
        "currency_code": line["currency_code"],
    }
    if line["item_type"] == "other":
        payload["description"] = line["description"]
    elif line["item_type"] != "kit":
        payload["catalog_ref_id"] = line["catalog_ref_id"]
    payload.update(overrides)
    return payload


# --- entry: stored as its description, dispatching nothing --------------------------


@pytest.mark.parametrize("create", CREATES)
async def test_an_other_line_is_its_description_and_dispatches_nothing(client, retailer, create):
    """Beside a kit line, so "no kits" is a count of one rather than of none."""
    created = await create(client, retailer, [kit_line(quantity=1), other_line()])
    for order in (created, await _stored(client, created["id"])):
        line = _line(order, "other")
        assert line["description"] == BAG
        assert (line["quantity"], line["unit_price_minor"], line["currency_code"]) == (
            2,
            350,
            "AUD",
        )
        assert line["catalog_ref_id"] is None
        assert line["spawned_kit_ids"] == [] and line["kits"] == []
        # The neighbour's description is not borrowed, and its kit is its own.
        assert _line(order, "kit")["description"] is None
        assert len(_line(order, "kit")["kits"]) == 1
    assert len((await client.get("/kits")).json()) == 1
    assert await _catalog_rows(client) == dict.fromkeys(CATALOG_PATHS, 0)


#: (what a writer sends, what the line's description then says). The importer's
#: `parse_text` reads the same cell the same way, which `test_its_own_export_*` holds.
DESCRIBED = [
    pytest.param(BAG, BAG, id="plain"),
    pytest.param(f"  {BAG}\n", BAG, id="surrounded"),
    pytest.param('Carry bag, "large"', 'Carry bag, "large"', id="quoted"),
    pytest.param("Magazine\nMarch issue", "Magazine\nMarch issue", id="two lines"),
    pytest.param("=SUM(A1)", "=SUM(A1)", id="formula lead"),
    pytest.param("送料無料クーポン", "送料無料クーポン", id="Japanese"),
]


@pytest.mark.parametrize(("sent", "kept"), DESCRIBED)
@pytest.mark.parametrize("create", CREATES)
async def test_a_create_stores_what_a_description_is(client, retailer, create, sent, kept):
    order = await create(client, retailer, [other_line(sent)])
    assert _line(order, "other")["description"] == kept
    assert _line(await _stored(client, order["id"]), "other")["description"] == kept


async def test_an_order_of_only_other_lines_is_an_ordinary_pending_order(client, retailer):
    """No kit carries a stage signal, so it reads `ordered` like a paint-only order
    does, and moves through ship and receive with nothing to advance."""
    order = await make_order(client, retailer, [other_line()])
    assert order["stage"] == "ordered"
    assert (await client.get("/summary")).json()["orders"]["ordered"] == 1

    shipped = await client.post(f"/orders/{order['id']}/ship")
    assert shipped.status_code == 200 and shipped.json()["stage"] == "in_transit"
    received = await client.post(f"/orders/{order['id']}/receive")
    assert received.status_code == 200 and received.json()["stage"] == "received"
    assert (await client.get("/kits")).json() == []
    assert await _catalog_rows(client) == dict.fromkeys(CATALOG_PATHS, 0)


@pytest.mark.parametrize("how", ["received at entry", "received later"])
@pytest.mark.parametrize("create", CREATES)
async def test_a_receipt_applies_the_catalog_lines_stock_and_nothing_for_the_other_line(
    client, retailer, create, how
):
    """The catalog line is the control: the receipt did run, and moved exactly its
    five units. The other line's quantity is a different number on purpose."""
    paint = await make_consumable(client)
    items = [consumable_line(paint["id"], quantity=5), other_line(quantity=7)]
    if how == "received at entry":
        order = await create(client, retailer, items, received=True)
    else:
        order = await create(client, retailer, items)
        assert await _stock(client, paint["id"]) == 0
        resp = await client.post(f"/orders/{order['id']}/receive")
        assert resp.status_code == 200, resp.text
        order = resp.json()
    assert order["received_at"] is not None
    assert await _stock(client, paint["id"]) == 5
    assert await _catalog_rows(client) == dict.fromkeys(CATALOG_PATHS, 0) | {"consumables": 1}


# --- entry: what the type takes and refuses -----------------------------------------

#: (line, the fragment of the finding that names the rule). Each is one field away
#: from a line that is accepted, so the refusal is that field's.
MISSHAPEN = [
    pytest.param(other_line(None), "other lines require a 'description'", id="no description"),
    pytest.param(other_line(""), "other lines require a 'description'", id="empty description"),
    pytest.param(
        other_line("  \n\t "), "other lines require a 'description'", id="blank description"
    ),
    pytest.param(
        other_line(kit={"name": "Zaku II", "grade": "HG"}),
        "other lines are not tracked",
        id="with kit details",
    ),
    pytest.param(
        other_line(catalog_ref_id="11111111-1111-4111-8111-111111111111"),
        "other lines are not tracked",
        id="with a catalog reference",
    ),
    pytest.param(
        other_line(new_item={"name": "Panel liner", "category": "paint"}),
        "other lines are not tracked",
        id="with a new catalog item",
    ),
    pytest.param(
        kit_line(quantity=1) | {"description": BAG},
        "kit lines must not set 'description'",
        id="a kit line with a description",
    ),
    pytest.param(
        {
            "item_type": "consumable",
            "quantity": 1,
            "unit_price_minor": 650,
            "currency_code": "AUD",
            "new_item": {"name": "Panel liner", "category": "paint"},
            "description": BAG,
        },
        "consumable lines must not set 'description'",
        id="a catalog line with a description",
    ),
]


@pytest.mark.parametrize(("line", "rule"), MISSHAPEN)
async def test_rest_refuses_a_line_its_type_does_not_take(http_client, retailer, line, rule):
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [line],
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "request.validation"
    [finding] = body["detail"]
    assert rule in finding["msg"], finding
    assert finding["loc"][:3] == ["body", "items", 0]
    await _nothing_stored(http_client)


@pytest.mark.parametrize(("line", "rule"), MISSHAPEN)
async def test_mcp_refuses_the_same_lines(client, retailer, line, rule):
    """By the same rule, named: a ToolError alone would also be what an unknown
    `item_type` earns, which is how every one of these read before the type existed."""
    with pytest.raises(ToolError) as refusal:
        await _create_mcp(client, retailer, [line])
    assert rule in str(refusal.value)
    await _nothing_stored(client)


async def test_a_blank_description_on_another_line_is_no_description(client, retailer):
    """Blank is null on the way in, as it is for every stripped text field, so a
    form that sends an empty box beside a kit line is not refused for it."""
    order = await make_order(client, retailer, [kit_line(quantity=1) | {"description": "  "}])
    assert _line(order, "kit")["description"] is None


# --- edits ----------------------------------------------------------------------------


@pytest.mark.parametrize("update", UPDATES)
async def test_an_edit_restates_an_other_line_and_dispatches_nothing(client, retailer, update):
    order = await make_order(client, retailer, [kit_line(quantity=1), other_line()])
    kit, bag = _line(order, "kit"), _line(order, "other")
    changed = _restated(bag, description="Tote bag", quantity=3, unit_price_minor=400)
    updated = await update(client, order["id"], {"items": [_restated(kit), changed]})
    for read in (updated, await _stored(client, order["id"])):
        line = _line(read, "other")
        assert line["id"] == bag["id"]
        assert (line["description"], line["quantity"], line["unit_price_minor"]) == (
            "Tote bag",
            3,
            400,
        )
        assert line["catalog_ref_id"] is None and line["kits"] == []
    assert len((await client.get("/kits")).json()) == 1
    assert await _catalog_rows(client) == dict.fromkeys(CATALOG_PATHS, 0)


async def test_an_edit_that_omits_the_description_is_refused(http_client, retailer):
    """A supplied line replaces the stored one field for field, so a restated
    `other` line with no description would be one with none. The control is the
    same payload with it, which is accepted."""
    order = await make_order(http_client, retailer, [other_line()])
    bag = _line(order, "other")
    without = {key: value for key, value in _restated(bag).items() if key != "description"}

    resp = await http_client.patch(f"/orders/{order['id']}", json={"items": [without]})
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "request.validation"
    assert "other lines require a 'description'" in resp.json()["detail"][0]["msg"]
    assert _line(await _stored(http_client, order["id"]), "other")["description"] == BAG

    resp = await http_client.patch(f"/orders/{order['id']}", json={"items": [_restated(bag)]})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    ("stored", "as_type"),
    [
        pytest.param("other", "kit", id="an other line cannot become a kit line"),
        pytest.param("kit", "other", id="a kit line cannot become an other line"),
    ],
)
async def test_a_lines_type_cannot_change_into_or_out_of_other(
    http_client, retailer, stored, as_type
):
    """No conversion (owner's call, #349): what was bought untracked stays that way,
    and tracking it later is removing the line and adding a tracked one."""
    order = await make_order(http_client, retailer, [kit_line(quantity=1), other_line()])
    kit, bag = _line(order, "kit"), _line(order, "other")
    if as_type == "kit":
        flipped = {
            "id": bag["id"],
            "item_type": "kit",
            "quantity": bag["quantity"],
            "unit_price_minor": bag["unit_price_minor"],
            "currency_code": "AUD",
            "kit": {"name": "Zaku II", "grade": "HG"},
        }
        lines = [_restated(kit), flipped]
    else:
        flipped = {
            "id": kit["id"],
            "item_type": "other",
            "quantity": kit["quantity"],
            "unit_price_minor": kit["unit_price_minor"],
            "currency_code": "AUD",
            "description": "Zaku II",
        }
        lines = [flipped, _restated(bag)]

    resp = await http_client.patch(f"/orders/{order['id']}", json={"items": lines})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "order_line.item_type_immutable"
    assert body["params"] == {"before": stored, "after": as_type}
    after = await _stored(http_client, order["id"])
    assert [(item["id"], item["item_type"]) for item in after["items"]] == [
        (item["id"], item["item_type"]) for item in order["items"]
    ]
    assert len((await http_client.get("/kits")).json()) == 1


@pytest.mark.parametrize(
    "edit",
    ["more of it", "fewer of it", "removed", "added"],
)
@pytest.mark.parametrize("update", UPDATES)
async def test_an_other_line_on_a_received_order_never_moves_stock(client, retailer, update, edit):
    """A received order is where a catalog line's edit moves stock (rule 2). The
    catalog line beside it holds five units throughout, so any stock an `other`
    line's edit moved would show as a number other than five."""
    paint = await make_consumable(client)
    items = [consumable_line(paint["id"], quantity=5)]
    if edit != "added":
        items.append(other_line(quantity=4))
    order = await make_order(client, retailer, items, received=True)
    assert await _stock(client, paint["id"]) == 5
    kept = _restated(_line(order, "consumable"))

    if edit == "added":
        lines = [kept, other_line(quantity=4)]
        expected = 4
    elif edit == "removed":
        lines = [kept]
        expected = None
    else:
        expected = 9 if edit == "more of it" else 1
        lines = [kept, _restated(_line(order, "other"), quantity=expected)]
    updated = await update(client, order["id"], {"items": lines})

    others = [item["quantity"] for item in updated["items"] if item["item_type"] == "other"]
    assert others == ([] if expected is None else [expected])
    assert await _stock(client, paint["id"]) == 5
    assert await _catalog_rows(client) == dict.fromkeys(CATALOG_PATHS, 0) | {"consumables": 1}


async def test_deleting_a_received_order_reverses_the_catalog_line_alone(client, retailer):
    paint = await make_consumable(client, quantity=2)
    order = await make_order(
        client,
        retailer,
        [consumable_line(paint["id"], quantity=5), other_line(quantity=7)],
        received=True,
    )
    assert await _stock(client, paint["id"]) == 7
    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    assert await _stock(client, paint["id"]) == 2
    assert (await client.get("/orders")).json() == []


# --- MCP reads, and the catalog tools' vocabulary --------------------------------------


async def test_mcp_reads_the_description_on_both_read_tools(client, retailer):
    order = await make_order(client, retailer, [other_line()])
    async with Client(mcp) as mcp_client:
        fetched = (await mcp_client.call_tool("get_order", {"order_id": order["id"]})).data
        listed = (await mcp_client.call_tool("list_orders", {})).structured_content["result"]
    assert [item["description"] for item in fetched["items"]] == [BAG]
    assert [item["description"] for row in listed for item in row["items"]] == [BAG]


@pytest.mark.parametrize("tool", ["list_catalog_items", "list_catalog_categories"])
@pytest.mark.parametrize("spelling", ["other", "Others", " OTHER "])
async def test_other_names_no_catalog_table(client, tool, spelling):
    """`other` is an order line's type and no table: the catalog tools refuse it by
    naming the tables there are, as they do any unknown word, where a lookup by
    it would have been a KeyError."""
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as refusal:
            await mcp_client.call_tool(tool, {"item_type": spelling})
        assert "valid types: tool, consumable, upgrade, display" in str(refusal.value)
        # The control: the same call with a table's name answers.
        assert (await mcp_client.call_tool(tool, {"item_type": "tool"})).data == []


# --- the archive -----------------------------------------------------------------------


async def _seed_for_export(client, retailer) -> dict:
    paint = await make_consumable(client)
    return await make_order(
        client,
        retailer,
        [
            kit_line(quantity=1),
            consumable_line(paint["id"], quantity=5),
            other_line('Carry bag, "large"'),
        ],
        received=True,
        order_number="AMZ-1",
    )


async def test_its_own_export_states_the_line_and_re_imports_as_no_change(client, retailer):
    order = await _seed_for_export(client, retailer)
    content = (await client.get("/export/archive")).content
    [row] = [r for r in read_archive(content)["order_items"] if r["item_type"] == "other"]
    assert row["description"] == 'Carry bag, "large"'
    assert (row["catalog_ref_id"], row["catalog_name"], row["kit_name"]) == ("", "", "")
    assert (row["quantity"], row["unit_price_minor"], row["unit_price"]) == ("2", "350", "3.50")
    # No other line borrows the column.
    assert [
        r["description"] for r in read_archive(content)["order_items"] if r["item_type"] != "other"
    ] == ["", ""]

    plan = await preview(client, content)
    assert plan["blocking_errors"] == []
    assert set(actions(plan, "order_items")) == {"unchanged"}
    assert (await apply(client, content)).status_code == 200
    assert await _stored(client, order["id"]) == order


@pytest.mark.parametrize("mode", ["replace_all", "merge"])
async def test_an_archive_restores_the_line_into_an_instance_without_it(client, retailer, mode):
    order = await _seed_for_export(client, retailer)
    content = (await client.get("/export/archive")).content
    if mode == "merge":
        # Gone from the instance, so the merge has to create it from the sheet.
        resp = await client.delete(f"/orders/{order['id']}")
        assert resp.status_code == 204, resp.text
        assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 0

    extra = {"confirm": "REPLACE"} if mode == "replace_all" else {}
    resp = await apply(client, content, mode=mode, **extra)
    assert resp.status_code == 200, resp.text
    restored = await _stored(client, order["id"])
    line = _line(restored, "other")
    assert line == _line(order, "other")
    # Rule 10: the restore states stock, it never derives it.
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 5


def _line_row(order: dict, **cells) -> dict:
    return {
        "order_id": order["id"],
        "item_type": "other",
        "quantity": "2",
        "unit_price_minor": "350",
        "currency_code": "AUD",
        **cells,
    }


LINE_HEADER = ["id", "order_id", "item_type", "quantity", "unit_price_minor", "currency_code"]


async def test_a_hand_written_row_adds_an_other_line(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    content = sheet(
        "order_items", [*LINE_HEADER, "description"], [_line_row(order, description=f" {BAG} ")]
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["create"], plan["tables"]
    assert (await apply(client, content, filename="order_items.csv")).status_code == 200

    line = _line(await _stored(client, order["id"]), "other")
    assert (line["description"], line["quantity"], line["unit_price_minor"]) == (BAG, 2, 350)
    assert line["catalog_ref_id"] is None
    assert len((await client.get("/kits")).json()) == 1
    assert await _catalog_rows(client) == dict.fromkeys(CATALOG_PATHS, 0)

    # And the same sheet again is that line, not a second one.
    again = await preview(client, content, filename="order_items.csv")
    assert actions(again, "order_items") == ["unchanged"], again["tables"]


def _row_errors(plan: dict, table: str = "order_items") -> list[list[dict]]:
    [entry] = [e for e in plan["tables"] if e["table"] == table]
    return [row["errors"] for row in entry["rows"]]


def _row_messages(plan: dict, table: str = "order_items") -> list[list[dict]]:
    [entry] = [e for e in plan["tables"] if e["table"] == table]
    return [row["messages"] for row in entry["rows"]]


@pytest.mark.parametrize(
    "header",
    [
        pytest.param(LINE_HEADER, id="no description column"),
        pytest.param([*LINE_HEADER, "description"], id="a blank cell"),
    ],
)
async def test_a_new_other_line_without_a_description_is_a_row_error(client, retailer, header):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    content = sheet("order_items", header, [_line_row(order, description="   ")])
    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    [[error]] = _row_errors(plan)
    assert error["code"] == "import.line_description_required"
    assert error["params"] == {}
    assert (await apply(client, content, filename="order_items.csv")).status_code == 409
    assert [i["item_type"] for i in (await _stored(client, order["id"]))["items"]] == ["kit"]


@pytest.mark.parametrize(
    ("header", "cells", "verdict"),
    [
        pytest.param(
            [*LINE_HEADER, "description"],
            {"description": ""},
            "refused",
            id="a blank cell empties it",
        ),
        pytest.param(LINE_HEADER, {}, "kept", id="a sheet without the column leaves it"),
        pytest.param(
            [*LINE_HEADER, "description"],
            {"description": "Tote bag"},
            "replaced",
            id="a stated one replaces it",
        ),
    ],
)
async def test_an_update_to_a_stored_other_line_lands_with_a_description_or_not_at_all(
    client, retailer, header, cells, verdict
):
    """Judged on what lands. The price changes in every case, so the row is an
    update whatever the description cell says, and "kept" is not merely unchanged."""
    order = await make_order(client, retailer, [other_line()])
    bag = _line(order, "other")
    content = sheet(
        "order_items", header, [_line_row(order, id=bag["id"], unit_price_minor="400", **cells)]
    )
    plan = await preview(client, content, filename="order_items.csv")
    resp = await apply(client, content, filename="order_items.csv")
    line = _line(await _stored(client, order["id"]), "other")

    if verdict == "refused":
        assert actions(plan, "order_items") == ["error"], plan["tables"]
        assert codes(_row_errors(plan)[0]) == ["import.line_description_required"]
        assert resp.status_code == 409
        assert (line["description"], line["unit_price_minor"]) == (BAG, 350)
    else:
        assert actions(plan, "order_items") == ["update"], plan["tables"]
        assert resp.status_code == 200, resp.text
        assert line["unit_price_minor"] == 400
        assert line["description"] == (BAG if verdict == "kept" else "Tote bag")


@pytest.mark.parametrize("line_type", ["kit", "consumable"])
@pytest.mark.parametrize("row", ["a stored line", "a new line"])
async def test_a_description_on_any_other_type_of_line_is_a_row_error(
    client, retailer, line_type, row
):
    """Both row actions, because a create has no stored line to read the type from
    and an update that omits `item_type` has only that."""
    paint = await make_consumable(client)
    stored_line = (
        kit_line(quantity=1) if line_type == "kit" else consumable_line(paint["id"], quantity=1)
    )
    order = await make_order(client, retailer, [stored_line])
    stored = order["items"][0]
    if row == "a stored line":
        header = ["id", "order_id", "quantity", "description"]
        cells = {"id": stored["id"], "order_id": order["id"], "quantity": "1", "description": BAG}
    else:
        header = [*LINE_HEADER, "catalog_ref_id", "kit_name", "kit_grade", "description"]
        cells = _line_row(
            order,
            item_type=line_type,
            description=BAG,
            catalog_ref_id=paint["id"] if line_type == "consumable" else "",
            kit_name="Gouf" if line_type == "kit" else "",
            kit_grade="HG" if line_type == "kit" else "",
        )
    content = sheet("order_items", header, [cells])

    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    [[error]] = _row_errors(plan)
    assert error["code"] == "import.line_description_misplaced"
    assert error["params"] == {"item_type": line_type}
    assert (await apply(client, content, filename="order_items.csv")).status_code == 409
    after = await _stored(client, order["id"])
    assert [(i["id"], i["description"]) for i in after["items"]] == [(stored["id"], None)]
    assert len((await client.get("/kits")).json()) == (1 if line_type == "kit" else 0)


@pytest.mark.parametrize(
    ("cells", "fields"),
    [
        pytest.param({"catalog_name": "Panel liner"}, ["catalog_name"], id="a name"),
        pytest.param(
            {"catalog_ref_id": "11111111-1111-4111-8111-111111111111"},
            ["catalog_ref_id"],
            id="an id nothing has",
        ),
        pytest.param({"catalog_ref_id": "@paint"}, ["catalog_ref_id"], id="an id a row has"),
        pytest.param(
            {"catalog_ref_id": "@paint", "catalog_name": "Panel liner"},
            ["catalog_ref_id", "catalog_name"],
            id="both",
        ),
    ],
)
async def test_a_catalog_reference_on_an_other_line_is_ignored_and_said_so(
    client, retailer, cells, fields
):
    """Ignored, not resolved: a name on a catalog line creates the item it names
    (§3.9 select-or-create), and here that would mint a catalog row for something
    the line exists to say is not tracked. So the counts are the assertion."""
    paint = await make_consumable(client)
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    cells = {k: (paint["id"] if v == "@paint" else v) for k, v in cells.items()}
    content = sheet(
        "order_items",
        [*LINE_HEADER, "catalog_ref_id", "catalog_name", "description"],
        [_line_row(order, description=BAG, **cells)],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["create"], plan["tables"]
    [messages] = _row_messages(plan)
    ignored = [m for m in messages if m["code"] == "import.ref_ignored_other_line"]
    assert [m["params"] for m in ignored] == [{"field": field} for field in fields]
    assert plan["blocking_errors"] == []
    # No stub was planned for the name.
    assert [e["table"] for e in plan["tables"] if e["rows"]] == ["order_items"]

    assert (await apply(client, content, filename="order_items.csv")).status_code == 200
    line = _line(await _stored(client, order["id"]), "other")
    assert line["catalog_ref_id"] is None
    assert await _catalog_rows(client) == dict.fromkeys(CATALOG_PATHS, 0) | {"consumables": 1}
    assert await _stock(client, paint["id"]) == 0


@pytest.mark.parametrize(
    "placement",
    ["already on the order", "arriving in the same upload"],
)
@pytest.mark.parametrize(
    ("beside", "verdict"),
    [
        pytest.param("other", "allowed", id="an other line carries no stock"),
        pytest.param("consumable", "refused", id="the control: a catalog line does"),
    ],
)
async def test_an_import_may_receive_an_order_whose_only_lines_beside_kits_are_other_ones(
    client, retailer, beside, verdict, placement
):
    """Rule 2.1 refuses a receipt arriving by import where a line would have moved
    stock. An `other` line moves none, so the order is as free to be received by a
    sheet as a kit-only one; the catalog line in the same place is not.

    Both places the rule reads the order's lines from: the stored order, and the
    upload that flips the receipt. A line the same upload adds is stock left just
    as unaccounted as one already there."""
    paint = await make_consumable(client)
    stored_lines = [kit_line(quantity=1)]
    if placement == "already on the order":
        stored_lines.append(
            other_line() if beside == "other" else consumable_line(paint["id"], quantity=3)
        )
    order = await make_order(client, retailer, stored_lines, order_number="A-1")
    tables = {
        "orders": [
            {
                "id": order["id"],
                "retailer_id": retailer["id"],
                "order_date": order["order_date"],
                "order_number": "A-1",
                "currency_code": "AUD",
                "received_at": "2026-08-05T00:00:00Z",
            }
        ]
    }
    if placement == "arriving in the same upload":
        cells = (
            {"description": BAG}
            if beside == "other"
            else {"item_type": "consumable", "catalog_ref_id": paint["id"]}
        )
        tables["order_items"] = [_line_row(order, **cells)]
    content = archive(**tables)

    plan = await preview(client, content)
    resp = await apply(client, content)
    stored = await _stored(client, order["id"])
    if verdict == "allowed":
        assert actions(plan, "orders") == ["update"], plan["tables"]
        assert plan["blocking_errors"] == []
        assert resp.status_code == 200, resp.text
        assert stored["received_at"] is not None
        assert sorted(item["item_type"] for item in stored["items"]) == ["kit", "other"]
        assert [k["status"] for k in (await client.get("/kits")).json()] == ["backlog"]
    else:
        assert actions(plan, "orders") == ["error"], plan["tables"]
        assert codes(_row_errors(plan, "orders")[0]) == ["import.receipt_unaccounted"]
        assert resp.status_code == 409
        assert stored["received_at"] is None
    assert await _stock(client, paint["id"]) == 0


@pytest.mark.parametrize(
    ("joining", "verdict"),
    [
        pytest.param("other", "allowed", id="an other line joins"),
        pytest.param("consumable", "refused", id="the control: a catalog line may not"),
    ],
)
async def test_a_new_line_joining_a_received_order(client, retailer, joining, verdict):
    paint = await make_consumable(client)
    order = await make_order(client, retailer, [kit_line(quantity=1)], received=True)
    cells = (
        {"description": BAG}
        if joining == "other"
        else {"item_type": "consumable", "catalog_ref_id": paint["id"]}
    )
    content = sheet(
        "order_items",
        [*LINE_HEADER, "catalog_ref_id", "description"],
        [_line_row(order, **cells)],
    )
    plan = await preview(client, content, filename="order_items.csv")
    resp = await apply(client, content, filename="order_items.csv")
    types = sorted(i["item_type"] for i in (await _stored(client, order["id"]))["items"])
    if verdict == "allowed":
        assert actions(plan, "order_items") == ["create"], plan["tables"]
        assert resp.status_code == 200, resp.text
        assert types == ["kit", "other"]
    else:
        assert codes(_row_errors(plan)[0]) == ["import.line_joins_received"]
        assert resp.status_code == 409
        assert types == ["kit"]
    assert await _stock(client, paint["id"]) == 0


@pytest.mark.parametrize(
    ("described", "matched"),
    [
        pytest.param(BAG, True, id="the same description is the same line"),
        pytest.param("carry BAG ", True, id="case and spacing aside"),
        pytest.param("Tote bag", False, id="another description is another purchase"),
    ],
)
async def test_an_order_with_no_number_is_matched_by_its_lines_descriptions(
    client, retailer, described, matched
):
    """A numberless order from an instance that never knew our ids is found by its
    date and lines. An `other` line has no kit and no catalog item to be named by
    there, so its description is its name in that fingerprint."""
    existing = await make_order(client, retailer, [other_line()])
    foreign = "33333333-3333-4333-8333-333333333333"
    content = archive(
        orders=[
            {
                "id": foreign,
                "retailer_name": retailer["name"],
                "order_date": existing["order_date"],
                "currency_code": "AUD",
            }
        ],
        order_items=[
            _line_row({"id": foreign}, id="44444444-4444-4444-8444-444444444444")
            | {"description": described}
        ],
    )
    plan = await preview(client, content)
    [order_row] = next(e for e in plan["tables"] if e["table"] == "orders")["rows"]
    if matched:
        assert order_row["matched_by"] == "retailer_date_lines"
        assert order_row["matched_id"] == existing["id"]
    else:
        assert order_row["action"] == "create"
    assert (await apply(client, content)).status_code == 200
    assert len((await client.get("/orders")).json()) == (1 if matched else 2)


async def test_a_kit_cannot_take_its_provenance_from_an_other_line(client, retailer):
    """`kits.order_item_id` says which line bought the kit, and an `other` line
    buys nothing the collection tracks. The kit line beside it is the control."""
    order = await make_order(client, retailer, [kit_line(quantity=1), other_line()])
    loose = (
        await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
    ).json()
    content = sheet(
        "kits",
        ["id", "name", "grade", "order_item_id"],
        [
            {
                "id": loose["id"],
                "name": "Gouf",
                "grade": "HG",
                "order_item_id": _line(order, "other")["id"],
            }
        ],
    )
    plan = await preview(client, content, filename="kits.csv")
    assert actions(plan, "kits") == ["error"], plan["tables"]
    [[error]] = _row_errors(plan, "kits")
    assert error["code"] == "import.kit_move_to_catalog_line"
    assert error["params"]["item_type"] == "other"
    assert "only a kit line buys kits" in error["detail"]
    assert (await apply(client, content, filename="kits.csv")).status_code == 409
    assert (await client.get(f"/kits/{loose['id']}")).json()["order_item_id"] is None


def _version_one_archive(order: dict, retailer: dict) -> bytes:
    """An archive as export format 1 wrote one: no `description` column, and a
    manifest that says 1."""
    line = order["items"][0]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "manifest.json", json.dumps({"format": "plamotrack-archive", "export_version": 1})
        )
        zf.writestr(
            "order_items.csv",
            make_csv(
                [*LINE_HEADER, "kit_name", "kit_grade"],
                [
                    {
                        "id": line["id"],
                        "order_id": order["id"],
                        "item_type": "kit",
                        "quantity": "1",
                        "unit_price_minor": "5200",
                        "currency_code": "AUD",
                        "kit_name": "RX-79[G] Gundam Ground Type",
                        "kit_grade": "HG",
                    }
                ],
            ),
        )
    return buffer.getvalue()


async def test_an_archive_from_export_format_one_still_imports(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    content = _version_one_archive(order, retailer)
    plan = await preview(client, content)
    assert plan["blocking_errors"] == []
    assert actions(plan, "order_items") == ["update"], plan["tables"]
    assert (await apply(client, content)).status_code == 200
    line = (await _stored(client, order["id"]))["items"][0]
    assert (line["unit_price_minor"], line["description"]) == (5200, None)
