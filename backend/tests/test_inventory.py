async def _make_upgrade(client, quantity: int) -> dict:
    resp = await client.post(
        "/upgrades",
        json={
            "name": "Metal thrusters",
            "manufacturer": "Metal Build",
            "quantity_on_hand": quantity,
        },
    )
    assert resp.status_code == 201
    return resp.json()


async def _make_kit(client) -> dict:
    resp = await client.post("/kits", json={"name": "Sazabi Ver.Ka", "grade": "MG"})
    assert resp.status_code == 201
    return resp.json()


async def test_apply_upgrade_decrements_stock(client):
    upgrade = await _make_upgrade(client, 5)
    kit = await _make_kit(client)

    resp = await client.post(
        f"/upgrades/{upgrade['id']}/apply", json={"kit_id": kit["id"], "quantity": 2}
    )
    assert resp.status_code == 201
    application = resp.json()
    assert application["upgrade_id"] == upgrade["id"]
    assert application["kit_id"] == kit["id"]
    assert application["quantity_used"] == 2

    refreshed = (await client.get("/upgrades")).json()[0]
    assert refreshed["quantity_on_hand"] == 3


async def test_apply_upgrade_insufficient_stock_is_atomic(client):
    upgrade = await _make_upgrade(client, 1)
    kit = await _make_kit(client)

    resp = await client.post(
        f"/upgrades/{upgrade['id']}/apply", json={"kit_id": kit["id"], "quantity": 2}
    )
    assert resp.status_code == 409
    assert "insufficient stock" in resp.json()["detail"]

    refreshed = (await client.get("/upgrades")).json()[0]
    assert refreshed["quantity_on_hand"] == 1  # untouched


async def test_update_and_delete_catalog_item(client):
    tool = (
        await client.post("/tools", json={"name": "Godhand SPN-120", "category": "cutting"})
    ).json()

    resp = await client.patch(f"/tools/{tool['id']}", json={"condition_notes": "blade chipped"})
    assert resp.status_code == 200
    assert resp.json()["condition_notes"] == "blade chipped"

    assert (await client.delete(f"/tools/{tool['id']}")).status_code == 204
    assert (await client.get("/tools")).json() == []


async def test_delete_catalog_item_referenced_by_order_blocked(client):
    retailer = (await client.post("/retailers", json={"name": "HLJ"})).json()
    consumable = (
        await client.post("/consumables", json={"name": "Marker", "category": "paint"})
    ).json()
    await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "consumable",
                    "quantity": 1,
                    "unit_price_minor": 650,
                    "currency_code": "AUD",
                    "catalog_ref_id": consumable["id"],
                }
            ],
        },
    )
    resp = await client.delete(f"/consumables/{consumable['id']}")
    assert resp.status_code == 409
    assert "order" in resp.json()["detail"]


async def test_delete_applied_upgrade_blocked(client):
    upgrade = await _make_upgrade(client, 2)
    kit = await _make_kit(client)
    await client.post(f"/upgrades/{upgrade['id']}/apply", json={"kit_id": kit["id"], "quantity": 1})

    resp = await client.delete(f"/upgrades/{upgrade['id']}")
    assert resp.status_code == 409
    assert "applied" in resp.json()["detail"]


async def test_delete_kit_with_an_applied_upgrade_blocked(client):
    """The other end of the same join, which nothing guarded.

    `upgrade_applications.kit_id` is ON DELETE CASCADE, so deleting the kit used to
    return 204 and take the application with it — while the upgrade stock it spent
    stayed spent. Rule 3 applies in both directions: history is fact.
    """
    upgrade = await _make_upgrade(client, 2)
    kit = await _make_kit(client)
    await client.post(f"/upgrades/{upgrade['id']}/apply", json={"kit_id": kit["id"], "quantity": 1})

    resp = await client.delete(f"/kits/{kit['id']}")
    assert resp.status_code == 409
    assert "applied" in resp.json()["detail"]
    assert len((await client.get("/kits")).json()) == 1  # still there
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 1  # still spent


async def test_delete_kit_without_applications_still_works(client):
    """The control: the guard must not make every standalone kit undeletable."""
    kit = await _make_kit(client)
    assert (await client.delete(f"/kits/{kit['id']}")).status_code == 204
    assert (await client.get("/kits")).json() == []


async def test_retailer_report_card_fields(client):
    resp = await client.post(
        "/retailers",
        json={
            "name": "Gundam Express Australia",
            "rating": 5,
            "packing_quality": "excellent",
            "shipping_speed": "fast",
            "would_order_again": "yes",
            "notes": "Free shipping over $150",
        },
    )
    assert resp.status_code == 201
    retailer = resp.json()
    assert retailer["rating"] == 5
    assert retailer["packing_quality"] == "excellent"
    assert retailer["shipping_speed"] == "fast"
    assert retailer["would_order_again"] == "yes"

    resp = await client.patch(
        f"/retailers/{retailer['id']}",
        json={"rating": 3, "would_order_again": "maybe", "shipping_speed": "very_slow"},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["rating"] == 3
    assert updated["would_order_again"] == "maybe"
    assert updated["packing_quality"] == "excellent"  # untouched


async def test_retailer_report_card_validation(client):
    assert (await client.post("/retailers", json={"name": "X", "rating": 6})).status_code == 422
    assert (
        await client.post("/retailers", json={"name": "X", "packing_quality": "amazing"})
    ).status_code == 422
    assert (
        await client.post("/retailers", json={"name": "X", "would_order_again": "never again"})
    ).status_code == 422


async def test_retailer_update_and_guarded_delete(client):
    retailer = (await client.post("/retailers", json={"name": "HLJ"})).json()

    resp = await client.patch(f"/retailers/{retailer['id']}", json={"url": "https://hlj.com"})
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://hlj.com"

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
                    "kit": {"name": "HG Zaku II", "grade": "HG"},
                }
            ],
        },
    )
    assert (await client.delete(f"/retailers/{retailer['id']}")).status_code == 409

    unused = (await client.post("/retailers", json={"name": "Temu (mistake)"})).json()
    assert (await client.delete(f"/retailers/{unused['id']}")).status_code == 204


async def test_catalog_search_spans_all_three_tables(client):
    await client.post("/tools", json={"name": "Godhand Nippers", "category": "cutting"})
    await client.post("/consumables", json={"name": "Gundam Marker GM02", "category": "paint"})
    await client.post(
        "/upgrades", json={"name": "G-Rework Decal RX-78", "manufacturer": "G-Rework"}
    )

    results = (await client.get("/catalog/search", params={"q": "g"})).json()
    assert {r["item_type"] for r in results} == {"tool", "consumable", "upgrade"}

    marker_only = (await client.get("/catalog/search", params={"q": "MARKER"})).json()
    assert len(marker_only) == 1
    assert marker_only[0]["item_type"] == "consumable"
    assert marker_only[0]["name"] == "Gundam Marker GM02"
