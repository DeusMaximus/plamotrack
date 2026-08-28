"""Naive CSV datetimes read in the instance's time zone (#114).

A bare `2026-02-08` in a sheet used to be read as midnight UTC, landing the
stored instant on the previous calendar day for every viewer west of
Greenwich. Since #23 the instance owns a time zone, so the planner attaches it
to any datetime cell that states no offset — one change in `_parse_row`, every
member of the class at once (build dates, the starter sheet's received-on
default, any archive timestamp cell).

The boundary (rule 4's ethos — a settings change never reinterprets history):
* an explicit offset in the cell always wins, untouched;
* exports render every datetime with `+00:00`, so an archive written under the
  old rule re-imports as the same instants — the no-op is preserved;
* stored rows are never rewritten; only cells parsed after this change read
  differently, and only naive ones.

Axes per the checklist: the default zone (UTC — byte-for-byte the old
behaviour) beside a contrasting west-of-UTC zone; date-only beside timed naive
values beside an explicit offset; and the preview/apply seam, where a zone
change between the two stales the hash instead of silently changing what the
approved plan means.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from tests.test_portability import actions, apply, make_csv, preview, read_archive

NEW_YORK = ZoneInfo("America/New_York")


async def _set_zone(client, zone: str) -> None:
    resp = await client.patch("/settings", json={"time_zone": zone})
    assert resp.status_code == 200, resp.text


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _import_kit(client, cell: str) -> datetime:
    content = make_csv(
        ["name", "grade", "build_completed_at"],
        [{"name": "Zaku II", "grade": "HG", "build_completed_at": cell}],
    )
    assert (await apply(client, content, filename="kits.csv")).status_code == 200
    [kit] = (await client.get("/kits")).json()
    return _instant(kit["build_completed_at"])


async def test_a_naive_date_reads_as_midnight_in_the_instance_zone(client):
    """The issue's acceptance row: `build_completed: 2026-02-08` imported on a
    west-of-UTC instance is the 8th in that zone — not the 7th."""
    await _set_zone(client, "America/New_York")
    stored = await _import_kit(client, "2026-02-08")
    assert stored == datetime(2026, 2, 8, tzinfo=NEW_YORK)
    assert stored.astimezone(NEW_YORK).date() == date(2026, 2, 8)
    # And it genuinely differs from the old UTC-midnight reading.
    assert stored != datetime(2026, 2, 8, tzinfo=UTC)


async def test_a_timed_naive_cell_localises_too(client):
    await _set_zone(client, "America/New_York")
    stored = await _import_kit(client, "2026-02-08T14:30:00")
    assert stored == datetime(2026, 2, 8, 14, 30, tzinfo=NEW_YORK)


async def test_an_explicit_offset_is_never_reinterpreted(client):
    """The boundary: a cell that states its offset means that instant on any
    instance — the zone setting touches only naive cells."""
    await _set_zone(client, "America/New_York")
    stored = await _import_kit(client, "2026-02-08T00:00:00+00:00")
    assert stored == datetime(2026, 2, 8, tzinfo=UTC)


async def test_the_default_zone_keeps_the_old_reading(client):
    """The seeded default is UTC, so an instance that never touched its
    settings imports byte-for-byte as before #114 — the null/default axis."""
    stored = await _import_kit(client, "2026-02-08")
    assert stored == datetime(2026, 2, 8, tzinfo=UTC)


async def test_the_starter_sheets_received_default_reads_in_the_instance_zone(client):
    """The class member the issue names beside build dates: a received order's
    `received_at` defaults to the order_date string, which must land as
    midnight local — March, deliberately, so the DST offset (-04:00) differs
    from February's and a hardcoded-offset fix would show."""
    await _set_zone(client, "America/New_York")
    content = make_csv(
        ["kit_name", "grade", "retailer", "order_date", "received"],
        [
            {
                "kit_name": "Zaku II",
                "grade": "HG",
                "retailer": "Gundam Base",
                "order_date": "2026-03-14",
                "received": "yes",
            }
        ],
    )
    assert (await apply(client, content, filename="starter-sheet.csv")).status_code == 200
    [order] = (await client.get("/orders")).json()
    assert _instant(order["received_at"]) == datetime(2026, 3, 14, tzinfo=NEW_YORK)


async def test_an_archive_written_under_the_old_rule_reimports_unchanged(client):
    """Exports render datetimes with +00:00, so the archive of a collection —
    including instants that were read as UTC midnights before #114 — previews
    as a no-op on a re-import whatever the instance zone says (rule 10)."""
    stored = await _import_kit(client, "2026-02-08")  # UTC instance, old reading
    await _set_zone(client, "America/New_York")
    archive = (await client.get("/export/archive")).content
    # The archive states the offset, so the zone change reinterprets nothing.
    kits_rows = read_archive(archive)["kits"]
    assert kits_rows[0]["build_completed_at"] == stored.astimezone(UTC).isoformat()
    plan = await preview(client, archive)
    assert actions(plan, "kits") == ["unchanged"], plan["tables"]


async def test_a_zone_change_between_preview_and_apply_stales_the_hash(client):
    """The read-once seam: the naive cell's meaning is part of the plan, so a
    zone change after the preview must 409 rather than apply an instant the
    operator never saw."""
    content = make_csv(
        ["name", "grade", "build_completed_at"],
        [{"name": "Zaku II", "grade": "HG", "build_completed_at": "2026-02-08"}],
    )
    plan = await preview(client, content, filename="kits.csv")
    await _set_zone(client, "America/New_York")
    resp = await apply(client, content, filename="kits.csv", plan_hash=plan["plan_hash"])
    assert resp.status_code == 409
    assert resp.json()["code"] == "import.plan_stale"
    assert (await client.get("/kits")).json() == []
