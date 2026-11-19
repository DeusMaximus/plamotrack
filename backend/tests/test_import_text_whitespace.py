"""A stored text value differs from its cell only by what the parser trims (#356).

Rule 10: re-importing your own export changes nothing. The CSV importer reads every
free-text cell through `spec.parse_text`, which drops surrounding whitespace and reads
a blank as no value. Most writers store the text as they were sent it, so a notes box
saved with a trailing newline holds `"…\\n"`, its export says `"…\\n"`, and the cell
reads back as `"…"`. The preview compared the two raw, called the row an update, and
the apply quietly rewrote the stored value.

The comparison is now the parser's: a stored value is unchanged when trimming it the
way `parse_text` trims a cell gives what the cell says. No write path changes and no
stored value moves, including on a row that is an update for some other column.

Every column `parse_text` reads is driven, from a list written here by hand and
checked against the registry, because the rule is the comparison's and a column the
list missed is a column nobody measured. The values are the three the issue measured
on `retailers.notes`, each wrapped around the seeded value, so every column holds
something different from every other column.
"""

import csv
import io
import uuid
import zipfile

import pytest
from sqlalchemy import select, text

from app.db import get_sessionmaker
from app.models import KitPhoto
from app.services.portability import spec
from tests.test_portability import apply, make_archive, preview, read_archive

pytestmark = pytest.mark.anyio

#: Every stored column the importer reads with `parse_text`, by hand (never derived
#: from the registry the test is checking). The values are stored with SQL, so every
#: column holds one whatever its writers do. Measured through REST when this was
#: written, eleven keep surrounding whitespace: `retailers.url` and `.notes`,
#: `orders.order_number`, `.delivery_service`, `.tracking_number` and
#: `.tracking_url`, and `kits.name`, `.grade`, `.scale`, `.kit_number` and
#: `.build_notes`. The rest trim it on the way in, or have no writer yet
#: (`kit_photos`), so there the values stand for a row an older writer or a direct
#: edit left. The comparison cannot tell which writer
#: stored a value, so it is asked about all of them.
TEXT_COLUMNS: list[tuple[str, str]] = [
    ("retailers", "name"),
    ("retailers", "url"),
    ("retailers", "notes"),
    ("tools", "name"),
    ("tools", "category"),
    ("tools", "condition_notes"),
    ("consumables", "name"),
    ("consumables", "category"),
    ("upgrades", "name"),
    ("upgrades", "manufacturer"),
    ("display_items", "name"),
    ("display_items", "category"),
    ("display_items", "scale"),
    ("display_items", "manufacturer"),
    ("display_items", "notes"),
    ("orders", "order_number"),
    ("orders", "delivery_service"),
    ("orders", "tracking_number"),
    ("orders", "tracking_url"),
    ("orders", "notes"),
    ("order_items", "description"),
    ("order_adjustments", "label"),
    ("kits", "name"),
    ("kits", "grade"),
    ("kits", "scale"),
    ("kits", "kit_number"),
    ("kits", "series"),
    ("kits", "build_notes"),
    ("kit_photos", "file_path"),
    ("kit_photos", "caption"),
]

#: The rest of what `parse_text` reads: readable mirrors and the kit details an order
#: line carries for the fan-out. None is a stored column, so none is compared.
NOT_STORED: list[tuple[str, str]] = [
    ("orders", "retailer_name"),
    ("order_items", "catalog_name"),
    ("order_items", "kit_name"),
    ("order_items", "kit_grade"),
    ("order_items", "kit_scale"),
    ("order_items", "kit_number"),
    ("upgrade_applications", "upgrade_name"),
]

#: The listed columns a row cannot leave blank. A cell in one of these that reads as
#: no value is refused when the row is read (`import.rows_unreadable`), before any
#: comparison, so "only spaces" is not stored in them here. Most of their writers
#: refuse a blank too; `kits.name` and `kits.grade` do not, which is a sibling of
#: this issue, not this issue.
REQUIRED: set[tuple[str, str]] = {
    ("retailers", "name"),
    ("tools", "name"),
    ("tools", "category"),
    ("consumables", "name"),
    ("consumables", "category"),
    ("upgrades", "name"),
    ("upgrades", "manufacturer"),
    ("display_items", "name"),
    ("display_items", "category"),
    ("order_adjustments", "label"),
    ("kits", "name"),
    ("kits", "grade"),
    ("kit_photos", "file_path"),
}

#: Not required by the registry, but the seeded order line is an `other` line, whose
#: description the importer requires (#349) and every writer trims and refuses blank.
NEVER_BLANK = REQUIRED | {("order_items", "description")}

TABLES = sorted({table for table, _ in TEXT_COLUMNS})

#: What a writer stored, from the column and its seeded value: the issue's three
#: measured rows. A textarea's trailing newline, a leading indent, and a box of
#: nothing but spaces (which the cell reads as no value at all).
WRAPPED = [
    pytest.param(lambda key, seeded: f"{seeded}\n", id="trailing newline"),
    pytest.param(lambda key, seeded: f"  {seeded}", id="leading spaces"),
    pytest.param(lambda key, seeded: seeded if key in NEVER_BLANK else "   ", id="only spaces"),
    # Not measured by the issue: what else `str.strip` takes, a tab and an
    # ideographic space, so the comparison is seen to trim what the parser trims and
    # not merely ASCII spaces and newlines.
    pytest.param(lambda key, seeded: f"\t{seeded}\u3000", id="tab and ideographic space"),
]


def test_the_lists_are_every_column_parse_text_reads():
    """The hand-written lists against the registry: 30 stored, 7 not, 37 in all,
    13 of the stored ones required."""
    registry = {
        (table.key, column.name)
        for table in spec.TABLE_SPECS
        for column in table.columns
        if column.parse is spec.parse_text
    }
    stored = {
        (table.key, column.name)
        for table in spec.TABLE_SPECS
        for column in table.columns
        if column.parse is spec.parse_text and column.persisted
    }
    required = {
        (table.key, column.name)
        for table in spec.TABLE_SPECS
        for column in table.columns
        if column.parse is spec.parse_text and column.persisted and column.required
    }
    assert len(TEXT_COLUMNS) == len(set(TEXT_COLUMNS)) == 30
    assert len(NOT_STORED) == len(set(NOT_STORED)) == 7
    assert set(TEXT_COLUMNS) == stored
    assert set(TEXT_COLUMNS) | set(NOT_STORED) == registry
    assert len(registry) == 37
    assert REQUIRED == required
    assert len(REQUIRED) == 13


# --- the collection --------------------------------------------------------------


async def _seed(client) -> dict[str, str]:
    """One row in every table with a text column, every text column filled. The
    seeded values are what each column holds before a test wraps it."""

    async def post(path: str, body: dict) -> dict:
        resp = await client.post(path, json=body)
        assert resp.status_code == 201, resp.text
        return resp.json()

    retailer = await post(
        "/retailers",
        {"name": "Hobby Link Japan", "url": "https://shop.example/hlj", "notes": "Fast"},
    )
    await post("/tools", {"name": "Side cutter", "category": "cutting", "condition_notes": "Sharp"})
    await post("/consumables", {"name": "Gundam Marker GM01", "category": "marker"})
    await post("/upgrades", {"name": "Metal thrusters", "manufacturer": "Madworks"})
    await post(
        "/display-items",
        {
            "name": "Action Base 1",
            "category": "stand",
            "scale": "1/144",
            "manufacturer": "Bandai",
            "notes": "Clear",
        },
    )
    await post(
        "/orders",
        {
            "retailer_id": retailer["id"],
            "order_date": "2026-03-14",
            "order_number": "HLJ-88213",
            "delivery_service": "EMS",
            "tracking_number": "EE123456789JP",
            "tracking_url": "https://track.example/EE123456789JP",
            "notes": "Gift wrapped",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "other",
                    "description": "Shipping insurance",
                    "quantity": 1,
                    "unit_price_minor": 1000,
                    "currency_code": "AUD",
                }
            ],
            "adjustments": [{"label": "SPRING10", "amount_minor": 100}],
        },
    )
    kit = await post(
        "/kits",
        {
            "name": "Zaku II",
            "grade": "HG",
            "scale": "1/144",
            "kit_number": "241",
            "series": "Mobile Suit Gundam",
            "build_notes": "Panel lined",
        },
    )
    # No writer adds a photo yet (Milestone 7), so the one row is inserted.
    async with get_sessionmaker()() as session:
        await session.execute(
            text(
                "INSERT INTO kit_photos (id, kit_id, file_path, caption) "
                "VALUES (:id, :kit_id, 'photos/zaku.jpg', 'Finished')"
            ),
            {"id": uuid.uuid4(), "kit_id": kit["id"]},
        )
        await session.commit()
    return await _stored()


async def _stored() -> dict[tuple[str, str], str | None]:
    """Every listed column's one stored value, read from the database."""
    values: dict[tuple[str, str], str | None] = {}
    async with get_sessionmaker()() as session:
        for table, column in TEXT_COLUMNS:
            name = spec.SPEC_BY_KEY[table].model.__tablename__
            rows = (await session.execute(text(f"SELECT {column} FROM {name}"))).all()
            assert len(rows) == 1, (table, rows)
            values[(table, column)] = rows[0][0]
    return values


async def _store(values: dict[tuple[str, str], str]) -> None:
    """Write text the way a writer that keeps whitespace would have stored it."""
    async with get_sessionmaker()() as session:
        for (table, column), value in values.items():
            name = spec.SPEC_BY_KEY[table].model.__tablename__
            await session.execute(text(f"UPDATE {name} SET {column} = :value"), {"value": value})
        await session.commit()


async def _wrapped_collection(client, wrap) -> dict[tuple[str, str], str]:
    seeded = await _seed(client)
    assert all(seeded.values()), seeded  # every column filled, so a wrap has a seed
    stored = {key: wrap(key, value) for key, value in seeded.items()}
    await _store(stored)
    assert await _stored() == stored  # what the export below will carry
    return stored


async def _export(client) -> bytes:
    """This instance's export, with its photo row written in.

    The exporter leaves `kit_photos.csv` empty until photos land (Milestone 7),
    while the importer already reads the sheet. The row is rendered the way the
    exporter renders every other table, `TableSpec.to_row`, and every other member
    of the archive is passed through as exported.
    """
    resp = await client.get("/export/archive")
    assert resp.status_code == 200
    async with get_sessionmaker()() as session:
        photos = (await session.scalars(select(KitPhoto))).all()
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=spec.KIT_PHOTOS.header)
    writer.writeheader()
    writer.writerows(spec.KIT_PHOTOS.to_row(photo) for photo in photos)
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(resp.content)) as exported,
        zipfile.ZipFile(buffer, "w") as archive,
    ):
        assert exported.read("kit_photos.csv").decode().splitlines()[1:] == []
        for name in exported.namelist():
            if name != "kit_photos.csv":
                archive.writestr(name, exported.read(name))
        archive.writestr("kit_photos.csv", out.getvalue())
    return buffer.getvalue()


def _rows(plan: dict) -> dict[str, list[dict]]:
    return {entry["table"]: entry["rows"] for entry in plan["tables"]}


def _changed_fields(plan: dict) -> dict[str, list[tuple[str, str, str]]]:
    return {
        table: [(c["field"], c["before"], c["after"]) for row in rows for c in row["changes"]]
        for table, rows in _rows(plan).items()
    }


# --- a value the parser would trim is unchanged ----------------------------------


@pytest.mark.parametrize("wrap", WRAPPED)
async def test_merging_your_own_export_leaves_whitespace_around_stored_text(client, wrap):
    stored = await _wrapped_collection(client, wrap)
    content = await _export(client)

    plan = await preview(client, content, mode="merge")
    assert plan["blocking_errors"] == []
    # Before the actions, so a red run names every column the comparison misreads.
    assert {table: fields for table, fields in _changed_fields(plan).items() if fields} == {}
    rows = _rows(plan)
    for table in TABLES:
        assert [row["action"] for row in rows[table]] == ["unchanged"], table
        assert all(not row["errors"] for row in rows[table]), rows[table]

    resp = await apply(client, content, mode="merge")
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 0
    assert resp.json()["created"] == 0
    assert await _stored() == stored  # no stored value moved


async def test_a_row_that_updates_another_column_leaves_the_text_as_stored(client):
    """An update writes only what it lists. A column whose stored value differs from
    the cell by whitespace alone is not listed, so it is not rewritten either."""
    stored = await _wrapped_collection(client, lambda key, seeded: f"{seeded}\n")
    tables = read_archive(await _export(client))
    tables["retailers"][0]["rating"] = "4"
    tables["kits"][0]["rating"] = "5"

    plan = await preview(client, make_archive(tables), mode="merge")
    changed = _changed_fields(plan)
    assert changed["retailers"] == [("rating", "", "4")]
    assert changed["kits"] == [("rating", "", "5")]
    assert {table: fields for table, fields in changed.items() if fields} == {
        "retailers": [("rating", "", "4")],
        "kits": [("rating", "", "5")],
    }

    resp = await apply(client, make_archive(tables), mode="merge")
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 2
    assert await _stored() == stored


# --- a value that genuinely differs is still an update ---------------------------


def _edited(tables: dict[str, list[dict[str, str]]]) -> dict[tuple[str, str], str]:
    """Every listed cell rewritten to something its stored value is not, in place."""
    edits = {}
    for table, column in TEXT_COLUMNS:
        cell = tables[table][0]
        cell[column] = edits[(table, column)] = f"{cell[column].strip()} (edited)"
    return edits


async def test_a_cell_that_differs_still_previews_an_update_in_merge(client):
    stored = await _wrapped_collection(client, lambda key, seeded: f"  {seeded}\n")
    tables = read_archive(await _export(client))
    edits = _edited(tables)
    content = make_archive(tables)

    plan = await preview(client, content, mode="merge")
    assert plan["blocking_errors"] == []
    rows = _rows(plan)
    changed = _changed_fields(plan)
    for table in TABLES:
        assert [row["action"] for row in rows[table]] == ["update"], table
        # `before` is the value as stored, whitespace and all: the preview shows
        # what the apply replaces.
        assert sorted(changed[table]) == sorted(
            (column, stored[(t, column)], edits[(t, column)])
            for t, column in TEXT_COLUMNS
            if t == table
        ), table

    resp = await apply(client, content, mode="merge")
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == len(TABLES)
    assert await _stored() == edits


async def test_replace_all_recreates_every_row_from_its_cells(client):
    """replace_all compares nothing: every row is a create from the sheet, so an
    edited cell lands as written, and a cell that only trims lands trimmed. That is
    the parser's reading, not the comparison's, and it is pinned here so a change
    to it is seen."""
    stored = await _wrapped_collection(client, lambda key, seeded: f"  {seeded}\n")
    tables = read_archive(await _export(client))
    edits = _edited(tables)
    trimmed_kit_name = tables["kits"][0]["name"] = stored[("kits", "name")]
    edits[("kits", "name")] = trimmed_kit_name.strip()
    content = make_archive(tables)

    plan = await preview(client, content, mode="replace_all")
    assert plan["blocking_errors"] == []
    rows = _rows(plan)
    for table in TABLES:
        assert [row["action"] for row in rows[table]] == ["create"], table

    resp = await apply(client, content, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text
    assert await _stored() == edits


# --- the archive itself ----------------------------------------------------------


async def test_the_export_carries_the_whitespace_it_was_given(client):
    """The other half of the round trip: the cell holds the stored value exactly,
    so the trimming the preview forgives happens in the parser, not the export.
    (`_export` writes the photo row the exporter does not yet carry.)"""
    stored = await _wrapped_collection(client, lambda key, seeded: f"  {seeded}\n")
    with zipfile.ZipFile(io.BytesIO(await _export(client))) as archive:
        for table in TABLES:
            rows = list(csv.DictReader(io.StringIO(archive.read(f"{table}.csv").decode())))
            for (t, column), value in stored.items():
                if t == table:
                    assert rows[0][column] == value, (table, column)
