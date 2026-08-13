"""Import/export: round-trip fidelity, idempotency, and not duplicating things.

The duplication tests are the point of the feature — an import that quietly
doubles someone's order history is worse than no import at all.
"""

import csv
import io
import json
import zipfile

import pytest

from app.services.portability import exporting, spec, starter_sheet

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


def test_every_int4_column_is_covered_by_a_range_check(client):
    """#43's sweep, as a standing guard rather than a one-time audit.

    Two routes reach an int4 column and they are checked in different places:
    `parse_int` for the column itself, and `_apply_money_alternates` for the three
    major-unit mirrors that scale into one. A new integer column that arrives by
    neither route fails here rather than at a user's flush.
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
