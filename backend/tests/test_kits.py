async def test_create_kit_derives_scale_from_grade(client):
    resp = await client.post("/kits", json={"name": "Zaku II Ver.Ka", "grade": "MG"})
    assert resp.status_code == 201
    kit = resp.json()
    assert kit["scale"] == "1/100"
    assert kit["status"] == "backlog"
    assert kit["order_item_id"] is None


async def test_create_kit_explicit_scale_wins(client):
    resp = await client.post(
        "/kits", json={"name": "Weird resin kit", "grade": "HG", "scale": "1/120"}
    )
    assert resp.json()["scale"] == "1/120"


async def test_status_patch_bumps_status_updated_at(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()

    resp = await client.patch(f"/kits/{created['id']}", json={"status": "building"})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["status"] == "building"
    assert updated["status_updated_at"] != created["status_updated_at"]


async def test_non_status_patch_leaves_status_updated_at(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()

    updated = (
        await client.patch(f"/kits/{created['id']}", json={"build_notes": "panel lining done"})
    ).json()
    assert updated["build_notes"] == "panel lining done"
    assert updated["status_updated_at"] == created["status_updated_at"]


async def test_invalid_status_rejected(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()
    resp = await client.patch(f"/kits/{created['id']}", json={"status": "painting"})
    assert resp.status_code == 422


async def test_rating_bounds(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()
    assert (await client.patch(f"/kits/{created['id']}", json={"rating": 6})).status_code == 422
    assert (await client.patch(f"/kits/{created['id']}", json={"rating": 5})).status_code == 200


async def test_list_kits_filters(client):
    await client.post("/kits", json={"name": "A", "grade": "HG"})
    await client.post("/kits", json={"name": "B", "grade": "MG", "status": "building"})

    building = (await client.get("/kits", params={"status": "building"})).json()
    assert [k["name"] for k in building] == ["B"]

    hg = (await client.get("/kits", params={"grade": "hg"})).json()  # case-insensitive
    assert [k["name"] for k in hg] == ["A"]


async def test_delete_kit(client):
    created = (await client.post("/kits", json={"name": "RX-78-2", "grade": "RG"})).json()
    assert (await client.delete(f"/kits/{created['id']}")).status_code == 204
    assert (await client.get(f"/kits/{created['id']}")).status_code == 404
