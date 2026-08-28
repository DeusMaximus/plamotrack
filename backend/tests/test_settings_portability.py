"""The instance-settings singleton in the portability layer (§6.1, #23).

One row, and an import has exactly one verb for it: update. These tests drive
the mode axis (merge / add_only / replace_all) against the presence axis (sheet
present / absent / duplicated / invalid), because the singleton's contract is
defined by the cells of that matrix — a replace_all that deleted the row, or a
partial upload that quietly reset it, is the defect class under test.
"""

import pytest

from app.services.portability import spec, starter_sheet
from tests.diag import details, row_error, row_messages
from tests.test_portability import (
    actions,
    apply,
    make_archive,
    make_csv,
    preview,
    read_archive,
    read_manifest,
    sheet_row,
)

pytestmark = pytest.mark.anyio

SETTINGS_HEADER = spec.SPEC_BY_KEY["instance_settings"].header

#: The migration's seed, restated as literals (see test_settings.py).
BOOTSTRAP = {
    "interface_language": "en-AU",
    "formatting_locale": "en-AU",
    "time_zone": "UTC",
    "date_style": "locale",
    "hour_cycle": "locale",
    "reference_currency": "AUD",
}


def settings_csv(*rows: dict, header: list[str] | None = None) -> bytes:
    return make_csv(header or SETTINGS_HEADER, [BOOTSTRAP | row for row in rows])


def table_rows(plan: dict, table: str) -> list[dict]:
    for entry in plan["tables"]:
        if entry["table"] == table:
            return entry["rows"]
    return []


async def read_settings(client) -> dict:
    settings = (await client.get("/settings")).json()
    settings.pop("updated_at")
    return settings


# --- export ---------------------------------------------------------------------


async def test_the_archive_exports_the_settings_row(client):
    await client.patch("/settings", json={"time_zone": "Australia/Sydney"})
    content = (await client.get("/export/archive")).content
    rows = read_archive(content)["instance_settings"]
    assert rows == [BOOTSTRAP | {"time_zone": "Australia/Sydney"}]
    assert read_manifest(content)["tables"]["instance_settings"]["rows"] == 1


async def test_the_single_table_export_serves_the_settings(client):
    resp = await client.get("/export/instance_settings.csv")
    assert resp.status_code == 200
    header, row = resp.text.strip().splitlines()
    assert header.split(",") == SETTINGS_HEADER
    assert "en-AU" in row


# --- the round trip and the merge path -------------------------------------------


async def test_reimporting_an_export_is_a_no_op(client):
    content = (await client.get("/export/archive")).content
    plan = await preview(client, content)
    assert actions(plan, "instance_settings") == ["unchanged"]
    assert (await apply(client, content)).status_code == 200
    assert await read_settings(client) == BOOTSTRAP


async def test_a_changed_sheet_previews_the_exact_field_and_applies_it(client):
    sheet = settings_csv({"time_zone": "Australia/Sydney"})
    plan = await preview(client, sheet, filename="instance_settings.csv")
    (row,) = table_rows(plan, "instance_settings")
    assert row["action"] == "update"
    assert row["matched_by"] == "instance_settings"
    assert row["changes"] == [{"field": "time_zone", "before": "UTC", "after": "Australia/Sydney"}]
    assert (await apply(client, sheet, filename="instance_settings.csv")).status_code == 200
    assert await read_settings(client) == BOOTSTRAP | {"time_zone": "Australia/Sydney"}


async def test_cells_canonicalise_exactly_like_a_patch(client):
    # The cell parsers are the service's own validators (rule 1: shared
    # predicates) — lower-case spellings land in canonical form, not verbatim.
    sheet = settings_csv(
        {
            "time_zone": "australia/sydney",
            "formatting_locale": "EN-au",
            "reference_currency": "jpy",
        }
    )
    assert (await apply(client, sheet, filename="instance_settings.csv")).status_code == 200
    assert await read_settings(client) == BOOTSTRAP | {
        "time_zone": "Australia/Sydney",
        "formatting_locale": "en-AU",
        "reference_currency": "JPY",
    }


async def test_a_partial_header_touches_only_its_own_column(client):
    sheet = settings_csv({"time_zone": "Australia/Sydney"}, header=["time_zone"])
    plan = await preview(client, sheet, filename="instance_settings.csv")
    (row,) = table_rows(plan, "instance_settings")
    assert [change["field"] for change in row["changes"]] == ["time_zone"]
    assert row_messages(row) == []
    assert (await apply(client, sheet, filename="instance_settings.csv")).status_code == 200
    assert await read_settings(client) == BOOTSTRAP | {"time_zone": "Australia/Sydney"}


async def test_a_blank_cell_keeps_the_stored_value_and_says_so(client):
    # Nothing on this row is nullable, so "blank means empty this field" lands on
    # the same keep-stored answer every other required column gets (#88).
    await client.patch("/settings", json={"time_zone": "Australia/Sydney"})
    sheet = settings_csv({"reference_currency": "JPY", "time_zone": ""})
    plan = await preview(client, sheet, filename="instance_settings.csv")
    (row,) = table_rows(plan, "instance_settings")
    assert any("time_zone: left as it was" in message for message in row_messages(row))
    assert (await apply(client, sheet, filename="instance_settings.csv")).status_code == 200
    assert await read_settings(client) == BOOTSTRAP | {
        "time_zone": "Australia/Sydney",
        "reference_currency": "JPY",
    }


async def test_an_unknown_currency_warns_and_still_imports(client):
    sheet = settings_csv({"reference_currency": "ZZZ"})
    plan = await preview(client, sheet, filename="instance_settings.csv")
    (row,) = table_rows(plan, "instance_settings")
    assert any("isn't a currency code we recognise" in message for message in row_messages(row))
    assert (await apply(client, sheet, filename="instance_settings.csv")).status_code == 200
    assert (await read_settings(client))["reference_currency"] == "ZZZ"


# --- add_only and replace_all ----------------------------------------------------


async def test_add_only_skips_the_settings_row(client):
    sheet = settings_csv({"time_zone": "Australia/Sydney"})
    plan = await preview(client, sheet, filename="instance_settings.csv", mode="add_only")
    assert actions(plan, "instance_settings") == ["skip"]
    assert (
        await apply(client, sheet, filename="instance_settings.csv", mode="add_only")
    ).status_code == 200
    assert await read_settings(client) == BOOTSTRAP


async def test_replace_all_updates_the_settings_and_never_deletes_them(client):
    assert (await client.post("/retailers", json={"name": "Hobby Link Japan"})).status_code == 201
    archive = make_archive(
        {
            "instance_settings": [BOOTSTRAP | {"time_zone": "Australia/Sydney"}],
            "retailers": [{"name": "USA Gundam Store"}],
        }
    )
    plan = await preview(client, archive, mode="replace_all")
    assert actions(plan, "instance_settings") == ["update"]
    deleted = plan["derived"]["rows_deleted"]
    assert deleted.get("retailers") == 1
    assert "instance_settings" not in deleted

    resp = await apply(client, archive, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text
    assert await read_settings(client) == BOOTSTRAP | {"time_zone": "Australia/Sydney"}
    names = [retailer["name"] for retailer in (await client.get("/retailers")).json()]
    assert names == ["USA Gundam Store"]


async def test_replace_all_without_the_sheet_leaves_settings_alone(client):
    await client.patch("/settings", json={"time_zone": "Australia/Sydney"})
    archive = make_archive({"retailers": [{"name": "USA Gundam Store"}]})
    resp = await apply(client, archive, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text
    assert await read_settings(client) == BOOTSTRAP | {"time_zone": "Australia/Sydney"}


# --- refusals -------------------------------------------------------------------


async def test_a_second_row_is_refused(client):
    sheet = settings_csv({}, {"time_zone": "Australia/Sydney"})
    plan = await preview(client, sheet, filename="instance_settings.csv")
    first, second = table_rows(plan, "instance_settings")
    assert first["action"] != "error"
    assert second["action"] == "error"
    assert "two rows in one upload cannot describe the same record" in row_error(second)
    assert details(plan["blocking_errors"])
    assert (await apply(client, sheet, filename="instance_settings.csv")).status_code == 409
    assert await read_settings(client) == BOOTSTRAP


@pytest.mark.parametrize(
    ("cell", "fragment"),
    [
        ({"interface_language": "fr-FR"}, "not an interface language this build ships"),
        ({"interface_language": "not a tag!"}, "not a locale tag"),
        ({"formatting_locale": "en-AU-u-hc-h23"}, "not a locale tag"),
        ({"time_zone": "Mars/Olympus_Mons"}, "not an IANA time zone"),
        ({"date_style": "sideways"}, "not valid here"),
        ({"hour_cycle": "h25"}, "not valid here"),
        ({"reference_currency": "AU$"}, "not a 3-letter ISO 4217 currency code"),
        # Unicode letters are not ISO 4217 letters (PR #159 review, P2): PATCH
        # refused this while the sheet imported it and new snapshots carried it.
        ({"reference_currency": "ÅUD"}, "not a 3-letter ISO 4217 currency code"),
        ({"formatting_locale": "en-abcde-abcde"}, "repeats a variant subtag"),
    ],
)
async def test_invalid_cells_are_row_errors_that_block(client, cell, fragment):
    sheet = settings_csv(cell)
    plan = await preview(client, sheet, filename="instance_settings.csv")
    (row,) = table_rows(plan, "instance_settings")
    assert row["action"] == "error"
    assert fragment in row_error(row)
    assert details(plan["blocking_errors"])
    assert (await apply(client, sheet, filename="instance_settings.csv")).status_code == 409
    assert await read_settings(client) == BOOTSTRAP


# --- neighbours that must not reach it -------------------------------------------


async def test_a_starter_sheet_priced_without_a_currency_uses_the_setting(client):
    # The starter expansion's blank-currency fill reads the settings row (#23),
    # not the bootstrap env value.
    await client.patch("/settings", json={"reference_currency": "JPY"})
    row = sheet_row("1", retailer="Yodobashi") | {"currency": ""}
    sheet = make_csv(starter_sheet.STARTER_SHEET_HEADER, [row])
    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200
    (order,) = (await client.get("/orders")).json()
    assert order["currency_code"] == "JPY"


async def test_the_starter_sheet_never_touches_settings(client):
    sheet = make_csv(starter_sheet.STARTER_SHEET_HEADER, [sheet_row("1")])
    plan = await preview(client, sheet, filename="starter-sheet.csv")
    assert table_rows(plan, "instance_settings") == []
    assert (await apply(client, sheet, filename="starter-sheet.csv")).status_code == 200
    assert await read_settings(client) == BOOTSTRAP


async def test_a_settings_change_between_preview_and_apply_stales_the_hash(client):
    # The plan's money fill reads the settings row (#23), so the fill is part of
    # what the operator approved — a currency changed under an approved preview
    # must 409 into a fresh preview, not silently stamp the new default.
    sheet = make_csv(
        ["name", "category", "unit_cost_reference"],
        [{"name": "God Hand SPN-120", "category": "cutting", "unit_cost_reference": "45.00"}],
    )
    plan = await preview(client, sheet, filename="tools.csv")
    await client.patch("/settings", json={"reference_currency": "JPY"})
    resp = await apply(client, sheet, filename="tools.csv", plan_hash=plan["plan_hash"])
    assert resp.status_code == 409
    assert "run the preview again" in resp.json()["detail"]
