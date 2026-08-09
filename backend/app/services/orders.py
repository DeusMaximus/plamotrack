import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import (
    Consumable,
    ItemType,
    Kit,
    KitStatus,
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
    OrderKitDetails,
    OrderUpdate,
    RetailerCreate,
    RetailerUpdate,
)
from app.services.catalog import CATALOG_MODELS
from app.services.kits import default_scale_for_grade


def _converted_snapshot(line: OrderItemCreate) -> tuple[int | None, str | None]:
    """The §6 conversion snapshot: an amount and the currency it was captured in.

    A caller that supplies an amount but no currency means "the instance's
    reference currency" — resolved once, here, at write time. Reading the setting
    on the way out instead would make every historical amount change meaning the
    day the operator edits an env var.
    """
    if line.converted_price_minor is None:
        return None, None
    return line.converted_price_minor, (
        line.converted_currency_code or get_settings().reference_currency
    )


def _apply_converted_snapshot(item: OrderItem, line: OrderItemCreate) -> None:
    """An edit that never mentions the snapshot leaves it alone (issue #3).

    Everything else on a line is replaced wholesale by an edit; this pair is the
    exception, because it is a recorded fact the caller usually cannot restate —
    no client has the entry-time FX rate, so "quantity: 2" would otherwise erase
    what the purchase converted to. Clearing takes an explicit null.

    Reads `model_fields_set`, so a Python caller that constructs the model with
    converted_price_minor=None *is* asking to clear it; only an absent key means
    "leave this alone".
    """
    if "converted_price_minor" not in line.model_fields_set:
        return
    item.converted_price_minor, item.converted_currency_code = _converted_snapshot(line)


# A kit that has visibly progressed is never silently deleted by order edits.
PROGRESSED_STATUSES = {KitStatus.BUILDING, KitStatus.COMPLETE}
# Statuses that a delivery arrival naturally advances to backlog (in hand, unbuilt).
ARRIVAL_ELIGIBLE = {KitStatus.PRE_ORDERED, KitStatus.ORDERED, KitStatus.IN_TRANSIT}


# --- retailers -----------------------------------------------------------------


async def create_retailer(session: AsyncSession, data: RetailerCreate) -> Retailer:
    retailer = Retailer(**data.model_dump())
    session.add(retailer)
    await session.flush()
    await session.commit()
    return retailer


async def list_retailers(session: AsyncSession) -> list[Retailer]:
    return list((await session.scalars(select(Retailer).order_by(Retailer.name))).all())


async def get_or_create_retailer(session: AsyncSession, name: str) -> Retailer:
    """Case-insensitive match by name; used by the MCP create_order tool so agents
    don't fragment the retailer list.

    Deliberately does NOT commit: it participates in the caller's transaction so
    a failed order creation rolls the new retailer back too — no partial data."""
    retailer = await session.scalar(
        select(Retailer).where(Retailer.name.ilike(name.strip())).limit(1)
    )
    if retailer is None:
        retailer = Retailer(name=name.strip())
        session.add(retailer)
        await session.flush()
    return retailer


async def update_retailer(
    session: AsyncSession, retailer_id: uuid.UUID, data: RetailerUpdate
) -> Retailer:
    retailer = await session.get(Retailer, retailer_id)
    if retailer is None:
        raise NotFoundError(f"retailer {retailer_id} not found")
    fields = data.model_dump(exclude_unset=True)
    if fields.get("name") is None and "name" in fields:
        raise InvalidInputError("name cannot be null")
    for key, value in fields.items():
        setattr(retailer, key, value)
    await session.flush()
    await session.commit()
    return retailer


async def delete_retailer(session: AsyncSession, retailer_id: uuid.UUID) -> None:
    retailer = await session.get(Retailer, retailer_id)
    if retailer is None:
        raise NotFoundError(f"retailer {retailer_id} not found")
    order_count = await session.scalar(
        select(func.count()).select_from(Order).where(Order.retailer_id == retailer_id)
    )
    if order_count:
        raise ConflictError(
            f"retailer '{retailer.name}' has {order_count} order(s) — "
            "order history is kept, so the retailer cannot be deleted"
        )
    await session.delete(retailer)
    await session.flush()
    await session.commit()


# --- dispatch helpers ----------------------------------------------------------


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


async def _adjust_ref(
    session: AsyncSession, item_type: ItemType, ref_id: uuid.UUID, delta: int
) -> None:
    """Row-locked stock adjustment with a can't-go-negative guard."""
    model = CATALOG_MODELS[item_type]
    row = await session.get(model, ref_id, with_for_update=True)
    if row is None:
        raise NotFoundError(f"{item_type} {ref_id} not found")
    new_quantity = row.quantity_on_hand + delta
    if new_quantity < 0:
        raise ConflictError(
            f"cannot remove {-delta}× '{row.name}': only {row.quantity_on_hand} on hand "
            "(already consumed?) — adjust its stock first"
        )
    row.quantity_on_hand = new_quantity
    await session.flush()


def _initial_kit_status(requested: KitStatus, received: bool) -> KitStatus:
    if received and requested in ARRIVAL_ELIGIBLE:
        return KitStatus.BACKLOG
    return requested


async def spawn_kits(
    session: AsyncSession,
    item: OrderItem,
    *,
    name: str,
    grade: str,
    scale: str | None = None,
    kit_number: str | None = None,
    status: KitStatus | str | None = None,
    count: int = 1,
    received: bool = False,
) -> None:
    """The §3.9 fan-out: one physical `kits` row per unit on a kit-type order line.

    Shared with the CSV importer, which needs the same fan-out for order lines that
    arrive without their kits — hence the loose keyword signature rather than an
    `OrderKitDetails`, which is a REST-payload shape the importer doesn't have.
    """
    requested = KitStatus(status) if status else KitStatus.ORDERED
    final_status = _initial_kit_status(requested, received)
    resolved_scale = scale if scale is not None else default_scale_for_grade(grade)
    for _ in range(count):
        session.add(
            Kit(
                name=name,
                grade=grade,
                scale=resolved_scale,
                kit_number=kit_number,
                status=final_status,
                order_item_id=item.id,
            )
        )
    await session.flush()


async def _spawn_from_details(
    session: AsyncSession,
    item: OrderItem,
    details: OrderKitDetails,
    count: int,
    received: bool,
) -> None:
    await spawn_kits(
        session,
        item,
        name=details.name,
        grade=details.grade,
        scale=details.scale,
        kit_number=details.kit_number,
        status=details.status,
        count=count,
        received=received,
    )


async def _line_kits(session: AsyncSession, item_id: uuid.UUID) -> list[Kit]:
    stmt = (
        select(Kit)
        .where(Kit.order_item_id == item_id)
        .options(selectinload(Kit.photos))
        .order_by(Kit.created_at, Kit.id)
    )
    return list((await session.scalars(stmt)).all())


def _kit_progressed(kit: Kit) -> bool:
    return kit.status in PROGRESSED_STATUSES or kit.rating is not None or len(kit.photos) > 0


async def _delete_line_kits(session: AsyncSession, item: OrderItem, count: int | None) -> None:
    """Delete `count` spawned kits (None = all). Progressed kits are protected."""
    kits = await _line_kits(session, item.id)
    safe = [kit for kit in kits if not _kit_progressed(kit)]
    needed = len(kits) if count is None else count
    if len(safe) < needed:
        raise ConflictError(
            f"cannot remove {needed} kit(s) from this line: only {len(safe)} can be "
            "deleted safely — the rest are building/complete, rated, or have photos. "
            "Move or edit those kits first."
        )
    targets = safe if count is None else list(reversed(safe))[:count]  # newest first
    for kit in targets:
        await session.delete(kit)
    await session.flush()


async def _add_line(
    session: AsyncSession, order: Order, line: OrderItemCreate, received: bool
) -> OrderItem:
    """The §3.9 dispatch: kit lines FAN OUT into kits rows immediately; catalog
    lines INCREMENT stock — but only once the order is received."""
    converted_minor, converted_code = _converted_snapshot(line)
    item = OrderItem(
        order_id=order.id,
        item_type=line.item_type,
        quantity=line.quantity,
        unit_price_minor=line.unit_price_minor,
        currency_code=line.currency_code,
        converted_price_minor=converted_minor,
        converted_currency_code=converted_code,
    )
    session.add(item)
    await session.flush()

    if line.item_type is ItemType.KIT:
        await _spawn_from_details(session, item, line.kit, line.quantity, received)
    else:
        if line.new_item is not None:
            row = _build_catalog_row(line.item_type, line.new_item)
            session.add(row)
            await session.flush()
        else:
            model = CATALOG_MODELS[line.item_type]
            row = await session.get(model, line.catalog_ref_id, with_for_update=True)
            if row is None:
                raise NotFoundError(f"{line.item_type} {line.catalog_ref_id} not found")
        item.catalog_ref_id = row.id
        if received:
            row.quantity_on_hand += line.quantity
        await session.flush()
    return item


async def _undo_line_dispatch(session: AsyncSession, item: OrderItem, received: bool) -> None:
    """Undo one line's side effects: delete spawned kits / reverse applied stock."""
    if item.item_type is ItemType.KIT:
        await _delete_line_kits(session, item, count=None)
    elif received and item.catalog_ref_id is not None:
        await _adjust_ref(session, item.item_type, item.catalog_ref_id, -item.quantity)


async def _remove_line(session: AsyncSession, item: OrderItem, received: bool) -> None:
    await _undo_line_dispatch(session, item, received)
    await session.delete(item)
    await session.flush()


async def _update_line(
    session: AsyncSession, item: OrderItem, line: OrderItemCreate, received: bool
) -> None:
    if line.item_type != item.item_type:
        raise InvalidInputError(
            "a line's item_type cannot change — remove the line and add a new one"
        )

    if item.item_type is ItemType.KIT:
        details = line.kit
        scale = (
            details.scale if details.scale is not None else default_scale_for_grade(details.grade)
        )
        # Kit details propagate to every kit this line spawned (single source of
        # truth for "I misspelled the name at order entry").
        line_kits = await _line_kits(session, item.id)
        for kit in line_kits:
            kit.name = details.name
            kit.grade = details.grade
            kit.scale = scale
            kit.kit_number = details.kit_number
        # Diff against the actual surviving kit count, not item.quantity —
        # defense in depth should the two ever drift.
        delta = line.quantity - len(line_kits)
        if delta > 0:
            await _spawn_from_details(session, item, details, delta, received)
        elif delta < 0:
            await _delete_line_kits(session, item, count=-delta)
    else:
        old_ref = item.catalog_ref_id
        if line.new_item is not None:
            new_row = _build_catalog_row(line.item_type, line.new_item)
            session.add(new_row)
            await session.flush()
            new_ref = new_row.id
        else:
            new_ref = line.catalog_ref_id
            if new_ref != old_ref:
                model = CATALOG_MODELS[line.item_type]
                if await session.get(model, new_ref) is None:
                    raise NotFoundError(f"{line.item_type} {new_ref} not found")
        if received:
            if new_ref == old_ref:
                delta = line.quantity - item.quantity
                if delta != 0:
                    await _adjust_ref(session, item.item_type, old_ref, delta)
            else:
                if old_ref is not None:
                    await _adjust_ref(session, item.item_type, old_ref, -item.quantity)
                await _adjust_ref(session, item.item_type, new_ref, line.quantity)
        item.catalog_ref_id = new_ref

    item.quantity = line.quantity
    item.unit_price_minor = line.unit_price_minor
    item.currency_code = line.currency_code
    _apply_converted_snapshot(item, line)
    await session.flush()


# --- orders --------------------------------------------------------------------


async def create_order(session: AsyncSession, data: OrderCreate) -> Order:
    retailer = await session.get(Retailer, data.retailer_id)
    if retailer is None:
        raise NotFoundError(f"retailer {data.retailer_id} not found")

    order = Order(**data.model_dump(exclude={"items", "received"}))
    if data.received:
        order.received_at = datetime.now(UTC)
    session.add(order)
    await session.flush()

    for line in data.items:
        await _add_line(session, order, line, received=data.received)

    result = await get_order(session, order.id)
    await session.commit()
    return result


async def _get_order_for_write(session: AsyncSession, order_id: uuid.UUID) -> Order:
    """Load an order with its lines, row-locked. The lock serializes all order
    mutations (receive/edit/delete): a concurrent receive waits here, then sees
    received_at already set and 409s instead of applying stock a second time."""
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items))
        .with_for_update()
    )
    if order is None:
        raise NotFoundError(f"order {order_id} not found")
    return order


async def update_order(session: AsyncSession, order_id: uuid.UUID, data: OrderUpdate) -> Order:
    order = await _get_order_for_write(session, order_id)
    received = order.received_at is not None

    header = data.model_dump(exclude_unset=True, exclude={"items"})
    if "retailer_id" in header:
        if header["retailer_id"] is None:
            raise InvalidInputError("retailer_id cannot be null")
        if await session.get(Retailer, header["retailer_id"]) is None:
            raise NotFoundError(f"retailer {header['retailer_id']} not found")
    for non_nullable in ("order_date", "currency_code"):
        if non_nullable in header and header[non_nullable] is None:
            raise InvalidInputError(f"{non_nullable} cannot be null")
    for key, value in header.items():
        setattr(order, key, value)

    if data.items is not None:
        existing = {item.id: item for item in order.items}
        seen: set[uuid.UUID] = set()
        for line in data.items:
            if line.id is not None:
                if line.id not in existing:
                    raise InvalidInputError(f"order item {line.id} does not belong to this order")
                if line.id in seen:
                    raise InvalidInputError(f"order item {line.id} appears twice")
                seen.add(line.id)
                await _update_line(session, existing[line.id], line, received)
            else:
                await _add_line(session, order, line, received)
        for item_id, item in existing.items():
            if item_id not in seen:
                await _remove_line(session, item, received)

    await session.flush()
    result = await get_order(session, order.id)
    await session.commit()
    return result


async def receive_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    """Mark an order arrived: apply catalog stock increments and advance kits
    still in the ordering pipeline to backlog (in hand, unbuilt)."""
    order = await _get_order_for_write(session, order_id)
    if order.received_at is not None:
        raise ConflictError("order is already marked received")

    now = datetime.now(UTC)
    order.received_at = now
    for item in order.items:
        if item.item_type is ItemType.KIT:
            for kit in await _line_kits(session, item.id):
                if kit.status in ARRIVAL_ELIGIBLE:
                    kit.status = KitStatus.BACKLOG
                    kit.status_updated_at = now
        elif item.catalog_ref_id is not None:
            await _adjust_ref(session, item.item_type, item.catalog_ref_id, item.quantity)

    await session.flush()
    result = await get_order(session, order.id)
    await session.commit()
    return result


async def delete_order(session: AsyncSession, order_id: uuid.UUID) -> None:
    """Delete = undo the order entry: spawned kits are removed and any applied
    stock increments reversed. Progressed kits or already-consumed stock block
    the delete with a 409 rather than silently losing history."""
    order = await _get_order_for_write(session, order_id)
    received = order.received_at is not None
    for item in list(order.items):
        # dispatch undo only — deleting the order cascades the items themselves
        await _undo_line_dispatch(session, item, received)
    await session.delete(order)
    await session.flush()
    await session.commit()


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    # populate_existing: this also runs right after line edits in the same
    # session, where the identity-mapped order/items would otherwise serve
    # stale collections (removed lines, un-refreshed kit lists).
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items).selectinload(OrderItem.kits))
        .execution_options(populate_existing=True)
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
