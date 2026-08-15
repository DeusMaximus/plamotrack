"""Regression tests for integrity issues raised in external review:
double-receive concurrency, MCP order atomicity, and kit provenance."""

import asyncio
import csv
import io
import json
import time
import uuid
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.db import get_sessionmaker, session_scope
from app.exceptions import ConflictError, NotFoundError
from app.mcp import mcp
from app.models import Consumable, ItemType, Kit, KitStatus, OrderItem, Upgrade, UpgradeApplication
from app.schemas.kits import KitCreate
from app.schemas.orders import OrderCreate, OrderItemCreate, OrderItemUpsert, OrderUpdate
from app.services import catalog as catalog_service
from app.services import kits as kits_service
from app.services import orders as orders_service
from app.services import upgrades as upgrades_service
from app.services.portability import exporting, importing, spec
from app.services.write_gate import acquire_write_gate


async def test_concurrent_receive_applies_stock_once(client, retailer):
    """Two simultaneous receives: the order row lock lets exactly one through;
    the loser sees received_at set and conflicts instead of re-applying stock."""
    consumable = (
        await client.post(
            "/consumables",
            json={"name": "Gundam Marker GM01", "category": "paint", "quantity_on_hand": 1},
        )
    ).json()
    order = (
        await client.post(
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
    ).json()
    order_id = uuid.UUID(order["id"])

    async def attempt() -> str:
        try:
            async with session_scope() as session:
                await orders_service.receive_order(session, order_id)
            return "received"
        except ConflictError:
            return "conflict"

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == ["conflict", "received"]
    assert (await client.get("/consumables")).json()[0]["quantity_on_hand"] == 6  # 1 + 5, once


async def test_failed_mcp_order_rolls_back_new_retailer(client):
    """get_or_create_retailer participates in the tool transaction: a failed
    order must not strand the retailer it implicitly created."""
    async with Client(mcp) as mcp_client:
        with pytest.raises(ToolError):
            await mcp_client.call_tool(
                "create_order",
                {
                    "retailer": "Brand New Shop",
                    "order_date": "2026-08-02",
                    "items": [
                        {
                            "item_type": "consumable",
                            "quantity": 1,
                            "unit_price_minor": 500,
                            "currency_code": "AUD",
                            "catalog_ref_id": str(uuid.uuid4()),  # does not exist
                        }
                    ],
                },
            )
    names = [r["name"] for r in (await client.get("/retailers")).json()]
    assert "Brand New Shop" not in names


async def test_mcp_order_still_reuses_existing_retailer(client, retailer):
    """The atomicity fix must not break the happy path: existing retailer is
    matched case-insensitively, new one is created WITH a successful order."""
    async with Client(mcp) as mcp_client:
        await mcp_client.call_tool(
            "create_order",
            {
                "retailer": retailer["name"].upper(),
                "order_date": "2026-08-02",
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
    retailers = (await client.get("/retailers")).json()
    assert len(retailers) == 1  # reused, not duplicated


async def test_order_spawned_kit_blocked_from_direct_delete(client, retailer):
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
                        "kit": {"name": "HG Zaku II", "grade": "HG"},
                    }
                ],
            },
        )
    ).json()
    kit_id = order["items"][0]["spawned_kit_ids"][0]

    resp = await client.delete(f"/kits/{kit_id}")
    assert resp.status_code == 409
    assert "order" in resp.json()["detail"]
    assert len((await client.get("/kits")).json()) == 1  # still in the collection

    # kits without order provenance still delete fine
    standalone = (await client.post("/kits", json={"name": "Backlog kit", "grade": "HG"})).json()
    assert (await client.delete(f"/kits/{standalone['id']}")).status_code == 204


async def test_applying_an_upgrade_while_the_kit_is_deleted_keeps_the_two_in_step(client):
    """Whichever wins, the stock and the record of where it went must still agree.

    `apply_upgrade` locks the *upgrade* row and `delete_kit` locks the *kit*, so
    neither sees the other's lock directly. What serializes them is the kit row:
    inserting an application needs FOR KEY SHARE on it, which the delete's FOR
    UPDATE conflicts with. Without that lock the delete decides "no applications",
    the application commits, and the DELETE cascades it away with the stock still
    spent.

    Deliberately raced rather than pinned. Forcing the losing interleaving would
    mean pausing the delete between its check and its delete *while holding FOR
    UPDATE* — at which point the concurrent application blocks on that very lock
    and the test deadlocks instead of asserting. So this asserts the invariant
    whoever wins, the same shape as test_concurrent_receive_applies_stock_once.

    Repeated, because one race is a coin flip: against the unlocked code a single
    pass caught the defect roughly twice in eight runs, which is a detector worth
    nothing. Ten passes turn that into a near-certainty while still costing under
    a second.
    """
    for attempt in range(10):
        upgrade = (
            await client.post(
                "/upgrades",
                json={
                    "name": f"Metal thrusters {attempt}",
                    "manufacturer": "Metal Build",
                    "quantity_on_hand": 3,
                },
            )
        ).json()
        kit = (
            await client.post("/kits", json={"name": f"Sazabi Ver.Ka {attempt}", "grade": "MG"})
        ).json()
        kit_id, upgrade_id = uuid.UUID(kit["id"]), uuid.UUID(upgrade["id"])

        async def delete(kit_id=kit_id) -> None:
            async with session_scope() as session:
                await kits_service.delete_kit(session, kit_id)

        async def apply(kit_id=kit_id, upgrade_id=upgrade_id) -> None:
            async with session_scope() as session:
                await upgrades_service.apply_upgrade(session, upgrade_id, kit_id, 1)

        # Any refusal from either side is a legal outcome; only the end state matters.
        await asyncio.gather(delete(), apply(), return_exceptions=True)

        async with session_scope() as session:
            remaining = await session.scalar(
                select(Upgrade.quantity_on_hand).where(Upgrade.id == upgrade_id)
            )
            applications = await session.scalar(
                select(func.count())
                .select_from(UpgradeApplication)
                .where(UpgradeApplication.kit_id == kit_id)
            )
            kit_rows = await session.scalar(
                select(func.count()).select_from(Kit).where(Kit.id == kit_id)
            )

        # The forbidden state is stock spent with nothing left to explain it.
        if remaining < 3:
            assert applications == 1, f"attempt {attempt}: stock spent, application gone"
            assert kit_rows == 1, f"attempt {attempt}: stock spent on a kit that no longer exists"
        else:
            assert applications == 0, f"attempt {attempt}: application recorded, stock untouched"


# --- catalog lock discipline (#36) ---------------------------------------------
#
# Rule 7 says stock mutations take row locks. These four tests cover the three ways
# it was applied unevenly: a lock that served a pre-lock value, writers that took no
# lock at all, and no agreed order between the writers that did.
#
# Unlike the upgrade race above, these are pinned rather than repeated. The barrier
# is a third transaction holding FOR UPDATE on one row: a writer that reaches for it
# parks there, so the test decides what has committed before it wakes up. That works
# here and not there because the gate holds a single lock and always releases it —
# it can never be half of the cycle a deadlock test is trying to provoke.


async def _lock_waiters() -> int:
    """Backends parked on a lock right now, counted from a connection of its own."""
    async with get_sessionmaker()() as session:
        return await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND wait_event_type = 'Lock'"
            )
        )


async def _wait_until(condition: Callable[[], Awaitable[bool]], what: str) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if await condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


async def _wait_for_parked(count: int) -> None:
    """The barrier itself: return once `count` writers are waiting on a lock."""

    async def parked() -> bool:
        return await _lock_waiters() >= count

    await _wait_until(parked, f"{count} writer(s) parked on a lock")


async def _finished_or_parked(task: asyncio.Task, count: int) -> bool:
    """For a writer that may legitimately never park — it depends which lock the
    fix makes it take first."""
    return task.done() or await _lock_waiters() >= count


@asynccontextmanager
async def _gate(table: str, row_id: uuid.UUID) -> AsyncIterator[None]:
    """Hold FOR UPDATE on one row until the `with` block exits."""
    async with get_sessionmaker()() as session:
        await session.execute(
            text(f"SELECT 1 FROM {table} WHERE id = :id FOR UPDATE"),  # noqa: S608 — literal
            {"id": row_id},
        )
        try:
            yield
        finally:
            await session.rollback()


def _is_deadlock(outcome: object) -> bool:
    """40P01. Integrity survives a deadlock — Postgres aborts one side — but the
    owner sees a 500 on an edit that was never wrong, which is why the fix is an
    order every writer agrees on rather than a retry."""
    return isinstance(outcome, DBAPIError) and getattr(outcome.orig, "sqlstate", None) == "40P01"


async def _catalog_order(retailer_id: str, *lines: tuple[uuid.UUID, int]) -> uuid.UUID:
    """A received consumable order, so its lines have already applied stock."""
    async with session_scope() as session:
        order = await orders_service.create_order(
            session,
            OrderCreate(
                retailer_id=uuid.UUID(retailer_id),
                order_date=date(2026, 8, 1),
                currency_code="AUD",
                received=True,
                items=[
                    OrderItemCreate(
                        item_type=ItemType.CONSUMABLE,
                        quantity=quantity,
                        unit_price_minor=650,
                        currency_code="AUD",
                        catalog_ref_id=ref_id,
                    )
                    for ref_id, quantity in lines
                ],
            ),
        )
        return order.id


async def test_catalog_delete_cannot_land_between_an_order_lines_check_and_its_commit(
    client, retailer
):
    """`delete_catalog_item` counts references and then deletes. Unlocked, those are
    two decisions with a gap: an order line can commit into it. Nothing at the
    database layer catches that, because `OrderItem.catalog_ref_id` is polymorphic
    across three tables and therefore carries no foreign key — so the item is gone
    and the line points at nothing.

    Gated on the consumable, which makes the interleaving the defect needs: the
    order write has already asked for the row when the delete starts, and the delete
    runs its reference count while the order is still uncommitted.
    """
    consumable = (
        await client.post("/consumables", json={"name": "Mr Surfacer 1200", "category": "primer"})
    ).json()
    consumable_id = uuid.UUID(consumable["id"])

    async def create_order() -> None:
        await _catalog_order(retailer["id"], (consumable_id, 2))

    async def delete_item() -> None:
        async with session_scope() as session:
            await catalog_service.delete_catalog_item(session, ItemType.CONSUMABLE, consumable_id)

    async with _gate("consumables", consumable_id):
        creating = asyncio.create_task(create_order())
        await _wait_for_parked(1)
        deleting = asyncio.create_task(delete_item())
        # Both writers end up parked whichever way this goes: locked, the delete
        # waits at its opening SELECT; unlocked, it waits at the DELETE, having
        # already counted zero references. Either way it has made its decision.
        await _wait_for_parked(2)
    outcomes = await asyncio.gather(creating, deleting, return_exceptions=True)

    assert outcomes[0] is None, f"the order write asked first and should have won: {outcomes[0]!r}"
    async with session_scope() as session:
        survivors = await session.scalar(
            select(func.count()).select_from(Consumable).where(Consumable.id == consumable_id)
        )
        references = await session.scalar(
            select(func.count())
            .select_from(OrderItem)
            .where(OrderItem.catalog_ref_id == consumable_id)
        )
    assert references == 1
    assert survivors == 1, "order line left referencing a catalog item that was deleted"
    assert isinstance(outcomes[1], ConflictError), f"delete not refused: {outcomes[1]!r}"


async def test_a_locked_catalog_read_returns_what_the_lock_sees(client):
    """`lock_catalog_row`'s contract, and the whole reason it exists.

    `session.get(..., with_for_update=True)` really does emit `SELECT … FOR UPDATE`,
    but without `populate_existing` an instance the session already holds keeps the
    attributes it was loaded with — so a writer locks the row and then computes its
    delta from the value that was true before the lock.

    No caller reaches that today, and the reason is not a good one: the identity map
    holds weak references, and the paths that load a row before locking it discard
    the result, so CPython collects it and the locked read comes back fresh by
    accident. This asserts the helper's behaviour with a reference deliberately held
    alive, because that accident is not what the lock should depend on.
    """
    item = (
        await client.post("/consumables", json={"name": "Mr Cement S", "category": "cement"})
    ).json()
    item_id = uuid.UUID(item["id"])

    async with session_scope() as reader:
        stale = await reader.get(Consumable, item_id)  # held, so it cannot be collected
        assert stale.quantity_on_hand == 0

        async with session_scope() as writer:
            await catalog_service.adjust_stock(writer, item_id, 40, reason="restock")

        locked = await catalog_service.lock_catalog_row(reader, Consumable, item_id)
        assert locked.quantity_on_hand == 40, (
            f"locked read served the pre-lock value {locked.quantity_on_hand}; "
            "any delta computed from it would erase the other writer's 40"
        )
        assert stale is locked  # same identity-mapped instance, refreshed in place


async def test_retargeting_a_received_line_keeps_both_writers_increments(client, retailer):
    """Moving a received line onto a different catalog item touches two rows and
    races a third writer on one of them. Gated on the *old* target, so the retarget
    is provably mid-flight when the restock commits.

    This one passes before the fix as well as after — kept because retargeting is the
    path the up-front locking most changes, and losing an increment here is exactly
    what that change must not do.
    """
    old_item, new_item = [
        (await client.post("/consumables", json={"name": name, "category": "cement"})).json()
        for name in ("Tamiya Extra Thin", "Tamiya Quick Setting")
    ]
    old_id, new_id = uuid.UUID(old_item["id"]), uuid.UUID(new_item["id"])
    order_id = await _catalog_order(retailer["id"], (old_id, 5))  # old target: 0 + 5

    async with session_scope() as session:
        order = await orders_service.get_order(session, order_id)
        line_id = order.items[0].id

    async def retarget() -> None:
        async with session_scope() as session:
            await orders_service.update_order(
                session,
                order_id,
                OrderUpdate(
                    items=[
                        OrderItemUpsert(
                            id=line_id,
                            item_type=ItemType.CONSUMABLE,
                            quantity=5,
                            unit_price_minor=650,
                            currency_code="AUD",
                            catalog_ref_id=new_id,
                        )
                    ]
                ),
            )

    async def top_up() -> None:
        async with session_scope() as session:
            await catalog_service.adjust_stock(session, new_id, 100, reason="bulk restock")

    async with _gate("consumables", old_id):
        retargeting = asyncio.create_task(retarget())
        await _wait_for_parked(1)
        topping_up = asyncio.create_task(top_up())
        # Don't await the top-up here: once the retarget locks its targets up front,
        # it may already hold the new one, and the top-up parks behind it. Waiting
        # for "finished or parked" covers both without the test hanging on itself.
        await _wait_until(
            lambda: _finished_or_parked(topping_up, 2), "the concurrent restock to land"
        )
    outcomes = await asyncio.gather(retargeting, topping_up, return_exceptions=True)
    assert not [o for o in outcomes if isinstance(o, BaseException)], outcomes

    # Asserted against the committed rows, not either call's response: the defect
    # was that the response looked right while the row had lost the other writer's
    # 100. Both writers ran, so both have to be in the number.
    async def stock_of(row_id: uuid.UUID) -> int:
        async with session_scope() as session:
            return await session.scalar(
                select(Consumable.quantity_on_hand).where(Consumable.id == row_id)
            )

    old_stock, new_stock = await stock_of(old_id), await stock_of(new_id)
    assert old_stock == 0, "the old target kept stock the line no longer claims"
    assert new_stock == 105, f"restock lost: expected 100 + 5, got {new_stock}"


async def test_order_edits_naming_the_same_items_in_reverse_do_not_deadlock(client, retailer):
    """Two edits, two catalog targets, opposite payload order. Locking in the order
    the lines happen to arrive means each edit can hold what the other is waiting
    for; sorting by uuid gives every writer the same sequence, so one simply waits.
    """
    first, second = [
        (await client.post("/consumables", json={"name": name, "category": "paint"})).json()
        for name in ("Mr Color 1", "Mr Color 2")
    ]
    first_id, second_id = uuid.UUID(first["id"]), uuid.UUID(second["id"])
    forward = await _catalog_order(retailer["id"], (first_id, 2), (second_id, 2))
    reverse = await _catalog_order(retailer["id"], (second_id, 2), (first_id, 2))

    async def bump(order_id: uuid.UUID, targets: tuple[uuid.UUID, ...]) -> None:
        async with session_scope() as session:
            order = await orders_service.get_order(session, order_id)
            by_target = {item.catalog_ref_id: item.id for item in order.items}
            await orders_service.update_order(
                session,
                order_id,
                OrderUpdate(
                    items=[
                        OrderItemUpsert(
                            id=by_target[target],
                            item_type=ItemType.CONSUMABLE,
                            quantity=3,  # 2 -> 3: a +1 on each target, never negative
                            unit_price_minor=650,
                            currency_code="AUD",
                            catalog_ref_id=target,
                        )
                        for target in targets
                    ]
                ),
            )

    async with _gate("consumables", first_id):
        forwards = asyncio.create_task(bump(forward, (first_id, second_id)))
        await _wait_for_parked(1)
        backwards = asyncio.create_task(bump(reverse, (second_id, first_id)))
        await _wait_for_parked(2)
    outcomes = await asyncio.gather(forwards, backwards, return_exceptions=True)

    assert not [o for o in outcomes if _is_deadlock(o)], f"lock cycle between two edits: {outcomes}"
    assert not [o for o in outcomes if isinstance(o, BaseException)], outcomes
    async with session_scope() as session:
        stock = {
            row_id: await session.scalar(
                select(Consumable.quantity_on_hand).where(Consumable.id == row_id)
            )
            for row_id in (first_id, second_id)
        }
    assert list(stock.values()) == [6, 6]  # 2 + 2 received, +1 from each edit


async def test_editing_an_order_while_an_upgrade_is_applied_does_not_deadlock(client, retailer):
    """The cycle that spans two tables, and the reason catalog locks come first.

    An order edit touching a kit line and an upgrade line took its locks in payload
    order: kits, then the upgrade. `apply_upgrade` goes the other way — it locks the
    upgrade, then needs FOR KEY SHARE on the kit to record the application. Held at
    the same time those are a cycle. Taking every catalog lock before the first kit
    lock puts order writes on the same catalog → kits path as `apply_upgrade`, so
    the two can only queue.
    """
    upgrade = (
        await client.post("/upgrades", json={"name": "Metal thruster set", "manufacturer": "Delpi"})
    ).json()
    upgrade_id = uuid.UUID(upgrade["id"])
    order = (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-08-01",
                "currency_code": "AUD",
                "received": True,
                "items": [
                    {
                        "item_type": "kit",
                        "quantity": 2,
                        "unit_price_minor": 2800,
                        "currency_code": "AUD",
                        "kit": {"name": "MG Sazabi", "grade": "MG"},
                    },
                    {
                        "item_type": "upgrade",
                        "quantity": 3,
                        "unit_price_minor": 1500,
                        "currency_code": "AUD",
                        "catalog_ref_id": str(upgrade_id),
                    },
                ],
            },
        )
    ).json()
    order_id = uuid.UUID(order["id"])
    kit_line, upgrade_line = order["items"][0], order["items"][1]
    kit_id = uuid.UUID(kit_line["spawned_kit_ids"][0])

    async def edit() -> None:
        """Kit line first in the payload, so the kit locks are taken first."""
        async with session_scope() as session:
            await orders_service.update_order(
                session,
                order_id,
                OrderUpdate(
                    items=[
                        OrderItemUpsert(
                            id=uuid.UUID(kit_line["id"]),
                            item_type=ItemType.KIT,
                            quantity=1,  # 2 -> 1: locks and deletes a spawned kit
                            unit_price_minor=2800,
                            currency_code="AUD",
                            kit={"name": "MG Sazabi", "grade": "MG"},
                        ),
                        OrderItemUpsert(
                            id=uuid.UUID(upgrade_line["id"]),
                            item_type=ItemType.UPGRADE,
                            quantity=4,  # 3 -> 4: a +1 on the upgrade
                            unit_price_minor=1500,
                            currency_code="AUD",
                            catalog_ref_id=upgrade_id,
                        ),
                    ]
                ),
            )

    async def apply() -> None:
        async with session_scope() as session:
            await upgrades_service.apply_upgrade(session, upgrade_id, kit_id, 1)

    async with _gate("upgrades", upgrade_id):
        applying = asyncio.create_task(apply())
        await _wait_for_parked(1)
        editing = asyncio.create_task(edit())
        await _wait_for_parked(2)
    outcomes = await asyncio.gather(applying, editing, return_exceptions=True)

    assert not [o for o in outcomes if _is_deadlock(o)], f"kit/catalog lock cycle: {outcomes}"
    # A refusal is legal here — whoever loses may find the kit gone or the kit
    # carrying an application that blocks its deletion. A 500 is not.
    for outcome in outcomes:
        assert outcome is None or isinstance(outcome, ConflictError | NotFoundError), outcome


async def test_a_line_left_dangling_by_the_old_delete_says_so_instead_of_404ing(client, retailer):
    """The residue the lock cannot help with (#63).

    A database that ran the pre-0.2.4 unlocked delete can hold a line pointing at a
    catalog row that is gone. Every path that touches such a line reverses its stock
    first and so cannot proceed — but "consumable <uuid> not found" reads as though
    the *caller* named something missing, and sends the owner hunting a request they
    never made. Forged here with a raw delete, because the fixed code will no longer
    produce it.
    """
    consumable = (
        await client.post("/consumables", json={"name": "Ghost cement", "category": "cement"})
    ).json()
    consumable_id = uuid.UUID(consumable["id"])
    order_id = await _catalog_order(retailer["id"], (consumable_id, 2))

    async with session_scope() as session:
        await session.execute(text("DELETE FROM consumables WHERE id = :id"), {"id": consumable_id})
        await session.commit()

    with pytest.raises(ConflictError) as refusal:
        async with session_scope() as session:
            await orders_service.delete_order(session, order_id)
    assert "no longer in the catalog" in str(refusal.value)
    assert str(consumable_id) in str(refusal.value)

    # Header-only edits stay possible: an unrelated field must not be held hostage
    # by a corrupt line, which is why the up-front locking skips missing rows rather
    # than refusing outright.
    async with session_scope() as session:
        edited = await orders_service.update_order(
            session, order_id, OrderUpdate(tracking_number="EE123456789AU")
        )
    assert edited.tracking_number == "EE123456789AU"


async def test_two_lines_on_one_order_share_a_target_without_losing_an_increment(client, retailer):
    """Not a race — the ordering inside a single transaction that the locked reads
    depend on. Re-reading the row under its lock is only correct because the
    adjustment before it flushed, so the second read sees this session's own
    uncommitted value. Drop that flush and the second line silently overwrites the
    first with a value computed from the same starting point.
    """
    consumable = (
        await client.post("/consumables", json={"name": "Panel liner", "category": "paint"})
    ).json()
    consumable_id = uuid.UUID(consumable["id"])
    await _catalog_order(retailer["id"], (consumable_id, 4), (consumable_id, 3))

    async with session_scope() as session:
        stock = await session.scalar(
            select(Consumable.quantity_on_hand).where(Consumable.id == consumable_id)
        )
    assert stock == 7, f"two lines on one target should both count: expected 4 + 3, got {stock}"


# --- the collection-wide write gate ---------------------------------------------
#
# Per-row locks serialize writers that touch the same row. They cannot express the
# shape the importer has: read a lot of state, decide from it, then write across
# many tables — where a concurrent write to a row the plan never named invalidates
# the decision. These cover the gate that closes that (app/services/write_gate.py).
#
# Note on scope: every mutating service commits at the end of its own work, and the
# gate is transaction-scoped, so it is held from acquisition to that commit — which
# is exactly the read-decide-write unit. A test that sleeps *after* calling a
# service is sleeping outside the gate and proves nothing.


def _sheet(header: list[str], rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def _archive(tables: dict[str, list[dict[str, str]]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {"format": "plamotrack-archive", "export_version": exporting.EXPORT_VERSION}
            ),
        )
        for key, rows in tables.items():
            out = io.StringIO()
            writer = csv.DictWriter(
                out, fieldnames=spec.SPEC_BY_KEY[key].header, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
            archive.writestr(f"{key}.csv", out.getvalue())
    return buffer.getvalue()


async def _unreceived_order_with_a_kit(client) -> dict:
    retailer = (await client.post("/retailers", json={"name": "Hobby Link Japan"})).json()
    return (
        await client.post(
            "/orders",
            json={
                "retailer_id": retailer["id"],
                "order_date": "2026-03-14",
                "order_number": "HLJ-1",
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


async def test_the_gate_blocks_a_second_writer_until_the_first_commits():
    """The primitive's contract, pinned directly rather than inferred from a
    service outcome: while one transaction holds the gate, a second one's
    acquisition does not return.

    Ordering is forced with an event rather than raced, so this is deterministic —
    the holder is provably first, and the only question under test is whether the
    waiter is made to wait for it.
    """
    holder_has_it = asyncio.Event()
    sequence: list[str] = []

    async def holder() -> None:
        async with session_scope() as session:
            await acquire_write_gate(session)
            sequence.append("holder acquired")
            holder_has_it.set()
            await asyncio.sleep(0.3)
            sequence.append("holder committing")
        # session_scope commits on exit; Postgres drops the advisory lock there.

    async def waiter() -> None:
        await holder_has_it.wait()
        async with session_scope() as session:
            await acquire_write_gate(session)
            sequence.append("waiter acquired")

    await asyncio.gather(holder(), waiter())
    assert sequence == ["holder acquired", "holder committing", "waiter acquired"], sequence


async def test_reads_do_not_wait_behind_the_gate(client):
    """The gate must not turn a read into a queue: import preview and every list
    endpoint stay concurrent with a writer holding it.

    Holds the gate explicitly for the duration of the read, because a real service
    call would have committed — and released — long before the read was measured.
    """
    await _unreceived_order_with_a_kit(client)
    gate_taken = asyncio.Event()
    release = asyncio.Event()
    latency: list[float] = []

    async def hold_the_gate() -> None:
        async with session_scope() as session:
            await acquire_write_gate(session)
            gate_taken.set()
            await asyncio.wait_for(release.wait(), timeout=5)

    async def timed_read() -> None:
        await gate_taken.wait()
        started = time.monotonic()
        assert (await client.get("/kits")).status_code == 200
        assert (await client.get("/orders")).status_code == 200
        latency.append(time.monotonic() - started)
        release.set()

    await asyncio.gather(hold_the_gate(), timed_read())
    assert latency[0] < 1.0, f"reads waited {latency[0]:.2f}s behind a writer — reads must not gate"


# The two repros below force the genuinely dangerous window: the racing mutation
# is launched *after* `plan_import` has returned, so without the gate it lands
# between the plan and the writes — the interval no plan_hash and no per-row lock
# can see. It is deliberately NOT awaited inside the patch: under the gate it
# blocks until the apply commits, so awaiting it there would deadlock the test
# against the very serialization it is checking.
#
# Codex's third repro (an import reverting a kit somebody moved to `building`)
# needs the importer's kit-arrival side effect, which does not exist on main —
# it arrives with #47/#79. Its regression belongs on that branch, not here.


def _race_after_planning(monkeypatch, launch):
    """Patch `plan_import` so `launch()` fires once the plan exists, and hand the
    caller the task to await after the apply has finished."""
    original_plan_import = importing.plan_import
    holder: dict[str, asyncio.Task] = {}

    async def plan_then_race(*args, **kwargs):
        execution = await original_plan_import(*args, **kwargs)
        holder["task"] = asyncio.create_task(launch())
        await asyncio.sleep(0.05)  # let it reach — and block on — the gate
        return execution

    monkeypatch.setattr(importing, "plan_import", plan_then_race)
    return holder


async def test_a_create_whose_parent_is_deleted_mid_apply_is_never_a_500(http_client, monkeypatch):
    """Codex repro 1. A catalog line CREATE has no existing row to re-verify and
    no spawn parent, so no per-row guard covered it: a parent order deleted
    between planning and the write turned the insert into a foreign-key 500.

    The gate makes that interleaving unreachable — the delete waits until the
    apply has committed — so the apply completes cleanly and the delete lands
    afterwards, on an order whose new line it then cascades away.
    """
    order = await _unreceived_order_with_a_kit(http_client)
    tool = (
        await http_client.post("/tools", json={"name": "Godhand Nippers", "category": "cutting"})
    ).json()

    line = {
        "order_id": order["id"],
        "item_type": "tool",
        "catalog_ref_id": tool["id"],
        "quantity": "1",
        "unit_price_minor": "2800",
        "currency_code": "JPY",
    }
    content = _sheet(spec.ORDER_ITEMS.header, [line])

    preview = await http_client.post(
        "/import/preview",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge"},
    )
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["derived"]["kits_spawned"] == 0  # no spawn: the old guards saw nothing here
    plan_hash = plan["plan_hash"]

    deleted: list[int] = []

    async def delete_the_parent() -> None:
        resp = await http_client.delete(f"/orders/{order['id']}")
        deleted.append(resp.status_code)

    racing = _race_after_planning(monkeypatch, delete_the_parent)

    applied = await http_client.post(
        "/import/apply",
        files={"file": ("order_items.csv", content, "text/csv")},
        data={"mode": "merge", "plan_hash": plan_hash},
    )
    await racing["task"]

    assert applied.status_code != 500, f"foreign-key violation surfaced raw: {applied.text[:300]}"
    assert applied.status_code == 200, f"{applied.status_code}: {applied.text[:300]}"
    assert deleted == [204], f"the racing delete didn't land: {deleted}"
    assert (await http_client.get("/orders")).json() == []


async def test_replace_all_cannot_truncate_a_row_its_preview_never_listed(client, monkeypatch):
    """Codex repro 2, and the worst of the three: silent data loss.

    `TRUNCATE` empties the table at execution time, so a row created after the
    plan was built but before the truncate ran was destroyed without ever
    appearing in the approved `rows_deleted`. Under the gate the create waits for
    the apply to commit, so it lands on the far side of the truncate and survives
    — it was never part of what the user approved deleting.
    """
    await client.post("/retailers", json={"name": "Hobby Link Japan"})
    archive = (await client.get("/export/archive")).content

    preview = await client.post(
        "/import/preview",
        files={"file": ("archive.zip", archive, "application/zip")},
        data={"mode": "replace_all"},
    )
    assert preview.status_code == 200, preview.text
    plan_hash = preview.json()["plan_hash"]

    created: list[str] = []

    async def create_a_kit() -> None:
        async with session_scope() as session:
            kit = await kits_service.create_kit(
                session,
                KitCreate(name="Created mid-apply", grade="MG", status=KitStatus.BACKLOG),
            )
            created.append(str(kit.id))

    racing = _race_after_planning(monkeypatch, create_a_kit)

    applied = await client.post(
        "/import/apply",
        files={"file": ("archive.zip", archive, "application/zip")},
        data={"mode": "replace_all", "plan_hash": plan_hash, "confirm": "REPLACE"},
    )
    await racing["task"]

    assert applied.status_code == 200, applied.text
    assert created, "the racing create never ran — not exercising the race"

    names = {k["name"] for k in (await client.get("/kits")).json()}
    assert "Created mid-apply" in names, (
        "replace_all destroyed a kit created after its preview — the approved plan "
        "never listed it as a deletion"
    )
