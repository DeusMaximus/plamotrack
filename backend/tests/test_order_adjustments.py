"""What came off an order's price (#350), through every writer.

An adjustment is a discount, a promo code, a voucher or a gift card applied to an
order: a label and a positive amount in the order's own currency. Line prices stay
what the shop charged, and what was paid is derived (`services/order_totals.py`).

One rule holds the set together: an order's adjustments never come to more than
its lines in the order's currency plus its shipping. It is not a rule about
adjustments. A cheaper line, a removed line, a dropped shipping cost and a changed
order currency break it just as well, so it is asked of the order as it will be
stored, by REST and MCP in the service and by the CSV importer in its preview
(rule 1: three writers, one predicate). The matrix near the end drives one edit
through both and fails when only one of them answers.

Refusals are paired with the neighbour that is allowed — the same edit at exactly
the ceiling — because a refusal on its own proves only that something said no.
"""

import io
import json
import uuid
import zipfile

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import text as sa_text

from app.db import session_scope
from app.mcp import mcp
from app.services import order_totals
from app.services.portability import spec
from tests.diag import codes
from tests.test_order_invariants import archive, sheet
from tests.test_order_lifecycle import consumable_line, kit_line, make_consumable, make_order
from tests.test_portability import actions, apply, preview, read_archive

pytestmark = pytest.mark.anyio

OVERRUN = "order.adjustments_exceed_total"
GIFT_CARD = {"label": "Amazon gift card", "amount_minor": 3388}


def demi_trainer(price: int = 2475) -> dict:
    return kit_line(quantity=1, name="HG Demi Trainer") | {"unit_price_minor": price}


def dilanza(price: int = 2650) -> dict:
    return kit_line(quantity=1, name="HG Dilanza Standard Type") | {"unit_price_minor": price}


async def _create_rest(client, retailer, items, **extra) -> dict:
    return await make_order(client, retailer, items, **extra)


async def _create_mcp(client, retailer, items, **extra) -> dict:
    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "create_order",
            {
                "order_date": "2026-08-01",
                "retailer_id": retailer["id"],
                "currency_code": "AUD",
                "items": items,
                **extra,
            },
        )
    return result.data


async def _update_rest(client, order_id: str, changes: dict) -> dict:
    resp = await client.patch(f"/orders/{order_id}", json=changes)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _update_mcp(client, order_id: str, changes: dict) -> dict:
    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool(
            "update_order",
            {"order_id": order_id, "changes": changes, "remove_missing_lines": True},
        )
    return result.data


CREATES = [pytest.param(_create_rest, id="REST"), pytest.param(_create_mcp, id="MCP")]
UPDATES = [pytest.param(_update_rest, id="REST"), pytest.param(_update_mcp, id="MCP")]


async def _stored(client, order_id: str) -> dict:
    """Read back, not the write's own response: what was stored is the question."""
    resp = await client.get(f"/orders/{order_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _said(order: dict) -> list[tuple[str, int]]:
    return [(entry["label"], entry["amount_minor"]) for entry in order["adjustments"]]


def _total(order: dict, currency: str = "AUD") -> dict:
    [total] = [entry for entry in order["totals"] if entry["currency_code"] == currency]
    return total


def _restated(line: dict, **overrides) -> dict:
    payload = {
        "id": line["id"],
        "item_type": line["item_type"],
        "quantity": line["quantity"],
        "unit_price_minor": line["unit_price_minor"],
        "currency_code": line["currency_code"],
    }
    if line["item_type"] not in ("kit", "other"):
        payload["catalog_ref_id"] = line["catalog_ref_id"]
    payload.update(overrides)
    return payload


async def _adjustment_rows() -> int:
    async with session_scope() as session:
        return await session.scalar(sa_text("SELECT count(*) FROM order_adjustments"))


# --- the totals, as a rule on bare numbers --------------------------------------------


def _order(currency: str, shipping: int | None, lines: list, adjustments: list) -> dict:
    return dict(
        currency_code=currency, shipping_cost_minor=shipping, lines=lines, adjustments=adjustments
    )


def _totals(**order) -> list[tuple[str, int, int, int, int]]:
    return [
        (t.currency_code, t.items_minor, t.shipping_minor, t.adjustments_minor, t.paid_minor)
        for t in order_totals.totals(**order)
    ]


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        pytest.param(
            _order("AUD", 0, [("AUD", 1, 2475), ("AUD", 1, 2650)], [3388]),
            [("AUD", 5125, 0, 3388, 1737)],
            id="the issue's own receipt",
        ),
        pytest.param(
            _order("AUD", None, [("AUD", 3, 100)], []),
            [("AUD", 300, 0, 0, 300)],
            id="no shipping recorded, no adjustments",
        ),
        pytest.param(
            _order("AUD", 995, [("AUD", 2, 1000)], [500, 250]),
            [("AUD", 2000, 995, 750, 2245)],
            id="two adjustments and shipping",
        ),
        pytest.param(
            _order("AUD", 1500, [("JPY", 2, 3000), ("AUD", 1, 400), ("JPY", 1, 500)], [900]),
            [("JPY", 6500, 0, 0, 6500), ("AUD", 400, 1500, 900, 1000)],
            id="two currencies: shipping and adjustments are the order's",
        ),
        pytest.param(
            _order("AUD", 1500, [("JPY", 1, 3000)], []),
            [("JPY", 3000, 0, 0, 3000), ("AUD", 0, 1500, 0, 1500)],
            id="the order's currency joins for its shipping alone",
        ),
        pytest.param(
            _order("AUD", 0, [("JPY", 1, 3000)], []),
            [("JPY", 3000, 0, 0, 3000)],
            id="free post adds no currency",
        ),
        pytest.param(
            _order("AUD", None, [], []),
            [],
            id="nothing at all",
        ),
    ],
)
def test_totals_per_currency(order, expected):
    assert _totals(**order) == expected


@pytest.mark.parametrize(
    ("order", "overrun"),
    [
        pytest.param(
            _order("AUD", 500, [("AUD", 2, 1000)], [2500]),
            None,
            id="exactly the ceiling: paid nothing",
        ),
        pytest.param(
            _order("AUD", 500, [("AUD", 2, 1000)], [2501]),
            ("AUD", 2501, 2500),
            id="one past it",
        ),
        pytest.param(
            _order("AUD", 500, [("AUD", 2, 1000)], [2000, 501]),
            ("AUD", 2501, 2500),
            id="two that pass it together",
        ),
        pytest.param(
            _order("AUD", None, [("AUD", 1, 100)], [101]),
            ("AUD", 101, 100),
            id="no shipping to count",
        ),
        pytest.param(
            _order("AUD", 500, [("JPY", 9, 9000)], [501]),
            ("AUD", 501, 500),
            id="lines in another currency do not count",
        ),
        pytest.param(
            _order("AUD", None, [("JPY", 9, 9000)], [1]),
            ("AUD", 1, 0),
            id="nothing in the order's currency at all",
        ),
        pytest.param(
            _order("AUD", None, [], []),
            None,
            id="no adjustments, nothing to exceed",
        ),
    ],
)
def test_the_ceiling_on_bare_numbers(order, overrun):
    found = order_totals.adjustment_overrun(**order)
    if overrun is None:
        assert found is None
    else:
        assert (found.currency_code, found.adjustments_minor, found.ceiling_minor) == overrun


# --- entry ----------------------------------------------------------------------------


@pytest.mark.parametrize("create", CREATES)
async def test_an_order_records_what_came_off_and_what_was_paid(client, retailer, create):
    """The issue's own receipt: two kits at shelf price, a gift card against the
    order, and the line prices exactly as the shop charged them."""
    created = await create(
        client,
        retailer,
        [demi_trainer(), dilanza()],
        shipping_cost_minor=0,
        adjustments=[GIFT_CARD],
    )
    for order in (created, await _stored(client, created["id"])):
        assert _said(order) == [("Amazon gift card", 3388)]
        assert order["adjustments"][0]["id"]
        assert order["totals"] == [
            {
                "currency_code": "AUD",
                "items_minor": 5125,
                "shipping_minor": 0,
                "adjustments_minor": 3388,
                "paid_minor": 1737,
            }
        ]
        assert sorted(item["unit_price_minor"] for item in order["items"]) == [2475, 2650]
    [listed] = (await client.get("/orders")).json()
    assert listed["totals"] == created["totals"]


@pytest.mark.parametrize("create", CREATES)
async def test_an_order_without_adjustments_paid_its_lines_and_shipping(client, retailer, create):
    """The control: the field is there, empty, and the total is what it always was."""
    order = await create(client, retailer, [demi_trainer()], shipping_cost_minor=995)
    assert order["adjustments"] == []
    assert _total(order) == {
        "currency_code": "AUD",
        "items_minor": 2475,
        "shipping_minor": 995,
        "adjustments_minor": 0,
        "paid_minor": 3470,
    }


@pytest.mark.parametrize("create", CREATES)
async def test_adjustments_keep_the_order_they_were_given_in(client, retailer, create):
    """Not alphabetical, not by size: a promo code then a gift card stays that way."""
    given = [
        {"label": "Zed promo", "amount_minor": 100},
        {"label": "Alpha gift card", "amount_minor": 900},
        {"label": "Middle voucher", "amount_minor": 500},
    ]
    order = await create(client, retailer, [demi_trainer()], adjustments=given)
    expected = [("Zed promo", 100), ("Alpha gift card", 900), ("Middle voucher", 500)]
    assert _said(order) == expected
    assert _said(await _stored(client, order["id"])) == expected
    assert _total(order)["paid_minor"] == 2475 - 1500


@pytest.mark.parametrize("create", CREATES)
async def test_a_label_is_stored_without_its_surrounding_whitespace(client, retailer, create):
    order = await create(
        client,
        retailer,
        [demi_trainer()],
        adjustments=[{"label": "  SPRING10\t", "amount_minor": 1}],
    )
    assert _said(await _stored(client, order["id"])) == [("SPRING10", 1)]


MISSHAPEN = [
    pytest.param({"label": "", "amount_minor": 100}, "label", id="empty label"),
    pytest.param({"label": "   ", "amount_minor": 100}, "label", id="blank label"),
    pytest.param({"label": None, "amount_minor": 100}, "label", id="null label"),
    pytest.param({"amount_minor": 100}, "label", id="no label"),
    pytest.param({"label": 7, "amount_minor": 100}, "label", id="a number for a label"),
    pytest.param({"label": "Gift card", "amount_minor": 0}, "amount_minor", id="zero"),
    pytest.param({"label": "Gift card", "amount_minor": -5}, "amount_minor", id="negative"),
    pytest.param({"label": "Gift card", "amount_minor": True}, "amount_minor", id="a boolean"),
    pytest.param({"label": "Gift card", "amount_minor": None}, "amount_minor", id="null amount"),
    pytest.param({"label": "Gift card"}, "amount_minor", id="no amount"),
    pytest.param(
        {"label": "Gift card", "amount_minor": 2_147_483_648}, "amount_minor", id="past int4"
    ),
    pytest.param({"label": "Gift card", "amount_minor": 10.5}, "amount_minor", id="a fraction"),
]


@pytest.mark.parametrize(("adjustment", "field"), MISSHAPEN)
async def test_rest_refuses_a_misshapen_adjustment(http_client, retailer, adjustment, field):
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [demi_trainer()],
            "adjustments": [adjustment],
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "request.validation"
    [finding] = body["detail"]
    assert finding["loc"] == ["body", "adjustments", 0, field], finding
    assert (await http_client.get("/orders")).json() == []


@pytest.mark.parametrize(("adjustment", "field"), MISSHAPEN)
async def test_mcp_refuses_the_same_adjustments(client, retailer, adjustment, field):
    """Named by its field: a ToolError alone is also what an unknown argument
    earns, which is how every one of these read before the argument existed."""
    with pytest.raises(ToolError) as refusal:
        await _create_mcp(client, retailer, [demi_trainer()], adjustments=[adjustment])
    assert f"adjustments.0.{field}" in str(refusal.value)
    assert (await client.get("/orders")).json() == []


# --- the ceiling at entry ---------------------------------------------------------------

#: `(lines, extra, the most that may come off)`.
CEILINGS = [
    pytest.param(lambda ref: [demi_trainer()], {}, 2475, id="lines alone, no shipping recorded"),
    pytest.param(lambda ref: [demi_trainer()], {"shipping_cost_minor": 0}, 2475, id="free post"),
    pytest.param(
        lambda ref: [demi_trainer(), dilanza()],
        {"shipping_cost_minor": 995},
        6120,
        id="two lines and shipping",
    ),
    pytest.param(
        lambda ref: [
            demi_trainer(),
            {
                "item_type": "other",
                "quantity": 2,
                "unit_price_minor": 350,
                "currency_code": "AUD",
                "description": "Carry bag",
            },
            consumable_line(ref, quantity=3),
        ],
        {},
        2475 + 700 + 1950,
        id="an other line and a catalog line count like any line",
    ),
    pytest.param(
        lambda ref: [demi_trainer() | {"currency_code": "JPY"}],
        {"shipping_cost_minor": 500},
        500,
        id="a yen line on a dollar order counts for nothing",
    ),
]


@pytest.mark.parametrize("create", CREATES)
@pytest.mark.parametrize(("lines", "extra", "ceiling"), CEILINGS)
async def test_adjustments_may_come_to_exactly_what_was_charged(
    client, retailer, create, lines, extra, ceiling
):
    marker = await make_consumable(client)
    order = await create(
        client,
        retailer,
        lines(marker["id"]),
        adjustments=[{"label": "Gift card", "amount_minor": ceiling}],
        **extra,
    )
    assert _total(await _stored(client, order["id"]))["paid_minor"] == 0


@pytest.mark.parametrize(("lines", "extra", "ceiling"), CEILINGS)
async def test_rest_refuses_adjustments_past_what_was_charged(
    http_client, retailer, lines, extra, ceiling
):
    marker = await make_consumable(http_client)
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": lines(marker["id"]),
            # Two that pass it only together, so the rule is the sum.
            "adjustments": [
                {"label": "Promo", "amount_minor": 1},
                {"label": "Gift card", "amount_minor": ceiling},
            ],
            **extra,
        },
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == OVERRUN
    assert body["params"] == {
        "currency_code": "AUD",
        "adjustments_minor": ceiling + 1,
        "ceiling_minor": ceiling,
    }
    # One transaction: the order, its kits and its adjustments all went with it.
    assert (await http_client.get("/orders")).json() == []
    assert (await http_client.get("/kits")).json() == []
    assert await _adjustment_rows() == 0


async def test_mcp_refuses_adjustments_past_what_was_charged(client, retailer):
    with pytest.raises(ToolError) as refusal:
        await _create_mcp(
            client,
            retailer,
            [demi_trainer()],
            adjustments=[{"label": "Gift card", "amount_minor": 2476}],
        )
    assert "2476 AUD" in str(refusal.value) and "more than the 2475" in str(refusal.value)
    assert (await client.get("/orders")).json() == []


async def test_the_default_order_currency_is_the_one_adjustments_are_in(client, retailer):
    """MCP may omit the order's currency, which then is the instance's reference
    currency: the ceiling is asked in that one, not in whatever the lines say."""
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError) as refusal:
            await mcp_client.call_tool(
                "create_order",
                {
                    "order_date": "2026-08-01",
                    "retailer_id": retailer["id"],
                    "items": [demi_trainer() | {"currency_code": "JPY"}],
                    "adjustments": [{"label": "Gift card", "amount_minor": 1}],
                },
            )
    assert "1 AUD" in str(refusal.value)


# --- edits ------------------------------------------------------------------------------


async def _with_gift_card(client, retailer, **extra) -> dict:
    return await make_order(
        client,
        retailer,
        [demi_trainer(), dilanza()],
        adjustments=[{"label": "Promo", "amount_minor": 500}, GIFT_CARD],
        **extra,
    )


@pytest.mark.parametrize("update", UPDATES)
@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"order_number": "A-1"}, id="omitted"),
        pytest.param({"order_number": "A-1", "adjustments": None}, id="null"),
    ],
)
async def test_an_edit_that_does_not_state_adjustments_leaves_them(
    client, retailer, update, changes
):
    order = await _with_gift_card(client, retailer)
    await update(client, order["id"], changes)
    after = await _stored(client, order["id"])
    assert after["order_number"] == "A-1"
    assert after["adjustments"] == order["adjustments"]


@pytest.mark.parametrize("update", UPDATES)
async def test_a_stated_list_is_the_whole_set(client, retailer, update):
    order = await _with_gift_card(client, retailer)
    replacement = [
        {"label": "Store credit", "amount_minor": 1000},
        {"label": "Promo", "amount_minor": 250},
        {"label": "Loyalty points", "amount_minor": 75},
    ]
    updated = await update(client, order["id"], {"adjustments": replacement})
    expected = [("Store credit", 1000), ("Promo", 250), ("Loyalty points", 75)]
    for read in (updated, await _stored(client, order["id"])):
        assert _said(read) == expected
        assert _total(read)["adjustments_minor"] == 1325
        assert _total(read)["paid_minor"] == 5125 - 1325
    assert await _adjustment_rows() == 3


@pytest.mark.parametrize("update", UPDATES)
async def test_an_empty_list_removes_them_all(client, retailer, update):
    order = await _with_gift_card(client, retailer)
    updated = await update(client, order["id"], {"adjustments": []})
    assert updated["adjustments"] == []
    assert _total(await _stored(client, order["id"]))["paid_minor"] == 5125
    assert await _adjustment_rows() == 0


@pytest.mark.parametrize("update", UPDATES)
async def test_restating_the_stored_set_writes_nothing(client, retailer, update):
    """An editor that sends back what it loaded keeps the rows, ids and all, so
    the next export is the last one (rule 10)."""
    order = await _with_gift_card(client, retailer)
    restated = [{"label": label, "amount_minor": amount} for label, amount in _said(order)]
    await update(client, order["id"], {"adjustments": restated})
    assert (await _stored(client, order["id"]))["adjustments"] == order["adjustments"]
    # The control: the same two, the other way round, is a change.
    await update(client, order["id"], {"adjustments": restated[::-1]})
    assert _said(await _stored(client, order["id"])) == _said(order)[::-1]


async def test_an_edit_refuses_a_misshapen_adjustment(http_client, retailer):
    order = await _with_gift_card(http_client, retailer)
    resp = await http_client.patch(
        f"/orders/{order['id']}", json={"adjustments": [{"label": " ", "amount_minor": 5}]}
    )
    assert resp.status_code == 422, resp.text
    [finding] = resp.json()["detail"]
    assert finding["loc"] == ["body", "adjustments", 0, "label"]
    assert (await _stored(http_client, order["id"]))["adjustments"] == order["adjustments"]


async def test_receiving_shipping_and_deleting_carry_the_adjustments(client, retailer):
    marker = await make_consumable(client)
    order = await make_order(
        client,
        retailer,
        [demi_trainer(), consumable_line(marker["id"], quantity=2)],
        adjustments=[GIFT_CARD],
    )
    shipped = (await client.post(f"/orders/{order['id']}/ship")).json()
    received = (await client.post(f"/orders/{order['id']}/receive")).json()
    for read in (shipped, received):
        assert read["adjustments"] == order["adjustments"]
        assert read["totals"] == order["totals"]
    # An adjustment is money, never stock: the receipt applied the line's two.
    stocked = (await client.get("/consumables")).json()
    assert [row["quantity_on_hand"] for row in stocked] == [2]
    # ... and an edit to them on a received order moves none of it.
    await _update_rest(client, order["id"], {"adjustments": []})
    assert [row["quantity_on_hand"] for row in (await client.get("/consumables")).json()] == [2]

    await _update_rest(client, order["id"], {"adjustments": [GIFT_CARD]})
    assert await _adjustment_rows() == 1
    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    assert await _adjustment_rows() == 0


# --- the ceiling on an edit: one edit, three writers --------------------------------------
#
# The stored order is two AUD kit lines (2475 + 2650), 500 shipping, and a 500
# promo beside a 3388 gift card: 3888 off a ceiling of 5625. Each scenario is one
# edit to it, said twice — as a PATCH (REST and MCP) and as rows of a CSV — and
# whether the order still holds afterwards. Both sides read the same table, so a
# rule only one of them enforces fails here.

LINES_TOTAL = 5125
SHIPPING = 500
STORED_OFF = 3888


def _cell(value) -> str:
    return "" if value is None else str(value)


def _sheet_rows(order: dict, table: str) -> list[dict]:
    """The stored order's rows of one table, as an export would write them."""
    if table == "orders":
        return [
            {
                "id": order["id"],
                "retailer_id": order["retailer_id"],
                "order_date": order["order_date"],
                "currency_code": order["currency_code"],
                "shipping_cost_minor": _cell(order["shipping_cost_minor"]),
            }
        ]
    if table == "order_items":
        return [
            {
                "id": line["id"],
                "order_id": order["id"],
                "item_type": line["item_type"],
                "quantity": str(line["quantity"]),
                "unit_price_minor": str(line["unit_price_minor"]),
                "currency_code": line["currency_code"],
            }
            for line in order["items"]
        ]
    return [
        {
            "id": entry["id"],
            "order_id": order["id"],
            "label": entry["label"],
            "amount_minor": str(entry["amount_minor"]),
            "position": str(position),
        }
        for position, entry in enumerate(order["adjustments"])
    ]


def _line_edit(index: int, **changes):
    """One stored line restated with `changes`, for both writers."""

    def rest(order: dict) -> dict:
        lines = [_restated(line) for line in order["items"]]
        lines[index].update(changes)
        return {"items": lines}

    def csv_rows(order: dict) -> dict[str, list[dict]]:
        rows = _sheet_rows(order, "order_items")
        rows[index].update({key: str(value) for key, value in changes.items()})
        return {"order_items": rows}

    return rest, csv_rows


def _header_edit(**changes):
    def rest(order: dict) -> dict:
        return dict(changes)

    def csv_rows(order: dict) -> dict[str, list[dict]]:
        rows = _sheet_rows(order, "orders")
        rows[0].update({key: "" if value is None else str(value) for key, value in changes.items()})
        return {"orders": rows}

    return rest, csv_rows


def _adjustment_edit(index: int, amount: int):
    def rest(order: dict) -> dict:
        entries = [{"label": label, "amount_minor": minor} for label, minor in _said(order)]
        entries[index]["amount_minor"] = amount
        return {"adjustments": entries}

    def csv_rows(order: dict) -> dict[str, list[dict]]:
        rows = _sheet_rows(order, "order_adjustments")
        rows[index]["amount_minor"] = str(amount)
        return {"order_adjustments": rows}

    return rest, csv_rows


def _both(*edits):
    """Several edits in one request, and in one upload."""

    def rest(order: dict) -> dict:
        merged: dict = {}
        for edit_rest, _ in edits:
            merged.update(edit_rest(order))
        return merged

    def csv_rows(order: dict) -> dict[str, list[dict]]:
        merged: dict[str, list[dict]] = {}
        for _, edit_csv in edits:
            merged.update(edit_csv(order))
        return merged

    return rest, csv_rows


#: `(edit, the tables whose rows the importer refuses, or None when it holds)`.
#: The importer blames the adjustment rows an upload writes, since those are what
#: the sheet can lower; with none, every order or line row whose change brought
#: the ceiling down.
EDITS = [
    # The adjustments themselves.
    pytest.param(_adjustment_edit(1, 5125), None, id="gift card up to the ceiling"),
    pytest.param(_adjustment_edit(1, 5126), "order_adjustments", id="gift card one past it"),
    pytest.param(_adjustment_edit(0, 2238), "order_adjustments", id="the other one, past it"),
    # A line: the adjustments are not mentioned, and are what no longer fits.
    pytest.param(_line_edit(0, unit_price_minor=738), None, id="line down to the ceiling"),
    pytest.param(_line_edit(0, unit_price_minor=737), "order_items", id="line one below it"),
    pytest.param(_line_edit(1, unit_price_minor=0), "order_items", id="the other line, to zero"),
    pytest.param(_line_edit(0, unit_price_minor=9999), None, id="a dearer line"),
    pytest.param(_line_edit(0, currency_code="JPY"), "order_items", id="a line into yen"),
    # The header.
    pytest.param(_header_edit(shipping_cost_minor=0), None, id="free post still fits"),
    pytest.param(_header_edit(shipping_cost_minor=None), None, id="shipping cleared still fits"),
    pytest.param(_header_edit(currency_code="JPY"), "orders", id="the order into yen"),
    # Two together: the order as it lands is what is asked.
    pytest.param(
        _both(_line_edit(0, unit_price_minor=0), _adjustment_edit(1, 2650)),
        None,
        id="a line to zero with the gift card lowered to match",
    ),
    pytest.param(
        _both(_line_edit(0, unit_price_minor=9000), _adjustment_edit(1, 9000)),
        None,
        id="a dearer line with a larger gift card",
    ),
    pytest.param(
        _both(_line_edit(0, unit_price_minor=9000), _adjustment_edit(1, 11651)),
        "order_adjustments",
        id="a dearer line with a gift card past even that",
    ),
    # The adjustments are in the upload and say nothing new: the row that changed
    # is the one refused, not the rows that only restate what is stored.
    pytest.param(
        _both(_line_edit(0, unit_price_minor=737), _adjustment_edit(1, 3388)),
        "order_items",
        id="a line one below it, beside adjustments restated as they are",
    ),
    pytest.param(
        _both(_header_edit(shipping_cost_minor=0), _line_edit(0, unit_price_minor=1238)),
        None,
        id="free post and a cheaper line, to the ceiling",
    ),
    pytest.param(
        _both(_header_edit(shipping_cost_minor=0), _line_edit(0, unit_price_minor=1237)),
        "orders+order_items",
        id="free post and a cheaper line, one below",
    ),
]


async def _matrix_order(client, retailer) -> dict:
    order = await _with_gift_card(client, retailer, shipping_cost_minor=SHIPPING)
    assert _total(order)["paid_minor"] == LINES_TOTAL + SHIPPING - STORED_OFF
    return order


@pytest.mark.parametrize("via", ["REST", "MCP"])
@pytest.mark.parametrize(("edit", "refused_in"), EDITS)
async def test_the_ceiling_holds_through_an_edit(http_client, retailer, via, edit, refused_in):
    rest, _ = edit
    order = await _matrix_order(http_client, retailer)
    changes = rest(order)
    if via == "REST":
        resp = await http_client.patch(f"/orders/{order['id']}", json=changes)
        refused = resp.status_code == 422
        if refused:
            assert resp.json()["code"] == OVERRUN, resp.text
        else:
            assert resp.status_code == 200, resp.text
    else:
        try:
            await _update_mcp(http_client, order["id"], changes)
            refused = False
        except ToolError as refusal:
            assert "adjustments come to" in str(refusal), refusal
            refused = True
    assert refused is (refused_in is not None)
    after = await _stored(http_client, order["id"])
    if refused:
        assert after == order
    else:
        assert after != order
        assert _total(after)["paid_minor"] >= 0


@pytest.mark.parametrize("via", ["REST", "MCP"])
async def test_removing_a_line_is_refused_while_the_adjustments_no_longer_fit(
    http_client, retailer, via
):
    """The one way down the importer has no counterpart for: a merge never deletes
    a line, and an edit that leaves one out does. The order is left with 2650 of
    lines and 500 shipping under 3888 of adjustments. Its kit is still there
    afterwards: the refusal undid the removal with everything else."""
    order = await _matrix_order(http_client, retailer)
    keep = next(line for line in order["items"] if line["unit_price_minor"] == 2650)
    changes = {"items": [_restated(keep)]}
    if via == "REST":
        resp = await http_client.patch(f"/orders/{order['id']}", json=changes)
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == OVERRUN
        assert resp.json()["params"]["ceiling_minor"] == 2650 + SHIPPING
    else:
        with pytest.raises(ToolError) as refusal:
            await _update_mcp(http_client, order["id"], changes)
        assert f"more than the {2650 + SHIPPING}" in str(refusal.value)
    assert await _stored(http_client, order["id"]) == order
    assert len((await http_client.get("/kits")).json()) == 2

    # The control: the same removal with the adjustments brought down to fit.
    fits = changes | {"adjustments": [{"label": "Gift card", "amount_minor": 2650 + SHIPPING}]}
    after = await (_update_rest if via == "REST" else _update_mcp)(http_client, order["id"], fits)
    assert len(after["items"]) == 1
    assert _total(after)["paid_minor"] == 0
    assert len((await http_client.get("/kits")).json()) == 1


@pytest.mark.parametrize(("edit", "refused_in"), EDITS)
async def test_the_ceiling_holds_through_an_import(client, retailer, edit, refused_in):
    _, csv_rows = edit
    order = await _matrix_order(client, retailer)
    tables = csv_rows(order)
    upload = archive(headers={table: list(rows[0]) for table, rows in tables.items()}, **tables)
    plan = await preview(client, upload)
    refusals = {
        entry["table"]: [codes(row["errors"]) for row in entry["rows"] if row["errors"]]
        for entry in plan["tables"]
    }
    refusals = {table: found for table, found in refusals.items() if found}
    applied = await apply(client, upload)
    after = await _stored(client, order["id"])
    if refused_in is None:
        assert refusals == {}, refusals
        assert applied.status_code == 200, applied.text
        assert after != order
        assert _total(after)["paid_minor"] >= 0
    else:
        # Only the rows that could have caused it, and each by this rule alone.
        assert set(refusals) == set(refused_in.split("+")), refusals
        for found in refusals.values():
            assert all(row == [OVERRUN] for row in found), refusals
        assert applied.status_code == 409, applied.text
        assert applied.json()["code"] == "import.blocked"
        assert after == order


# --- export and import ------------------------------------------------------------------

ADJUSTMENTS_HEADER = ["id", "order_id", "label", "amount_minor", "position"]


async def test_the_archive_carries_the_adjustments_and_reads_back_as_no_change(client, retailer):
    order = await _with_gift_card(client, retailer)
    await make_order(client, retailer, [demi_trainer()], order_number="NO-ADJ")
    content = (await client.get("/export/archive")).content
    rows = read_archive(content)["order_adjustments"]
    assert list(rows[0]) == ADJUSTMENTS_HEADER == spec.ORDER_ADJUSTMENTS.header
    assert [
        (row["order_id"], row["label"], row["amount_minor"], row["position"]) for row in rows
    ] == [
        (order["id"], "Promo", "500", "0"),
        (order["id"], "Amazon gift card", "3388", "1"),
    ]
    assert [row["id"] for row in rows] == [entry["id"] for entry in order["adjustments"]]

    plan = await preview(client, content)
    assert actions(plan, "order_adjustments") == ["unchanged", "unchanged"], plan["tables"]
    assert (await apply(client, content)).status_code == 200
    assert (await _stored(client, order["id"])) == order


async def test_a_restore_brings_the_adjustments_back_in_order(client, retailer):
    order = await _with_gift_card(client, retailer)
    content = (await client.get("/export/archive")).content
    await _update_rest(client, order["id"], {"adjustments": []})
    assert await _adjustment_rows() == 0

    restored = await apply(client, content, mode="replace_all", confirm="REPLACE")
    assert restored.status_code == 200, restored.text
    after = await _stored(client, order["id"])
    assert after["adjustments"] == order["adjustments"]
    assert after["totals"] == order["totals"]


async def test_an_upload_without_the_file_leaves_stored_adjustments_alone(client, retailer):
    """A partial archive, or one written before the file existed: silence about
    adjustments is not an instruction to remove them."""
    order = await _with_gift_card(client, retailer)
    upload = archive(
        headers={"orders": list(_sheet_rows(order, "orders")[0])},
        orders=_sheet_rows(order, "orders"),
    )
    assert (await apply(client, upload)).status_code == 200
    assert (await _stored(client, order["id"]))["adjustments"] == order["adjustments"]


async def test_a_hand_written_row_needs_no_id_and_is_not_added_twice(client, retailer):
    order = await make_order(client, retailer, [demi_trainer()])
    upload = sheet(
        "order_adjustments",
        ["order_id", "label", "amount_minor"],
        [{"order_id": order["id"], "label": "  Gift card ", "amount_minor": "1000"}],
    )
    plan = await preview(client, upload, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["create"], plan["tables"]
    assert (await apply(client, upload, filename="order_adjustments.csv")).status_code == 200
    after = await _stored(client, order["id"])
    assert _said(after) == [("Gift card", 1000)]
    assert _total(after)["paid_minor"] == 1475

    # The same sheet again describes the row it made: that label on that order.
    plan = await preview(client, upload, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["unchanged"], plan["tables"]

    # In whatever case it is typed, and with its amount corrected: still that
    # row, updated, never a second deduction beside the first.
    again = sheet(
        "order_adjustments",
        ["order_id", "label", "amount_minor"],
        [{"order_id": order["id"], "label": "GIFT CARD", "amount_minor": "1200"}],
    )
    plan = await preview(client, again, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["update"], plan["tables"]
    assert (await apply(client, again, filename="order_adjustments.csv")).status_code == 200
    assert _said(await _stored(client, order["id"])) == [("GIFT CARD", 1200)]
    assert await _adjustment_rows() == 1


async def test_position_orders_them_and_blank_is_first(client, retailer):
    order = await make_order(client, retailer, [demi_trainer()])
    upload = sheet(
        "order_adjustments",
        ["order_id", "label", "amount_minor", "position"],
        [
            {"order_id": order["id"], "label": "Third", "amount_minor": "3", "position": "7"},
            {"order_id": order["id"], "label": "First", "amount_minor": "1", "position": ""},
            {"order_id": order["id"], "label": "Second", "amount_minor": "2", "position": "2"},
        ],
    )
    assert (await apply(client, upload, filename="order_adjustments.csv")).status_code == 200
    assert _said(await _stored(client, order["id"])) == [("First", 1), ("Second", 2), ("Third", 3)]


BAD_ROWS = [
    pytest.param({"label": ""}, "import.cell_required", id="blank label"),
    pytest.param({"amount_minor": ""}, "import.cell_required", id="blank amount"),
    pytest.param({"amount_minor": "0"}, "import.cell_below_minimum", id="zero"),
    pytest.param({"amount_minor": "-5"}, "import.cell_below_minimum", id="negative"),
    pytest.param({"amount_minor": "2147483648"}, None, id="past int4"),
    pytest.param({"amount_minor": "ten"}, "import.cell_invalid", id="not a number"),
    pytest.param({"position": "-1"}, "import.cell_below_minimum", id="negative position"),
    pytest.param(
        {"order_id": "00000000-0000-4000-8000-000000000000"},
        "import.ref_unmatched",
        id="an order that is not there",
    ),
    pytest.param({"order_id": ""}, "import.cell_required", id="no order"),
]


@pytest.mark.parametrize(("cells", "code"), BAD_ROWS)
async def test_the_importer_refuses_a_row_no_other_writer_would_take(client, retailer, cells, code):
    order = await make_order(client, retailer, [demi_trainer()])
    row = {"order_id": order["id"], "label": "Gift card", "amount_minor": "100", "position": "0"}
    upload = sheet("order_adjustments", list(row), [row | cells])
    plan = await preview(client, upload, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["error"], plan["tables"]
    [entry] = [e for e in plan["tables"] if e["table"] == "order_adjustments"]
    if code is not None:
        assert code in codes(entry["rows"][0]["errors"]), entry["rows"][0]["errors"]
    assert (await apply(client, upload, filename="order_adjustments.csv")).status_code == 409
    assert await _adjustment_rows() == 0

    # The control: the row these cells were laid over is one the importer takes.
    good = sheet("order_adjustments", list(row), [row])
    assert (await apply(client, good, filename="order_adjustments.csv")).status_code == 200
    assert await _adjustment_rows() == 1


async def test_two_alike_without_ids_are_asked_to_say_which(client, retailer):
    order = await make_order(client, retailer, [demi_trainer()])
    row = {"order_id": order["id"], "label": "Voucher", "amount_minor": "100"}
    upload = sheet("order_adjustments", list(row), [row, row])
    plan = await preview(client, upload, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["create", "error"], plan["tables"]
    [entry] = [e for e in plan["tables"] if e["table"] == "order_adjustments"]
    assert codes(entry["rows"][1]["errors"]) == ["import.natural_key_duplicated"]

    # A different amount under the same label is still the same claim on one row.
    upload = sheet("order_adjustments", list(row), [row, row | {"amount_minor": "150"}])
    plan = await preview(client, upload, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["create", "error"], plan["tables"]

    # The control: another label is another adjustment.
    upload = sheet("order_adjustments", list(row), [row, row | {"label": "Voucher 2"}])
    plan = await preview(client, upload, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["create", "create"], plan["tables"]


async def test_two_stored_under_one_label_need_an_id_to_be_named(client, retailer):
    """REST and MCP allow two adjustments with one label. An id-less row cannot
    say which of them it means, and is told so rather than guessed at."""
    order = await make_order(
        client,
        retailer,
        [demi_trainer()],
        adjustments=[
            {"label": "Voucher", "amount_minor": 100},
            {"label": "Voucher", "amount_minor": 200},
        ],
    )
    row = {"order_id": order["id"], "label": "Voucher", "amount_minor": "300"}
    plan = await preview(
        client, sheet("order_adjustments", list(row), [row]), filename="order_adjustments.csv"
    )
    [entry] = [e for e in plan["tables"] if e["table"] == "order_adjustments"]
    assert codes(entry["rows"][0]["errors"]) == ["import.match_ambiguous"]

    # With its id it is that one, and the other is left alone.
    named = row | {"id": order["adjustments"][1]["id"]}
    upload = sheet("order_adjustments", list(named), [named])
    assert (await apply(client, upload, filename="order_adjustments.csv")).status_code == 200
    assert _said(await _stored(client, order["id"])) == [("Voucher", 100), ("Voucher", 300)]


async def test_a_new_adjustment_is_judged_with_what_is_already_stored(client, retailer):
    """The sheet names one row. The rule is about all of the order's."""
    order = await make_order(
        client, retailer, [demi_trainer()], adjustments=[{"label": "Promo", "amount_minor": 2000}]
    )
    row = {"order_id": order["id"], "label": "Gift card", "amount_minor": "476"}
    over = sheet("order_adjustments", list(row), [row])
    plan = await preview(client, over, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["error"], plan["tables"]
    [entry] = [e for e in plan["tables"] if e["table"] == "order_adjustments"]
    [refusal] = entry["rows"][0]["errors"]
    assert refusal["code"] == OVERRUN
    assert refusal["params"] == {
        "currency_code": "AUD",
        "adjustments_minor": 2476,
        "ceiling_minor": 2475,
    }

    fits = sheet("order_adjustments", list(row), [row | {"amount_minor": "475"}])
    assert (await apply(client, fits, filename="order_adjustments.csv")).status_code == 200
    assert _total(await _stored(client, order["id"]))["paid_minor"] == 0


async def test_an_adjustment_moved_to_another_order_is_judged_there(client, retailer):
    big = await make_order(
        client, retailer, [dilanza()], adjustments=[{"label": "Gift card", "amount_minor": 2600}]
    )
    small = await make_order(client, retailer, [demi_trainer()], order_number="SMALL")
    [row] = _sheet_rows(big, "order_adjustments")
    moved = sheet("order_adjustments", list(row), [row | {"order_id": small["id"]}])
    plan = await preview(client, moved, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["error"], plan["tables"]

    fits = sheet(
        "order_adjustments", list(row), [row | {"order_id": small["id"], "amount_minor": "2475"}]
    )
    assert (await apply(client, fits, filename="order_adjustments.csv")).status_code == 200
    assert (await _stored(client, big["id"]))["adjustments"] == []
    assert _said(await _stored(client, small["id"])) == [("Gift card", 2475)]


async def test_an_adjustment_that_moved_away_no_longer_counts_where_it_was(client, retailer):
    """One upload moves an order's only adjustment off it and gives it a new one
    for the whole of its lines. That fits only if the one that left is not still
    counted there."""
    big = await make_order(
        client, retailer, [dilanza()], adjustments=[{"label": "Gift card", "amount_minor": 2600}]
    )
    small = await make_order(client, retailer, [demi_trainer()], order_number="SMALL")
    [row] = _sheet_rows(big, "order_adjustments")
    upload = sheet(
        "order_adjustments",
        list(row),
        [
            row | {"order_id": small["id"], "amount_minor": "2475"},
            {"order_id": big["id"], "label": "Store credit", "amount_minor": "2650"},
        ],
    )
    plan = await preview(client, upload, filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["update", "create"], plan["tables"]
    assert (await apply(client, upload, filename="order_adjustments.csv")).status_code == 200
    assert _said(await _stored(client, big["id"])) == [("Store credit", 2650)]
    assert _said(await _stored(client, small["id"])) == [("Gift card", 2475)]


@pytest.mark.parametrize(
    ("price", "refused"),
    # 3888 is off, and the other line is 2650: this one has to stay at 1238.
    [pytest.param("1238", False, id="fits"), pytest.param("1237", True, id="over")],
)
async def test_a_sheet_that_states_only_the_price_is_judged_on_the_stored_line(
    client, retailer, price, refused
):
    """A partial sheet: a line's id, its order and the one cell that changes. Its
    quantity and currency, which the rule also reads, are what is stored."""
    order = await _with_gift_card(client, retailer)
    line = next(item for item in order["items"] if item["unit_price_minor"] == 2475)
    upload = sheet(
        "order_items",
        ["id", "order_id", "unit_price_minor"],
        [{"id": line["id"], "order_id": order["id"], "unit_price_minor": price}],
    )
    plan = await preview(client, upload, filename="order_items.csv")
    assert actions(plan, "order_items") == ["error" if refused else "update"], plan["tables"]
    resp = await apply(client, upload, filename="order_items.csv")
    after = await _stored(client, order["id"])
    if refused:
        assert resp.status_code == 409, resp.text
        assert after == order
    else:
        assert resp.status_code == 200, resp.text
        assert _total(after)["paid_minor"] == 0


@pytest.mark.parametrize(
    ("amount", "refused"),
    # 5125 of lines, less the 500 promo that is also there.
    [
        pytest.param("3388", False, id="as stored"),
        pytest.param("4625", False, id="fits"),
        pytest.param("4626", True, id="over"),
    ],
)
async def test_an_archive_under_other_ids_is_judged_on_the_order_it_matches(
    client, retailer, amount, refused
):
    """An archive of the same collection from another instance: every id differs,
    and the order is matched by its retailer and number, its lines and adjustments
    by what they say. The rule has to follow the rows to the order they land on,
    not look for an order under an id that exists only in the file."""
    order = await _with_gift_card(client, retailer, order_number="FOREIGN-1")
    tables = read_archive((await client.get("/export/archive")).content)
    minted = [order["id"], *(row["id"] for row in order["items"] + order["adjustments"])]
    elsewhere = {here: str(uuid.uuid4()) for here in minted}

    def renamed(table: str) -> list[dict]:
        return [
            {column: elsewhere.get(cell, cell) for column, cell in row.items()}
            for row in tables[table]
        ]

    adjustments = renamed("order_adjustments")
    card = next(row for row in adjustments if row["label"] == "Amazon gift card")
    card["amount_minor"] = amount
    upload = archive(
        retailers=tables["retailers"],
        orders=renamed("orders"),
        order_items=renamed("order_items"),
        order_adjustments=adjustments,
    )
    plan = await preview(client, upload)
    resp = await apply(client, upload)
    after = await _stored(client, order["id"])
    if refused:
        assert "error" in actions(plan, "order_adjustments"), plan["tables"]
        assert resp.status_code == 409, resp.text
        assert after == order
    else:
        assert "error" not in actions(plan, "order_adjustments"), plan["tables"]
        assert resp.status_code == 200, resp.text
        # Landed on the stored order, which is still the only one, and on its two
        # stored adjustments: a corrected amount is not a third.
        assert len((await client.get("/orders")).json()) == 1
        assert _said(after) == [("Promo", 500), ("Amazon gift card", int(amount))]
        assert [entry["id"] for entry in after["adjustments"]] == [
            entry["id"] for entry in order["adjustments"]
        ]
        assert len(after["items"]) == 2


async def test_a_new_line_with_no_price_counts_for_nothing(client, retailer):
    """A hand-written line may leave its price out, and lands at zero. Beside a
    new adjustment in the same upload it adds nothing to the ceiling, and is
    not a number the rule trips over."""
    order = await make_order(client, retailer, [demi_trainer()])
    line = {
        "order_id": order["id"],
        "item_type": "other",
        "quantity": "3",
        "currency_code": "AUD",
        "description": "Free sticker sheet",
    }

    def upload(amount: str) -> bytes:
        return archive(
            headers={
                "order_items": list(line),
                "order_adjustments": ["order_id", "label", "amount_minor"],
            },
            order_items=[line],
            order_adjustments=[
                {"order_id": order["id"], "label": "Gift card", "amount_minor": amount}
            ],
        )

    plan = await preview(client, upload("2476"))
    assert actions(plan, "order_adjustments") == ["error"], plan["tables"]
    assert (await apply(client, upload("2475"))).status_code == 200
    after = await _stored(client, order["id"])
    assert sorted(item["unit_price_minor"] for item in after["items"]) == [0, 2475]
    assert _total(after)["paid_minor"] == 0


async def test_an_adjustment_on_an_order_the_upload_refused_is_not_a_crash(http_client, retailer):
    """The order row is refused for its own reason, so there is no order to judge
    its adjustment against. The answer is that row's refusal and the adjustment's
    own, for naming an order that will not exist, never a 500."""
    upload = archive(
        retailers=[{"id": retailer["id"], "name": retailer["name"]}],
        orders=[
            {
                "id": "11111111-1111-4111-8111-111111111111",
                "retailer_id": retailer["id"],
                "order_date": "not a date",
                "currency_code": "AUD",
            }
        ],
        order_adjustments=[
            {
                "order_id": "11111111-1111-4111-8111-111111111111",
                "label": "Gift card",
                "amount_minor": "100",
            }
        ],
    )
    for mode in ("merge", "replace_all"):
        resp = await http_client.post(
            "/import/preview",
            files={"file": ("archive.zip", upload, "application/octet-stream")},
            data={"mode": mode},
        )
        assert resp.status_code == 200, (mode, resp.text)
        assert actions(resp.json(), "orders") == ["error"], (mode, resp.json()["tables"])
        assert actions(resp.json(), "order_adjustments") == ["error"], (mode, resp.json())


@pytest.mark.parametrize(
    ("amount", "status"),
    [pytest.param("2475", 200, id="fits"), pytest.param("2476", 409, id="over")],
)
async def test_a_replace_all_archive_is_judged_against_itself(client, retailer, amount, status):
    """The database it replaces says nothing: here the stored order is far too
    small for either amount, and only the archive's own lines decide."""
    stored = await make_order(
        client,
        retailer,
        [demi_trainer(price=1)],
        # Gone with the rest of what is stored: it is not in the archive, and
        # counting it would put the amount that fits one over.
        adjustments=[{"label": "Old", "amount_minor": 1}],
    )
    upload = archive(
        retailers=[{"id": retailer["id"], "name": retailer["name"]}],
        orders=[
            {
                "id": stored["id"],
                "retailer_id": retailer["id"],
                "order_date": "2026-08-01",
                "currency_code": "AUD",
            }
        ],
        order_items=[
            {
                "id": stored["items"][0]["id"],
                "order_id": stored["id"],
                "item_type": "kit",
                "quantity": "1",
                "unit_price_minor": "2475",
                "currency_code": "AUD",
                "kit_name": "HG Demi Trainer",
                "kit_grade": "HG",
            }
        ],
        order_adjustments=[
            {
                "order_id": stored["id"],
                "label": "Gift card",
                "amount_minor": amount,
                "position": "0",
            }
        ],
    )
    resp = await apply(client, upload, mode="replace_all", confirm="REPLACE")
    assert resp.status_code == status, resp.text
    after = await _stored(client, stored["id"])
    if status == 200:
        assert _total(after)["paid_minor"] == 0
    else:
        assert after == stored


async def test_add_only_leaves_a_stored_adjustment_as_it_is(client, retailer):
    """A row add_only skips writes nothing, so it cannot break the rule: an
    amount that would be refused as an update is not even considered."""
    order = await _with_gift_card(client, retailer)
    rows = _sheet_rows(order, "order_adjustments")
    rows[1]["amount_minor"] = "999999"
    upload = sheet("order_adjustments", list(rows[0]), rows)
    plan = await preview(client, upload, mode="add_only", filename="order_adjustments.csv")
    assert actions(plan, "order_adjustments") == ["skip", "skip"], plan["tables"]
    resp = await apply(client, upload, mode="add_only", filename="order_adjustments.csv")
    assert resp.status_code == 200, resp.text
    assert (await _stored(client, order["id"])) == order


async def test_an_archive_from_before_adjustments_restores(client, retailer):
    """An archive written before the file existed has no such member and lists
    none in its manifest. A restore from one leaves the order with no adjustments
    and its lines as they were."""
    order = await _with_gift_card(client, retailer)
    content = (await client.get("/export/archive")).content
    older = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(older, "w") as target:
        for name in source.namelist():
            if name == "order_adjustments.csv":
                continue
            data = source.read(name)
            if name == "manifest.json":
                manifest = json.loads(data)
                assert manifest["tables"].pop("order_adjustments") == {
                    "file": "order_adjustments.csv",
                    "rows": 2,
                }
                data = json.dumps(manifest).encode()
            target.writestr(name, data)
    restored = await apply(client, older.getvalue(), mode="replace_all", confirm="REPLACE")
    assert restored.status_code == 200, restored.text
    after = await _stored(client, order["id"])
    assert after["adjustments"] == []
    assert _total(after)["paid_minor"] == 5125
    assert await _adjustment_rows() == 0
