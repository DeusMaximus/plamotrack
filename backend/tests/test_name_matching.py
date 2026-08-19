"""#49 — names are matched by equality after case-folding, never as LIKE patterns.

`get_or_create_retailer` (the MCP `create_order` path) matched with an unescaped
`ILIKE`, so a shop named `%` attached its order to whichever retailer sorted first,
and `_` matched any single character. `list_kits(grade=)` had the read-only twin.
The importer already compared `strip().lower()` for equality; these pin all three
surfaces to that one rule.

State matters here as much as values: with an *empty* retailer table, `%` creates a
retailer named `%` on the unfixed code too, and the test proves nothing. Every case
below that expects a *new* retailer seeds a decoy first, and asserts the decoy is
untouched as well as that the new row exists.
"""

import asyncio
import uuid

import pytest
from fastmcp import Client

from app.db import session_scope
from app.mcp import mcp
from app.services import orders

# --- helpers ---------------------------------------------------------------


async def _retailers(client) -> dict[str, dict]:
    return {r["name"]: r for r in (await client.get("/retailers")).json()}


def _order_payload(retailer: str) -> dict:
    return {
        "retailer": retailer,
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
    }


# --- retailer: the service, over the value space ---------------------------


@pytest.mark.parametrize(
    ("existing", "asked", "expect_reuse"),
    [
        # wildcards in the *input* are literal characters, not patterns
        ("Hobby Link Japan", "%", False),
        ("Hobby Link Japan", "_", False),  # creates `_`; a 16-char decoy can't be hit by `_`
        ("X", "_", False),  # a one-character decoy can — this is the `_` detector
        ("Hobby Link Japan", "Hobby%", False),
        ("Hobby Link Japan", "Hobby_Link Japan", False),  # `_` used to match the space
        ("Hobby Link Japan", "%Link%", False),
        # backslash is ILIKE's default escape: `A\B` used to match "AB"
        ("AB", "A\\B", False),
        # a retailer literally named with a wildcard round-trips to itself
        ("%", "%", True),
        ("A\\B", "A\\B", True),
        # what still has to work: case-folding and surrounding whitespace
        ("Hobby Link Japan", "HOBBY LINK JAPAN", True),
        ("Hobby Link Japan", "  hobby link japan  ", True),
        # and what deliberately does not: internal whitespace is significant
        ("Hobby Link Japan", "Hobby  Link Japan", False),
    ],
    ids=lambda v: repr(v) if isinstance(v, str) else str(v),
)
async def test_get_or_create_retailer_matches_by_equality(client, existing, asked, expect_reuse):
    seeded = (await client.post("/retailers", json={"name": existing})).json()

    async with session_scope() as session:
        row = await orders.get_or_create_retailer(session, asked)
        got_id, got_name = str(row.id), row.name

    if expect_reuse:
        assert got_id == seeded["id"], f"{asked!r} should have reused {existing!r}"
    else:
        assert got_id != seeded["id"], f"{asked!r} was matched against {existing!r}"
        assert got_name == asked.strip()
    # exactly the rows we expect, and the seeded one untouched either way
    names = await _retailers(client)
    assert names[existing]["id"] == seeded["id"]
    assert len(names) == (1 if expect_reuse else 2)


# --- retailer: the MCP path the issue names ----------------------------------


async def test_mcp_create_order_with_a_wildcard_name_does_not_attach_to_another_shop(client):
    """The reachable path: an agent names a shop `%` and, before the fix, the order
    silently belonged to whichever retailer sorted first."""
    decoy = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()

    async with Client(mcp) as mcp_client:
        order = (await mcp_client.call_tool("create_order", _order_payload("%"))).data

    assert order["retailer_id"] != decoy["id"]
    names = await _retailers(client)
    assert set(names) == {"Hobby Link Japan", "%"}
    assert order["retailer_id"] == names["%"]["id"]
    decoy_orders = [
        o for o in (await client.get("/orders")).json() if o["retailer_id"] == decoy["id"]
    ]
    assert decoy_orders == []


async def test_two_agents_naming_the_same_new_shop_at_once_create_it_once(client):
    """The check-then-insert is under the write gate (#80), so a race creates one
    retailer and both orders land on it. Pinned here because it is the other half
    of "select-or-create never fragments the retailer list" (rule 3)."""
    name = f"Race Shop {uuid.uuid4().hex[:6]}"

    async def attempt():
        async with Client(mcp) as mcp_client:
            return (await mcp_client.call_tool("create_order", _order_payload(name))).data

    first, second = await asyncio.gather(attempt(), attempt())
    assert first["retailer_id"] == second["retailer_id"]
    names = await _retailers(client)
    assert [n for n in names if n.startswith("Race Shop")] == [name]


# --- kits: the grade filter, REST and MCP ------------------------------------


@pytest.mark.parametrize(
    ("grade_filter", "expected"),
    [
        ("M_", ["literal-underscore"]),  # not MG
        ("M%", []),  # not MG / MSV
        ("%", []),  # not everything
        ("mg", ["mg-kit"]),  # case-folding kept
        ("MG", ["mg-kit"]),
    ],
)
async def test_list_kits_grade_filter_is_not_a_pattern(client, grade_filter, expected):
    for name, grade in [("mg-kit", "MG"), ("hg-kit", "HG"), ("literal-underscore", "M_")]:
        assert (await client.post("/kits", json={"name": name, "grade": grade})).status_code == 201

    rest = (await client.get("/kits", params={"grade": grade_filter})).json()
    assert [k["name"] for k in rest] == expected

    async with Client(mcp) as mcp_client:
        via_mcp = (await mcp_client.call_tool("list_kits", {"grade": grade_filter})).data
    assert [k["name"] for k in via_mcp] == expected
