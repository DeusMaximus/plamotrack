"""Import/export: round-trip fidelity, idempotency, and not duplicating things.

The duplication tests are the point of the feature — an import that quietly
doubles someone's order history is worse than no import at all.
"""

import asyncio
import csv
import io
import json
import pathlib
import time
import tomllib
import uuid
import zipfile

import pytest
from sqlalchemy import text as sa_text

from app import __version__ as app_version
from app.db import session_scope
from app.models import Retailer
from app.services import orders
from app.services.portability import exporting, importing, spec, starter_sheet

# --- helpers --------------------------------------------------------------------


def read_archive(content: bytes) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if name.endswith(".csv"):
                text = archive.read(name).decode("utf-8")
                tables[name.removesuffix(".csv")] = list(csv.DictReader(io.StringIO(text)))
    return tables


def read_manifest(content: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return json.loads(archive.read("manifest.json"))


def make_archive(tables: dict[str, list[dict[str, str]]], *, manifest: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                manifest
                or {"format": "plamotrack-archive", "export_version": exporting.EXPORT_VERSION}
            ),
        )
        for key, rows in tables.items():
            header = spec.SPEC_BY_KEY[key].header
            out = io.StringIO()
            writer = csv.DictWriter(out, fieldnames=header, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(f"{key}.csv", out.getvalue())
    return buffer.getvalue()


def make_csv(header: list[str], rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


async def preview(client, content: bytes, *, mode="merge", filename="archive.zip") -> dict:
    resp = await client.post(
        "/import/preview",
        files={"file": (filename, content, "application/octet-stream")},
        data={"mode": mode},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def apply(client, content: bytes, *, mode="merge", filename="archive.zip", **extra):
    """Preview, then apply exactly what the preview showed.

    The hash is mandatory (#41), so an apply is always a two-step. Pass
    `plan_hash=` explicitly to drive the stale-hash and missing-hash paths on
    purpose; leaving it off exercises the honest round trip, which is also the
    standing check that the fingerprint is stable across two runs of the same
    file — the id-less sheets in this module mint fresh uuids on every plan.
    """
    if "plan_hash" not in extra:
        seen = await client.post(
            "/import/preview",
            files={"file": (filename, content, "application/octet-stream")},
            data={"mode": mode},
        )
        # A file the preview itself rejects has no hash to quote. Send none and
        # let the apply answer for it, rather than masking the status under test.
        extra["plan_hash"] = seen.json().get("plan_hash", "") if seen.status_code == 200 else ""
    data = {"mode": mode, **extra}
    return await client.post(
        "/import/apply",
        files={"file": (filename, content, "application/octet-stream")},
        data=data,
    )


async def _a_writer_is_parked_on_the_gate() -> bool:
    """Whether Postgres currently has someone blocked on the collection write gate
    (#80). Asked from a separate connection, so it observes the server's own view
    rather than anything this test arranged."""
    async with session_scope() as probe:
        blocked = await probe.scalar(
            sa_text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND wait_event = 'advisory'"
            )
        )
    return bool(blocked)


def actions(plan: dict, table: str) -> list[str]:
    for entry in plan["tables"]:
        if entry["table"] == table:
            return [row["action"] for row in entry["rows"]]
    return []


async def seed_collection(client) -> dict:
    """A realistic little collection: one retailer, one received order with a
    2-kit line and a consumable line, plus a standalone tool."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-88213",
                "currency_code": "AUD",
                "received": True,
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 2,
                        "unit_price_minor": 2450,
                        "currency_code": "AUD",
                        "kit": {
                            "name": "RX-79(G) Ground Type",
                            "grade": "HG",
                            "kit_number": "HGUC 210",
                        },
                    },
                    {
                        "item_type": "consumable",
                        "quantity": 3,
                        "unit_price_minor": 500,
                        "currency_code": "AUD",
                        "new_item": {"name": "Gundam Marker GM02", "category": "paint"},
                    },
                ],
            },
        )
    ).json()
    tool = (
        await client.post(
            "/tools",
            json={"name": "Godhand Ultimate Nippers", "category": "cutting", "quantity_on_hand": 1},
        )
    ).json()
    # Standalone rather than a third order line: the round-trip tests here assert on
    # order-line counts, and this exists to prove the table survives an archive, not
    # to restate the dispatch (which test_orders covers). `scale` is set because it
    # is the one column no sibling table has — a spec entry that omitted it would
    # round-trip a null and every other assertion would still hold.
    display_item = (
        await client.post(
            "/display-items",
            json={
                "name": "Action Base 2",
                "category": "stand",
                "scale": "1/144",
                "quantity_on_hand": 4,
            },
        )
    ).json()
    return {
        "retailer": retailer,
        "order": order,
        "tool": tool,
        "display_item": display_item,
    }


async def snapshot(client) -> dict:
    return {
        "kits": sorted(
            (k["name"], k["grade"], k["status"]) for k in (await client.get("/kits")).json()
        ),
        "retailers": sorted(r["name"] for r in (await client.get("/retailers")).json()),
        "consumables": sorted(
            (c["name"], c["quantity_on_hand"]) for c in (await client.get("/consumables")).json()
        ),
        "tools": sorted(
            (t["name"], t["quantity_on_hand"]) for t in (await client.get("/tools")).json()
        ),
        "display_items": sorted(
            (d["name"], d["category"], d["scale"], d["quantity_on_hand"])
            for d in (await client.get("/display-items")).json()
        ),
        "orders": sorted(
            (o["order_number"], len(o["items"])) for o in (await client.get("/orders")).json()
        ),
    }


# --- export ---------------------------------------------------------------------


async def test_export_archive_has_manifest_and_every_table(client):
    await seed_collection(client)
    resp = await client.get("/export/archive")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    manifest = read_manifest(resp.content)
    assert manifest["format"] == "plamotrack-archive"
    assert manifest["export_version"] == exporting.EXPORT_VERSION
    # The live Alembic revision, so an importer can tell which schema wrote this.
    assert manifest["schema_version"]
    assert manifest["tables"]["kits"]["rows"] == 2

    tables = read_archive(resp.content)
    assert set(tables) == {table.key for table in spec.TABLE_SPECS}
    assert len(tables["kits"]) == 2
    assert tables["orders"][0]["retailer_name"] == "Hobby Link Japan"
    # Money stays canonical in minor units, with a readable major-unit twin.
    kit_line = next(row for row in tables["order_items"] if row["item_type"] == "kit")
    assert kit_line["unit_price_minor"] == "2450"
    assert kit_line["unit_price"] == "24.50"
    assert kit_line["kit_name"] == "RX-79(G) Ground Type"


async def test_export_single_table_csv(client):
    await seed_collection(client)
    resp = await client.get("/export/kits.csv")
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [row["name"] for row in rows] == ["RX-79(G) Ground Type"] * 2


async def test_unknown_table_export_is_404(client):
    assert (await client.get("/export/nonsense.csv")).status_code == 404


# --- round trip -----------------------------------------------------------------


async def test_archive_round_trips_through_replace_all(client):
    await seed_collection(client)
    before = await snapshot(client)
    archive = (await client.get("/export/archive")).content

    resp = await apply(client, archive, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows_deleted"]["kits"] == 2

    assert await snapshot(client) == before


async def test_archive_restores_into_an_empty_instance(client):
    await seed_collection(client)
    before = await snapshot(client)
    archive = (await client.get("/export/archive")).content

    # Wipe by hand, then restore — the migration path onto a fresh instance. Every
    # standalone table the seed touches has to go, or the restore is never asked to
    # bring it back and the assertion below passes on a row that simply never left.
    for order in (await client.get("/orders")).json():
        assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    for tool in (await client.get("/tools")).json():
        await client.delete(f"/tools/{tool['id']}")
    for display_item in (await client.get("/display-items")).json():
        assert (await client.delete(f"/display-items/{display_item['id']}")).status_code == 204
    assert (await client.get("/kits")).json() == []
    assert (await client.get("/display-items")).json() == []

    resp = await apply(client, archive)
    assert resp.status_code == 200, resp.text
    assert await snapshot(client) == before


# --- idempotency ----------------------------------------------------------------


async def test_merge_import_is_idempotent(client):
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content
    before = await snapshot(client)

    first = await apply(client, archive)
    assert first.status_code == 200, first.text
    assert await snapshot(client) == before

    plan = await preview(client, archive)
    for table in (
        "retailers",
        "orders",
        "order_items",
        "kits",
        "consumables",
        "tools",
        "display_items",
    ):
        assert set(actions(plan, table)) <= {"unchanged"}, f"{table} would change on re-import"

    second = await apply(client, archive)
    assert second.status_code == 200, second.text
    assert second.json()["created"] == 0
    assert await snapshot(client) == before


async def test_add_only_skips_everything_that_exists(client):
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content
    before = await snapshot(client)

    plan = await preview(client, archive, mode="add_only")
    assert set(actions(plan, "retailers")) == {"skip"}
    assert set(actions(plan, "kits")) == {"skip"}

    resp = await apply(client, archive, mode="add_only")
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 0
    assert await snapshot(client) == before


# --- matching -------------------------------------------------------------------


async def test_retailer_matched_case_insensitively(client):
    await client.post("/retailers", json={"name": "Hobby Link Japan"})
    content = make_csv(
        spec.RETAILERS.header,
        [{"id": "", "name": "hobby link japan", "url": "https://hlj.com"}],
    )

    plan = await preview(client, content, filename="retailers.csv")
    row = plan["tables"][0]["rows"][0]
    assert row["action"] == "update"
    assert row["matched_by"] == "name"

    assert (await apply(client, content, filename="retailers.csv")).status_code == 200
    retailers = (await client.get("/retailers")).json()
    assert len(retailers) == 1
    assert retailers[0]["url"] == "https://hlj.com"


async def test_order_matched_by_retailer_and_order_number(client):
    seeded = await seed_collection(client)
    archive = read_archive((await client.get("/export/archive")).content)

    # Same order, described by a different instance: no ids anywhere.
    for row in archive["orders"]:
        row["id"] = ""
        row["retailer_id"] = ""
    for row in archive["order_items"]:
        row["id"] = ""
    del archive["order_items"]  # lines are matched via their parent; test the header alone
    del archive["kits"]

    plan = await preview(client, make_archive(archive))
    order_row = next(r for r in plan["tables"] if r["table"] == "orders")["rows"][0]
    assert order_row["matched_by"] == "retailer + order number"
    assert order_row["matched_id"] == seeded["order"]["id"]

    assert (await apply(client, make_archive(archive))).status_code == 200
    assert len((await client.get("/orders")).json()) == 1


async def test_order_matched_by_fingerprint_when_no_order_number(client):
    """The same purchase, described by an instance that never knew our uuids and
    has no retailer reference number to go on — date plus lines has to carry it."""
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    existing = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-04-01",
                "currency_code": "AUD",
                "received": True,
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
    ).json()

    foreign_order = "33333333-3333-4333-8333-333333333333"
    archive = make_archive(
        {
            # Retailer arrives by name only — it must resolve to ours, not duplicate.
            "retailers": [{"id": "", "name": "gundam base"}],
            "orders": [
                {
                    "id": foreign_order,
                    "retailer_name": "Gundam Base",
                    "order_date": "2026-04-01",
                    "order_number": "",
                    "currency_code": "AUD",
                    "received_at": "2026-04-08T00:00:00+00:00",
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
    order_row = next(r for r in plan["tables"] if r["table"] == "orders")["rows"][0]
    assert order_row["matched_by"] == "retailer + date + lines"
    assert order_row["matched_id"] == existing["id"]
    assert plan["derived"]["kits_spawned"] == 0  # the kit is already here

    assert (await apply(client, archive)).status_code == 200
    assert len((await client.get("/orders")).json()) == 1
    assert len((await client.get("/retailers")).json()) == 1
    assert len((await client.get("/kits")).json()) == 1


async def test_kits_are_never_matched_by_name(client):
    """Two of the same kit are two kits — name matching would silently merge them."""
    await client.post("/kits", json={"name": "RX-78-2 Gundam", "grade": "MG"})
    content = make_csv(
        spec.KITS.header, [{"id": "", "name": "RX-78-2 Gundam", "grade": "MG", "status": "backlog"}]
    )

    plan = await preview(client, content, filename="kits.csv")
    row = plan["tables"][0]["rows"][0]
    assert row["action"] == "create"
    assert row["matched_id"] is None
    assert any("already have 1 kit" in message for message in row["messages"])

    assert (await apply(client, content, filename="kits.csv")).status_code == 200
    assert len((await client.get("/kits")).json()) == 2


# --- hybrid dispatch ------------------------------------------------------------


async def test_kit_line_spawns_kits_when_the_import_has_none(client):
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    archive = make_archive(
        {
            "orders": [
                {
                    "id": "11111111-1111-4111-8111-111111111111",
                    "retailer_id": retailer["id"],
                    "order_date": "2026-05-02",
                    "order_number": "GB-1",
                    "currency_code": "AUD",
                    "received_at": "2026-05-09T00:00:00+00:00",
                }
            ],
            "order_items": [
                {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "order_id": "11111111-1111-4111-8111-111111111111",
                    "item_type": "kit",
                    "quantity": "3",
                    "unit_price_minor": "1999",
                    "currency_code": "AUD",
                    "kit_name": "Gouf Custom",
                    "kit_grade": "HG",
                    "kit_status": "backlog",
                }
            ],
        }
    )

    plan = await preview(client, archive)
    assert plan["derived"]["kits_spawned"] == 3

    resp = await apply(client, archive)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_spawned"] == 3
    kits = (await client.get("/kits")).json()
    assert len(kits) == 3
    # Scale still derives from the grade, exactly as order entry would.
    assert {kit["scale"] for kit in kits} == {"1/144"}


async def test_kit_line_does_not_spawn_when_kits_are_in_the_archive(client):
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content

    plan = await preview(client, archive, mode="replace_all")
    assert plan["derived"]["kits_spawned"] == 0
    # Replace-all deletes the existing kits first, so "you already have one of
    # these" would be actively misleading here.
    kit_rows = next(t for t in plan["tables"] if t["table"] == "kits")["rows"]
    assert all(row["messages"] == [] for row in kit_rows)

    resp = await apply(client, archive, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_spawned"] == 0
    assert len((await client.get("/kits")).json()) == 2


async def test_import_never_changes_stock(client):
    """Stock is stated in the catalog files, never re-derived from received orders —
    otherwise a re-import silently doubles what you think you own."""
    await seed_collection(client)
    before = {c["name"]: c["quantity_on_hand"] for c in (await client.get("/consumables")).json()}
    assert before["Gundam Marker GM02"] == 3

    archive = (await client.get("/export/archive")).content
    plan = await preview(client, archive)
    assert plan["derived"]["stock_changes"] == 0

    assert (await apply(client, archive)).status_code == 200
    after = {c["name"]: c["quantity_on_hand"] for c in (await client.get("/consumables")).json()}
    assert after == before


# --- starter sheet --------------------------------------------------------------


async def test_starter_sheet_expands_into_retailers_orders_and_kits(client):
    sheet = make_csv(
        starter_sheet.STARTER_SHEET_HEADER,
        [
            {
                "kit_name": "RX-79(G) Ground Type",
                "grade": "HG",
                "status": "backlog",
                "quantity": "1",
                "retailer": "Hobby Link Japan",
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "unit_price": "24.50",
                "currency": "AUD",
                "received": "yes",
            },
            {
                "kit_name": "Sazabi Ver.Ka",
                "grade": "MG",
                "status": "building",
                "quantity": "1",
                "retailer": "Hobby Link Japan",
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "unit_price": "112.00",
                "currency": "AUD",
                "received": "yes",
            },
            {"kit_name": "RX-78-2 Ver.3.0", "grade": "MG", "status": "complete", "rating": "5"},
        ],
    )

    plan = await preview(client, sheet, filename="starter-sheet.csv")
    assert plan["source"] == "starter-sheet"
    assert plan["derived"]["kits_spawned"] == 2  # the two order-backed rows

    resp = await apply(client, sheet, filename="starter-sheet.csv")
    assert resp.status_code == 200, resp.text

    # Two rows sharing a retailer, date, and number collapse into ONE order.
    orders = (await client.get("/orders")).json()
    assert len(orders) == 1
    assert len(orders[0]["items"]) == 2
    assert orders[0]["received_at"] is not None

    kits = {k["name"]: k for k in (await client.get("/kits")).json()}
    assert set(kits) == {"RX-79(G) Ground Type", "Sazabi Ver.Ka", "RX-78-2 Ver.3.0"}
    assert kits["Sazabi Ver.Ka"]["status"] == "building"
    assert kits["RX-78-2 Ver.3.0"]["rating"] == 5
    assert len((await client.get("/retailers")).json()) == 1
    # Major-unit price converted to canonical minor units.
    kit_line = next(i for i in orders[0]["items"] if i["quantity"] == 1)
    assert kit_line["unit_price_minor"] in (2450, 11200)


async def test_starter_sheet_does_not_erase_fields_it_says_nothing_about(client):
    """The flat sheet knows a retailer's name and nothing else. Importing a kit list
    must not blank the report card off a shop you've already rated."""
    created = (
        await client.post(
            "/retailers",
            json={
                "name": "Hobby Link Japan",
                "rating": 5,
                "notes": "fast",
                "url": "https://hlj.com",
            },
        )
    ).json()
    sheet = make_csv(
        starter_sheet.STARTER_SHEET_HEADER,
        [
            {
                "kit_name": "Sazabi Ver.Ka",
                "grade": "MG",
                "quantity": "1",
                "retailer": "Hobby Link Japan",
                "order_date": "2026-06-01",
                "order_number": "HLJ-99001",
                "unit_price": "112.00",
                "currency": "AUD",
            }
        ],
    )

    plan = await preview(client, sheet, filename="starter-sheet.csv")
    retailer_row = next(t for t in plan["tables"] if t["table"] == "retailers")["rows"][0]
    assert retailer_row["action"] == "unchanged"
    assert retailer_row["changes"] == []

    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200
    after = (await client.get("/retailers")).json()[0]
    assert after["id"] == created["id"]
    assert (after["rating"], after["notes"], after["url"]) == (5, "fast", "https://hlj.com")


async def test_starter_sheet_reimport_does_not_duplicate_orders(client):
    sheet = make_csv(
        starter_sheet.STARTER_SHEET_HEADER,
        [
            {
                "kit_name": "Gouf Custom",
                "grade": "HG",
                "quantity": "1",
                "retailer": "Gundam Base",
                "order_date": "2026-05-02",
                "order_number": "GB-1",
                "unit_price": "19.99",
                "currency": "AUD",
            }
        ],
    )
    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200
    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200

    assert len((await client.get("/orders")).json()) == 1
    assert len((await client.get("/retailers")).json()) == 1
    assert len((await client.get("/kits")).json()) == 1


# --- safety -------------------------------------------------------------------


async def test_plan_hash_mismatch_is_rejected(client):
    await client.post("/retailers", json={"name": "Gundam Base"})
    content = make_csv(spec.RETAILERS.header, [{"id": "", "name": "Gundam Base", "notes": "good"}])
    plan = await preview(client, content, filename="retailers.csv")

    # Somebody edits the same retailer between preview and apply.
    retailer = (await client.get("/retailers")).json()[0]
    await client.patch(f"/retailers/{retailer['id']}", json={"notes": "good"})

    resp = await apply(client, content, filename="retailers.csv", plan_hash=plan["plan_hash"])
    assert resp.status_code == 409
    assert "run the preview again" in resp.json()["detail"]


async def test_matching_plan_hash_is_accepted(client):
    content = make_csv(spec.RETAILERS.header, [{"id": "", "name": "Gundam Base"}])
    plan = await preview(client, content, filename="retailers.csv")
    resp = await apply(client, content, filename="retailers.csv", plan_hash=plan["plan_hash"])
    assert resp.status_code == 200, resp.text


async def test_one_bad_row_blocks_the_whole_import(client):
    content = make_csv(
        spec.KITS.header,
        [
            {"id": "", "name": "Good Kit", "grade": "HG", "status": "backlog"},
            {"id": "", "name": "Bad Kit", "grade": "HG", "status": "definitely-not-a-status"},
        ],
    )
    plan = await preview(client, content, filename="kits.csv")
    assert plan["blocking_errors"]
    assert actions(plan, "kits") == ["create", "error"]

    resp = await apply(client, content, filename="kits.csv")
    assert resp.status_code == 409
    assert (await client.get("/kits")).json() == []  # not even the good row


async def test_replace_all_requires_typed_confirmation(client):
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content

    resp = await apply(client, archive, mode="replace_all")
    assert resp.status_code == 422
    assert "REPLACE" in resp.json()["detail"]
    assert len((await client.get("/kits")).json()) == 2  # untouched


async def test_newer_export_version_is_refused(client):
    archive = make_archive(
        {"retailers": [{"id": "", "name": "Future Shop"}]},
        manifest={"format": "plamotrack-archive", "export_version": exporting.EXPORT_VERSION + 1},
    )
    resp = await client.post(
        "/import/preview",
        files={"file": ("archive.zip", archive, "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422
    assert "newer version" in resp.json()["detail"]


async def test_unknown_file_is_rejected_clearly(client):
    resp = await client.post(
        "/import/preview",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422


# --- templates ------------------------------------------------------------------


async def test_template_pack_headers_match_the_export_exactly(client):
    """Guards the whole point of the shared spec registry: a template can never
    describe a column the exporter doesn't write or the importer won't read."""
    resp = await client.get("/export/templates")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
        names = set(archive.namelist())
        assert "COLUMNS.txt" in names
        assert "starter-sheet.csv" in names
        for table in spec.TABLE_SPECS:
            assert table.filename in names
            header = next(csv.reader(io.StringIO(archive.read(table.filename).decode("utf-8"))))
            assert header == table.header

            exported = await client.get(f"/export/{table.key}.csv")
            assert next(csv.reader(io.StringIO(exported.text))) == table.header


async def test_starter_sheet_template_is_importable_as_is(client):
    """The examples shipped in the template have to actually work."""
    resp = await client.get("/export/starter-sheet.csv")
    assert resp.status_code == 200
    applied = await apply(client, resp.content, filename="starter-sheet.csv")
    assert applied.status_code == 200, applied.text
    assert len((await client.get("/kits")).json()) == 3


# --- minor units through the CSV layer (#6) -------------------------------------
#
# The conversions themselves are unit-tested in tests/test_currency.py. What these
# cover is the layer above: that the major-unit column and the export read the
# exponent off the row's *own* currency, so an archive comes back worth what it went
# in worth.


def _order_row(retailer: dict, code: str, **extra) -> dict:
    return {
        "id": "",
        "retailer_id": retailer["id"],
        "order_date": "2026-08-01",
        "currency_code": code,
        **extra,
    }


@pytest.mark.parametrize(
    ("code", "major", "minor"),
    [
        ("KWD", "1.234", 1234),  # 3 decimals — used to import as 123
        ("CLF", "1.2345", 12345),  # 4 decimals — a factor of 100 out
        ("JPY", "1200", 1200),
        ("AUD", "49.99", 4999),
    ],
)
async def test_order_line_money_round_trips_in_its_own_currency(
    client, retailer, code, major, minor
):
    content = make_csv(
        spec.ORDERS.header,
        [_order_row(retailer, code)],
    )
    assert (await apply(client, content, filename="orders.csv")).status_code == 200
    order_id = (await client.get("/orders")).json()[0]["id"]

    # In through the major-unit column, which is the half a human types.
    lines = make_csv(
        spec.ORDER_ITEMS.header,
        [
            {
                "id": "",
                "order_id": order_id,
                "item_type": "tool",
                "catalog_name": "Godhand nippers",
                "quantity": "1",
                "unit_price": major,
                "currency_code": code,
            }
        ],
    )
    applied = await apply(client, lines, filename="order_items.csv")
    assert applied.status_code == 200, applied.text

    stored = (await client.get(f"/orders/{order_id}")).json()["items"][0]
    assert stored["unit_price_minor"] == minor
    assert stored["currency_code"] == code

    # ...and out again, unchanged.
    exported = read_archive((await client.get("/export/archive")).content)
    row = exported["order_items"][0]
    assert row["unit_price_minor"] == str(minor)
    assert row["unit_price"] == major


async def test_unknown_currency_is_accepted_with_a_warning(client, retailer):
    """Rejecting it would strand an instance already holding one; saying nothing is
    how a typo'd code quietly becomes a wrong amount. So: accept, and say so."""
    content = make_csv(
        spec.ORDERS.header,
        # "AUS" is one keystroke from AUD, and not a currency.
        [_order_row(retailer, "AUS", shipping_cost="12.50")],
    )

    plan = await preview(client, content, filename="orders.csv")
    row = plan["tables"][0]["rows"][0]
    assert row["action"] == "create"
    assert any("isn't a currency code we recognise" in message for message in row["messages"])

    assert (await apply(client, content, filename="orders.csv")).status_code == 200
    order = (await client.get("/orders")).json()[0]
    assert order["currency_code"] == "AUS"
    assert order["shipping_cost_minor"] == 1250  # the documented 2-decimal default


async def test_known_currency_import_is_not_warned_about(client, retailer):
    content = make_csv(
        spec.ORDERS.header,
        [_order_row(retailer, "KWD")],
    )
    plan = await preview(client, content, filename="orders.csv")
    assert plan["tables"][0]["rows"][0]["messages"] == []


# --- the preview is binding (#41) ------------------------------------------------
#
# Every test below drives a *value* the old fingerprint could not see. It read
# `(row_number, action, matched_id, changes)`, so a CREATE contributed only its
# position and the word "create" — two different files of the same shape hashed
# identically. Asserting a mismatched hash is rejected proves nothing here: that
# path always worked. The cases that matter are the ones where the shape is equal
# and the content is not.


def _retailer_sheet(name: str) -> bytes:
    """One id-less create. Same shape every time, so only the value can move the hash."""
    return make_csv(spec.RETAILERS.header, [{"name": name, "country": "JP"}])


async def test_apply_without_a_plan_hash_is_refused(client):
    # The defect was `if plan_hash and ...` — falsy skipped the recheck entirely.
    # A wrong hash was always caught; an *absent* one was not, so absent is the
    # case under test, along with the two falsy strings a form can actually send.
    content = _retailer_sheet("Nippon Hobby")

    for missing in ("", "   "):
        resp = await apply(client, content, filename="retailers.csv", plan_hash=missing)
        assert resp.status_code == 422, f"blank hash {missing!r} was accepted"
        assert "preview" in resp.json()["detail"]

    # Omitted entirely — no form field at all, which is what the old code let past.
    resp = await client.post(
        "/import/apply",
        files={"file": ("retailers.csv", content, "application/octet-stream")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422, "an apply with no plan_hash field was accepted"
    assert (await client.get("/retailers")).json() == []


async def test_a_same_shaped_file_cannot_reuse_another_files_hash(client):
    # Both files plan one create at row 2. Identical under the old fingerprint.
    previewed = await preview(client, _retailer_sheet("Previewed"), filename="retailers.csv")

    resp = await apply(
        client,
        _retailer_sheet("Different"),
        filename="retailers.csv",
        plan_hash=previewed["plan_hash"],
    )
    assert resp.status_code == 409, resp.text
    assert (await client.get("/retailers")).json() == []


async def test_changed_spawn_attributes_invalidate_the_hash(client):
    # `kits_spawned` was in the old hash, so a changed *quantity* was caught. The
    # kit's identity was not — same count, different kit, same fingerprint.
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()

    def archive(kit_name: str) -> bytes:
        return make_archive(
            {
                "orders": [
                    {
                        "id": "11111111-1111-4111-8111-111111111111",
                        "retailer_id": retailer["id"],
                        "order_date": "2026-05-02",
                        "order_number": "GB-1",
                        "currency_code": "AUD",
                    }
                ],
                "order_items": [
                    {
                        "id": "22222222-2222-4222-8222-222222222222",
                        "order_id": "11111111-1111-4111-8111-111111111111",
                        "item_type": "kit",
                        "quantity": "3",
                        "unit_price_minor": "1999",
                        "currency_code": "AUD",
                        "kit_name": kit_name,
                        "kit_grade": "HG",
                    }
                ],
            }
        )

    previewed = await preview(client, archive("Gouf Custom"))
    assert previewed["derived"]["kits_spawned"] == 3

    resp = await apply(client, archive("Zaku II"), plan_hash=previewed["plan_hash"])
    assert resp.status_code == 409, resp.text
    assert (await client.get("/kits")).json() == []


async def test_a_changed_stub_reference_invalidates_the_hash(client):
    # A retailer named but never declared is conjured as a stub. Stubs are pure
    # creates with a minted id, so under the old fingerprint every stub in a given
    # position hashed the same no matter who it was.
    def sheet(retailer_name: str) -> bytes:
        return make_csv(
            spec.ORDERS.header,
            [
                {
                    "retailer_name": retailer_name,
                    "order_date": "2026-05-02",
                    "order_number": "X-1",
                    "currency_code": "AUD",
                }
            ],
        )

    previewed = await preview(client, sheet("Hobby Link Japan"), filename="orders.csv")

    resp = await apply(
        client, sheet("Some Other Shop"), filename="orders.csv", plan_hash=previewed["plan_hash"]
    )
    assert resp.status_code == 409, resp.text
    assert (await client.get("/retailers")).json() == []


async def test_changed_deletion_identity_invalidates_the_hash(client):
    # replace_all previews a count of rows to destroy. Swapping which rows those
    # are, without changing how many, is a different loss at the same number.
    await client.post("/retailers", json={"name": "Doomed One"})
    content = _retailer_sheet("Replacement")

    previewed = await preview(client, content, filename="retailers.csv", mode="replace_all")
    assert previewed["derived"]["rows_deleted"] == {"retailers": 1}

    existing = (await client.get("/retailers")).json()
    await client.delete(f"/retailers/{existing[0]['id']}")
    await client.post("/retailers", json={"name": "A Different Doomed One"})

    resp = await apply(
        client,
        content,
        filename="retailers.csv",
        mode="replace_all",
        confirm="REPLACE",
        plan_hash=previewed["plan_hash"],
    )
    assert resp.status_code == 409, resp.text
    assert {r["name"] for r in (await client.get("/retailers")).json()} == {
        "A Different Doomed One"
    }


async def test_the_same_id_less_file_previews_to_the_same_hash(client):
    """Negative control for the trap in `_plan_fingerprint`.

    Every create here mints a fresh `uuid4()` per plan, the referenced retailer is
    conjured as a stub with another, and the kits carry a `status_updated_at`
    default off the clock. Hash any of those directly and the honest round trip
    below fails 409 every time, on a file nobody touched.
    """
    content = make_csv(
        spec.ORDERS.header,
        [
            {
                "retailer_name": "Conjured Shop",
                "order_date": "2026-05-02",
                "order_number": "X-1",
                "currency_code": "AUD",
            }
        ],
    )

    first = await preview(client, content, filename="orders.csv")
    second = await preview(client, content, filename="orders.csv")
    assert first["plan_hash"] == second["plan_hash"]

    resp = await apply(client, content, filename="orders.csv", plan_hash=first["plan_hash"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 2  # the order, and the retailer it named


async def test_a_blank_id_column_still_hashes_stably_through_a_reference(client):
    """The id-less case has two shapes, and only one is obvious.

    A sheet with no `id` column at all leaves `id` out of the row's `present` set.
    A sheet that *has* the column and leaves the cell empty does not — and every
    export template ships the column, so that is the common one. Both mint a uuid,
    and when a second row resolves to that row by name, the reference carries the
    minted value. Hash it raw and the round trip 409s on a file nobody edited.
    """
    tables = {
        # A blank id cell, not an absent column: make_archive writes the full header.
        "retailers": [{"name": "Conjured Shop", "country": "JP"}],
        "orders": [
            {
                "retailer_name": "Conjured Shop",
                "order_date": "2026-05-02",
                "order_number": "X-1",
                "currency_code": "AUD",
            }
        ],
    }
    content = make_archive(tables)

    first = await preview(client, content)
    second = await preview(client, content)
    assert first["plan_hash"] == second["plan_hash"], "a blank id cell moved the hash"

    resp = await apply(client, content, plan_hash=first["plan_hash"])
    assert resp.status_code == 200, resp.text
    orders = (await client.get("/orders")).json()
    retailers = (await client.get("/retailers")).json()
    assert len(orders) == 1 and len(retailers) == 1
    assert orders[0]["retailer_id"] == retailers[0]["id"]


async def test_an_update_to_a_conjured_reference_hashes_stably(client):
    """The other half of the minted-uuid trap, and it isn't in `values`.

    `_classify` records a reference change as `after=render(new_value)`. When the
    new value is a stub this planner just conjured, that render is a fresh uuid —
    so an UPDATE pointing at a conjured retailer moved the hash on every pass even
    though `values` was tokenised correctly. Reported by an external review of #72.
    """
    old = (await client.post("/retailers", json={"name": "Old Shop"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": old["id"],
                "order_date": "2026-05-02",
                "order_number": "X-1",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2450,
                        "currency_code": "AUD",
                        "kit": {"name": "Gouf Custom", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()

    # Existing order (matched by id), repointed at a retailer that does not exist
    # yet — so `_resolve_ref` conjures a stub and the change's `after` is its uuid.
    content = make_csv(
        spec.ORDERS.header,
        [
            {
                "id": order["id"],
                "retailer_name": "Conjured Replacement Shop",
                "order_date": "2026-05-02",
                "order_number": "X-1",
                "currency_code": "AUD",
            }
        ],
    )

    first = await preview(client, content, filename="orders.csv")
    assert actions(first, "orders") == ["update"], first["tables"]
    second = await preview(client, content, filename="orders.csv")
    assert first["plan_hash"] == second["plan_hash"], "a conjured reference moved the hash"

    resp = await apply(client, content, filename="orders.csv", plan_hash=first["plan_hash"])
    assert resp.status_code == 200, resp.text
    names = {r["name"] for r in (await client.get("/retailers")).json()}
    assert names == {"Old Shop", "Conjured Replacement Shop"}


async def test_an_update_to_a_conjured_catalog_reference_hashes_stably(client):
    """The same defect on a different table, ref column and stub type.

    The fix canonicalises every change's `after`, so it is not order-specific —
    this drives an order *line* repointed at a conjured consumable, which also
    goes through `_resolve_ref`'s `catalog` indirection (the target table is
    chosen from `item_type` rather than named on the column).
    """
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    consumable = (
        await client.post(
            "/consumables",
            json={"name": "Mr Color 1", "category": "paint", "quantity_on_hand": 1},
        )
    ).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-05-02",
                "order_number": "GB-9",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "consumable",
                        "catalog_ref_id": consumable["id"],
                        "quantity": 1,
                        "unit_price_minor": 400,
                        "currency_code": "AUD",
                    }
                ],
            },
        )
    ).json()

    content = make_csv(
        spec.ORDER_ITEMS.header,
        [
            {
                "id": order["items"][0]["id"],
                "order_id": order["id"],
                "item_type": "consumable",
                "catalog_name": "Conjured Paint",
                "quantity": "1",
                "unit_price_minor": "400",
                "currency_code": "AUD",
            }
        ],
    )

    first = await preview(client, content, filename="order_items.csv")
    assert actions(first, "order_items") == ["update"], first["tables"]
    second = await preview(client, content, filename="order_items.csv")
    assert first["plan_hash"] == second["plan_hash"], "a conjured catalog ref moved the hash"

    resp = await apply(client, content, filename="order_items.csv", plan_hash=first["plan_hash"])
    assert resp.status_code == 200, resp.text
    names = {c["name"] for c in (await client.get("/consumables")).json()}
    assert names == {"Mr Color 1", "Conjured Paint"}


# --- numeric grammar (#40, #43) --------------------------------------------------
#
# The parsers used to accept whatever `Decimal()` accepted and then truncate, so a
# malformed cell imported as a *different number* instead of as an error. These
# assert the whole value space of the field, and — because a parse failure is what
# decides whether a row is an ERROR at all — that the row state follows.


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("3", 3),
        (
            "3.0",
            3,
        ),
        (" 7 ", 7),
        ("1e2", 100),  # AGENTS.md: the #6 rewrite broke exponent input once already
        ("1,234", 1234),  # unambiguous grouping stays readable
        ("2147483647", 2147483647),  # int4 max, inclusive
        ("-2147483648", -2147483648),  # int4 min, inclusive
        ("", None),
        ("   ", None),
    ],
)
def test_parse_int_accepts(cell, expected):
    assert spec.parse_int(cell) == expected


@pytest.mark.parametrize(
    "cell",
    [
        "1.9",  # truncated to 1
        "-0.5",  # truncated to 0
        "0.4",
        "1_000",  # Decimal honours Python literal underscores → 1000
        "inf",  # OverflowError out of int(), which _parse_row did not catch → 500
        "-inf",
        "nan",
        "Infinity",
        "2147483648",  # one past int4 → IntegrityError at flush → 500
        "-2147483649",
        "1e10",  # in range as a float, nowhere near it as an int4
        "12,34",  # a European decimal comma, silently 100× out
        "abc",
        "1.2.3",
    ],
)
def test_parse_int_refuses(cell):
    with pytest.raises(ValueError):
        spec.parse_int(cell)


def test_every_int4_column_is_declared_with_parse_int(client):
    """A structural guarantee, and only that one — it stays green if the range check
    in `_apply_money_alternates` is deleted, so it is not evidence that route works.

    What it does catch is a *new* int4 column declared with some other parser, which
    would reach PostgreSQL unbounded. The behaviour of the two range checks is
    covered by `test_parse_int_refuses` and the ALT_MONEY matrix below.
    """
    import sqlalchemy as sa

    from app.models.base import Base

    unchecked = []
    for table in Base.metadata.sorted_tables:
        table_spec = spec.SPEC_BY_KEY.get(table.name)
        if table_spec is None:
            continue
        for column in table.columns:
            if not isinstance(column.type, sa.Integer) or isinstance(column.type, sa.BigInteger):
                continue
            declared = table_spec.column(column.name)
            if declared is not None and declared.parse is spec.parse_int:
                continue
            unchecked.append(f"{table.name}.{column.name}")

    assert unchecked == [], f"int4 columns with no parse-time range check: {unchecked}"


async def test_a_fractional_quantity_is_refused_and_blocks_the_import(client):
    """The row state is the point, not just the value.

    A cell that won't parse turns its row into an ERROR before matching runs, so it
    is never a create *or* an update — and one bad row blocks the whole file. Under
    the old parser this imported silently as quantity 1.
    """
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    content = make_csv(
        spec.ORDERS.header,
        [
            {
                "retailer_id": retailer["id"],
                "order_date": "2026-05-02",
                "order_number": "GB-1",
                "currency_code": "AUD",
                "shipping_cost_minor": "1.9",
            }
        ],
    )

    plan = await preview(client, content, filename="orders.csv")
    assert actions(plan, "orders") == ["error"]
    assert "shipping_cost_minor" in plan["tables"][0]["rows"][0]["error"]
    assert plan["blocking_errors"]

    resp = await apply(client, content, filename="orders.csv")
    assert resp.status_code == 409, resp.text
    assert (await client.get("/orders")).json() == []


async def test_a_bad_cell_errors_an_update_row_too(client):
    """The same value in the other row state.

    #41's suite proved a field can be structurally unreachable in the state a test
    never drives. Here the row *matches* an existing record, so without the parse
    error it would be an UPDATE — the assertion is that the error still wins, and
    that the existing row is left exactly as it was rather than half-written.
    """
    tool = (
        await client.post(
            "/tools",
            json={"name": "Godhand Nippers", "category": "cutting", "quantity_on_hand": 4},
        )
    ).json()
    content = make_csv(
        spec.TOOLS.header,
        [
            {
                "id": tool["id"],
                "name": "Godhand Nippers",
                # `category` is required, and a blank one errors the row on its own —
                # leaving it out made this pass against the unfixed parser for a
                # reason that had nothing to do with 2.5.
                "category": "cutting",
                "quantity_on_hand": "2.5",
            }
        ],
    )

    plan = await preview(client, content, filename="tools.csv")
    assert actions(plan, "tools") == ["error"]
    assert "quantity_on_hand" in plan["tables"][0]["rows"][0]["error"]

    resp = await apply(client, content, filename="tools.csv")
    assert resp.status_code == 409, resp.text
    assert (await client.get("/tools")).json()[0]["quantity_on_hand"] == 4


async def test_infinity_in_an_integer_column_is_a_row_error_not_a_500(client):
    """`parse_int` raised OverflowError, which `_parse_row` caught nothing of."""
    content = make_csv(
        spec.CONSUMABLES.header,
        [{"name": "Mr Color 1", "category": "paint", "quantity_on_hand": "inf"}],
    )
    plan = await preview(client, content, filename="consumables.csv")
    assert actions(plan, "consumables") == ["error"]
    assert "quantity_on_hand" in plan["tables"][0]["rows"][0]["error"]
    assert (await apply(client, content, filename="consumables.csv")).status_code == 409


async def test_an_ambiguous_comma_in_a_money_column_is_refused(client):
    """`12,34` used to strip to `1234` and store 123400 — a hundredfold error, in
    the column where being wrong costs the most."""
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    content = make_csv(
        spec.ORDERS.header,
        [
            {
                "retailer_id": retailer["id"],
                "order_date": "2026-05-02",
                "order_number": "GB-2",
                "currency_code": "AUD",
                "shipping_cost": "12,34",
            }
        ],
    )
    plan = await preview(client, content, filename="orders.csv")
    assert actions(plan, "orders") == ["error"]
    assert "shipping_cost" in plan["tables"][0]["rows"][0]["error"]
    assert (await client.get("/orders")).json() == []


async def test_a_major_amount_that_scales_out_of_int4_is_a_row_error(client):
    """The route `parse_int` never sees.

    `unit_price` is well inside int4 as written and 100× out once counted in cents,
    so the bound has to be re-checked on the product. It reached PostgreSQL as an
    IntegrityError at flush before — a 500, several tables into the transaction.
    """
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-05-02",
                "order_number": "GB-3",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2450,
                        "currency_code": "AUD",
                        "kit": {"name": "Gouf Custom", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()

    content = make_csv(
        spec.ORDER_ITEMS.header,
        [
            {
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "AUD",
                # A kit line short of kits errors in `_plan_spawns` when it has no
                # kit_name/kit_grade to build them from. Omitting these made this
                # test pass against the unfixed code without ever reaching the
                # overflow it was written for.
                "kit_name": "Zaku II",
                "kit_grade": "HG",
                "unit_price": "99999999999",  # 9,999,999,999,900 cents
            }
        ],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["error"]
    assert "unit_price" in plan["tables"][0]["rows"][0]["error"]
    assert (await apply(client, content, filename="order_items.csv")).status_code == 409


async def test_exponent_notation_still_imports(client):
    """The regression AGENTS.md names by hand: the #6 rewrite silently broke `1e2`
    in a file that then had no tests. Both the integer and the money route."""
    content = make_csv(
        spec.CONSUMABLES.header,
        [{"name": "Mr Color 2", "category": "paint", "quantity_on_hand": "1e2"}],
    )
    assert (await apply(client, content, filename="consumables.csv")).status_code == 200
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 100


def _alt_money_columns() -> list[tuple[str, str, str, str]]:
    """Every ALT_MONEY declaration, as (table, major column, minor column, currency)."""
    return [
        (table.key, column.name, column.mirrors, column.currency_column)
        for table in spec.TABLE_SPECS
        for column in table.columns
        if column.role is spec.ColumnRole.ALT_MONEY
    ]


def test_the_alt_money_column_set_is_what_these_tests_think_it_is():
    """If a fourth major-unit mirror is added, the matrix below has to cover it."""
    assert _alt_money_columns() == [
        (
            "tools",
            "unit_cost_reference",
            "unit_cost_reference_minor",
            "unit_cost_reference_currency",
        ),
        ("orders", "shipping_cost", "shipping_cost_minor", "currency_code"),
        ("order_items", "unit_price", "unit_price_minor", "currency_code"),
    ]


async def _alt_money_sheet(client, table, major_col, currency_col, code, amount):
    """A one-row sheet for whichever ALT_MONEY column is under test, with every
    other required field filled so the only thing that can error is the amount."""
    if table == "tools":
        return make_csv(
            spec.TOOLS.header,
            [{"name": "Nippers", "category": "cutting", major_col: amount, currency_col: code}],
        ), "tools.csv"

    # Uniquely named: a test calls this twice for one currency, and a second retailer
    # under the same name is a 409 (#107).
    shop = f"Shop {code} {uuid.uuid4().hex[:6]}"
    retailer = (await client.post("/retailers", json={"name": shop})).json()
    if table == "orders":
        return make_csv(
            spec.ORDERS.header,
            [
                {
                    "retailer_id": retailer["id"],
                    "order_date": "2026-05-02",
                    "order_number": f"B-{code}",
                    "currency_code": code,
                    major_col: amount,
                }
            ],
        ), "orders.csv"

    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-05-02",
                "order_number": f"L-{code}",
                "currency_code": code,
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 100,
                        "currency_code": code,
                        "kit": {"name": "Gouf", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    return make_csv(
        spec.ORDER_ITEMS.header,
        [
            {
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": code,
                # A kit line short of kits errors in _plan_spawns without these, which
                # would mask the overflow this test exists for.
                "kit_name": "Zaku II",
                "kit_grade": "HG",
                major_col: amount,
            }
        ],
    ), "order_items.csv"


@pytest.mark.parametrize("code", ["JPY", "AUD", "KWD", "CLF"], ids=["0-digit", "2", "3", "4"])
@pytest.mark.parametrize("table, major_col, minor_col, currency_col", _alt_money_columns())
async def test_alt_money_scaling_respects_the_int4_bound(
    client, table, major_col, minor_col, currency_col, code
):
    """Just inside and just outside the bound, per column and per exponent.

    The bound is on the *scaled* integer, so where it falls in major units depends on
    the currency: 21,474,836.47 AUD and 2,147,483.647 KWD are the same int4 ceiling.
    Driven through the importer, not through `require_int4` — a unit test of the
    helper would stay green if any one of the three columns stopped calling it.
    """
    from decimal import Decimal

    from app.services.currency import minor_fraction_digits
    from app.services.numeric import INT4_MAX

    scale = Decimal(10) ** minor_fraction_digits(code)
    inside = Decimal(INT4_MAX) / scale
    outside = (Decimal(INT4_MAX) + 1) / scale

    content, filename = await _alt_money_sheet(
        client, table, major_col, currency_col, code, str(inside)
    )
    plan = await preview(client, content, filename=filename)
    assert actions(plan, table) != ["error"], plan["tables"][0]["rows"][0]

    content, filename = await _alt_money_sheet(
        client, table, major_col, currency_col, code, str(outside)
    )
    plan = await preview(client, content, filename=filename)
    assert actions(plan, table) == ["error"], plan["tables"][0]["rows"][0]
    assert major_col in plan["tables"][0]["rows"][0]["error"]


@pytest.mark.parametrize(
    "code, refused",
    [("JPY", False), ("AUD", True), ("KWD", True), ("CLF", True), ("ZZZ", True)],
)
async def test_a_lone_grouped_amount_is_settled_by_the_currency(client, code, refused):
    """`1,234` is grammatical grouping and an equally valid European `1.234`.

    Only the exponent settles it, and only one way: with no minor unit there is
    nowhere for a decimal reading to land. Driven through the importer rather than
    the parser, because the currency is not known until the money step — the whole
    point of the deferral.
    """
    retailer = (await client.post("/retailers", json={"name": f"Shop {code}"})).json()
    content = make_csv(
        spec.ORDERS.header,
        [
            {
                "retailer_id": retailer["id"],
                "order_date": "2026-05-02",
                "order_number": f"LG-{code}",
                "currency_code": code,
                "shipping_cost": "1,234",
            }
        ],
    )
    plan = await preview(client, content, filename="orders.csv")

    if refused:
        assert actions(plan, "orders") == ["error"]
        assert "shipping_cost" in plan["tables"][0]["rows"][0]["error"]
    else:
        assert actions(plan, "orders") == ["create"], plan["tables"][0]["rows"][0]
        assert (await apply(client, content, filename="orders.csv")).status_code == 200
        assert (await client.get("/orders")).json()[0]["shipping_cost_minor"] == 1234


# --- the per-line quantity ceiling, through the sheet (#43) -----------------------


def order_line_row(order_id: str, quantity: int, **extra) -> dict:
    return {
        "id": "",
        "order_id": order_id,
        "item_type": "kit",
        "quantity": str(quantity),
        "unit_price_minor": "2800",
        "currency_code": "JPY",
        "kit_name": "Zaku II",
        "kit_grade": "HG",
        **extra,
    }


async def seeded_order(client) -> dict:
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    return (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()


@pytest.mark.parametrize(
    ("quantity", "refused"),
    [
        pytest.param(orders.MAX_LINE_QUANTITY, False, id="exactly at the ceiling"),
        pytest.param(orders.MAX_LINE_QUANTITY + 1, True, id="one over"),
        pytest.param(2_000_000_000, True, id="absurd but a valid int4"),
    ],
)
async def test_a_sheet_cannot_spawn_past_the_ceiling(client, quantity, refused):
    """A kit line short of its kits is the importer's own fan-out route — it reaches
    `spawn_kits` without ever building an `OrderItemCreate`, so the REST guard says
    nothing about it."""
    order = await seeded_order(client)
    content = make_csv(spec.ORDER_ITEMS.header, [order_line_row(order["id"], quantity)])

    plan = await preview(client, content, filename="order_items.csv")
    if refused:
        assert actions(plan, "order_items") == ["error"]
        error = plan["tables"][0]["rows"][0]["error"]
        assert "quantity" in error and "at most" in error, error
        assert plan["blocking_errors"]
        assert (await apply(client, content, filename="order_items.csv")).status_code == 409
    else:
        assert actions(plan, "order_items") == ["create"], plan["tables"][0]["rows"][0]
        assert plan["derived"]["kits_spawned"] == quantity


async def test_a_catalog_line_in_a_sheet_is_held_to_the_ceiling_too(client):
    """Spawns nothing, so `_plan_spawns` never looks at it. The check has to sit on
    the row rather than on the fan-out, or the two item types get two limits."""
    order = await seeded_order(client)
    content = make_csv(
        spec.ORDER_ITEMS.header,
        [
            {
                "id": "",
                "order_id": order["id"],
                "item_type": "consumable",
                "quantity": str(orders.MAX_LINE_QUANTITY + 1),
                "unit_price_minor": "500",
                "currency_code": "JPY",
                "catalog_item_name": "Mr Surfacer 1200",
            }
        ],
    )

    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["error"]
    assert "quantity" in plan["tables"][0]["rows"][0]["error"]


async def test_an_update_row_is_held_to_the_ceiling_as_well(client):
    """The action axis, not another value on the same one. An update carries a
    `changes` list and a `matched_id` that a create does not have, and it reaches
    the quantity by a different branch of `_classify` — a check that only ever ran
    on creates would read green here with the row still going through.
    """
    order = await seeded_order(client)
    line = order["items"][0]

    # Same line by id, so this is an update rather than a second line.
    content = make_csv(
        spec.ORDER_ITEMS.header,
        [order_line_row(order["id"], orders.MAX_LINE_QUANTITY + 1, id=line["id"])],
    )
    plan = await preview(client, content, filename="order_items.csv")

    assert actions(plan, "order_items") == ["error"]
    assert "quantity" in plan["tables"][0]["rows"][0]["error"]
    assert (await apply(client, content, filename="order_items.csv")).status_code == 409
    # The stored line is untouched, and no kits were spawned against it.
    assert (await client.get(f"/orders/{order['id']}")).json()["items"][0]["quantity"] == 1
    assert len((await client.get("/kits")).json()) == 1


async def test_an_update_that_stays_under_the_ceiling_still_applies(client):
    """The control: refusing the over-ceiling update must not mean refusing updates."""
    order = await seeded_order(client)
    content = make_csv(
        spec.ORDER_ITEMS.header,
        [order_line_row(order["id"], 3, id=order["items"][0]["id"])],
    )

    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["update"], plan["tables"][0]["rows"][0]
    assert (await apply(client, content, filename="order_items.csv")).status_code == 200
    assert (await client.get(f"/orders/{order['id']}")).json()["items"][0]["quantity"] == 3


# --- archive integrity (#42) -----------------------------------------------------


def rebuild_archive(
    content: bytes, *, drop: str = "", edit: dict[str, bytes] | None = None
) -> bytes:
    """Re-zip a real export, optionally losing or rewriting one member.

    The manifest is carried through untouched, which is what makes the result a
    *truncated export* rather than a different archive — the claim about what the
    zip holds survives the thing it describes going missing.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
            for name in source.namelist():
                if name == drop:
                    continue
                out.writestr(name, (edit or {}).get(name, source.read(name)))
    return buffer.getvalue()


def drop_rows(csv_bytes: bytes, keep: int) -> bytes:
    """Keep the header and the first `keep` data lines — a half-written file."""
    lines = csv_bytes.split(b"\r\n")
    return b"\r\n".join(lines[: keep + 1]) + b"\r\n"


async def test_an_intact_export_reconciles_against_its_own_manifest(client):
    """The check has to be silent on a real archive, or it is just noise.

    Every table is declared, including the ones that export empty, so this also
    pins that a legitimately zero-row file is not read as a missing one.
    """
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content

    plan = await preview(client, archive)
    assert plan["blocking_errors"] == []
    assert [w for w in plan["warnings"] if "manifest" in w or "isn't intact" in w] == []


async def test_kit_photos_is_exported_empty_on_purpose(client):
    """Schema-only until M7. The archive shape is correct in advance, so an empty
    kit_photos.csv is the intended output and not a hole in the export (#42)."""
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content

    assert read_archive(archive)["kit_photos"] == []
    assert read_manifest(archive)["tables"]["kit_photos"] == {"file": "kit_photos.csv", "rows": 0}


async def test_a_file_the_manifest_names_but_the_zip_lacks_blocks_the_import(client):
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content
    truncated = rebuild_archive(archive, drop="orders.csv")

    plan = await preview(client, truncated)
    assert any(
        "orders.csv" in error and "truncated" in error for error in plan["blocking_errors"]
    ), plan["blocking_errors"]

    resp = await apply(client, truncated)
    assert resp.status_code == 409


async def test_a_short_file_is_reported_against_the_manifest_count(client):
    """Present but half there. Not blocking — a hand-trimmed export is a
    legitimate thing to import — but it can no longer pass unremarked."""
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        short = drop_rows(source.read("kits.csv"), keep=1)
    assert read_manifest(archive)["tables"]["kits"]["rows"] == 2

    plan = await preview(client, rebuild_archive(archive, edit={"kits.csv": short}))
    assert any(
        "kits.csv" in warning and "says 2 row(s) but 1" in warning for warning in plan["warnings"]
    ), plan["warnings"]
    assert plan["blocking_errors"] == []


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(None, id="no tables block at all — an older manifest"),
        pytest.param("kits.csv", id="tables is a string"),
        pytest.param({"kits": "kits.csv"}, id="entry is not an object"),
        pytest.param({"kits": {"file": "kits.csv"}}, id="entry has no row count"),
        pytest.param({"kits": {"file": "kits.csv", "rows": "two"}}, id="row count is not a number"),
        pytest.param({"kits": {"file": None, "rows": 2}}, id="file name is null"),
        pytest.param({"kits": {"file": "kits.csv", "rows": True}}, id="row count is a bool"),
    ],
)
async def test_an_unreconcilable_manifest_is_read_as_far_as_it_goes(client, block):
    """A manifest that can't be checked against must not become a parse error on a
    file that is otherwise fine — the counts are a cross-check, not a schema."""
    manifest = {"format": "plamotrack-archive", "export_version": exporting.EXPORT_VERSION}
    if block is not None:
        manifest["tables"] = block
    archive = make_archive({"retailers": [{"id": "", "name": "Gundam Base"}]}, manifest=manifest)

    plan = await preview(client, archive)
    assert plan["blocking_errors"] == []
    assert actions(plan, "retailers") == ["create"]


async def test_a_damaged_member_is_a_diagnosis_not_a_500(client):
    """`ZipFile()` only reads the central directory, so a member whose own payload
    is corrupt gets past construction and blows up on read."""
    await seed_collection(client)
    archive = bytearray((await client.get("/export/archive")).content)
    offset = archive.index(b"kits.csv") + len(b"kits.csv")
    archive[offset + 8] ^= 0xFF  # inside the deflated payload

    resp = await client.post(
        "/import/preview",
        files={"file": ("archive.zip", bytes(archive), "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422, resp.text
    assert "kits.csv" in resp.json()["detail"]
    assert "damaged" in resp.json()["detail"]


# --- encoding (#42) --------------------------------------------------------------


def latin1_csv(header: list[str], rows: list[dict[str, str]]) -> bytes:
    """Valid CSV, wrong encoding — what Excel writes on a non-UTF-8 default."""
    return make_csv(header, rows).decode().encode("latin-1")


async def test_undecodable_bytes_in_a_single_csv_name_the_file_and_line(client):
    content = latin1_csv(
        spec.RETAILERS.header,
        [
            {"id": "", "name": "Gundam Base"},
            {"id": "", "name": "Hobby Search"},
            {"id": "", "name": "Café Kaiyodo"},  # line 4: the é is 0xE9 in latin-1
        ],
    )
    resp = await client.post(
        "/import/preview",
        files={"file": ("retailers.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "retailers.csv" in detail
    assert "line 4" in detail, detail
    assert (await client.get("/retailers")).json() == []


async def test_undecodable_bytes_in_an_archive_member_name_the_member(client):
    archive = make_archive({"retailers": [{"id": "", "name": "Gundam Base"}]})
    broken = rebuild_archive(
        archive,
        edit={
            "retailers.csv": latin1_csv(spec.RETAILERS.header, [{"id": "", "name": "Café Kaiyodo"}])
        },
    )

    resp = await client.post(
        "/import/preview",
        files={"file": ("archive.zip", broken, "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422, resp.text
    assert "retailers.csv" in resp.json()["detail"]
    assert "UTF-8" in resp.json()["detail"]


async def test_non_ascii_utf8_still_imports(client):
    """The other half of decoding strictly: refusing bad bytes must not turn into
    refusing bytes that are merely not English."""
    content = make_csv(spec.RETAILERS.header, [{"id": "", "name": "ホビーサーチ"}])
    assert (await apply(client, content, filename="retailers.csv")).status_code == 200
    assert [r["name"] for r in (await client.get("/retailers")).json()] == ["ホビーサーチ"]


async def test_a_utf8_bom_is_still_stripped(client):
    """utf-8-sig, not utf-8 — Excel writes the BOM, and decoding it as a character
    would put it on the front of the first header name and lose that column."""
    content = b"\xef\xbb\xbf" + make_csv(spec.RETAILERS.header, [{"id": "", "name": "Gundam Base"}])
    assert (await apply(client, content, filename="retailers.csv")).status_code == 200
    assert [r["name"] for r in (await client.get("/retailers")).json()] == ["Gundam Base"]


# --- expansion budget (#43) ------------------------------------------------------


def zip_of(payload: bytes, name: str = "kits.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("slack", "accepted"),
    [
        pytest.param(0, True, id="exactly at the budget"),
        pytest.param(-1, False, id="one byte over"),
    ],
)
async def test_the_expanded_budget_is_enforced_at_its_boundary(
    client, monkeypatch, slack, accepted
):
    payload = make_csv(spec.RETAILERS.header, [{"id": "", "name": "Gundam Base"}])
    monkeypatch.setattr(importing, "MAX_EXPANDED_BYTES", len(payload) + slack)

    resp = await client.post(
        "/import/preview",
        files={"file": ("archive.zip", zip_of(payload, "retailers.csv"), "application/zip")},
        data={"mode": "merge"},
    )
    if accepted:
        assert resp.status_code == 200, resp.text
        assert actions(resp.json(), "retailers") == ["create"]
    else:
        assert resp.status_code == 422, resp.text
        assert "unpacks to more than" in resp.json()["detail"]


async def test_the_budget_is_cumulative_across_members(client, monkeypatch):
    """Per-member would let an archive of N files spend the budget N times over."""
    payload = make_csv(spec.RETAILERS.header, [{"id": "", "name": "Gundam Base"}])
    monkeypatch.setattr(importing, "MAX_EXPANDED_BYTES", len(payload))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("retailers.csv", payload)
        archive.writestr("kits.csv", payload)

    resp = await client.post(
        "/import/preview",
        files={"file": ("archive.zip", buffer.getvalue(), "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422, resp.text
    assert "unpacks to more than" in resp.json()["detail"]


async def test_a_compressible_archive_cannot_expand_past_the_real_budget(client):
    """The shipped default, not a patched one: an upload well inside the 10 MB
    compressed limit that unpacks to 120 MB of CSV.

    The size is written out rather than derived from `MAX_EXPANDED_BYTES`, so the
    test still means something against code that has no such constant — which is
    what makes it a detector and not a tautology. Against the unfixed importer it
    fails on the *message*: the whole 120 MB is read and parsed, and the refusal
    that eventually comes is `MAX_ROWS` complaining about a row count, long after
    the memory it was supposed to defend has been spent. Raising the budget past
    120 MB is a policy change and is supposed to turn this red.
    """
    row = b"00000000-0000-0000-0000-000000000000,Gundam Base,note\r\n"
    payload = b"id,name,notes\r\n" + row * (120 * 1024 * 1024 // len(row))
    bomb = zip_of(payload, "retailers.csv")
    assert len(bomb) < importing.MAX_UPLOAD_BYTES, "the compressed limit would catch it first"

    resp = await client.post(
        "/import/preview",
        files={"file": ("archive.zip", bomb, "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422, resp.text
    assert "unpacks to more than" in resp.json()["detail"]


# --- reconciliation is over the rows actually consumed (external review of #75) ---


def zip_members(members: dict[str, bytes], *, manifest: object = ...) -> bytes:
    """Build an archive member by member, with no assumption that a file's name,
    its manifest entry and the table it routes to agree."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if manifest is not ...:
            archive.writestr("manifest.json", json.dumps(manifest))
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def declaring(**tables: tuple[str, int]) -> dict:
    return {
        "format": "plamotrack-archive",
        "export_version": exporting.EXPORT_VERSION,
        "tables": {key: {"file": name, "rows": rows} for key, (name, rows) in tables.items()},
    }


RETAILERS_CSV = make_csv(spec.RETAILERS.header, [{"id": "", "name": "Gundam Base"}])
OTHER_RETAILERS_CSV = make_csv(spec.RETAILERS.header, [{"id": "", "name": "Hobby Search"}])


async def test_a_member_the_manifest_never_mentions_is_reported(client):
    """The manifest is a claim about what the archive holds, and it was only ever
    checked in one direction. An undeclared file imported alongside the declared
    ones while reconciliation reported the archive intact."""
    archive = zip_members(
        {"retailers.csv": RETAILERS_CSV, "extra.csv": OTHER_RETAILERS_CSV},
        manifest=declaring(retailers=("retailers.csv", 1)),
    )

    plan = await preview(client, archive)
    assert any(
        "extra.csv" in warning and "isn't listed" in warning for warning in plan["warnings"]
    ), plan["warnings"]
    # Reported, not blocked: the rows are there, and the preview lists them.
    assert plan["blocking_errors"] == []
    assert sum(len(table["rows"]) for table in plan["tables"]) == 2


async def test_one_basename_from_two_directories_blocks(client):
    """`a/retailers.csv` and `b/retailers.csv` are two files and one basename. Keyed
    by basename, the second silently replaced the first's count."""
    archive = zip_members(
        {"a/retailers.csv": RETAILERS_CSV, "b/retailers.csv": OTHER_RETAILERS_CSV},
        manifest=declaring(retailers=("retailers.csv", 1)),
    )

    plan = await preview(client, archive)
    assert any(
        "a/retailers.csv" in error and "b/retailers.csv" in error
        for error in plan["blocking_errors"]
    ), plan["blocking_errors"]
    assert (await apply(client, archive)).status_code == 409
    assert (await client.get("/retailers")).json() == []


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param(declaring(retailers=("retailers.csv", 1)), id="with a manifest"),
        pytest.param(..., id="no manifest at all"),
    ],
)
async def test_two_members_under_one_name_block(client, manifest):
    """A zip may legally carry the same path twice, and `archive.open(name)` resolves
    to whichever was written last — so one member is read twice and the other never.
    That is true whether or not a manifest is there to notice it.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if manifest is not ...:
            archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("retailers.csv", RETAILERS_CSV)
        archive.writestr("retailers.csv", OTHER_RETAILERS_CSV)

    plan = await preview(client, buffer.getvalue())
    assert any(
        "more than one member" in error and "retailers.csv" in error
        for error in plan["blocking_errors"]
    ), plan["blocking_errors"]
    assert (await apply(client, buffer.getvalue())).status_code == 409
    assert (await client.get("/retailers")).json() == []


async def test_a_declaration_filed_under_the_wrong_table_is_reported(client):
    """Reducing the block to `filename -> count` threw the table key away, so a
    manifest that disagreed with its own contents reconciled clean."""
    archive = zip_members(
        {"retailers.csv": RETAILERS_CSV},
        manifest=declaring(kits=("retailers.csv", 1)),
    )

    plan = await preview(client, archive)
    assert any("retailers.csv" in warning and "kits" in warning for warning in plan["warnings"]), (
        plan["warnings"]
    )
    assert actions(plan, "retailers") == ["create"]  # imported as what it actually is


async def test_a_short_declared_file_still_warns_when_another_shares_its_basename(client):
    """The count comparison has to survive the one-to-one resolution above: a
    declaration that resolves cleanly is still compared, not skipped."""
    archive = zip_members(
        {"retailers.csv": make_csv(spec.RETAILERS.header, [])},
        manifest=declaring(retailers=("retailers.csv", 4)),
    )

    plan = await preview(client, archive)
    assert any("says 4 row(s) but 0" in warning for warning in plan["warnings"]), plan["warnings"]


# --- a malformed archive is a diagnosis, never a 500 (external review of #75) -----


@pytest.mark.parametrize(
    ("manifest", "shape"),
    [
        pytest.param([], "a list", id="a JSON list"),
        pytest.param("plamotrack-archive", "a string", id="a bare JSON string"),
        pytest.param(None, "null", id="JSON null"),
        pytest.param(1, "a number", id="a bare number"),
        pytest.param(True, "a boolean", id="a bare boolean"),
        pytest.param({}, None, id="an object saying nothing"),
        pytest.param({"tables": {}}, None, id="an object declaring no tables"),
    ],
)
async def test_a_manifest_of_any_json_shape_is_read_as_far_as_it_goes(http_client, manifest, shape):
    """The outer shape, not the inner `tables` value.

    The first matrix here varied what `tables` held while every case kept the
    document an object — so every one of them reached `data.get(...)` on a dict and
    none of them could have caught `manifest.json = []`, which left as an
    `AttributeError` 500. The axis was the document itself.

    `shape` is asserted, not just the status. Checking only "200, and the row still
    imported" is what let `null` through the *second* time: it is the one non-object
    that `json.loads` returns as `None`, which collided with the `None` used as the
    "couldn't parse it" sentinel, so it silently skipped the warning every other
    shape got while still passing a status-only assertion.
    """
    archive = zip_members({"retailers.csv": RETAILERS_CSV}, manifest=manifest)

    resp = await http_client.post(
        "/import/preview",
        files={"file": ("archive.zip", archive, "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["blocking_errors"] == []
    assert actions(plan, "retailers") == ["create"]

    said = [w for w in plan["warnings"] if "not an object" in w]
    if shape is None:
        assert said == [], said  # an object, however empty, is a manifest
    else:
        assert len(said) == 1, plan["warnings"]
        assert f"manifest.json is {shape}, not an object" in said[0]


def flag_every_member(content: bytes, *, gp_flag: int = 0, method: int | None = None) -> bytes:
    """Rewrite the general-purpose flag and/or compression method on every header.

    `zipfile` will not *write* an encrypted or exotically compressed member, so the
    only way to hold the reader to what it does with one is to say so in the headers
    of a zip it did write.
    """
    raw = bytearray(content)
    for signature, flag_at, method_at in ((b"PK\x03\x04", 6, 8), (b"PK\x01\x02", 8, 10)):
        index = 0
        while (index := raw.find(signature, index)) != -1:
            raw[index + flag_at] |= gp_flag
            if method is not None:
                raw[index + method_at : index + method_at + 2] = method.to_bytes(2, "little")
            index += 4
    return bytes(raw)


def corrupt_payload(content: bytes) -> bytes:
    raw = bytearray(content)
    raw[len(raw) // 2] ^= 0xFF
    return bytes(raw)


@pytest.mark.parametrize(
    ("damage", "id_"),
    [
        pytest.param(corrupt_payload, "corrupt", id="a payload that fails its CRC"),
        pytest.param(
            lambda c: flag_every_member(c, gp_flag=0x01), "encrypted", id="an encrypted member"
        ),
        pytest.param(
            lambda c: flag_every_member(c, method=99),
            "unsupported",
            id="a compression method we can't read",
        ),
    ],
)
async def test_an_unreadable_member_is_a_422_naming_it(http_client, damage, id_):
    """Rule 6: these are all properties of a file somebody uploaded, so none of them
    is a 500. The first pass here caught only the decompression errors, and left an
    encrypted member (`RuntimeError`) and an unknown method (`NotImplementedError`)
    escaping to FastAPI.

    Driven through `http_client` on purpose: under the default transport a 500 is
    re-raised into the test and the assertion never sees a status at all, which
    fails without pinning what the status should have been.
    """
    archive = zip_members({"retailers.csv": RETAILERS_CSV * 40}, manifest=...)

    resp = await http_client.post(
        "/import/preview",
        files={"file": ("archive.zip", damage(archive), "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 422, f"{id_}: {resp.status_code} {resp.text[:200]}"
    assert "retailers.csv" in resp.json()["detail"]
    assert (await http_client.get("/retailers")).json() == []


# --- the archive structure itself is attacker-shaped (follow-up review of #75) ----


@pytest.mark.parametrize(
    "order",
    [
        pytest.param(("a/manifest.json", "b/manifest.json"), id="a before b"),
        pytest.param(("b/manifest.json", "a/manifest.json"), id="b before a"),
    ],
)
async def test_two_competing_manifests_block(client, order):
    """Taking the first left the governing manifest decided by member order, so the
    same files re-zipped differently claimed different things. Both orderings are
    driven precisely because order was the deciding input — one of them would have
    passed a single-ordering test by luck.
    """
    describes_retailers = declaring(retailers=("retailers.csv", 1))
    describes_kits = declaring(kits=("kits.csv", 99))
    bodies = {"a/manifest.json": describes_retailers, "b/manifest.json": describes_kits}

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in order:
            archive.writestr(name, json.dumps(bodies[name]))
        archive.writestr("retailers.csv", RETAILERS_CSV)

    plan = await preview(client, buffer.getvalue())
    assert any(
        "2 manifests" in error and "a/manifest.json" in error and "b/manifest.json" in error
        for error in plan["blocking_errors"]
    ), plan["blocking_errors"]
    assert (await apply(client, buffer.getvalue())).status_code == 409
    assert (await client.get("/retailers")).json() == []


#: Members in the structural-cost archive below. Sized so the two complexities are
#: unmistakable rather than merely different: on the machine this was written on,
#: the quadratic scans took **6.73 s** here and the indexed ones take **0.06 s**.
_STRUCTURAL_MEMBERS = 30_000
#: Generous against a loaded or slower runner — 25x the linear cost measured above,
#: and still 4.5x under the quadratic one. This is a complexity guard, not a
#: benchmark: it exists to fail if the scans go back to being nested, and the gap it
#: watches is two orders of magnitude wide.
_STRUCTURAL_BUDGET_SECONDS = 1.5


async def test_archive_structure_is_processed_in_linear_time(client):
    """`names.count(n)` per member, and a fresh walk of every member per declaration,
    are both quadratic in numbers the uploader chooses — and both ran over the
    central directory *before* any member content was read, so the expanded-byte
    budget could not have helped. A DoS in the middle of the code added to stop one.

    Empty members are nearly free in a zip, so the 10 MB upload limit permits on the
    order of 100,000 of them; this drives 30,000 and a manifest declaring 7,500
    tables, well inside that.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                declaring(
                    **{
                        f"t{i}": (f"declared{i:06d}.csv", 0)
                        for i in range(_STRUCTURAL_MEMBERS // 4)
                    }
                )
            ),
        )
        archive.writestr("retailers.csv", RETAILERS_CSV)
        for i in range(_STRUCTURAL_MEMBERS):
            archive.writestr(f"pad{i:06d}.txt", b"")
    content = buffer.getvalue()
    assert len(content) < importing.MAX_UPLOAD_BYTES, "the upload limit would catch it first"

    started = time.perf_counter()
    upload = importing.read_upload("archive.zip", content)
    elapsed = time.perf_counter() - started

    assert elapsed < _STRUCTURAL_BUDGET_SECONDS, (
        f"{_STRUCTURAL_MEMBERS:,} members took {elapsed:.2f}s — the structural scans "
        "look quadratic again"
    )
    # And it still did the work: every declaration is missing, and says so.
    assert len(upload.errors) >= _STRUCTURAL_MEMBERS // 4


# --- manifest metadata is data too (third-pass review of #75) --------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("export_version", "not-an-integer", id="an integer field given a string"),
        pytest.param("format", [], id="a string field given a list"),
        pytest.param("schema_version", {}, id="a string field given an object"),
        pytest.param("exported_at", 42, id="a string field given a number"),
        pytest.param("app_version", True, id="a string field given a boolean"),
    ],
)
async def test_unreadable_manifest_metadata_warns_rather_than_500s(http_client, field, value):
    """The document is an object and its `tables` block is fine — it's the metadata
    that won't validate. `ManifestInfo` is a Pydantic model, so `ValidationError`
    lands here, and that is a `ValueError`: it was covered for free while parsing and
    model-building were one expression inside the same `try`. Splitting them to tell
    JSON `null` apart from a parse failure took the cover away, and this asserts it
    back.
    """
    archive = zip_members({"retailers.csv": RETAILERS_CSV}, manifest={field: value})

    resp = await http_client.post(
        "/import/preview",
        files={"file": ("archive.zip", archive, "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert plan["blocking_errors"] == []
    assert actions(plan, "retailers") == ["create"]

    said = [w for w in plan["warnings"] if "metadata this instance can't read" in w]
    assert len(said) == 1, plan["warnings"]
    assert field in said[0], said[0]
    # The report itself stays out of the preview panel — the field name is the part
    # a person can act on.
    assert "pydantic" not in said[0].lower()


async def test_valid_metadata_is_not_warned_about(http_client):
    """The control for the matrix above: a manifest that validates says nothing."""
    archive = zip_members(
        {"retailers.csv": RETAILERS_CSV},
        manifest={"format": "plamotrack-archive", "export_version": exporting.EXPORT_VERSION},
    )

    resp = await http_client.post(
        "/import/preview",
        files={"file": ("archive.zip", archive, "application/zip")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text
    assert [w for w in resp.json()["warnings"] if "manifest" in w] == []


async def test_bad_metadata_does_not_discard_a_good_tables_block(client):
    """Metadata and declarations fail independently. `exported_at` being the wrong
    type says nothing about whether the file list is readable, and dropping the whole
    manifest would throw away the reconciliation — the half that actually protects
    the import."""
    archive = zip_members(
        {"retailers.csv": RETAILERS_CSV},
        manifest={"exported_at": 42, "tables": {"kits": {"file": "kits.csv", "rows": 3}}},
    )

    plan = await preview(client, archive)
    assert any("exported_at" in warning for warning in plan["warnings"]), plan["warnings"]
    # The declaration was still read, and still held the archive to it.
    assert any("kits.csv" in error and "truncated" in error for error in plan["blocking_errors"]), (
        plan["blocking_errors"]
    )


# --- the starter sheet's retailer-free branch (review of #76) ---------------------


def sheet_row(quantity: str, *, retailer: str = "", name: str = "Zaku II") -> dict:
    row = {"kit_name": name, "grade": "HG", "status": "backlog", "quantity": quantity}
    if retailer:
        row |= {
            "retailer": retailer,
            "order_date": "2026-03-14",
            "order_number": "HLJ-1",
            "unit_price": "24.50",
            "currency": "AUD",
            "received": "yes",
        }
    return row


def starter_sheet_csv(rows: list[dict]) -> bytes:
    return make_csv(starter_sheet.STARTER_SHEET_HEADER, rows)


async def test_a_retailer_free_row_spawns_one_kit_per_unit(client):
    """`quantity` used to be read and then dropped on this branch: a row with no
    shop named emitted exactly one kit, so an ordinary `3` silently became `1`.

    That is data loss with nothing to do with the ceiling — it is why the fix is to
    fan out rather than to reject anything above 1. A column cannot mean "how many
    of this kit" when a shop is named and nothing at all when one isn't.
    """
    sheet = starter_sheet_csv([sheet_row("3")])

    plan = await preview(client, sheet, filename="starter-sheet.csv")
    assert actions(plan, "kits") == ["create"] * 3, actions(plan, "kits")

    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200
    kits = (await client.get("/kits")).json()
    assert len(kits) == 3
    assert {k["name"] for k in kits} == {"Zaku II"}
    assert (await client.get("/orders")).json() == []  # still no purchase record


@pytest.mark.parametrize(
    "quantity",
    [pytest.param("", id="blank"), pytest.param("1", id="one")],
)
async def test_a_retailer_free_row_still_defaults_to_a_single_kit(client, quantity):
    """The control. Blank means one, as the sheet's own guidance says, and the
    fan-out must not turn an unstated quantity into zero kits or an error."""
    sheet = starter_sheet_csv([sheet_row(quantity)])

    plan = await preview(client, sheet, filename="starter-sheet.csv")
    assert plan["blocking_errors"] == []
    assert actions(plan, "kits") == ["create"]


@pytest.mark.parametrize(
    "retailer",
    [
        pytest.param("Hobby Link Japan", id="a row that names a shop"),
        pytest.param("", id="a row that names no shop"),
    ],
)
@pytest.mark.parametrize(
    ("quantity", "accepted"),
    [
        pytest.param(str(orders.MAX_LINE_QUANTITY), True, id="exactly at the ceiling"),
        pytest.param(str(orders.MAX_LINE_QUANTITY + 1), False, id="one over"),
    ],
)
async def test_the_ceiling_covers_both_starter_sheet_shapes(client, retailer, quantity, accepted):
    """Both branches at the limit and above it.

    Whether a row reaches the ceiling used to depend on whether it named a shop:
    the retailer-bearing branch emits an order line that `_check_line_quantity`
    sees, and the retailer-free branch emits kits that nothing checked. Same
    column, same number, same sheet — so the coverage cannot come down to a value
    in a different cell.
    """
    sheet = starter_sheet_csv([sheet_row(quantity, retailer=retailer)])

    plan = await preview(client, sheet, filename="starter-sheet.csv")
    if accepted:
        assert plan["blocking_errors"] == []
        expected = int(quantity)
        spawned = len(actions(plan, "kits")) + plan["derived"]["kits_spawned"]
        assert spawned == expected, f"{spawned} kits planned, expected {expected}"
    else:
        assert plan["blocking_errors"], plan
        assert any("at most" in str(error) for error in plan["blocking_errors"]) or any(
            "at most" in (row.get("error") or "")
            for table in plan["tables"]
            for row in table["rows"]
        ), plan
        assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 409
        assert (await client.get("/kits")).json() == []


@pytest.mark.parametrize(
    "retailer",
    [
        pytest.param("Hobby Link Japan", id="a row that names a shop"),
        pytest.param("", id="a row that names no shop"),
    ],
)
@pytest.mark.parametrize(
    "quantity",
    [
        pytest.param("0", id="zero"),
        pytest.param("-2", id="negative"),
        pytest.param("1.5", id="fractional"),
        pytest.param("many", id="not a number"),
    ],
)
async def test_a_quantity_that_cannot_be_honoured_is_refused_in_both_shapes(
    http_client, retailer, quantity
):
    """The *lower* end of the range, across the same two shapes as the ceiling.

    The first version of this matrix drove these four values with the retailer cell
    blank only — so it swept its values properly and never varied the one cell that
    decides which code path reads them. The ceiling had been fixed in both branches
    while the floor was still fixed in one: a retailer-backed row became an
    `order_items` row whose only lower bound was the database's `quantity_positive`
    constraint, so `quantity: 0` previewed as a clean create and applied as a 500.

    Driven through `http_client` so the apply asserts a status rather than dying on
    a re-raised `IntegrityError` that says nothing about which status was intended.
    """
    sheet = starter_sheet_csv([sheet_row(quantity, retailer=retailer)])

    resp = await http_client.post(
        "/import/preview",
        files={"file": ("starter-sheet.csv", sheet, "text/csv")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()

    reported = plan["blocking_errors"] + [
        row["error"] for table in plan["tables"] for row in table["rows"] if row["error"]
    ]
    assert any("quantity" in str(said) for said in reported), plan

    applied = await http_client.post(
        "/import/apply",
        files={"file": ("starter-sheet.csv", sheet, "text/csv")},
        data={"mode": "merge", "plan_hash": plan["plan_hash"]},
    )
    assert applied.status_code == 409, f"{applied.status_code}: {applied.text[:200]}"
    assert (await http_client.get("/kits")).json() == []
    assert (await http_client.get("/orders")).json() == []


@pytest.mark.parametrize(
    "quantity", [pytest.param("0", id="zero"), pytest.param("-2", id="negative")]
)
@pytest.mark.parametrize(
    "row_state",
    [pytest.param("create", id="a new line"), pytest.param("update", id="an existing line")],
)
async def test_a_normalized_order_line_is_held_to_the_lower_bound(http_client, quantity, row_state):
    """The sibling path: `order_items.csv` reaches the same fan-out without the
    starter sheet in front of it, and an update reaches it by a different branch of
    `_classify` than a create."""
    retailer = (await http_client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await http_client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()

    line = {
        "id": order["items"][0]["id"] if row_state == "update" else "",
        "order_id": order["id"],
        "item_type": "kit",
        "quantity": quantity,
        "unit_price_minor": "2800",
        "currency_code": "JPY",
        "kit_name": "Zaku II",
        "kit_grade": "HG",
    }
    content = make_csv(spec.ORDER_ITEMS.header, [line])

    resp = await http_client.post(
        "/import/preview",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    assert "quantity" in plan["tables"][0]["rows"][0]["error"]

    applied = await http_client.post(
        "/import/apply",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge", "plan_hash": plan["plan_hash"]},
    )
    assert applied.status_code == 409, f"{applied.status_code}: {applied.text[:200]}"
    # The stored line is untouched.
    stored = (await http_client.get(f"/orders/{order['id']}")).json()
    assert stored["items"][0]["quantity"] == 1


async def test_the_expansion_stops_before_building_the_rows_it_cannot_keep(
    http_client, monkeypatch
):
    """Charged up front, not measured afterwards.

    `plan_import` compares `MAX_ROWS` against what expansion *returned*, which is far
    too late to be a budget: the rows already exist by then. On the reviewed head a
    1,915-byte, 51-row sheet built 51,000 kit dictionaries before anything objected,
    and the reachable worst case is a permitted 50,000-row sheet attempting
    50,000,000.

    Proved by counting `_present` calls rather than by timing it. With a budget of
    1,500 and five rows of 1,000, an unbudgeted expansion builds 5,000 rows; charging
    before each fan-out means the first row is built and the second is refused, so
    the count stops at exactly 1,000.
    """
    monkeypatch.setattr(importing, "MAX_ROWS", 1_500)
    built = 0
    original = starter_sheet._present

    def counting(*args, **kwargs):
        nonlocal built
        built += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(starter_sheet, "_present", counting)

    sheet = starter_sheet_csv([sheet_row("1000", name=f"Kit {i}") for i in range(5)])
    resp = await http_client.post(
        "/import/preview",
        files={"file": ("starter-sheet.csv", sheet, "text/csv")},
        data={"mode": "merge"},
    )

    assert resp.status_code == 422, resp.text
    assert "expands to more than" in resp.json()["detail"]
    assert built == 1_000, f"{built} rows were built before the budget stopped it"


async def test_the_expansion_budget_is_cumulative_across_zip_members(http_client, monkeypatch):
    """Two starter sheets in one zip share one allowance.

    The single-CSV test above proves the charge happens before the rows are built;
    this proves the allowance isn't handed out fresh per member. A per-member budget
    would let an archive of N sheets spend `MAX_ROWS` N times over, which is the same
    defect the compressed-vs-expanded byte budget exists to prevent one layer down.

    Counted rather than timed, for the same reason: with 1,500 allowed and two sheets
    of 1,000, the first is built and the second is refused, so `_present` stops at
    exactly 1,000 rather than 2,000.
    """
    monkeypatch.setattr(importing, "MAX_ROWS", 1_500)
    built = 0
    original = starter_sheet._present

    def counting(*args, **kwargs):
        nonlocal built
        built += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(starter_sheet, "_present", counting)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for member in ("sheet-one.csv", "sheet-two.csv"):
            archive.writestr(member, starter_sheet_csv([sheet_row("1000", name=member)]))

    resp = await http_client.post(
        "/import/preview",
        files={"file": ("archive.zip", buffer.getvalue(), "application/zip")},
        data={"mode": "merge"},
    )

    assert resp.status_code == 422, resp.text
    assert "expands to more than" in resp.json()["detail"]
    assert built == 1_000, f"{built} rows were built — the second sheet got its own budget"


# --- received state feeding the fan-out (#47) --------------------------------------


def _two_line_order(first_received: str, second_received: str) -> bytes:
    """One order, two kit rows — the ordinary multi-kit haul shape."""
    shared = {
        "retailer": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-1",
        "unit_price": "24.50",
        "currency": "AUD",
        "quantity": "1",
    }
    return starter_sheet_csv(
        [
            {"kit_name": "Zaku II", "grade": "HG", "received": first_received, **shared},
            {"kit_name": "Gouf", "grade": "HG", "received": second_received, **shared},
        ]
    )


@pytest.mark.parametrize(
    ("first", "second", "outcome"),
    [
        pytest.param("yes", "", "received", id="stated on the first row only"),
        pytest.param("", "yes", "received", id="stated on the later row only"),
        pytest.param("no", "", "not received", id="no on the first row only"),
        pytest.param("", "no", "not received", id="no on the later row only"),
        pytest.param("yes", "yes", "received", id="agreeing"),
        pytest.param("no", "no", "not received", id="agreeing on no"),
        pytest.param("", "", "received", id="neither row says"),
        pytest.param("yes", "no", "conflict", id="contradicting"),
        pytest.param("no", "yes", "conflict", id="contradicting the other way"),
        pytest.param("yes", "maybe", "error", id="a typo on the later row"),
        pytest.param("maybe", "yes", "error", id="a typo on the first row"),
    ],
)
async def test_received_is_resolved_across_every_row_of_one_order(client, first, second, outcome):
    """`received` used to be read from the row that *opened* an order group and
    nowhere else, because the parse sat inside `if key not in orders`. A five-kit
    haul is five rows and one order, so a typo on rows 2-5 silently meant
    "received" and an explicit `no` down there was dropped on the floor — on the
    single most ordinary shape this sheet has (review of #79/#47).

    Every row is parsed now, and the group is resolved from whatever the rows
    actually state: blank is "didn't say" rather than "no", so stating it once is
    enough, while two rows stating *different* things is refused rather than
    resolved by position.
    """
    sheet = _two_line_order(first, second)
    plan = await preview(client, sheet, filename="starter-sheet.csv")

    if outcome in {"conflict", "error"}:
        reported = plan["blocking_errors"] + [
            r["error"] for t in plan["tables"] for r in t["rows"] if r["error"]
        ]
        assert any("received" in str(said) for said in reported), plan
        if outcome == "conflict":
            assert any("has to agree" in str(said) for said in reported), reported
        assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 409
        assert (await client.get("/orders")).json() == []
        return

    assert plan["blocking_errors"] == [], plan
    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200

    orders = (await client.get("/orders")).json()
    assert len(orders) == 1, "two rows sharing retailer + date + number are one order"
    assert len(orders[0]["items"]) == 2
    if outcome == "received":
        assert orders[0]["received_at"] is not None
    else:
        assert orders[0]["received_at"] is None


@pytest.mark.parametrize(
    ("first_pass", "second_pass", "ends_received"),
    [
        pytest.param("no", "yes", True, id="no -> yes"),
        pytest.param("yes", "no", False, id="yes -> no"),
    ],
)
async def test_re_importing_a_starter_sheet_moves_receipt_in_both_directions(
    client, first_pass, second_pass, ends_received
):
    """The update axis, which the create-only matrix above cannot reach.

    `no` resolves to an empty `received_at`, and `_present()` drops empty cells —
    so the matched `orders` row carried no `received_at` at all and the generic
    classifier had nothing to clear. Importing `yes` and then `no` left the order
    received, which is the sheet failing to say something it plainly said. The
    expansion now sets `received_at` unconditionally, so an explicit `no` reaches
    the classifier as a real "clear this" (review of #79/#47).
    """
    row = {
        "kit_name": "Zaku II",
        "grade": "HG",
        "quantity": "1",
        "retailer": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-1",
        "unit_price": "24.50",
        "currency": "AUD",
    }

    first = starter_sheet_csv([{**row, "received": first_pass}])
    assert (await apply(client, first, filename="starter-sheet.csv")).status_code == 200
    started_received = (await client.get("/orders")).json()[0]["received_at"] is not None
    assert started_received is (first_pass == "yes")

    second = starter_sheet_csv([{**row, "received": second_pass}])
    assert (await apply(client, second, filename="starter-sheet.csv")).status_code == 200

    orders = (await client.get("/orders")).json()
    assert len(orders) == 1, "the re-import must match the same order, not add one"
    assert (orders[0]["received_at"] is not None) is ends_received


@pytest.mark.parametrize(
    ("cell", "outcome"),
    [
        pytest.param("", "received", id="blank"),
        pytest.param("no", "not received", id="no"),
        pytest.param("FALSE", "not received", id="FALSE"),
        pytest.param("yes", "received", id="yes"),
        pytest.param("maybe", "error", id="maybe"),
    ],
)
async def test_received_cell_is_parsed_as_a_boolean(client, cell, outcome):
    """`received` used to be a hand-rolled string check recognising only a fixed
    negative set, so a typo like `maybe` silently read as "received" instead of
    being refused. It's declared and parsed as `parse_bool` now, so anything that
    isn't a yes/no spelling is a row error rather than a guess.
    """
    row = sheet_row("1", retailer="Hobby Link Japan")
    row["received"] = cell
    sheet = starter_sheet_csv([row])

    plan = await preview(client, sheet, filename="starter-sheet.csv")

    if outcome == "error":
        reported = plan["blocking_errors"] + [
            r["error"] for t in plan["tables"] for r in t["rows"] if r["error"]
        ]
        assert any("received" in str(said) for said in reported), plan
        return

    assert plan["blocking_errors"] == [], plan
    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200
    order = (await client.get("/orders")).json()[0]
    if outcome == "received":
        assert order["received_at"] is not None
    else:
        assert order["received_at"] is None


async def test_a_received_starter_order_lands_its_kits_in_backlog(client):
    """A received order used to spawn its kits `ordered` regardless: `apply_import`
    called `spawn_kits` without `received`, so `_initial_kit_status` never ran and
    the collection was wrong the moment onboarding finished (#47).
    """
    row = sheet_row("1", retailer="Hobby Link Japan")
    row.pop("status", None)  # blank -> spawn_kits' own default of `ordered`
    row["received"] = "yes"
    sheet = starter_sheet_csv([row])

    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200
    kits = (await client.get("/kits")).json()
    assert [k["status"] for k in kits] == ["backlog"]


async def test_an_unreceived_starter_order_leaves_its_kits_on_the_way(client):
    """The mirror of the case above: an order that hasn't arrived must not have its
    kits advanced to `backlog`."""
    row = sheet_row("1", retailer="Hobby Link Japan")
    row.pop("status", None)
    row["received"] = "no"
    sheet = starter_sheet_csv([row])

    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200
    kits = (await client.get("/kits")).json()
    assert [k["status"] for k in kits] == ["ordered"]


async def test_apply_is_rejected_once_the_parent_order_is_received_after_preview(http_client):
    """Whether a spawn lands `backlog` depends on the parent order's `received_at` —
    a value no row in the plan carries directly — so the fingerprint has to read it
    from the order, not assume a spawn with the same shape means the same outcome.

    Before `_Spawn.received` joined `_plan_fingerprint`'s payload, two plans built
    from the same file — one before the order was received, one after — hashed
    identically even though one spawns an `ordered` kit and the other a `backlog`
    one. That let a stale preview apply cleanly: exactly the drift #41's plan_hash
    exists to catch (review of #79/#47).
    """
    retailer = (await http_client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await http_client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()

    line = {
        "order_id": order["id"],
        "item_type": "kit",
        "quantity": "1",
        "unit_price_minor": "2800",
        "currency_code": "JPY",
        "kit_name": "Char's Zaku II",
        "kit_grade": "HG",
    }
    content = make_csv(spec.ORDER_ITEMS.header, [line])

    preview_resp = await http_client.post(
        "/import/preview",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
    assert preview_resp.status_code == 200, preview_resp.text
    plan_hash = preview_resp.json()["plan_hash"]

    # The order arrives between preview and apply — the exact race the hash exists
    # to catch.
    assert (await http_client.post(f"/orders/{order['id']}/receive")).status_code == 200

    applied = await http_client.post(
        "/import/apply",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge", "plan_hash": plan_hash},
    )
    assert applied.status_code == 409, applied.text
    # Rejected, not half-applied.
    assert {k["name"] for k in (await http_client.get("/kits")).json()} == {"Zaku II"}


async def test_add_only_reads_received_state_off_the_order_it_will_keep_not_the_file(
    http_client,
):
    """`add_only` leaves a matched order row completely alone (SKIP) — but the
    fan-out for a *new* line on that same order used to read the order's received
    state off the uploaded cell regardless, rather than the persisted row that
    import will actually leave standing. An add-only file with a blank
    `received_at` on an already-received order therefore spawned an `ordered` kit
    instead of `backlog` (review of #79/#47).
    """
    retailer = (await http_client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await http_client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "received": True,
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()

    orders_row = {
        "id": order["id"],
        "retailer_name": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-1",
        "currency_code": "JPY",
        "received_at": "",  # blank on the file; the order this import keeps is received
    }
    line = {
        "order_id": order["id"],
        "item_type": "kit",
        "quantity": "1",
        "unit_price_minor": "2800",
        "currency_code": "JPY",
        "kit_name": "Char's Zaku II",
        "kit_grade": "HG",
    }
    archive = make_archive({"orders": [orders_row], "order_items": [line]})

    plan = await preview(http_client, archive, mode="add_only")
    assert actions(plan, "orders") == ["skip"], plan

    resp = await apply(http_client, archive, mode="add_only")
    assert resp.status_code == 200, resp.text

    stored_order = (await http_client.get(f"/orders/{order['id']}")).json()
    assert stored_order["received_at"] is not None  # untouched by add_only

    kits = {k["name"]: k for k in (await http_client.get("/kits")).json()}
    assert kits["Char's Zaku II"]["status"] == "backlog"


async def test_a_spawn_free_import_that_edits_a_line_and_receives_its_order_succeeds(client):
    """An `order_items.csv` price correction on an existing line, combined with an
    `orders.csv` receipt transition on its parent, in one apply — with no spawn
    anywhere in it.

    Both halves land, and the kit-arrival side effect still reaches the line's
    pre-existing kit even though nothing in the upload mentions that kit and no
    fan-out put it there. The two tables are planned and written independently,
    so this is the case where an order-level derivation has to survive a
    same-apply edit to its own child rows (review of #79/#47).
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    assert order["received_at"] is None
    item_id = order["items"][0]["id"]

    orders_row = {
        "id": order["id"],
        "retailer_name": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-1",
        "currency_code": "JPY",
        "received_at": "2026-03-20T00:00:00Z",
    }
    line = {
        "id": item_id,
        "order_id": order["id"],
        "item_type": "kit",
        "quantity": "1",
        "unit_price_minor": "3000",  # the correction — no new line
        "currency_code": "JPY",
        "kit_name": "Zaku II",
        "kit_grade": "HG",
    }
    archive = make_archive({"orders": [orders_row], "order_items": [line]})

    plan = await preview(client, archive, mode="merge")
    assert plan["blocking_errors"] == [], plan
    assert actions(plan, "orders") == ["update"], plan
    assert actions(plan, "order_items") == ["update"], plan
    assert plan["derived"]["kits_spawned"] == 0

    applied = await apply(client, archive, mode="merge")
    assert applied.status_code == 200, applied.text

    stored_order = (await client.get(f"/orders/{order['id']}")).json()
    assert stored_order["received_at"] is not None
    assert stored_order["items"][0]["unit_price_minor"] == 3000

    kits = (await client.get("/kits")).json()
    assert [k["status"] for k in kits] == ["backlog"]


async def test_an_import_that_both_receives_an_order_and_adds_a_line_succeeds(client):
    """One apply that both receives an existing order and adds a line to it.

    `_order_received()` answers a matched UPDATE row with the *post-apply* state,
    which is what the fan-out needs: a line added in the same apply that also
    receives its order should spawn `backlog`, not `ordered`.

    Also covers the sibling gap the same review raised: `receive_order()` always
    advances every arrival-eligible kit on the order it receives, but the
    importer writes model rows directly and skipped that side effect for a kit
    this import doesn't otherwise mention. The order's pre-existing kit here must
    land `backlog` right alongside the newly spawned one (review of #79/#47).
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    assert order["received_at"] is None

    orders_row = {
        "id": order["id"],
        "retailer_name": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-1",
        "currency_code": "JPY",
        "received_at": "2026-03-20T00:00:00Z",
    }
    line = {
        "order_id": order["id"],
        "item_type": "kit",
        "quantity": "1",
        "unit_price_minor": "2800",
        "currency_code": "JPY",
        "kit_name": "Char's Zaku II",
        "kit_grade": "HG",
    }
    archive = make_archive({"orders": [orders_row], "order_items": [line]})

    plan = await preview(client, archive, mode="merge")
    assert plan["blocking_errors"] == [], plan
    assert actions(plan, "orders") == ["update"], plan
    assert plan["derived"]["kits_spawned"] == 1

    applied = await apply(client, archive, mode="merge")
    assert applied.status_code == 200, applied.text

    stored_order = (await client.get(f"/orders/{order['id']}")).json()
    assert stored_order["received_at"] is not None

    kits = {k["name"]: k["status"] for k in (await client.get("/kits")).json()}
    assert kits == {"Zaku II": "backlog", "Char's Zaku II": "backlog"}


async def test_clearing_an_orders_received_at_does_not_touch_its_kits(client):
    """The other half of the transition: nothing established mirrors an
    "un-arrive" for a kit, so an import that clears `received_at` back to blank
    must not silently move a kit backwards out of `backlog` — it just leaves
    kits exactly as they already were, the same as before this behaviour
    existed (review of #79/#47).
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "received": True,
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    assert order["received_at"] is not None
    kit_id = order["items"][0]["kits"][0]["id"]
    await client.patch(f"/kits/{kit_id}", json={"status": "building"})

    orders_row = {
        "id": order["id"],
        "retailer_name": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-1",
        "currency_code": "JPY",
        "received_at": "",
    }
    archive = make_archive({"orders": [orders_row]})

    applied = await apply(client, archive, mode="merge")
    assert applied.status_code == 200, applied.text

    stored_order = (await client.get(f"/orders/{order['id']}")).json()
    assert stored_order["received_at"] is None
    stored_kit = (await client.get(f"/kits/{kit_id}")).json()
    assert stored_kit["status"] == "building"  # untouched, not reverted


async def test_correcting_an_already_received_orders_timestamp_does_not_touch_its_kits(client):
    """A third state for `received_at`, distinct from both the arrival case and
    the clearing case above: an already-received order whose timestamp is
    corrected to a *different* non-null value. No transition into received
    happens here — it already was — so nothing about a pipeline kit on that
    order should move, even though `row.target.received_at` is non-null both
    before and after the write and a naive "is it non-null now" check can't
    tell this apart from a genuine arrival (review of #79/#47).

    No spawn anywhere in this import, on purpose: nothing on the fan-out path
    could have caught it, so the distinction has to live in
    `_advance_kits_for_newly_received_orders` itself.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "received": True,
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    original_received_at = order["received_at"]
    assert original_received_at is not None

    kit_id = order["items"][0]["kits"][0]["id"]
    # Arrival-eligible, and NOT the status a receive would have left it in — so
    # an incorrect advance to `backlog` is unmistakable in the assertion below.
    await client.patch(f"/kits/{kit_id}", json={"status": "ordered"})
    kit_before = (await client.get(f"/kits/{kit_id}")).json()
    assert kit_before["status"] == "ordered"

    orders_row = {
        "id": order["id"],
        "retailer_name": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-1",
        "currency_code": "JPY",
        "received_at": "2026-04-01T00:00:00Z",  # a correction, not a first arrival
    }
    archive = make_archive({"orders": [orders_row]})

    plan = await preview(client, archive, mode="merge")
    assert actions(plan, "orders") == ["update"], plan

    applied = await apply(client, archive, mode="merge")
    assert applied.status_code == 200, applied.text

    stored_order = (await client.get(f"/orders/{order['id']}")).json()
    assert stored_order["received_at"] != original_received_at  # the correction landed

    kit_after = (await client.get(f"/kits/{kit_id}")).json()
    assert kit_after["status"] == "ordered"  # not advanced to backlog
    assert kit_after["status_updated_at"] == kit_before["status_updated_at"]


async def test_an_import_does_not_revert_a_kit_someone_moved_on_during_it(client, monkeypatch):
    """Codex repro 3 from the #79 review, reachable only now that the importer has
    a kit-arrival side effect at all.

    An orders-only receipt update plans just the Order, but
    `_advance_kits_for_newly_received_orders` also mutates pre-existing kits — off
    the relationship snapshot planning loaded. A normal `PATCH /kits/{id}` to
    `building` landing between the plan and that write used to be overwritten back
    to `backlog`, which the REST receive path would never do.

    The write gate (#80) makes that interleaving unreachable: the PATCH waits for
    the apply to commit, then lands on top. `building` survives, and `backlog` is
    never what the kit ends on.

    The racer is launched as a task and awaited *after* the apply — under the gate
    it blocks until the apply commits, so awaiting it inline would deadlock the
    test against the serialization it is checking.
    """
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
                "currency_code": "JPY",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 2800,
                        "currency_code": "JPY",
                        "kit": {"name": "Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    kit_id = order["items"][0]["kits"][0]["id"]

    orders_row = {
        "id": order["id"],
        "retailer_name": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-1",
        "currency_code": "JPY",
        "received_at": "2026-03-20T00:00:00Z",
    }
    archive = make_archive({"orders": [orders_row]})

    plan = await preview(client, archive, mode="merge")
    assert plan["blocking_errors"] == [], plan
    plan_hash = plan["plan_hash"]

    original_plan_import = importing.plan_import
    racer: dict[str, asyncio.Task] = {}
    patched: list[int] = []

    async def plan_then_patch_the_kit(*args, **kwargs):
        execution = await original_plan_import(*args, **kwargs)

        async def move_it_on() -> None:
            resp = await client.patch(f"/kits/{kit_id}", json={"status": "building"})
            patched.append(resp.status_code)

        task = asyncio.create_task(move_it_on())
        racer["task"] = task
        # Waits for an observable state, not a duration: either the racer is
        # parked on the gate (the guard working) or it has finished (the guard
        # gone, and its write lands before the apply's — the interleaving this
        # regression needs). A fixed sleep only creates the opportunity for one
        # of those; it never establishes that either happened.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if task.done() or await _a_writer_is_parked_on_the_gate():
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError(
                "the racing PATCH neither completed nor blocked on the gate — "
                "this test is not exercising the interleaving it claims to"
            )
        return execution

    monkeypatch.setattr(importing, "plan_import", plan_then_patch_the_kit)

    applied = await client.post(
        "/import/apply",
        files={"file": ("archive.zip", archive, "application/zip")},
        data={"mode": "merge", "plan_hash": plan_hash},
    )
    await racer["task"]

    assert applied.status_code == 200, applied.text
    assert patched == [200], f"the racing PATCH didn't land: {patched}"

    stored = (await client.get(f"/kits/{kit_id}")).json()
    assert stored["status"] == "building", (
        "an import's kit-arrival side effect reverted a kit somebody had already moved to building"
    )


# --- the version an archive claims (release prep) ---------------------------------


async def test_the_manifest_reports_this_instances_version(client):
    """`app_version` was a literal `"0.1.0"` from the day it was written, and stayed
    that way through six releases: it is written into every archive and read by
    nobody, so nothing ever noticed. It now comes from the same `__version__` that
    `/meta` and the MCP handshake report, and this is what keeps it there."""
    await seed_collection(client)
    archive = (await client.get("/export/archive")).content

    assert read_manifest(archive)["app_version"] == app_version
    assert (await client.get("/meta")).json()["version"] == app_version


def test_the_packaging_version_matches_the_one_the_app_reports():
    """`pyproject.toml` carries a comment saying to keep it in step with
    `app/__init__.py`, and until now that comment was the only thing enforcing it."""
    declared = tomllib.loads(
        (pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    )["project"]["version"]
    assert declared == app_version


# --- replace_all resolves only against the upload (#45) ---------------------------
#
# A replace_all truncates every portable table and then writes the upload, so the
# rows it is about to delete are not a world any reference may point into. The
# planner was already mode-aware nearly everywhere — matching skipped, "you already
# have one of these" suppressed — and `_resolve_ref` was the one step still asking
# the live database, by uuid and by readable-mirror name.
#
# What that cost depends on whether the column has a foreign key.
# `order_items.catalog_ref_id` is polymorphic across three catalog tables and so has
# none: the apply committed a line holding a truncated row's uuid and nothing ever
# complained. The other four fail at flush — a rollback rather than corruption, but
# a 500 raised *after* the operator typed REPLACE against a preview that promised
# the import was clean.
#
# The two axes below are both real and neither implies the other. Which dependency
# is missing decides whether anything catches it; how the row *names* it decides
# whether it can be satisfied at all, because a readable name is satisfiable by
# creating what it names and a bare uuid is not.


async def _seeded_archive_without(client, omit: str) -> tuple[bytes, dict]:
    """A real exported archive with one table's CSV dropped, so every reference into
    it is left naming a row that only exists in the live database."""
    seeded = await seed_collection(client)
    upgrade = (
        await client.post(
            "/upgrades",
            json={"name": "Metal Thruster", "manufacturer": "Kotobukiya", "quantity_on_hand": 1},
        )
    ).json()
    kit_id = (await client.get("/kits")).json()[0]["id"]
    applied = await client.post(
        f"/upgrades/{upgrade['id']}/apply", json={"kit_id": kit_id, "quantity": 1}
    )
    assert applied.status_code == 201, applied.text

    tables = read_archive((await client.get("/export/archive")).content)
    assert tables[omit], f"the seed produced no {omit} rows — this case tests nothing"
    del tables[omit]
    return make_archive(tables), seeded


@pytest.mark.parametrize(
    ("omit", "referrer", "column", "mirror"),
    [
        # One case per dependency class, and one per shape of consequence: the
        # catalog line is the silent one, the other four are the 500s.
        #
        # `mirror` is not decoration. Two of these columns have a readable twin and
        # an exported archive fills it in, so dropping the CSV alone leaves the row
        # still able to say what it wants and the reference resolves by creating it
        # — correct, and the subject of the next test, but not this one. Blanking
        # the twin is what leaves a bare uuid, which is the state that used to be
        # answered out of the database. The first draft of this matrix omitted it
        # and those two cases went green on the fix for the wrong reason.
        pytest.param(
            "retailers", "orders", "retailer_id", "retailer_name", id="the retailer an order names"
        ),
        pytest.param(
            "consumables",
            "order_items",
            "catalog_ref_id",
            "catalog_name",
            id="the catalog item a line buys",
        ),
        pytest.param("orders", "order_items", "order_id", None, id="the order a line belongs to"),
        pytest.param("order_items", "kits", "order_item_id", None, id="the line that bought a kit"),
        pytest.param(
            "kits", "upgrade_applications", "kit_id", None, id="the kit an upgrade went onto"
        ),
    ],
)
async def test_replace_all_blocks_a_reference_the_upload_does_not_contain(
    client, omit, referrer, column, mirror
):
    """#45. Every one of these previewed clean and applied: four wrote a dangling
    foreign key and 500'd at flush, and the catalog line — polymorphic, so no FK —
    committed a dead uuid in silence."""
    archive, _ = await _seeded_archive_without(client, omit)
    if mirror is not None:
        tables = read_archive(archive)
        for row in tables[referrer]:
            row[mirror] = ""
        archive = make_archive(tables)
    before = await snapshot(client)

    plan = await preview(client, archive, mode="replace_all")

    assert plan["blocking_errors"], (
        f"{referrer}.{column} named a {omit} row this upload deletes, and the preview "
        "raised nothing"
    )
    assert "error" in actions(plan, referrer), actions(plan, referrer)
    errored = [row for row in _rows_of(plan, referrer) if row["action"] == "error"]
    assert all(column in row["error"] for row in errored), errored
    assert all(omit in row["error"] for row in errored), errored

    resp = await apply(client, archive, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 409, resp.text
    assert await snapshot(client) == before, "a blocked replace_all still destroyed the collection"


def _rows_of(plan: dict, table: str) -> list[dict]:
    for entry in plan["tables"]:
        if entry["table"] == table:
            return entry["rows"]
    return []


@pytest.mark.parametrize(
    ("omit", "referrer", "column", "mirror", "name"),
    [
        pytest.param(
            "retailers",
            "orders",
            "retailer_id",
            "retailer_name",
            "Hobby Link Japan",
            id="an order naming its retailer",
        ),
        pytest.param(
            "consumables",
            "order_items",
            "catalog_ref_id",
            "catalog_name",
            "Gundam Marker GM02",
            id="a line naming its catalog item",
        ),
    ],
)
async def test_replace_all_still_creates_what_a_readable_name_asks_for(
    client, omit, referrer, column, mirror, name
):
    """The neighbour of the matrix above, and the reason it varies the *shape* of
    the reference rather than only which table is missing.

    Blocking a dangling uuid must not block a readable name, because a name is
    satisfiable: an archive that supplies `retailer_name` with no retailers.csv is
    a documented onboarding path, and the right answer is to create the retailer —
    which exists after the truncate — not to resolve to the one being deleted.
    Drop the mode gate on the uuid branch and the test above still passes while
    this one starts failing, and vice versa.
    """
    archive, _ = await _seeded_archive_without(client, omit)
    tables = read_archive(archive)
    for row in tables[referrer]:
        if row[column]:
            row[column] = ""  # the uuid is gone; only the readable name is left
            assert row[mirror] == name, row

    plan = await preview(client, make_archive(tables), mode="replace_all")
    assert not plan["blocking_errors"], plan["blocking_errors"]

    resp = await apply(client, make_archive(tables), mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text

    # Created, not resolved to the row that was deleted — one row, and the referrer
    # points at the one that now exists.
    listed = (await client.get(f"/{omit}")).json()
    assert [item["name"] for item in listed] == [name], listed
    assert await _dangling_references(column) == []


async def _dangling_references(column: str) -> list:
    """Every value of a reference column that names no live row. Asked of the
    database rather than the API, because the column this issue is really about —
    `order_items.catalog_ref_id` — has no foreign key and so is exactly the one a
    serialized response will happily render as a uuid nobody can follow."""
    table = {"retailer_id": "orders", "catalog_ref_id": "order_items"}[column]
    targets = {
        "retailer_id": "SELECT id FROM retailers",
        "catalog_ref_id": (
            "SELECT id FROM tools UNION SELECT id FROM consumables "
            "UNION SELECT id FROM upgrades UNION SELECT id FROM display_items"
        ),
    }[column]
    async with session_scope() as session:
        rows = await session.scalars(
            sa_text(
                # Interpolated, not parameterised: every piece comes from the two
                # literal maps above, and a table name can't be a bind parameter.
                f"SELECT {column} FROM {table} "
                f"WHERE {column} IS NOT NULL AND {column} NOT IN ({targets})"
            )
        )
        return list(rows.all())


async def test_merge_still_resolves_a_reference_to_a_row_it_is_keeping(client):
    """The counter-case, and the one that keeps the fix from over-reaching.

    In merge mode nothing is truncated, so a uuid found in the live database is a
    perfectly good answer — the row is still there afterwards. Only replace_all may
    not trust it. Without this, "resolve against the upload only" reads like a
    general rule and the next reader applies it to both modes.
    """
    archive, seeded = await _seeded_archive_without(client, "retailers")
    before = await snapshot(client)

    plan = await preview(client, archive, mode="merge")
    assert not plan["blocking_errors"], plan["blocking_errors"]

    resp = await apply(client, archive, mode="merge")
    assert resp.status_code == 200, resp.text
    assert await snapshot(client) == before  # re-importing an archive is a no-op
    assert [r["name"] for r in (await client.get("/retailers")).json()] == [
        seeded["retailer"]["name"]
    ]


# --- import identity: currency, units, and the upload itself (#46) -----------------
#
# Three independent causes behind one symptom — an import conflating two things that
# are not the same, or failing to see that one thing is in the file twice.
#
#  1. `_line_fingerprint` had no currency, so a stored ¥1000 line and an incoming
#     A$1000 line were the same purchase and the apply relabelled the stored one.
#  2. Order matching groups the incoming lines in a pre-pass that called `_parse_row`
#     and nothing else, so a sheet stating major units fingerprinted as 0 against
#     stored minor units and the fallback never matched.
#  3. `by_id`/`by_natural` are built from the database and never learn what the
#     upload is planning, so nothing could see a duplicate inside one file.


async def _unnumbered_order(client) -> tuple[dict, dict]:
    """An order with no `order_number`, so matching has to fall back to
    retailer + date + lines — the path causes 1 and 2 both run through."""
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-04-02",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "consumable",
                        "quantity": 2,
                        "unit_price_minor": 1250,
                        "currency_code": "AUD",
                        "new_item": {"name": "Mr Surfacer 1200", "category": "paint"},
                    }
                ],
            },
        )
    ).json()
    return retailer, order


async def test_a_line_in_another_currency_is_a_different_purchase(client):
    """Cause 1, and the one that corrupts rather than duplicates.

    Same item, same quantity, same number — in yen instead of dollars. The line
    fingerprint had no currency, so this matched the stored AUD line and the apply
    wrote `currency_code: JPY` over it as an ordinary field update: #12's
    relabelling reached from a different direction, and §6's whole point is that
    the code on the row is what the amount means.
    """
    seeded = await seed_collection(client)
    line = next(i for i in seeded["order"]["items"] if i["item_type"] == "consumable")

    content = make_csv(
        spec.ORDER_ITEMS.header,
        [
            {
                "id": "",
                "order_id": seeded["order"]["id"],
                "item_type": "consumable",
                "catalog_name": "Gundam Marker GM02",
                "quantity": "3",
                "unit_price_minor": "500",
                "currency_code": "JPY",  # the stored line is AUD
            }
        ],
    )

    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["create"], (
        "an amount in a different currency matched the stored line — the fingerprint "
        "is comparing numbers without their units"
    )

    resp = await apply(client, content, filename="order_items.csv")
    assert resp.status_code == 200, resp.text

    stored = (await client.get("/orders")).json()[0]["items"]
    original = next(i for i in stored if i["id"] == line["id"])
    assert original["currency_code"] == "AUD", "the stored line was relabelled to JPY"
    assert len(stored) == 3, "the yen line should have been recorded as its own purchase"


@pytest.mark.parametrize(
    ("column", "value", "currency", "matches"),
    [
        # The control: the same amount, said the way the exporter says it.
        pytest.param("unit_price_minor", "1250", "AUD", True, id="minor units, same currency"),
        # Cause 2: the same amount in the major-unit twin. The pre-pass never ran
        # `_apply_money_alternates`, so this fingerprinted as 0.
        pytest.param("unit_price", "12.50", "AUD", True, id="major units, same currency"),
        # Cause 1 again, one level up: the order-level fallback compares the same
        # tuples, so a currency change has to stop the order matching too.
        pytest.param("unit_price_minor", "1250", "JPY", False, id="minor units, other currency"),
    ],
)
async def test_the_order_fallback_compares_amounts_in_the_same_units(
    client, column, value, currency, matches
):
    """The `retailer + date + lines` match, driven by a foreign order id — the shape
    an archive from another instance has, where nothing matches by id and the lines
    are the only evidence the order is the one already on file."""
    retailer, order = await _unnumbered_order(client)
    foreign = str(uuid.uuid4())

    archive = make_archive(
        {
            "orders": [
                {
                    "id": foreign,
                    "retailer_id": retailer["id"],
                    "order_date": "2026-04-02",
                    "currency_code": "AUD",
                }
            ],
            "order_items": [
                {
                    "id": "",
                    "order_id": foreign,
                    "item_type": "consumable",
                    "catalog_name": "Mr Surfacer 1200",
                    "quantity": "2",
                    column: value,
                    "currency_code": currency,
                }
            ],
        }
    )

    plan = await preview(client, archive)
    assert actions(plan, "orders") == (["unchanged"] if matches else ["create"]), (
        f"a line stated as {column}={value} {currency} "
        f"{'failed to match' if matches else 'matched'} the stored 1250 AUD line"
    )

    resp = await apply(client, archive)
    assert resp.status_code == 200, resp.text
    orders = (await client.get("/orders")).json()
    assert len(orders) == (1 if matches else 2), [o["id"] for o in orders]


@pytest.mark.parametrize(
    ("mode", "seed_it"),
    [
        # Both rows become creates on one primary key: `session.add` twice, then an
        # IntegrityError out of the flush — a 500 after a preview showing two clean
        # creates. Asserted through `http_client` so the status is a response rather
        # than a re-raised internal exception (rule 6).
        pytest.param("merge", False, id="merge, an id this instance doesn't have"),
        # Both rows match the same existing row instead. No exception — the second
        # update simply overwrites the first, silently.
        pytest.param("merge", True, id="merge, an id it does"),
        # Nothing is matched in replace_all, so every row is a create and the
        # collision is the first case again by another route.
        pytest.param("replace_all", False, id="replace_all"),
    ],
)
async def test_two_rows_cannot_claim_one_id(http_client, mode, seed_it):
    """Cause 3, first half."""
    if seed_it:
        existing = (await http_client.post("/retailers", json={"name": "Gundam Base"})).json()
        claimed = existing["id"]
    else:
        claimed = str(uuid.uuid4())

    content = make_csv(
        spec.RETAILERS.header,
        [{"id": claimed, "name": "Gundam Base"}, {"id": claimed, "name": "Gundam Base Tokyo"}],
    )
    before = [r["name"] for r in (await http_client.get("/retailers")).json()]

    plan = await preview(http_client, content, filename="retailers.csv", mode=mode)
    assert plan["blocking_errors"], "two rows carrying one id previewed as clean"
    assert actions(plan, "retailers")[1] == "error", actions(plan, "retailers")
    assert "row 2" in _rows_of(plan, "retailers")[1]["error"]

    extra = {"confirm": "REPLACE"} if mode == "replace_all" else {}
    resp = await apply(http_client, content, filename="retailers.csv", mode=mode, **extra)
    assert resp.status_code == 409, f"{resp.status_code}: {resp.text[:200]}"
    assert [r["name"] for r in (await http_client.get("/retailers")).json()] == before


async def test_one_file_id_cannot_mean_two_different_rows(http_client):
    """Cause 3, and the state the first cut of this fix missed — found by external
    review, verified against that cut before this test was written.

    Both rows carry file id `X`, but they *resolve differently*: the first
    natural-matches the retailer already here, the second matches nothing and plans
    a create at `X`. Claiming the resolved target sees `A` and `X` — two distinct
    values, nothing to report — so the preview said `unchanged` + `create` and the
    apply returned 200.

    The damage is in the third row. `orders.csv` names `retailer_id=X`, and row 2's
    match recorded `remap[X] → A`, so the order was written pointing at **Gundam
    Base** while the row actually created at `X` was **Other Shop**. One id, two
    meanings, and the import silently picks one. The id in the cell has to be
    claimed on its own, before anything resolves it.
    """
    local = (await http_client.post("/retailers", json={"name": "Gundam Base"})).json()
    claimed = str(uuid.uuid4())
    archive = make_archive(
        {
            "retailers": [
                {"id": claimed, "name": "Gundam Base"},  # natural-matches the local row
                {"id": claimed, "name": "Other Shop"},  # same file id, but creates
            ],
            "orders": [
                {
                    "id": str(uuid.uuid4()),
                    "retailer_id": claimed,  # which of the two does this mean?
                    "order_date": "2026-04-02",
                    "currency_code": "AUD",
                }
            ],
        }
    )

    plan = await preview(http_client, archive)
    assert plan["blocking_errors"], (
        "two rows claiming one file id resolved to different targets and previewed "
        "as clean — the order below would have been written against the wrong shop"
    )
    assert actions(plan, "retailers") == ["unchanged", "error"], actions(plan, "retailers")
    error = _rows_of(plan, "retailers")[1]["error"]
    assert "row 2" in error and claimed in error, error

    resp = await apply(http_client, archive)
    assert resp.status_code == 409, f"{resp.status_code}: {resp.text[:200]}"
    assert [(r["id"], r["name"]) for r in (await http_client.get("/retailers")).json()] == [
        (local["id"], "Gundam Base")
    ]
    assert (await http_client.get("/orders")).json() == []


async def test_two_file_ids_cannot_land_on_one_existing_row(client):
    """The case the *target* claim is for, and the reason it stays alongside the
    file-id claim above rather than being replaced by it.

    Two different file ids, so nothing is duplicated in the cells; both rows
    natural-match the same local retailer, so both plan a write to it. Neither the
    file-id check nor the natural-key check (skipped — both rows supply an id) can
    see this one.
    """
    await client.post("/retailers", json={"name": "Gundam Base"})
    content = make_csv(
        spec.RETAILERS.header,
        [
            {"id": str(uuid.uuid4()), "name": "Gundam Base", "url": "https://one.example"},
            {"id": str(uuid.uuid4()), "name": "gundam base", "url": "https://two.example"},
        ],
    )

    plan = await preview(client, content, filename="retailers.csv")
    assert plan["blocking_errors"], "two rows both updating one retailer previewed as clean"
    assert actions(plan, "retailers")[1] == "error", actions(plan, "retailers")
    assert "already claims this row" in _rows_of(plan, "retailers")[1]["error"]

    assert (await apply(client, content, filename="retailers.csv")).status_code == 409
    assert [r["url"] for r in (await client.get("/retailers")).json()] == [None]


async def test_two_new_rows_cannot_describe_one_retailer(client):
    """Cause 3, second half. Neither row carries an id, so they get different random
    ones and the id check cannot see them — the natural key is the only thing that
    can. Cased differently on purpose: `_name_key` is case-insensitive, matching the
    select-or-create rule the rest of the app de-dups by (rule 3)."""
    content = make_csv(
        spec.RETAILERS.header,
        [{"id": "", "name": "Gundam Base"}, {"id": "", "name": "gundam base"}],
    )

    plan = await preview(client, content, filename="retailers.csv")
    assert plan["blocking_errors"], "one upload created the same retailer twice"
    assert actions(plan, "retailers") == ["create", "error"]
    assert "name" in _rows_of(plan, "retailers")[1]["error"]

    assert (await apply(client, content, filename="retailers.csv")).status_code == 409
    assert (await client.get("/retailers")).json() == []


@pytest.mark.parametrize("mode", ["merge", "replace_all"])
async def test_two_retailers_with_one_name_still_round_trip(client, mode):
    """The neighbour of the test above, and the reason the natural-key check is
    restricted to rows that supply no id.

    A collection can hold two retailers with the same name: there is no unique
    constraint, and until #107 `POST /retailers` didn't dedupe, so an instance may
    still carry the pair. An export writes both, and both rows carry the id that says
    which is which. Apply the natural-key check to those and the archive this
    instance just produced becomes un-importable. Seeded through the session, not the
    API — the API now refuses the second row, which is the other half of the point.
    """
    async with session_scope() as session:
        session.add_all([Retailer(name="Gundam Base"), Retailer(name="Gundam Base")])
        await session.commit()
    archive = (await client.get("/export/archive")).content

    plan = await preview(client, archive, mode=mode)
    assert not plan["blocking_errors"], plan["blocking_errors"]

    extra = {"confirm": "REPLACE"} if mode == "replace_all" else {}
    resp = await apply(client, archive, mode=mode, **extra)
    assert resp.status_code == 200, resp.text
    assert [r["name"] for r in (await client.get("/retailers")).json()] == [
        "Gundam Base",
        "Gundam Base",
    ]


async def test_a_display_order_line_exports_and_reimports_its_catalog_name(client, retailer):
    """The readable mirror for the fourth catalog table (#126).

    `catalog_name` is filled from a per-item_type map in `_fill_alternates`, so it
    is one of the few places a new catalog type needs naming rather than being
    reached through `CATALOG_MODELS`. A missing entry exports a blank cell — which
    still round-trips correctly on the uuid, so the archive tests pass and only the
    human reading the sheet is worse off. Asserted on the exported cell for that
    reason, and then re-imported to prove the blank would not have been benign
    either: with the id stripped, the name is the only thing left to match on.
    """
    item = (
        await client.post(
            "/display-items",
            json={"name": "DCM21 Dio-Com Hangar", "category": "structure", "scale": "1/144"},
        )
    ).json()
    await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "order_number": "HLJ-99",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "display",
                    "quantity": 1,
                    "unit_price_minor": 7999,
                    "currency_code": "AUD",
                    "catalog_ref_id": item["id"],
                }
            ],
        },
    )

    tables = read_archive((await client.get("/export/archive")).content)
    assert [row["name"] for row in tables["display_items"]] == ["DCM21 Dio-Com Hangar"]
    line = tables["order_items"][0]
    assert line["item_type"] == "display"
    assert line["catalog_name"] == "DCM21 Dio-Com Hangar"

    # Now make the name load-bearing: no uuid to fall back on, in a fresh instance.
    for order in (await client.get("/orders")).json():
        assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    for row in (await client.get("/display-items")).json():
        assert (await client.delete(f"/display-items/{row['id']}")).status_code == 204

    tables["order_items"][0]["catalog_ref_id"] = ""
    tables["display_items"][0]["id"] = ""
    resp = await apply(client, make_archive(tables))
    assert resp.status_code == 200, resp.text

    restored = (await client.get("/display-items")).json()
    assert len(restored) == 1, "the named row was matched, not duplicated"
    assert restored[0]["name"] == "DCM21 Dio-Com Hangar"
    assert restored[0]["scale"] == "1/144"
    relinked = (await client.get("/orders")).json()[0]["items"][0]
    assert relinked["catalog_ref_id"] == restored[0]["id"]


# --- #129 review: the enumeration traps a fourth catalog table fell into ----------


def test_every_catalog_table_can_be_stubbed():
    """The registry and the stub placeholders agree — checked here as well as at
    import, because the import-time check only runs where this module is imported.

    Both defects below were one shape: a literal tuple of three table names inside
    the importer, written when three was all there was. Asserting the *derived* sets
    is what makes a fifth catalog type fail here rather than at someone's flush.
    """
    assert importing.CATALOG_TABLES == {"tools", "consumables", "upgrades", "display_items"}
    required = {
        column.name
        for key in importing.CATALOG_TABLES | {"retailers"}
        for column in spec.SPEC_BY_KEY[key].columns
        if column.required and column.name != "name"
    }
    assert required <= importing.STUB_PLACEHOLDERS.keys(), (
        f"no stub placeholder for {sorted(required - importing.STUB_PLACEHOLDERS.keys())}"
    )


@pytest.mark.parametrize(
    ("item_type", "table", "extra"),
    [
        ("consumable", "consumables", {"category": "uncategorised"}),
        ("upgrade", "upgrades", {"manufacturer": "unknown"}),
        ("display", "display_items", {"category": "uncategorised"}),
    ],
    ids=["consumable", "upgrade", "display"],
)
async def test_a_name_only_catalog_line_creates_a_stub_rather_than_500ing(
    http_client, retailer, item_type, table, extra
):
    """A line naming an undeclared catalog item, with no CSV for that table.

    Display is the case that broke: `_create_stub` filled `category` for tools and
    consumables and `manufacturer` for upgrades, by name, so a display stub was
    built without its NOT NULL `category`. Preview reported a clean CREATE and apply
    died at flush — a 500 after the operator was told the import was fine (rule 6,
    #129 review P2-1). The two working types are parametrised alongside it because a
    fix that reached only the new table is the same defect one release later.

    `http_client`, not `client`: the point is which status the apply earns.
    """
    order_id = "22222222-2222-4222-8222-222222222222"
    archive = make_archive(
        {
            "orders": [
                {
                    "id": order_id,
                    "retailer_id": retailer["id"],
                    "order_date": "2026-08-01",
                    "currency_code": "AUD",
                }
            ],
            "order_items": [
                {
                    "id": "33333333-3333-4333-8333-333333333333",
                    "order_id": order_id,
                    "item_type": item_type,
                    "catalog_name": "Undeclared Thing",
                    "quantity": "2",
                    "unit_price_minor": "900",
                    "currency_code": "AUD",
                }
            ],
        }
    )

    plan = await preview(http_client, archive)
    assert not plan["blocking_errors"], plan["blocking_errors"]
    assert actions(plan, table) == ["create"]

    resp = await apply(http_client, archive)
    assert resp.status_code == 200, resp.text

    rows = (await http_client.get(f"/{table.replace('_', '-')}")).json()
    assert len(rows) == 1
    # Stock is never inferred from an order (rule 10), and the placeholder columns
    # are asserted rather than just "a row exists" — a stub created with the wrong
    # placeholder is still a row.
    assert rows[0]["quantity_on_hand"] == 0
    for field, value in extra.items():
        assert rows[0][field] == value


@pytest.mark.parametrize(
    ("item_type", "table", "create"),
    [
        ("consumable", "consumables", {"name": "Shared Paint", "category": "paint"}),
        ("display", "display_items", {"name": "Shared Base", "category": "stand"}),
    ],
    ids=["consumable", "display"],
)
async def test_an_order_arriving_under_a_foreign_uuid_matches_by_catalog_name(
    client, retailer, item_type, table, create
):
    """The cross-instance case the whole natural-key machinery exists for: the same
    order exported from another instance, where every uuid differs.

    An order with no order number falls back to retailer + date + its line set, and
    a line is compared by the item's *name* — read from `catalog_names`, which was
    built from three tables. A display line's name was therefore never found, the
    line never matched, and the order was recreated: two orders for one purchase
    (#129 review, P2-2). Seeded through the API so the stored uuids are real, then
    re-imported under uuids that deliberately do not exist here.
    """
    item = (await client.post(f"/{table.replace('_', '-')}", json=create)).json()
    await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": item_type,
                    "quantity": 1,
                    "unit_price_minor": 900,
                    "currency_code": "AUD",
                    "catalog_ref_id": item["id"],
                }
            ],
        },
    )
    before = await snapshot(client)

    foreign_order = "99999999-9999-4999-8999-999999999999"
    archive = make_archive(
        {
            "retailers": [{"id": retailer["id"], "name": retailer["name"]}],
            "orders": [
                {
                    "id": foreign_order,
                    "retailer_id": retailer["id"],
                    "order_date": "2026-08-01",
                    "currency_code": "AUD",
                }
            ],
            "order_items": [
                {
                    "id": "88888888-8888-4888-8888-888888888888",
                    "order_id": foreign_order,
                    "item_type": item_type,
                    "catalog_name": create["name"],
                    "quantity": "1",
                    "unit_price_minor": "900",
                    "currency_code": "AUD",
                }
            ],
        }
    )

    plan = await preview(client, archive)
    assert actions(plan, "orders") == ["unchanged"], plan["tables"]

    resp = await apply(client, archive)
    assert resp.status_code == 200, resp.text
    assert len((await client.get("/orders")).json()) == 1, "the foreign uuid duplicated the order"
    assert await snapshot(client) == before
