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
