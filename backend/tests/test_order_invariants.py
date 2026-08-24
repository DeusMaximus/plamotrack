"""What an order line and an order receipt are allowed to become, whichever
writer asks (#44).

The importer writes model rows by direct `setattr`, so it reached the same tables
as REST and MCP without any of their guards. This module is the check on that:
one table of edits, driven through **both** the REST order editor and a merge
import, asserting each writer reaches the same verdict and the same collection
state. Two suites, one per side, is how the two drifted apart in the first place
— the whole point is that a scenario cannot be added to one driver without an
answer from the other.

Receipt is deliberately *not* in that table, and has its own section below. REST
and import legitimately differ there: `POST /orders/{id}/receive` applies stock,
and an import never invents stock (rule 10). So the receipt axis asserts what
each one does rather than that they match.
"""

import csv
import io
import zipfile
from datetime import datetime

import pytest
from sqlalchemy import text as sa_text

from app.db import session_scope
from app.services.portability import exporting, spec
from tests.test_portability import actions, apply, preview, read_archive

pytestmark = pytest.mark.anyio


# --- helpers --------------------------------------------------------------------


def archive(headers: dict[str, list[str]] | None = None, **tables: list[dict]) -> bytes:
    """A merge-importable zip of whole tables, written from the spec's own headers
    (rule 9) so a column added to a model reaches these tests for free.

    `headers` narrows one table to the columns named, for the rows whose point is
    what the sheet does *not* say. A full `kits` header carries `created_at` and
    `updated_at`, and those are NOT NULL — a blank cell in either is a 500 that has
    nothing to do with what the test is about (see the note in HANDOFF).
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "manifest.json",
            f'{{"format": "plamotrack-archive", "export_version": {exporting.EXPORT_VERSION}}}',
        )
        for key, rows in tables.items():
            out = io.StringIO()
            fieldnames = (headers or {}).get(key) or spec.SPEC_BY_KEY[key].header
            writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            zf.writestr(f"{key}.csv", out.getvalue())
    return buffer.getvalue()


def sheet(table: str, header: list[str], rows: list[dict]) -> bytes:
    """A single CSV with a header the caller chooses, for the cases whose whole
    point is which columns the sheet carries."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


async def make_order(client, retailer, items, *, received=False, number="HLJ-1"):
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-03-14",
            "order_number": number,
            "currency_code": "JPY",
            "received": received,
            "items": items,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def kit_line(quantity=2, name="Zaku II"):
    return {
        "item_type": "kit",
        "quantity": quantity,
        "unit_price_minor": 2800,
        "currency_code": "JPY",
        "kit": {"name": name, "grade": "HG"},
    }


def consumable_line(ref_id, quantity=3):
    return {
        "item_type": "consumable",
        "quantity": quantity,
        "unit_price_minor": 500,
        "currency_code": "JPY",
        "catalog_ref_id": ref_id,
    }


async def make_consumable(client, name="Panel liner", on_hand=0):
    resp = await client.post(
        "/consumables",
        json={"name": name, "category": "paint", "quantity_on_hand": on_hand},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def stock_of(client, consumable_id) -> int:
    rows = (await client.get("/consumables")).json()
    return next(row["quantity_on_hand"] for row in rows if row["id"] == consumable_id)


async def kit_states(client) -> list[tuple[str, str]]:
    return sorted((k["name"], k["status"]) for k in (await client.get("/kits")).json())


def order_row(order, retailer, **overrides) -> dict:
    """The order exactly as it stands, so only `overrides` differ from stored."""
    row = {
        "id": order["id"],
        "retailer_id": retailer["id"],
        "order_date": order["order_date"],
        "order_number": order["order_number"],
        "currency_code": order["currency_code"],
        "received_at": order["received_at"] or "",
    }
    row.update(overrides)
    return row


def line_row(order, item, **overrides) -> dict:
    row = {
        "id": item["id"],
        "order_id": order["id"],
        "item_type": item["item_type"],
        "catalog_ref_id": item["catalog_ref_id"] or "",
        "quantity": str(item["quantity"]),
        "unit_price_minor": str(item["unit_price_minor"]),
        "currency_code": item["currency_code"],
    }
    if item["item_type"] == "kit":
        row["kit_name"] = "Zaku II"
        row["kit_grade"] = "HG"
    row.update(overrides)
    return row


def rest_line(item, **overrides) -> dict:
    """The stored line echoed back the way a client hydrates a form from it —
    which is what makes an unintended change unintended."""
    payload = {
        "id": item["id"],
        "item_type": item["item_type"],
        "quantity": item["quantity"],
        "unit_price_minor": item["unit_price_minor"],
        "currency_code": item["currency_code"],
    }
    if item["item_type"] == "kit":
        payload["kit"] = {"name": "Zaku II", "grade": "HG"}
    else:
        payload["catalog_ref_id"] = item["catalog_ref_id"]
    payload.update(overrides)
    return payload


# --- the shared matrix: one edit, two writers ------------------------------------
#
# Each scenario names an edit to a stored order line and says whether *both*
# writers have to refuse it. `refused=True` means the collection must come back
# untouched from each; `refused=False` means each applies it and lands on the same
# kit list. The two drivers below read the same table.

INVARIANTS = [
    pytest.param(
        {
            "id": "item_type change",
            "kits": 2,
            "progress": (),
            "rest": {"item_type": "consumable", "kit": None, "catalog_ref_id": None},
            "sheet": {"item_type": "consumable"},
            "refused": True,
        },
        id="item_type change",
    ),
    pytest.param(
        {
            "id": "reparent to another order",
            "kits": 2,
            "progress": (),
            "rest": "other-order",
            "sheet": "other-order",
            "refused": True,
        },
        id="reparent",
    ),
    pytest.param(
        {
            "id": "quantity 2 -> 1, nothing started",
            "kits": 2,
            "progress": (),
            "rest": {"quantity": 1},
            "sheet": {"quantity": "1"},
            "refused": False,
            "kits_after": 1,
        },
        id="quantity down, clean",
    ),
    pytest.param(
        {
            "id": "quantity 2 -> 1, both kits building",
            "kits": 2,
            "progress": ("building", "building"),
            "rest": {"quantity": 1},
            "sheet": {"quantity": "1"},
            "refused": True,
        },
        id="quantity down, progressed",
    ),
    pytest.param(
        {
            "id": "quantity 2 -> 1, both kits carry an applied upgrade",
            "kits": 2,
            "progress": (),
            "apply_upgrades": True,
            "rest": {"quantity": 1},
            "sheet": {"quantity": "1"},
            "refused": True,
        },
        id="quantity down, applied upgrade",
    ),
]


async def _seed_scenario(client, case) -> tuple[dict, dict, dict]:
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(case["kits"])], number="HLJ-1")
    other = await make_order(client, retailer, [kit_line(1, name="Gouf")], number="HLJ-2")
    item = order["items"][0]

    for kit, status in zip(item["kits"], case.get("progress", ()), strict=False):
        resp = await client.patch(f"/kits/{kit['id']}", json={"status": status})
        assert resp.status_code == 200, resp.text

    if case.get("apply_upgrades"):
        upgrade = (
            await client.post(
                "/upgrades",
                json={
                    "name": "Metal thruster",
                    "manufacturer": "Kotobukiya",
                    "quantity_on_hand": 5,
                },
            )
        ).json()
        for kit in item["kits"]:
            resp = await client.post(
                f"/upgrades/{upgrade['id']}/apply",
                json={"kit_id": kit["id"], "quantity": 1},
            )
            assert resp.status_code == 201, resp.text

    return retailer, order, other


@pytest.mark.parametrize("case", INVARIANTS)
async def test_the_rest_editor_answers_the_invariant_matrix(client, case):
    retailer, order, other = await _seed_scenario(client, case)
    item = order["items"][0]
    before = await kit_states(client)

    if case["rest"] == "other-order":
        # There is no "move this line" payload: REST reaches reparenting only by
        # offering a line id to an order that doesn't own it, which is the shape
        # `update_order` refuses. Same intent as the sheet's order_id change.
        resp = await client.patch(f"/orders/{other['id']}", json={"items": [rest_line(item)]})
    else:
        resp = await client.patch(
            f"/orders/{order['id']}", json={"items": [rest_line(item, **case["rest"])]}
        )

    if case["refused"]:
        assert resp.status_code in (409, 422), f"{case['id']}: {resp.status_code} {resp.text}"
        assert await kit_states(client) == before, case["id"]
    else:
        assert resp.status_code == 200, f"{case['id']}: {resp.text}"
        assert len(await kit_states(client)) == case["kits_after"] + 1, case["id"]


@pytest.mark.parametrize("case", INVARIANTS)
async def test_a_merge_import_answers_the_same_invariant_matrix(client, case):
    retailer, order, other = await _seed_scenario(client, case)
    item = order["items"][0]
    before = await kit_states(client)

    overrides = {"order_id": other["id"]} if case["sheet"] == "other-order" else case["sheet"]
    content = archive(order_items=[line_row(order, item, **overrides)])

    plan = await preview(client, content)
    resp = await apply(client, content)

    if case["refused"]:
        assert actions(plan, "order_items") == ["error"], f"{case['id']}: {plan['tables']}"
        assert plan["blocking_errors"], case["id"]
        assert resp.status_code == 409, f"{case['id']}: {resp.text}"
        assert await kit_states(client) == before, case["id"]
    else:
        assert plan["blocking_errors"] == [], f"{case['id']}: {plan}"
        assert resp.status_code == 200, f"{case['id']}: {resp.text}"
        assert len(await kit_states(client)) == case["kits_after"] + 1, case["id"]


async def test_the_refusal_names_the_column_it_is_about(client):
    """The matrix asserts the verdict; a verdict nobody can act on is half a fix.

    Both refusals have to say which cell is wrong — the importer reports one error
    per row, so a message naming only "this line" leaves the operator diffing a
    sheet against a database by hand.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line()], number="HLJ-1")
    other = await make_order(client, retailer, [kit_line(1, name="Gouf")], number="HLJ-2")
    item = order["items"][0]

    typed = await preview(client, archive(order_items=[line_row(order, item, item_type="tool")]))
    moved = await preview(
        client, archive(order_items=[line_row(order, item, order_id=other["id"])])
    )
    assert typed["tables"][0]["rows"][0]["error"].startswith("item_type:")
    assert moved["tables"][0]["rows"][0]["error"].startswith("order_id:")
    # And the fix, not merely the refusal.
    assert "Remove the line and add a new one" in typed["tables"][0]["rows"][0]["error"]
    assert "add a new line to the other order" in moved["tables"][0]["rows"][0]["error"]


async def test_restating_item_type_and_order_id_unchanged_is_not_a_change(client):
    """The immutability check reads `changes`, not values — so a full archive,
    which restates every column of every row, is still a no-op. This is the case
    that would have made the guard unusable if it compared values instead."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line()])
    item = order["items"][0]

    plan = await preview(client, archive(order_items=[line_row(order, item)]))
    assert actions(plan, "order_items") == ["unchanged"], plan["tables"]
    assert plan["blocking_errors"] == []


async def test_kit_details_propagate_through_rest_and_not_through_a_sheet(client):
    """The one documented divergence in the matrix's subject area, pinned so it
    stays deliberate.

    `_update_line` pushes a restated kit name down onto every kit the line spawned
    (#65): the Orders page is the only place that edit can be made, so it has to
    reach the kits. `order_items.csv`'s `kit_*` columns are virtual and mean
    something narrower — the spec says they "only matter when no kits row covers
    the line", because an archive carries `kits.csv` and that file is where a kit's
    own name lives. A sheet that renames them there is not ambiguous; one that
    renames them on the order line is, so the importer leaves the kits alone.

    Not a refusal either way, which is why it is not in the table above.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line()])
    item = order["items"][0]

    resp = await apply(client, archive(order_items=[line_row(order, item, kit_name="Char's Zaku")]))
    assert resp.status_code == 200, resp.text
    assert {name for name, _ in await kit_states(client)} == {"Zaku II"}

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [rest_line(item, kit={"name": "Char's Zaku", "grade": "HG"})]},
    )
    assert resp.status_code == 200, resp.text
    assert {name for name, _ in await kit_states(client)} == {"Char's Zaku"}


# --- downward reconciliation: which kits go, and when none do --------------------


async def test_a_reduced_line_removes_the_newest_kit_and_says_so_first(client):
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(3)])
    item = order["items"][0]
    oldest = item["kits"][0]["id"]

    content = archive(order_items=[line_row(order, item, quantity="1")])
    plan = await preview(client, content)
    assert plan["derived"]["kits_removed"] == 2, plan["derived"]
    assert "will remove 2 kit(s) from this line" in plan["tables"][0]["rows"][0]["messages"]

    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_removed"] == 2
    remaining = (await client.get("/kits")).json()
    assert [k["id"] for k in remaining] == [oldest], "the oldest kit is the one kept"


async def test_a_reduced_line_will_not_remove_a_kit_the_same_upload_describes(client):
    """The upload contradicting itself — a `kits.csv` asserting two kits exist and
    an `order_items.csv` quantity implying one does. Neither half is wrong on its
    own, so nothing but the pair can catch it, and picking a winner silently is
    how an import surprises someone."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]
    kits = item["kits"]

    content = archive(
        order_items=[line_row(order, item, quantity="1")],
        kits=[
            {"id": k["id"], "name": "Zaku II", "grade": "HG", "order_item_id": item["id"]}
            for k in kits
        ],
    )
    plan = await preview(client, content)
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    assert "described by this upload" in plan["tables"][0]["rows"][0]["error"]

    resp = await apply(client, content)
    assert resp.status_code == 409
    assert len(await kit_states(client)) == 2


async def test_a_line_cannot_be_over_supplied_by_the_uploads_own_kits(client):
    """The same contradiction reached from the create side: `kits.csv` brings more
    new kits for a stored line than its quantity admits. The line's row is here but
    restates the quantity, so it authorises nothing and the new kits are refused as
    moves the upload cannot reconcile — the message names the restated number, so
    the operator's edit is one cell. (A line the upload *creates* with too many
    kits is the fan-out's own over-supply error, three modes, further down.)"""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]

    content = archive(
        order_items=[line_row(order, item, quantity="1")],
        kits=[
            {"name": "Zaku II", "grade": "HG", "order_item_id": item["id"]},
            {"name": "Zaku II", "grade": "HG", "order_item_id": item["id"]},
        ],
    )
    plan = await preview(client, content)
    assert actions(plan, "order_items") == ["unchanged"], plan["tables"]
    assert actions(plan, "kits") == ["error", "error"], plan["tables"]
    kits_plan = next(t for t in plan["tables"] if t["table"] == "kits")
    assert "leaves that quantity as it is" in kits_plan["rows"][0]["error"]
    assert "holding 3 kit(s) while the line says it bought 1" in kits_plan["rows"][0]["error"]
    assert plan["blocking_errors"]
    assert (await apply(client, content)).status_code == 409
    assert len(await kit_states(client)) == 1


@pytest.mark.parametrize(
    ("header_has_quantity", "cell", "expected"),
    [
        # The column simply isn't there. `values.get("quantity") or 0` reads that as
        # zero, and zero counting *downward* asks for every kit on the line — so a
        # sheet fixing a tracking number would have emptied the order. This is the
        # case the guard exists for, and no value in the cell can express it.
        (False, None, "untouched"),
        # There, but empty. `quantity` is required, so this is a row error rather
        # than a silent nothing — and either way not a removal.
        (True, "", "error"),
        # There, and the same as stored: nothing to reconcile in either direction.
        (True, "2", "untouched"),
        # There, and lower: the reconciliation this parametrisation is bracketing.
        (True, "1", "removed"),
    ],
    ids=["column absent", "blank cell", "same value", "lower"],
)
async def test_a_quantity_the_sheet_never_states_removes_nothing(
    client, header_has_quantity, cell, expected
):
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]

    header = ["id", "order_id", "item_type", "unit_price_minor", "currency_code"]
    row = {
        "id": item["id"],
        "order_id": order["id"],
        "item_type": "kit",
        "unit_price_minor": "2800",
        "currency_code": "JPY",
    }
    if header_has_quantity:
        header.insert(3, "quantity")
        row["quantity"] = cell

    content = sheet("order_items", header, [row])
    plan = await preview(client, content, filename="order_items.csv")
    resp = await apply(client, content, filename="order_items.csv")

    if expected == "error":
        assert actions(plan, "order_items") == ["error"], plan["tables"]
        assert resp.status_code == 409
        assert len(await kit_states(client)) == 2
    elif expected == "untouched":
        assert plan["derived"]["kits_removed"] == 0, plan["derived"]
        assert resp.status_code == 200, resp.text
        assert len(await kit_states(client)) == 2
    else:
        assert plan["derived"]["kits_removed"] == 1, plan["derived"]
        assert resp.status_code == 200, resp.text
        assert len(await kit_states(client)) == 1


@pytest.mark.parametrize(
    ("direction", "quantity", "expect_spawned", "expect_removed", "kits_on_line"),
    [
        # A kit moved ONTO a two-kit line, quantity raised to take it: nothing to
        # spawn, because the arriving kit is the third. Counting `row.target.kits`
        # read the database before that write and spawned one anyway — measured on
        # the first cut of this branch.
        ("onto", "3", 0, 0, 3),
        # ...raised past it: the arrival is counted and one more is owed.
        ("onto", "4", 1, 0, 4),
        # ...dropped below it: the arrival is described by the upload and stays;
        # both incumbents are the surplus.
        ("onto", "1", 0, 2, 1),
        # A kit moved OFF, quantity dropped to match: the count has to see the
        # departure, or it plans a removal for a kit that is already leaving.
        ("off", "1", 0, 0, 1),
        # ...and raised: the departure leaves one, three are owed, two are spawned.
        ("off", "3", 2, 0, 3),
    ],
    ids=[
        "moved on, quantity raised to take it",
        "moved on, quantity raised past it",
        "moved on, quantity dropped below it",
        "moved off, quantity dropped to match",
        "moved off, quantity raised",
    ],
)
async def test_the_fan_out_counts_the_kits_the_line_will_hold_not_the_ones_it_holds(
    client, direction, quantity, expect_spawned, expect_removed, kits_on_line
):
    """`kits.order_item_id` is an ordinary REF column, so one upload can state a
    line's quantity *and* move kits onto or off that line. Both sides of the fan-out
    arithmetic have to read the post-write set, or they answer about a state that
    won't exist by the time they're applied.

    Pre-existing — `_plan_spawns` always counted stored rows — but only visible once
    downward reconciliation claimed a line and its kits were kept in agreement.

    Every row here *changes* the quantity (the stored line says 2). Two rows that
    restated it unchanged used to sit in this matrix and reconcile — a delete and a
    spawn on the strength of a number the upload didn't write; they now live in
    `test_a_line_whose_quantity_this_upload_leaves_alone_authorises_no_reconciliation`
    as refusals.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]

    if direction == "onto":
        subject = (
            await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
        ).json()
        parent = item["id"]
    else:
        subject = item["kits"][0]
        parent = ""

    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        order_items=[line_row(order, item, quantity=quantity)],
        kits=[
            {
                "id": subject["id"],
                "name": subject["name"],
                "grade": "HG",
                "order_item_id": parent,
            }
        ],
    )
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert plan["derived"]["kits_spawned"] == expect_spawned, plan["derived"]
    assert plan["derived"]["kits_removed"] == expect_removed, plan["derived"]

    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert stored["quantity"] == int(quantity)
    assert len(stored["kits"]) == kits_on_line, "the line and the collection have to agree"
    assert len(stored["kits"]) == stored["quantity"]


async def test_one_mistyped_order_item_id_in_a_full_archive_cannot_spawn_a_duplicate(client):
    """Two decided behaviours meeting: #82 nulls an optional reference it can't
    resolve (the row "imports without it"), and this branch spawns for a line
    whose restated quantity its kits no longer cover. Compose them on a pristine
    archive with one wrong cell — a spawned kit's `order_item_id` mistyped — and
    the kit was detached from the line that bought it *and* a replacement spawned
    in its place, at 200, with only informational messages to show for it. The
    same cell in `kits.csv` alone was already a 409, because that line's quantity
    was never restated: the archive's own unchanged `order_items.csv` was what
    turned a refusal into a duplicate.

    Now refused at the cell (`_refuse_unresolved_overwrite`): an id that names
    nothing may not clear a link the stored row has. Asserted on the message that
    rule writes, because the count rule (#44) can refuse a detach too and a bare
    409 would not say which one spoke.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]
    kit = item["kits"][0]

    tables = read_archive((await client.get("/export/archive")).content)
    for row in tables["kits"]:
        if row["id"] == kit["id"]:
            row["order_item_id"] = "00000000-0000-0000-0000-00000000dead"
    content = archive(**tables)

    plan = await preview(client, content)
    assert actions(plan, "kits") == ["error"], plan["tables"]
    kits_plan = next(t for t in plan["tables"] if t["table"] == "kits")
    assert "can't be what clears that link" in kits_plan["rows"][0]["error"]
    assert plan["derived"]["kits_spawned"] == 0, plan["derived"]
    assert plan["derived"]["kits_removed"] == 0, plan["derived"]
    assert (await apply(client, content)).status_code == 409

    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert [k["id"] for k in stored["kits"]] == [kit["id"]], "still the one kit, still on its line"
    assert len(await kit_states(client)) == 1


@pytest.mark.parametrize("direction", ["attach", "detach"], ids=["attach", "detach"])
@pytest.mark.parametrize(
    "line_row_state",
    ["restated", "edited elsewhere"],
    ids=["line restated", "line edited elsewhere"],
)
async def test_a_line_whose_quantity_this_upload_leaves_alone_authorises_no_reconciliation(
    client, direction, line_row_state
):
    """Authority to spawn or delete comes from a quantity this upload *writes*, not
    one it carries. Both shapes here carry the line's quantity — restated exactly,
    or on an update that changes some other column — and neither authorises the
    fan-out to make a kit move fit.

    Why it matters: every full archive restates every line, so under the earlier
    reading ("stated") an unchanged row was what turned a refused move into a
    delete — `kits.csv` alone attaching a kit to a quantity-one line was a 409,
    and the same move beside the archive's own `order_items.csv` deleted the
    incumbent, announced, at 200. A restated line describes; it does not instruct.

    The refusal names the restated quantity and says the row leaves it as it is,
    because "add a row" — the message for an absent line — would send the
    operator to add a row that is already there.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]
    incumbent = item["kits"][0]

    if direction == "attach":
        subject = (
            await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
        ).json()
        parent = item["id"]
    else:
        subject = incumbent
        parent = ""

    overrides = {} if line_row_state == "restated" else {"unit_price_minor": "9999"}
    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        order_items=[line_row(order, item, **overrides)],
        kits=[
            {"id": subject["id"], "name": subject["name"], "grade": "HG", "order_item_id": parent}
        ],
    )
    plan = await preview(client, content)
    expected_line = "unchanged" if line_row_state == "restated" else "update"
    assert actions(plan, "order_items") == [expected_line], plan["tables"]
    assert actions(plan, "kits") == ["error"], plan["tables"]
    kits_plan = next(t for t in plan["tables"] if t["table"] == "kits")
    error = kits_plan["rows"][0]["error"]
    holding = 2 if direction == "attach" else 0
    assert f"holding {holding} kit(s) while the line says it bought 1" in error, error
    assert "leaves that quantity as it is" in error, error
    assert plan["derived"]["kits_spawned"] == 0, plan["derived"]
    assert plan["derived"]["kits_removed"] == 0, plan["derived"]

    assert (await apply(client, content)).status_code == 409
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert [k["id"] for k in stored["kits"]] == [incumbent["id"]], "nobody moved, nobody went"
    assert stored["unit_price_minor"] == item["unit_price_minor"], "the edit didn't land either"


@pytest.mark.parametrize("drift", ["one kit short", "one kit over"], ids=["short", "over"])
async def test_re_importing_an_archive_of_a_drifted_line_is_a_no_op(client, drift):
    """Rule 10, literally: re-importing an archive is a no-op *whatever the
    collection holds*. Importers before this branch could leave a kit line holding
    a different number of kits than its quantity said (the fan-out only counted
    upward). An archive taken from such an instance restates the line unchanged
    and restates each kit where it already is — nothing written, nothing moved —
    so a merge re-import must plan nothing: no spawn to "repair" the short line,
    no refusal of the over-supplied one. Both were the earlier reading's answers.

    The drift is made directly in the database, because no writer produces it any
    more. `replace_all` is different and stays refused for the over-supplied
    shape: every row is a create there, the upload is the only world, and it
    contradicts itself — `docs/import-export.md` says why an operator can see it.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]
    async with session_scope() as session:
        if drift == "one kit short":
            await session.execute(
                sa_text("DELETE FROM kits WHERE id = :id"), {"id": item["kits"][1]["id"]}
            )
        else:
            await session.execute(
                sa_text(
                    "INSERT INTO kits (id, name, grade, status, status_updated_at, "
                    "order_item_id, created_at, updated_at) VALUES (gen_random_uuid(), "
                    "'Zaku II', 'HG', 'backlog', now(), :line, now(), now())"
                ),
                {"line": item["id"]},
            )
        await session.commit()
    before = await kit_states(client)
    assert len(before) == (1 if drift == "one kit short" else 3)

    export = (await client.get("/export/archive")).content

    plan = await preview(client, export)
    assert plan["blocking_errors"] == [], plan
    assert plan["derived"]["kits_spawned"] == 0, plan["derived"]
    assert plan["derived"]["kits_removed"] == 0, plan["derived"]
    resp = await apply(client, export)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_spawned"] == 0 and resp.json()["kits_removed"] == 0
    assert await kit_states(client) == before, "a re-imported archive changed the collection"

    if drift == "one kit over":
        restore = await preview(client, export, mode="replace_all")
        assert actions(restore, "order_items") == ["error"], restore["tables"]
        error = next(t for t in restore["tables"] if t["table"] == "order_items")["rows"][0]
        assert "this upload supplies 3 kit(s)" in error["error"], error


@pytest.mark.parametrize(
    ("quantity", "drifted", "expect_spawned", "kits_after"),
    [("2", False, 0, 2), ("3", False, 1, 3), ("2", True, 0, 1)],
    ids=["line restated", "line quantity raised", "line restated, collection drifted"],
)
async def test_a_kits_sheet_that_never_mentions_order_item_id_moves_nothing(
    client, quantity, drifted, expect_spawned, kits_after
):
    """The column-absent state, on the *other* table.

    A partial `kits.csv` fixing a build note has no `order_item_id` column, and
    `values.get(...)` is then `None` — indistinguishable from a cell that says
    "detach this kit". Two places read `present` rather than values so the two
    are told apart, and each has its own line state here:

    * **line quantity raised** — the line is reconciled, so `_attached_after` is
      what sees the row; reading it as a detach spawns a replacement for a kit
      that never went anywhere (two spawned here instead of one).
    * **line restated** — the line authorises nothing, so the kit-move refusal is
      what sees the row. On a healthy line its guard is shadowed by
      `_attached_after`'s (the count comes out right either way); on a line whose
      collection had drifted before this rule existed, reading the row as a move
      refuses a build-note fix for "leaving the line short" — so the drifted
      state is the one that pins it.

    Found by mutation testing, three times: removing either guard left the suite
    green, because every other kits row in it carries the column, and the
    refusal's guard stayed green on a healthy line for the reason above.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]
    before = [k["id"] for k in item["kits"]]
    if drifted:
        async with session_scope() as session:
            await session.execute(sa_text("DELETE FROM kits WHERE id = :id"), {"id": before[1]})
            await session.commit()
        before = before[:1]

    content = archive(
        {"kits": ["id", "name", "grade", "build_notes"]},
        order_items=[line_row(order, item, quantity=quantity)],
        kits=[
            {"id": before[0], "name": "Zaku II", "grade": "HG", "build_notes": "waist is fiddly"}
        ],
    )
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert plan["derived"]["kits_spawned"] == expect_spawned, plan["derived"]
    assert plan["derived"]["kits_removed"] == 0, plan["derived"]

    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert [k["id"] for k in stored["kits"]][: len(before)] == before, "nobody moved"
    assert len(stored["kits"]) == kits_after
    assert (await client.get(f"/kits/{before[0]}")).json()["build_notes"] == "waist is fiddly"


async def test_a_partial_line_update_that_omits_item_type_still_reconciles(client):
    """The axis the shared matrix never varies, because `line_row` always supplies
    `item_type` (external review of #86).

    `_plan_spawns` classified the line from `row.values` alone, so a partial sheet
    stating only `id,order_id,quantity` read as typeless and skipped reconciliation
    entirely — the line dropped to 1 and kept both kits. `invariants` already had
    the correct reading for exactly this reason; the fan-out had a second, wrong
    one written one module over.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]

    content = sheet(
        "order_items",
        ["id", "order_id", "quantity"],
        [{"id": item["id"], "order_id": order["id"], "quantity": "1"}],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert plan["derived"]["kits_removed"] == 1, plan["derived"]

    resp = await apply(client, content, filename="order_items.csv")
    assert resp.status_code == 200, resp.text
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert stored["quantity"] == 1
    assert len(stored["kits"]) == 1, "the line and the collection have to agree"


# --- #90: the omitted-item_type axis of catalog reference resolution -------------
#
# `_resolve_ref` dispatches `catalog_ref_id` by the line's item_type, and a partial
# sheet legitimately omits that column. These cases cross the omitted axis with
# what the reference cell holds; the shared matrix above never varies it because
# `line_row` always supplies `item_type`, and the REST driver has no analogue at
# all — the schema requires the field, so only the importer can reach this state.


DEAD_REF = "11111111-1111-1111-1111-111111111111"


async def line_ref_after(client, order) -> str | None:
    return (await client.get(f"/orders/{order['id']}")).json()["items"][0]["catalog_ref_id"]


async def test_a_kit_line_update_omitting_item_type_does_not_write_a_catalog_ref(client):
    """The #90 write-through, on the branch #86's invariant cannot see.

    A stored *catalog* line omitting `item_type` is refused downstream by
    `_check_catalog_targets`, whose effective reading knows the stored type — but a
    stored **kit** line passes that check by design (kit lines don't reference the
    catalog), so a resolver that reads `values` alone sent the raw cell straight to
    the database: a dangling uuid on a kit line, silently, at 200. The fix gives the
    resolver the same effective reading, so the cell earns #89's ignored-reference
    message instead of a write."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]

    content = sheet(
        "order_items",
        ["id", "order_id", "catalog_ref_id"],
        [{"id": item["id"], "order_id": order["id"], "catalog_ref_id": DEAD_REF}],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert plan["blocking_errors"] == [], plan
    [row] = plan["tables"][0]["rows"]
    assert any("doesn't reference the catalog" in message for message in row["messages"]), row

    resp = await apply(client, content, filename="order_items.csv")
    assert resp.status_code == 200, resp.text
    assert await line_ref_after(client, order) is None, (
        "a kit line must never hold a catalog reference"
    )


async def test_a_catalog_line_update_omitting_item_type_still_refuses_a_dead_ref(client):
    """The issue's headline row, pinned at its post-#86 verdict: refused, not
    written. Before the resolver fix the refusal came from `_check_catalog_targets`
    alone; with it, the resolver nulls the cell and `_refuse_unresolved_overwrite`
    speaks first. Either way the layer is the preview and the answer is a blocking
    error on this column — which is what this asserts, not the wording."""
    paint = await make_consumable(client)
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [consumable_line(paint["id"])])
    item = order["items"][0]

    content = sheet(
        "order_items",
        ["id", "order_id", "catalog_ref_id"],
        [{"id": item["id"], "order_id": order["id"], "catalog_ref_id": DEAD_REF}],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert plan["blocking_errors"], plan
    [row] = plan["tables"][0]["rows"]
    assert row["action"] == "error"
    assert row["error"].startswith("catalog_ref_id:"), row["error"]

    resp = await apply(client, content, filename="order_items.csv")
    assert resp.status_code == 409, resp.text
    assert await line_ref_after(client, order) == paint["id"]


async def test_a_catalog_line_update_omitting_item_type_repoints_at_a_local_id(client):
    """The green control on the same axis: a resolvable local uuid imports whether
    or not the resolver dispatches, because `_check_catalog_targets` accepts what
    `by_id` holds. Here so the two red neighbours can't be read as 'omitting
    item_type refuses everything'."""
    paint = await make_consumable(client, "Panel liner")
    topcoat = await make_consumable(client, "Top coat")
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [consumable_line(paint["id"])])
    item = order["items"][0]

    content = sheet(
        "order_items",
        ["id", "order_id", "catalog_ref_id"],
        [{"id": item["id"], "order_id": order["id"], "catalog_ref_id": topcoat["id"]}],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert plan["blocking_errors"] == [], plan

    resp = await apply(client, content, filename="order_items.csv")
    assert resp.status_code == 200, resp.text
    assert await line_ref_after(client, order) == topcoat["id"]


async def test_a_catalog_line_update_omitting_item_type_resolves_the_readable_mirror(client):
    """`catalog_name` is documented as standing in for the uuid, and a typeless
    resolver skipped the mirror entirely — the cell the operator filled in was
    ignored without a message, and the line silently kept its old reference."""
    paint = await make_consumable(client, "Panel liner")
    topcoat = await make_consumable(client, "Top coat")
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [consumable_line(paint["id"])])
    item = order["items"][0]

    content = sheet(
        "order_items",
        ["id", "order_id", "catalog_name"],
        [{"id": item["id"], "order_id": order["id"], "catalog_name": "Top coat"}],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert plan["blocking_errors"] == [], plan

    resp = await apply(client, content, filename="order_items.csv")
    assert resp.status_code == 200, resp.text
    assert await line_ref_after(client, order) == topcoat["id"]
    rows = (await client.get("/consumables")).json()
    assert {r["name"] for r in rows} == {"Panel liner", "Top coat"}, "no stub conjured"


async def test_a_catalog_line_update_omitting_item_type_follows_the_uploads_remap(client):
    """A consumables.csv row natural-matching a local item records a remap, and
    every later reference through the file's id is supposed to follow it. The
    typeless resolver never consulted the remap, so the line's reference read as
    pointing at nothing and a legitimate partial archive was refused."""
    topcoat = await make_consumable(client, "Top coat")
    paint = await make_consumable(client, "Panel liner")
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [consumable_line(paint["id"])])
    item = order["items"][0]
    foreign = "22222222-2222-2222-2222-222222222222"

    content = archive(
        {
            "consumables": ["id", "name"],
            "order_items": ["id", "order_id", "catalog_ref_id"],
        },
        consumables=[{"id": foreign, "name": "Top coat"}],
        order_items=[{"id": item["id"], "order_id": order["id"], "catalog_ref_id": foreign}],
    )
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan

    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    assert await line_ref_after(client, order) == topcoat["id"]


async def test_replace_all_does_not_type_the_line_from_the_doomed_database(client):
    """#45's rule holds for the stored line too: a replace-all truncates it, so its
    item_type must not drive resolution. The typeless row is a create refused for
    the missing column — and the mirror name it carries must not conjure a stub
    from a dispatch that had no right to run."""
    paint = await make_consumable(client, "Panel liner")
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [consumable_line(paint["id"])])
    item = order["items"][0]

    content = archive(
        {
            "retailers": ["id", "name"],
            "order_items": ["id", "order_id", "catalog_name", "quantity"],
        },
        retailers=[{"id": retailer["id"], "name": retailer["name"]}],
        orders=[order_row(order, retailer)],
        order_items=[
            {
                "id": item["id"],
                "order_id": order["id"],
                "catalog_name": "Panel liner",
                "quantity": "3",
            }
        ],
    )
    plan = await preview(client, content, mode="replace_all")
    line_rows = next(entry["rows"] for entry in plan["tables"] if entry["table"] == "order_items")
    assert line_rows[0]["action"] == "error"
    assert line_rows[0]["error"].startswith("item_type:"), line_rows[0]["error"]
    assert actions(plan, "consumables") == [], "no stub conjured from the mirror"


async def test_an_existing_kit_moved_onto_a_line_this_upload_creates_supplies_it(client):
    """The action axis of `_attached_after`: the line is a CREATE, so it has no
    stored kits — but a `kits.csv` update can still point an existing kit at it, and
    `covered` cannot see that because `covered` counts kit *creates*.

    Reading "no target" as "nothing attached" spawned a second kit for a
    quantity-one line (external review of #86). The `kept` half is genuinely empty
    for a create; the `arriving` half is not.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    loose = (
        await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
    ).json()
    new_line = "3f0c9e11-2b44-4c8e-9d21-77aa10bb5c33"

    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        order_items=[
            {
                "id": new_line,
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "unit_price_minor": "2500",
                "currency_code": "JPY",
                "kit_name": "Gouf",
                "kit_grade": "HG",
            }
        ],
        kits=[{"id": loose["id"], "name": "Gouf", "grade": "HG", "order_item_id": new_line}],
    )
    plan = await preview(client, content)
    assert plan["derived"]["kits_spawned"] == 0, "the upload supplies this line's kit"

    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    line = next(
        i
        for i in (await client.get(f"/orders/{order['id']}")).json()["items"]
        if i["id"] == new_line
    )
    assert [k["id"] for k in line["kits"]] == [loose["id"]]


@pytest.mark.parametrize(
    ("mode", "shape"),
    [
        # add_only: the line's own row is SKIP, so the fan-out never visits it,
        # while a new kits.csv row attaches a second kit to it.
        ("add_only", "oversupply"),
        # merge, kits.csv only: nothing states the line's quantity at all, and an
        # update blanks its kit's order_item_id.
        ("merge", "undersupply"),
    ],
    ids=["add_only oversupply", "kits-only undersupply"],
)
async def test_a_kit_move_the_upload_cannot_reconcile_is_refused(client, mode, shape):
    """A line reached only from the kits side (external review of #86).

    Refused rather than reconciled. The fan-out spawns and removes because *the
    line stated a quantity*; a kits row moving provenance says nothing about how
    many kits the line bought, so conjuring or deleting one on the strength of it
    invents intent the file never expressed — and in `add_only` it would mean
    deleting, which is the one thing that mode promises never to do.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]

    if shape == "oversupply":
        content = archive(
            {"kits": ["name", "grade", "order_item_id"]},
            order_items=[line_row(order, item)],
            kits=[{"name": "Extra", "grade": "HG", "order_item_id": item["id"]}],
        )
    else:
        content = sheet(
            "kits",
            ["id", "name", "grade", "order_item_id"],
            [{"id": item["kits"][0]["id"], "name": "Zaku II", "grade": "HG", "order_item_id": ""}],
        )

    kwargs = {"mode": mode} if shape == "oversupply" else {"mode": mode, "filename": "kits.csv"}
    plan = await preview(client, content, **kwargs)
    assert actions(plan, "kits") == ["error"], plan["tables"]
    error = next(r for r in plan["tables"][-1]["rows"] if r["error"])["error"]
    assert error.startswith("order_item_id:")
    assert "add an order_items.csv row" in error, "the refusal has to name the fix"

    resp = await apply(client, content, **kwargs)
    assert resp.status_code == 409
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert stored["quantity"] == 1
    assert len(stored["kits"]) == 1, "nothing moved"


@pytest.mark.parametrize("direction", ["attach", "detach"], ids=["attach", "detach"])
@pytest.mark.parametrize("restated", [False, True], ids=["line unchanged", "line updated"])
async def test_a_line_row_carrying_no_quantity_authorises_no_reconciliation(
    client, direction, restated
):
    """Naming a line is not the same as saying what it holds (external review of
    #86, round two).

    `reconciled` was filled as a side effect of the fan-out loop, so it meant
    *visited* rather than *reconciled*. A partial `order_items.csv` naming a line
    without a `quantity` column marked it handled, the fan-out then did nothing
    with it — `wanted` of 0 makes every branch a no-op — and the kit-move refusal
    skipped it as somebody else's problem. Both directions applied at 200.

    The line's own action is the second axis: an otherwise-identical row is
    UNCHANGED or UPDATE depending on whether it restates anything, and the two
    reach the fan-out down different branches of `_classify`.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]

    if direction == "attach":
        subject = (
            await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
        ).json()
        parent = item["id"]
    else:
        subject = item["kits"][0]
        parent = ""

    line = {
        "id": item["id"],
        "order_id": order["id"],
        "item_type": "kit",
        "unit_price_minor": "3000" if restated else "2800",
        "currency_code": "JPY",
    }
    content = archive(
        {
            "order_items": ["id", "order_id", "item_type", "unit_price_minor", "currency_code"],
            "kits": ["id", "name", "grade", "order_item_id"],
        },
        order_items=[line],
        kits=[
            {"id": subject["id"], "name": subject["name"], "grade": "HG", "order_item_id": parent}
        ],
    )
    plan = await preview(client, content)
    assert actions(plan, "kits") == ["error"], plan["tables"]
    # The stored quantity is what the line still says, so the refusal reports both
    # numbers rather than pleading ignorance — the sheet's silence doesn't erase it.
    error = plan["tables"][-1]["rows"][0]["error"]
    assert "while the line says it bought 1" in error, error
    assert (await apply(client, content)).status_code == 409

    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert (stored["quantity"], len(stored["kits"])) == (1, 1), "nothing moved"


async def test_a_kit_moved_onto_a_new_line_that_states_no_quantity_is_refused(client):
    """The branch where *nothing* knows the quantity: the line is created by this
    upload and its sheet has no `quantity` column, so there is no stored row to
    fall back on either.

    Reachable, and worth refusing rather than letting through: `quantity` is NOT
    NULL, so the row would otherwise reach the database as a null and come back as
    a 500 rather than a named row (rule 6).
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    loose = (
        await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
    ).json()
    new_line = "5c1d77aa-9e02-4b31-8a44-2f0016cc9d10"

    content = archive(
        {
            "order_items": ["id", "order_id", "item_type", "unit_price_minor", "currency_code"],
            "kits": ["id", "name", "grade", "order_item_id"],
        },
        order_items=[
            {
                "id": new_line,
                "order_id": order["id"],
                "item_type": "kit",
                "unit_price_minor": "2500",
                "currency_code": "JPY",
            }
        ],
        kits=[{"id": loose["id"], "name": "Gouf", "grade": "HG", "order_item_id": new_line}],
    )
    plan = await preview(client, content)
    # Refused on the *line*, not on the kit that would have moved onto it. #82/#88
    # landed a create rule that reaches this first: a new order line with no
    # quantity has nothing to fall back on, so the column it needs is named
    # directly rather than through the downstream consequence. Better diagnosis,
    # same outcome — nothing moves. #44's own "nothing states the quantity" branch
    # is still exercised by `test_a_line_row_carrying_no_quantity_authorises_no_
    # reconciliation`, where the line is an update and the stored quantity applies.
    lines_plan = next(t for t in plan["tables"] if t["table"] == "order_items")
    assert [r["action"] for r in lines_plan["rows"]] == ["error"], plan["tables"]
    assert lines_plan["rows"][0]["error"].startswith("quantity:")
    assert (await apply(client, content)).status_code == 409
    assert (await client.get(f"/kits/{loose['id']}")).json()["order_item_id"] is None


@pytest.mark.parametrize(
    ("item_type", "quantity"),
    [
        # A catalog line: caught by the provenance rule, which reads the uploaded
        # row and never consults a stored one.
        ("consumable", "1"),
        # A kit line stating no quantity: this one *does* reach the stored lookup,
        # for its quantity and its kits, and is the reason the mode guard is
        # load-bearing. Found by mutation testing — the consumable case alone
        # stayed green with the guard removed, because it errors earlier.
        ("kit", None),
    ],
    ids=["catalog line", "kit line with no quantity"],
)
async def test_a_replace_all_plan_does_not_depend_on_rows_it_will_truncate(
    client, item_type, quantity
):
    """Rule #45, reached through the new refusal (external review of #86, round two).

    A non-kit line leaves the fan-out *before* it is marked reconciled, so an
    upload reusing a stored kit line's uuid for a consumable line fell through to
    a `by_id` lookup — rows `TRUNCATE` is about to remove — and counted their kits.
    The same upload previewed as two errors with the stored order present and
    cleanly without it.

    Asserted as the invariant rather than as a verdict: whatever `replace_all`
    decides about an upload, it has to decide the same thing about it in an empty
    instance and a populated one, because everything the stored rows say is about
    to stop being true.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    line_id = order["items"][0]["id"]
    paint = "aaaaaaaa-0000-4000-8000-000000000001"

    headers = {"kits": ["name", "grade", "order_item_id"]}
    if quantity is None:
        # Genuinely absent, not a blank cell: a blank one is "quantity is required"
        # and errors the line row for an unrelated reason, which would leave the
        # path this case exists for unexercised.
        headers["order_items"] = [
            "id",
            "order_id",
            "item_type",
            "unit_price_minor",
            "currency_code",
            "kit_name",
            "kit_grade",
        ]
    content = archive(
        headers,
        retailers=[{"id": retailer["id"], "name": "Hobby Link Japan"}],
        consumables=[{"id": paint, "name": "Paint", "category": "paint", "quantity_on_hand": "0"}],
        orders=[
            {
                "id": order["id"],
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
            }
        ],
        order_items=[
            {
                "id": line_id,  # the stored kit line's uuid, reused by this upload
                "order_id": order["id"],
                "item_type": item_type,
                "catalog_ref_id": paint if item_type == "consumable" else "",
                **({"quantity": quantity} if quantity else {}),
                "unit_price_minor": "500",
                "currency_code": "JPY",
                "kit_name": "Gouf" if item_type == "kit" else "",
                "kit_grade": "HG" if item_type == "kit" else "",
            }
        ],
        kits=[
            {"name": "A", "grade": "HG", "order_item_id": line_id},
            {"name": "B", "grade": "HG", "order_item_id": line_id},
        ],
    )

    with_stored = await preview(client, content, mode="replace_all")
    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    without_stored = await preview(client, content, mode="replace_all")

    # The whole row diagnosis, not just the action: a stored row can change *which*
    # error is reported while leaving the count of them the same.
    def kit_errors(plan):
        return [r["error"] for r in next(t for t in plan["tables"] if t["table"] == "kits")["rows"]]

    assert kit_errors(with_stored) == kit_errors(without_stored), (
        "the plan changed with rows this mode is about to truncate"
    )
    assert actions(with_stored, "kits") == actions(without_stored, "kits")
    assert actions(without_stored, "kits") == ["error", "error"], without_stored["tables"]


async def test_a_kit_cannot_take_its_provenance_from_a_catalog_line(client):
    """`kits.order_item_id` records which order line bought the kit, and a paint
    line never bought one (external review of #86, round two).

    §3.9 gives catalog lines a different dispatch entirely — they move
    `quantity_on_hand`, they don't own kits — and neither REST nor MCP exposes any
    way to write this column, so the importer was the only writer in the
    application that could attach a kit to a consumable. The first cut of the
    kit-move refusal skipped non-kit lines explicitly, which is what left the route
    open.

    Both row actions, because the structure differs: an UPDATE moves an existing
    kit's provenance, a CREATE mints one already holding it.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [consumable_line(consumable["id"], quantity=1)])
    line_id = order["items"][0]["id"]
    loose = (
        await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
    ).json()

    content = sheet(
        "kits",
        ["id", "name", "grade", "order_item_id"],
        [
            {"id": loose["id"], "name": "Gouf", "grade": "HG", "order_item_id": line_id},
            {"id": "", "name": "Zaku II", "grade": "HG", "order_item_id": line_id},
        ],
    )
    plan = await preview(client, content, filename="kits.csv")
    assert actions(plan, "kits") == ["error", "error"], plan["tables"]
    error = plan["tables"][0]["rows"][0]["error"]
    assert "is a consumable line" in error
    assert "Point these kits at a kit line" in error, "the refusal has to name the fix"

    assert (await apply(client, content, filename="kits.csv")).status_code == 409
    kits = (await client.get("/kits")).json()
    assert [k["id"] for k in kits if k["order_item_id"] == line_id] == []
    assert (await client.get(f"/kits/{loose['id']}")).json()["order_item_id"] is None


async def test_a_refused_move_contributes_no_planned_removal(client):
    """The preview is binding (#41), so a destructive effect derived from a move
    that will be refused cannot appear in it (external review of #86, round two).

    The fan-out ran before the refusal, so it saw the move, found the destination
    over-supplied, and planned to delete the destination's own kit. The refusal
    then errored the move — because the *source* line would be left empty — and the
    removal stayed in the plan: `kits_removed: 1` on a preview whose apply 409s and
    removes nothing.

    Fixed by ordering rather than by cleanup: the refusal runs first, so an errored
    kits row is already out of `_attached_after` and the surplus never exists.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    source = await make_order(client, retailer, [kit_line(1, name="First")], number="A")
    dest = await make_order(client, retailer, [kit_line(1, name="Second")], number="B")
    moving = source["items"][0]["kits"][0]["id"]
    loose = (
        await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
    ).json()

    # The destination writes its quantity up to two, so it *is* reconciled, and two
    # kits arrive: the loose one legitimately, the source's one leaving its line
    # empty. Fan-out first would count three for two places and plan to delete the
    # destination's own kit; refusal first takes the bad move out and the count is
    # exactly right.
    target = dest["items"][0]["id"]
    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        order_items=[line_row(dest, dest["items"][0], quantity="2", kit_name="Second")],
        kits=[
            {"id": moving, "name": "First", "grade": "HG", "order_item_id": target},
            {"id": loose["id"], "name": "Gouf", "grade": "HG", "order_item_id": target},
        ],
    )
    plan = await preview(client, content)
    assert plan["blocking_errors"], "the source line would be left empty"
    assert plan["derived"]["kits_removed"] == 0, "a refused move deletes nothing"

    assert (await apply(client, content)).status_code == 409
    assert len((await client.get("/kits")).json()) == 3


async def test_a_move_onto_a_reconciled_line_may_still_leave_a_shortfall_to_spawn(client):
    """Why the refusal yields to a line that states its own quantity, rather than
    checking every line it can reach.

    A move onto a line whose quantity is *higher* than the resulting count is not a
    contradiction — it is a shortfall, and filling shortfalls is what the fan-out
    is for. Checking the count here regardless would refuse a legitimate spawn.
    Found by mutation testing: the sibling test below happens to land on a count
    that matches, so with the `reconciled` skip removed it stayed green and nothing
    pinned the difference.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]
    loose = (
        await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
    ).json()

    # Quantity 3, one kit already on the line, one moved on: a shortfall of one.
    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        order_items=[line_row(order, item, quantity="3")],
        kits=[{"id": loose["id"], "name": "Gouf", "grade": "HG", "order_item_id": item["id"]}],
    )
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert plan["derived"]["kits_spawned"] == 1, plan["derived"]
    assert plan["derived"]["kits_removed"] == 0, plan["derived"]

    assert (await apply(client, content)).status_code == 200
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert stored["quantity"] == 3
    assert len(stored["kits"]) == 3
    assert loose["id"] in {k["id"] for k in stored["kits"]}


@pytest.mark.parametrize(
    ("progressed_before", "destination"),
    [
        # Already protected in the database, detached to nothing.
        (True, "detach"),
        # Protected by this same upload — the row that promotes it to `building` is
        # the row that strips its provenance, so a check reading stored evidence
        # alone sees an ordinary kit.
        (False, "detach"),
        # Moved to another line rather than cleared: the guard follows the kit and
        # the original order becomes deletable just the same.
        (True, "another line"),
    ],
    ids=["already protected", "protected by this upload", "moved to another line"],
)
async def test_a_count_preserving_swap_cannot_strip_protected_provenance(
    client, progressed_before, destination
):
    """A swap satisfies the count check perfectly — one kit out, one in — while the
    kit that leaves takes its purchase record with it (external review of #86,
    round three).

    That record is what `delete_order` reads to refuse, so an order holding a
    `building` kit went from a 409 before the import to a **204** after it. The
    count was never wrong; the thing being protected isn't the count.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    other = await make_order(client, retailer, [kit_line(1, name="Gouf")], number="HLJ-2")
    item = order["items"][0]
    kit = item["kits"][0]

    if progressed_before:
        assert (
            await client.patch(f"/kits/{kit['id']}", json={"status": "building"})
        ).status_code == 200
        assert (await client.delete(f"/orders/{order['id']}")).status_code == 409, (
            "the Orders page has to be refusing already, or this proves nothing"
        )

    parent = other["items"][0]["id"] if destination == "another line" else ""
    content = sheet(
        "kits",
        ["id", "name", "grade", "status", "order_item_id"],
        [
            {
                "id": kit["id"],
                "name": "Zaku II",
                "grade": "HG",
                "status": "building",
                "order_item_id": parent,
            },
            {
                "id": "",
                "name": "Replacement",
                "grade": "HG",
                "status": "ordered",
                "order_item_id": item["id"],
            },
        ],
    )
    plan = await preview(client, content, filename="kits.csv")
    assert plan["blocking_errors"], plan["tables"]
    assert plan["tables"][0]["rows"][0]["error"].startswith("order_item_id:")
    assert (await apply(client, content, filename="kits.csv")).status_code == 409

    stored = (await client.get(f"/kits/{kit['id']}")).json()
    assert stored["order_item_id"] == item["id"], "the link survived"
    if progressed_before:
        # Only meaningful where the kit was already protected: in the other
        # variant the promotion to `building` was part of the refused upload, so
        # the kit is still `ordered` and the order is legitimately deletable. What
        # that variant proves is that the *upload's own* evidence counted.
        assert (await client.delete(f"/orders/{order['id']}")).status_code == 409, (
            "and the order is still protected by it"
        )


async def test_a_protected_kit_cannot_be_moved_even_when_both_counts_work_out(client):
    """The provenance rule standing on its own.

    The variant above moves a protected kit to a line whose quantity it then
    breaks, so the *count* check refuses it and the provenance rule is never the
    thing deciding — mutating the provenance rule to ignore moves left that test
    green. Here both lines are restated so every count balances: the source gets a
    replacement, the destination's quantity rises to take the arrival. Nothing is
    numerically wrong anywhere, and the move must still be refused, because what
    is being protected is the link and not the arithmetic.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    source = await make_order(client, retailer, [kit_line(1)], number="HLJ-1")
    dest = await make_order(client, retailer, [kit_line(1, name="Gouf")], number="HLJ-2")
    src_line, dst_line = source["items"][0], dest["items"][0]
    kit = src_line["kits"][0]

    assert (
        await client.patch(f"/kits/{kit['id']}", json={"status": "building"})
    ).status_code == 200
    assert (await client.delete(f"/orders/{source['id']}")).status_code == 409

    # Both lines *write* their quantity, so both are reconciled by the fan-out and
    # every count balances: the source goes to two and gets two new kits, the
    # destination goes to two and takes the arrival. Without the provenance rule
    # this upload is clean.
    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        order_items=[
            line_row(source, src_line, quantity="2"),
            line_row(dest, dst_line, quantity="2", kit_name="Gouf"),
        ],
        kits=[
            {"id": kit["id"], "name": "Zaku II", "grade": "HG", "order_item_id": dst_line["id"]},
            {"id": "", "name": "Zaku II", "grade": "HG", "order_item_id": src_line["id"]},
            {"id": "", "name": "Zaku II", "grade": "HG", "order_item_id": src_line["id"]},
        ],
    )
    plan = await preview(client, content)
    kits_plan = next(t for t in plan["tables"] if t["table"] == "kits")
    moved_row = next(r for r in kits_plan["rows"] if r["matched_id"] == kit["id"])
    assert moved_row["action"] == "error", plan["tables"]
    assert "building or complete" in moved_row["error"], moved_row["error"]
    assert (await apply(client, content)).status_code == 409

    assert (await client.get(f"/kits/{kit['id']}")).json()["order_item_id"] == src_line["id"]
    assert (await client.delete(f"/orders/{source['id']}")).status_code == 409


async def test_an_unprotected_kit_can_still_be_swapped(client):
    """The refusal is about progression, not about `order_item_id` — a kit nobody
    has touched still moves, so this doesn't become a blanket ban on the column."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]
    kit = item["kits"][0]

    content = sheet(
        "kits",
        ["id", "name", "grade", "status", "order_item_id"],
        [
            {
                "id": kit["id"],
                "name": "Zaku II",
                "grade": "HG",
                "status": "ordered",
                "order_item_id": "",
            },
            {
                "id": "",
                "name": "Replacement",
                "grade": "HG",
                "status": "ordered",
                "order_item_id": item["id"],
            },
        ],
    )
    plan = await preview(client, content, filename="kits.csv")
    assert plan["blocking_errors"] == [], plan
    assert (await apply(client, content, filename="kits.csv")).status_code == 200

    stored = (await client.get(f"/kits/{kit['id']}")).json()
    assert stored["order_item_id"] is None
    line = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert [k["name"] for k in line["kits"]] == ["Replacement"]


@pytest.mark.parametrize("child", ["upgrade_applications", "kit_photos"])
async def test_a_child_this_upload_creates_protects_its_kit_from_removal(client, child):
    """Progression evidence the upload is *writing*, not evidence already stored
    (external review of #86, round three).

    `_plan_removals` picked the newest kit, and the same upload created an upgrade
    application or a photo for exactly that kit: the child was written during the
    table loop and the foreign-key cascade erased it with its kit moments later.
    The result counted a create a later export could not find — and for an
    application, that is consumed upgrade stock with nothing left to explain it.

    The other kit is still safe, so the fix is to remove *that* one rather than to
    refuse: the reduction the operator asked for still happens.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]
    oldest, newest = (k["id"] for k in item["kits"])

    tables = {"order_items": [line_row(order, item, quantity="1")]}
    if child == "upgrade_applications":
        upgrade = (
            await client.post(
                "/upgrades", json={"name": "Thruster", "manufacturer": "K", "quantity_on_hand": 5}
            )
        ).json()
        tables["upgrades"] = [
            {"id": upgrade["id"], "name": "Thruster", "manufacturer": "K", "quantity_on_hand": "5"}
        ]
        tables["upgrade_applications"] = [
            {"upgrade_id": upgrade["id"], "kit_id": newest, "quantity_used": "1"}
        ]
    else:
        tables["kit_photos"] = [{"kit_id": newest, "file_path": "shots/a.jpg"}]

    content = archive(**tables)
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert plan["derived"]["kits_removed"] == 1, plan["derived"]
    assert (await apply(client, content)).status_code == 200

    survivors = {k["id"] for k in (await client.get("/kits")).json()}
    assert newest in survivors, "the kit this upload gave a child to has to survive"
    assert oldest not in survivors, "the safe kit is the one that goes"

    if child == "upgrade_applications":
        # kit_photos is exported empty on purpose until Milestone 7, so only the
        # application can be checked end to end — and it is the half that matters,
        # because it explains where upgrade stock went.
        exported = read_archive((await client.get("/export/archive")).content)
        assert len(exported["upgrade_applications"]) == 1, "created, then cascaded away"


CHILD_HEADERS = {
    # Narrowed past `applied_at` / `created_at`: both are NOT NULL, and a blank
    # cell in either is #88's 500, which has nothing to do with these cases.
    "upgrade_applications": ["id", "upgrade_id", "kit_id", "quantity_used"],
    "kit_photos": ["id", "kit_id", "file_path"],
}


async def _seed_child(client, table, kit_id):
    """An existing child row on `kit_id`, and the ids needed to move it later."""
    if table == "upgrade_applications":
        upgrade = (
            await client.post(
                "/upgrades", json={"name": "Thruster", "manufacturer": "K", "quantity_on_hand": 4}
            )
        ).json()
        applied = (
            await client.post(
                f"/upgrades/{upgrade['id']}/apply", json={"kit_id": kit_id, "quantity": 1}
            )
        ).json()
        return {"id": applied["id"], "upgrade_id": upgrade["id"], "quantity_used": "1"}

    photo_id = "b17c0a4e-9d33-4a51-8f60-2ee9c1130044"
    seed = sheet(
        "kit_photos",
        ["id", "kit_id", "file_path"],
        [{"id": photo_id, "kit_id": kit_id, "file_path": "shots/a.jpg"}],
    )
    assert (await apply(client, seed, filename="kit_photos.csv")).status_code == 200
    return {"id": photo_id, "file_path": "shots/a.jpg"}


@pytest.mark.parametrize("table", ["upgrade_applications", "kit_photos"])
async def test_a_child_this_upload_moves_protects_the_kit_it_arrives_on(client, table):
    """A child row does not have to be *created* to be evidence (external review of
    #86, round four).

    `upgrade_applications.kit_id` and `kit_photos.kit_id` are ordinary REF columns,
    so an update can carry an existing child from one kit to another — and the kit
    it lands on gains exactly what a create would have given it. Reading `CREATE`
    alone let that arrival be picked as the removal victim: the child moved onto it
    and was cascaded away with it, so an upgrade's stock stayed spent with no
    application left anywhere to explain it.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]
    oldest, newest = (k["id"] for k in item["kits"])
    spare = (
        await client.post("/kits", json={"name": "Spare", "grade": "HG", "status": "backlog"})
    ).json()
    child = await _seed_child(client, table, spare["id"])

    content = archive(
        CHILD_HEADERS,
        order_items=[line_row(order, item, quantity="1")],
        **{table: [{**child, "kit_id": newest}]},
    )
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert actions(plan, table) == ["update"], plan["tables"]
    assert plan["derived"]["kits_removed"] == 1, plan["derived"]
    assert (await apply(client, content)).status_code == 200

    survivors = {k["id"] for k in (await client.get("/kits")).json()}
    assert newest in survivors, "the kit the child moved onto has to survive"
    assert oldest not in survivors, "the safe kit is the one that goes"

    if table == "upgrade_applications":
        exported = read_archive((await client.get("/export/archive")).content)
        assert len(exported["upgrade_applications"]) == 1, "moved, not cascaded away"
        assert exported["upgrade_applications"][0]["kit_id"] == newest


async def test_a_child_this_upload_moves_also_protects_that_kits_provenance(client):
    """The same omission defeated the other consumer. A kit gaining a moved
    application is protected, so the swap that would strip its purchase link is
    refused — the count still balances, and the link is not the count."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]
    kit = item["kits"][0]["id"]
    spare = (
        await client.post("/kits", json={"name": "Spare", "grade": "HG", "status": "backlog"})
    ).json()
    child = await _seed_child(client, "upgrade_applications", spare["id"])

    content = archive(
        {**CHILD_HEADERS, "kits": ["id", "name", "grade", "order_item_id"]},
        upgrade_applications=[{**child, "kit_id": kit}],
        kits=[
            {"id": kit, "name": "Zaku II", "grade": "HG", "order_item_id": ""},
            {"id": "", "name": "Replacement", "grade": "HG", "order_item_id": item["id"]},
        ],
    )
    plan = await preview(client, content)
    assert plan["blocking_errors"], plan["tables"]
    assert (await apply(client, content)).status_code == 409
    assert (await client.get(f"/kits/{kit}")).json()["order_item_id"] == item["id"]


@pytest.mark.parametrize("mode", ["merge", "add_only", "replace_all"], ids=lambda m: m)
async def test_a_line_this_upload_creates_cannot_be_over_supplied_either(client, mode):
    """The action axis of over-supply (external review of #86, round four).

    `test_a_line_cannot_be_over_supplied_by_the_uploads_own_kits` drives an
    *existing* line, where the surplus is measured against stored kits. On a line
    the upload creates there are none, and `_plan_removals` returned before saying
    anything at all — so a quantity-one line landed holding two kits, in every
    mode. There is nothing to remove here and nothing stored to blame: the file
    contradicts itself, and that is what the refusal has to say.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1, name="Existing")])
    new_line = "7a1c0e55-3b90-4f22-9d81-6c22aa0e1177"

    tables = {
        "order_items": [
            {
                "id": new_line,
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "unit_price_minor": "2500",
                "currency_code": "JPY",
                "kit_name": "New",
                "kit_grade": "HG",
            }
        ],
        "kits": [
            {"name": "K1", "grade": "HG", "order_item_id": new_line},
            {"name": "K2", "grade": "HG", "order_item_id": new_line},
        ],
    }
    if mode == "replace_all":
        tables["retailers"] = [{"id": retailer["id"], "name": "Hobby Link Japan"}]
        tables["orders"] = [
            {
                "id": order["id"],
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
            }
        ]

    content = archive({"kits": ["name", "grade", "order_item_id"]}, **tables)
    plan = await preview(client, content, mode=mode)
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    lines_plan = next(t for t in plan["tables"] if t["table"] == "order_items")
    error = next(r for r in lines_plan["rows"] if r["error"])["error"]
    assert "this upload supplies 2 kit(s)" in error, error

    extra = {"confirm": "REPLACE"} if mode == "replace_all" else {}
    assert (await apply(client, content, mode=mode, **extra)).status_code == 409
    lines = [i for o in (await client.get("/orders")).json() for i in o["items"]]
    assert not any(i["id"] == new_line for i in lines), "nothing was created"


async def test_a_reduction_is_refused_when_every_candidate_gains_a_child(client):
    """The other end of the same rule: with both kits protected by children this
    upload creates, there is nothing safe to remove and the reduction is refused
    rather than resolved by picking a victim anyway."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]

    content = archive(
        order_items=[line_row(order, item, quantity="1")],
        kit_photos=[
            {"kit_id": k["id"], "file_path": f"shots/{i}.jpg"} for i, k in enumerate(item["kits"])
        ],
    )
    plan = await preview(client, content)
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    assert "can be removed safely" in plan["tables"][0]["rows"][0]["error"]
    assert (await apply(client, content)).status_code == 409
    assert len((await client.get("/kits")).json()) == 2


async def test_a_kit_move_the_upload_does_reconcile_is_still_allowed(client):
    """The other side of that refusal: state the line's quantity in the same upload
    and the move lands, because now the file has said both halves out loud. This is
    what keeps the refusal from being a blanket ban on `order_item_id`."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]

    content = archive(
        {"kits": ["name", "grade", "order_item_id"]},
        order_items=[line_row(order, item, quantity="2")],
        kits=[{"name": "Extra", "grade": "HG", "order_item_id": item["id"]}],
    )
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert (await apply(client, content)).status_code == 200

    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert stored["quantity"] == 2
    assert len(stored["kits"]) == 2


async def test_a_kit_arriving_from_another_line_is_not_the_one_given_up(client):
    """The two halves meeting: one upload moves a kit onto a line *and* reduces that
    line below what it can then hold. The arriving kit is described by the upload, so
    it is never a removal candidate — the surplus has to come from the kits already
    there, and be reported when it can't."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(3)])
    item = order["items"][0]
    incumbents = [k["id"] for k in item["kits"]]
    loose = (
        await client.post("/kits", json={"name": "Gouf", "grade": "HG", "status": "backlog"})
    ).json()

    # Three on the line, one arriving, quantity written down to two: four kits for
    # two places, and the arrival is never a candidate.
    content = archive(
        {"kits": ["id", "name", "grade", "order_item_id"]},
        order_items=[line_row(order, item, quantity="2")],
        kits=[{"id": loose["id"], "name": "Gouf", "grade": "HG", "order_item_id": item["id"]}],
    )
    plan = await preview(client, content)
    assert plan["derived"]["kits_removed"] == 2, plan["derived"]
    assert (await apply(client, content)).status_code == 200

    surviving = {k["id"] for k in (await client.get("/kits")).json()}
    assert loose["id"] in surviving, "the upload said this kit is on the line"
    assert surviving & set(incumbents) == {incumbents[0]}, "two incumbents gave way, newest first"


async def test_a_replace_all_import_reconciles_nothing_downward(client):
    """Every row is a create and every stored kit is truncated first, so `existing`
    is zero by construction — there is no surplus to find, and a removal planned
    against a row about to be truncated would be a delete of a row that no longer
    exists."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]

    content = archive(
        retailers=[{"id": retailer["id"], "name": "Hobby Link Japan"}],
        orders=[order_row(order, retailer)],
        order_items=[line_row(order, item, quantity="1")],
    )
    plan = await preview(client, content, mode="replace_all")
    assert plan["derived"]["kits_removed"] == 0, plan["derived"]
    assert plan["blocking_errors"] == [], plan

    resp = await apply(client, content, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_removed"] == 0
    assert len(await kit_states(client)) == 1, "one kit, spawned fresh by the line"


async def test_an_add_only_import_reconciles_nothing_downward(client):
    """`add_only` leaves every matched row exactly as it is (SKIP), so a quantity
    it would have reduced never lands — and a removal derived from a quantity that
    isn't being written would delete kits on the strength of a cell the import is
    ignoring."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(2)])
    item = order["items"][0]

    content = archive(order_items=[line_row(order, item, quantity="1")])
    plan = await preview(client, content, mode="add_only")
    assert actions(plan, "order_items") == ["skip"], plan["tables"]
    assert plan["derived"]["kits_removed"] == 0, plan["derived"]

    resp = await apply(client, content, mode="add_only")
    assert resp.status_code == 200, resp.text
    assert len(await kit_states(client)) == 2


async def test_a_planned_removal_hashes_stably_and_moves_with_its_kits(client):
    """Two previews of one file agree, and a removal set that changes changes the
    hash. `rows_deleted` learned this the hard way: two collections of the same
    size are the same number and a different loss."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(3)])
    item = order["items"][0]

    content = archive(order_items=[line_row(order, item, quantity="2")])
    first = await preview(client, content)
    second = await preview(client, content)
    assert first["plan_hash"] == second["plan_hash"], "a removal moved the hash on its own"

    # Take the kit the plan was going to remove out of reach: the surviving plan
    # removes a different kit, for the same count.
    newest = item["kits"][-1]["id"]
    assert (await client.patch(f"/kits/{newest}", json={"status": "building"})).status_code == 200
    third = await preview(client, content)
    assert third["derived"]["kits_removed"] == 1
    assert third["plan_hash"] != first["plan_hash"], "which kit goes is part of the plan"


# --- receipt: the transitions, and what each does to stock -----------------------
#
# REST and import differ here on purpose, so this axis asserts behaviour rather
# than agreement. The variables are the transition (`unreceived -> received`,
# `received -> unreceived`, and a correction between two non-null timestamps) and
# whether the order holds a line that moves stock.


@pytest.fixture
async def catalog_order(client):
    """A pending order with one consumable line — the shape whose receipt carries
    accounting. Stock starts at zero and the line is for three."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [consumable_line(consumable["id"])])
    return {"retailer": retailer, "consumable": consumable, "order": order}


@pytest.fixture
async def kit_order(client):
    """The starter-sheet shape: kits only, nothing that moves stock."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    return {"retailer": retailer, "order": order}


async def test_an_import_cannot_receive_an_order_that_would_have_moved_stock(client, catalog_order):
    """Case 4's first hole. The transition is refused rather than represented: the
    only thing that could tell "received" from "received, stock outstanding" is a
    column, and `received_at is not None` is the proxy for "stock was applied" in
    four separate stock mutators.

    All three consequences are asserted, not just the 409 the issue documents —
    they are what makes this worth refusing rather than tolerating.
    """
    order, consumable = catalog_order["order"], catalog_order["consumable"]
    content = archive(
        orders=[order_row(order, catalog_order["retailer"], received_at="2026-03-20T00:00:00Z")]
    )

    plan = await preview(client, content)
    assert actions(plan, "orders") == ["error"], plan["tables"]
    error = plan["tables"][0]["rows"][0]["error"]
    assert error.startswith("received_at:")
    # The refusal has to name a fix that works. It once offered "state the on-hand
    # quantity in consumables.csv" as one, and that is not a fix for *this*
    # refusal — the check never reads the catalog files, so an upload that states
    # the count and flips received_at is refused again with the same message
    # (driven below). The remedy that exists is the app's receive.
    assert "receive the order in the app" in error, error
    assert "consumables.csv" in error and "doesn't stand in" in error, error
    assert (await apply(client, content)).status_code == 409

    # Following the retired remedy to the letter — count stated in the same
    # upload — must still be refused, or the message above is lying the other way.
    with_count = archive(
        orders=[order_row(order, catalog_order["retailer"], received_at="2026-03-20T00:00:00Z")],
        consumables=[
            {
                "id": consumable["id"],
                "name": consumable["name"],
                "category": "paint",
                "quantity_on_hand": "3",
            }
        ],
    )
    assert actions(await preview(client, with_count), "orders") == ["error"]
    assert (await apply(client, with_count)).status_code == 409
    assert await stock_of(client, consumable["id"]) == 0, "nothing landed, the count included"

    stored = (await client.get(f"/orders/{order['id']}")).json()
    assert stored["received_at"] is None

    # 1. the real receive still works, and applies the stock
    assert (await client.post(f"/orders/{order['id']}/receive")).status_code == 200
    assert await stock_of(client, consumable["id"]) == 3
    # 2. an edit moves stock by the real difference, not from a phantom zero
    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [rest_line(order["items"][0], quantity=5)]},
    )
    assert resp.status_code == 200, resp.text
    assert await stock_of(client, consumable["id"]) == 5
    # 3. and the order is still deletable
    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    assert await stock_of(client, consumable["id"]) == 0


async def test_an_import_cannot_un_receive_an_order_whose_stock_was_applied(client, catalog_order):
    """Case 4's second and most severe hole: clearing `received_at` left the stock
    the receive applied exactly where it was and re-armed `receive_order`, so a
    second receive counted the same delivery twice. Silent, and only visible as a
    number that is quietly wrong."""
    order, consumable = catalog_order["order"], catalog_order["consumable"]
    assert (await client.post(f"/orders/{order['id']}/receive")).status_code == 200
    assert await stock_of(client, consumable["id"]) == 3

    received = (await client.get(f"/orders/{order['id']}")).json()
    content = archive(orders=[order_row(received, catalog_order["retailer"], received_at="")])

    plan = await preview(client, content)
    assert actions(plan, "orders") == ["error"], plan["tables"]
    error = plan["tables"][0]["rows"][0]["error"]
    assert "add it a second time" in error
    # The remedy has to be one that exists. There is no un-receive anywhere —
    # `OrderUpdate` has no `received_at` — so this refusal removes the only route
    # there ever was, and a message offering only "correct the count in
    # consumables.csv" would be answering a question the operator didn't ask.
    assert "isn't supported anywhere" in error
    assert "delete the order" in error
    assert (await apply(client, content)).status_code == 409

    assert (await client.get(f"/orders/{order['id']}")).json()["received_at"] is not None
    assert (await client.post(f"/orders/{order['id']}/receive")).status_code == 409
    assert await stock_of(client, consumable["id"]) == 3


async def test_a_correction_between_two_timestamps_is_not_a_transition(client, catalog_order):
    """The third state on the axis, and the one a naive "is it non-null now" check
    cannot tell from an arrival. Nothing about the accounting changes when a
    received order's timestamp is corrected, so it stays importable — on a catalog
    order, where both other transitions are refused."""
    order, consumable = catalog_order["order"], catalog_order["consumable"]
    assert (await client.post(f"/orders/{order['id']}/receive")).status_code == 200
    received = (await client.get(f"/orders/{order['id']}")).json()

    content = archive(
        orders=[order_row(received, catalog_order["retailer"], received_at="2026-04-01T00:00:00Z")]
    )
    plan = await preview(client, content)
    assert actions(plan, "orders") == ["update"], plan["tables"]
    assert plan["blocking_errors"] == []
    assert (await apply(client, content)).status_code == 200

    stored = (await client.get(f"/orders/{order['id']}")).json()
    assert stored["received_at"] != received["received_at"]
    assert await stock_of(client, consumable["id"]) == 3, "corrected, not re-applied"


@pytest.mark.parametrize("received_at", ["2026-03-20T00:00:00Z", ""], ids=["receive", "clear"])
async def test_a_kit_only_order_still_moves_in_both_directions(client, kit_order, received_at):
    """#79's reviewed behaviour, which the refusal must not regress. Nothing on
    this order ever moved stock, so neither direction can leave stock unaccounted
    for — and receipt arriving by import is the starter sheet's normal case, not
    an anomaly."""
    order = kit_order["order"]
    if received_at == "":
        assert (await client.post(f"/orders/{order['id']}/receive")).status_code == 200
        order = (await client.get(f"/orders/{order['id']}")).json()

    content = archive(orders=[order_row(order, kit_order["retailer"], received_at=received_at)])
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert actions(plan, "orders") == ["update"], plan["tables"]

    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    stored = (await client.get(f"/orders/{order['id']}")).json()
    assert (stored["received_at"] is not None) == bool(received_at)


async def test_a_catalog_line_this_upload_adds_counts_against_the_transition(client, kit_order):
    """The state axis the stored order cannot express. A kit-only order transitions
    freely — until the same upload puts a consumable line on it, at which point the
    order it becomes holds stock nobody applied. Reading only `row.target.items`
    reports "kit-only" and lets it through."""
    order = kit_order["order"]
    consumable = await make_consumable(client)

    content = archive(
        orders=[order_row(order, kit_order["retailer"], received_at="2026-03-20T00:00:00Z")],
        order_items=[
            {
                "order_id": order["id"],
                "item_type": "consumable",
                "catalog_ref_id": consumable["id"],
                "quantity": "2",
                "unit_price_minor": "500",
                "currency_code": "JPY",
            }
        ],
    )
    plan = await preview(client, content)
    assert actions(plan, "orders") == ["error"], plan["tables"]
    assert (await apply(client, content)).status_code == 409
    assert (await client.get(f"/orders/{order['id']}")).json()["received_at"] is None


async def test_a_received_order_with_catalog_lines_still_restores_from_an_archive(client):
    """The case the refusal must not catch, in both modes that create rather than
    transition.

    A create is not a transition: the archive carries the order, its lines *and*
    the post-receipt `quantity_on_hand` in `consumables.csv`, and the importer
    writes that number directly (rule 10). That is how `received_at ⟹ stock
    accounted for` already survives a full restore, and refusing it would make
    every archive of a received order unimportable.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [consumable_line(consumable["id"])], received=True)
    assert await stock_of(client, consumable["id"]) == 3

    exported = (await client.get("/export/archive")).content
    for mode, extra in (("replace_all", {"confirm": "REPLACE"}), ("merge", {})):
        plan = await preview(client, exported, mode=mode)
        assert plan["blocking_errors"] == [], f"{mode}: {plan}"
        resp = await apply(client, exported, mode=mode, **extra)
        assert resp.status_code == 200, f"{mode}: {resp.text}"
        assert await stock_of(client, consumable["id"]) == 3, mode
        stored = (await client.get("/orders")).json()[0]
        assert stored["received_at"] is not None, mode
        assert order["order_number"] == stored["order_number"], mode


# --- the receipt instant import-written arrivals inherit --------------------------
#
# Since #93, a kit a receipt lands in backlog is stamped with the order's
# `received_at` — backdated included — by every writer: `receive_order`, entry
# with `received=true`, and a line edit spawning into a received order. The
# importer's two arrival sites (`_advance_kits_for_newly_received_orders` and the
# apply loop's `spawn_kits` call) borrow the same instant. The value is stated in
# the upload or already stored, so rule 10 is not offended: nothing is invented,
# and neither site fires on a re-import (no quantity written, no null -> non-null
# transition). Every RECEIPT below is months in the past precisely so the
# importer's clock cannot produce a passing value by accident.

RECEIPT = "2026-03-20T09:00:00Z"


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def test_a_receipt_arriving_by_import_stamps_the_advance_with_the_stated_instant(
    client, kit_order
):
    """Site one: the kit-only receive-by-import. The advance mirrors
    `receive_order()` (rule 2), and `receive_order` stamps the kits it advances
    with the receipt instant — so the mirror must too, or the same arrival sorts
    differently on the Board depending on which writer recorded it."""
    order = kit_order["order"]
    content = archive(orders=[order_row(order, kit_order["retailer"], received_at=RECEIPT)])
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text

    kit = (await client.get("/kits")).json()[0]
    assert kit["status"] == "backlog"
    assert instant(kit["status_updated_at"]) == instant(RECEIPT)


async def test_a_kit_spawned_into_a_received_order_borrows_its_receipt(client, kit_order):
    """Site two, the update shape: a quantity increase on a received order's line.
    The same edit through REST stamps the new kit with the order's receipt; the
    spawned kit entered the collection when the box did, whichever writer says
    the line got bigger."""
    order = kit_order["order"]
    resp = await client.post(f"/orders/{order['id']}/receive", json={"received_at": RECEIPT})
    assert resp.status_code == 200, resp.text
    before = {k["id"] for k in (await client.get("/kits")).json()}

    content = archive(order_items=[line_row(order, order["items"][0], quantity="2")])
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text

    new = next(k for k in (await client.get("/kits")).json() if k["id"] not in before)
    assert new["status"] == "backlog"
    assert instant(new["status_updated_at"]) == instant(RECEIPT)


async def test_one_upload_that_receives_and_spawns_stamps_both_kits_the_same(client, kit_order):
    """Both sites in one apply, and the ordering seam pinned: the upload flips the
    receipt AND grows the line, so the receipt the spawn borrows exists only in
    the post-write order row — the stored row still says pending when the plan is
    made. The advance stamps the pre-existing kit, the fan-out stamps the new
    one, and both must say the instant the sheet stated, not the clock and not
    the stored null."""
    order = kit_order["order"]
    before = {k["id"] for k in (await client.get("/kits")).json()}
    assert len(before) == 1

    content = archive(
        orders=[order_row(order, kit_order["retailer"], received_at=RECEIPT)],
        order_items=[line_row(order, order["items"][0], quantity="2")],
    )
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text

    kits = (await client.get("/kits")).json()
    assert len(kits) == 2
    for kit in kits:
        assert kit["status"] == "backlog", kit
        assert instant(kit["status_updated_at"]) == instant(RECEIPT), (
            "advanced" if kit["id"] in before else "spawned"
        )


@pytest.mark.parametrize("mode", ["merge", "replace_all"])
@pytest.mark.parametrize(
    ("status_cell", "expected_status", "borrows"),
    [
        # The line states no kit status, so the spawn lands wherever the order
        # says — backlog, carrying the order's receipt.
        ("", "backlog", True),
        # An explicitly asserted later status keeps the entry-time stamp: the
        # receipt is not when "building" began. `spawn_kits` owns that gate for
        # every caller; this drives it through the importer.
        ("building", "building", False),
    ],
    ids=["lands in backlog", "asserted past backlog"],
)
async def test_a_created_received_order_spawns_kits_carrying_its_receipt(
    client, status_cell, expected_status, borrows, mode
):
    """Site two, the create shape, in both modes that create rather than
    transition — a restore is the shape's ordinary case, and `replace_all` is the
    classification where every row is a CREATE. The fan-out runs at apply time,
    after the write loop, so the instant comes from the post-write order row —
    which is exactly what this upload stated."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order_id = "7d9a1c22-4e8b-4f3a-9c1d-2b6e8f4a5d30"
    content = archive(
        {
            "retailers": ["id", "name"],
            "orders": [
                "id",
                "retailer_id",
                "order_date",
                "order_number",
                "currency_code",
                "received_at",
            ],
            "order_items": [
                "id",
                "order_id",
                "item_type",
                "quantity",
                "unit_price_minor",
                "currency_code",
                "kit_name",
                "kit_grade",
                "kit_status",
            ],
        },
        retailers=[{"id": retailer["id"], "name": retailer["name"]}],
        orders=[
            {
                "id": order_id,
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-9",
                "currency_code": "JPY",
                "received_at": RECEIPT,
            }
        ],
        order_items=[
            {
                "id": "3f2b8d11-9a4c-4e7f-8b2a-1c5d9e6f7a48",
                "order_id": order_id,
                "item_type": "kit",
                "quantity": "1",
                "unit_price_minor": "2800",
                "currency_code": "JPY",
                "kit_name": "Gouf",
                "kit_grade": "HG",
                "kit_status": status_cell,
            }
        ],
    )
    extra = {"confirm": "REPLACE"} if mode == "replace_all" else {}
    resp = await apply(client, content, mode=mode, **extra)
    assert resp.status_code == 200, resp.text

    kit = next(k for k in (await client.get("/kits")).json() if k["name"] == "Gouf")
    assert kit["status"] == expected_status
    assert (instant(kit["status_updated_at"]) == instant(RECEIPT)) is borrows


async def test_a_correction_by_import_leaves_kit_stamps_alone(client, kit_order):
    """The declared divergence, pinned. REST's correction path restamps exactly
    the kits whose stamp equals the old receipt (`_restamp_receipt_kits`, #93);
    an import correcting the same date does not — the importer writes only rows
    the upload names plus the two arrival derivations above, and a full archive
    states every kit's stamp explicitly. Filed as #116; if that decision is ever
    reversed, this is the test to flip."""
    order = kit_order["order"]
    resp = await client.post(f"/orders/{order['id']}/receive", json={"received_at": RECEIPT})
    assert resp.status_code == 200, resp.text

    corrected = "2026-04-02T10:00:00Z"
    stored = (await client.get(f"/orders/{order['id']}")).json()
    content = archive(orders=[order_row(stored, kit_order["retailer"], received_at=corrected)])
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text

    assert instant((await client.get(f"/orders/{order['id']}")).json()["received_at"]) == instant(
        corrected
    )
    kit = (await client.get("/kits")).json()[0]
    assert instant(kit["status_updated_at"]) == instant(RECEIPT), (
        "import corrections do not cascade restamps"
    )


# --- a receipt that hasn't happened yet (Codex round five) ------------------------
#
# REST and MCP refuse a future `received_at` at entry, receive and correction —
# `_refuse_future_receipt`, judged as a calendar date in the instant's own offset
# (#93). The importer was the one writer without the check, and once the arrival
# sites borrow the instant, the accepted value became a Board stamp sitting in
# 2099. The refusal reads the *change*, not the cell: a stored future value —
# admitted before the check existed — restates and restores untouched, and a
# create is a restore, not a data-entry path (the §12.5 create rule, applied to
# the date). The predicate itself is shared from `services/orders.py`, so its
# own-offset calendar semantics are #93's tested ground, not re-implemented here.

FUTURE = "2099-01-02T09:00:00Z"


async def test_an_import_cannot_receive_an_order_in_the_future(client, kit_order):
    """Round five's P2, the arrival shape: null → future previewed clean and
    applied at 200, stamping the kit's `status_updated_at` in 2099."""
    order = kit_order["order"]
    content = archive(orders=[order_row(order, kit_order["retailer"], received_at=FUTURE)])
    plan = await preview(client, content)
    assert actions(plan, "orders") == ["error"], plan["tables"]
    error = plan["tables"][0]["rows"][0]["error"]
    assert error.startswith("received_at:")
    assert "future" in error
    assert (await apply(client, content)).status_code == 409

    assert (await client.get(f"/orders/{order['id']}")).json()["received_at"] is None
    kit = (await client.get("/kits")).json()[0]
    assert kit["status"] == "ordered", "no arrival happened, so no advance either"


async def test_an_import_cannot_correct_a_receipt_into_the_future(client, kit_order):
    """The correction shape of the same hole. A correction never moves stock, so
    the receipt-transition refusal is deliberately silent here — this check has
    to speak on its own, on any order."""
    order = kit_order["order"]
    resp = await client.post(f"/orders/{order['id']}/receive", json={"received_at": RECEIPT})
    assert resp.status_code == 200, resp.text
    stored = (await client.get(f"/orders/{order['id']}")).json()

    content = archive(orders=[order_row(stored, kit_order["retailer"], received_at=FUTURE)])
    plan = await preview(client, content)
    assert actions(plan, "orders") == ["error"], plan["tables"]
    assert "future" in plan["tables"][0]["rows"][0]["error"]
    assert (await apply(client, content)).status_code == 409
    assert instant((await client.get(f"/orders/{order['id']}")).json()["received_at"]) == instant(
        RECEIPT
    )


async def test_a_stored_future_receipt_restated_is_still_a_no_op(client, kit_order):
    """The refusal reads the change, not the cell: a legacy future value must
    restate and round-trip untouched, or the archive of an instance that once
    imported one becomes unimportable. Seeded by SQL because the application no
    longer writes one anywhere."""
    order = kit_order["order"]
    async with session_scope() as session:
        await session.execute(
            sa_text("update orders set received_at = :v where id = :id"),
            {"v": instant(FUTURE), "id": order["id"]},
        )
        await session.commit()

    stored = (await client.get(f"/orders/{order['id']}")).json()
    content = archive(orders=[order_row(stored, kit_order["retailer"])])
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert (await apply(client, content)).status_code == 200
    assert instant((await client.get(f"/orders/{order['id']}")).json()["received_at"]) == instant(
        FUTURE
    )


@pytest.mark.parametrize("mode", ["merge", "replace_all"])
async def test_a_created_order_still_restores_a_future_receipt(client, mode):
    """The stated create policy (round five asked for it to be explicit rather
    than accidental): a create is a restore. An archive holding a legacy future
    receipt must restore in both creating modes, and the app itself no longer
    writes one anywhere — entry, receive and correction (REST/MCP) and now
    arrival and correction by import all refuse it. The accepted cost: a
    hand-written CSV can still create a future order, and its kit will sort at
    the Board's top until the date passes."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order_id = "b4c8e1f0-2d5a-4b7c-9e3f-6a1d8c2b5e70"
    content = archive(
        {
            "retailers": ["id", "name"],
            "orders": [
                "id",
                "retailer_id",
                "order_date",
                "order_number",
                "currency_code",
                "received_at",
            ],
            "order_items": [
                "id",
                "order_id",
                "item_type",
                "quantity",
                "unit_price_minor",
                "currency_code",
                "kit_name",
                "kit_grade",
            ],
        },
        retailers=[{"id": retailer["id"], "name": retailer["name"]}],
        orders=[
            {
                "id": order_id,
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-77",
                "currency_code": "JPY",
                "received_at": FUTURE,
            }
        ],
        order_items=[
            {
                "id": "9e2f7a44-1b3c-4d8e-a5f6-0c9b8d7e6f51",
                "order_id": order_id,
                "item_type": "kit",
                "quantity": "1",
                "unit_price_minor": "2800",
                "currency_code": "JPY",
                "kit_name": "Acguy",
                "kit_grade": "HG",
            }
        ],
    )
    extra = {"confirm": "REPLACE"} if mode == "replace_all" else {}
    resp = await apply(client, content, mode=mode, **extra)
    assert resp.status_code == 200, resp.text

    kit = next(k for k in (await client.get("/kits")).json() if k["name"] == "Acguy")
    assert kit["status"] == "backlog"
    assert instant(kit["status_updated_at"]) == instant(FUTURE)


async def test_a_receipt_correction_between_preview_and_apply_stales_the_hash(client, kit_order):
    """Round five's P3. The hash binds what will be written, and a spawned kit's
    stamp is a write — with the instant absent from the spawn descriptor, a
    correction landing between preview and apply produced a kit stamped with a
    value the operator never saw. The instant rides in `_Spawn` and the
    fingerprint now, so the stale apply 409s and a fresh preview stamps the
    corrected value."""
    order = kit_order["order"]
    resp = await client.post(f"/orders/{order['id']}/receive", json={"received_at": RECEIPT})
    assert resp.status_code == 200, resp.text
    content = archive(order_items=[line_row(order, order["items"][0], quantity="2")])
    old_hash = (await preview(client, content))["plan_hash"]

    corrected = "2026-04-02T10:00:00Z"
    resp = await client.patch(f"/orders/{order['id']}", json={"received_at": corrected})
    assert resp.status_code == 200, resp.text

    stale = await apply(client, content, plan_hash=old_hash)
    assert stale.status_code == 409, stale.text
    assert "preview again" in stale.json()["detail"]

    fresh_hash = (await preview(client, content))["plan_hash"]
    assert fresh_hash != old_hash
    before = {k["id"] for k in (await client.get("/kits")).json()}
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    new = next(k for k in (await client.get("/kits")).json() if k["id"] not in before)
    assert instant(new["status_updated_at"]) == instant(corrected)


# --- a catalog line has to point at something ------------------------------------


@pytest.mark.parametrize(
    ("id_cell", "name_cell", "accepted"),
    [
        ("", "", False),  # neither: the line can never move stock, ever
        ("11111111-1111-1111-1111-111111111111", "", False),  # a uuid nothing holds
        ("", "Mr Surfacer 1200", True),  # named: created at 0 on hand, like rule 3's flow
        ("real", "", True),  # the ordinary case
        ("wrong-table", "", False),  # a real uuid, in the wrong catalog
    ],
    ids=["neither", "unknown uuid", "name only", "resolvable", "wrong catalog table"],
)
async def test_a_catalog_line_must_resolve_for_its_own_item_type(
    client, id_cell, name_cell, accepted
):
    """`catalog_ref_id` is polymorphic across three tables, so no foreign key can
    hold it and nothing downstream notices a line pointing nowhere — it can never
    apply stock on receive nor have it reversed on delete. "Wrong catalog table" is
    the value the other four cannot express: a uuid that resolves perfectly, just
    not for this line's type."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    consumable = await make_consumable(client)
    tool = (
        await client.post(
            "/tools", json={"name": "Nippers", "category": "cutting", "quantity_on_hand": 1}
        )
    ).json()

    resolved = {"real": consumable["id"], "wrong-table": tool["id"]}.get(id_cell, id_cell)
    content = archive(
        order_items=[
            {
                "order_id": order["id"],
                "item_type": "consumable",
                "catalog_ref_id": resolved,
                "catalog_name": name_cell,
                "quantity": "2",
                "unit_price_minor": "500",
                "currency_code": "JPY",
            }
        ]
    )
    plan = await preview(client, content)
    resp = await apply(client, content)

    if accepted:
        assert plan["blocking_errors"] == [], plan
        assert resp.status_code == 200, resp.text
        lines = (await client.get(f"/orders/{order['id']}")).json()["items"]
        added = next(line for line in lines if line["item_type"] == "consumable")
        assert added["catalog_ref_id"] is not None
    else:
        assert actions(plan, "order_items") == ["error"], plan["tables"]
        assert "catalog_ref_id:" in plan["tables"][0]["rows"][0]["error"]
        assert resp.status_code == 409
        assert len((await client.get(f"/orders/{order['id']}")).json()["items"]) == 1


async def test_an_update_that_says_nothing_about_the_reference_keeps_it(client):
    """The action axis for the same check. A partial sheet correcting a price on a
    catalog line legitimately omits `catalog_ref_id`, and the stored reference has
    to survive that — asking the question of every row rather than every row that
    *says* something would refuse the commonest partial import there is."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [consumable_line(consumable["id"])])
    item = order["items"][0]

    content = sheet(
        "order_items",
        ["id", "order_id", "item_type", "quantity", "unit_price_minor", "currency_code"],
        [
            {
                "id": item["id"],
                "order_id": order["id"],
                "item_type": "consumable",
                "quantity": "3",
                "unit_price_minor": "650",
                "currency_code": "JPY",
            }
        ],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert plan["blocking_errors"] == [], plan
    resp = await apply(client, content, filename="order_items.csv")
    assert resp.status_code == 200, resp.text

    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert stored["catalog_ref_id"] == consumable["id"]
    assert stored["unit_price_minor"] == 650


async def test_a_mistyped_reference_on_a_stored_catalog_line_keeps_the_stored_one(client):
    """The third value in this neighbourhood: not omitted, not blank, but an id that
    resolves to nothing, on a line that already points somewhere. #82 would null it
    and say the row imports without it; `_check_catalog_targets` would then refuse
    the null. `_refuse_unresolved_overwrite` now speaks first, and says the more
    useful thing — which id was mistyped and what the line points at now — with a
    remedy that is true for this column (omit it), not the kits one (blank it)."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [consumable_line(consumable["id"])])
    line = order["items"][0]

    dead = "00000000-0000-0000-0000-00000000dead"
    content = archive(order_items=[line_row(order, line, catalog_ref_id=dead)])
    plan = await preview(client, content)
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    error = plan["tables"][0]["rows"][0]["error"]
    assert error.startswith("catalog_ref_id:"), error
    assert dead in error and consumable["id"] in error, error
    assert "leave the column out" in error, error
    assert (await apply(client, content)).status_code == 409
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert stored["catalog_ref_id"] == consumable["id"]


async def test_a_blank_reference_cell_on_a_catalog_line_is_refused_not_nulled(client):
    """The other half of that action axis: the column is there and empty, which is
    what an export template and a hand-edited archive both look like. Blank means
    null, and null on a catalog line is the dangling row this check exists for —
    so it is a refusal, not a silent write."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [consumable_line(consumable["id"])])
    item = order["items"][0]

    content = archive(order_items=[line_row(order, item, catalog_ref_id="")])
    plan = await preview(client, content)
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    assert (await apply(client, content)).status_code == 409
    stored = (await client.get(f"/orders/{order['id']}")).json()["items"][0]
    assert stored["catalog_ref_id"] == consumable["id"]


async def test_a_kit_line_carrying_a_stray_catalog_reference_is_still_fine(client):
    """Kit lines don't reference the catalog — `_resolve_ref` nulls the column for
    them. The check has to skip that rather than read the null as unresolvable."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [kit_line(1)])
    item = order["items"][0]

    content = archive(order_items=[line_row(order, item, catalog_ref_id=consumable["id"])])
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert (await apply(client, content)).status_code == 200
    assert (await client.get(f"/orders/{order['id']}")).json()["items"][0]["catalog_ref_id"] is None


# --- a status the sheet moves without saying when ---------------------------------


KIT_HEADER = ["id", "name", "grade", "status", "status_updated_at"]


def kit_sheet(kit_id, status, stamp=None, *, with_stamp_column=True) -> bytes:
    header = KIT_HEADER if with_stamp_column else KIT_HEADER[:-1]
    row = {"id": kit_id, "name": "Zaku II", "grade": "HG", "status": status}
    if with_stamp_column:
        row["status_updated_at"] = stamp or ""
    return sheet("kits", header, [row])


@pytest.fixture
async def spawned_kit(client):
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    kit = (await client.get(f"/kits/{order['items'][0]['kits'][0]['id']}")).json()
    assert kit["status"] == "ordered"
    return kit


@pytest.mark.parametrize(
    ("status", "stamp", "with_column", "expected"),
    [
        # The case the issue names: a status move with no timestamp anywhere.
        ("building", None, False, "generated"),
        # The same move with the column present and empty — what the export
        # template ships and a hand-edited archive is full of. `status_updated_at`
        # is NOT NULL, so writing the blank through was an IntegrityError: a 500
        # out of the apply, on the row that needed a generated stamp anyway.
        ("building", None, True, "generated"),
        # A sheet that says both. An explicit value is a fact the file is asserting
        # and always wins — inventing one over the top is the mistake §6 keeps out
        # of money.
        ("building", "2026-02-01T00:00:00Z", True, "stated"),
        # No status change, so nothing to stamp: the row is unchanged and the
        # timestamp still says when the kit last actually moved.
        ("ordered", None, False, "untouched"),
    ],
    ids=["absent column", "blank cell", "stated", "no status change"],
)
async def test_a_status_change_gets_the_timestamp_the_board_reads(
    client, spawned_kit, status, stamp, with_column, expected
):
    """`update_kit` stamps `status_updated_at` on every status change because the
    board's "most recently moved" ordering is read off it. The importer assigned
    `status` directly and left the timestamp, so the board silently lied — and the
    further back the kit's last real move was, the further from the truth."""
    content = kit_sheet(spawned_kit["id"], status, stamp, with_stamp_column=with_column)
    resp = await apply(client, content, filename="kits.csv")
    assert resp.status_code == 200, resp.text

    after = (await client.get(f"/kits/{spawned_kit['id']}")).json()
    assert after["status"] == status
    if expected == "generated":
        assert after["status_updated_at"] != spawned_kit["status_updated_at"]
    elif expected == "stated":
        assert after["status_updated_at"].startswith("2026-02-01")
    else:
        assert after["status_updated_at"] == spawned_kit["status_updated_at"]


async def test_a_deferred_stamp_and_a_kept_blank_do_not_both_claim_the_column(client, spawned_kit):
    """The one behaviour that exists only because two branches merged.

    #44 defers a blank `status_updated_at` on a status-moving row so the apply can
    stamp the clock. #82/#88 keeps a blank in any column the database refuses to
    leave empty, and says "left as it was". `status_updated_at` is both: NOT NULL,
    and the one column #44 deliberately blanks in `present`.

    Run keep-stored first and the row previews **"left as it was"** while the apply
    stamps `now` anyway — a preview that contradicts itself and then contradicts
    the outcome. Deferring first takes the column out of `present`, so keep-stored
    finds nothing to keep and says nothing.

    Neither branch could test this: on #44 alone there is no keep-stored rule, and
    on #82/#88 alone there is no deferral. It was predicted by an external review
    that read both trees at once, and this is the pin.
    """
    content = kit_sheet(spawned_kit["id"], "building", with_stamp_column=True)
    plan = await preview(client, content, filename="kits.csv")
    messages = plan["tables"][0]["rows"][0]["messages"]

    assert any("will be set to the time of this import" in m for m in messages), messages
    assert not any("left as it was" in m for m in messages), (
        "keep-stored ran first and claimed a column the deferral is about to write"
    )
    assert "status_updated_at" not in [c["field"] for c in plan["tables"][0]["rows"][0]["changes"]]

    resp = await apply(client, content, filename="kits.csv")
    assert resp.status_code == 200, resp.text
    after = (await client.get(f"/kits/{spawned_kit['id']}")).json()
    assert after["status"] == "building"
    assert after["status_updated_at"] != spawned_kit["status_updated_at"], (
        "the preview promised a new timestamp"
    )


async def test_a_blank_stamp_with_no_status_change_is_kept_not_generated(client, spawned_kit):
    """The other half of the same crossing, and the reason both rules are needed.

    No status change means #44's deferral does not fire, so #82/#88's keep-stored
    is what stops the blank reaching a NOT NULL column — which it used to do as a
    500. One column, two rules, and each covers what the other does not.
    """
    content = kit_sheet(spawned_kit["id"], "ordered", with_stamp_column=True)
    plan = await preview(client, content, filename="kits.csv")
    messages = plan["tables"][0]["rows"][0]["messages"]

    assert any("left as it was" in m for m in messages), messages
    assert not any("will be set to the time of this import" in m for m in messages), messages

    assert (await apply(client, content, filename="kits.csv")).status_code == 200
    after = (await client.get(f"/kits/{spawned_kit['id']}")).json()
    assert after["status_updated_at"] == spawned_kit["status_updated_at"]


@pytest.mark.parametrize("with_column", [False, True], ids=["absent column", "blank cell"])
async def test_a_generated_status_stamp_does_not_move_the_plan_hash(
    client, spawned_kit, with_column
):
    """The reason the stamp is deferred to apply rather than filled in at plan
    time. `_plan_fingerprint` hashes every value in `row.present`, so a clock
    reading in the plan is a different hash on every pass — preview and apply could
    never agree, and every status-moving import would 409 on a preview it had just
    been shown.

    Both sheet shapes, because only one of them can see it. With the column absent
    the fingerprint never reads `status_updated_at` at all, so a plan-time
    `datetime.now(UTC)` written into `values` hashes as nothing and this test
    passes against the broken build. The blank-cell shape has the column in
    `present`, which is where the clock would actually land — and `present.discard`
    is what takes it back out. Found by mutation testing: the absent-column case
    alone stayed green with the deferral removed.
    """
    content = kit_sheet(spawned_kit["id"], "building", with_stamp_column=with_column)
    first = await preview(client, content, filename="kits.csv")
    second = await preview(client, content, filename="kits.csv")
    assert first["plan_hash"] == second["plan_hash"], "a generated timestamp moved the hash"
    assert "status_updated_at" in " ".join(first["tables"][0]["rows"][0]["messages"])

    resp = await apply(client, content, filename="kits.csv", plan_hash=first["plan_hash"])
    assert resp.status_code == 200, resp.text
    after = (await client.get(f"/kits/{spawned_kit['id']}")).json()
    assert after["status_updated_at"] != spawned_kit["status_updated_at"]


async def test_an_arrival_and_a_status_row_do_not_both_stamp_one_kit(client):
    """The two derivations that write this column meet on one kit: an order this
    import receives, whose kit the same import also gives an explicit status.
    `_advance_kits_for_newly_received_orders` already yields to an explicit status
    cell, so the generated stamp has to come from the kits row alone — and the
    explicit status is what lands, not `backlog`."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = await make_order(client, retailer, [kit_line(1)])
    kit = order["items"][0]["kits"][0]

    content = archive(
        {"kits": ["id", "name", "grade", "status"]},
        orders=[order_row(order, retailer, received_at="2026-03-20T00:00:00Z")],
        kits=[{"id": kit["id"], "name": "Zaku II", "grade": "HG", "status": "building"}],
    )
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text

    after = (await client.get(f"/kits/{kit['id']}")).json()
    assert after["status"] == "building", "the sheet's status wins over the arrival default"
    assert after["status_updated_at"] != kit["status_updated_at"]
