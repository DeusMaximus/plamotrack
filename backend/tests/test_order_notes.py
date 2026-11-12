"""An order's free-text note (#348), through every writer and out of every reader.

REST and MCP share `OrderCreate`/`OrderUpdate`; the importer shares neither, so it
is driven beside them rather than left to `test_portability.py`'s generic round
trip. What the three must agree on is what a note *is*: surrounding whitespace is
not part of it and a blank one is no note. A writer that stored anything else would
leave a row its own export calls an update when re-imported, which rule 10 says it
never is.

The note is the one order field that nothing reads, so its guard is the other way
round from every other order test: it must move through states where the rest of an
edit would be refused, and it must touch nothing else on the way.
"""

import pytest
from fastmcp import Client

from app.mcp import mcp
from tests.diag import row_error
from tests.test_order_invariants import archive
from tests.test_order_lifecycle import (
    consumable_line,
    kit_line,
    make_consumable,
    make_order,
)
from tests.test_portability import actions, apply, preview, read_archive

pytestmark = pytest.mark.anyio

NOTE = "Part-paid with a gift card"

#: (what a writer sends, what a note it stores says). `None` and the blanks are one
#: state, the rest are what a real note holds: a textarea's trailing newline, several
#: lines, what CSV has to quote, a spreadsheet's formula lead, more than one script.
WRITTEN = [
    pytest.param(None, None, id="null"),
    pytest.param("", None, id="empty"),
    pytest.param("  \n\t ", None, id="whitespace"),
    pytest.param(NOTE, NOTE, id="plain"),
    pytest.param(f"  {NOTE}\n", NOTE, id="surrounded"),
    pytest.param("line one\nline two", "line one\nline two", id="two lines"),
    pytest.param("line one\r\nline two", "line one\r\nline two", id="CRLF inside"),
    pytest.param('paid, "partly"\nthen refunded', 'paid, "partly"\nthen refunded', id="quoted"),
    pytest.param("=SUM(A1)", "=SUM(A1)", id="formula lead"),
    pytest.param("ギフト券で一部支払い", "ギフト券で一部支払い", id="Japanese"),
]


async def _create_rest(client, retailer, **extra) -> dict:
    return await make_order(client, retailer, [kit_line(quantity=1)], **extra)


async def _create_mcp(client, retailer, **extra) -> dict:
    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "create_order",
            {
                "order_date": "2026-10-27",
                "retailer_id": retailer["id"],
                "currency_code": "AUD",
                "items": [kit_line(quantity=1)],
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
            "update_order", {"order_id": order_id, "changes": changes}
        )
    return result.data


CREATES = [pytest.param(_create_rest, id="REST"), pytest.param(_create_mcp, id="MCP")]
UPDATES = [pytest.param(_update_rest, id="REST"), pytest.param(_update_mcp, id="MCP")]


async def _stored(client, order_id: str) -> str | None:
    """Read back, not the write's own response: what was stored is the question."""
    resp = await client.get(f"/orders/{order_id}")
    assert resp.status_code == 200
    return resp.json()["notes"]


# --- REST and MCP ----------------------------------------------------------------


@pytest.mark.parametrize("create", CREATES)
async def test_an_order_is_created_with_no_note_unless_it_states_one(client, retailer, create):
    order = await create(client, retailer)
    assert order["notes"] is None
    assert await _stored(client, order["id"]) is None


@pytest.mark.parametrize(("sent", "kept"), WRITTEN)
@pytest.mark.parametrize("create", CREATES)
async def test_a_create_stores_what_a_note_is(client, retailer, create, sent, kept):
    order = await create(client, retailer, notes=sent)
    assert order["notes"] == kept
    assert await _stored(client, order["id"]) == kept


@pytest.mark.parametrize(("sent", "kept"), WRITTEN)
@pytest.mark.parametrize("update", UPDATES)
async def test_an_update_stores_what_a_note_is(client, retailer, update, sent, kept):
    """Over a note that differs from all of them, so a write that did nothing fails."""
    order = await _create_rest(client, retailer, notes="the note before")
    updated = await update(client, order["id"], {"notes": sent})
    assert updated["notes"] == kept
    assert await _stored(client, order["id"]) == kept


@pytest.mark.parametrize("update", UPDATES)
async def test_an_update_that_omits_it_leaves_it(client, retailer, update):
    order = await _create_rest(client, retailer, notes=NOTE)
    updated = await update(client, order["id"], {"order_number": "AMZ-1"})
    assert updated["order_number"] == "AMZ-1"
    assert updated["notes"] == NOTE
    assert await _stored(client, order["id"]) == NOTE


async def test_mcp_reads_it_on_both_read_tools(client, retailer):
    order = await _create_rest(client, retailer, notes=NOTE)
    async with Client(mcp) as mcp_client:
        fetched = (await mcp_client.call_tool("get_order", {"order_id": order["id"]})).data
        listed = (await mcp_client.call_tool("list_orders", {})).structured_content["result"]
    assert fetched["notes"] == NOTE
    assert [row["notes"] for row in listed] == [NOTE]


async def test_rest_lists_it(client, retailer):
    await _create_rest(client, retailer, notes=NOTE)
    assert [row["notes"] for row in (await client.get("/orders")).json()] == [NOTE]


# --- it touches nothing, and nothing refuses it ------------------------------------


async def _pending(client, retailer) -> dict:
    return await _create_rest(client, retailer)


async def _received_with_stock(client, retailer) -> dict:
    consumable = await make_consumable(client)
    return await make_order(
        client, retailer, [kit_line(quantity=1), consumable_line(consumable["id"])], received=True
    )


async def _with_a_progressed_kit(client, retailer) -> dict:
    """The state that makes every destructive edit of this order a 409."""
    order = await _create_rest(client, retailer)
    kit_id = order["items"][0]["spawned_kit_ids"][0]
    resp = await client.patch(f"/kits/{kit_id}", json={"status": "building"})
    assert resp.status_code == 200, resp.text
    return (await client.get(f"/orders/{order['id']}")).json()


STATES = [
    pytest.param(_pending, id="pending"),
    pytest.param(_received_with_stock, id="received with stock"),
    pytest.param(_with_a_progressed_kit, id="a kit in progress"),
]


async def _collection(client) -> dict:
    return {
        "kits": (await client.get("/kits")).json(),
        "consumables": (await client.get("/consumables")).json(),
    }


@pytest.mark.parametrize("update", UPDATES)
@pytest.mark.parametrize("state", STATES)
async def test_a_note_edit_touches_nothing_else(client, retailer, state, update):
    order = await state(client, retailer)
    before = await _collection(client)
    updated = await update(client, order["id"], {"notes": NOTE})
    assert updated == {**order, "notes": NOTE}
    assert await _collection(client) == before


# --- the importer -----------------------------------------------------------------


@pytest.mark.parametrize(("sent", "kept"), WRITTEN)
async def test_an_export_of_it_re_imports_as_no_change(client, retailer, sent, kept):
    """Rule 10. The export first has to hold the note, or this passes on a column
    nothing writes."""
    await _create_rest(client, retailer, notes=sent)
    exported = await client.get("/export/archive")
    (row,) = read_archive(exported.content)["orders"]
    assert row["notes"] == (kept or "")
    plan = await preview(client, exported.content)
    assert actions(plan, "orders") == ["unchanged"]


def _order_row(order: dict, **cells) -> dict:
    return {
        "id": order["id"],
        "retailer_id": order["retailer_id"],
        "order_date": order["order_date"],
        "currency_code": order["currency_code"],
        **cells,
    }


NARROW = ["id", "retailer_id", "order_date", "currency_code", "notes"]
NO_NOTES = ["id", "retailer_id", "order_date", "currency_code"]


@pytest.mark.parametrize(
    ("cell", "kept"),
    [
        pytest.param("", None, id="blank"),
        pytest.param("  \n ", None, id="whitespace"),
        pytest.param(f"  {NOTE}\n", NOTE, id="surrounded"),
        pytest.param("line one\nline two", "line one\nline two", id="two lines"),
    ],
)
@pytest.mark.parametrize("state", STATES)
async def test_a_merge_states_it_on_an_order_in_any_state(client, retailer, state, cell, kept):
    """`invariants.py` refuses a receipt moving and a line changing. Neither is this."""
    order = await state(client, retailer)
    await _update_rest(client, order["id"], {"notes": "the note before"})
    before = await _collection(client)
    content = archive(headers={"orders": NARROW}, orders=[_order_row(order, notes=cell)])
    plan = await preview(client, content)
    (row,) = next(entry for entry in plan["tables"] if entry["table"] == "orders")["rows"]
    assert row_error(row) is None
    assert row["action"] == "update"
    assert [change["field"] for change in row["changes"]] == ["notes"]
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    assert await _stored(client, order["id"]) == kept
    assert await _collection(client) == before


async def test_a_sheet_without_the_column_leaves_it(client, retailer):
    """Every archive from before this release is one of these. Absent is not blank."""
    order = await _create_rest(client, retailer, notes=NOTE)
    content = archive(headers={"orders": NO_NOTES}, orders=[_order_row(order)])
    assert actions(await preview(client, content), "orders") == ["unchanged"]
    assert (await apply(client, content)).status_code == 200
    assert await _stored(client, order["id"]) == NOTE


async def test_add_only_does_not_write_it_over_an_existing_order(client, retailer):
    order = await _create_rest(client, retailer, notes=NOTE)
    content = archive(headers={"orders": NARROW}, orders=[_order_row(order, notes="other")])
    resp = await apply(client, content, mode="add_only")
    assert resp.status_code == 200, resp.text
    assert await _stored(client, order["id"]) == NOTE


async def test_an_order_the_sheet_creates_carries_it(client, retailer):
    """An export of the order, brought back after the order is gone, so the sheet
    states its lines as well: those are not this test's point."""
    order = await _create_rest(client, retailer, notes=NOTE)
    exported = (await client.get("/export/archive")).content
    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    plan = await preview(client, exported)
    assert "create" in actions(plan, "orders")
    assert (await apply(client, exported)).status_code == 200
    assert await _stored(client, order["id"]) == NOTE


async def test_replace_all_restores_it(client, retailer):
    order = await _create_rest(client, retailer, notes=NOTE)
    exported = (await client.get("/export/archive")).content
    await _update_rest(client, order["id"], {"notes": "changed since the backup"})
    resp = await apply(client, exported, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text
    assert await _stored(client, order["id"]) == NOTE


async def test_a_cell_a_column_cannot_hold_errors_the_row(client, retailer):
    order = await _create_rest(client, retailer, notes=NOTE)
    content = archive(headers={"orders": NARROW}, orders=[_order_row(order, notes="a\x00b")])
    plan = await preview(client, content)
    (row,) = next(entry for entry in plan["tables"] if entry["table"] == "orders")["rows"]
    assert row["action"] == "error"
    assert "notes" in row_error(row)
    assert await _stored(client, order["id"]) == NOTE
