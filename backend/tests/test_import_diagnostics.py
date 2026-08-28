"""Import-preview diagnostics (#26): {code, params, detail} inside the 200.

The registry side — module == fixture, code shape, the construction-site params
audit — lives in `test_error_envelope.py` beside the raise-site audit it
mirrors. This file pins the *wire behaviour*:

- a planned row's problems arrive as separate diagnostics, each carrying the
  full envelope shape, never a semicolon-joined sentence;
- the plan-level surfaces (warnings, blocking errors, the stock note) carry the
  same shape, and the parse-stage warning dedup is by value;
- a blocked apply is a structured 409 on the #25 contract — the blocking
  diagnostics ride in `params`, verbatim, beside the joined-English `detail`;
- the plan hash reads none of it: rewording every diagnostic on a built plan
  recomputes to the same fingerprint (§6.1 — translating a diagnostic must
  never invalidate an outstanding preview);
- the starter sheet's row-scoped problems borrow the refusing service's own
  code and add the source row.

Value axes per the checklist: the clean row (empty lists) is driven beside the
single- and the two-diagnostic rows; the state axis is the mode where it
decides shape (merge vs add_only for the row surface, replace_all confirm on
the blocked apply).
"""

import io
import json
import zipfile

import pytest

from app import error_codes
from app.db import session_scope
from app.schemas.portability import ImportMode
from app.services.portability.importing import _plan_fingerprint, plan_import
from tests.test_portability import make_csv, preview


def _rows(plan: dict, table: str) -> list[dict]:
    return next(t for t in plan["tables"] if t["table"] == table)["rows"]


def _shape_ok(diagnostic: dict) -> bool:
    return set(diagnostic) == {"code", "params", "detail"} and isinstance(diagnostic["detail"], str)


# --- the row surface -------------------------------------------------------------


@pytest.mark.parametrize("mode", ["merge", "add_only"])
async def test_a_clean_row_carries_empty_diagnostic_lists(client, mode):
    content = make_csv(["name", "grade"], [{"name": "Zaku II", "grade": "HG"}])
    plan = await preview(client, content, filename="kits.csv", mode=mode)
    row = _rows(plan, "kits")[0]
    assert row["errors"] == []
    assert row["messages"] == []


async def test_an_unreadable_cell_is_one_full_diagnostic(client):
    content = make_csv(
        ["name", "grade", "rating"], [{"name": "Zaku II", "grade": "HG", "rating": "great"}]
    )
    plan = await preview(client, content, filename="kits.csv")
    row = _rows(plan, "kits")[0]
    assert row["action"] == "error"
    assert len(row["errors"]) == 1
    diagnostic = row["errors"][0]
    assert _shape_ok(diagnostic)
    assert diagnostic["code"] == "import.cell_invalid"
    assert diagnostic["params"]["field"] == "rating"
    # The English keeps the parser's specifics — the fallback an API client and
    # an unknown-code browser read.
    assert diagnostic["detail"].startswith("rating: ")


async def test_two_problems_are_two_diagnostics_not_a_joined_sentence(client):
    content = make_csv(
        ["name", "grade", "rating", "status"],
        [{"name": "Zaku II", "grade": "HG", "rating": "great", "status": "vibing"}],
    )
    plan = await preview(client, content, filename="kits.csv")
    row = _rows(plan, "kits")[0]
    # Two diagnostics, one per cell (spec column order, not header order).
    assert sorted(d["params"]["field"] for d in row["errors"]) == ["rating", "status"]
    for diagnostic in row["errors"]:
        assert diagnostic["code"] == "import.cell_invalid"
        assert ";" not in diagnostic["detail"]


async def test_a_row_message_carries_the_same_shape(client):
    content = make_csv(
        ["name", "grade", "rating"],
        [
            {"name": "Zaku II", "grade": "HG", "rating": "5"},
            {"name": "Zaku II", "grade": "HG", "rating": "4"},
        ],
    )
    assert (await client.post("/kits", json={"name": "Zaku II", "grade": "HG"})).status_code == 201
    plan = await preview(client, content, filename="kits.csv")
    for row in _rows(plan, "kits"):
        [message] = [d for d in row["messages"] if d["code"] == "import.kit_name_exists"]
        assert _shape_ok(message)
        assert message["params"] == {"count": 1, "name": "Zaku II"}


async def test_a_borrowed_code_is_the_live_writers_own(client):
    """`quantity: 0` on an order line is the same condition REST 422s, so the
    diagnostic carries `order_line.quantity_too_small` with the raise's params."""
    content = make_csv(
        ["order_id", "item_type", "quantity", "kit_name", "kit_grade"],
        [
            {
                "order_id": "0be04b6e-2ff5-4ab6-9c33-000000000001",
                "item_type": "kit",
                "quantity": "0",
                "kit_name": "Zaku II",
                "kit_grade": "HG",
            }
        ],
    )
    plan = await preview(client, content, filename="order_items.csv")
    row = _rows(plan, "order_items")[0]
    assert row["action"] == "error"
    codes = [d["code"] for d in row["errors"]]
    assert error_codes.ORDER_LINE_QUANTITY_TOO_SMALL in codes
    borrowed = next(
        d for d in row["errors"] if d["code"] == error_codes.ORDER_LINE_QUANTITY_TOO_SMALL
    )
    assert borrowed["params"]["quantity"] == 0


# --- the plan surface ------------------------------------------------------------


async def test_plan_surfaces_carry_diagnostics_and_the_stray_column_dedups_by_value(client):
    content = make_csv(
        ["name", "grade", "vibes"],
        [
            {"name": "Zaku II", "grade": "HG", "vibes": "immaculate"},
            {"name": "Gouf", "grade": "HG", "vibes": "also immaculate"},
            {"name": "", "grade": "HG", "vibes": ""},
        ],
    )
    plan = await preview(client, content, filename="kits.csv")

    # One warning for the stray column, not one per row — the dedup is by value.
    strays = [d for d in plan["warnings"] if d["code"] == "import.column_unknown"]
    assert len(strays) == 1
    assert _shape_ok(strays[0])
    assert strays[0]["params"] == {"column": "vibes", "table": "kits"}

    # The blocking summary counts the unreadable rows, as a diagnostic.
    [blocking] = plan["blocking_errors"]
    assert blocking["code"] == "import.rows_unreadable"
    assert blocking["params"] == {"count": 1}

    # The stock note is the rule-10 sentence with a stable code.
    note = plan["derived"]["stock_note"]
    assert note["code"] == "import.stock_note"
    assert note["params"] == {}
    assert note["detail"] == (
        "Stock levels come from the catalog files. "
        "Importing orders never changes what you have on hand."
    )


async def test_manifest_metadata_fields_arrive_sorted_deduped_and_structured(client):
    """The one site where `detail` deliberately differs from main's rendering
    (#171 review, P3-1): two unreadable manifest-metadata fields list sorted
    and deduplicated, and `params.fields` carries the structured list. Pinned
    so the PR body's carve-out stays a decision rather than drift — the
    pre-#26 rendering followed pydantic's error order."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format": 123, "export_version": "abc"}))
        archive.writestr("kits.csv", "name,grade\nZaku II,HG\n")
    plan = await preview(client, buffer.getvalue())
    [warning] = [d for d in plan["warnings"] if d["code"] == "import.manifest_metadata_unreadable"]
    assert warning["params"] == {"fields": ["export_version", "format"]}
    assert "(export_version, format)" in warning["detail"]


async def test_a_blocked_apply_is_a_structured_conflict(http_client):
    """The #25 contract on the apply side: `import.blocked` still guarantees
    `count`, and since #26 the blocking diagnostics ride in params verbatim, so
    a client can render the refusal without re-running the preview."""
    content = make_csv(
        ["name", "grade", "rating"], [{"name": "Zaku II", "grade": "HG", "rating": "great"}]
    )
    seen = await http_client.post(
        "/import/preview",
        files={"file": ("kits.csv", content, "application/octet-stream")},
        data={"mode": "merge"},
    )
    assert seen.status_code == 200
    plan = seen.json()
    resp = await http_client.post(
        "/import/apply",
        files={"file": ("kits.csv", content, "application/octet-stream")},
        data={"mode": "merge", "plan_hash": plan["plan_hash"]},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert set(body) == {"detail", "code", "params"}
    assert body["code"] == "import.blocked"
    assert body["params"]["count"] == 1
    # Verbatim — the same diagnostics the preview showed, not a re-rendering.
    assert body["params"]["diagnostics"] == plan["blocking_errors"]
    # The joined English stays the string detail (the pre-#26 fallback).
    assert body["detail"] == "; ".join(d["detail"] for d in plan["blocking_errors"])


# --- the hash reads none of it ---------------------------------------------------


async def test_rewording_every_diagnostic_leaves_the_plan_hash_alone(client):
    """§6.1: wording — and the presentation params beside it — stay out of the
    fingerprint, so translating or rewording a diagnostic can never stale an
    outstanding preview. Driven by mutation, not by reading: every diagnostic on
    a built plan (row errors, row messages, and the plan surfaces) is reworded
    and the fingerprint recomputed over the same rows."""
    content = make_csv(
        ["name", "grade", "rating", "order_item_id"],
        [
            {"name": "Zaku II", "grade": "HG", "rating": "5", "order_item_id": ""},
            # A dangling optional reference — carries a row *message* (#82).
            {
                "name": "Gouf",
                "grade": "HG",
                "rating": "4",
                "order_item_id": "0be04b6e-2ff5-4ab6-9c33-000000000009",
            },
            # An unreadable cell — carries a row *error*.
            {"name": "Dom", "grade": "HG", "rating": "many", "order_item_id": ""},
        ],
    )
    async with session_scope() as session:
        execution = await plan_import(session, "kits.csv", content, ImportMode.MERGE)
    baseline = execution.plan.plan_hash

    touched = 0
    for rows in execution.rows.values():
        for row in rows:
            for diagnostic in [*row.errors, *row.messages]:
                diagnostic.detail = "reworded for a different audience"
                diagnostic.params = {"anything": "else"}
                touched += 1
    assert touched >= 2, "the plan under test must actually carry diagnostics"

    recomputed = _plan_fingerprint(
        ImportMode.MERGE,
        execution.plan.source,
        execution.rows,
        execution.spawns,
        execution.removals,
        execution.advances,
        {},
    )
    assert recomputed == baseline


# --- the starter sheet -----------------------------------------------------------


async def test_a_starter_row_problem_borrows_the_code_and_names_the_row(client):
    header = ["kit_name", "grade", "quantity", "retailer", "order_date"]
    content = make_csv(
        header,
        [
            {
                "kit_name": "Zaku II",
                "grade": "HG",
                "quantity": "abc",
                "retailer": "",
                "order_date": "",
            },
            {"kit_name": "Gouf", "grade": "HG", "quantity": "0", "retailer": "", "order_date": ""},
        ],
    )
    plan = await preview(client, content, filename="starter-sheet.csv")
    by_row = {d["params"]["row"]: d for d in plan["blocking_errors"] if "row" in d["params"]}
    unreadable = by_row["2"]
    assert unreadable["code"] == "import.cell_invalid"
    assert unreadable["params"]["field"] == "quantity"
    assert unreadable["detail"].startswith("row 2: quantity: ")
    out_of_range = by_row["3"]
    assert out_of_range["code"] == error_codes.ORDER_LINE_QUANTITY_TOO_SMALL
    assert out_of_range["params"]["quantity"] == 0


# --- OpenAPI ---------------------------------------------------------------------


def test_openapi_documents_the_diagnostic_shape():
    from app.main import app

    components = app.openapi()["components"]["schemas"]
    assert set(components["Diagnostic"]["required"]) >= {"code", "detail"}
    row = components["PlannedRow"]["properties"]
    assert "Diagnostic" in str(row["errors"])
    assert "Diagnostic" in str(row["messages"])
