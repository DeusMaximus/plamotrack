"""The importer holds a value to its column's domain, as REST and MCP do (#305).

Ratings are 1–5, stock never goes below 0, a price or a quantity used is never
negative. REST and MCP have always refused these through the request schemas, and
the database through CHECK constraints — but the importer builds models directly,
so it met neither until flush. `rating=7` or `quantity_on_hand=-2` previewed as a
clean import, then failed the apply with an `IntegrityError`: a 500 naming no row,
after the preview said the import was fine. Two columns with no CHECK at all —
`shipping_cost_minor`, `low_stock_threshold` — went further: a negative value
imported, which no other writer could store.

What is pinned here:

- **The three sources agree.** Every range CHECK on a portable table has the same
  bound declared on its spec column, and every declared bound equals the request
  schema's. Both are read from their own source — the database metadata and the
  pydantic schemas — never from the spec under test.
- **The preview refuses, the apply never 500s.** One step outside each bound is a
  row error carrying `import.cell_below_minimum` / `import.cell_above_maximum` with
  exact params; the apply is the structured 409 and writes nothing. The bound
  itself still imports.
- **States:** create and update (a stored row the sheet would overwrite), merge and
  replace_all; a major-unit cell, judged as the minor-unit value it becomes and
  named as the cell the sheet wrote; the starter sheet.
"""

import csv
import io
import re
import uuid
import zipfile

import pytest
from sqlalchemy import CheckConstraint

from app import error_codes
from app.models.base import Base
from app.schemas.catalog import (
    ConsumableCreate,
    DisplayItemCreate,
    ToolCreate,
    UpgradeApplyRequest,
    UpgradeCreate,
)
from app.schemas.kits import KitUpdate
from app.schemas.orders import OrderCreate, OrderItemCreate, RetailerCreate
from app.services.portability import spec
from tests.test_portability import apply, make_archive, make_csv, preview

# --- the three sources agree -------------------------------------------------------

#: Each bounded import column and the request-schema field REST and MCP hold to the
#: same rule. `upgrade_applications.quantity_used` is the apply request's `quantity`.
SCHEMA_FIELD = {
    ("retailers", "rating"): (RetailerCreate, "rating"),
    ("kits", "rating"): (KitUpdate, "rating"),
    ("tools", "quantity_on_hand"): (ToolCreate, "quantity_on_hand"),
    ("tools", "unit_cost_reference_minor"): (ToolCreate, "unit_cost_reference_minor"),
    ("consumables", "quantity_on_hand"): (ConsumableCreate, "quantity_on_hand"),
    ("consumables", "low_stock_threshold"): (ConsumableCreate, "low_stock_threshold"),
    ("upgrades", "quantity_on_hand"): (UpgradeCreate, "quantity_on_hand"),
    ("display_items", "quantity_on_hand"): (DisplayItemCreate, "quantity_on_hand"),
    ("orders", "shipping_cost_minor"): (OrderCreate, "shipping_cost_minor"),
    ("order_items", "unit_price_minor"): (OrderItemCreate, "unit_price_minor"),
    ("order_items", "converted_price_minor"): (OrderItemCreate, "converted_price_minor"),
    ("upgrade_applications", "quantity_used"): (UpgradeApplyRequest, "quantity"),
}

#: A line's quantity has its own guard, `require_line_quantity`, which answers in
#: the live writers' codes (`order_line.quantity_too_small`) and holds the fan-out
#: ceiling too. Declaring a bound on the column as well would report one problem twice.
OWN_GUARD = {("order_items", "quantity")}

_RANGE = (
    (re.compile(r"(\w+) >= (-?\d+)"), lambda m: (int(m[2]), None)),
    (re.compile(r"(\w+) > (-?\d+)"), lambda m: (int(m[2]) + 1, None)),
    (re.compile(r"(\w+) BETWEEN (-?\d+) AND (-?\d+)"), lambda m: (int(m[2]), int(m[3]))),
)

#: CHECK forms that are not a numeric range, each answered elsewhere: an enum's
#: value list (the enum parsers), a null-together pair (`_clear_orphan_money_currency`
#: and the money-pair handling), a singleton's key. Anything matching neither these
#: nor `_RANGE` fails the walk, so a new range written another way (`price <= 100`)
#: cannot pass it unread.
_NOT_A_RANGE = (
    re.compile(r"\w+\.\w+ IN \(.*\)"),
    re.compile(r"\(\w+ IS NULL\) = \(\w+ IS NULL\)"),
    re.compile(r"id = \d+"),
)


def _range_checks() -> dict[tuple[str, str], tuple[int, int | None]]:
    """Every range CHECK on a portable table, read off the database metadata."""
    portable = {s.model.__tablename__: s.key for s in spec.TABLE_SPECS}
    found = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in portable:
            continue
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            text = str(constraint.sqltext)
            for pattern, bounds in _RANGE:
                if match := pattern.fullmatch(text):
                    found[(portable[table.name], match[1])] = bounds(match)
                    break
            else:
                assert any(p.fullmatch(text) for p in _NOT_A_RANGE), (
                    f"{table.name}.{constraint.name}: a CHECK this audit can't read — "
                    f"teach `_RANGE` its bound, or `_NOT_A_RANGE` why it isn't one: {text}"
                )
    return found


def _schema_bounds(model, name: str) -> tuple[int | None, int | None]:
    schema = model.model_json_schema()["properties"][name]
    branch = next(b for b in schema.get("anyOf", [schema]) if b.get("type") == "integer")
    minimum = branch.get("minimum")
    if "exclusiveMinimum" in branch:
        minimum = branch["exclusiveMinimum"] + 1
    maximum = branch.get("maximum")
    return minimum, maximum


def _declared(table: str, column: str) -> tuple[int | None, int | None]:
    declared = spec.SPEC_BY_KEY[table].column(column)
    return declared.minimum, declared.maximum


def test_every_range_check_is_declared_on_its_column():
    checks = _range_checks()
    # Twelve since #309 added the shipping-cost and low-stock-threshold CHECKs; the
    # floor keeps the walk from passing on nothing.
    assert len(checks) >= 12, checks
    assert ("orders", "shipping_cost_minor") in checks
    assert ("consumables", "low_stock_threshold") in checks
    for key, bounds in checks.items():
        if key in OWN_GUARD:
            assert _declared(*key) == (None, None), key
            continue
        assert _declared(*key) == bounds, key


def test_a_check_the_walk_cannot_read_fails_it():
    """The walk is total: a range written in a form `_RANGE` doesn't know is a
    failure, never a constraint quietly left uncompared."""
    table = Base.metadata.tables["tools"]
    probe = CheckConstraint("quantity_on_hand <= 100", name="probe_ceiling")
    table.append_constraint(probe)
    try:
        with pytest.raises(AssertionError, match="a CHECK this audit can't read"):
            _range_checks()
    finally:
        table.constraints.discard(probe)
    assert probe not in table.constraints


def test_every_declared_bound_is_the_request_schemas():
    """The schema's ceiling is int4 where the column has no product maximum; the
    importer gets that one from `parse_int`, so only a product maximum is compared."""
    for key, (model, name) in SCHEMA_FIELD.items():
        minimum, maximum = _schema_bounds(model, name)
        declared_min, declared_max = _declared(*key)
        assert declared_min == minimum, key
        if declared_max is not None or maximum < 2_147_483_647:
            assert declared_max == maximum, key


def test_every_integer_column_is_accounted_for():
    """A new integer column owes an answer: a schema field to agree with, or a guard
    of its own."""
    integer_columns = {
        (table_spec.key, column.name)
        for table_spec in spec.TABLE_SPECS
        for column in table_spec.columns
        if column.parse is spec.parse_int and column.persisted
    }
    assert integer_columns == set(SCHEMA_FIELD) | OWN_GUARD


# --- the preview refuses, the apply never 500s ---------------------------------------

RETAILER = {"id": "11111111-1111-4111-8111-111111111111", "name": "Range Test Shop"}
ORDER = {
    "id": "22222222-2222-4222-8222-222222222222",
    "retailer_id": RETAILER["id"],
    "order_date": "2026-01-01",
    "currency_code": "AUD",
}
UPGRADE = {
    "id": "33333333-3333-4333-8333-333333333333",
    "name": "Range Test Decal",
    "manufacturer": "Delpi",
    "quantity_on_hand": "5",
}
KIT = {"id": "44444444-4444-4444-8444-444444444444", "name": "Range Test Kit", "grade": "HG"}
TOOL = {
    "id": "55555555-5555-4555-8555-555555555555",
    "name": "Range Test Nippers",
    "category": "cutting",
    "quantity_on_hand": "1",
}
LINE = {
    "id": "66666666-6666-4666-8666-666666666666",
    "order_id": ORDER["id"],
    "item_type": "tool",
    "catalog_ref_id": TOOL["id"],
    "quantity": "1",
    "unit_price_minor": "100",
    "currency_code": "AUD",
}
CONSUMABLE = {"name": "Range Test Paint", "category": "paint"}
DISPLAY = {"name": "Range Test Base", "category": "base"}


def _tables(table: str, cells: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    """The smallest archive that holds a `table` row carrying `cells`."""
    if table == "retailers":
        return {"retailers": [RETAILER | cells]}
    if table == "kits":
        return {"kits": [KIT | cells]}
    if table == "tools":
        return {"tools": [TOOL | cells]}
    if table == "consumables":
        return {"consumables": [CONSUMABLE | cells]}
    if table == "upgrades":
        return {"upgrades": [UPGRADE | cells]}
    if table == "display_items":
        return {"display_items": [DISPLAY | cells]}
    if table == "orders":
        return {"retailers": [RETAILER], "orders": [ORDER | cells]}
    if table == "order_items":
        return {
            "retailers": [RETAILER],
            "tools": [TOOL],
            "orders": [ORDER],
            "order_items": [LINE | cells],
        }
    if table == "upgrade_applications":
        application = {"upgrade_id": UPGRADE["id"], "kit_id": KIT["id"], "quantity_used": "1"}
        return {"upgrades": [UPGRADE], "kits": [KIT], "upgrade_applications": [application | cells]}
    raise AssertionError(table)


BELOW = error_codes.IMPORT_CELL_BELOW_MINIMUM
ABOVE = error_codes.IMPORT_CELL_ABOVE_MAXIMUM

#: (table, cells, the diagnostic the row must carry). One step outside each bound.
OUT_OF_RANGE = [
    ("retailers", {"rating": "0"}, (BELOW, {"field": "rating", "value": "0", "minimum": 1})),
    ("retailers", {"rating": "6"}, (ABOVE, {"field": "rating", "value": "6", "maximum": 5})),
    ("kits", {"rating": "0"}, (BELOW, {"field": "rating", "value": "0", "minimum": 1})),
    ("kits", {"rating": "6"}, (ABOVE, {"field": "rating", "value": "6", "maximum": 5})),
    *(
        (
            table,
            {"quantity_on_hand": "-1"},
            (BELOW, {"field": "quantity_on_hand", "value": "-1", "minimum": 0}),
        )
        for table in ("tools", "consumables", "upgrades", "display_items")
    ),
    (
        "tools",
        {"unit_cost_reference_minor": "-1", "unit_cost_reference_currency": "AUD"},
        (BELOW, {"field": "unit_cost_reference_minor", "value": "-1", "minimum": 0}),
    ),
    (
        "consumables",
        {"low_stock_threshold": "-1"},
        (BELOW, {"field": "low_stock_threshold", "value": "-1", "minimum": 0}),
    ),
    (
        "orders",
        {"shipping_cost_minor": "-1"},
        (BELOW, {"field": "shipping_cost_minor", "value": "-1", "minimum": 0}),
    ),
    (
        "order_items",
        {"unit_price_minor": "-1"},
        (BELOW, {"field": "unit_price_minor", "value": "-1", "minimum": 0}),
    ),
    (
        "order_items",
        {"converted_price_minor": "-1", "converted_currency_code": "AUD"},
        (BELOW, {"field": "converted_price_minor", "value": "-1", "minimum": 0}),
    ),
    (
        "upgrade_applications",
        {"quantity_used": "0"},
        (BELOW, {"field": "quantity_used", "value": "0", "minimum": 1}),
    ),
    # A major-unit cell is judged as the minor-unit value it becomes, and named as
    # the cell the sheet wrote, in its own spelling.
    (
        "order_items",
        {"unit_price_minor": "", "unit_price": "-1.50"},
        (BELOW, {"field": "unit_price", "value": "-1.50", "minimum": 0}),
    ),
    (
        "tools",
        {"unit_cost_reference": "-0.5", "unit_cost_reference_currency": "AUD"},
        (BELOW, {"field": "unit_cost_reference", "value": "-0.5", "minimum": 0}),
    ),
    (
        "orders",
        {"currency_code": "JPY", "shipping_cost": "-2"},
        (BELOW, {"field": "shipping_cost", "value": "-2", "minimum": 0}),
    ),
    # The cell is quoted as the sheet wrote it, in its own spelling rather than the
    # parsed value; `test_a_retired_header_is_quoted_as_written` covers the header.
    ("kits", {"rating": "+7"}, (ABOVE, {"field": "rating", "value": "+7", "maximum": 5})),
    ("retailers", {"rating": " 6 "}, (ABOVE, {"field": "rating", "value": "6", "maximum": 5})),
]

#: The bounds themselves, and a value inside them, import cleanly.
AT_THE_BOUND = [
    ("retailers", {"rating": "1"}),
    ("retailers", {"rating": "5"}),
    ("kits", {"rating": "1"}),
    ("kits", {"rating": "5"}),
    *((table, {"quantity_on_hand": "0"}) for table in ("tools", "consumables", "upgrades")),
    ("display_items", {"quantity_on_hand": "0"}),
    ("tools", {"unit_cost_reference_minor": "0", "unit_cost_reference_currency": "AUD"}),
    ("consumables", {"low_stock_threshold": "0"}),
    ("orders", {"shipping_cost_minor": "0"}),
    ("order_items", {"unit_price_minor": "0"}),
    ("order_items", {"converted_price_minor": "0", "converted_currency_code": "AUD"}),
    ("upgrade_applications", {"quantity_used": "1"}),
    ("order_items", {"unit_price_minor": "", "unit_price": "0.00"}),
]


def _case_id(case) -> str:
    table, cells = case[0], case[1]
    return f"{table}-" + "-".join(f"{k}={v}" for k, v in cells.items() if v)


def _only_error(plan: dict, table: str) -> dict:
    [entry] = [t for t in plan["tables"] if t["table"] == table]
    [row] = entry["rows"]
    assert row["action"] == "error", row
    [diagnostic] = row["errors"]
    return diagnostic


async def _assert_refused(http_client, archive: bytes, table: str, expected, mode: str):
    code, params = expected
    plan = await preview(http_client, archive, mode=mode)
    diagnostic = _only_error(plan, table)
    assert diagnostic["code"] == code
    assert diagnostic["params"] == params
    assert [d["code"] for d in plan["blocking_errors"]] == [error_codes.IMPORT_ROWS_UNREADABLE]
    extra = {"confirm": "REPLACE"} if mode == "replace_all" else {}
    resp = await apply(http_client, archive, mode=mode, **extra)
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == error_codes.IMPORT_BLOCKED


@pytest.mark.parametrize("mode", ["merge", "replace_all"])
@pytest.mark.parametrize("case", OUT_OF_RANGE, ids=_case_id)
async def test_a_value_outside_its_range_is_a_row_error(http_client, case, mode):
    table, cells, expected = case
    await _assert_refused(http_client, make_archive(_tables(table, cells)), table, expected, mode)
    # Nothing was written: the archive's own retailer, tool or kit never landed.
    assert (await http_client.get("/retailers")).json() == []
    assert (await http_client.get("/kits")).json() == []


@pytest.mark.parametrize("case", AT_THE_BOUND, ids=_case_id)
async def test_the_bound_itself_imports(http_client, case):
    table, cells = case
    archive = make_archive(_tables(table, cells))
    plan = await preview(http_client, archive)
    assert plan["blocking_errors"] == []
    resp = await apply(http_client, archive)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("mode", ["merge", "replace_all"])
async def test_a_retired_header_is_quoted_as_written(http_client, mode):
    """A pre-0.2 export names the conversion snapshot `converted_price_aud_minor`.
    The refusal names that header — the one the file has — not the current name.
    Written by hand: `make_archive` writes the current header and drops the alias."""
    tables = _tables("order_items", {})
    line = dict(tables.pop("order_items")[0])
    archive = make_archive(tables)
    header = [*line, "converted_price_aud_minor"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header)
    writer.writeheader()
    writer.writerow(line | {"converted_price_aud_minor": "-1"})
    buffer = io.BytesIO(archive)
    with zipfile.ZipFile(buffer, "a") as zipped:
        zipped.writestr("order_items.csv", out.getvalue())
    expected = (BELOW, {"field": "converted_price_aud_minor", "value": "-1", "minimum": 0})
    await _assert_refused(http_client, buffer.getvalue(), "order_items", expected, mode)


# --- the update state: a stored row the sheet would overwrite --------------------------


async def test_an_update_out_of_range_leaves_the_stored_row_alone(http_client):
    retailer = (
        await http_client.post("/retailers", json={"name": "Stored Shop", "rating": 4})
    ).json()
    tool = (
        await http_client.post(
            "/tools", json={"name": "Stored Nippers", "category": "cutting", "quantity_on_hand": 2}
        )
    ).json()
    kit = (await http_client.post("/kits", json={"name": "Stored Kit", "grade": "HG"})).json()
    await http_client.patch(f"/kits/{kit['id']}", json={"rating": 3})

    cases = [
        (
            "retailers",
            {"id": retailer["id"], "name": "Stored Shop", "rating": "9"},
            (ABOVE, {"field": "rating", "value": "9", "maximum": 5}),
        ),
        (
            "tools",
            {
                "id": tool["id"],
                "name": "Stored Nippers",
                "category": "cutting",
                "quantity_on_hand": "-3",
            },
            (BELOW, {"field": "quantity_on_hand", "value": "-3", "minimum": 0}),
        ),
        (
            "kits",
            {"id": kit["id"], "name": "Stored Kit", "grade": "HG", "rating": "0"},
            (BELOW, {"field": "rating", "value": "0", "minimum": 1}),
        ),
    ]
    for table, row, expected in cases:
        await _assert_refused(http_client, make_archive({table: [row]}), table, expected, "merge")

    [stored_retailer] = (await http_client.get("/retailers")).json()
    [stored_tool] = (await http_client.get("/tools")).json()
    [stored_kit] = (await http_client.get("/kits")).json()
    assert (stored_retailer["id"], stored_retailer["rating"]) == (retailer["id"], 4)
    assert (stored_tool["id"], stored_tool["quantity_on_hand"]) == (tool["id"], 2)
    assert (stored_kit["id"], stored_kit["rating"]) == (kit["id"], 3)


# --- the starter sheet ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("cells", "field"),
    [({"rating": "7"}, "rating"), ({"unit_price": "-1.00"}, "unit_price")],
    ids=["rating", "unit_price"],
)
async def test_a_starter_sheet_out_of_range_is_refused_not_a_500(http_client, cells, field):
    row = {
        "kit_name": "Starter Range Kit",
        "grade": "HG",
        "status": "complete",
        "quantity": "1",
        "retailer": "Starter Range Shop",
        "order_date": "2026-01-01",
        "unit_price": "10.00",
        "currency": "AUD",
        "received": "yes",
    } | cells
    content = make_csv(list(row), [row])
    plan = await preview(http_client, content, filename="starter-sheet.csv")
    codes = [
        (d["code"], d["params"].get("field"))
        for t in plan["tables"]
        for r in t["rows"]
        for d in r["errors"]
    ] + [(d["code"], d["params"].get("field")) for d in plan["blocking_errors"]]
    assert any(code in (BELOW, ABOVE) and named == field for code, named in codes), codes
    resp = await apply(http_client, content, filename="starter-sheet.csv")
    assert resp.status_code == 409, resp.text
    assert (await http_client.get("/kits")).json() == []


def test_the_ids_in_this_file_are_distinct():
    ids = [RETAILER["id"], ORDER["id"], UPGRADE["id"], KIT["id"], TOOL["id"], LINE["id"]]
    assert len({uuid.UUID(i) for i in ids}) == len(ids)
