"""Regression tests for integrity issues raised in external review:
double-receive concurrency, MCP order atomicity, and kit provenance."""

import asyncio
import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from sqlalchemy import func, select

from app.db import session_scope
from app.exceptions import ConflictError
from app.mcp import mcp
from app.models import Kit, Upgrade, UpgradeApplication
from app.services import kits as kits_service
from app.services import orders as orders_service
from app.services import upgrades as upgrades_service


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
