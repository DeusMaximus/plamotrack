"""The kit series column (#96): free text with a select-or-create escort.

The decision under test: `series` is user-extensible free text like grade and
scale — nothing has to be registered before an agent can write it — and the
guard against fragmentation is not a vocabulary but a distinct-values surface
(most frequent first) that the kit form's typeahead and MCP both read before
inventing a new spelling. Rule 1 applies: the filter and the values list exist
on the service, REST and MCP alike.
"""

from fastmcp import Client

from app.mcp import mcp
from app.services.portability import spec
from tests.test_portability import apply, make_csv


async def make_kit(client, name: str, series: str | None = None, **extra) -> dict:
    payload = {"name": name, "grade": "HG", **extra}
    if series is not None:
        payload["series"] = series
    resp = await client.post("/kits", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_series_settable_on_create_update_and_clearable(client):
    kit = await make_kit(client, "RX-79[G]", series="The 08th MS Team")
    assert kit["series"] == "The 08th MS Team"

    renamed = await client.patch(f"/kits/{kit['id']}", json={"series": "08th MS Team"})
    assert renamed.json()["series"] == "08th MS Team"

    cleared = await client.patch(f"/kits/{kit['id']}", json={"series": None})
    assert cleared.json()["series"] is None


async def test_series_filter_is_case_insensitive_equality(client):
    await make_kit(client, "Barbatos", series="Iron-Blooded Orphans")
    await make_kit(client, "Gusion", series="Iron-Blooded Orphans")
    await make_kit(client, "RX-78-2", series="Mobile Suit Gundam")
    await make_kit(client, "No series at all")

    rows = (await client.get("/kits", params={"series": "iron-blooded orphans"})).json()
    assert {row["name"] for row in rows} == {"Barbatos", "Gusion"}
    # Equality, not a pattern: an underscore is a literal, not a wildcard (#49).
    assert (await client.get("/kits", params={"series": "Iron_Blooded Orphans"})).json() == []


async def test_distinct_values_come_most_frequent_first(client):
    for name in ("Barbatos", "Gusion", "Flauros"):
        await make_kit(client, name, series="Iron-Blooded Orphans")
    await make_kit(client, "RX-78-2", series="Mobile Suit Gundam")
    await make_kit(client, "Zaku II", series="Mobile Suit Gundam")
    await make_kit(client, "Wing Zero", series="Gundam Wing")
    await make_kit(client, "Unnamed", series=None)

    values = (await client.get("/kits/series")).json()
    assert values == ["Iron-Blooded Orphans", "Mobile Suit Gundam", "Gundam Wing"]


async def test_distinct_values_route_wins_over_the_uuid_param(client):
    # /kits/series is a literal segment on the same prefix as /kits/{kit_id};
    # if the uuid route matched first this would be a 422, not an empty list.
    resp = await client.get("/kits/series")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_mcp_series_round_trip_and_values(client):
    kit = await make_kit(client, "Aerial", series="The Witch from Mercury")
    async with Client(mcp) as mcp_client:
        values = (await mcp_client.call_tool("list_kit_series", {})).data
        assert values == ["The Witch from Mercury"]

        filtered = (
            await mcp_client.call_tool("list_kits", {"series": "the witch from mercury"})
        ).data
        assert [row["id"] for row in filtered] == [kit["id"]]

        edited = (
            await mcp_client.call_tool(
                "update_kit", {"kit_id": kit["id"], "changes": {"series": "G-Witch"}}
            )
        ).data
        assert edited["series"] == "G-Witch"


async def test_csv_round_trip_preserves_series(client):
    kit = await make_kit(client, "RX-78-2", series="Mobile Suit Gundam")
    exported = await client.get("/export/kits.csv")
    assert "series" in exported.text.splitlines()[0]
    assert (await apply(client, exported.content, filename="kits.csv")).status_code == 200
    fresh = (await client.get(f"/kits/{kit['id']}")).json()
    assert fresh["series"] == "Mobile Suit Gundam"


async def test_starter_sheet_standalone_row_carries_series(client):
    from app.services.portability.starter_sheet import STARTER_SHEET_COLUMNS

    header = [c.name for c in STARTER_SHEET_COLUMNS]
    row = {"kit_name": "RX-78-2", "grade": "MG", "series": "Mobile Suit Gundam", "quantity": "1"}
    content = make_csv(header, [row])
    assert (await apply(client, content, filename="starter-sheet.csv")).status_code == 200
    (kit,) = (await client.get("/kits")).json()
    assert kit["series"] == "Mobile Suit Gundam"


async def test_blank_and_whitespace_series_are_stored_as_null(client):
    # P3-1 (Cursor round 1 on PR #113): the importer's parse_text collapses a
    # blank cell to null. The live writers have to agree, or the distinct-values
    # surface offers an empty option — the opposite of what it exists for.
    empty = await make_kit(client, "Empty", series="")
    assert empty["series"] is None
    spaces = await make_kit(client, "Spaces", series="   ")
    assert spaces["series"] is None
    padded = await make_kit(client, "Padded", series="  Gundam Wing  ")
    assert padded["series"] == "Gundam Wing"

    patched = await client.patch(f"/kits/{padded['id']}", json={"series": "   "})
    assert patched.status_code == 200
    assert patched.json()["series"] is None
    assert (await client.get("/kits/series")).json() == []


async def test_distinct_values_hide_a_legacy_blank_row(client):
    # A blank written before the normalization existed (or by a future writer
    # that forgets it) must not surface as an empty typeahead option.
    from app.db import get_sessionmaker
    from app.models import Kit

    async with get_sessionmaker()() as session:
        session.add(Kit(name="Legacy", grade="HG", series="   "))
        await session.commit()
    await make_kit(client, "Real", series="Gundam Wing")
    assert (await client.get("/kits/series")).json() == ["Gundam Wing"]


def test_kits_spec_declares_series():
    assert "series" in [c.name for c in spec.KITS.columns]
