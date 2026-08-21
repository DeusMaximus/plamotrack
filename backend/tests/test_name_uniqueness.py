"""#107 — a retailer's or catalog item's name is unique within its table, case-
insensitively, on every write surface.

The importer treats `strip().lower()` of the name as the natural key for retailers
and the three catalog tables (§12.4), and refuses an id-less row that matches two.
`get_or_create_retailer` applied that rule on the way in (#49); the create and rename
paths applied none, so `HLJ` and `hlj` were one request apart on REST, on MCP and
through an order line's `new_item`. These tests pin the rule at `services/names.py`
and drive it through every surface that writes a name.

Value axis (what a name can be relative to one already stored): exact, re-cased,
padded, padded *in the database* (rows written before the rule existed), a wildcard
character, genuinely different, and blank. State axis: the existing row present or
absent; create vs rename; rename onto another row, onto a fresh name, and onto the
row's own name re-cased — the last is the case a naïve uniqueness check gets wrong.
Two rows are seeded wherever the rule is about rows diverging.

Negative controls are the rows that must still be *allowed*: different names, the
same name in a different table, a row re-casing itself. Those stay green on the
unfixed code; everything asserting 409/ToolError goes red there.
"""

import asyncio
import time
import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import text

from app.db import session_scope
from app.exceptions import ConflictError, InvalidInputError
from app.mcp import mcp
from app.models import Consumable, DisplayItem, Retailer, Tool, Upgrade
from app.schemas.catalog import (
    ConsumableCreate,
    DisplayItemCreate,
    ToolCreate,
    UpgradeCreate,
)
from app.schemas.orders import RetailerCreate
from app.services import catalog, orders
from app.services.write_gate import acquire_write_gate

# --- the five tables, as REST sees them ------------------------------------------

#: (collection path, the non-name fields a create needs, the model behind it)
TABLES = [
    pytest.param("/retailers", {}, Retailer, id="retailers"),
    pytest.param("/tools", {"category": "cutting"}, Tool, id="tools"),
    pytest.param("/consumables", {"category": "paint"}, Consumable, id="consumables"),
    pytest.param("/upgrades", {"manufacturer": "Metal Build"}, Upgrade, id="upgrades"),
    pytest.param("/display-items", {"category": "stand"}, DisplayItem, id="display_items"),
]


async def _create(client, path: str, extra: dict, name: str):
    return await client.post(path, json={"name": name, **extra})


async def _names(client, path: str) -> list[str]:
    return sorted(r["name"] for r in (await client.get(path)).json())


async def _seed_raw(model, name: str, **fields):
    """A row as the database may already hold it — written around the API, because
    the API no longer writes padded or duplicate names."""
    async with session_scope() as session:
        row = model(name=name, **fields)
        session.add(row)
        await session.commit()
        return str(row.id)


def _raw_fields(model) -> dict:
    return {
        Tool: {"category": "x"},
        Consumable: {"category": "x"},
        Upgrade: {"manufacturer": "x"},
        DisplayItem: {"category": "x"},
    }.get(model, {})


# --- create: the value axis, every table ---------------------------------------

#: (stored, asked, clashes). Ids are explicit because `pytest -k` is case-insensitive:
#: the two re-cased directions are distinct mutants' detectors (fold the stored side
#: only vs fold the input only) and have to be selectable apart.
VALUE_CASES = [
    pytest.param("HLJ", "HLJ", True, id="exact"),
    pytest.param("HLJ", "hlj", True, id="recased-stored-upper"),
    # the other way — both sides fold, not just the stored one
    pytest.param("hlj", "HLJ", True, id="recased-stored-lower"),
    pytest.param("HLJ", "  hlj  ", True, id="padded-input"),  # stripped before comparing
    # folded in Postgres on both sides (#49)
    pytest.param("İstanbul Hobby", "istanbul hobby", True, id="turkish-dotted-i"),
    # a wildcard is a character, and a character equals itself
    pytest.param("%", "%", True, id="percent-is-itself"),
    pytest.param("A", "_", False, id="underscore-is-not-any-char"),
    # internal whitespace is significant
    pytest.param("Hobby Link Japan", "Hobby  Link Japan", False, id="internal-space"),
    pytest.param("HLJ", "HLJ Japan", False, id="different"),
    pytest.param("HLJ", "  HLJ Japan  ", False, id="different-padded"),  # stored stripped
]


@pytest.mark.parametrize(("path", "extra", "model"), TABLES)
@pytest.mark.parametrize(("stored", "asked", "clashes"), VALUE_CASES)
async def test_create_refuses_a_name_another_row_already_holds(
    http_client, path, extra, model, stored, asked, clashes
):
    first = await _create(http_client, path, extra, stored)
    assert first.status_code == 201, first.text

    second = await _create(http_client, path, extra, asked)

    if clashes:
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        assert "already exists" in detail
        assert f"'{stored}'" in detail  # names the row that holds it, as stored
        assert first.json()["id"] in detail  # and hands over its id for reuse
        assert await _names(http_client, path) == [stored]
    else:
        assert second.status_code == 201, second.text
        assert second.json()["name"] == asked.strip()
        assert await _names(http_client, path) == sorted([stored, asked.strip()])


@pytest.mark.parametrize(("path", "extra", "model"), TABLES)
async def test_create_with_no_existing_row_is_unchanged(client, path, extra, model):
    """The state axis's other value: nothing stored, so nothing to clash with."""
    resp = await _create(client, path, extra, "HLJ")
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "HLJ"


#: Padding a row written before the rule can carry. The importer's `strip()` removes
#: all of these; a stored-side trim that removes fewer leaves the pair #107 closes
#: (PR #109 review, P3-1: plain `btrim` is `0x20` only, and the other four each
#: let a second row through).
LEGACY_PADDING = [
    pytest.param(" ", id="space"),
    pytest.param("\t", id="tab"),
    pytest.param("\n", id="newline"),
    pytest.param("\u00a0", id="nbsp"),
    pytest.param("\u3000", id="ideographic-space"),
]


@pytest.mark.parametrize(("path", "extra", "model"), TABLES)
@pytest.mark.parametrize("pad", LEGACY_PADDING)
async def test_a_row_stored_with_surrounding_whitespace_still_owns_its_name(
    http_client, path, extra, model, pad
):
    """Rows written before the rule can carry padding (the browser forms never
    trimmed, and nothing stopped a paste bringing a no-break space along). The
    importer reads `"\tHLJ"` and `hlj` as one key, so the refusal has to as well —
    the stored side is trimmed with the same set Python's `strip()` uses, not
    `btrim`'s default space."""
    legacy_id = await _seed_raw(model, f"{pad}HLJ{pad}", **_raw_fields(model))

    resp = await _create(http_client, path, extra, "hlj")

    assert resp.status_code == 409, resp.text
    assert legacy_id in resp.json()["detail"]
    assert await _names(http_client, path) == [f"{pad}HLJ{pad}"]  # the legacy row is left alone


@pytest.mark.parametrize("pad", LEGACY_PADDING)
async def test_get_or_create_retailer_reuses_a_legacy_padded_row(client, pad):
    """The other consumer of the predicate: an agent naming `HLJ` on `create_order`
    must land on the tab-padded legacy shop, not mint a second one — which is the
    one thing that function exists to prevent (#49)."""
    legacy_id = await _seed_raw(Retailer, f"{pad}HLJ{pad}")

    async with session_scope() as session:
        row = await orders.get_or_create_retailer(session, "HLJ")
        assert str(row.id) == legacy_id
        await session.commit()

    assert await _names(client, "/retailers") == [f"{pad}HLJ{pad}"]


async def test_the_same_name_in_different_tables_is_not_a_clash(client):
    """Per table, as the importer's natural key is. A tool and a consumable called
    "Nipper" are two things; so is a retailer that happens to share the word."""
    for path, extra, _ in (p.values for p in TABLES):
        resp = await _create(client, path, extra, "Nipper")
        assert resp.status_code == 201, (path, resp.text)


@pytest.mark.parametrize(
    ("path", "extra", "model", "opening"),
    [
        pytest.param("/retailers", {}, Retailer, "a retailer named", id="retailers"),
        pytest.param("/tools", {"category": "cutting"}, Tool, "a tool named", id="tools"),
        pytest.param(
            "/consumables",
            {"category": "paint"},
            Consumable,
            "a consumable named",
            id="consumables",
        ),
        pytest.param(
            "/upgrades", {"manufacturer": "Metal Build"}, Upgrade, "an upgrade named", id="upgrades"
        ),
    ],
)
async def test_the_refusal_reads_as_a_sentence(http_client, path, extra, model, opening):
    """The message is what the browser banner and the agent both see. "an upgrade",
    not "a upgrade" (PR #109 review, drive-by)."""
    await _create(http_client, path, extra, "Nipper")
    resp = await _create(http_client, path, extra, "nipper")
    assert resp.status_code == 409
    assert resp.json()["detail"].startswith(opening), resp.json()["detail"]


# --- create: blank -----------------------------------------------------------------


@pytest.mark.parametrize(("path", "extra", "model"), TABLES)
@pytest.mark.parametrize("blank", [" ", "   ", "\t"], ids=repr)
async def test_a_whitespace_only_name_is_invalid_input(http_client, path, extra, model, blank):
    """`min_length=1` lets `" "` through. Stored, it has no natural key at all; stripped
    on the way in it would be `""`. Refused as invalid input — not a conflict, and
    not a database error."""
    resp = await _create(http_client, path, extra, blank)
    assert resp.status_code == 422, resp.text
    assert "blank" in resp.json()["detail"]
    assert await _names(http_client, path) == []


# --- create: the service speaks, with the right class ----------------------------


async def test_the_service_raises_a_conflict_not_an_integrity_error():
    """Assert the layer and the class: `ConflictError` from the service, before any
    insert — not an `IntegrityError` from a constraint the schema doesn't have."""
    async with session_scope() as session:
        await orders.create_retailer(session, RetailerCreate(name="HLJ"))
    async with session_scope() as session:
        with pytest.raises(ConflictError, match="already exists"):
            await orders.create_retailer(session, RetailerCreate(name="hlj"))

    async with session_scope() as session:
        await catalog.create_tool(session, ToolCreate(name="Nipper", category="cutting"))
    async with session_scope() as session:
        with pytest.raises(ConflictError, match="already exists"):
            await catalog.create_tool(session, ToolCreate(name="NIPPER", category="cutting"))
    async with session_scope() as session:
        await catalog.create_consumable(session, ConsumableCreate(name="Cement", category="glue"))
    async with session_scope() as session:
        with pytest.raises(ConflictError, match="already exists"):
            await catalog.create_consumable(
                session, ConsumableCreate(name="cement", category="glue")
            )
    async with session_scope() as session:
        await catalog.create_upgrade(session, UpgradeCreate(name="Thrusters", manufacturer="MB"))
    async with session_scope() as session:
        with pytest.raises(ConflictError, match="already exists"):
            await catalog.create_upgrade(
                session, UpgradeCreate(name="thrusters", manufacturer="MB")
            )
    async with session_scope() as session:
        await catalog.create_display_item(
            session, DisplayItemCreate(name="Action Base 2", category="stand")
        )
    async with session_scope() as session:
        # The conflict message is built from a per-model noun table, and a model
        # missing from it raises a KeyError *inside* the conflict path — a 500 where
        # a 409 was owed, which is what display items did until #126 added the entry.
        # `pytest.raises(ConflictError)` is what separates the two; a bare
        # "this refused" assertion would have passed on the KeyError.
        with pytest.raises(ConflictError, match="a display item named"):
            await catalog.create_display_item(
                session, DisplayItemCreate(name="ACTION BASE 2", category="stand")
            )

    async with session_scope() as session:
        with pytest.raises(InvalidInputError, match="blank"):
            await orders.create_retailer(session, RetailerCreate(name="  "))


# --- rename: the state axis --------------------------------------------------------


@pytest.mark.parametrize(("path", "extra", "model"), TABLES)
async def test_rename_onto_another_rows_name_is_refused(http_client, path, extra, model):
    """Two rows, so the rule has something to diverge over."""
    hlj = (await _create(http_client, path, extra, "HLJ")).json()
    base = (await _create(http_client, path, extra, "Gundam Base")).json()

    resp = await http_client.patch(f"{path}/{base['id']}", json={"name": "hlj"})

    assert resp.status_code == 409, resp.text
    assert "'HLJ'" in resp.json()["detail"]
    assert hlj["id"] in resp.json()["detail"]
    assert await _names(http_client, path) == ["Gundam Base", "HLJ"]  # nothing renamed


@pytest.mark.parametrize(("path", "extra", "model"), TABLES)
@pytest.mark.parametrize(
    ("new_name", "stored_after"),
    [
        ("Gundam Base Tokyo", "Gundam Base Tokyo"),  # onto a fresh name
        ("gundam base", "gundam base"),  # onto its own name, re-cased
        ("  Gundam Base  ", "Gundam Base"),  # onto its own name, padded — stored stripped
    ],
    ids=repr,
)
async def test_rename_to_a_free_name_or_its_own_is_allowed(
    client, path, extra, model, new_name, stored_after
):
    """The row's own id is excluded from the check — a naïve "does anything hold
    this name" sees the row itself and refuses a re-casing. The other row is a
    bystander that must stay untouched."""
    await _create(client, path, extra, "HLJ")
    base = (await _create(client, path, extra, "Gundam Base")).json()

    resp = await client.patch(f"{path}/{base['id']}", json={"name": new_name})

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == stored_after
    assert await _names(client, path) == sorted(["HLJ", stored_after])


@pytest.mark.parametrize(("path", "extra", "model"), TABLES)
async def test_a_patch_that_does_not_carry_the_name_is_not_checked(client, path, extra, model):
    """Absent, not merely unchanged: the check runs only when `name` is in the
    patch. A notes-only edit on a row whose name a *legacy* duplicate shares must
    still succeed — the edit is not the thing that made the pair."""
    await _seed_raw(model, "HLJ", **_raw_fields(model))
    twin_id = await _seed_raw(model, "hlj", **_raw_fields(model))
    patch = {"quantity_on_hand": 3} if path != "/retailers" else {"notes": "still fine"}

    resp = await client.patch(f"{path}/{twin_id}", json=patch)

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "hlj"


@pytest.mark.parametrize(("path", "extra", "model"), TABLES)
async def test_rename_to_blank_is_invalid_input(http_client, path, extra, model):
    row = (await _create(http_client, path, extra, "HLJ")).json()
    resp = await http_client.patch(f"{path}/{row['id']}", json={"name": "   "})
    assert resp.status_code == 422, resp.text
    assert "blank" in resp.json()["detail"]
    assert await _names(http_client, path) == ["HLJ"]


# --- new_item on an order line: the third writer ------------------------------------

NEW_ITEM_LINES = [
    pytest.param("tool", "/tools", {"category": "cutting"}, id="tool"),
    pytest.param("consumable", "/consumables", {"category": "paint"}, id="consumable"),
    pytest.param("upgrade", "/upgrades", {"manufacturer": "Metal Build"}, id="upgrade"),
]


def _new_item_line(item_type: str, name: str, extra: dict) -> dict:
    return {
        "item_type": item_type,
        "quantity": 1,
        "unit_price_minor": 500,
        "currency_code": "AUD",
        "new_item": {"name": name, **extra},
    }


def _order(retailer: dict, lines: list[dict]) -> dict:
    return {
        "retailer_id": retailer["id"],
        "order_date": "2026-08-01",
        "currency_code": "AUD",
        "items": lines,
    }


@pytest.mark.parametrize(("item_type", "path", "extra"), NEW_ITEM_LINES)
async def test_new_item_on_order_create_refuses_an_existing_name(
    http_client, retailer, item_type, path, extra
):
    """`search_catalog` is the select half of select-or-create and only a gate if it
    was called. A line that creates what already exists is refused, and because an
    order is one transaction (rule 2) the order is not created either."""
    existing = (await _create(http_client, path, extra, "Tamiya Extra Thin")).json()

    resp = await http_client.post(
        "/orders",
        json=_order(retailer, [_new_item_line(item_type, "tamiya extra thin", extra)]),
    )

    assert resp.status_code == 409, resp.text
    assert existing["id"] in resp.json()["detail"]
    assert (await http_client.get("/orders")).json() == []
    assert await _names(http_client, path) == ["Tamiya Extra Thin"]


@pytest.mark.parametrize(("item_type", "path", "extra"), NEW_ITEM_LINES)
async def test_new_item_with_a_fresh_name_still_creates_it_stripped(
    client, retailer, item_type, path, extra
):
    resp = await client.post(
        "/orders",
        json=_order(retailer, [_new_item_line(item_type, "  Tamiya Extra Thin  ", extra)]),
    )
    assert resp.status_code == 201, resp.text
    assert await _names(client, path) == ["Tamiya Extra Thin"]


async def test_new_item_on_order_edit_refuses_an_existing_name(http_client, retailer):
    """The other state: the line arrives through `update_order`'s diff, not entry.
    The edit is refused whole — the order keeps the lines it had."""
    existing = (
        await _create(http_client, "/consumables", {"category": "paint"}, "Mr Color 1")
    ).json()
    order = (
        await http_client.post(
            "/orders",
            json=_order(
                retailer,
                [_new_item_line("consumable", "Mr Color 2", {"category": "paint"})],
            ),
        )
    ).json()
    kept = order["items"][0]

    kept_line = {
        "id": kept["id"],
        "item_type": "consumable",
        "quantity": 1,
        "unit_price_minor": 500,
        "currency_code": "AUD",
        "catalog_ref_id": kept["catalog_ref_id"],
    }
    resp = await http_client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                kept_line,
                _new_item_line("consumable", "MR COLOR 1", {"category": "paint"}),
            ]
        },
    )

    assert resp.status_code == 409, resp.text
    assert existing["id"] in resp.json()["detail"]
    after = (await http_client.get(f"/orders/{order['id']}")).json()
    assert [i["id"] for i in after["items"]] == [kept["id"]]
    assert await _names(http_client, "/consumables") == ["Mr Color 1", "Mr Color 2"]


async def test_two_new_item_lines_naming_one_thing_refuse_and_create_nothing(http_client, retailer):
    """Declared, not implied: the first line's row is flushed before the second is
    checked, so the second refuses and the transaction takes the first with it. Say
    it on one line with the quantity."""
    resp = await http_client.post(
        "/orders",
        json=_order(
            retailer,
            [
                _new_item_line("consumable", "Mr Hobby Topcoat", {"category": "coat"}),
                _new_item_line("consumable", "mr hobby topcoat", {"category": "coat"}),
            ],
        ),
    )

    assert resp.status_code == 409, resp.text
    assert (await http_client.get("/orders")).json() == []
    assert await _names(http_client, "/consumables") == []


# --- MCP: the same service, the same refusal ---------------------------------------


async def _tool(name: str, args: dict):
    async with Client(mcp) as mcp_client:
        return (await mcp_client.call_tool(name, args)).data


async def _tool_error(name: str, args: dict) -> str:
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as raised:
            await mcp_client.call_tool(name, args)
    return str(raised.value)


async def test_mcp_create_retailer_refuses_what_rest_refuses(client):
    hlj = (await client.post("/retailers", json={"name": "HLJ"})).json()

    message = await _tool_error("create_retailer", {"retailer": {"name": "hlj"}})

    assert "already exists" in message
    assert hlj["id"] in message
    assert await _names(client, "/retailers") == ["HLJ"]


async def test_mcp_create_order_reuses_a_shop_where_create_retailer_refuses_it(client):
    """The two MCP paths differ on purpose. `create_order(retailer=)` is
    select-or-create and *reuses* the match (#49); `create_retailer` is a create and
    *refuses* it (#107). Same predicate, two answers — pinned side by side so a
    change to one is noticed against the other."""
    hlj = (await client.post("/retailers", json={"name": "HLJ"})).json()

    order = await _tool(
        "create_order",
        {
            "retailer": "hlj",
            "order_date": "2026-08-02",
            "items": [
                {
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 2800,
                    "currency_code": "JPY",
                    "kit": {"name": "HG Zaku II", "grade": "HG"},
                }
            ],
        },
    )
    assert order["retailer_id"] == hlj["id"]
    assert "already exists" in await _tool_error("create_retailer", {"retailer": {"name": "hlj"}})
    assert await _names(client, "/retailers") == ["HLJ"]


async def test_mcp_create_order_with_a_blank_retailer_name_is_invalid(client):
    message = await _tool_error(
        "create_order",
        {
            "retailer": "   ",
            "order_date": "2026-08-02",
            "items": [
                {
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 2800,
                    "currency_code": "JPY",
                    "kit": {"name": "HG Zaku II", "grade": "HG"},
                }
            ],
        },
    )
    assert "blank" in message
    assert await _names(client, "/retailers") == []


async def test_mcp_update_retailer_refuses_a_rename_onto_another_shop(client):
    hlj = (await client.post("/retailers", json={"name": "HLJ"})).json()
    base = (await client.post("/retailers", json={"name": "Gundam Base"})).json()

    message = await _tool_error(
        "update_retailer", {"retailer_id": base["id"], "changes": {"name": "Hlj"}}
    )

    assert hlj["id"] in message
    assert await _names(client, "/retailers") == ["Gundam Base", "HLJ"]


async def test_mcp_create_order_new_item_refuses_an_existing_catalog_name(client):
    existing = (
        await client.post("/consumables", json={"name": "Tamiya Extra Thin", "category": "glue"})
    ).json()

    message = await _tool_error(
        "create_order",
        {
            "retailer": "HLJ",
            "order_date": "2026-08-02",
            "items": [_new_item_line("consumable", "TAMIYA EXTRA THIN", {"category": "glue"})],
        },
    )

    assert existing["id"] in message
    assert (await client.get("/orders")).json() == []
    assert await _names(client, "/consumables") == ["Tamiya Extra Thin"]
    # the retailer named on the refused order rolled back with it (rule 2)
    assert await _names(client, "/retailers") == []


@pytest.mark.parametrize(
    ("tool_name", "path", "extra", "id_key"),
    [
        pytest.param(
            "update_catalog_tool", "/tools", {"category": "cutting"}, "tool_id", id="tool"
        ),
        pytest.param(
            "update_catalog_consumable",
            "/consumables",
            {"category": "paint"},
            "consumable_id",
            id="consumable",
        ),
        pytest.param(
            "update_catalog_upgrade",
            "/upgrades",
            {"manufacturer": "Metal Build"},
            "upgrade_id",
            id="upgrade",
        ),
    ],
)
async def test_mcp_catalog_rename_refuses_another_rows_name(client, tool_name, path, extra, id_key):
    first = (await _create(client, path, extra, "Nipper")).json()
    second = (await _create(client, path, extra, "Sanding Stick")).json()

    message = await _tool_error(tool_name, {id_key: second["id"], "changes": {"name": "nipper"}})

    assert first["id"] in message
    assert await _names(client, path) == ["Nipper", "Sanding Stick"]


# --- two writers at once --------------------------------------------------------------


async def _writers_parked_on_the_gate() -> int:
    """How many backends Postgres reports blocked on the advisory lock — asked from
    a connection of its own, so it is the server's view, not the test's hope."""
    async with session_scope() as probe:
        return await probe.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND wait_event = 'advisory'"
            )
        )


async def test_two_writers_naming_one_new_shop_at_once_produce_one_row_and_one_409(http_client):
    """The check is a read the insert depends on, so it runs under the write gate
    (rule 7.1). Two concurrent creates of the same new name serialise: one 201, one
    409, one row — never two rows.

    **Pinned, not raced.** A third transaction holds the gate; both POSTs are
    launched and the test waits until Postgres reports *both* parked on the advisory
    lock; only then is the gate released. Correct code parks *before* its SELECT, so
    the second writer reads the first's committed row → `[201, 409]`. Code that
    checks before it gates has both SELECTs done by the time they park → `[201,
    201]` — every time, not six times out of six under `asyncio.gather` (PR #109
    review, P3-2). The wait is on `pg_stat_activity`, never a sleep."""
    name = f"Race Shop {uuid.uuid4().hex[:6]}"

    async with session_scope() as holder:
        await acquire_write_gate(holder)
        first_task = asyncio.create_task(http_client.post("/retailers", json={"name": name}))
        second_task = asyncio.create_task(
            http_client.post("/retailers", json={"name": name.lower()})
        )
        deadline = time.monotonic() + 10
        while await _writers_parked_on_the_gate() < 2:
            assert time.monotonic() < deadline, (
                "both writers should be parked on the gate by now — "
                "the test is not exercising the interleaving it claims to"
            )
            await asyncio.sleep(0.01)
        # session_scope commits on exit; Postgres drops the advisory lock there.
    first, second = await asyncio.gather(first_task, second_task)

    assert sorted([first.status_code, second.status_code]) == [201, 409]
    # one row under the key — spelled however the writer that won spelled it
    rows = [
        r for r in (await http_client.get("/retailers")).json() if r["name"].lower() == name.lower()
    ]
    assert len(rows) == 1, rows
    winner = first if first.status_code == 201 else second
    assert rows[0]["name"] == winner.json()["name"]
