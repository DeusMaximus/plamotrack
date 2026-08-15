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
