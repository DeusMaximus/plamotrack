"""Build start/completion dates (#94), on every status writer.

The defect: `kits` carried a single `status_updated_at`, so finishing a build
destroyed the record of starting it. These pin the replacement contract: entering
`building`/`complete` stamps the matching date **only when it is null**, the user
owns both values (explicitly settable on every surface, never overwritten by a
later transition), and the importer never invents either one — an imported
`complete` kit with no date stays null, exactly as rule 10 keeps stock honest.

The state axis is the point here (per AGENTS.md): the same field is right or
wrong depending on which transition wrote it, so the suite drives transitions,
re-entries, explicit values riding the same PATCH, and the import cell states
(column absent / blank / populated) rather than one straight-line pass.
"""

from datetime import UTC, datetime, timedelta

from app.services.portability import spec
from tests.test_portability import apply, make_csv

BACKFILL = "2026-02-08T10:00:00+10:00"


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def close_to_now(value: str) -> bool:
    return abs(datetime.now(UTC) - instant(value)) < timedelta(seconds=60)


async def make_kit(client, **extra) -> dict:
    resp = await client.post("/kits", json={"name": "RX-79[G] Ground Type", "grade": "HG", **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def move(client, kit_id: str, status: str) -> dict:
    resp = await client.patch(f"/kits/{kit_id}", json={"status": status})
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- transitions ------------------------------------------------------------------


async def test_full_pipeline_retains_both_dates(client):
    kit = await make_kit(client)
    building = await move(client, kit["id"], "building")
    assert building["build_started_at"] is not None
    # One clock: the stamp is the same instant the transition wrote, not a second read.
    assert instant(building["build_started_at"]) == instant(building["status_updated_at"])
    assert building["build_completed_at"] is None

    complete = await move(client, kit["id"], "complete")
    # The defect this issue exists for: completing must not destroy the start.
    assert complete["build_started_at"] == building["build_started_at"]
    assert complete["build_completed_at"] is not None
    assert instant(complete["build_completed_at"]) == instant(complete["status_updated_at"])


async def test_reentering_building_keeps_the_original_start(client):
    kit = await make_kit(client)
    first = await move(client, kit["id"], "building")
    await move(client, kit["id"], "backlog")  # shelved
    second = await move(client, kit["id"], "building")
    assert second["build_started_at"] == first["build_started_at"]


async def test_backlog_straight_to_complete_stamps_only_completion(client):
    kit = await make_kit(client)
    complete = await move(client, kit["id"], "complete")
    assert complete["build_started_at"] is None
    assert complete["build_completed_at"] is not None


async def test_creation_never_derives_a_build_date(client):
    # A kit *created* already building/complete is a backfill in progress — the
    # honest default is null, not the entry clock (the importer's rule, applied
    # to REST so the two writers cannot disagree).
    building = await make_kit(client, status="building")
    complete = await make_kit(client, name="MG Zaku II 2.0", status="complete")
    assert building["build_started_at"] is None
    assert complete["build_completed_at"] is None


# --- the user owns the values -----------------------------------------------------


async def test_an_explicit_date_in_the_transitioning_patch_wins(client):
    kit = await make_kit(client)
    resp = await client.patch(
        f"/kits/{kit['id']}", json={"status": "complete", "build_completed_at": BACKFILL}
    )
    assert resp.status_code == 200
    assert instant(resp.json()["build_completed_at"]) == instant(BACKFILL)


async def test_an_explicit_null_in_the_transitioning_patch_is_not_fought(client):
    kit = await make_kit(client)
    resp = await client.patch(
        f"/kits/{kit['id']}", json={"status": "building", "build_started_at": None}
    )
    assert resp.status_code == 200
    assert resp.json()["build_started_at"] is None


async def test_a_user_set_date_survives_the_later_transition(client):
    kit = await make_kit(client)
    resp = await client.patch(f"/kits/{kit['id']}", json={"build_started_at": BACKFILL})
    assert resp.status_code == 200
    building = await move(client, kit["id"], "building")
    assert instant(building["build_started_at"]) == instant(BACKFILL)


async def test_completion_without_a_start_is_a_legal_backfill(client):
    kit = await make_kit(client, status="complete")
    resp = await client.patch(f"/kits/{kit['id']}", json={"build_completed_at": BACKFILL})
    assert resp.status_code == 200
    body = resp.json()
    assert instant(body["build_completed_at"]) == instant(BACKFILL)
    assert body["build_started_at"] is None


async def test_both_dates_are_clearable(client):
    kit = await make_kit(client)
    await move(client, kit["id"], "building")
    complete = await move(client, kit["id"], "complete")
    assert complete["build_started_at"] and complete["build_completed_at"]
    resp = await client.patch(
        f"/kits/{kit['id']}", json={"build_started_at": None, "build_completed_at": None}
    )
    assert resp.status_code == 200
    assert resp.json()["build_started_at"] is None
    assert resp.json()["build_completed_at"] is None


async def test_a_naive_build_date_is_refused_by_the_schema(http_client):
    kit = await make_kit(http_client)
    resp = await http_client.patch(
        f"/kits/{kit['id']}", json={"build_started_at": "2026-02-08T10:00:00"}
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)  # pydantic AwareDatetime spoke


async def test_reentering_complete_keeps_the_original_completion(client):
    # The mirror of the re-entry rule on the other field (Cursor round 1 on
    # PR #113): complete -> building (reopened for repairs) -> complete keeps
    # the first completion; the stored value is editable when latest is wanted.
    kit = await make_kit(client)
    first = await move(client, kit["id"], "complete")
    await move(client, kit["id"], "building")
    second = await move(client, kit["id"], "complete")
    assert second["build_completed_at"] == first["build_completed_at"]


async def test_mcp_naive_build_date_is_a_tool_error(client):
    # REST pins the schema-layer refusal above; this pins the same rule through
    # the MCP tool, where _KitPatch inherits AwareDatetime from KitUpdate.
    import pytest as _pytest
    from fastmcp import Client
    from fastmcp.exceptions import ToolError

    from app.mcp import mcp

    kit = await make_kit(client)
    async with Client(mcp) as mcp_client:
        with _pytest.raises(ToolError, match="timezone"):
            await mcp_client.call_tool(
                "update_kit",
                {"kit_id": kit["id"], "changes": {"build_started_at": "2026-02-08T10:00:00"}},
            )
    fresh = (await client.get(f"/kits/{kit['id']}")).json()
    assert fresh["build_started_at"] is None  # refused, not coerced to UTC


# --- receive_order: the other live status writer ----------------------------------


async def test_receiving_an_order_advances_kits_without_inventing_build_dates(client):
    retailer = (await client.post("/retailers", json={"name": "Gundam Base"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-08-01",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 1,
                        "unit_price_minor": 4999,
                        "currency_code": "AUD",
                        "kit": {"name": "HG Barbatos", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    received = (await client.post(f"/orders/{order['id']}/receive")).json()
    kit_id = received["items"][0]["spawned_kit_ids"][0]
    kit = (await client.get(f"/kits/{kit_id}")).json()
    assert kit["status"] == "backlog"
    assert kit["build_started_at"] is None
    assert kit["build_completed_at"] is None


# --- MCP: the third writer surface (rule 1) ----------------------------------------


async def test_mcp_can_backfill_and_transitions_stamp(client):
    from fastmcp import Client

    from app.mcp import mcp

    kit = await make_kit(client)
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_kit",
                {"kit_id": kit["id"], "changes": {"build_completed_at": BACKFILL}},
            )
        ).data
        assert instant(edited["build_completed_at"]) == instant(BACKFILL)
        moved = (
            await mcp_client.call_tool(
                "update_kit_status", {"kit_id": kit["id"], "status": "building"}
            )
        ).data
    assert moved["build_started_at"] is not None
    assert close_to_now(moved["build_started_at"])
    # The backfilled completion was set by the user; the drag must not touch it.
    assert instant(moved["build_completed_at"]) == instant(BACKFILL)


# --- the importer never invents ----------------------------------------------------


def kit_row(kit: dict, **overrides) -> dict:
    row = {
        "id": kit["id"],
        "name": kit["name"],
        "grade": kit["grade"],
        "status": kit["status"],
    }
    row.update(overrides)
    return row


async def test_import_of_a_complete_kit_with_no_date_columns_stays_null(client):
    # Column ABSENT: the sheet says nothing, so nothing is written — a complete
    # kit does not acquire the import's own clock.
    header = ["id", "name", "grade", "status"]
    row = {"id": "", "name": "PG Unleashed", "grade": "PG", "status": "complete"}
    content = make_csv(header, [row])
    resp = await apply(client, content, filename="kits.csv")
    assert resp.status_code == 200, resp.text
    (kit,) = (await client.get("/kits")).json()
    assert kit["status"] == "complete"
    assert kit["build_started_at"] is None
    assert kit["build_completed_at"] is None


async def test_import_cell_states_absent_blank_populated(client):
    # Over an EXISTING kit with a stored date, the three cell states mean three
    # different things: absent = keep, blank = clear, populated = overwrite.
    kit = await make_kit(client, status="complete", build_completed_at=BACKFILL)
    assert kit["build_completed_at"] is not None

    absent = make_csv(["id", "name", "grade", "status"], [kit_row(kit)])
    assert (await apply(client, absent, filename="kits.csv")).status_code == 200
    fresh = (await client.get(f"/kits/{kit['id']}")).json()
    assert instant(fresh["build_completed_at"]) == instant(BACKFILL)

    populated = make_csv(
        ["id", "name", "grade", "status", "build_completed_at"],
        [kit_row(kit, build_completed_at="2026-03-01T00:00:00+00:00")],
    )
    assert (await apply(client, populated, filename="kits.csv")).status_code == 200
    fresh = (await client.get(f"/kits/{kit['id']}")).json()
    assert instant(fresh["build_completed_at"]) == instant("2026-03-01T00:00:00+00:00")

    blank = make_csv(
        ["id", "name", "grade", "status", "build_completed_at"],
        [kit_row(kit, build_completed_at="")],
    )
    assert (await apply(client, blank, filename="kits.csv")).status_code == 200
    fresh = (await client.get(f"/kits/{kit['id']}")).json()
    assert fresh["build_completed_at"] is None


async def test_export_import_round_trip_preserves_both_dates(client):
    kit = await make_kit(
        client,
        status="complete",
        build_started_at="2026-01-10T00:00:00+10:00",
        build_completed_at=BACKFILL,
    )
    exported = await client.get("/export/kits.csv")
    assert exported.status_code == 200
    assert "build_started_at" in exported.text.splitlines()[0]
    resp = await apply(client, exported.content, filename="kits.csv")
    assert resp.status_code == 200
    fresh = (await client.get(f"/kits/{kit['id']}")).json()
    assert instant(fresh["build_started_at"]) == instant("2026-01-10T00:00:00+10:00")
    assert instant(fresh["build_completed_at"]) == instant(BACKFILL)


async def test_starter_sheet_standalone_row_carries_build_dates(client):
    from app.services.portability.starter_sheet import STARTER_SHEET_COLUMNS

    header = [c.name for c in STARTER_SHEET_COLUMNS]
    content = make_csv(
        header,
        [
            {
                "kit_name": "RX-78-2 Ver.3.0",
                "grade": "MG",
                "status": "complete",
                "build_started": "2026-01-10",
                "build_completed": "2026-02-08",
                "quantity": "1",
            }
        ],
    )
    resp = await apply(client, content, filename="starter-sheet.csv")
    assert resp.status_code == 200, resp.text
    (kit,) = (await client.get("/kits")).json()
    assert kit["build_started_at"] is not None and kit["build_started_at"].startswith("2026-01-10")
    assert kit["build_completed_at"] is not None
    assert kit["build_completed_at"].startswith("2026-02-08")


# guard: the spec really carries the columns (rule 9 — declared once, read everywhere)
def test_kits_spec_declares_the_build_columns():
    names = [c.name for c in spec.KITS.columns]
    assert "build_started_at" in names and "build_completed_at" in names
