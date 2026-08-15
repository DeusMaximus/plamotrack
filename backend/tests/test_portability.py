"""Import/export: round-trip fidelity, idempotency, and not duplicating things.

The duplication tests are the point of the feature — an import that quietly
doubles someone's order history is worse than no import at all.
"""

import csv
import io
import json
import time
import zipfile

import pytest

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
    return {"retailer": retailer, "order": order, "tool": tool}


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

    # Wipe by hand, then restore — the migration path onto a fresh instance.
    for order in (await client.get("/orders")).json():
        assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    for tool in (await client.get("/tools")).json():
        await client.delete(f"/tools/{tool['id']}")
    assert (await client.get("/kits")).json() == []

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
    for table in ("retailers", "orders", "order_items", "kits", "consumables", "tools"):
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

    retailer = (await client.post("/retailers", json={"name": f"Shop {code}"})).json()
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
