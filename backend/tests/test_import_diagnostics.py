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
from pathlib import Path

import pytest

from app import error_codes
from app.db import session_scope
from app.models.orders import Retailer
from app.schemas.portability import ImportMode
from app.services.portability.importing import _plan_fingerprint, plan_import
from tests.test_portability import make_archive, make_csv, preview

# The shared registry, for the bridge runtime matrix below: the two bridge
# helpers build their params dynamically, so the static exact-params audit in
# test_error_envelope.py exempts them by name — which makes runtime the only
# place their emitted keys can be held against the declaration (#178).
_REGISTRY = json.loads(
    (
        Path(__file__).resolve().parents[2] / "frontend/src/lib/__fixtures__/api-error-codes.json"
    ).read_text(encoding="utf-8")
)["codes"]


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
    # Runtime matrix for the audit-exempt `_borrowed_diagnostic` bridge (#178):
    # it forwards the refusing raise's params verbatim and adds nothing, so its
    # output equals the borrowed code's declaration exactly.
    assert set(borrowed["params"]) == set(_REGISTRY["order_line.quantity_too_small"]["params"])


async def test_the_borrowed_bridge_matrix_covers_the_large_quantity_and_fanout_codes(client):
    """The other two codes `_borrowed_diagnostic` can carry (#180 review, P3-1):
    the matrix is the ONLY control on a bridge's output — the static audit
    exempts bridges by name — so a raise-side extra on any borrowed code
    becomes an undeclared Diagnostic param the moment the matrix doesn't
    exercise that code. The small-quantity case above proved nothing about
    these two: a probe param added to the `quantity_too_large` raise sailed
    through 34/34 green at `7fc20d6`."""
    too_large = make_csv(
        ["order_id", "item_type", "quantity", "kit_name", "kit_grade"],
        [
            {
                "order_id": "0be04b6e-2ff5-4ab6-9c33-000000000001",
                "item_type": "kit",
                "quantity": "2000",
                "kit_name": "Zaku II",
                "kit_grade": "HG",
            }
        ],
    )
    plan = await preview(client, too_large, filename="order_items.csv")
    row = _rows(plan, "order_items")[0]
    assert row["action"] == "error"
    borrowed = next(
        d for d in row["errors"] if d["code"] == error_codes.ORDER_LINE_QUANTITY_TOO_LARGE
    )
    assert borrowed["params"]["quantity"] == 2000
    assert set(borrowed["params"]) == set(_REGISTRY["order_line.quantity_too_large"]["params"])

    # The aggregate ceiling: every line individually legal, the plan's spawn
    # total over MAX_TOTAL_FANOUT — a blocking diagnostic, not a row error.
    # The lines must join a real order: a dangling order_id refuses the row
    # as ref_unmatched before any kit is ever counted as a spawn.
    retailer = (await client.post("/retailers", json={"name": "Bulk Base"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-04-01",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 5500,
                        "currency_code": "AUD",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    fanout = make_csv(
        [
            "order_id",
            "item_type",
            "quantity",
            "unit_price_minor",
            "currency_code",
            "kit_name",
            "kit_grade",
        ],
        [
            {
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1000",
                "unit_price_minor": "5500",
                "currency_code": "AUD",
                "kit_name": f"Zaku II unit {index}",
                "kit_grade": "HG",
            }
            for index in range(11)
        ],
    )
    plan = await preview(client, fanout, filename="order_items.csv")
    blocked = next(
        d for d in plan["blocking_errors"] if d["code"] == error_codes.ORDER_FANOUT_LIMIT
    )
    assert blocked["params"]["total"] == 11_000
    assert set(blocked["params"]) == set(_REGISTRY["order.fanout_limit"]["params"])


# --- ambiguous matches (#178) ----------------------------------------------------
#
# Two emitter shapes, two codes. The generic natural-key matcher speaks
# `import.match_ambiguous` with exactly {count, table}; the order matcher knows
# *which* natural key was ambiguous and speaks `import.order_match_ambiguous`
# with exactly {count, matched_by}, so the catalogue can render the hint the
# English detail carries. Codes and params are asserted as literals, never via
# the constants the fix introduces (checklist rule 10 — a missing symbol masks
# the file against the unfixed tree).


async def test_generic_natural_key_ambiguity_keeps_the_generic_code(client):
    """Two stored rows sharing a normalised name are unreachable through the
    services (name.duplicate refuses), but this is the importer, and the third
    writer plans against whatever Postgres actually holds — so the state is
    seeded directly, the way any external writer could leave it."""
    async with session_scope() as session:
        session.add_all([Retailer(name="Gundam Base"), Retailer(name="GUNDAM BASE")])

    content = make_csv(["id", "name"], [{"id": "", "name": "gundam base"}])
    plan = await preview(client, content, filename="retailers.csv")
    row = _rows(plan, "retailers")[0]
    assert row["action"] == "error"
    assert row["matched_id"] is None
    codes = [d["code"] for d in row["errors"]]
    assert "import.match_ambiguous" in codes, codes
    ambiguous = next(d for d in row["errors"] if d["code"] == "import.match_ambiguous")
    assert _shape_ok(ambiguous)
    assert ambiguous["params"] == {"count": 2, "table": "retailers"}
    assert ambiguous["detail"] == (
        "2 existing retailers rows match this one — set the id column to say which one you mean"
    )


async def test_order_ambiguity_by_retailer_and_order_number(client):
    """Order numbers are deliberately not unique (models/orders.py), so two
    orders sharing retailer + number are ordinary API-reachable state."""
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    for order_date in ("2026-03-01", "2026-04-01"):
        resp = await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": order_date,
                "order_number": "INV-7",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 5500,
                        "currency_code": "AUD",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
        assert resp.status_code == 201, resp.text

    content = make_csv(
        ["id", "retailer_name", "order_date", "order_number", "currency_code"],
        [
            {
                "id": "",
                "retailer_name": "Gundam Base",
                "order_date": "2026-05-01",
                "order_number": "inv-7",  # numbers match normalised, like names
                "currency_code": "AUD",
            }
        ],
    )
    plan = await preview(client, content, filename="orders.csv")
    row = _rows(plan, "orders")[0]
    assert row["action"] == "error"
    assert row["matched_id"] is None
    codes = [d["code"] for d in row["errors"]]
    assert "import.order_match_ambiguous" in codes, codes
    ambiguous = next(d for d in row["errors"] if d["code"] == "import.order_match_ambiguous")
    assert _shape_ok(ambiguous)
    assert ambiguous["params"] == {"count": 2, "matched_by": "retailer_order_number"}
    assert ambiguous["detail"] == (
        "2 existing orders match this one (retailer + order number) — "
        "set the id column to say which one you mean"
    )


async def test_order_ambiguity_by_date_and_line_fingerprint(client):
    """Three identical purchases, and an incoming description with no order
    number: the fingerprint route must be named, and the count is 3 so the
    value axis is not stuck at the smallest ambiguous case."""
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    for _ in range(3):
        resp = await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-04-01",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 5500,
                        "currency_code": "AUD",
                        "kit": {"name": "Zaku II", "grade": "MG"},
                    }
                ],
            },
        )
        assert resp.status_code == 201, resp.text

    foreign_order = "33333333-3333-4333-8333-333333333333"
    archive = make_archive(
        {
            "orders": [
                {
                    "id": foreign_order,
                    "retailer_name": "Gundam Base",
                    "order_date": "2026-04-01",
                    "order_number": "",
                    "currency_code": "AUD",
                }
            ],
            "order_items": [
                {
                    "id": "44444444-4444-4444-8444-444444444444",
                    "order_id": foreign_order,
                    "item_type": "kit",
                    "quantity": "1",
                    "unit_price_minor": "5500",
                    "currency_code": "AUD",
                    "kit_name": "Zaku II",
                    "kit_grade": "MG",
                }
            ],
        }
    )
    plan = await preview(client, archive)
    row = _rows(plan, "orders")[0]
    assert row["action"] == "error"
    assert row["matched_id"] is None
    codes = [d["code"] for d in row["errors"]]
    assert "import.order_match_ambiguous" in codes, codes
    ambiguous = next(d for d in row["errors"] if d["code"] == "import.order_match_ambiguous")
    assert _shape_ok(ambiguous)
    assert ambiguous["params"] == {"count": 3, "matched_by": "retailer_date_lines"}
    assert ambiguous["detail"] == (
        "3 existing orders match this one (retailer + date + lines) — "
        "set the id column to say which one you mean"
    )


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
            {
                "kit_name": "Dom",
                "grade": "HG",
                "quantity": "2000",
                "retailer": "",
                "order_date": "",
            },
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
    over_ceiling = by_row["4"]
    assert over_ceiling["code"] == error_codes.ORDER_LINE_QUANTITY_TOO_LARGE
    assert over_ceiling["params"]["quantity"] == 2000
    # Runtime matrix for the audit-exempt `_row_problem` bridge (#178): the
    # borrowed code's declared params exactly, plus the source `row` it adds —
    # deliberately undeclared, since the borrowed codes are shared with sites
    # that have no source row. The catalogue consequently cannot render the
    # row context (it lives in `detail` only) — #178's class, filed as #179.
    # Every code this bridge can carry is driven (#180 review, P3-1): the cell
    # parsers' `cell_invalid` and both ends of the quantity range.
    assert set(unreadable["params"]) == set(_REGISTRY["import.cell_invalid"]["params"]) | {"row"}
    assert set(out_of_range["params"]) == (
        set(_REGISTRY["order_line.quantity_too_small"]["params"]) | {"row"}
    )
    assert set(over_ceiling["params"]) == (
        set(_REGISTRY["order_line.quantity_too_large"]["params"]) | {"row"}
    )


# --- OpenAPI ---------------------------------------------------------------------


def test_openapi_documents_the_diagnostic_shape():
    from app.main import app

    components = app.openapi()["components"]["schemas"]
    assert set(components["Diagnostic"]["required"]) >= {"code", "detail"}
    row = components["PlannedRow"]["properties"]
    assert "Diagnostic" in str(row["errors"])
    assert "Diagnostic" in str(row["messages"])
