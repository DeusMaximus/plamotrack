import uuid

from fastapi import APIRouter

from app.db import SessionDep
from app.schemas.orders import OrderCreate, OrderRead, OrderUpdate
from app.services import orders as orders_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderRead])
async def list_orders(session: SessionDep):
    return await orders_service.list_orders(session)


@router.post("", response_model=OrderRead, status_code=201)
async def create_order(data: OrderCreate, session: SessionDep):
    """Create an order with nested items; the server dispatches per §3.9 —
    kit lines fan out into `kits` rows, catalog lines increment stock."""
    return await orders_service.create_order(session, data)


@router.get("/{order_id}", response_model=OrderRead)
async def get_order(order_id: uuid.UUID, session: SessionDep):
    return await orders_service.get_order(session, order_id)


@router.patch("/{order_id}", response_model=OrderRead)
async def update_order(order_id: uuid.UUID, data: OrderUpdate, session: SessionDep):
    """Edit header fields and/or replace the line-item set. Line edits re-run the
    dispatch diff: kits are spawned/removed and applied stock adjusted to match."""
    return await orders_service.update_order(session, order_id, data)


@router.post("/{order_id}/receive", response_model=OrderRead)
async def receive_order(order_id: uuid.UUID, session: SessionDep):
    """Mark the order arrived: applies catalog stock increments and moves kits
    still in the ordering pipeline to in_hand."""
    return await orders_service.receive_order(session, order_id)


@router.delete("/{order_id}", status_code=204)
async def delete_order(order_id: uuid.UUID, session: SessionDep):
    """Undo the order entry: removes spawned kits and reverses applied stock
    (409 if kits have progressed or stock was already consumed)."""
    await orders_service.delete_order(session, order_id)
