"""The catalog `category` vocabulary (#127): free text with a select-or-create escort.

The decision under test: `category` on tools, consumables and display items is
user-extensible free text — the guard against fragmentation is the #96 device (a
frequency-ordered distinct-values surface the form's typeahead and MCP read
before writing) plus one lean the series column does not have: a write whose
category matches an existing one case-insensitively is stored under that existing
spelling (`canonical_category`). Three live writers reach these tables (rule 1) —
the direct create, the PATCH, and an order line's `new_item` — and all three
fold. The CSV importer folds exactly one case: an id-less row classified CREATE,
which states no prior spelling to preserve (#130 review, P2-3). Everything that
*restores* — an UPDATE, an id-bearing create-is-a-restore — stays verbatim, so a
re-imported archive remains a no-op (rule 10 by analogy). `upgrades` has no
category column at all — decided against in #127, not an oversight.
"""

import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp
from app.services.portability import spec
from tests.diag import row_messages
from tests.test_portability import apply, make_csv


async def make_tool(client, name: str, category: str, **extra) -> dict:
    resp = await client.post("/tools", json={"name": name, "category": category, **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- the filter -----------------------------------------------------------------


async def test_category_filter_is_case_insensitive_equality(client):
    await make_tool(client, "Godhand SPN-120", "Cutting")
    await make_tool(client, "Tamiya sharp nipper", "cutting")
    await make_tool(client, "Glass file", "Filing")

    # The second create folded onto the first spelling, so one folded value
    # matches both rows — and the filter folds too, so any casing asks for them.
    rows = (await client.get("/tools", params={"category": "CUTTING"})).json()
    assert {row["name"] for row in rows} == {"Godhand SPN-120", "Tamiya sharp nipper"}
    # Equality, not a pattern: an underscore is a literal, not a wildcard (#49).
    assert (await client.get("/tools", params={"category": "Cutt_ng"})).json() == []


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        pytest.param("/consumables", {"name": "Mr Cement S", "category": "Glue"}, id="consumable"),
        pytest.param(
            "/display-items", {"name": "Action Base 2", "category": "Stand"}, id="display"
        ),
    ],
)
async def test_category_filter_exists_on_every_categorised_table(client, path, payload):
    # Tools are driven above; these pin the other two tables, because the routes
    # are declared one by one and a filter added to one list route proves nothing
    # about its neighbours (the sweep rule).
    created = (await client.post(path, json=payload)).json()
    rows = (await client.get(path, params={"category": payload["category"].lower()})).json()
    assert [row["id"] for row in rows] == [created["id"]]
    assert (await client.get(path, params={"category": "elsewhere"})).json() == []


# --- the distinct-values surface -------------------------------------------------


async def test_distinct_categories_come_most_frequent_first(client):
    for name in ("Godhand SPN-120", "Tamiya sharp", "DSPIAE nipper"):
        await make_tool(client, name, "Cutting")
    await make_tool(client, "Glass file", "Filing")
    await make_tool(client, "Metal file", "Filing")
    await make_tool(client, "PS-270", "Airbrush")

    values = (await client.get("/tools/categories")).json()
    # 3 > 2 > 1 by frequency; the 1s would tie, but there is only one — the
    # alphabetical tie-break is pinned by test_distinct_categories_tie_break.
    assert values == ["Cutting", "Filing", "Airbrush"]


async def test_distinct_categories_tie_break_is_alphabetical_case_insensitive(client):
    await make_tool(client, "PS-270", "airbrush")
    await make_tool(client, "Glass file", "Filing")

    assert (await client.get("/tools/categories")).json() == ["airbrush", "Filing"]


async def test_categories_are_per_table_vocabularies(client):
    await make_tool(client, "Godhand SPN-120", "Cutting")
    resp = await client.post("/consumables", json={"name": "Mr Cement S", "category": "Glue"})
    assert resp.status_code == 201

    assert (await client.get("/tools/categories")).json() == ["Cutting"]
    assert (await client.get("/consumables/categories")).json() == ["Glue"]
    assert (await client.get("/display-items/categories")).json() == []


async def test_an_empty_catalog_lists_no_categories(client):
    for path in ("/tools/categories", "/consumables/categories", "/display-items/categories"):
        resp = await client.get(path)
        assert resp.status_code == 200, resp.text
        assert resp.json() == []


async def test_distinct_categories_hide_a_legacy_blank_row(client):
    # A blank written before #129's refusal existed (or by a future writer that
    # forgets it) must not surface as an empty typeahead option — the series
    # rule (#113 review, P3-1), applied to this column.
    from app.db import get_sessionmaker
    from app.models import Tool

    async with get_sessionmaker()() as session:
        session.add(Tool(name="Legacy", category="   ", quantity_on_hand=0))
        await session.commit()
    await make_tool(client, "Godhand SPN-120", "Cutting")
    assert (await client.get("/tools/categories")).json() == ["Cutting"]


async def test_upgrades_have_no_categories_route(client):
    # Decided against in #127, so the absence is the contract: no GET route
    # answers this path. (405, not 404: the path shape exists for PATCH/DELETE
    # /upgrades/{upgrade_id}, and routing matches the shape before the uuid
    # type does — either status is the refusal; a 200 vocabulary is the bug.)
    assert (await client.get("/upgrades/categories")).status_code in (404, 405)


# --- canonicalisation on write ---------------------------------------------------


async def test_create_folds_category_onto_the_existing_spelling(client):
    await make_tool(client, "Godhand SPN-120", "Cutting")
    row = await make_tool(client, "Tamiya sharp", "cutting")
    assert row["category"] == "Cutting"
    # Padded input is trimmed before it is folded, so it reaches the same key.
    padded = await make_tool(client, "DSPIAE nipper", "  CUTTING  ")
    assert padded["category"] == "Cutting"


async def test_a_genuinely_new_category_stands_as_given(client):
    await make_tool(client, "Godhand SPN-120", "Cutting")
    row = await make_tool(client, "Glass file", "Filing")
    assert row["category"] == "Filing"
    # A near-miss is a different key — folding is equality, never similarity.
    near = await make_tool(client, "Tamiya sharp", "Cutters")
    assert near["category"] == "Cutters"


async def test_update_folds_category_onto_another_rows_spelling(client):
    await make_tool(client, "Godhand SPN-120", "Cutting")
    other = await make_tool(client, "Glass file", "Filing")

    resp = await client.patch(f"/tools/{other['id']}", json={"category": "CUTTING"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["category"] == "Cutting"


async def test_recasing_the_only_holder_wins_over_its_own_spelling(client):
    # The exclude-own-row half (`require_unique_name`'s #107 shape): with no
    # other row holding the key, the PATCH is the user correcting the vocabulary
    # entry itself, and must not be silently reverted by the row it corrects.
    row = await make_tool(client, "Godhand SPN-120", "cutting")
    resp = await client.patch(f"/tools/{row['id']}", json={"category": "Cutting"})
    assert resp.json()["category"] == "Cutting"

    # With a second holder, the vocabulary wins again: the same PATCH shape now
    # folds back onto the spelling the other rows keep alive.
    await make_tool(client, "Tamiya sharp", "Cutting")
    reverted = await client.patch(f"/tools/{row['id']}", json={"category": "CUTTING"})
    assert reverted.json()["category"] == "Cutting"


async def test_the_most_frequent_legacy_spelling_wins(client):
    # Divergent spellings can only predate this change (or arrive by import), so
    # seed them beneath the service layer the way legacy rows actually exist.
    from app.db import get_sessionmaker
    from app.models import Tool

    async with get_sessionmaker()() as session:
        session.add_all(
            [
                Tool(name="A", category="cutting", quantity_on_hand=0),
                Tool(name="B", category="cutting", quantity_on_hand=0),
                Tool(name="C", category="Cutting", quantity_on_hand=0),
            ]
        )
        await session.commit()

    row = await make_tool(client, "D", "CUTTING")
    assert row["category"] == "cutting"


async def test_a_frequency_tie_breaks_by_byte_order(client):
    from app.db import get_sessionmaker
    from app.models import Tool

    async with get_sessionmaker()() as session:
        session.add_all(
            [
                Tool(name="A", category="cutting", quantity_on_hand=0),
                Tool(name="B", category="Cutting", quantity_on_hand=0),
            ]
        )
        await session.commit()

    # One row each — COLLATE "C" pins the winner ("C" < "c") on every platform,
    # so the dev Mac and CI cannot canonicalise onto different spellings.
    row = await make_tool(client, "D", "CUTTING")
    assert row["category"] == "Cutting"


async def test_an_order_new_item_line_folds_its_category(client, retailer):
    await make_tool(client, "Godhand SPN-120", "Cutting")
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "tool",
                    "quantity": 1,
                    "unit_price_minor": 4500,
                    "currency_code": "AUD",
                    "new_item": {"name": "DSPIAE nipper", "category": "cutting"},
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    (spawned,) = [t for t in (await client.get("/tools")).json() if t["name"] == "DSPIAE nipper"]
    assert spawned["category"] == "Cutting"


async def test_an_upgrade_new_item_line_carrying_a_category_is_still_accepted(
    http_client, client, retailer
):
    # `NewCatalogItem` is one schema for every line type, so an upgrade line may
    # state a category; upgrades have no column and the base behaviour was to
    # ignore it. Canonicalisation must not turn that valid shape into a 500
    # (#130 review, P2-1). `http_client`, because the point is the status.
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "upgrade",
                    "quantity": 1,
                    "unit_price_minor": 1500,
                    "currency_code": "AUD",
                    "new_item": {
                        "name": "Delpi holo decals",
                        "manufacturer": "Delpi",
                        "category": "decals",
                    },
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    (row,) = (await client.get("/upgrades")).json()
    assert row["name"] == "Delpi holo decals"


# --- legacy padding: matched, never propagated (#130 review, P2-2) ----------------


def _seed_padded_legacy_tool():
    # Tab and NBSP, not ASCII space — the padding must stay aligned with the
    # full WHITESPACE set, not just what a spacebar produces (#109's lesson).
    from app.db import get_sessionmaker
    from app.models import Tool

    async def _seed():
        async with get_sessionmaker()() as session:
            session.add(Tool(name="Legacy", category="\tCutting\u00a0", quantity_on_hand=0))
            await session.commit()

    return _seed()


async def test_a_legacy_padded_category_is_found_by_its_trimmed_spelling(client):
    # Padding from before trimming existed is a supported stored state. The
    # filter and the vocabulary answer for the *logical* category: the row is
    # found under its trimmed spelling, and the vocabulary offers the trimmed
    # spelling rather than the raw padded cell.
    await _seed_padded_legacy_tool()
    rows = (await client.get("/tools", params={"category": "cutting"})).json()
    assert [row["name"] for row in rows] == ["Legacy"]
    assert (await client.get("/tools/categories")).json() == ["Cutting"]


async def test_a_write_never_propagates_legacy_padding(client):
    # The fold reuses the *spelling*, not the stored bytes: a new row folding
    # onto a padded legacy row gets the trimmed spelling — at the base the live
    # write stored the clean input, and canonicalisation must not regress that.
    await _seed_padded_legacy_tool()
    row = await make_tool(client, "Fresh", "cutting")
    assert row["category"] == "Cutting"


async def test_mcp_update_folds_a_category_too(client):
    # The MCP wrapper is thin over the same service (rule 1) — one case to pin
    # that the fold is reachable from the third live writer's surface as well.
    await make_tool(client, "Godhand SPN-120", "Cutting")
    other = await make_tool(client, "Glass file", "Filing")
    async with Client(mcp) as mcp_client:
        edited = (
            await mcp_client.call_tool(
                "update_catalog_tool",
                {"tool_id": other["id"], "changes": {"category": "cutting"}},
            )
        ).data
    assert edited["category"] == "Cutting"


# --- the importer folds id-less CREATEs, and only those (#130 review, P2-3) -------


def _tools_csv(rows: list[dict[str, str]]) -> bytes:
    return make_csv([c.name for c in spec.TOOLS.columns], rows)


async def test_an_id_less_import_create_folds_its_category(client):
    # An id-less row classified CREATE states no prior spelling to preserve —
    # the row exists only after apply — so it folds like every live writer.
    await make_tool(client, "Godhand SPN-120", "Cutting")

    content = _tools_csv([{"name": "Glass file", "category": "cutting"}])
    assert (await apply(client, content, filename="tools.csv")).status_code == 200

    (imported,) = [t for t in (await client.get("/tools")).json() if t["name"] == "Glass file"]
    assert imported["category"] == "Cutting"


async def test_the_fold_is_stated_in_the_preview(client):
    # `changes` is empty on a create (the state axis AGENTS.md warns about), so
    # the fold announces itself as a row message — the preview says what apply
    # will write rather than diverging from it silently.
    from tests.test_portability import preview

    await make_tool(client, "Godhand SPN-120", "Cutting")
    plan = await preview(
        client, _tools_csv([{"name": "Glass file", "category": "cutting"}]), filename="tools.csv"
    )
    table = next(t for t in plan["tables"] if t["table"] == "tools")
    (row,) = [r for r in table["rows"] if r["label"] == "Glass file"]
    assert any("stored as 'Cutting'" in message for message in row_messages(row))


async def test_a_vocabulary_change_between_preview_and_apply_stales_the_hash(client):
    # The fold is computed at plan time and the fingerprint hashes the planned
    # values, so a spelling landing between preview and apply means the shown
    # plan no longer describes what apply would write — 409, re-preview (the
    # #86 round-5 shape, applied to this derivation).
    from tests.test_portability import preview

    content = _tools_csv([{"name": "Glass file", "category": "cutting"}])
    plan = await preview(client, content, filename="tools.csv")

    await make_tool(client, "Godhand SPN-120", "Cutting")

    resp = await apply(client, content, filename="tools.csv", plan_hash=plan["plan_hash"])
    assert resp.status_code == 409, resp.text


async def test_an_import_update_keeps_its_stated_spelling(client):
    # The other half of the rule: an UPDATE asserts a stored fact, and rewriting
    # it would make a re-imported archive a rewrite. Verbatim, by design.
    await make_tool(client, "Godhand SPN-120", "Cutting")
    await make_tool(client, "Glass file", "Cutting")

    content = _tools_csv([{"name": "Glass file", "category": "cutting"}])
    assert (await apply(client, content, filename="tools.csv")).status_code == 200

    (updated,) = [t for t in (await client.get("/tools")).json() if t["name"] == "Glass file"]
    assert updated["category"] == "cutting"


async def test_an_id_bearing_restore_create_keeps_its_stated_spelling(client):
    # create-is-a-restore (#86's stated policy): a row arriving under its own id
    # is a stored fact being put back, even when nothing currently holds the id.
    await make_tool(client, "Godhand SPN-120", "Cutting")

    restored_id = str(uuid.uuid4())
    content = _tools_csv([{"id": restored_id, "name": "Glass file", "category": "cutting"}])
    assert (await apply(client, content, filename="tools.csv")).status_code == 200

    (restored,) = [t for t in (await client.get("/tools")).json() if t["name"] == "Glass file"]
    assert restored["id"] == restored_id
    assert restored["category"] == "cutting"


async def test_two_id_less_creates_in_one_upload_fold_onto_one_spelling(client):
    # Nothing stored: the vocabulary is the upload's own, first spelling in file
    # order wins, and the second row folds onto it rather than fragmenting.
    content = _tools_csv(
        [
            {"name": "Godhand SPN-120", "category": "Cutting"},
            {"name": "Glass file", "category": "cutting"},
        ]
    )
    assert (await apply(client, content, filename="tools.csv")).status_code == 200

    categories = {t["name"]: t["category"] for t in (await client.get("/tools")).json()}
    assert categories == {"Godhand SPN-120": "Cutting", "Glass file": "Cutting"}


async def test_a_create_folds_onto_the_spelling_an_update_is_writing(client):
    # The vocabulary the fold consults is the EFFECTIVE post-import one (#130
    # round 2, P2-5): a stored row being rewritten by this same upload votes
    # with the spelling it will hold after apply, not the one it held before —
    # otherwise the create folds onto a spelling the import itself is erasing,
    # and the fold recreates the exact split it exists to prevent.
    existing = await make_tool(client, "Existing nipper", "Cutting")

    content = _tools_csv(
        [
            {"id": existing["id"], "name": "Existing nipper", "category": "cutting"},
            {"name": "Glass file", "category": "CUTTING"},
        ]
    )
    assert (await apply(client, content, filename="tools.csv")).status_code == 200

    categories = {t["name"]: t["category"] for t in (await client.get("/tools")).json()}
    assert categories == {"Existing nipper": "cutting", "Glass file": "cutting"}


async def test_replace_all_restores_vote_by_frequency_not_file_order(client):
    # Verbatim rows are a multiset, not a first-wins set: three restores under
    # one key pick the winner by the same most-frequent / byte-order rule
    # `canonical_category` uses, so reordering the sheet cannot change which
    # spelling a create receives (#130 round 2, P2-5). The minority spelling
    # deliberately comes first in file order.
    ids = [str(uuid.uuid4()) for _ in range(3)]
    content = _tools_csv(
        [
            {"id": ids[0], "name": "A", "category": "cutting"},
            {"id": ids[1], "name": "B", "category": "Cutting"},
            {"id": ids[2], "name": "C", "category": "Cutting"},
            {"name": "Glass file", "category": "CUTTING"},
        ]
    )
    resp = await apply(client, content, filename="tools.csv", mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text

    categories = {t["name"]: t["category"] for t in (await client.get("/tools")).json()}
    # Restores verbatim; the create gets the 2:1 winner, not the first row's.
    assert categories == {"A": "cutting", "B": "Cutting", "C": "Cutting", "Glass file": "Cutting"}


async def test_a_create_folds_onto_a_restored_rows_spelling_in_the_same_upload(client):
    # An id-bearing restore's spelling will exist after apply, so an id-less
    # create in the same upload folds onto it — regardless of row order in the
    # sheet (the create deliberately comes first here; verbatim rows seed the
    # vocabulary before any create is folded).
    restored_id = str(uuid.uuid4())
    content = _tools_csv(
        [
            {"name": "Glass file", "category": "cutting"},
            {"id": restored_id, "name": "Godhand SPN-120", "category": "Cutting"},
        ]
    )
    resp = await apply(client, content, filename="tools.csv", mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text

    categories = {t["name"]: t["category"] for t in (await client.get("/tools")).json()}
    assert categories == {"Godhand SPN-120": "Cutting", "Glass file": "Cutting"}


async def test_replace_all_folds_against_the_uploads_own_rows_not_the_doomed_ones(client):
    # Under replace_all the stored rows are deleted before the creates land, so
    # the only spellings that will exist are the upload's own — folding onto a
    # doomed row's spelling would canonicalise onto something being destroyed.
    await make_tool(client, "Old nipper", "cutting")

    content = _tools_csv(
        [
            {"name": "Godhand SPN-120", "category": "Cutting"},
            {"name": "Glass file", "category": "CUTTING"},
        ]
    )
    resp = await apply(client, content, filename="tools.csv", mode="replace_all", confirm="REPLACE")
    assert resp.status_code == 200, resp.text

    categories = {t["name"]: t["category"] for t in (await client.get("/tools")).json()}
    assert categories == {"Godhand SPN-120": "Cutting", "Glass file": "Cutting"}


async def test_reimporting_an_export_with_divergent_spellings_is_a_noop(client):
    # The reason the importer is excluded: an instance can legitimately hold
    # case-variant spellings from before this change, its export states them,
    # and a re-import that folded them onto each other would rewrite rows the
    # upload never asked to change (rule 10 by analogy).
    from app.db import get_sessionmaker
    from app.models import Tool

    async with get_sessionmaker()() as session:
        session.add_all(
            [
                Tool(name="A", category="cutting", quantity_on_hand=0),
                Tool(name="B", category="Cutting", quantity_on_hand=0),
            ]
        )
        await session.commit()

    exported = await client.get("/export/tools.csv")
    assert (await apply(client, exported.content, filename="tools.csv")).status_code == 200

    categories = {t["name"]: t["category"] for t in (await client.get("/tools")).json()}
    assert categories == {"A": "cutting", "B": "Cutting"}


# --- the MCP read surface --------------------------------------------------------


async def test_mcp_categories_and_filter_round_trip(client):
    await make_tool(client, "Godhand SPN-120", "Cutting")
    await make_tool(client, "Tamiya sharp", "Cutting")
    await make_tool(client, "Glass file", "Filing")

    async with Client(mcp) as mcp_client:
        # item_type is tolerant the way status is — "Tools" is what an agent says.
        values = (
            await mcp_client.call_tool("list_catalog_categories", {"item_type": "Tools"})
        ).data
        assert values == ["Cutting", "Filing"]

        filtered = (
            await mcp_client.call_tool(
                "list_catalog_items", {"item_type": "tool", "category": "cutting"}
            )
        ).data
        assert {row["name"] for row in filtered} == {"Godhand SPN-120", "Tamiya sharp"}


async def test_mcp_refuses_category_asks_that_have_no_answer(client):
    async with Client(mcp) as mcp_client:
        # Upgrades: no column — the refusal names the table rather than answering
        # with an empty vocabulary that implies one exists (rule 6's error shape).
        with pytest.raises(ToolError, match="upgrades have no category"):
            await mcp_client.call_tool("list_catalog_categories", {"item_type": "upgrade"})
        with pytest.raises(ToolError, match="upgrades have no category"):
            await mcp_client.call_tool(
                "list_catalog_items", {"item_type": "upgrade", "category": "anything"}
            )
        # Kits are not a catalog table; the refusal points at the right tools.
        with pytest.raises(ToolError, match="list_kits"):
            await mcp_client.call_tool("list_catalog_categories", {"item_type": "kit"})
