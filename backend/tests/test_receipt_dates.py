"""Backdatable receipt dates (#93), on every write surface.

`received_at` was always stamped "now", so a collection logged after the fact
carried arrival times clustered in the minutes the data entry took. These pin the
new contract: entry and receive accept an arrival instant, a PATCH corrects one
already set (and only one already set), the kits a receipt advances carry the same
instant as the order, and a correction follows exactly the kits whose stamp *was*
the receipt.

Layer assertions: a schema refusal (pydantic) answers 422 with a `detail` list; a
service refusal (`InvalidInputError`) answers 422 with a `detail` string. The
tests assert the shape as well as the status, so a rule migrating between layers
is a visible change rather than a silent one.
"""

from datetime import UTC, datetime, time, timedelta, timezone

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.mcp import mcp
from tests.test_order_lifecycle import kit_line, make_order

BACKDATE = "2026-05-04T14:30:00+10:00"
BACKDATE_INSTANT = datetime.fromisoformat(BACKDATE)


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def close_to_now(value: str) -> bool:
    return abs(datetime.now(UTC) - instant(value)) < timedelta(seconds=60)


async def order_kits(client, order: dict) -> list[dict]:
    ids = {kit_id for item in order["items"] for kit_id in item["spawned_kit_ids"]}
    rows = (await client.get("/kits")).json()
    return [row for row in rows if row["id"] in ids]


# --- entry (create_order) --------------------------------------------------------


async def test_create_received_with_backdate_stores_it_and_stamps_spawned_kits(client, retailer):
    order = await make_order(
        client, retailer, [kit_line(quantity=2)], received=True, received_at=BACKDATE
    )
    assert instant(order["received_at"]) == BACKDATE_INSTANT
    kits = await order_kits(client, order)
    assert len(kits) == 2
    for kit in kits:
        assert kit["status"] == "backlog"
        assert instant(kit["status_updated_at"]) == BACKDATE_INSTANT


async def test_create_received_without_a_date_still_defaults_to_now(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)], received=True)
    assert close_to_now(order["received_at"])
    (kit,) = await order_kits(client, order)
    # The same instant, not merely the same minute: order and kit are stamped from
    # one value, so a drift here means two clocks were read.
    assert instant(kit["status_updated_at"]) == instant(order["received_at"])


async def test_create_pending_leaves_received_at_null(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    assert order["received_at"] is None


async def test_a_date_on_an_unreceived_create_is_refused_not_ignored(http_client, retailer):
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "received_at": BACKDATE,
            "items": [kit_line(quantity=1)],
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, list)  # the schema spoke, not the service
    assert "received=true" in str(detail)
    assert (await http_client.get("/orders")).json() == []


async def test_create_with_future_received_at_is_refused_and_nothing_persists(
    http_client, retailer
):
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "received": True,
            "received_at": future,
            "items": [kit_line(quantity=1)],
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str)  # the service refused (InvalidInputError)
    assert "future" in detail
    assert (await http_client.get("/orders")).json() == []
    assert (await http_client.get("/kits")).json() == []


async def test_create_with_naive_received_at_is_refused(http_client, retailer):
    resp = await http_client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "currency_code": "AUD",
            "received": True,
            "received_at": "2026-05-04T14:30:00",  # no offset
            "items": [kit_line(quantity=1)],
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, list)  # pydantic's AwareDatetime, at the schema layer
    assert "received_at" in str(detail)


async def test_create_backdate_before_order_date_is_deliberately_allowed(client, retailer):
    # order_date is a plain date with no offset, so "earlier than the order" is not
    # well-defined across time zones — a same-day purchase entered in UTC+10 holds
    # a receipt instant that is "yesterday" in UTC. Odd is allowed (#93).
    order = await make_order(
        client,
        retailer,
        [kit_line(quantity=1)],
        received=True,
        received_at="2026-07-15T10:00:00+10:00",
    )
    assert instant(order["received_at"]) == instant("2026-07-15T10:00:00+10:00")


async def test_create_received_kit_asserted_building_keeps_the_entry_stamp(client, retailer):
    # A kit whose status the entry itself asserts (building) was not moved by the
    # arrival — the backdate is when it came into hand, not when the build began,
    # so it keeps the "when you told me" default rather than borrowing the receipt.
    line = kit_line(quantity=1)
    line["kit"]["status"] = "building"
    order = await make_order(client, retailer, [line], received=True, received_at=BACKDATE)
    (kit,) = await order_kits(client, order)
    assert kit["status"] == "building"
    assert instant(kit["status_updated_at"]) != BACKDATE_INSTANT
    assert close_to_now(kit["status_updated_at"])


# --- receive ---------------------------------------------------------------------


async def test_receive_with_backdate_stamps_order_and_kits(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    resp = await client.post(f"/orders/{order['id']}/receive", json={"received_at": BACKDATE})
    assert resp.status_code == 200
    received = resp.json()
    assert instant(received["received_at"]) == BACKDATE_INSTANT
    kits = await order_kits(client, received)
    assert len(kits) == 2
    for kit in kits:
        assert kit["status"] == "backlog"
        assert instant(kit["status_updated_at"]) == BACKDATE_INSTANT


@pytest.mark.parametrize(
    "body",
    [None, {}, {"received_at": None}],
    ids=["no-body", "empty-object", "explicit-null"],
)
async def test_receive_without_a_date_behaves_exactly_as_before(client, retailer, body):
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    if body is None:
        resp = await client.post(f"/orders/{order['id']}/receive")
    else:
        resp = await client.post(f"/orders/{order['id']}/receive", json=body)
    assert resp.status_code == 200, resp.text
    assert close_to_now(resp.json()["received_at"])


async def test_receive_with_future_date_is_refused_and_order_stays_pending(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = await http_client.post(f"/orders/{order['id']}/receive", json={"received_at": future})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str) and "future" in detail
    fresh = (await http_client.get(f"/orders/{order['id']}")).json()
    assert fresh["received_at"] is None
    (kit,) = await order_kits(http_client, fresh)
    assert kit["status"] == "ordered"


async def test_receive_with_naive_date_is_refused_by_the_schema(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    resp = await http_client.post(
        f"/orders/{order['id']}/receive", json={"received_at": "2026-05-04T14:30:00"}
    )
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)


async def test_receipt_late_today_in_a_behind_offset_is_not_future(client, retailer):
    # The rule is a calendar date judged in the datetime's OWN offset, not an
    # instant against the server clock: 23:59 today in UTC-12 is usually a future
    # *instant*, but it is still "today" where the caller says the box arrived.
    tz = timezone(timedelta(hours=-12))
    stamp = datetime.combine(datetime.now(tz).date(), time(23, 59, 59), tzinfo=tz)
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    resp = await client.post(
        f"/orders/{order['id']}/receive", json={"received_at": stamp.isoformat()}
    )
    assert resp.status_code == 200, resp.text
    assert instant(resp.json()["received_at"]) == stamp


class _PinnedDatetime(datetime):
    """`datetime` with `now` frozen to one instant, for the ahead-offset case below.

    20:00Z is already 10:00 on the *next* calendar day in UTC+14, so the pinned
    instant makes "today in an ahead offset, while UTC is still on yesterday's
    date" true at any wall-clock hour instead of fourteen out of twenty-four."""

    PINNED = datetime(2026, 8, 20, 20, 0, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):  # noqa: ANN001 - signature mirrors datetime.now
        if tz is None:
            return cls.PINNED.replace(tzinfo=None)
        return cls.PINNED.astimezone(tz)


async def test_receipt_today_in_an_ahead_offset_is_judged_by_its_own_calendar(
    client, retailer, monkeypatch
):
    # P3-1 (Cursor round 1 on PR #111): the UTC-12 test above cannot distinguish
    # `now(received_at.tzinfo)` from `now(UTC)` — a behind offset's calendar date
    # is never ahead of UTC's, at any hour. The discriminating case is the mirror:
    # an honest "today" in UTC+14 whose date UTC has not reached yet. Real clocks
    # only produce that for part of each day, so the clock is pinned rather than
    # hoped at (rule: pin the timing).
    monkeypatch.setattr("app.services.orders.datetime", _PinnedDatetime)
    stamp = "2026-08-21T00:30:00+14:00"  # today in +14; UTC's date is still the 20th
    order = await make_order(client, retailer, [kit_line(quantity=1)])
    resp = await client.post(f"/orders/{order['id']}/receive", json={"received_at": stamp})
    assert resp.status_code == 200, resp.text
    assert instant(resp.json()["received_at"]) == instant(stamp)


async def test_receive_backdated_still_skips_progressed_kits(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)])
    first, second = await order_kits(client, order)
    moved = (await client.patch(f"/kits/{first['id']}", json={"status": "building"})).json()

    resp = await client.post(f"/orders/{order['id']}/receive", json={"received_at": BACKDATE})
    assert resp.status_code == 200
    kits = {kit["id"]: kit for kit in await order_kits(client, resp.json())}
    assert kits[first["id"]]["status"] == "building"
    assert instant(kits[first["id"]]["status_updated_at"]) == instant(moved["status_updated_at"])
    assert kits[second["id"]]["status"] == "backlog"
    assert instant(kits[second["id"]]["status_updated_at"]) == BACKDATE_INSTANT


async def test_double_receive_conflicts_even_with_a_backdate(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=1)], received=True)
    resp = await client.post(f"/orders/{order['id']}/receive", json={"received_at": BACKDATE})
    assert resp.status_code == 409


# --- correction (PATCH /orders/{id}) ---------------------------------------------


async def test_patch_corrects_the_receipt_and_restamps_only_untouched_kits(client, retailer):
    order = await make_order(client, retailer, [kit_line(quantity=2)], received=True)
    first, second = await order_kits(client, order)
    # One kit moves on after the receipt: its stamp is now the drag's, not the
    # receipt's, and a later correction has no business rewriting it.
    moved = (await client.patch(f"/kits/{first['id']}", json={"status": "building"})).json()

    resp = await client.patch(f"/orders/{order['id']}", json={"received_at": BACKDATE})
    assert resp.status_code == 200
    assert instant(resp.json()["received_at"]) == BACKDATE_INSTANT

    kits = {kit["id"]: kit for kit in await order_kits(client, resp.json())}
    assert instant(kits[second["id"]]["status_updated_at"]) == BACKDATE_INSTANT
    assert instant(kits[first["id"]]["status_updated_at"]) == instant(moved["status_updated_at"])


async def test_patch_received_at_on_a_pending_order_is_a_conflict(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)])
    resp = await http_client.patch(f"/orders/{order['id']}", json={"received_at": BACKDATE})
    assert resp.status_code == 409
    assert "receive" in resp.json()["detail"]
    assert (await http_client.get(f"/orders/{order['id']}")).json()["received_at"] is None


async def test_patch_cannot_clear_received_at(http_client, retailer):
    order = await make_order(http_client, retailer, [kit_line(quantity=1)], received=True)
    resp = await http_client.patch(f"/orders/{order['id']}", json={"received_at": None})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, str) and "cleared" in detail
    fresh = (await http_client.get(f"/orders/{order['id']}")).json()
    assert fresh["received_at"] is not None


async def test_patch_with_a_future_correction_is_refused(http_client, retailer):
    order = await make_order(
        http_client, retailer, [kit_line(quantity=1)], received=True, received_at=BACKDATE
    )
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = await http_client.patch(f"/orders/{order['id']}", json={"received_at": future})
    assert resp.status_code == 422
    assert "future" in resp.json()["detail"]
    fresh = (await http_client.get(f"/orders/{order['id']}")).json()
    assert instant(fresh["received_at"]) == BACKDATE_INSTANT


async def test_patch_correction_alongside_a_line_edit_stamps_new_kits_with_the_new_date(
    client, retailer
):
    order = await make_order(client, retailer, [kit_line(quantity=1)], received=True)
    item = order["items"][0]
    line = kit_line(quantity=3)
    line["id"] = item["id"]
    resp = await client.patch(
        f"/orders/{order['id']}", json={"received_at": BACKDATE, "items": [line]}
    )
    assert resp.status_code == 200, resp.text
    kits = await order_kits(client, resp.json())
    assert len(kits) == 3
    # The original kit's stamp was the receipt, so the correction follows it; the
    # two the same request spawns are in hand as of the corrected receipt too.
    for kit in kits:
        assert kit["status"] == "backlog"
        assert instant(kit["status_updated_at"]) == BACKDATE_INSTANT


async def test_line_added_to_a_backdated_order_carries_the_receipt_stamp(client, retailer):
    order = await make_order(
        client, retailer, [kit_line(quantity=1)], received=True, received_at=BACKDATE
    )
    existing = order["items"][0]
    keep = kit_line(quantity=1)
    keep["id"] = existing["id"]
    resp = await client.patch(
        f"/orders/{order['id']}",
        json={"items": [keep, kit_line(quantity=1, name="MG Zaku II 2.0")]},
    )
    assert resp.status_code == 200, resp.text
    kits = await order_kits(client, resp.json())
    assert len(kits) == 2
    for kit in kits:
        assert kit["status"] == "backlog"
        assert instant(kit["status_updated_at"]) == BACKDATE_INSTANT


# --- MCP -------------------------------------------------------------------------


def mcp_kit_order(**extra) -> dict:
    return {
        "retailer": "USA Gundam Store",
        "order_date": "2026-04-20",
        "currency_code": "USD",
        "items": [
            {
                "item_type": "kit",
                "quantity": 1,
                "unit_price_minor": 2999,
                "currency_code": "USD",
                "kit": {"name": "RG Nu Gundam", "grade": "RG"},
            }
        ],
        **extra,
    }


async def test_mcp_create_order_backdated(client):
    async with Client(mcp) as mcp_client:
        order = (
            await mcp_client.call_tool(
                "create_order", mcp_kit_order(received=True, received_at=BACKDATE)
            )
        ).data
    assert instant(order["received_at"]) == BACKDATE_INSTANT
    (kit,) = await order_kits(client, order)
    assert kit["status"] == "backlog"
    assert instant(kit["status_updated_at"]) == BACKDATE_INSTANT


async def test_mcp_mark_order_received_backdated(client):
    async with Client(mcp) as mcp_client:
        order = (await mcp_client.call_tool("create_order", mcp_kit_order())).data
        received = (
            await mcp_client.call_tool(
                "mark_order_received", {"order_id": order["id"], "received_at": BACKDATE}
            )
        ).data
    assert instant(received["received_at"]) == BACKDATE_INSTANT
    (kit,) = await order_kits(client, received)
    assert kit["status"] == "backlog"
    assert instant(kit["status_updated_at"]) == BACKDATE_INSTANT


async def test_mcp_received_at_without_the_flag_is_a_tool_error():
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="received=true"):
            await mcp_client.call_tool("create_order", mcp_kit_order(received_at=BACKDATE))


async def test_mcp_naive_received_at_is_a_tool_error():
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError, match="offset"):
            await mcp_client.call_tool(
                "create_order",
                mcp_kit_order(received=True, received_at="2026-05-04T14:30:00"),
            )


async def test_mcp_future_received_at_surfaces_as_a_tool_error():
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    async with Client(mcp) as mcp_client:
        order = (await mcp_client.call_tool("create_order", mcp_kit_order())).data
        with pytest.raises(ToolError, match="future"):
            await mcp_client.call_tool(
                "mark_order_received", {"order_id": order["id"], "received_at": future}
            )
