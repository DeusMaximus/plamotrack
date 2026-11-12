import uuid

import pytest

from app.db import get_sessionmaker
from app.exceptions import InvalidInputError
from app.models import OrderItem
from app.services import orders


def kit_line(quantity: int = 1, status: str | None = None, **kit_overrides) -> dict:
    kit = {"name": "RX-79(G) Ground Type", "grade": "HG", "kit_number": "HGUC 210"}
    kit.update(kit_overrides)
    if status is not None:
        kit["status"] = status
    return {
        "item_type": "kit",
        "quantity": quantity,
        "unit_price_minor": 2800,
        "currency_code": "JPY",
        "kit": kit,
    }


async def test_kit_line_fans_out(client, retailer):
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "items": [kit_line(quantity=3)],
        },
    )
    assert resp.status_code == 201
    line = resp.json()["items"][0]
    assert line["catalog_ref_id"] is None
    assert len(line["spawned_kit_ids"]) == 3

    kits = (await client.get("/kits")).json()
    assert len(kits) == 3
    assert all(k["order_item_id"] == line["id"] for k in kits)
    assert all(k["status"] == "ordered" for k in kits)  # default for ordered kit lines
    assert all(k["scale"] == "1/144" for k in kits)  # derived from HG


async def test_kit_line_preorder_status(client, retailer):
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "items": [kit_line(status="pre_ordered")],
        },
    )
    assert resp.status_code == 201
    kits = (await client.get("/kits")).json()
    assert kits[0]["status"] == "pre_ordered"


async def test_pending_catalog_line_defers_increment(client, retailer):
    """Stock means 'physically on hand' — a pending order must not inflate it."""
    consumable = (
        await client.post(
            "/consumables",
            json={"name": "Gundam Marker GM02", "category": "paint", "quantity_on_hand": 2},
        )
    ).json()

    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "consumable",
                    "quantity": 5,
                    "unit_price_minor": 650,
                    "currency_code": "AUD",
                    "catalog_ref_id": consumable["id"],
                }
            ],
        },
    )
    assert resp.status_code == 201
    order = resp.json()
    assert order["received_at"] is None
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 2  # unchanged

    received = (await client.post(f"/orders/{order['id']}/receive")).json()
    assert received["received_at"] is not None
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 7  # 2 + 5


async def test_received_catalog_line_increments_immediately(client, retailer):
    consumable = (
        await client.post(
            "/consumables",
            json={"name": "Gundam Marker GM02", "category": "paint", "quantity_on_hand": 2},
        )
    ).json()

    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "received": True,
            "items": [
                {
                    "item_type": "consumable",
                    "quantity": 5,
                    "unit_price_minor": 650,
                    "currency_code": "AUD",
                    "catalog_ref_id": consumable["id"],
                }
            ],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["received_at"] is not None
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 7


async def test_catalog_line_new_item_creates_then_increments(client, retailer):
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "received": True,
            "items": [
                {
                    "item_type": "upgrade",
                    "quantity": 4,
                    "unit_price_minor": 1200,
                    "currency_code": "AUD",
                    "new_item": {"name": "G-Rework Decal Sheet #4", "manufacturer": "G-Rework"},
                }
            ],
        },
    )
    assert resp.status_code == 201

    upgrades = (await client.get("/upgrades")).json()
    assert len(upgrades) == 1
    assert upgrades[0]["quantity_on_hand"] == 4
    assert resp.json()["items"][0]["catalog_ref_id"] == upgrades[0]["id"]


async def test_pending_new_item_created_at_zero_stock(client, retailer):
    """Select-or-create still registers the catalog item, but stock waits for arrival."""
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "upgrade",
                    "quantity": 4,
                    "unit_price_minor": 1200,
                    "currency_code": "AUD",
                    "new_item": {"name": "G-Rework Decal Sheet #4", "manufacturer": "G-Rework"},
                }
            ],
        },
    )
    assert resp.status_code == 201
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 0


async def test_order_failure_rolls_back_everything(client, retailer):
    """A bad line anywhere must abort the whole order — no partial fan-out."""
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "items": [
                kit_line(quantity=2),
                {
                    "item_type": "consumable",
                    "quantity": 1,
                    "unit_price_minor": 500,
                    "currency_code": "JPY",
                    "catalog_ref_id": str(uuid.uuid4()),  # does not exist
                },
            ],
        },
    )
    assert resp.status_code == 404
    assert (await client.get("/kits")).json() == []
    assert (await client.get("/orders")).json() == []


async def test_kit_line_requires_kit_details(client, retailer):
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "items": [
                {
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 2800,
                    "currency_code": "JPY",
                }
            ],
        },
    )
    assert resp.status_code == 422


async def test_catalog_line_rejects_both_ref_and_new_item(client, retailer):
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
                    "unit_price_minor": 8000,
                    "currency_code": "AUD",
                    "catalog_ref_id": str(uuid.uuid4()),
                    "new_item": {"name": "Nippers", "category": "cutting"},
                }
            ],
        },
    )
    assert resp.status_code == 422


async def test_new_tool_requires_category(client, retailer):
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
                    "unit_price_minor": 8000,
                    "currency_code": "AUD",
                    "new_item": {"name": "Godhand SPN-120"},
                }
            ],
        },
    )
    assert resp.status_code == 422
    assert (await client.get("/tools")).json() == []


async def test_mixed_order(client, retailer):
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "shipping_cost_minor": 2400,
            "tracking_number": "EMS123456789JP",
            "items": [
                kit_line(quantity=2),
                {
                    "item_type": "consumable",
                    "quantity": 3,
                    "unit_price_minor": 300,
                    "currency_code": "JPY",
                    "new_item": {"name": "GodHand blade", "category": "blades"},
                },
            ],
        },
    )
    assert resp.status_code == 201
    order = resp.json()
    assert len(order["items"]) == 2

    fetched = (await client.get(f"/orders/{order['id']}")).json()
    kit_items = [i for i in fetched["items"] if i["item_type"] == "kit"]
    assert len(kit_items[0]["spawned_kit_ids"]) == 2


async def test_order_unknown_retailer_404(client):
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": str(uuid.uuid4()),
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "items": [kit_line()],
        },
    )
    assert resp.status_code == 404


# --- the per-line quantity ceiling (#43) -----------------------------------------


async def order_with(client, retailer, line: dict, **header):
    return await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "items": [line],
            **header,
        },
    )


@pytest.mark.parametrize(
    ("quantity", "accepted"),
    [
        pytest.param(orders.MAX_LINE_QUANTITY, True, id="exactly at the ceiling"),
        pytest.param(orders.MAX_LINE_QUANTITY + 1, False, id="one over"),
        pytest.param(2_000_000_000, False, id="absurd but a valid int4"),
    ],
)
async def test_a_kit_line_cannot_ask_for_more_kits_than_the_ceiling(
    client, retailer, quantity, accepted
):
    """`quantity` on a kit line is an insert count, not a number in a column — it
    is the one cell in the app that decides how many rows get written."""
    resp = await order_with(client, retailer, kit_line(quantity=quantity))

    if accepted:
        assert resp.status_code == 201, resp.text
        assert len(resp.json()["items"][0]["spawned_kit_ids"]) == quantity
    else:
        assert resp.status_code == 422, resp.text
        assert "at most" in resp.json()["detail"]
        assert (await client.get("/kits")).json() == []
        assert (await client.get("/orders")).json() == []  # not even the order header


async def test_a_catalog_line_is_held_to_the_same_ceiling(client, retailer):
    """No fan-out on this route — the ceiling is on the line, so a stock line that
    spawns nothing is refused by the same number rather than a different one."""
    resp = await order_with(
        client,
        retailer,
        {
            "item_type": "consumable",
            "quantity": orders.MAX_LINE_QUANTITY + 1,
            "unit_price_minor": 500,
            "currency_code": "JPY",
            "new_item": {"name": "Mr Surfacer 1200", "category": "primer"},
        },
        received=True,
    )
    assert resp.status_code == 422, resp.text
    assert (await client.get("/consumables")).json() == []


async def test_raising_an_existing_line_past_the_ceiling_is_refused(client, retailer):
    """The edit route reaches the fan-out through `_update_line`, not `_add_line` —
    a ceiling enforced only at entry is not a ceiling."""
    order = (await order_with(client, retailer, kit_line(quantity=2))).json()
    line = order["items"][0]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [{**kit_line(quantity=orders.MAX_LINE_QUANTITY + 1), "id": line["id"]}]},
    )
    assert resp.status_code == 422, resp.text
    assert len((await client.get("/kits")).json()) == 2  # the edit did not half-apply


async def test_adding_an_over_ceiling_line_to_an_existing_order_is_refused(client, retailer):
    order = (await order_with(client, retailer, kit_line(quantity=2))).json()

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {**kit_line(quantity=2), "id": order["items"][0]["id"]},
                kit_line(quantity=orders.MAX_LINE_QUANTITY + 1, name="Zaku II"),
            ]
        },
    )
    assert resp.status_code == 422, resp.text
    assert len((await client.get("/kits")).json()) == 2


async def test_spawn_kits_refuses_the_count_itself(client, retailer):
    """The backstop, driven directly. Every public route stops a bad quantity before
    this, so the guard is unreachable through the API by design — which is exactly
    why it needs a test that does not go through one. A fourth caller of the shared
    fan-out inherits the invariant instead of rediscovering it.
    """
    order = (await order_with(client, retailer, kit_line(quantity=1))).json()

    async with get_sessionmaker()() as session:
        item = await session.get(OrderItem, uuid.UUID(order["items"][0]["id"]))
        with pytest.raises(InvalidInputError, match="at most"):
            await orders.spawn_kits(
                session,
                item,
                name="Zaku II",
                grade="HG",
                count=orders.MAX_LINE_QUANTITY + 1,
            )


@pytest.mark.parametrize("count", [pytest.param(0, id="zero"), pytest.param(-1, id="negative")])
async def test_spawn_kits_refuses_a_non_positive_count(client, count):
    """The backstop covers the range, not one end of it. A count of 0 used to be an
    empty loop that quietly did nothing, which is not the same as being asked for
    nothing and is exactly the kind of silence the ceiling exists to prevent."""
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-08-01",
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

    async with get_sessionmaker()() as session:
        item = await session.get(OrderItem, uuid.UUID(order["items"][0]["id"]))
        with pytest.raises(InvalidInputError, match="at least 1"):
            await orders.spawn_kits(session, item, name="Zaku II", grade="HG", count=count)


# --- the aggregate fan-out ceiling (#77) -----------------------------------------
#
# Every line below is within its own ceiling (#43); the aggregate is what #77
# bounds — "split it across several lines" was the documented way around the only
# limit there was. Sizes and message fragments are literals (10 × 1,000, 10,001),
# not the new constant, so this file still imports against a tree that predates
# #77; the lockstep pin is the one place the constant is named.


def kit_lines(count: int, quantity: int) -> list[dict]:
    return [kit_line(quantity=quantity, name=f"Zaku II unit {i}") for i in range(count)]


async def multi_line_order(client, retailer, lines: list[dict], **header):
    return await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "JPY",
            "items": lines,
            **header,
        },
    )


async def test_the_aggregate_ceiling_matches_its_documented_number():
    """The lockstep pin: every other test in this block sizes off the literal, and
    this is what keeps the literal and the constant the same number."""
    assert orders.MAX_TOTAL_FANOUT == 10_000


@pytest.mark.parametrize(
    ("shape", "accepted"),
    [
        pytest.param([(10, 1_000)], True, id="exactly at the ceiling"),
        pytest.param([(10, 1_000), (1, 1)], False, id="one unit over, every line legal"),
    ],
)
async def test_an_order_cannot_derive_more_kits_than_the_aggregate_ceiling(
    client, retailer, shape, accepted
):
    lines = [line for count, quantity in shape for line in kit_lines(count, quantity)]
    resp = await multi_line_order(client, retailer, lines)

    if accepted:
        assert resp.status_code == 201, resp.text
        spawned = sum(len(item["spawned_kit_ids"]) for item in resp.json()["items"])
        assert spawned == 10_000
    else:
        assert resp.status_code == 422, resp.text
        # The aggregate message, not the per-line one — "an order line holds at
        # most" is the neighbouring refusal and would pass a containment check.
        assert "add up to 10,001" in resp.json()["detail"]
        assert (await client.get("/kits")).json() == []
        assert (await client.get("/orders")).json() == []  # not even the order header


async def test_catalog_lines_do_not_count_toward_the_aggregate_ceiling(client, retailer):
    """Stock lines adjust a count instead of fanning out. An at-ceiling kit load
    plus a 1,000-unit consumable line is 11,000 by the wrong sum and exactly at
    the ceiling by the right one — acceptance is the assertion."""
    lines = kit_lines(10, 1_000)
    lines.append(
        {
            "item_type": "consumable",
            "quantity": 1_000,
            "unit_price_minor": 500,
            "currency_code": "JPY",
            "new_item": {"name": "Mr Surfacer 1200", "category": "primer"},
        }
    )
    resp = await multi_line_order(client, retailer, lines)
    assert resp.status_code == 201, resp.text


async def test_an_edit_cannot_state_the_order_past_the_aggregate_ceiling(client, retailer):
    """The full-replacement edit is the other live route to the fan-out, and the
    check reads the *stated* set — the restated line's single unit is what tips
    10 × 1,000 over, so this also pins that restatements count (a deliberate
    call: the stated total bounds the derived creates from above, without
    re-deriving the dispatch diff before the order lock)."""
    order = (await multi_line_order(client, retailer, [kit_line(quantity=2)])).json()
    line = order["items"][0]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [{**kit_line(quantity=1), "id": line["id"]}, *kit_lines(10, 1_000)]},
    )
    assert resp.status_code == 422, resp.text
    assert "add up to 10,001" in resp.json()["detail"]
    assert len((await client.get("/kits")).json()) == 2  # the edit did not half-apply


# --- display lines (#126) --------------------------------------------------------


async def test_display_line_new_item_carries_its_own_columns(client, retailer):
    """The `display` branch of `_build_catalog_row`, which is the only new dispatch
    code #126 adds.

    Every column it can set is set, because the branch constructs the row field by
    field: one it forgot to pass would still create a perfectly valid display item
    and still increment stock, so a test asserting only name and quantity passes
    against a branch that silently drops `scale` and `notes`.
    """
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "received": True,
            "items": [
                {
                    "item_type": "display",
                    "quantity": 2,
                    "unit_price_minor": 4599,
                    "currency_code": "AUD",
                    "new_item": {
                        "name": "DCA11 Camp Set A",
                        "category": "scenery",
                        "scale": "1/144",
                        "manufacturer": "Tomytec",
                        "notes": "TMT31884",
                    },
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text

    created = (await client.get("/display-items")).json()
    assert len(created) == 1
    assert created[0]["name"] == "DCA11 Camp Set A"
    assert created[0]["category"] == "scenery"
    assert created[0]["scale"] == "1/144"
    assert created[0]["manufacturer"] == "Tomytec"
    assert created[0]["notes"] == "TMT31884"
    assert created[0]["quantity_on_hand"] == 2


async def test_new_display_item_requires_a_category_but_not_a_manufacturer(client, retailer):
    """The two halves of the branch's own rule, asserted against each other.

    Display items sit on the category side of `_build_catalog_row`'s first check
    with tools and consumables, and on the *opposite* side of upgrades' manufacturer
    check. Dropping either from the display branch leaves the other passing.
    """

    async def _order(new_item: dict):
        return await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-08-01",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "display",
                        "quantity": 1,
                        "unit_price_minor": 2999,
                        "currency_code": "AUD",
                        "new_item": new_item,
                    }
                ],
            },
        )

    missing_category = await _order({"name": "Wire Netting Fence"})
    assert missing_category.status_code == 422
    assert (await client.get("/display-items")).json() == []

    no_manufacturer = await _order({"name": "Wire Netting Fence", "category": "scenery"})
    assert no_manufacturer.status_code == 201, no_manufacturer.text
    assert (await client.get("/display-items")).json()[0]["manufacturer"] is None


async def test_pending_display_line_defers_its_increment(client, retailer):
    """Rule 2 holds for the fourth table too: quantity means physically on hand, so
    a pending order leaves it alone and receiving applies it."""
    item = (
        await client.post(
            "/display-items",
            json={"name": "Action Base 2", "category": "stand", "quantity_on_hand": 1},
        )
    ).json()

    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-08-01",
                "currency_code": "AUD",
                "items": [
                    {
                        "item_type": "display",
                        "quantity": 3,
                        "unit_price_minor": 900,
                        "currency_code": "AUD",
                        "catalog_ref_id": item["id"],
                    }
                ],
            },
        )
    ).json()
    assert order["received_at"] is None
    assert (await client.get("/display-items")).json()[0]["quantity_on_hand"] == 1  # unchanged

    await client.post(f"/orders/{order['id']}/receive")
    assert (await client.get("/display-items")).json()[0]["quantity_on_hand"] == 4  # 1 + 3

    # Delete undoes the entry, stock included — the display table is not exempt.
    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    assert (await client.get("/display-items")).json()[0]["quantity_on_hand"] == 1


# --- sort and limit (§13.4, #232) ------------------------------------------------


async def _seed_three_clocks(client, retailer) -> None:
    """One order per clock the `recent` sort reads: received (placed earliest,
    received latest), shipped-not-received, and pending (placed after the
    shipment). `placed` and `recent` disagree on every position."""

    async def make(number: str, order_date: str, **extra) -> dict:
        resp = await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": order_date,
                "order_number": number,
                "currency_code": "JPY",
                "items": [kit_line()],
                **extra,
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    await make("R", "2026-01-10", received=True, received_at="2026-03-01T10:00:00+00:00")
    await make("S", "2026-02-01", shipped_at="2026-02-20T10:00:00+00:00")
    await make("P", "2026-02-25")


def _numbers(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [order["order_number"] for order in resp.json()]


async def test_list_orders_sort_recent_is_the_last_status_change(client, retailer):
    await _seed_three_clocks(client, retailer)
    assert _numbers(await client.get("/orders")) == ["P", "S", "R"]
    assert _numbers(await client.get("/orders", params={"sort": "placed"})) == ["P", "S", "R"]
    # Received on 1 March beats placed on 25 February beats shipped on 20 February.
    assert _numbers(await client.get("/orders", params={"sort": "recent"})) == ["R", "P", "S"]


async def test_list_orders_limit_and_pending_only_compose_with_the_sort(client, retailer):
    await _seed_three_clocks(client, retailer)
    assert _numbers(await client.get("/orders", params={"sort": "recent", "limit": 1})) == ["R"]
    assert _numbers(await client.get("/orders", params={"pending_only": "true"})) == ["P", "S"]
    # The limit counts pending rows, not rows before the filter.
    assert _numbers(
        await client.get("/orders", params={"pending_only": "true", "sort": "recent", "limit": 1})
    ) == ["P"]


async def _seed_near_midnight_pair(client, retailer) -> None:
    """A placed on 2 August with no shipment; B placed earlier and shipped at
    15:00Z on 1 August. Which is the later change depends on whose midnight
    "2 August" means: Brisbane's (UTC+10, no DST) is 14:00Z on the 1st, an hour
    *before* B's shipment; Los Angeles's (UTC−7 in August) is 07:00Z on the 2nd,
    after it; the database session's UTC midnight puts A first too."""
    for number, order_date, extra in (
        ("A", "2026-08-02", {}),
        ("B", "2026-07-31", {"shipped_at": "2026-08-01T15:00:00+00:00"}),
    ):
        resp = await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": order_date,
                "order_number": number,
                "currency_code": "JPY",
                "items": [kit_line()],
                **extra,
            },
        )
        assert resp.status_code == 201, resp.text


async def test_list_orders_sort_recent_reads_the_placement_date_in_the_instance_zone(
    client, retailer
):
    """A date against two instants: the day an order was placed is its midnight in
    the *instance's* time zone (§13.4, rule 11), not the SQL session's — the cast
    alone read the session zone, so the same rows ranked one way under a Brisbane
    session and the other under UTC (Codex #236 P2-1). Two zones either side of
    UTC, so a clock that ignores the setting fails one of them."""
    await _seed_near_midnight_pair(client, retailer)
    resp = await client.patch("/settings", json={"time_zone": "Australia/Brisbane"})
    assert resp.status_code == 200, resp.text
    assert _numbers(await client.get("/orders", params={"sort": "recent"})) == ["B", "A"]
    resp = await client.patch("/settings", json={"time_zone": "America/Los_Angeles"})
    assert resp.status_code == 200, resp.text
    assert _numbers(await client.get("/orders", params={"sort": "recent"})) == ["A", "B"]
    # `placed` is the date alone — no zone can move it.
    assert _numbers(await client.get("/orders", params={"sort": "placed"})) == ["A", "B"]


async def _make_order(client, retailer, number: str, order_date: str, **extra) -> None:
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": order_date,
            "order_number": number,
            "currency_code": "JPY",
            "items": [kit_line()],
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text


async def test_list_orders_sort_recent_reads_a_zone_alias_the_database_lacks(client, retailer):
    """The zone is the application's (rule 11), never the database's: Postgres's
    zone files lack 97 of the names `validate_time_zone` accepts — this IANA link
    among them — and answered the sort with a 500 (Codex #236 round 2, P2-7).
    Queensland is Brisbane's rules, so the pair reads B, A."""
    await _seed_near_midnight_pair(client, retailer)
    resp = await client.patch("/settings", json={"time_zone": "Australia/Queensland"})
    assert resp.status_code == 200, resp.text
    assert _numbers(await client.get("/orders", params={"sort": "recent"})) == ["B", "A"]


async def test_list_orders_sort_recent_reads_an_abbreviation_with_its_seasonal_rule(
    client, retailer
):
    """CET, EET, MET and WET are zones with seasonal rules in the application's
    zone database and fixed offsets in Postgres's (P2-7). On 2 August CET is +02,
    so A's midnight is 22:00Z on the 1st and B, shipped 22:30Z, is the later
    change; a fixed +01 would read A's midnight as 23:00Z and rank A first."""
    await _make_order(client, retailer, "A", "2026-08-02")
    await _make_order(client, retailer, "B", "2026-08-01", shipped_at="2026-08-01T22:30:00+00:00")
    resp = await client.patch("/settings", json={"time_zone": "CET"})
    assert resp.status_code == 200, resp.text
    assert _numbers(await client.get("/orders", params={"sort": "recent"})) == ["B", "A"]


async def test_list_orders_sort_recent_computes_under_every_zone_the_settings_accept(
    client, retailer
):
    """Whatever `validate_time_zone` admits, the clock can read (P2-7: 97 of these
    names raised in SQL, four ranked by the wrong rules). Every zone the
    application knows, through the settings and list services in one session,
    the pair ranked the way the zone's own midnight says — B first when its
    shipment at 15:00Z on the 1st is later than A's midnight, else A (a zone at
    exactly +09 ties them, and the tie is the newer placement)."""
    from datetime import UTC, date, datetime, time
    from zoneinfo import ZoneInfo, available_timezones

    from app.schemas.settings import InstanceSettingsUpdate
    from app.services import instance_settings

    await _seed_near_midnight_pair(client, retailer)
    shipped_b = datetime(2026, 8, 1, 15, tzinfo=UTC)
    async with get_sessionmaker()() as session:
        for zone in sorted(available_timezones()):
            await instance_settings.update_instance_settings(
                session, InstanceSettingsUpdate(time_zone=zone)
            )
            rows = await orders.list_orders(session, sort="recent")
            midnight_a = datetime.combine(date(2026, 8, 2), time.min, tzinfo=ZoneInfo(zone))
            expected = ["B", "A"] if midnight_a < shipped_b else ["A", "B"]
            assert [row.order_number for row in rows] == expected, zone


async def test_list_orders_sort_recent_ties_equal_instants_across_zone_representations(
    client, retailer
):
    """Equal instants must have equal keys whatever zone represents them (Codex
    #236 round 3, P3-9): a stored shipment is UTC, a placement midnight is
    zone-local, and Python calls an aware datetime whose offset depends on
    `fold` — a midnight a transition repeats or skips — *unequal* to any other
    zone's datetime at the same instant (PEP 495), so a key of raw datetimes
    never reached the placement date on exactly those ties and the rows fell
    back to id order. Havana: the repeated midnight of 2025-11-02 is 04:00Z, the
    skipped one of 2025-03-09 reads as 05:00Z; a shipment at each instant ties
    its placement, and the tie breaks on the newer placement date."""
    ids: dict[str, str] = {}
    for number in ("W", "X", "Y", "Z"):
        resp = await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2025-01-01",
                "order_number": number,
                "currency_code": "JPY",
                "items": [kit_line()],
            },
        )
        assert resp.status_code == 201, resp.text
        ids[number] = resp.json()["id"]
    number_of = {order_id: number for number, order_id in ids.items()}
    # The tie-break after the clock and the date is the id, ascending. Give the
    # *lower* id of each pair the older placement — the row a raw-datetime key
    # wrongly put first — so the defect is red whichever ids the database dealt.
    (nov_shipped, nov_placed) = sorted([ids["W"], ids["X"]])
    (mar_shipped, mar_placed) = sorted([ids["Y"], ids["Z"]])
    for order_id, placed, shipped in (
        (nov_shipped, "2025-11-01", "2025-11-02T04:00:00+00:00"),
        (nov_placed, "2025-11-02", None),
        (mar_shipped, "2025-03-08", "2025-03-09T05:00:00+00:00"),
        (mar_placed, "2025-03-09", None),
    ):
        resp = await client.patch(f"/orders/{order_id}", json={"order_date": placed})
        assert resp.status_code == 200, resp.text
        if shipped is not None:
            # A shipment is recorded through the ship endpoint; an edit only
            # corrects a date already set.
            resp = await client.post(f"/orders/{order_id}/ship", json={"shipped_at": shipped})
            assert resp.status_code == 200, resp.text
    resp = await client.patch("/settings", json={"time_zone": "America/Havana"})
    assert resp.status_code == 200, resp.text
    expected = [number_of[i] for i in (nov_placed, nov_shipped, mar_placed, mar_shipped)]
    recent = {"sort": "recent"}
    assert _numbers(await client.get("/orders", params=recent)) == expected
    assert _numbers(await client.get("/orders", params={**recent, "limit": 1})) == expected[:1]


async def test_list_orders_sort_recent_names_its_transition_policy(client, retailer):
    """Havana ends DST on 2025-11-02 at 01:00 → 00:00, so that midnight happens
    twice: a repeated midnight is its *first* occurrence, 04:00Z (fold=0), and a
    shipment at 04:30Z is the later change. It starts DST on 2025-03-09 at
    00:00 → 01:00, so that midnight never happens: the old offset's reading
    stands, 05:00Z (01:00 local), and a shipment at 04:30Z is the earlier one.
    §13.4 names both choices; the database's own reading of the repeated case
    was the second occurrence (Codex #236 round 2)."""
    await _make_order(client, retailer, "A1", "2025-11-02")
    await _make_order(client, retailer, "B1", "2025-11-01", shipped_at="2025-11-02T04:30:00+00:00")
    await _make_order(client, retailer, "A2", "2025-03-09")
    await _make_order(client, retailer, "B2", "2025-03-08", shipped_at="2025-03-09T04:30:00+00:00")
    resp = await client.patch("/settings", json={"time_zone": "America/Havana"})
    assert resp.status_code == 200, resp.text
    # B1 04:30Z, A1 04:00Z (November); A2 05:00Z, B2 04:30Z (March).
    assert _numbers(await client.get("/orders", params={"sort": "recent"})) == [
        "B1",
        "A1",
        "A2",
        "B2",
    ]


@pytest.mark.parametrize(
    "params",
    [{"sort": "newest"}, {"sort": ""}, {"limit": "0"}, {"limit": "-1"}, {"limit": "ten"}],
)
async def test_list_orders_refuses_a_sort_or_limit_outside_the_vocabulary(client, retailer, params):
    assert (await client.get("/orders", params=params)).status_code == 422
