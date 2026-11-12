"""#289 — MCP `create_order` names its shop by id or by name, and an id is never a name.

The tool had one field for the shop, `retailer`, a name it matched case-insensitively
or created. An agent holding a retailer's id from `list_retailers` passed the id
there, and the call succeeded: a new retailer *named* after the id, the order attached
to it, nothing to tell it from a correct call. The fix is two halves, and each is
tested on its own:

- `retailer_id`, a strict id path beside the name — an unknown id is not found and
  nothing is written; exactly one of the two fields per call.
- `get_or_create_retailer` refuses a name that parses as an id — the value space of
  `retailer_id` — so the mistake is loud even for a caller that never reads the new
  field. Refused even where a stored retailer already carries that string as its
  name, since that row is what the defect minted, and reusing it would keep
  attaching orders to it.

State matters as much as values: with an empty retailer table a refusal and a create
are both "one fewer surprise", so every case seeds the real shop *and* a decoy and
asserts the table is exactly those rows afterwards — no new row, neither touched —
and that no order and no kit was written.
"""

import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.db import session_scope
from app.exceptions import InvalidInputError
from app.mcp import mcp
from app.services import orders

# --- helpers ---------------------------------------------------------------


def _order_args(**shop: str) -> dict:
    return {
        **shop,
        "order_date": "2026-09-22",
        "items": [
            {
                "item_type": "kit",
                "quantity": 1,
                "unit_price_minor": 2800,
                "currency_code": "AUD",
                "kit": {"name": "HG Zaku II", "grade": "HG"},
            }
        ],
    }


async def _create_order(**shop: str) -> dict:
    async with Client(mcp) as mcp_client:
        return (await mcp_client.call_tool("create_order", _order_args(**shop))).data


async def _refusal(**shop: str) -> str:
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as raised:
            await mcp_client.call_tool("create_order", _order_args(**shop))
    return str(raised.value)


async def _seed(client) -> tuple[dict, dict]:
    """The shop the caller means, and a decoy that must stay untouched."""
    amazon = (await client.post("/retailers", json={"name": "Amazon"})).json()
    decoy = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    return amazon, decoy


async def _retailers(client) -> list[tuple[str, str]]:
    return sorted((r["id"], r["name"]) for r in (await client.get("/retailers")).json())


async def _assert_nothing_written(client, retailers_before, orders_before: int = 0):
    assert await _retailers(client) == retailers_before
    assert len((await client.get("/orders")).json()) == orders_before
    # A kit line spawns a kit at entry; a refused order must not leave one behind.
    assert len((await client.get("/kits")).json()) == orders_before


# --- retailer_id: the strict path -------------------------------------------


@pytest.mark.parametrize(
    "spell",
    [
        pytest.param(str, id="canonical"),
        pytest.param(lambda i: str(i).upper(), id="upper-case"),
    ],
)
async def test_retailer_id_attaches_the_order_to_that_shop(client, spell):
    amazon, decoy = await _seed(client)
    before = await _retailers(client)

    order = await _create_order(retailer_id=spell(amazon["id"]))

    assert order["retailer_id"] == amazon["id"]
    assert await _retailers(client) == before  # matched, nothing created


@pytest.mark.parametrize("target", ["unused uuid", "an order's id"])
async def test_an_unknown_retailer_id_is_not_found_and_writes_nothing(client, target):
    amazon, decoy = await _seed(client)
    orders_before = 0
    if target == "an order's id":
        # An id of the wrong kind of thing: real, just not a retailer.
        wrong = (await _create_order(retailer_id=decoy["id"]))["id"]
        orders_before = 1
    else:
        wrong = str(uuid.uuid4())
    before = await _retailers(client)

    message = await _refusal(retailer_id=wrong)

    # The order service's own NotFoundError, not a validation layer's.
    assert f"retailer {wrong} not found" in message
    await _assert_nothing_written(client, before, orders_before)


@pytest.mark.parametrize(
    "value",
    ["Amazon", "", "4a0b254b-f817-457c-bad8-9d1095baa46"],
    ids=["a-name", "empty", "one-digit-short"],
)
async def test_a_malformed_retailer_id_is_refused_before_anything_is_written(client, value):
    await _seed(client)
    before = await _retailers(client)

    message = await _refusal(retailer_id=value)

    assert f"retailer_id {value!r} is not a valid UUID" in message
    await _assert_nothing_written(client, before)


@pytest.mark.parametrize(
    "shape",
    ["both, agreeing", "both, disagreeing", "neither"],
)
async def test_exactly_one_of_retailer_and_retailer_id(client, shape):
    amazon, decoy = await _seed(client)
    before = await _retailers(client)
    shop = {
        "both, agreeing": {"retailer": "Amazon", "retailer_id": amazon["id"]},
        "both, disagreeing": {"retailer": "Amazon", "retailer_id": decoy["id"]},
        "neither": {},
    }[shape]

    message = await _refusal(**shop)

    assert "exactly one of retailer_id" in message
    await _assert_nothing_written(client, before)


# --- retailer: an id is never a name ----------------------------------------

#: Every spelling `retailer_id` accepts is refused as a name — the two fields'
#: value spaces are disjoint. Built from the seeded shop's id at run time, the
#: spellings themselves are literals here (never read off the code under test).
_ID_SPELLINGS = [
    pytest.param(lambda i: i, id="canonical"),
    pytest.param(lambda i: i.upper(), id="upper-case"),
    pytest.param(lambda i: "{" + i + "}", id="braced"),
    pytest.param(lambda i: "urn:uuid:" + i, id="urn"),
    pytest.param(lambda i: i.replace("-", ""), id="no-hyphens"),
    pytest.param(lambda i: "  " + i + "\t", id="padded"),
    pytest.param(lambda i: str(uuid.uuid4()), id="an-id-of-nothing"),
]


@pytest.mark.parametrize("spell", _ID_SPELLINGS)
async def test_an_id_given_as_the_retailer_name_is_refused(client, spell):
    amazon, decoy = await _seed(client)
    before = await _retailers(client)

    message = await _refusal(retailer=spell(amazon["id"]))

    assert "is an id, not a shop's name" in message
    assert "retailer_id" in message  # the refusal names the way out
    await _assert_nothing_written(client, before)


async def test_a_stored_row_named_after_an_id_is_not_reused(client):
    """The state an instance hit by #289 is in: a junk retailer whose name is the
    real shop's id. Name matching would find it and attach the next order made the
    same mistaken way to it — refused instead."""
    amazon, decoy = await _seed(client)
    junk = (await client.post("/retailers", json={"name": amazon["id"]})).json()
    assert junk["name"] == amazon["id"]
    before = await _retailers(client)

    message = await _refusal(retailer=amazon["id"])

    assert "is an id, not a shop's name" in message
    await _assert_nothing_written(client, before)
    # And the real shop is one `retailer_id` away.
    order = await _create_order(retailer_id=amazon["id"])
    assert order["retailer_id"] == amazon["id"]


@pytest.mark.parametrize(
    ("name", "reuses"),
    [("Amazon", True), ("  amazon ", True), ("Plamo Crazy", False)],
    ids=["exact", "case-and-padding", "new-shop"],
)
async def test_a_name_still_matches_or_creates(client, name, reuses):
    """The control: the guard refuses ids, not names."""
    amazon, decoy = await _seed(client)

    order = await _create_order(retailer=name)

    rows = await _retailers(client)
    if reuses:
        assert order["retailer_id"] == amazon["id"]
        assert len(rows) == 2
    else:
        assert order["retailer_id"] not in (amazon["id"], decoy["id"])
        assert (order["retailer_id"], name) in rows
        assert len(rows) == 3


# --- the layer that spoke ----------------------------------------------------


async def test_the_refusal_is_the_service_s_with_its_code(client):
    """`get_or_create_retailer` itself refuses — not the tool wrapper — so any
    future caller of the select-or-create inherits it (rule 1)."""
    amazon, decoy = await _seed(client)
    before = await _retailers(client)

    async with session_scope() as session:
        with pytest.raises(InvalidInputError) as raised:
            await orders.get_or_create_retailer(session, f" {amazon['id']} ")

    assert raised.value.code == "name.is_id"
    assert raised.value.params == {"name": amazon["id"]}
    assert await _retailers(client) == before


# --- the description and schema say so ---------------------------------------


async def test_the_schema_offers_both_fields_and_requires_neither():
    """The tool enforces "exactly one", which a JSON schema of optional fields
    cannot express — so the description has to say it, and name where an id
    comes from."""
    async with Client(mcp) as mcp_client:
        tools = {t.name: t for t in await mcp_client.list_tools()}
    schema = tools["create_order"].input_schema
    assert {"retailer", "retailer_id"} <= set(schema["properties"])
    assert "retailer" not in schema["required"]
    assert "retailer_id" not in schema["required"]
    description = " ".join((tools["create_order"].description or "").split())
    assert "exactly one of `retailer_id`" in description
    assert "list_retailers" in description and "list_retailers" in tools
    assert "an id passed as `retailer` is refused" in description
