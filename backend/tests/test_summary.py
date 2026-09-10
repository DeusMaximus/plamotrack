"""Home's counts and the order stage (design §13.2, #233).

`GET /summary` and the `get_summary` tool answer from one function
(`services/summary.py`), and every order row carries a derived `stage`
(`services/order_stage.py`) — so the number in a Home heading is the number of
rows the list page behind its *view all* link shows. The value axis for the
stage: `received_at` set or not, `shipped_at` set or not, and the kits — none,
every one pre-ordered, a mix, every one ordered, and one moved out of
`pre_ordered` by hand after entry. The state axis: a kit-only order, a mixed
order, a catalog-only order (no kit lines at all, so no signal).
"""

import pytest
from fastmcp import Client
from sqlalchemy import text

from app.mcp import mcp
from app.models.enums import KitStatus

# Literals, not the module's constants: the negative control runs this file
# against a tree without `services/order_stage.py`, and an import the old tree
# lacks fails the whole file rather than the assertion that names the defect.
STAGES = ("pre_ordered", "ordered", "in_transit", "received")
ZERO_KITS = {status.value: 0 for status in KitStatus}
ZERO_ORDERS = dict.fromkeys(STAGES, 0)


def test_the_count_shapes_are_the_vocabularies():
    """One field per status and per stage — the summary can never omit a bucket
    (an empty one reads 0) and never name one the lists cannot filter on."""
    from app.schemas.summary import KitCounts, OrderCounts
    from app.services.order_stage import ORDER_STAGES

    assert list(KitCounts.model_fields) == [status.value for status in KitStatus]
    assert list(OrderCounts.model_fields) == list(ORDER_STAGES) == list(STAGES)


async def test_an_empty_collection_counts_zero_everywhere(client):
    resp = await client.get("/summary")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"kits": ZERO_KITS, "orders": ZERO_ORDERS}


async def test_kit_counts_are_per_status_and_follow_a_move(client):
    made = {}
    for name, status in (
        ("A", None),  # the default, backlog
        ("B", "backlog"),
        ("C", "building"),
        ("D", "complete"),
        ("E", "complete"),
        ("F", "complete"),
        ("G", "pre_ordered"),
    ):
        body = {"name": name, "grade": "HG"} | ({"status": status} if status else {})
        resp = await client.post("/kits", json=body)
        assert resp.status_code == 201, resp.text
        made[name] = resp.json()["id"]

    kits = (await client.get("/summary")).json()["kits"]
    assert kits == ZERO_KITS | {"backlog": 2, "building": 1, "complete": 3, "pre_ordered": 1}
    # The count is the list page's total behind the same filter.
    for status, expected in kits.items():
        rows = (await client.get("/kits", params={"status": status})).json()
        assert len(rows) == expected, status

    await client.patch(f"/kits/{made['A']}", json={"status": "building"})
    kits = (await client.get("/summary")).json()["kits"]
    assert kits == ZERO_KITS | {"backlog": 1, "building": 2, "complete": 3, "pre_ordered": 1}


def _kit_line(name: str, status: str | None = None, quantity: int = 1) -> dict:
    kit = {"name": name, "grade": "HG"} | ({"status": status} if status else {})
    return {
        "item_type": "kit",
        "quantity": quantity,
        "unit_price_minor": 2800,
        "currency_code": "JPY",
        "kit": kit,
    }


def _catalog_line() -> dict:
    return {
        "item_type": "consumable",
        "quantity": 2,
        "unit_price_minor": 300,
        "currency_code": "JPY",
        "new_item": {"name": "Tamiya Extra Thin Cement", "category": "cement"},
    }


async def _order(client, retailer, number: str, items: list[dict], **extra) -> dict:
    resp = await client.post(
        "/orders",
        json={
            "retailer_id": retailer["id"],
            "order_date": "2026-08-01",
            "order_number": number,
            "currency_code": "JPY",
            "items": items,
            **extra,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed_every_stage(client, retailer) -> dict[str, dict]:
    """One order per way of landing in each stage; keyed by order number."""
    cement = await _order(client, retailer, "CEMENT", [_catalog_line()])
    return {
        # pre_ordered: every spawned kit still a pre-order — one line of two kits
        "PRE": await _order(client, retailer, "PRE", [_kit_line("Pre", "pre_ordered", 2)]),
        # ordered: an ordered kit; a mix (the pre-ordered line is tagged on Home);
        # no kit lines at all — paint carries no signal
        "ORD": await _order(client, retailer, "ORD", [_kit_line("Ord")]),
        "MIX": await _order(
            client, retailer, "MIX", [_kit_line("Mix-ord"), _kit_line("Mix-pre", "pre_ordered")]
        ),
        "CEMENT": cement,
        # in_transit: shipped, not received — whatever the kits say
        "SHIP": await _order(
            client,
            retailer,
            "SHIP",
            [_kit_line("Ship", "pre_ordered")],
            shipped_at="2026-08-10T10:00:00+00:00",
        ),
        # received: whether or not it was ever marked shipped
        "RCV": await _order(
            client,
            retailer,
            "RCV",
            [_kit_line("Rcv")],
            received=True,
            received_at="2026-08-20T10:00:00+00:00",
        ),
        "RCV-SHIP": await _order(
            client,
            retailer,
            "RCV-SHIP",
            [_kit_line("RcvShip")],
            shipped_at="2026-08-12T10:00:00+00:00",
            received=True,
            received_at="2026-08-20T10:00:00+00:00",
        ),
    }


EXPECTED_STAGE = {
    "PRE": "pre_ordered",
    "ORD": "ordered",
    "MIX": "ordered",
    "CEMENT": "ordered",
    "SHIP": "in_transit",
    "RCV": "received",
    "RCV-SHIP": "received",
}


async def test_every_order_row_carries_its_stage(client, retailer):
    seeded = await _seed_every_stage(client, retailer)
    # On the create response, the detail read and the list — one computed field.
    assert {n: o["stage"] for n, o in seeded.items()} == EXPECTED_STAGE
    for number, order in seeded.items():
        detail = (await client.get(f"/orders/{order['id']}")).json()
        assert detail["stage"] == EXPECTED_STAGE[number], number
    listed = {o["order_number"]: o["stage"] for o in (await client.get("/orders")).json()}
    assert listed == EXPECTED_STAGE


async def test_order_counts_are_per_stage_and_match_the_rows(client, retailer):
    seeded = await _seed_every_stage(client, retailer)
    orders = (await client.get("/summary")).json()["orders"]
    assert orders == {"pre_ordered": 1, "ordered": 3, "in_transit": 1, "received": 2}
    rows = (await client.get("/orders")).json()
    for stage, expected in orders.items():
        assert sum(1 for row in rows if row["stage"] == stage) == expected, stage
    # The kits the orders spawned are counted too — the summary is one snapshot of
    # both tables, not two pages' totals stapled together.
    kits = (await client.get("/summary")).json()["kits"]
    assert kits == ZERO_KITS | {
        "pre_ordered": 3,  # PRE ×2, MIX's pre-ordered line
        "ordered": 2,  # ORD, MIX's ordered line
        "in_transit": 1,  # SHIP's kit rode the shipment
        "backlog": 2,  # RCV, RCV-SHIP delivered theirs
    }
    assert seeded["PRE"]["stage"] == "pre_ordered"


async def test_a_kit_moved_by_hand_moves_its_order_out_of_pre_ordered(client, retailer):
    """Derived from the kits, never stored: a pre-order whose only kit the owner
    moves to backlog (it turned up early, say) is no longer a pre-order, and a
    pre-order's kit re-marked pre_ordered brings it back."""
    pre = await _order(client, retailer, "PRE", [_kit_line("Pre", "pre_ordered")])
    kit_id = pre["items"][0]["spawned_kit_ids"][0]
    assert pre["stage"] == "pre_ordered"
    assert (await client.get("/summary")).json()["orders"] == ZERO_ORDERS | {"pre_ordered": 1}

    assert (await client.patch(f"/kits/{kit_id}", json={"status": "backlog"})).status_code == 200
    assert (await client.get(f"/orders/{pre['id']}")).json()["stage"] == "ordered"
    assert (await client.get("/summary")).json()["orders"] == ZERO_ORDERS | {"ordered": 1}

    back = await client.patch(f"/kits/{kit_id}", json={"status": "pre_ordered"})
    assert back.status_code == 200
    assert (await client.get(f"/orders/{pre['id']}")).json()["stage"] == "pre_ordered"


async def test_shipping_and_receiving_move_the_stage_and_the_counts(client, retailer):
    """The order's own transitions, through the service calls that make them —
    the lifecycle the counts must follow without a page reload's help."""
    order = await _order(client, retailer, "PRE", [_kit_line("Pre", "pre_ordered")])
    assert (await client.get("/summary")).json()["orders"] == ZERO_ORDERS | {"pre_ordered": 1}

    shipped = await client.post(f"/orders/{order['id']}/ship")
    assert shipped.status_code == 200, shipped.text
    assert shipped.json()["stage"] == "in_transit"
    assert (await client.get("/summary")).json()["orders"] == ZERO_ORDERS | {"in_transit": 1}

    received = await client.post(f"/orders/{order['id']}/receive")
    assert received.status_code == 200, received.text
    assert received.json()["stage"] == "received"
    assert (await client.get("/summary")).json() == {
        "kits": ZERO_KITS | {"backlog": 1},
        "orders": ZERO_ORDERS | {"received": 1},
    }


async def test_get_summary_and_list_orders_match_rest_on_mcp(client, retailer):
    """Rule 1: the tool is the same function, and the rows it lists carry the
    same stage — an agent asking "what's in the mail?" reads what Home shows."""
    await _seed_every_stage(client, retailer)
    async with Client(mcp) as mcp_client:
        tool_summary = (await mcp_client.call_tool("get_summary", {})).data
        tool_orders = (await mcp_client.call_tool("list_orders", {"pending_only": True})).data
    rest_summary = (await client.get("/summary")).json()
    assert tool_summary == rest_summary
    assert rest_summary["orders"] == {
        "pre_ordered": 1,
        "ordered": 3,
        "in_transit": 1,
        "received": 2,
    }
    rest_orders = (await client.get("/orders", params={"pending_only": "true"})).json()
    assert [(o["order_number"], o["stage"]) for o in tool_orders] == [
        (o["order_number"], o["stage"]) for o in rest_orders
    ]
    assert {o["stage"] for o in tool_orders} == {"pre_ordered", "ordered", "in_transit"}


async def test_the_summary_reads_one_snapshot(client, monkeypatch):
    """Two statements — the kit counts, then the orders — under one REPEATABLE
    READ, asked of Postgres inside the request's own transaction (the shape of
    `test_integrity.py`'s export pin): a receive committing between them would
    otherwise show a kit in the backlog beside its order still in the mail."""
    from app.services import summary as summary_service

    observed: list[tuple[str | None, str | None]] = []
    real_begin = summary_service.begin_read_snapshot

    async def begin_then_ask(session) -> None:
        await real_begin(session)
        observed.append(
            (
                await session.scalar(text("SHOW transaction_isolation")),
                await session.scalar(text("SHOW transaction_read_only")),
            )
        )

    monkeypatch.setattr(summary_service, "begin_read_snapshot", begin_then_ask)
    assert (await client.get("/summary")).status_code == 200
    assert observed == [("repeatable read", "on")]


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
async def test_the_summary_is_read_only(http_client, method):
    """A GET-only namespace: nothing to write through, on any verb."""
    resp = await http_client.request(method, "/summary")
    assert resp.status_code == 405, resp.text
