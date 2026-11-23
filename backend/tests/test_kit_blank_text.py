"""A kit's `name` or `grade` that is only whitespace is refused by every writer (#380).

Rule 10: re-importing the instance's own export is a no-op. The importer reads every
`kits.csv` cell through `spec.parse_text`, which strips and reads a blank as no value,
and both columns are required, so a kit stored as `"   "` stopped the import of its own
export at `import.cell_required` → `import.rows_unreadable`. The request schemas say
`min_length=1`, which a space satisfies, so `POST /kits` answered 201.

The refusal is `field.blank` naming the field, from the service layer (rule 1, rule 6),
on every writer of the two columns: `POST /kits` and `PATCH /kits/{id}`, MCP
`create_kit` and `update_kit`, and an order's kit line (`OrderKitDetails`) on create and
on edit, through REST and MCP. The importer is the third writer and already refused;
a test here says so.

Value axis: blanks of several kinds (`str.strip`'s set, not ASCII alone), the empty
string (the schema's own `min_length` refusal, a different layer and code), and the
controls a fix must not refuse — a padded real value, stored as sent, and a real one.
State axis, for an order's kit line: a new line at entry, a stored line restated with
its quantity unchanged (the restatement writes onto spawned kits without passing
`spawn_kits`), the same line grown (which spawns), and a new line added on an edit.

Asserted at the layer that speaks: REST through `http_client`, the status *and* the
envelope's `code` and `params`; MCP carries no code to its client (`_tool_session`
renders `str(exc)`), so the message is compared whole, which the schema's own refusal
does not produce; and the store is read back unchanged after every refusal.
"""

import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import select

from app import error_codes
from app.db import get_sessionmaker
from app.exceptions import InvalidInputError
from app.mcp import mcp
from app.models import Kit, OrderItem
from tests.diag import codes
from tests.test_order_lifecycle import kit_line, make_order
from tests.test_portability import actions, apply, make_archive, preview, read_archive

pytestmark = pytest.mark.anyio

FIELDS = ["name", "grade"]

#: Whitespace only, in the kinds `str.strip` removes and a naïve `== " "` misses.
BLANKS = [
    pytest.param(" ", id="space"),
    pytest.param("   ", id="spaces"),
    pytest.param("\t", id="tab"),
    pytest.param("\n", id="newline"),
    pytest.param(" ", id="nbsp"),
    pytest.param("　", id="ideographic"),
]

KIT = {"name": "RX-78-2 Gundam", "grade": "HG"}


# --- the store, read back ----------------------------------------------------------


async def _kits() -> list[tuple]:
    """Every kit as stored, ordered by id: what a refused write must leave alone."""
    async with get_sessionmaker()() as session:
        rows = (await session.scalars(select(Kit).order_by(Kit.id))).all()
        return [
            (str(k.id), k.name, k.grade, k.scale, k.kit_number, k.status, k.order_item_id)
            for k in rows
        ]


async def _line_count() -> int:
    async with get_sessionmaker()() as session:
        return len((await session.scalars(select(OrderItem))).all())


def _assert_field_blank(resp, field: str) -> None:
    """The service's refusal, not the schema's: `field.blank` naming `field`."""
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == error_codes.FIELD_BLANK, body
    assert body["params"] == {"field": field}, body
    assert body["detail"] == f"{field} cannot be blank", body


async def _tool_error(name: str, args: dict) -> str:
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as raised:
            await mcp_client.call_tool(name, args)
    return str(raised.value)


async def _tool(name: str, args: dict):
    async with Client(mcp) as mcp_client:
        return (await mcp_client.call_tool(name, args)).data


# --- the predicate -------------------------------------------------------------------


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", BLANKS)
def test_the_predicate_names_the_field(field, blank):
    # Imported here, not at the top, so the file still imports on a tree without the
    # predicate and every other test in it can be run there as a negative control.
    from app.services.kits import refuse_blank_kit_text

    with pytest.raises(InvalidInputError) as raised:
        refuse_blank_kit_text(**{**KIT, field: blank})
    assert raised.value.code == error_codes.FIELD_BLANK
    assert raised.value.params == {"field": field}


def test_the_predicate_passes_a_field_not_sent_and_a_real_value():
    from app.services.kits import refuse_blank_kit_text

    refuse_blank_kit_text(None, None)
    refuse_blank_kit_text("  RX-78-2 Gundam ", "HG\n")


# --- REST: /kits ---------------------------------------------------------------------


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", BLANKS)
async def test_rest_create_kit_refuses_a_blank(http_client, field, blank):
    resp = await http_client.post("/kits", json={**KIT, field: blank})
    _assert_field_blank(resp, field)
    assert await _kits() == []


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", BLANKS)
async def test_rest_update_kit_refuses_a_blank(http_client, field, blank):
    created = await http_client.post("/kits", json=KIT)
    assert created.status_code == 201, created.text
    before = await _kits()

    resp = await http_client.patch(f"/kits/{created.json()['id']}", json={field: blank})
    _assert_field_blank(resp, field)
    assert await _kits() == before


@pytest.mark.parametrize("field", FIELDS)
async def test_rest_update_kit_refuses_a_blank_beside_a_good_change(http_client, field):
    """One bad field refuses the whole PATCH: the rating beside it is not stored."""
    created = (await http_client.post("/kits", json=KIT)).json()
    before = await _kits()
    resp = await http_client.patch(f"/kits/{created['id']}", json={field: "  ", "rating": 4})
    _assert_field_blank(resp, field)
    assert await _kits() == before
    assert (await http_client.get(f"/kits/{created['id']}")).json()["rating"] is None


@pytest.mark.parametrize("field", FIELDS)
async def test_an_empty_string_is_still_the_schemas_refusal(http_client, field):
    """`""` never reaches the service: `min_length=1` refuses it as a request error.
    Pinned so the two layers are told apart, and so a schema change is noticed."""
    resp = await http_client.post("/kits", json={**KIT, field: ""})
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] != error_codes.FIELD_BLANK
    assert await _kits() == []


async def test_a_padded_value_is_stored_as_sent(http_client):
    """The control: surrounding whitespace on a real value is neither refused nor
    trimmed (the merge import compares it as `parse_text` reads it, #356; normalising
    on write is #381's). A real rename goes through."""
    resp = await http_client.post("/kits", json={"name": " Zaku II ", "grade": "HG\n"})
    assert resp.status_code == 201, resp.text
    assert (resp.json()["name"], resp.json()["grade"]) == (" Zaku II ", "HG\n")

    renamed = await http_client.patch(f"/kits/{resp.json()['id']}", json={"name": "Zaku II"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Zaku II"
    assert renamed.json()["grade"] == "HG\n"


# --- MCP: create_kit, update_kit -----------------------------------------------------


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", BLANKS)
async def test_mcp_create_kit_refuses_a_blank(client, field, blank):
    message = await _tool_error("create_kit", {"kit": {**KIT, field: blank}})
    assert message == f"{field} cannot be blank"
    assert await _kits() == []


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", BLANKS)
async def test_mcp_update_kit_refuses_a_blank(client, field, blank):
    created = await _tool("create_kit", {"kit": KIT})
    before = await _kits()

    message = await _tool_error("update_kit", {"kit_id": created["id"], "changes": {field: blank}})
    assert message == f"{field} cannot be blank"
    assert await _kits() == before


async def test_mcp_kit_tools_take_a_real_value(client):
    created = await _tool("create_kit", {"kit": KIT})
    renamed = await _tool("update_kit", {"kit_id": created["id"], "changes": {"grade": "RG"}})
    assert renamed["grade"] == "RG"


# --- an order's kit line: entry ------------------------------------------------------


def _blank_kit_line(field: str, blank: str, quantity: int = 2) -> dict:
    line = kit_line(quantity=quantity)
    line["kit"] = {**line["kit"], field: blank}
    return line


def _order_body(retailer: dict, items: list[dict]) -> dict:
    return {
        "retailer_id": retailer["id"],
        "order_date": "2026-08-01",
        "currency_code": "AUD",
        "items": items,
    }


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", BLANKS)
async def test_rest_create_order_refuses_a_blank_kit_line(http_client, retailer, field, blank):
    resp = await http_client.post(
        "/orders", json=_order_body(retailer, [_blank_kit_line(field, blank)])
    )
    _assert_field_blank(resp, field)
    assert await _kits() == []
    assert (await http_client.get("/orders")).json() == []


@pytest.mark.parametrize("field", FIELDS)
async def test_rest_create_order_rolls_back_the_good_line_beside_it(http_client, retailer, field):
    """Rule 2: one bad line rolls back the order, the good kit line's kits included."""
    resp = await http_client.post(
        "/orders", json=_order_body(retailer, [kit_line(), _blank_kit_line(field, " ")])
    )
    _assert_field_blank(resp, field)
    assert await _kits() == []
    assert await _line_count() == 0


@pytest.mark.parametrize("field", FIELDS)
async def test_mcp_create_order_refuses_a_blank_kit_line(client, retailer, field):
    message = await _tool_error(
        "create_order",
        {
            "order_date": "2026-08-01",
            "retailer_id": retailer["id"],
            "currency_code": "AUD",
            "items": [_blank_kit_line(field, "　")],
        },
    )
    assert message == f"{field} cannot be blank"
    assert await _kits() == []
    assert await _line_count() == 0


# --- an order's kit line: edit -------------------------------------------------------


def _restated(item: dict, **kit) -> dict:
    """A stored kit line echoed back with its id, its kit details overridden."""
    first = item["kits"][0]
    return {
        "id": item["id"],
        "item_type": "kit",
        "quantity": item["quantity"],
        "unit_price_minor": item["unit_price_minor"],
        "currency_code": item["currency_code"],
        "kit": {"name": first["name"], "grade": first["grade"], **kit},
    }


#: How the edit reaches the kits: a stored line restated at its quantity (the
#: restatement writes onto spawned kits and never passes `spawn_kits`), the same line
#: grown (which spawns), and a new line beside it (spawned at entry to the edit).
EDITS = [
    pytest.param(lambda item, field, blank: [_restated(item, **{field: blank})], id="restated"),
    pytest.param(
        lambda item, field, blank: [{**_restated(item, **{field: blank}), "quantity": 3}],
        id="grown",
    ),
    pytest.param(
        lambda item, field, blank: [_restated(item), _blank_kit_line(field, blank, quantity=1)],
        id="added",
    ),
]


async def _order_with_a_kit_line(client, retailer) -> tuple[dict, dict]:
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    item = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert len(item["kits"]) == 2
    return order, item


@pytest.mark.parametrize("edit", EDITS)
@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("blank", [" ", " "], ids=["space", "nbsp"])
async def test_rest_update_order_refuses_a_blank_kit_line(
    http_client, retailer, edit, field, blank
):
    order, item = await _order_with_a_kit_line(http_client, retailer)
    before, lines = await _kits(), await _line_count()

    resp = await http_client.patch(
        f"/orders/{order['id']}", json={"items": edit(item, field, blank)}
    )
    _assert_field_blank(resp, field)
    assert await _kits() == before
    assert await _line_count() == lines


@pytest.mark.parametrize("edit", EDITS)
@pytest.mark.parametrize("field", FIELDS)
async def test_mcp_update_order_refuses_a_blank_kit_line(client, retailer, edit, field):
    order, item = await _order_with_a_kit_line(client, retailer)
    before, lines = await _kits(), await _line_count()

    message = await _tool_error(
        "update_order",
        {"order_id": order["id"], "changes": {"items": edit(item, field, "\t")}},
    )
    assert message == f"{field} cannot be blank"
    assert await _kits() == before
    assert await _line_count() == lines


async def test_an_order_edit_takes_a_real_restatement(client, retailer):
    """The control: the same three edits with real values go through."""
    order, item = await _order_with_a_kit_line(client, retailer)
    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {**_restated(item, name="RX-78-2 Gundam (Revive)"), "quantity": 3},
                kit_line(quantity=1, name="Zaku II"),
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    names = sorted(k[1] for k in await _kits())
    assert names == ["RX-78-2 Gundam (Revive)"] * 3 + ["Zaku II"]


# --- a kit already stored blank -------------------------------------------------------


async def _store_blank(kit_ids: list[str], field: str) -> None:
    """A kit as an older writer left it: written around the API, which now refuses."""
    async with get_sessionmaker()() as session:
        for kit_id in kit_ids:
            kit = await session.get(Kit, uuid.UUID(kit_id))
            setattr(kit, field, "   ")
        await session.commit()


@pytest.mark.parametrize("field", FIELDS)
async def test_a_stored_blank_kit_line_still_takes_other_edits(http_client, retailer, field):
    """No data migration: a kit already stored blank stays as it is. An edit that does
    not restate the line's kit details still saves (the order dialog omits `kit` on a
    line whose kit fields it did not touch, #67), and so does an edit to the kit that
    does not send the blank field. Adding kits to the line clones the first kit's
    details, which would spawn another blank kit, so that is refused, naming the
    field; and the kit takes a real value, which is how the owner fixes it."""
    order, item = await _order_with_a_kit_line(http_client, retailer)
    kit_ids = [k["id"] for k in item["kits"]]
    await _store_blank(kit_ids, field)
    line = {k: v for k, v in _restated(item).items() if k != "kit"}

    priced = await http_client.patch(
        f"/orders/{order['id']}", json={"items": [{**line, "unit_price_minor": 5200}]}
    )
    assert priced.status_code == 200, priced.text
    rated = await http_client.patch(f"/kits/{kit_ids[0]}", json={"rating": 3})
    assert rated.status_code == 200, rated.text
    before = await _kits()

    grown = await http_client.patch(
        f"/orders/{order['id']}", json={"items": [{**line, "quantity": 3}]}
    )
    _assert_field_blank(grown, field)
    assert await _kits() == before

    fixed = await http_client.patch(f"/kits/{kit_ids[0]}", json={field: KIT[field]})
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()[field] == KIT[field]


# --- the importer: already refused ---------------------------------------------------


@pytest.mark.parametrize("field", FIELDS)
async def test_the_importer_already_refuses_a_blank_cell(client, field):
    """The third writer needed no change: `parse_text` reads the cell as no value and
    the column is required. Measured here so the three writers are seen to agree."""
    kit = (await client.post("/kits", json=KIT)).json()
    export = await client.get("/export/archive")
    tables = read_archive(export.content)
    [row] = tables["kits"]
    row[field] = "   "
    upload = make_archive({"kits": [row]})
    plan = await preview(client, upload)
    assert actions(plan, "kits") == ["error"], plan["tables"]
    [entry] = [e for e in plan["tables"] if e["table"] == "kits"]
    assert "import.cell_required" in codes(entry["rows"][0]["errors"])
    assert [d["code"] for d in plan["blocking_errors"]] == ["import.rows_unreadable"]
    assert (await client.get(f"/kits/{kit['id']}")).json()["name"] == KIT["name"]


# --- the round trip ------------------------------------------------------------------


async def test_refused_writes_leave_an_export_that_reimports_as_a_no_op(
    http_client, client, retailer
):
    """Every writer path tries a blank; none lands; the store is what it was; and its
    export, imported back in merge mode, changes nothing (rule 10).

    Two kits of each provenance — one direct, one order-spawned line of two — so a
    refusal that reached one row and not another is seen. A padded name stands for
    the owner's existing kit with a trailing space: stored as sent, round-tripping.
    """
    direct = (await http_client.post("/kits", json={"name": "Zaku II ", "grade": "HG"})).json()
    order, item = await _order_with_a_kit_line(http_client, retailer)
    before, lines = await _kits(), await _line_count()
    assert len(before) == 3

    for field in FIELDS:
        _assert_field_blank(await http_client.post("/kits", json={**KIT, field: " "}), field)
        _assert_field_blank(
            await http_client.patch(f"/kits/{direct['id']}", json={field: " "}), field
        )
        blank_order = _order_body(retailer, [_blank_kit_line(field, " ")])
        _assert_field_blank(await http_client.post("/orders", json=blank_order), field)
        for edit in EDITS:
            _assert_field_blank(
                await http_client.patch(
                    f"/orders/{order['id']}", json={"items": edit.values[0](item, field, " ")}
                ),
                field,
            )
        await _tool_error("create_kit", {"kit": {**KIT, field: " "}})
        await _tool_error("update_kit", {"kit_id": direct["id"], "changes": {field: " "}})

    assert await _kits() == before
    assert await _line_count() == lines

    content = (await client.get("/export/archive")).content
    plan = await preview(client, content, mode="merge")
    assert plan["blocking_errors"] == []
    for entry in plan["tables"]:
        assert all(row["action"] == "unchanged" for row in entry["rows"]), entry
    resp = await apply(client, content, mode="merge")
    assert resp.status_code == 200, resp.text
    assert (resp.json()["created"], resp.json()["updated"]) == (0, 0)
    assert await _kits() == before
