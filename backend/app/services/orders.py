import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import InvalidInputError, NotFoundError
from app.models import (
    Consumable,
    ItemType,
    Kit,
    Order,
    OrderItem,
    Retailer,
    Tool,
    Upgrade,
)
from app.schemas.orders import (
    NewCatalogItem,
    OrderCreate,
    OrderItemCreate,
    RetailerCreate,
)
from app.services.catalog import CATALOG_MODELS
from app.services.kits import default_scale_for_grade


async def create_retailer(session: AsyncSession, data: RetailerCreate) -> Retailer:
    retailer = Retailer(**data.model_dump())
    session.add(retailer)
    await session.flush()
    return retailer


async def list_retailers(session: AsyncSession) -> list[Retailer]:
    return list((await session.scalars(select(Retailer).order_by(Retailer.name))).all())


async def get_or_create_retailer(session: AsyncSession, name: str) -> Retailer:
    """Case-insensitive match by name; used by the MCP create_order tool so agents
    don't fragment the retailer list."""
    retailer = await session.scalar(
        select(Retailer).where(Retailer.name.ilike(name.strip())).limit(1)
    )
    if retailer is None:
        retailer = Retailer(name=name.strip())
        session.add(retailer)
        await session.flush()
    return retailer


def _build_catalog_row(
    item_type: ItemType, new_item: NewCatalogItem
) -> Tool | Consumable | Upgrade:
    if item_type in (ItemType.TOOL, ItemType.CONSUMABLE):
        if not new_item.category:
            raise InvalidInputError(f"new {item_type} items require a category")
    if item_type is ItemType.TOOL:
        return Tool(
            name=new_item.name,
            category=new_item.category,
            quantity_on_hand=0,
            unit_cost_reference=new_item.unit_cost_reference,
            condition_notes=new_item.condition_notes,
        )
    if item_type is ItemType.CONSUMABLE:
        return Consumable(
            name=new_item.name,
            category=new_item.category,
            quantity_on_hand=0,
            low_stock_threshold=new_item.low_stock_threshold,
        )
    if not new_item.manufacturer:
        raise InvalidInputError("new upgrade items require a manufacturer")
    return Upgrade(
        name=new_item.name,
        manufacturer=new_item.manufacturer,
        quantity_on_hand=0,
    )


async def _dispatch_order_item(
    session: AsyncSession, order: Order, line: OrderItemCreate
) -> OrderItem:
    """The §3.9 quantity-semantics dispatch. Runs inside the caller's transaction:
    kit lines FAN OUT into new `kits` rows; catalog lines INCREMENT stock."""
    item = OrderItem(
        order_id=order.id,
        item_type=line.item_type,
        quantity=line.quantity,
        unit_price_minor=line.unit_price_minor,
        currency_code=line.currency_code,
        converted_price_aud_minor=line.converted_price_aud_minor,
    )
    session.add(item)
    await session.flush()

    if line.item_type is ItemType.KIT:
        details = line.kit
        scale = (
            details.scale if details.scale is not None else default_scale_for_grade(details.grade)
        )
        for _ in range(line.quantity):
            session.add(
                Kit(
                    name=details.name,
                    grade=details.grade,
                    scale=scale,
                    kit_number=details.kit_number,
                    status=details.status,
                    order_item_id=item.id,
                )
            )
        await session.flush()
    else:
        model = CATALOG_MODELS[line.item_type]
        if line.new_item is not None:
            row = _build_catalog_row(line.item_type, line.new_item)
            session.add(row)
            await session.flush()
        else:
            row = await session.get(model, line.catalog_ref_id, with_for_update=True)
            if row is None:
                raise NotFoundError(f"{line.item_type} {line.catalog_ref_id} not found")
        row.quantity_on_hand += line.quantity
        item.catalog_ref_id = row.id
        await session.flush()
    return item


async def create_order(session: AsyncSession, data: OrderCreate) -> Order:
    retailer = await session.get(Retailer, data.retailer_id)
    if retailer is None:
        raise NotFoundError(f"retailer {data.retailer_id} not found")

    order = Order(**data.model_dump(exclude={"items"}))
    session.add(order)
    await session.flush()

    for line in data.items:
        await _dispatch_order_item(session, order, line)

    return await get_order(session, order.id)


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).selectinload(OrderItem.kits))
    )
    if order is None:
        raise NotFoundError(f"order {order_id} not found")
    return order


async def list_orders(session: AsyncSession) -> list[Order]:
    stmt = (
        select(Order)
        .order_by(Order.order_date.desc(), Order.id)
        .options(selectinload(Order.items).selectinload(OrderItem.kits))
    )
    return list((await session.scalars(stmt)).all())
