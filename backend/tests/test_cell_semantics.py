"""What a cell means when it says nothing usable (#82, #88).

Three cases the CSV contract had never separated, all of which arrived as either
a silent drop or a 500:

* a **blank cell in a column the database cannot leave empty** — "blank means
  null" is the documented rule and archive fidelity needs it, but nine columns
  across six tables refuse null and died at flush;
* the **create** half of the same thing, where there is no stored value to fall
  back on;
* an **optional reference naming a row that isn't there** — resolvable in neither
  the database nor the upload, so the column the operator filled in was discarded
  without a word (#82).

The tables here are enumerated from the spec and the model rather than typed out,
so a column added to a model arrives in these tests on its own.
"""

import pytest
from sqlalchemy import inspect

from app.services.portability import spec
from app.services.portability.importing import _COLUMN_DEFAULTS
from app.services.portability.spec import ColumnRole
from tests.test_portability import actions, apply, make_csv, preview

pytestmark = pytest.mark.anyio

MISSING = "11111111-1111-1111-1111-111111111111"


def nullable(table_key: str, name: str) -> bool:
    """Read straight from the model, never through the importer's own helper.

    These tests parametrise themselves off this enumeration, so calling the
    function under test would let a mutation of it empty the list — and an empty
    `parametrize` is a *skip*, not a failure. Mutation testing caught exactly that:
    `_column_is_nullable` was replaced with `return True` and the whole matrix
    quietly stopped existing while the run stayed green. A test that derives its
    own subject from the code it is testing can be disarmed rather than broken.
    """
    column = spec.SPEC_BY_KEY[table_key].model.__table__.columns.get(name)
    return column is None or column.nullable


def has_own_default(table_key: str, name: str) -> bool:
    column = spec.SPEC_BY_KEY[table_key].model.__table__.columns.get(name)
    return column is not None and (column.default is not None or column.server_default is not None)


def unstatable_columns() -> list[tuple[str, str]]:
    """Every persisted column the database requires but the sheet may leave blank
    — the exact set that used to reach `IntegrityError`."""
    found = []
    for table in spec.TABLE_SPECS:
        for column in table.columns:
            if column.name == "id" or not column.persisted or column.required:
                continue
            if not nullable(table.key, column.name):
                found.append((table.key, column.name))
    return found


def mirrored_columns() -> list[tuple[str, str, str]]:
    """The subset of the enumeration whose value a readable twin can supply."""
    return [
        (table_key, name, mirror)
        for table_key, name in unstatable_columns()
        if (mirror := mirror_of(table_key, name)) is not None
    ]


def mirror_of(table_key: str, name: str) -> str | None:
    table = spec.SPEC_BY_KEY[table_key]
    return next(
        (
            c.name
            for c in table.columns
            if c.role in (ColumnRole.ALT_REF, ColumnRole.ALT_MONEY) and c.mirrors == name
        ),
        None,
    )


# --- the enumeration itself is a contract ---------------------------------------


def test_every_column_the_database_requires_can_be_filled_from_somewhere():
    """The systematic guard #88 asked for, and the check on the two lists agreeing.

    A column the database requires has to be fillable by *something* when a sheet
    leaves it out: the spec marks it required, the schema defaults it, the importer
    defaults it, or a readable mirror supplies it. `kits.created_at` and
    `kits.updated_at` satisfied none of those — they have server defaults the
    importer's hand-written `_COLUMN_DEFAULTS` didn't know about — and they were
    exactly the two blanks that came back as a 500.

    This is what catches the next column added to a model.
    """
    unfillable = []
    for table_key, name in unstatable_columns():
        table = spec.SPEC_BY_KEY[table_key]
        if has_own_default(table_key, name):
            continue
        if name in _COLUMN_DEFAULTS.get(table_key, {}):
            continue
        if mirror_of(table_key, name) is not None:
            continue
        unfillable.append(f"{table_key}.{name}")
    assert unfillable == [], (
        "these columns are NOT NULL, optional in the sheet, and nothing can fill "
        "them in — a blank cell reaches the database as null"
    )


def test_the_importers_default_list_claims_nothing_the_schema_already_covers():
    """`_COLUMN_DEFAULTS` is importer policy — the omissions the *file format*
    forgives where the database has no opinion. Anything the schema defaults is
    read from the model instead, so the two cannot say different things about one
    column."""
    overlap = [
        f"{table_key}.{name}"
        for table_key, names in _COLUMN_DEFAULTS.items()
        for name in names
        if has_own_default(table_key, name)
    ]
    assert overlap == [], (
        "these are defaulted by the schema and restated by the importer — pick one"
    )


# --- seeding --------------------------------------------------------------------


@pytest.fixture
async def collection(client):
    """One row in every table these tests touch, with the ids to address them."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    consumable = (
        await client.post(
            "/consumables", json={"name": "Paint", "category": "paint", "quantity_on_hand": 4}
        )
    ).json()
    tool = (
        await client.post(
            "/tools", json={"name": "Nippers", "category": "cutting", "quantity_on_hand": 2}
        )
    ).json()
    upgrade = (
        await client.post(
            "/upgrades", json={"name": "Thruster", "manufacturer": "K", "quantity_on_hand": 6}
        )
    ).json()
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
    kit = order["items"][0]["kits"][0]
    application = (
        await client.post(
            f"/upgrades/{upgrade['id']}/apply", json={"kit_id": kit["id"], "quantity": 1}
        )
    ).json()
    photo_id = "b17c0a4e-9d33-4a51-8f60-2ee9c1130044"
    seeded = make_csv(
        ["id", "kit_id", "file_path"],
        [{"id": photo_id, "kit_id": kit["id"], "file_path": "shots/a.jpg"}],
    )
    assert (await apply(client, seeded, filename="kit_photos.csv")).status_code == 200

    return {
        "retailers": {"id": retailer["id"], "row": {"name": "Hobby Link Japan"}},
        "tools": {"id": tool["id"], "row": {"name": "Nippers", "category": "cutting"}},
        "consumables": {"id": consumable["id"], "row": {"name": "Paint", "category": "paint"}},
        "upgrades": {"id": upgrade["id"], "row": {"name": "Thruster", "manufacturer": "K"}},
        "orders": {
            "id": order["id"],
            "row": {"order_date": "2026-03-14", "currency_code": "JPY"},
        },
        "order_items": {
            "id": order["items"][0]["id"],
            "row": {
                "order_id": order["id"],
                "item_type": "kit",
                "quantity": "1",
                "currency_code": "JPY",
            },
        },
        "kits": {"id": kit["id"], "row": {"name": "Zaku II", "grade": "HG"}},
        "upgrade_applications": {
            "id": application["id"],
            "row": {
                "upgrade_id": upgrade["id"],
                "kit_id": kit["id"],
                "quantity_used": "1",
            },
        },
        "kit_photos": {
            "id": photo_id,
            "row": {"kit_id": kit["id"], "file_path": "shots/a.jpg"},
        },
    }


async def stored_value(table_key: str, row_id: str) -> object:
    from app.db import get_sessionmaker

    model = spec.SPEC_BY_KEY[table_key].model
    async with get_sessionmaker()() as session:
        return await session.get(model, row_id)


# --- a blank cell never writes NULL where NULL is refused (#88) ------------------


@pytest.mark.parametrize(("table_key", "column"), unstatable_columns())
async def test_a_blank_cell_in_a_required_column_keeps_the_stored_value(
    client, collection, table_key, column
):
    """Every column in the enumeration, on an update, with the mirror deliberately
    left out so nothing else can supply the value.

    Previously all nine previewed clean and died at flush: a bare 500 naming no
    row, after the operator was told the import was fine (rule 6). The answer is
    the stored value — you cannot unset a creation time or a retailer, so a blank
    in a column like this is closer to an omission than an instruction, and an
    omitted column is already left alone.
    """
    seeded = collection[table_key]
    before = await stored_value(table_key, seeded["id"])
    was = getattr(before, column)
    assert was is not None, f"{table_key}.{column} has to start non-null for this to mean anything"

    header = ["id", *seeded["row"], column]
    row = {"id": seeded["id"], **seeded["row"], column: ""}
    content = make_csv(header, [row])

    plan = await preview(client, content, filename=f"{table_key}.csv")
    assert plan["blocking_errors"] == [], plan
    messages = " ".join(plan["tables"][0]["rows"][0]["messages"])
    assert f"{column}: left as it was" in messages, messages
    # And no change is planned for it — the preview must not promise an edit that
    # is not going to happen.
    assert column not in [c["field"] for c in plan["tables"][0]["rows"][0]["changes"]]

    resp = await apply(client, content, filename=f"{table_key}.csv")
    assert resp.status_code == 200, resp.text
    after = await stored_value(table_key, seeded["id"])
    assert getattr(after, column) == was


@pytest.mark.parametrize(("table_key", "column", "mirror"), mirrored_columns())
async def test_a_readable_mirror_still_wins_over_a_blank(
    client, collection, table_key, column, mirror
):
    """The ordering the fix depends on: `_resolve_all_refs` and
    `_apply_money_alternates` run first, so a blank `retailer_id` beside a filled
    `retailer_name` — or a blank `unit_price_minor` beside a filled `unit_price` —
    is settled from the mirror and never reaches the keep-the-stored-value rule.

    Parametrised over the mirrored subset rather than skipping the rest — a
    skip that is structural rather than conditional is a test count that lies."""
    seeded = collection[table_key]
    supplied = {"retailer_name": "Gundam Base", "unit_price": "31.50", "catalog_name": "Paint"}[
        mirror
    ]
    header = ["id", *seeded["row"], column, mirror]
    content = make_csv(
        [*header], [{"id": seeded["id"], **seeded["row"], column: "", mirror: supplied}]
    )

    plan = await preview(client, content, filename=f"{table_key}.csv")
    assert plan["blocking_errors"] == [], plan
    messages = " ".join(plan["tables"][0]["rows"][0]["messages"])
    assert f"{column}: left as it was" not in messages, "the mirror should have supplied it"
    assert (await apply(client, content, filename=f"{table_key}.csv")).status_code == 200


async def test_a_new_row_missing_a_required_value_is_named_not_a_500(client, http_client):
    """The create half. There is no stored value to keep, so the only answers are a
    default, a mirror, or a refusal — and the refusal has to name the row.

    `orders.retailer_id` is the one column in the enumeration with neither a
    default nor anything else to fall back on once the mirror is empty too.
    """
    content = make_csv(
        ["order_date", "currency_code", "retailer_id", "retailer_name"],
        [
            {
                "order_date": "2026-03-14",
                "currency_code": "JPY",
                "retailer_id": "",
                "retailer_name": "",
            }
        ],
    )
    plan = await preview(http_client, content, filename="orders.csv")
    assert actions(plan, "orders") == ["error"], plan["tables"]
    assert plan["tables"][0]["rows"][0]["error"].startswith("retailer_id:")

    resp = await apply(http_client, content, filename="orders.csv")
    assert resp.status_code == 409, "a named row, not the IntegrityError this used to be"
    assert (await client.get("/orders")).json() == []


async def test_a_new_row_takes_the_schema_default_it_leaves_blank(client):
    """The other side of the create rule: a column the schema defaults is filled by
    the schema, not refused and not written as null. `kits.created_at` and
    `kits.updated_at` are the two the importer's own list had never heard of."""
    content = make_csv(
        ["name", "grade", "status", "status_updated_at", "created_at", "updated_at"],
        [
            {
                "name": "Gouf",
                "grade": "HG",
                "status": "",
                "status_updated_at": "",
                "created_at": "",
                "updated_at": "",
            }
        ],
    )
    plan = await preview(client, content, filename="kits.csv")
    assert plan["blocking_errors"] == [], plan
    assert (await apply(client, content, filename="kits.csv")).status_code == 200

    kit = (await client.get("/kits")).json()[0]
    assert kit["status"] == "backlog", "the model's own default"
    for column in ("status_updated_at", "created_at", "updated_at"):
        assert kit[column] is not None, column


# --- an optional reference that resolves to nothing (#82) -----------------------


async def test_a_dangling_optional_reference_is_reported_not_silently_dropped(client, collection):
    """#82. `kits.order_item_id` names an order line that exists nowhere — not in
    this instance, not in the upload.

    Imported rather than blocked: "import just `kits.csv` into a fresh instance" is
    a documented onboarding path, and every row of that file names a line the new
    instance has never had. But not silent either — the operator filled the cell
    in, and it is being discarded.
    """
    content = make_csv(
        ["name", "grade", "order_item_id"],
        [{"name": "Gouf", "grade": "HG", "order_item_id": MISSING}],
    )
    plan = await preview(client, content, filename="kits.csv")
    assert plan["blocking_errors"] == [], plan
    messages = " ".join(plan["tables"][0]["rows"][0]["messages"])
    assert "order_item_id" in messages and MISSING in messages, messages

    assert (await apply(client, content, filename="kits.csv")).status_code == 200
    gouf = next(k for k in (await client.get("/kits")).json() if k["name"] == "Gouf")
    assert gouf["order_item_id"] is None


async def test_a_dangling_reference_in_a_required_column_still_blocks(client, collection):
    """The control on the rule above: `order_items.order_id` is required, so it
    keeps the blocking error it always had rather than becoming a message."""
    content = make_csv(
        ["order_id", "item_type", "quantity", "unit_price_minor", "currency_code"],
        [
            {
                "order_id": MISSING,
                "item_type": "kit",
                "quantity": "1",
                "unit_price_minor": "100",
                "currency_code": "JPY",
            }
        ],
    )
    plan = await preview(client, content, filename="order_items.csv")
    assert actions(plan, "order_items") == ["error"], plan["tables"]
    assert (await apply(client, content, filename="order_items.csv")).status_code == 409


async def test_a_reference_that_resolves_says_nothing(client, collection):
    """The other control: a live row still resolves silently, so the message is
    about a genuine loss rather than a running commentary on every reference."""
    content = make_csv(
        ["name", "grade", "order_item_id"],
        [{"name": "Gouf", "grade": "HG", "order_item_id": collection["order_items"]["id"]}],
    )
    plan = await preview(client, content, filename="kits.csv")
    assert plan["tables"][0]["rows"][0]["messages"] == []
    assert (await apply(client, content, filename="kits.csv")).status_code == 200
    gouf = next(k for k in (await client.get("/kits")).json() if k["name"] == "Gouf")
    assert gouf["order_item_id"] == collection["order_items"]["id"]


def test_the_model_metadata_these_tests_read_is_what_they_think_it_is():
    """The enumeration drives everything above, so it is worth one assertion that
    it is not silently empty — a bug there would make the whole module vacuous."""
    found = unstatable_columns()
    assert len(found) >= 9, found
    assert ("kits", "created_at") in found
    assert ("orders", "retailer_id") in found
    assert all(inspect(spec.SPEC_BY_KEY[t].model) is not None for t, _ in found)
