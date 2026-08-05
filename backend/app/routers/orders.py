import uuid

from fastapi import APIRouter

from app.db import SessionDep
from app.schemas.orders import OrderCreate, OrderRead
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
