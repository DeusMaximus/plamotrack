"""Regression tests for integrity issues raised in external review:
double-receive concurrency, MCP order atomicity, and kit provenance."""

import asyncio
import uuid

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app.db import session_scope
from app.exceptions import ConflictError
from app.mcp import mcp
from app.services import orders as orders_service


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
