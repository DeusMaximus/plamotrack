"""Shipped dates (#95), on every write surface.

`shipped_at` is `received_at`'s mirror one pipeline stage earlier: suppliable at
entry, a gated/locked transition (`POST /orders/{id}/ship`, `mark_order_shipped`)
that advances pre_ordered/ordered kits to in_transit stamped with the same
instant, a PATCH correction that follows exactly the kits whose stamp *was* the
shipment, and the importer performing the same arrival under the same
change-not-cell rules. The one thing it never does is touch stock — `received_at`
stays the sole "stock was applied" proxy (rule 2) — which is also why shipping
by import is free on every order where receiving by import is refused on
catalog-bearing ones.

Deliberately absent, as decided on the branch: no cross-field validation between
`shipped_at`, `order_date` and `received_at` (#113's rule — the user owns the
values, and a service-side check would diverge from the importer), and no
un-shipping anywhere.

Layer assertions as in test_receipt_dates.py: schema refusals answer 422 with a
`detail` list, service refusals 422 with a `detail` string.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp
from tests.test_order_invariants import archive, consumable_line, make_consumable, order_row
from tests.test_order_lifecycle import kit_line, make_order
from tests.test_portability import actions, apply, preview
from tests.test_receipt_dates import mcp_kit_order

SHIP = "2026-05-02T09:15:00+10:00"
SHIP_INSTANT = datetime.fromisoformat(SHIP)
RECEIPT = "2026-05-04T14:30:00+10:00"
RECEIPT_INSTANT = datetime.fromisoformat(RECEIPT)


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def close_to_now(value: str) -> bool:
    return abs(datetime.now(UTC) - instant(value)) < timedelta(seconds=60)


async def order_kits(client, order: dict) -> list[dict]:
    ids = {kit_id for item in order["items"] for kit_id in item["spawned_kit_ids"]}
    rows = (await client.get("/kits")).json()
    return [row for row in rows if row["id"] in ids]


# --- entry (create_order) --------------------------------------------------------


async def test_create_shipped_lands_kits_in_transit_with_the_ship_stamp(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)], shipped_at=SHIP)
    assert instant(order["shipped_at"]) == SHIP_INSTANT
    assert order["received_at"] is None
    kits = await order_kits(client, order)
    assert len(kits) == 2
    for kit in kits:
        assert kit["status"] == "in_transit"
        assert instant(kit["status_updated_at"]) == SHIP_INSTANT


async def test_create_shipped_and_received_keeps_both_dates_and_received_wins(client, retailer):
    """The state where both instants exist: a backlog entry for a parcel whose
    whole journey is already history. Received decides the kit's landing; the
    ship date is a timeline record."""
    order = await make_order(
        client,
        retailer,
        [kit_line(quantity=1)],
        received=True,
        received_at=RECEIPT,
        shipped_at=SHIP,
    )
    assert instant(order["shipped_at"]) == SHIP_INSTANT
    assert instant(order["received_at"]) == RECEIPT_INSTANT
    (kit,) = await order_kits(client, order)
    assert kit["status"] == "backlog"
    assert instant(kit["status_updated_at"]) == RECEIPT_INSTANT


async def test_create_pending_leaves_shipped_at_null(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    assert order["shipped_at"] is None


async def test_a_kit_asserted_building_at_shipped_entry_keeps_the_entry_stamp(client, retailer):
    """`spawn_kits`' gate, driven through the ship path: the shipment is not when
    "building" began."""
    line = kit_line(quantity=1)
    line["kit"]["status"] = "building"
    order = await make_order(client, retailer, [line], shipped_at=SHIP)
    (kit,) = await order_kits(client, order)
    assert kit["status"] == "building"
    assert close_to_now(kit["status_updated_at"])


async def test_create_with_future_shipped_at_is_refused_and_nothing_persists(http_client, retailer):
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "shipped_at": future,
            "items": [kit_line(quantity=1)],
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str)  # the service refused (InvalidInputError)
    assert "shipped_at" in detail and "future" in detail
    assert (await http_client.get("/orders")).json() == []
    assert (await http_client.get("/kits")).json() == []


async def test_create_with_naive_shipped_at_is_refused(http_client, retailer):
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "shipped_at": "2026-05-02T09:15:00",
            "items": [kit_line(quantity=1)],
        },
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)  # the schema spoke (AwareDatetime)
    assert (await http_client.get("/orders")).json() == []


# --- the ship transition ---------------------------------------------------------


async def test_ship_moves_pipeline_kits_to_in_transit_and_stamps_them(client, retailer):
    """The advance and its boundary in one order: an ordered kit and a
    pre_ordered kit move, a building kit (already progressed) does not, and an
    in_transit kit (already there) keeps its own stamp."""
    order = await make_order(client, retailer, [kit_line(quantity=4)])
    kits = await order_kits(client, order)
    building, transit, ordered, pre = kits
    for kit, status in ((building, "building"), (transit, "in_transit"), (pre, "pre_ordered")):
        resp = await client.patch(f"/kits/{kit['id']}", json={"status": status})
        assert resp.status_code == 200, resp.text
    transit_before = (await client.get(f"/kits/{transit['id']}")).json()["status_updated_at"]

    resp = await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
    assert resp.status_code == 200, resp.text
    assert instant(resp.json()["shipped_at"]) == SHIP_INSTANT

    after = {k["id"]: k for k in (await client.get("/kits")).json()}
    for moved in (ordered, pre):
        assert after[moved["id"]]["status"] == "in_transit"
        assert instant(after[moved["id"]]["status_updated_at"]) == SHIP_INSTANT
    assert after[building["id"]]["status"] == "building"
    assert after[transit["id"]]["status"] == "in_transit"
    assert after[transit["id"]]["status_updated_at"] == transit_before, (
        "a kit already in transit is not re-stamped"
    )


@pytest.mark.parametrize("body", [None, {}, {"shipped_at": None}], ids=["no body", "{}", "null"])
async def test_ship_without_a_date_means_now_in_all_three_spellings(client, retailer, body):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    resp = await client.post(
        f"/orders/{order['id']}/ship", **({} if body is None else {"json": body})
    )
    assert resp.status_code == 200, resp.text
    shipped = resp.json()
    assert close_to_now(shipped["shipped_at"])
    (kit,) = await order_kits(client, shipped)
    # One value, not two clock reads: kit stamp equals the order's instant.
    assert instant(kit["status_updated_at"]) == instant(shipped["shipped_at"])


async def test_double_ship_is_a_conflict(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    assert (await http_client.post(f"/orders/{order['id']}/ship")).status_code == 200
    resp = await http_client.post(f"/orders/{order['id']}/ship")
    assert resp.status_code == 409
    assert "already marked shipped" in resp.json()["detail"]


async def test_ship_after_receive_records_the_date_and_moves_nothing(client, retailer):
    """Legal by decision: the ship date is chronologically prior information. The
    kits are already in backlog with the receipt stamp and stay exactly there."""
    order = await make_order(
        client, retailer, [kit_line(quantity=1)], received=True, received_at=RECEIPT
    )
    resp = await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
    assert resp.status_code == 200, resp.text
    assert instant(resp.json()["shipped_at"]) == SHIP_INSTANT
    (kit,) = await order_kits(client, resp.json())
    assert kit["status"] == "backlog"
    assert instant(kit["status_updated_at"]) == RECEIPT_INSTANT


async def test_receive_without_ship_stays_legal_and_derives_nothing(client, retailer):
    """The common case for after-the-fact entry, and the never-backfill rule:
    receiving is not evidence of a shipment worth fabricating."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    resp = await client.post(f"/orders/{order['id']}/receive")
    assert resp.status_code == 200
    assert resp.json()["shipped_at"] is None
    (kit,) = await order_kits(client, resp.json())
    assert kit["status"] == "backlog"


async def test_ship_with_a_future_date_is_refused(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = await http_client.post(f"/orders/{order['id']}/ship", json={"shipped_at": future})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str) and "shipped_at" in detail and "future" in detail
    stored = (await http_client.get(f"/orders/{order['id']}")).json()
    assert stored["shipped_at"] is None
    (kit,) = await order_kits(http_client, stored)
    assert kit["status"] == "ordered", "no advance happened either"


async def test_ship_with_a_naive_date_is_refused_by_the_schema(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    resp = await http_client.post(
        f"/orders/{order['id']}/ship", json={"shipped_at": "2026-05-02T09:15:00"}
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)


# --- correction (PATCH) ----------------------------------------------------------


async def test_patch_corrects_the_ship_date_and_restamps_only_untouched_kits(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    assert (
        await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
    ).status_code == 200
    kits = await order_kits(client, order)
    moved, untouched = kits
    # One kit arrives early and gets dragged onward — its stamp is the drag's own.
    resp = await client.patch(f"/kits/{moved['id']}", json={"status": "backlog"})
    assert resp.status_code == 200, resp.text
    moved_stamp = (await client.get(f"/kits/{moved['id']}")).json()["status_updated_at"]

    corrected = "2026-05-03T08:00:00+10:00"
    resp = await client.patch(f"/orders/{order['id']}", json={"shipped_at": corrected})
    assert resp.status_code == 200, resp.text
    assert instant(resp.json()["shipped_at"]) == instant(corrected)

    after = {k["id"]: k for k in (await client.get("/kits")).json()}
    assert instant(after[untouched["id"]]["status_updated_at"]) == instant(corrected)
    assert after[moved["id"]]["status_updated_at"] == moved_stamp


async def test_patch_shipped_at_on_an_unshipped_order_is_a_conflict(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    resp = await http_client.patch(f"/orders/{order['id']}", json={"shipped_at": SHIP})
    assert resp.status_code == 409
    assert "not marked shipped yet" in resp.json()["detail"]
    assert (await http_client.get(f"/orders/{order['id']}")).json()["shipped_at"] is None


async def test_patch_shipped_at_null_is_refused(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    assert (await http_client.post(f"/orders/{order['id']}/ship")).status_code == 200
    resp = await http_client.patch(f"/orders/{order['id']}", json={"shipped_at": None})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str) and "un-shipping" in detail
    assert (await http_client.get(f"/orders/{order['id']}")).json()["shipped_at"] is not None


async def test_patch_ship_correction_into_the_future_is_refused(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    assert (
        await http_client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
    ).status_code == 200
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = await http_client.patch(f"/orders/{order['id']}", json={"shipped_at": future})
    assert resp.status_code == 422
    assert "future" in resp.json()["detail"]
    assert (
        instant((await http_client.get(f"/orders/{order['id']}")).json()["shipped_at"])
        == SHIP_INSTANT
    )


async def test_a_ship_correction_never_takes_a_receipt_stamped_at_the_same_instant(
    client, retailer
):
    """Round one's P2. A ship and a receive can legitimately share an instant —
    two date inputs on the same calendar day both serialise as one local
    midnight — and the receipt owns the backlog kit. The ship correction
    therefore follows only kits still in_transit whose stamp equals the old
    shipment (the UI's own promise); reusing the receipt helper's
    stamp-equality-alone rule let a shipped_at correction rewrite receipt
    history."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    same = "2026-05-02T00:00:00+10:00"
    assert (
        await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": same})
    ).status_code == 200
    assert (
        await client.post(f"/orders/{order['id']}/receive", json={"received_at": same})
    ).status_code == 200
    (kit,) = await order_kits(client, order)
    before = (await client.get(f"/kits/{kit['id']}")).json()
    assert before["status"] == "backlog"
    assert instant(before["status_updated_at"]) == instant(same)

    corrected = "2026-05-03T00:00:00+10:00"
    resp = await client.patch(f"/orders/{order['id']}", json={"shipped_at": corrected})
    assert resp.status_code == 200, resp.text
    after = (await client.get(f"/kits/{kit['id']}")).json()
    assert after["status"] == "backlog"
    assert instant(after["status_updated_at"]) == instant(same), (
        "the backlog kit's stamp is the receipt's, not the corrected shipment's"
    )


async def test_a_line_added_to_a_shipped_order_spawns_in_transit_kits(client, retailer):
    """The spawn path reads the order's ship state on an edit, exactly as it
    reads the receipt one stage later."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    assert (
        await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
    ).status_code == 200
    stored = (await client.get(f"/orders/{order['id']}")).json()
    item = stored["items"][0]
    before = {k["id"] for k in (await client.get("/kits")).json()}
    resp = await client.patch(
        f"/orders/{order['id']}",
        json={
            "items": [
                {
                    "id": item["id"],
                    "item_type": "kit",
                    "quantity": 2,
                    "unit_price_minor": item["unit_price_minor"],
                    "currency_code": item["currency_code"],
                    "kit": {"name": "Zaku II", "grade": "HG"},
                }
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    new = next(k for k in (await client.get("/kits")).json() if k["id"] not in before)
    assert new["status"] == "in_transit"
    assert instant(new["status_updated_at"]) == SHIP_INSTANT


# --- MCP -------------------------------------------------------------------------


async def test_mcp_mark_order_shipped_backdated(client):
    async with Client(mcp) as mcp_client:
        order = (await mcp_client.call_tool("create_order", mcp_kit_order())).data
        shipped = (
            await mcp_client.call_tool(
                "mark_order_shipped", {"order_id": order["id"], "shipped_at": SHIP}
            )
        ).data
    assert instant(shipped["shipped_at"]) == SHIP_INSTANT
    (kit,) = await order_kits(client, shipped)
    assert kit["status"] == "in_transit"
    assert instant(kit["status_updated_at"]) == SHIP_INSTANT


async def test_mcp_create_order_shipped(client):
    async with Client(mcp) as mcp_client:
        order = (await mcp_client.call_tool("create_order", mcp_kit_order(shipped_at=SHIP))).data
    assert instant(order["shipped_at"]) == SHIP_INSTANT
    (kit,) = await order_kits(client, order)
    assert kit["status"] == "in_transit"


async def test_mcp_naive_shipped_at_is_a_tool_error():
    async with Client(mcp) as mcp_client:
        order = (await mcp_client.call_tool("create_order", mcp_kit_order())).data
        with pytest.raises(ToolError, match="shipped_at.*offset"):
            await mcp_client.call_tool(
                "mark_order_shipped",
                {"order_id": order["id"], "shipped_at": "2026-05-02T09:15:00"},
            )


# --- the importer ----------------------------------------------------------------
#
# Shipping never moves stock, so — unlike the receipt — the null -> non-null
# direction imports freely on every order, catalog lines included. The same
# change-not-cell rules apply: restated values are no-ops, creates are restores,
# clearing mirrors the everywhere-refusal of un-shipping, and the future is
# refused with the shared calendar predicate.


async def test_ship_by_import_advances_and_stamps_the_kits(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    content = archive(orders=[order_row(order, retailer, shipped_at=SHIP)])
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text

    assert (
        instant((await client.get(f"/orders/{order['id']}")).json()["shipped_at"]) == SHIP_INSTANT
    )
    (kit,) = await order_kits(client, order)
    kit = (await client.get(f"/kits/{kit['id']}")).json()
    assert kit["status"] == "in_transit"
    assert instant(kit["status_updated_at"]) == SHIP_INSTANT


async def test_ship_by_import_is_free_on_a_catalog_order_and_moves_no_stock(client, retailer):
    """The order shape whose *receipt* the importer refuses. Shipping carries no
    stock semantics, so the same sheet is fine here — and the count proves it."""
    consumable = await make_consumable(client)
    order = await make_order(client, retailer, [consumable_line(consumable["id"])])
    content = archive(orders=[order_row(order, retailer, shipped_at=SHIP)])
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    stored = (await client.get(f"/orders/{order['id']}")).json()
    assert instant(stored["shipped_at"]) == SHIP_INSTANT
    assert stored["received_at"] is None
    rows = (await client.get("/consumables")).json()
    assert next(r["quantity_on_hand"] for r in rows if r["id"] == consumable["id"]) == 0


async def test_unship_by_import_is_refused(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    assert (
        await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
    ).status_code == 200
    stored = (await client.get(f"/orders/{order['id']}")).json()

    # `order_row` states no shipped_at, and the spec-driven header carries the
    # column — so the blank cell IS the clearing instruction under the
    # blank-means-empty rule, which is exactly the shape being refused.
    content = archive(orders=[order_row(stored, retailer)])
    plan = await preview(client, content)
    assert actions(plan, "orders") == ["error"], plan["tables"]
    error = plan["tables"][0]["rows"][0]["error"]
    assert error.startswith("shipped_at:") and "un-shipping" in error
    assert (await apply(client, content)).status_code == 409
    assert (
        instant((await client.get(f"/orders/{order['id']}")).json()["shipped_at"]) == SHIP_INSTANT
    )


@pytest.mark.parametrize(
    "state", ["arrival", "correction"], ids=["null to future", "set to future"]
)
async def test_a_future_ship_date_by_import_is_refused(client, retailer, state):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    if state == "correction":
        assert (
            await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
        ).status_code == 200
    stored = (await client.get(f"/orders/{order['id']}")).json()

    content = archive(orders=[order_row(stored, retailer, shipped_at="2099-01-02T09:00:00Z")])
    plan = await preview(client, content)
    assert actions(plan, "orders") == ["error"], plan["tables"]
    error = plan["tables"][0]["rows"][0]["error"]
    assert error.startswith("shipped_at:") and "future" in error
    assert (await apply(client, content)).status_code == 409
    stored_after = (await client.get(f"/orders/{order['id']}")).json()
    if state == "correction":
        assert instant(stored_after["shipped_at"]) == SHIP_INSTANT
    else:
        assert stored_after["shipped_at"] is None


async def test_a_restated_ship_date_is_a_no_op_and_restamps_nothing(client, retailer):
    """Change-not-cell: a full-archive re-import of a shipped order moves neither
    the order nor the kits it advanced (#116's boundary holds here too)."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    assert (
        await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
    ).status_code == 200
    stored = (await client.get(f"/orders/{order['id']}")).json()
    (kit,) = await order_kits(client, stored)
    stamp_before = (await client.get(f"/kits/{kit['id']}")).json()["status_updated_at"]

    content = archive(orders=[order_row(stored, retailer, shipped_at=stored["shipped_at"])])
    plan = await preview(client, content)
    assert plan["blocking_errors"] == [], plan
    assert (await apply(client, content)).status_code == 200
    assert (await client.get(f"/kits/{kit['id']}")).json()["status_updated_at"] == stamp_before


async def test_ship_and_receive_in_one_upload_land_in_backlog_with_the_receipt(client, retailer):
    """Both instants in one row: the ship advance runs first, the receipt advance
    carries the kit the rest of the way — the live writers' terminal state."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    content = archive(orders=[order_row(order, retailer, shipped_at=SHIP, received_at=RECEIPT)])
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    stored = (await client.get(f"/orders/{order['id']}")).json()
    assert instant(stored["shipped_at"]) == SHIP_INSTANT
    assert instant(stored["received_at"]) == RECEIPT_INSTANT
    (kit,) = await order_kits(client, stored)
    kit = (await client.get(f"/kits/{kit['id']}")).json()
    assert kit["status"] == "backlog"
    assert instant(kit["status_updated_at"]) == RECEIPT_INSTANT


async def test_a_ship_correction_between_preview_and_apply_stales_the_hash(client, retailer):
    """The P3 lesson from round five, applied to the new instant: `_Spawn`
    carries `shipped_at` and the fingerprint hashes it, so a correction landing
    between preview and apply 409s instead of stamping a value the operator
    never saw."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    assert (
        await client.post(f"/orders/{order['id']}/ship", json={"shipped_at": SHIP})
    ).status_code == 200
    stored = (await client.get(f"/orders/{order['id']}")).json()
    item = stored["items"][0]
    line = {
        "id": item["id"],
        "order_id": order["id"],
        "item_type": "kit",
        "quantity": "2",
        "unit_price_minor": str(item["unit_price_minor"]),
        "currency_code": item["currency_code"],
        "kit_name": "Zaku II",
        "kit_grade": "HG",
    }
    content = archive(order_items=[line])
    old_hash = (await preview(client, content))["plan_hash"]

    corrected = "2026-05-03T08:00:00+10:00"
    assert (
        await client.patch(f"/orders/{order['id']}", json={"shipped_at": corrected})
    ).status_code == 200

    stale = await apply(client, content, plan_hash=old_hash)
    assert stale.status_code == 409, stale.text
    assert "preview again" in stale.json()["detail"]

    before = {k["id"] for k in (await client.get("/kits")).json()}
    assert (await apply(client, content)).status_code == 200
    new = next(k for k in (await client.get("/kits")).json() if k["id"] not in before)
    assert new["status"] == "in_transit"
    assert instant(new["status_updated_at"]) == instant(corrected)


# --- #119: the derived advances are bound by the plan hash -----------------------
#
# The fingerprint binds the `_Advance` descriptors — kit id, before-status,
# landing status, stamp — so the set of pre-existing kits an approved preview
# says will move IS the set the apply moves. Before #119 the advance re-decided
# from live `kit.status` at apply time, after the hash check: a kit progressed
# between preview and apply was silently skipped (or a fresh one silently
# taken) under a hash that still matched. Both siblings — ship and receive —
# went through one structural change, so both sit in each matrix here.


@pytest.mark.parametrize(
    "column, value", [("shipped_at", SHIP), ("received_at", RECEIPT)], ids=["ship", "receive"]
)
async def test_a_kit_progressed_between_preview_and_apply_stales_the_hash(
    client, retailer, column, value
):
    """The #119 reproduction: preview a null -> set flip, progress the order's
    kit through the app, apply the old hash. The derived advance the operator
    approved no longer exists, so the apply must 409 — not mark the order
    shipped/received while silently moving nothing."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    (kit,) = await order_kits(client, order)
    content = archive(orders=[order_row(order, retailer, **{column: value})])
    old_hash = (await preview(client, content))["plan_hash"]

    assert (
        await client.patch(f"/kits/{kit['id']}", json={"status": "building"})
    ).status_code == 200

    stale = await apply(client, content, plan_hash=old_hash)
    assert stale.status_code == 409, stale.text
    assert "preview again" in stale.json()["detail"]
    stored = (await client.get(f"/orders/{order['id']}")).json()
    assert stored[column] is None, "the stale apply landed nothing"

    # The honest path after re-previewing: the flip lands, and the progressed
    # kit keeps the state the user gave it — same as the live writers.
    fresh = await preview(client, content)
    assert fresh["derived"]["kits_advanced"] == 0
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_advanced"] == 0
    assert instant((await client.get(f"/orders/{order['id']}")).json()[column]) == instant(value)
    assert (await client.get(f"/kits/{kit['id']}")).json()["status"] == "building"


@pytest.mark.parametrize(
    "column, value, landing",
    [("shipped_at", SHIP, "in_transit"), ("received_at", RECEIPT, "backlog")],
    ids=["ship", "receive"],
)
async def test_a_still_eligible_move_between_preview_and_apply_stales_the_hash(
    client, retailer, column, value, landing
):
    """The value axis on the descriptor's before-status: ordered -> pre_ordered
    keeps the kit eligible, so the *set* of advances is unchanged — but the
    descriptor the operator approved said "ordered", and the plan is bound to
    what it said, not merely to how many kits it moves."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    (kit,) = await order_kits(client, order)
    content = archive(orders=[order_row(order, retailer, **{column: value})])
    old_hash = (await preview(client, content))["plan_hash"]

    assert (
        await client.patch(f"/kits/{kit['id']}", json={"status": "pre_ordered"})
    ).status_code == 200

    stale = await apply(client, content, plan_hash=old_hash)
    assert stale.status_code == 409, stale.text
    # Re-previewed, the advance is real again: the still-eligible kit moves.
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_advanced"] == 1
    kit = (await client.get(f"/kits/{kit['id']}")).json()
    assert kit["status"] == landing
    assert instant(kit["status_updated_at"]) == instant(value)


@pytest.mark.parametrize(
    "column, value", [("shipped_at", SHIP), ("received_at", RECEIPT)], ids=["ship", "receive"]
)
async def test_a_kit_turning_eligible_between_preview_and_apply_stales_the_hash(
    client, retailer, column, value
):
    """The other direction: the preview showed *no* derived movement (the kit
    was building), then the kit returns to ordered before the apply. Unbound,
    the apply would move a kit the operator was never told about; bound, it
    409s."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    (kit,) = await order_kits(client, order)
    assert (
        await client.patch(f"/kits/{kit['id']}", json={"status": "building"})
    ).status_code == 200
    content = archive(orders=[order_row(order, retailer, **{column: value})])
    old_hash = (await preview(client, content))["plan_hash"]

    assert (await client.patch(f"/kits/{kit['id']}", json={"status": "ordered"})).status_code == 200

    stale = await apply(client, content, plan_hash=old_hash)
    assert stale.status_code == 409, stale.text
    assert (await client.get(f"/kits/{kit['id']}")).json()["status"] == "ordered"


async def test_the_preview_names_the_ship_advance_and_the_result_counts_it(client, retailer):
    """The advance the plan binds is also the advance the operator can *see*:
    the derived count, the per-order message, and the result line. The building
    kit on the same order is the boundary — outside the eligible set, outside
    the count, untouched by the apply."""
    order = await make_order(client, retailer, [kit_line(quantity=3)])
    kits = await order_kits(client, order)
    progressed, *pipeline = kits
    assert (
        await client.patch(f"/kits/{progressed['id']}", json={"status": "building"})
    ).status_code == 200

    content = archive(orders=[order_row(order, retailer, shipped_at=SHIP)])
    plan = await preview(client, content)
    assert plan["derived"]["kits_advanced"] == 2
    (row,) = plan["tables"][0]["rows"]
    assert "marking this order shipped moves 2 kit(s) to in transit" in row["messages"]

    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_advanced"] == 2
    after = {k["id"]: k["status"] for k in (await client.get("/kits")).json()}
    assert after[progressed["id"]] == "building"
    assert [after[k["id"]] for k in pipeline] == ["in_transit", "in_transit"]


async def test_a_combined_flip_previews_one_advance_per_kit_landing_in_backlog(client, retailer):
    """Ship and receive in one row compose into a single terminal descriptor —
    the pass through in_transit is unobservable inside one transaction, so the
    kit is counted once and the message says where it actually lands."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    content = archive(orders=[order_row(order, retailer, shipped_at=SHIP, received_at=RECEIPT)])
    plan = await preview(client, content)
    assert plan["derived"]["kits_advanced"] == 1
    (row,) = plan["tables"][0]["rows"]
    assert "marking this order received moves 1 kit(s) to backlog" in row["messages"]
    assert not any("in transit" in message for message in row["messages"])
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    assert resp.json()["kits_advanced"] == 1


@pytest.mark.parametrize("column", ["shipped_at", "received_at"], ids=["ship", "receive"])
async def test_a_correction_by_import_never_advances_a_regressed_kit(client, retailer, column):
    """Change-not-cell, now read at plan time (`_newly_set`): a correction
    between two non-null instants is not a transition, so a kit the user moved
    back into the pipeline stays exactly where they put it — no descriptor, no
    movement. Green before #119 too: this is the guard the descriptors
    inherited, pinned so the move to plan time cannot have dropped it."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    verb = "ship" if column == "shipped_at" else "receive"
    assert (
        await client.post(f"/orders/{order['id']}/{verb}", json={column: SHIP})
    ).status_code == 200
    (kit,) = await order_kits(client, order)
    assert (await client.patch(f"/kits/{kit['id']}", json={"status": "ordered"})).status_code == 200

    stored = (await client.get(f"/orders/{order['id']}")).json()
    corrected = "2026-05-03T08:00:00+10:00"
    content = archive(orders=[order_row(stored, retailer, **{column: corrected})])
    resp = await apply(client, content)
    assert resp.status_code == 200, resp.text
    assert instant((await client.get(f"/orders/{order['id']}")).json()[column]) == instant(
        corrected
    )
    assert (await client.get(f"/kits/{kit['id']}")).json()["status"] == "ordered"


async def test_add_only_plans_no_advance_for_a_matched_order(client, retailer):
    """A matched order is a SKIP under add_only — its shipped_at cell describes
    nothing that will land, so no advance is derived and the apply moves
    nothing."""
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    content = archive(orders=[order_row(order, retailer, shipped_at=SHIP)])
    plan = await preview(client, content, mode="add_only")
    assert actions(plan, "orders") == ["skip"]
    assert plan["derived"]["kits_advanced"] == 0
    resp = await apply(client, content, mode="add_only")
    assert resp.status_code == 200, resp.text
    assert (await client.get(f"/orders/{order['id']}")).json()["shipped_at"] is None
    (kit,) = await order_kits(client, order)
    assert (await client.get(f"/kits/{kit['id']}")).json()["status"] == "ordered"


async def test_an_archive_of_a_shipped_order_round_trips(client, retailer):
    """Create-is-a-restore for the new column, in both creating modes."""
    order = await make_order(client, retailer, [kit_line(quantity=1)], shipped_at=SHIP)
    exported = (await client.get("/export/archive")).content
    for mode, extra in (("replace_all", {"confirm": "REPLACE"}), ("merge", {})):
        resp = await apply(client, exported, mode=mode, **extra)
        assert resp.status_code == 200, f"{mode}: {resp.text}"
        stored = (await client.get(f"/orders/{order['id']}")).json()
        assert instant(stored["shipped_at"]) == SHIP_INSTANT, mode
        (kit,) = await order_kits(client, stored)
        kit = (await client.get(f"/kits/{kit['id']}")).json()
        assert kit["status"] == "in_transit", mode
        assert instant(kit["status_updated_at"]) == SHIP_INSTANT, mode
