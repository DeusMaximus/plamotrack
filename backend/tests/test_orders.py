import uuid


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
