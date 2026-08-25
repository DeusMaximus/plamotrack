import asyncio
import uuid

import pytest

from app.db import session_scope
from app.exceptions import ConflictError, NotFoundError
from app.services import kits as kits_service
from app.services import upgrades as upgrades_service


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


async def test_catalog_search_spans_every_catalog_table(client):
    await client.post("/tools", json={"name": "Godhand Nippers", "category": "cutting"})
    await client.post("/consumables", json={"name": "Gundam Marker GM02", "category": "paint"})
    await client.post(
        "/upgrades", json={"name": "G-Rework Decal RX-78", "manufacturer": "G-Rework"}
    )
    await client.post("/display-items", json={"name": "G-Stand riser", "category": "stand"})

    results = (await client.get("/catalog/search", params={"q": "g"})).json()
    assert {r["item_type"] for r in results} == {"tool", "consumable", "upgrade", "display"}

    marker_only = (await client.get("/catalog/search", params={"q": "MARKER"})).json()
    assert len(marker_only) == 1
    assert marker_only[0]["item_type"] == "consumable"
    assert marker_only[0]["name"] == "Gundam Marker GM02"


# --- display items (#126) --------------------------------------------------------


async def _make_display_item(client, **overrides) -> dict:
    payload = {"name": "Action Base 2", "category": "stand"} | overrides
    resp = await client.post("/display-items", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_display_item_round_trips_every_column(client):
    """Create then read back, with every optional column *set* — a create that
    silently dropped `scale` or `notes` reads identically to one that kept them if
    the assertions only cover the required pair."""
    item = await _make_display_item(
        client,
        scale="1/144",
        manufacturer="Tomytec",
        quantity_on_hand=3,
        notes="D-CM01 Diocom Destroyed Factory",
    )
    assert item["scale"] == "1/144"
    assert item["manufacturer"] == "Tomytec"
    assert item["quantity_on_hand"] == 3
    assert item["notes"] == "D-CM01 Diocom Destroyed Factory"

    listed = (await client.get("/display-items")).json()
    assert listed == [item]


async def test_display_item_optional_columns_default_to_null(client):
    """The other end of the value axis: the same route with them omitted. `scale`
    and `manufacturer` are the two columns that differ from every sibling table, so
    a default that quietly became "" rather than null would go unnoticed here."""
    item = await _make_display_item(client)
    assert item["scale"] is None
    assert item["manufacturer"] is None
    assert item["notes"] is None
    assert item["quantity_on_hand"] == 0


async def test_display_item_requires_a_category(client):
    """Required, and required for a reason — it is the only field that answers
    "how many stands do I have" without guessing from names (#126, #127)."""
    resp = await client.post("/display-items", json={"name": "Action Base 2"})
    assert resp.status_code == 422
    assert (await client.get("/display-items")).json() == []


async def test_display_item_patch_distinguishes_absent_from_null(client):
    """Three values per field, per the PATCH rule the *Update schemas encode:
    absent leaves the stored value, an explicit null clears it, a value replaces it."""
    item = await _make_display_item(client, scale="1/144", manufacturer="Tomytec", notes="boxed")

    # absent — untouched
    resp = await client.patch(f"/display-items/{item['id']}", json={"quantity_on_hand": 5})
    assert resp.status_code == 200, resp.text
    assert resp.json()["scale"] == "1/144"
    assert resp.json()["manufacturer"] == "Tomytec"

    # a new value — replaced
    resp = await client.patch(f"/display-items/{item['id']}", json={"scale": "1/100"})
    assert resp.json()["scale"] == "1/100"

    # explicit null — cleared
    resp = await client.patch(f"/display-items/{item['id']}", json={"scale": None, "notes": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["scale"] is None
    assert resp.json()["notes"] is None
    assert resp.json()["quantity_on_hand"] == 5  # the earlier edit survived


async def test_clearing_manufacturer_is_allowed_here_and_refused_on_an_upgrade(client):
    """The same field name, opposite answers, because they are different columns.

    `manufacturer` is NOT NULL on upgrades and nullable on display items, so
    `_NON_NULLABLE` cannot be a bare name set — it has to ask the model. Both
    directions are asserted together: a check that consulted only the name would
    refuse the first call, and one that consulted neither would accept the second
    and 500 at flush.
    """
    item = await _make_display_item(client, manufacturer="Tomytec")
    resp = await client.patch(f"/display-items/{item['id']}", json={"manufacturer": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["manufacturer"] is None

    upgrade = await _make_upgrade(client, 1)
    refused = await client.patch(f"/upgrades/{upgrade['id']}", json={"manufacturer": None})
    assert refused.status_code == 422
    assert "manufacturer cannot be null" in refused.json()["detail"]


async def test_display_item_category_cannot_be_nulled(client):
    """`category` is NOT NULL here too — the nullable-manufacturer carve-out is per
    column, not a blanket exemption for the whole table."""
    item = await _make_display_item(client)
    resp = await client.patch(f"/display-items/{item['id']}", json={"category": None})
    assert resp.status_code == 422
    assert "category cannot be null" in resp.json()["detail"]


async def test_display_item_delete_and_its_order_guard(client):
    """Unreferenced deletes; referenced refuses — rule 3, same as every catalog table."""
    spare = await _make_display_item(client, name="Spare base")
    assert (await client.delete(f"/display-items/{spare['id']}")).status_code == 204

    retailer = (await client.post("/retailers", json={"name": "HLJ"})).json()
    bought = await _make_display_item(client, name="Diocom Hangar")
    await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "display",
                    "quantity": 1,
                    "unit_price_minor": 7999,
                    "currency_code": "AUD",
                    "catalog_ref_id": bought["id"],
                }
            ],
        },
    )
    resp = await client.delete(f"/display-items/{bought['id']}")
    assert resp.status_code == 409
    assert "order" in resp.json()["detail"]


async def test_catalog_search_and_adjust_reach_display_items(client):
    """The two cross-table paths that resolve by walking `CATALOG_MODELS`. Display
    items are last in that mapping, so a loop that returned early still passes every
    other table's version of this."""
    item = await _make_display_item(client, scale="1/144", quantity_on_hand=2)

    results = (await client.get("/catalog/search", params={"q": "action"})).json()
    assert len(results) == 1
    assert results[0]["item_type"] == "display"
    assert results[0]["category"] == "stand"
    assert results[0]["scale"] == "1/144"

    adjusted = await client.post(f"/catalog/{item['id']}/adjust", json={"delta": -2})
    assert adjusted.status_code == 200, adjusted.text
    assert adjusted.json()["item_type"] == "display"
    assert adjusted.json()["quantity_on_hand"] == 0

    floored = await client.post(f"/catalog/{item['id']}/adjust", json={"delta": -1})
    assert floored.status_code == 409


# --- #129 review: blank-but-not-empty required text ------------------------------


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        pytest.param("/tools", {"name": "T"}, "category", id="tools.category"),
        pytest.param("/consumables", {"name": "C"}, "category", id="consumables.category"),
        pytest.param("/display-items", {"name": "D"}, "category", id="display_items.category"),
        pytest.param("/upgrades", {"name": "U"}, "manufacturer", id="upgrades.manufacturer"),
    ],
)
@pytest.mark.parametrize("blank", [" ", "   ", "\t", " "], ids=["space", "spaces", "tab", "nbsp"])
async def test_a_required_text_column_refuses_whitespace(client, path, payload, field, blank):
    """`min_length=1` is satisfied by a space, and the order dispatch tested
    `not new_item.category`, which a space also passes — so `"   "` reached a NOT
    NULL column verbatim and the create answered 201 (#129 review, P3-4).

    Every required free-text column on every catalog table, because the defect was
    the *rule* being absent rather than one table missing it; a fix that reached
    only display items is the same bug on three other tables. The blanks include a
    no-break space, which `str.strip()` removes and a naive `== " "` check does not.
    """
    resp = await client.post(path, json={**payload, field: blank})
    assert resp.status_code == 422, resp.text
    assert f"{field} cannot be blank" in resp.json()["detail"]
    assert (await client.get(path)).json() == []


@pytest.mark.parametrize(
    ("path", "payload", "field"),
    [
        pytest.param("/tools", {"name": "T"}, "category", id="tools.category"),
        pytest.param("/display-items", {"name": "D"}, "category", id="display_items.category"),
        pytest.param("/upgrades", {"name": "U"}, "manufacturer", id="upgrades.manufacturer"),
    ],
)
async def test_a_required_text_column_is_stored_trimmed(client, path, payload, field):
    """The other half: padding around a real value is removed rather than refused.

    Without this the fix could be "reject anything with whitespace", which would
    refuse `" cutting "` — a paste from a spreadsheet, and exactly what the CSV
    importer's `parse_text` accepts and trims. The two writers have to agree.
    """
    created = await client.post(path, json={**payload, field: "  cutting  "})
    assert created.status_code == 201, created.text
    assert created.json()[field] == "cutting"

    patched = await client.patch(f"{path}/{created.json()['id']}", json={field: "  filing  "})
    assert patched.status_code == 200, patched.text
    assert patched.json()[field] == "filing"


async def test_display_item_optional_text_stores_blank_as_null(client):
    """Nullable free text takes `_normalize_series`' rule (#113): trimmed, and blank
    means "not recorded" rather than a value that happens to be spaces.

    Asserted through both a create and a PATCH, and on `scale` in particular because
    #127 will offer these columns as a distinct-values typeahead — where a stored
    `"  "` becomes an empty option nobody can select or remove.
    """
    created = await client.post(
        "/display-items",
        json={"name": "Blank Optionals", "category": "stand", "scale": "   ", "notes": "\t"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["scale"] is None
    assert created.json()["notes"] is None

    patched = await client.patch(
        f"/display-items/{created.json()['id']}", json={"scale": "  1/144  "}
    )
    assert patched.json()["scale"] == "1/144"
    assert (
        await client.patch(f"/display-items/{created.json()['id']}", json={"scale": "  "})
    ).json()["scale"] is None


async def test_an_order_line_new_item_holds_the_same_text_rule(client, retailer):
    """The third writer onto these columns (rule 1). `_build_catalog_row` had its own
    truthiness check, so the order path could store what the REST path now refuses."""
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "items": [
                {
                    "item_type": "display",
                    "quantity": 1,
                    "unit_price_minor": 900,
                    "currency_code": "AUD",
                    "new_item": {"name": "Whitespace Base", "category": "   "},
                }
            ],
        },
    )
    assert resp.status_code == 422, resp.text
    assert (await client.get("/display-items")).json() == []


# --- Withdrawing an upgrade application (#61, §3.6) ---------------------------------


async def _apply(client, upgrade_id: str, kit_id: str, quantity: int) -> dict:
    resp = await client.post(
        f"/upgrades/{upgrade_id}/apply", json={"kit_id": kit_id, "quantity": quantity}
    )
    assert resp.status_code == 201
    return resp.json()


async def test_withdraw_with_restore_returns_the_whole_quantity(client):
    """quantity_used > 1 on purpose: an application is one event, not a running
    balance, so restoring returns all of it."""
    upgrade = await _make_upgrade(client, 10)
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 3)
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 7

    resp = await client.delete(
        f"/upgrades/{upgrade['id']}/applications/{application['id']}",
        params={"restore_stock": True},
    )
    assert resp.status_code == 204
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 10
    assert (await client.get(f"/kits/{kit['id']}/applications")).json() == []


async def test_withdraw_without_restore_keeps_stock_spent(client):
    upgrade = await _make_upgrade(client, 5)
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 2)

    resp = await client.delete(
        f"/upgrades/{upgrade['id']}/applications/{application['id']}",
        params={"restore_stock": False},
    )
    assert resp.status_code == 204
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 3  # still spent
    assert (await client.get(f"/kits/{kit['id']}/applications")).json() == []


async def test_withdraw_without_the_restore_choice_is_422(http_client):
    """`restore_stock` has no default anywhere, deliberately (#61): omitting it is
    refused at the validation layer, before the service can act."""
    upgrade = await _make_upgrade(http_client, 5)
    kit = await _make_kit(http_client)
    application = await _apply(http_client, upgrade["id"], kit["id"], 2)

    resp = await http_client.delete(f"/upgrades/{upgrade['id']}/applications/{application['id']}")
    assert resp.status_code == 422
    assert any(err["loc"] == ["query", "restore_stock"] for err in resp.json()["detail"])
    # Nothing happened: the application survives and the stock stays spent.
    assert len((await http_client.get(f"/kits/{kit['id']}/applications")).json()) == 1
    assert (await http_client.get("/upgrades")).json()[0]["quantity_on_hand"] == 3


async def test_withdraw_under_the_wrong_upgrade_is_404(client):
    upgrade = await _make_upgrade(client, 5)
    other = (
        await client.post(
            "/upgrades",
            json={"name": "Water decals", "manufacturer": "Bandai", "quantity_on_hand": 1},
        )
    ).json()
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 2)

    resp = await client.delete(
        f"/upgrades/{other['id']}/applications/{application['id']}",
        params={"restore_stock": True},
    )
    assert resp.status_code == 404
    assert "does not belong" in resp.json()["detail"]
    assert len((await client.get(f"/kits/{kit['id']}/applications")).json()) == 1


async def test_withdraw_unknown_application_is_404(client):
    resp = await client.delete(
        f"/upgrades/{uuid.uuid4()}/applications/{uuid.uuid4()}",
        params={"restore_stock": True},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


async def test_withdraw_twice_second_is_404_and_stock_restores_once(client):
    upgrade = await _make_upgrade(client, 5)
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 2)

    path = f"/upgrades/{upgrade['id']}/applications/{application['id']}"
    assert (await client.delete(path, params={"restore_stock": True})).status_code == 204
    assert (await client.delete(path, params={"restore_stock": True})).status_code == 404
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 5  # 3 + 2, once


async def test_withdraw_unblocks_kit_delete(client):
    """#37's guard holds until the application is withdrawn, then releases —
    and its message points at a route that now exists."""
    upgrade = await _make_upgrade(client, 2)
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 1)

    resp = await client.delete(f"/kits/{kit['id']}")
    assert resp.status_code == 409
    assert "Withdraw the application" in resp.json()["detail"]

    resp = await client.delete(
        f"/upgrades/{upgrade['id']}/applications/{application['id']}",
        params={"restore_stock": False},
    )
    assert resp.status_code == 204
    assert (await client.delete(f"/kits/{kit['id']}")).status_code == 204
    assert (await client.get("/kits")).json() == []


async def test_withdraw_unblocks_upgrade_delete(client):
    """The same release on the other end of the join: `delete_catalog_item`'s
    applied-upgrade guard has nothing to hold once the applications are gone."""
    upgrade = await _make_upgrade(client, 2)
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 1)

    assert (await client.delete(f"/upgrades/{upgrade['id']}")).status_code == 409
    resp = await client.delete(
        f"/upgrades/{upgrade['id']}/applications/{application['id']}",
        params={"restore_stock": True},
    )
    assert resp.status_code == 204
    assert (await client.delete(f"/upgrades/{upgrade['id']}")).status_code == 204
    assert (await client.get("/upgrades")).json() == []


async def test_withdraw_restore_past_int4_ceiling_refused(client):
    """A reachable state: apply, then stock adjusted up to the column max. The
    restore would derive out of range, so the stored state refuses (409, the #74
    family), the application survives, and the no-restore withdrawal stays open."""
    upgrade = await _make_upgrade(client, 5)
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 2)
    resp = await client.post(f"/catalog/{upgrade['id']}/adjust", json={"delta": 2_147_483_644})
    assert resp.status_code == 200
    assert resp.json()["quantity_on_hand"] == 2_147_483_647

    path = f"/upgrades/{upgrade['id']}/applications/{application['id']}"
    resp = await client.delete(path, params={"restore_stock": True})
    assert resp.status_code == 409
    assert "would hold" in resp.json()["detail"]
    # The refusal is atomic: application still there, stock untouched.
    assert len((await client.get(f"/kits/{kit['id']}/applications")).json()) == 1
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 2_147_483_647

    assert (await client.delete(path, params={"restore_stock": False})).status_code == 204


async def test_kit_applications_listed_oldest_first_with_upgrade_embedded(client):
    upgrade = await _make_upgrade(client, 5)
    second = (
        await client.post(
            "/upgrades",
            json={"name": "Water decals", "manufacturer": "Bandai", "quantity_on_hand": 3},
        )
    ).json()
    kit = await _make_kit(client)
    first_app = await _apply(client, upgrade["id"], kit["id"], 1)
    second_app = await _apply(client, second["id"], kit["id"], 2)

    listed = (await client.get(f"/kits/{kit['id']}/applications")).json()
    assert [row["id"] for row in listed] == [first_app["id"], second_app["id"]]
    assert [row["upgrade"]["name"] for row in listed] == ["Metal thrusters", "Water decals"]

    # Withdrawing one leaves the other untouched — two rows seeded on purpose.
    resp = await client.delete(
        f"/upgrades/{upgrade['id']}/applications/{first_app['id']}",
        params={"restore_stock": False},
    )
    assert resp.status_code == 204
    listed = (await client.get(f"/kits/{kit['id']}/applications")).json()
    assert [row["id"] for row in listed] == [second_app["id"]]


async def test_kit_applications_empty_list_and_unknown_kit(client):
    kit = await _make_kit(client)
    assert (await client.get(f"/kits/{kit['id']}/applications")).json() == []
    assert (await client.get(f"/kits/{uuid.uuid4()}/applications")).status_code == 404


async def test_concurrent_double_withdraw_restores_stock_once(client):
    """Two simultaneous withdrawals of one application: the write gate and the
    upgrade row lock let exactly one through; the loser finds the row gone."""
    upgrade = await _make_upgrade(client, 5)
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 2)
    app_id = uuid.UUID(application["id"])

    async def attempt() -> str:
        try:
            async with session_scope() as session:
                await upgrades_service.withdraw_upgrade_application(
                    session, app_id, restore_stock=True
                )
            return "withdrawn"
        except NotFoundError:
            return "not_found"

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == ["not_found", "withdrawn"]
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 5  # 3 + 2, once


async def test_withdraw_racing_kit_delete_leaves_no_stock_unexplained(client):
    """Whichever order the gate serializes them in, the application is never
    cascaded away with its stock still counted as spent: either the delete is
    blocked by #37's guard and succeeds on retry, or it ran after the withdrawal."""
    upgrade = await _make_upgrade(client, 5)
    kit = await _make_kit(client)
    application = await _apply(client, upgrade["id"], kit["id"], 2)
    app_id = uuid.UUID(application["id"])
    kit_id = uuid.UUID(kit["id"])

    async def withdraw() -> str:
        async with session_scope() as session:
            await upgrades_service.withdraw_upgrade_application(session, app_id, restore_stock=True)
        return "withdrawn"

    async def delete() -> str:
        try:
            async with session_scope() as session:
                await kits_service.delete_kit(session, kit_id)
            return "deleted"
        except ConflictError:
            return "blocked"

    withdrew, deleted = await asyncio.gather(withdraw(), delete())
    assert withdrew == "withdrawn"
    assert (await client.get("/upgrades")).json()[0]["quantity_on_hand"] == 5
    if deleted == "blocked":
        assert (await client.delete(f"/kits/{kit['id']}")).status_code == 204
    assert (await client.get("/kits")).json() == []
