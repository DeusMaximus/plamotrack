"""Receive / edit / delete semantics for orders (§3.9 amendments)."""


def kit_line(quantity: int = 2, name: str = "RX-79[G] Gundam Ground Type") -> dict:
    return {
        "item_type": "kit",
        "quantity": quantity,
        "unit_price_minor": 4999,
        "currency_code": "AUD",
        "kit": {"name": name, "grade": "HG", "kit_number": "HGUC 210"},
    }


def consumable_line(ref_id: str, quantity: int = 5) -> dict:
    return {
        "item_type": "consumable",
        "quantity": quantity,
        "unit_price_minor": 650,
        "currency_code": "AUD",
        "catalog_ref_id": ref_id,
    }


async def make_consumable(client, name: str = "Gundam Marker GM01", quantity: int = 0) -> dict:
    resp = await client.post(
        "/consumables", json={"name": name, "category": "paint", "quantity_on_hand": quantity}
    )
    assert resp.status_code == 201
    return resp.json()


async def make_order(client, retailer, items: list[dict], **extra) -> dict:
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": items,
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- receive -------------------------------------------------------------------


async def test_receive_moves_pipeline_kits_to_in_hand(client, retailer):
    order = await make_order(client, retailer, [kit_line()])
    kits = (await client.get("/kits")).json()
    assert all(k["status"] == "ordered" for k in kits)

    await client.post(f"/orders/{order['id']}/receive")
    kits = (await client.get("/kits")).json()
    assert all(k["status"] == "in_hand" for k in kits)


async def test_receive_leaves_progressed_kits_alone(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    kit_id = order["items"][0]["spawned_kit_ids"][0]
    await client.patch(f"/kits/{kit_id}", json={"status": "building"})

    await client.post(f"/orders/{order['id']}/receive")
    kits = {k["id"]: k["status"] for k in (await client.get("/kits")).json()}
    assert kits[kit_id] == "building"  # untouched
    assert sorted(kits.values()) == ["building", "in_hand"]


async def test_double_receive_conflicts(client, retailer):
    order = await make_order(client, retailer, [kit_line()])
    assert (await client.post(f"/orders/{order['id']}/receive")).status_code == 200
    resp = await client.post(f"/orders/{order['id']}/receive")
    assert resp.status_code == 409


async def test_received_order_spawns_kits_in_hand(client, retailer):
    await make_order(client, retailer, [kit_line()], received=True)
    kits = (await client.get("/kits")).json()
    assert all(k["status"] == "in_hand" for k in kits)


# --- delete (undo) -------------------------------------------------------------


async def test_delete_pending_order_removes_kits_leaves_stock(client, retailer):
    consumable = await make_consumable(client, quantity=2)
    order = await make_order(client, retailer, [kit_line(), consumable_line(consumable["id"])])

    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    assert (await client.get("/kits")).json() == []
    assert (await client.get("/orders")).json() == []
    # never applied, so never reversed
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 2


async def test_delete_received_order_reverses_stock(client, retailer):
    consumable = await make_consumable(client, quantity=2)
    order = await make_order(
        client, retailer, [consumable_line(consumable["id"], quantity=5)], received=True
    )
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 7

    assert (await client.delete(f"/orders/{order['id']}")).status_code == 204
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 2


async def test_delete_blocked_when_stock_consumed(client, retailer):
    consumable = await make_consumable(client, quantity=0)
    order = await make_order(
        client, retailer, [consumable_line(consumable["id"], quantity=5)], received=True
    )
    # burn through most of the delivery
    await client.patch(f"/consumables/{consumable['id']}", json={"quantity_on_hand": 1})

    resp = await client.delete(f"/orders/{order['id']}")
    assert resp.status_code == 409
    assert "on hand" in resp.json()["detail"]
    assert (await client.get("/orders")).json() != []  # order survived


async def test_delete_blocked_when_kit_progressed(client, retailer):
    order = await make_order(client, retailer, [kit_line()])
    kit_id = order["items"][0]["spawned_kit_ids"][0]
    await client.patch(f"/kits/{kit_id}", json={"status": "building"})

    resp = await client.delete(f"/orders/{order['id']}")
    assert resp.status_code == 409
    assert len((await client.get("/kits")).json()) == 2  # nothing deleted


# --- edit: header --------------------------------------------------------------


async def test_header_edit_leaves_lines_alone(client, retailer):
    order = await make_order(client, retailer, [kit_line()], order_number="GEA-10482")
    assert order["order_number"] == "GEA-10482"

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"tracking_number": "EMS123456789JP", "tracking_url": "https://track.example/x"},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["tracking_number"] == "EMS123456789JP"
    assert updated["order_number"] == "GEA-10482"  # untouched by other header edits
    assert len(updated["items"]) == 1
    assert len(updated["items"][0]["spawned_kit_ids"]) == 2


async def test_order_number_is_not_unique(client, retailer):
    """Retailer order numbers are reference-only — two retailers (or even the
    same one) can reuse a number without the API caring."""
    other = (await client.post("/retailers", json={"name": "HLJ"})).json()
    first = await make_order(client, retailer, [kit_line(quantity=1)], order_number="10001")
    second = await client.post(
        "/orders",
        json={
            "retailer_id": other["id"],
            "order_date": "2026-08-02",
            "currency_code": "JPY",
            "order_number": "10001",
            "items": [kit_line(quantity=1)],
        },
    )
    assert second.status_code == 201
    assert first["order_number"] == second.json()["order_number"] == "10001"


# --- edit: kit lines -----------------------------------------------------------


async def test_kit_line_edit_propagates_details(client, retailer):
    order = await make_order(client, retailer, [kit_line(name="RX-79[G] Gound Type")])  # typo
    line = order["items"][0]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": line["id"],
                    "item_type": "kit",
                    "quantity": 2,
                    "unit_price_minor": 4999,
                    "currency_code": "AUD",
                    "kit": {"name": "RX-79[G] Gundam Ground Type", "grade": "HG"},
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    kits = (await client.get("/kits")).json()
    assert len(kits) == 2
    assert all(k["name"] == "RX-79[G] Gundam Ground Type" for k in kits)


async def test_kit_line_quantity_increase_spawns(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    line = order["items"][0]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": line["id"],
                    "item_type": "kit",
                    "quantity": 3,
                    "unit_price_minor": 4999,
                    "currency_code": "AUD",
                    "kit": {"name": "RX-79[G] Gundam Ground Type", "grade": "HG"},
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"][0]["spawned_kit_ids"]) == 3
    assert len((await client.get("/kits")).json()) == 3


async def test_kit_line_quantity_decrease_prefers_safe_kits(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    line = order["items"][0]
    progressed_id = line["spawned_kit_ids"][0]
    await client.patch(f"/kits/{progressed_id}", json={"status": "building"})

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": line["id"],
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 4999,
                    "currency_code": "AUD",
                    "kit": {"name": "RX-79[G] Gundam Ground Type", "grade": "HG"},
                }
            ]
        },
    )
    assert resp.status_code == 200
    kits = (await client.get("/kits")).json()
    assert [k["id"] for k in kits] == [progressed_id]  # the building kit survived


async def test_kit_line_removal_blocked_by_progressed_kit(client, retailer):
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [kit_line(), consumable_line(consumable["id"], 1)])
    kit_item = next(i for i in order["items"] if i["item_type"] == "kit")
    other = next(i for i in order["items"] if i["item_type"] == "consumable")
    await client.patch(f"/kits/{kit_item['spawned_kit_ids'][0]}", json={"status": "complete"})

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": other["id"],
                    "item_type": "consumable",
                    "quantity": 1,
                    "unit_price_minor": 650,
                    "currency_code": "AUD",
                    "catalog_ref_id": consumable["id"],
                }
            ]
        },
    )
    assert resp.status_code == 409


# --- edit: catalog lines -------------------------------------------------------


async def test_received_catalog_edit_adjusts_stock(client, retailer):
    consumable = await make_consumable(client, quantity=0)
    order = await make_order(
        client, retailer, [consumable_line(consumable["id"], quantity=5)], received=True
    )
    line = order["items"][0]
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 5

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": line["id"],
                    "item_type": "consumable",
                    "quantity": 2,
                    "unit_price_minor": 650,
                    "currency_code": "AUD",
                    "catalog_ref_id": consumable["id"],
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 2


async def test_received_catalog_target_change_moves_stock(client, retailer):
    marker = await make_consumable(client, name="Gundam Marker GM01", quantity=0)
    cement = await make_consumable(client, name="Mr. Cement SP", quantity=1)
    order = await make_order(
        client, retailer, [consumable_line(marker["id"], quantity=3)], received=True
    )
    line = order["items"][0]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": line["id"],
                    "item_type": "consumable",
                    "quantity": 3,
                    "unit_price_minor": 650,
                    "currency_code": "AUD",
                    "catalog_ref_id": cement["id"],
                }
            ]
        },
    )
    assert resp.status_code == 200
    by_name = {c["name"]: c["quantity_on_hand"] for c in (await client.get("/consumables")).json()}
    assert by_name["Gundam Marker GM01"] == 0  # reversed
    assert by_name["Mr. Cement SP"] == 4  # 1 + 3


async def test_pending_catalog_edit_touches_no_stock(client, retailer):
    consumable = await make_consumable(client, quantity=2)
    order = await make_order(client, retailer, [consumable_line(consumable["id"], quantity=5)])
    line = order["items"][0]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": line["id"],
                    "item_type": "consumable",
                    "quantity": 9,
                    "unit_price_minor": 650,
                    "currency_code": "AUD",
                    "catalog_ref_id": consumable["id"],
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 2


async def test_line_omission_removes_and_reverses(client, retailer):
    consumable = await make_consumable(client, quantity=0)
    order = await make_order(
        client,
        retailer,
        [kit_line(quantity=1), consumable_line(consumable["id"], quantity=5)],
        received=True,
    )
    kit_item = next(i for i in order["items"] if i["item_type"] == "kit")

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": kit_item["id"],
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 4999,
                    "currency_code": "AUD",
                    "kit": {"name": "RX-79[G] Gundam Ground Type", "grade": "HG"},
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 0


async def test_line_added_to_received_order_spawns_in_hand(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)], received=True)
    existing_line = order["items"][0]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": existing_line["id"],
                    "item_type": "kit",
                    "quantity": 1,
                    "unit_price_minor": 4999,
                    "currency_code": "AUD",
                    "kit": {"name": "RX-79[G] Gundam Ground Type", "grade": "HG"},
                },
                kit_line(quantity=1, name="HG Zaku II"),
            ]
        },
    )
    assert resp.status_code == 200
    kits = (await client.get("/kits")).json()
    assert len(kits) == 2
    assert all(k["status"] == "in_hand" for k in kits)


async def test_item_type_change_rejected(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    line = order["items"][0]

    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": line["id"],
                    "item_type": "tool",
                    "quantity": 1,
                    "unit_price_minor": 4999,
                    "currency_code": "AUD",
                    "new_item": {"name": "Nippers", "category": "cutting"},
                }
            ]
        },
    )
    assert resp.status_code == 422
