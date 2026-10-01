"""The archive's CSV contract, pinned literally against a golden fixture (#303).

`test_portability.py` proves export, import and the templates agree with *each
other* — they all read `spec.py`, so they would go on agreeing through a renamed
column, a byte-order mark or a change of line ending, and every archive written by
an older release, and every other program that reads or writes one, would be broken
by a green CI. The archive is also the only bridge between a standalone client and
this server. So this file pins it to bytes committed in the repository:

* `tests/fixtures/golden/archive/` is an export, member for member, of the
  collection `tests/fixtures/golden/seed.py` builds through the REST surface.
* The headers, the member list and the manifest's keys are written out below as
  literals, never read from `spec.py` — a test that derived them from the code
  under test would agree with any change to it.

**Changing the fixture is a contract change.** Regenerate it with

    GOLDEN_REGENERATE=1 uv run pytest tests/test_golden_archive.py -k reproduces

and the PR says why, and whether `EXPORT_VERSION` moves. The one exception is
`README.txt`, which is prose for people and is never parsed: regenerate it freely.
"""

import csv
import io
import json
import os
import re
import subprocess
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from app import __version__ as app_version
from app.services.portability import exporting, spec
from tests.fixtures.golden.seed import seed
from tests.test_portability import apply, preview

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "archive"
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The archive's members, in the order the export writes them.
MEMBERS = (
    "manifest.json",
    "README.txt",
    "instance_settings.csv",
    "retailers.csv",
    "tools.csv",
    "consumables.csv",
    "upgrades.csv",
    "display_items.csv",
    "orders.csv",
    "order_items.csv",
    "kits.csv",
    "upgrade_applications.csv",
    "kit_photos.csv",
)

#: Every table's header, in column order: the readable mirrors (`retailer_name`,
#: `unit_price`, ...) and the virtual `kit_*` columns included.
HEADERS = {
    "instance_settings": (
        "interface_language",
        "formatting_locale",
        "time_zone",
        "date_style",
        "hour_cycle",
        "reference_currency",
    ),
    "retailers": (
        "id",
        "name",
        "url",
        "rating",
        "packing_quality",
        "shipping_speed",
        "would_order_again",
        "notes",
    ),
    "tools": (
        "id",
        "name",
        "category",
        "quantity_on_hand",
        "unit_cost_reference_minor",
        "unit_cost_reference",
        "unit_cost_reference_currency",
        "condition_notes",
    ),
    "consumables": ("id", "name", "category", "quantity_on_hand", "low_stock_threshold"),
    "upgrades": ("id", "name", "manufacturer", "quantity_on_hand"),
    "display_items": (
        "id",
        "name",
        "category",
        "scale",
        "manufacturer",
        "quantity_on_hand",
        "notes",
    ),
    "orders": (
        "id",
        "retailer_id",
        "retailer_name",
        "order_date",
        "order_number",
        "delivery_service",
        "tracking_number",
        "tracking_url",
        "shipping_cost_minor",
        "shipping_cost",
        "currency_code",
        "shipped_at",
        "received_at",
    ),
    "order_items": (
        "id",
        "order_id",
        "item_type",
        "catalog_ref_id",
        "catalog_name",
        "quantity",
        "unit_price_minor",
        "unit_price",
        "currency_code",
        "converted_price_minor",
        "converted_currency_code",
        "kit_name",
        "kit_grade",
        "kit_scale",
        "kit_number",
        "kit_status",
    ),
    "kits": (
        "id",
        "name",
        "grade",
        "scale",
        "kit_number",
        "series",
        "status",
        "status_updated_at",
        "build_started_at",
        "build_completed_at",
        "rating",
        "build_notes",
        "order_item_id",
        "created_at",
        "updated_at",
    ),
    "upgrade_applications": (
        "id",
        "upgrade_id",
        "upgrade_name",
        "kit_id",
        "quantity_used",
        "applied_at",
    ),
    "kit_photos": ("id", "kit_id", "file_path", "caption", "taken_at", "created_at"),
}

#: The manifest's keys, in order, and the ones whose value is not part of the
#: contract: when it was written, and by which release and schema. Every migration
#: moves `schema_version`, auth-only ones included, so pinning it would make each
#: one look like a format change; a real format change shows in the headers.
MANIFEST_KEYS = (
    "format",
    "export_version",
    "schema_version",
    "app_version",
    "exported_at",
    "tables",
)
VOLATILE_MANIFEST_KEYS = ("schema_version", "app_version", "exported_at")

#: Cell shapes, by (table, column). Written out rather than read off the parsers in
#: `spec.py`; `test_every_typed_column_has_a_pinned_shape` holds the two together.
UUID_COLUMNS = {
    (table, column)
    for table, columns in HEADERS.items()
    for column in columns
    if column == "id" or column.endswith("_id")
}
DATE_COLUMNS = {("orders", "order_date")}
TIMESTAMP_COLUMNS = {
    ("orders", "shipped_at"),
    ("orders", "received_at"),
    ("kits", "status_updated_at"),
    ("kits", "build_started_at"),
    ("kits", "build_completed_at"),
    ("kits", "created_at"),
    ("kits", "updated_at"),
    ("upgrade_applications", "applied_at"),
    ("kit_photos", "taken_at"),
    ("kit_photos", "created_at"),
}
ENUM_COLUMNS = {
    ("instance_settings", "date_style"),
    ("instance_settings", "hour_cycle"),
    ("retailers", "packing_quality"),
    ("retailers", "shipping_speed"),
    ("retailers", "would_order_again"),
    ("order_items", "item_type"),
    ("order_items", "kit_status"),
    ("kits", "status"),
}
#: Major-unit mirror -> (its minor-unit column, the column naming its currency).
MONEY_MIRRORS = {
    ("tools", "unit_cost_reference"): ("unit_cost_reference_minor", "unit_cost_reference_currency"),
    ("orders", "shipping_cost"): ("shipping_cost_minor", "currency_code"),
    ("order_items", "unit_price"): ("unit_price_minor", "currency_code"),
}
#: Tables the export sorts by `name`.
NAME_SORTED = ("retailers", "tools", "consumables", "upgrades", "display_items")
#: ISO 4217 minor-unit exponents of the currencies the fixture uses. Literal, so the
#: test does not borrow the exporter's own table.
EXPONENTS = {"JPY": 0, "AUD": 2, "KWD": 3}

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# `datetime.isoformat()` in UTC: seconds always, microseconds only when non-zero
# (six digits when present), and the offset spelled `+00:00`, never `Z`.
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?\+00:00")
REVISION = re.compile(r"[0-9a-f]{12}")
VERSION = re.compile(r"\d+\.\d+\.\d+")
SNAKE = re.compile(r"[a-z][a-z0-9]*(_[a-z0-9]+)*")


# --- helpers ---------------------------------------------------------------------


def golden_members() -> dict[str, bytes]:
    return {name: (GOLDEN / name).read_bytes() for name in MEMBERS}


def golden_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in golden_members().items():
            archive.writestr(name, content)
    return buffer.getvalue()


def unzip(content: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def rows(table: str) -> list[dict[str, str]]:
    content = (GOLDEN / f"{table}.csv").read_bytes().decode("utf-8")
    return list(csv.DictReader(io.StringIO(content, newline="")))


def assert_volatile_values_are_well_formed(manifest: dict) -> None:
    """The shapes of the values the byte comparison leaves out: an Alembic revision,
    a release version, and the export's instant as UTC `isoformat()`."""
    assert REVISION.fullmatch(manifest["schema_version"]), manifest["schema_version"]
    assert VERSION.fullmatch(manifest["app_version"]), manifest["app_version"]
    assert TIMESTAMP.fullmatch(manifest["exported_at"]), manifest["exported_at"]


def golden_manifest_as_of(produced: bytes) -> bytes:
    """The golden manifest with `produced`'s volatile values written into its text.
    Swapped as text, never re-serialised, so comparing the result with `produced`
    compares every byte of the formatting around them."""
    content = (GOLDEN / "manifest.json").read_text()
    ours, theirs = json.loads(content), json.loads(produced)
    # Excluded from the comparison, not from checking: what the export wrote has to
    # be well-formed and true of this instance before it is swapped in.
    assert_volatile_values_are_well_formed(theirs)
    assert theirs["app_version"] == app_version
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    assert theirs["schema_version"] == head
    for key in VOLATILE_MANIFEST_KEYS:
        stated = f'"{key}": {json.dumps(ours[key])}'
        assert content.count(stated) == 1, key
        content = content.replace(stated, f'"{key}": {json.dumps(theirs[key])}')
    return content.encode()


def assert_matches_golden(members: dict[str, bytes]) -> None:
    golden = golden_members()
    assert tuple(members) == MEMBERS
    assert members["manifest.json"] == golden_manifest_as_of(members["manifest.json"])
    for name in MEMBERS[1:]:
        assert members[name] == golden[name], f"{name} differs from the golden fixture"


# --- the literal contract -----------------------------------------------------------


def test_export_version_is_pinned():
    assert exporting.EXPORT_VERSION == 1
    assert json.loads((GOLDEN / "manifest.json").read_bytes())["export_version"] == 1


def test_every_portable_table_is_pinned():
    """A new portable table is a contract change: it owes a header here."""
    assert tuple(HEADERS) == tuple(s.key for s in spec.TABLE_SPECS)
    assert MEMBERS[2:] == tuple(f"{s.key}.csv" for s in spec.TABLE_SPECS)


@pytest.mark.parametrize("table", HEADERS)
def test_the_header_is_pinned(table):
    assert tuple(spec.SPEC_BY_KEY[table].header) == HEADERS[table]
    first_line = (GOLDEN / f"{table}.csv").read_bytes().split(b"\r\n", 1)[0]
    assert first_line == ",".join(HEADERS[table]).encode("ascii")


def test_the_fixture_holds_exactly_the_archive_members():
    assert sorted(p.name for p in GOLDEN.iterdir()) == sorted(MEMBERS)


def test_the_manifest_is_pinned():
    manifest = json.loads((GOLDEN / "manifest.json").read_bytes())
    assert tuple(manifest) == MANIFEST_KEYS
    assert manifest["format"] == "plamotrack-archive"
    assert tuple(manifest["tables"]) == tuple(HEADERS)
    for table, entry in manifest["tables"].items():
        assert entry == {"file": f"{table}.csv", "rows": len(rows(table))}
    assert_volatile_values_are_well_formed(manifest)


@pytest.mark.parametrize("table", HEADERS)
def test_the_csv_bytes_are_pinned(table):
    """UTF-8 without a byte-order mark, every record ended by CRLF, quoted only when
    a cell needs it. Re-writing the parsed rows with exactly those settings has to
    reproduce the file, which fails on any other line ending or quoting rule."""
    raw = (GOLDEN / f"{table}.csv").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    content = raw.decode("utf-8")
    assert content.endswith("\r\n")
    parsed = list(csv.reader(io.StringIO(content, newline="")))
    out = io.StringIO(newline="")
    csv.writer(out, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n").writerows(parsed)
    assert out.getvalue() == content


def test_the_fixture_exercises_what_the_format_has_to_carry():
    """The pins above are only as good as the cells they read. This is the list of
    edge cases the fixture promises; a regeneration that drops one fails here."""
    every = {table: rows(table) for table in HEADERS}
    cells = [cell for table_rows in every.values() for row in table_rows for cell in row.values()]
    assert all(every[table] for table in HEADERS if table != "kit_photos"), "a table is empty"
    assert any("," in c and '"' in c and "\n" in c for c in cells), "comma + quote + newline"
    assert any(re.search(r"[぀-ヿ一-鿿]", c) for c in cells), "Japanese text"
    assert any(c.startswith("=") for c in cells), "a cell beginning with ="
    assert any(c == "" for c in cells), "a blank optional field"
    stamps = [r[c] for (t, c) in TIMESTAMP_COLUMNS for r in every[t] if r[c]]
    assert any("." in s for s in stamps) and any("." not in s for s in stamps)
    assert {o["currency_code"] for o in every["orders"]} >= set(EXPONENTS)
    assert {k["status"] for k in every["kits"]} >= {
        "pre_ordered",
        "in_transit",
        "backlog",
        "building",
        "complete",
    }
    orders = every["orders"]
    assert any(o["received_at"] for o in orders), "a received order"
    assert any(o["shipped_at"] and not o["received_at"] for o in orders), "a shipped order"
    assert any(not o["shipped_at"] and not o["received_at"] for o in orders), "a placed order"
    assert any(i["item_type"] != "kit" for i in every["order_items"]), "a catalog line"
    assert any(not k["order_item_id"] for k in every["kits"]), "a kit added without an order"
    applied = [a["applied_at"] for a in every["upgrade_applications"]]
    assert len(applied) != len(set(applied)), "two applications at one instant"


@pytest.mark.parametrize("table", HEADERS)
def test_every_cell_has_its_pinned_shape(table):
    """Null is an empty cell; ids are lowercase uuids; enums are snake_case; dates
    are `YYYY-MM-DD`; timestamps are UTC `isoformat()`."""
    for row in rows(table):
        for column, cell in row.items():
            if cell == "":
                continue
            if (table, column) in UUID_COLUMNS:
                assert UUID.fullmatch(cell), (table, column, cell)
            elif (table, column) in DATE_COLUMNS:
                assert DATE.fullmatch(cell), (table, column, cell)
            elif (table, column) in TIMESTAMP_COLUMNS:
                assert TIMESTAMP.fullmatch(cell), (table, column, cell)
                parsed = datetime.fromisoformat(cell)
                assert parsed.utcoffset() == UTC.utcoffset(None)
                assert ("." in cell) == (parsed.microsecond != 0), cell
            elif (table, column) in ENUM_COLUMNS:
                assert SNAKE.fullmatch(cell), (table, column, cell)


def test_readable_amounts_follow_the_currency_exponent():
    seen = set()
    for (table, mirror), (minor_column, currency_column) in MONEY_MIRRORS.items():
        for row in rows(table):
            if row[minor_column] == "":
                assert row[mirror] == "", (table, row)
                continue
            exponent = EXPONENTS[row[currency_column]]
            seen.add(exponent)
            expected = Decimal(int(row[minor_column])).scaleb(-exponent)
            assert row[mirror] == f"{expected:.{exponent}f}", (table, row)
    assert seen == set(EXPONENTS.values()), "every exponent in the fixture is exercised"


def test_every_typed_column_has_a_pinned_shape():
    """The literal shape lists above against the parsers `spec.py` declares — so a
    new dated or enum column cannot slip past the cell checks unpinned."""
    by_parser = {
        spec.parse_uuid: UUID_COLUMNS,
        spec.parse_date: DATE_COLUMNS,
        spec.parse_datetime: TIMESTAMP_COLUMNS,
    }
    for table_spec in spec.TABLE_SPECS:
        for column in table_spec.columns:
            key = (table_spec.key, column.name)
            pinned = by_parser.get(column.parse)
            if pinned is not None:
                assert key in pinned, key
    for table, column in ENUM_COLUMNS | DATE_COLUMNS | TIMESTAMP_COLUMNS:
        assert column in HEADERS[table], (table, column)


@pytest.mark.parametrize("table", NAME_SORTED)
def test_name_order_does_not_depend_on_the_database_collation(table):
    """These tables export in `ORDER BY name`, which follows the database's
    collation, and that differs between a `C` and an `en_US` cluster — and from
    anything a client in another language can reproduce. Row order carries no
    meaning to the importer, so the fixture keeps to names every collation orders
    alike: code-point order and case-folded order agree."""
    names = [row["name"] for row in rows(table)]
    assert names == sorted(names)
    assert names == sorted(names, key=str.casefold)


def test_git_leaves_the_fixture_bytes_alone():
    """`.gitattributes` normalises text to LF on `git add`; the fixture's CRLF would
    not survive it. Asked of git itself, so it fails on a checkout without the rule."""
    out = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "check-attr",
            "text",
            "--",
            *(f"backend/tests/fixtures/golden/archive/{name}" for name in MEMBERS),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.splitlines() == [
        f"backend/tests/fixtures/golden/archive/{name}: text: unset" for name in MEMBERS
    ]


# --- the round trips ----------------------------------------------------------------


async def test_the_export_reproduces_the_fixture(client):
    """The seeded collection exports to the fixture byte for byte, member order and
    manifest formatting included. `GOLDEN_REGENERATE=1` writes it instead."""
    await seed(client)
    members = unzip((await client.get("/export/archive")).content)
    if os.environ.get("GOLDEN_REGENERATE") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for stale in GOLDEN.iterdir():
            stale.unlink()
        for name, content in members.items():
            (GOLDEN / name).write_bytes(content)
        pytest.skip("golden archive regenerated; review the diff")
    assert_matches_golden(members)


async def test_the_fixture_restores_into_an_empty_instance_losslessly(client):
    """Imported into an empty instance, the fixture plans clean and exports back
    unchanged; imported again, it plans and applies as no change at all."""
    archive = golden_zip()
    plan = await preview(client, archive)
    assert plan["blocking_errors"] == []
    assert plan["warnings"] == []
    for table in plan["tables"]:
        # The settings singleton always exists, so restoring it is an update.
        expected = {"update"} if table["table"] == "instance_settings" else {"create"}
        assert {row["action"] for row in table["rows"]} == expected, table["table"]
        assert all(not row["errors"] and not row["messages"] for row in table["rows"])

    resp = await apply(client, archive)
    assert resp.status_code == 200, resp.text
    assert_matches_golden(unzip((await client.get("/export/archive")).content))

    again = await preview(client, archive)
    for table in again["tables"]:
        assert {row["action"] for row in table["rows"]} <= {"unchanged"}, table["table"]
    resp = await apply(client, archive)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert (result["created"], result["updated"], result["kits_spawned"]) == (0, 0, 0)
    assert_matches_golden(unzip((await client.get("/export/archive")).content))


async def test_the_fixture_restores_through_replace_all(client):
    """Over a collection that already holds a record the fixture lacks, a
    `replace_all` restore leaves exactly the fixture behind."""
    await seed(client)
    stray = await client.post("/retailers", json={"name": "A shop the archive never heard of"})
    assert stray.status_code == 201, stray.text
    resp = await apply(client, golden_zip(), mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text
    assert_matches_golden(unzip((await client.get("/export/archive")).content))
