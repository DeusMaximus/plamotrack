import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Consumable, ItemType, OrderItem, Tool, Upgrade, UpgradeApplication
from app.schemas.catalog import (
    CatalogSearchResult,
    ConsumableCreate,
    ConsumableUpdate,
    StockAdjustmentResult,
    ToolCreate,
    ToolUpdate,
    UpgradeCreate,
    UpgradeUpdate,
)
from app.services.write_gate import acquire_write_gate

logger = logging.getLogger(__name__)

# The three fungible catalog tables an order line (or stock adjustment) can target.
CATALOG_MODELS: dict[ItemType, type[Tool | Consumable | Upgrade]] = {
    ItemType.TOOL: Tool,
    ItemType.CONSUMABLE: Consumable,
    ItemType.UPGRADE: Upgrade,
}


async def lock_catalog_row(
    session: AsyncSession, model: type[Tool | Consumable | Upgrade], item_id: uuid.UUID
) -> Tool | Consumable | Upgrade | None:
    """Load one catalog row under FOR UPDATE, refreshed from the locked read (rule 7).

    The single place the row-lock half of rule 7 is spelled out, because every writer
    of `quantity_on_hand` has to agree on it — three of them didn't (#36). Returns
    None for a missing row: callers own the error message, which knows which line or
    which request asked.

    `populate_existing` is the load-bearing half. `session.get(..., with_for_update=)`
    genuinely emits `SELECT … FOR UPDATE` — it skips the identity-map shortcut — but
    without it an instance the session already holds keeps the attribute values it was
    loaded with, so the caller computes its delta from the number that was true
    *before* the lock. That is worse than not locking at all: it reads as correct, and
    the response it produces looks correct too.

    Today no caller trips that, and only by luck — SQLAlchemy's identity map holds weak
    references, and the paths that load a row before locking it discard the result, so
    CPython collects it and the locked read comes back fresh. Correctness that rests on
    when the garbage collector runs isn't correctness.

    Callers may hold the returned row across further locked reads of the *same* row
    within one transaction (an order can name one item on two lines) — but only because
    each adjustment flushes before the next read, so the re-read sees this session's own
    uncommitted value. That flush ordering is load-bearing, not tidiness.
    """
    return await session.get(model, item_id, with_for_update=True, populate_existing=True)


def _to_search_result(item_type: ItemType, row: Tool | Consumable | Upgrade) -> CatalogSearchResult:
    return CatalogSearchResult(
        item_type=item_type,
        id=row.id,
        name=row.name,
        category=getattr(row, "category", None),
        manufacturer=getattr(row, "manufacturer", None),
        quantity_on_hand=row.quantity_on_hand,
    )


async def search(
    session: AsyncSession, query: str, limit_per_type: int = 20
) -> list[CatalogSearchResult]:
    """Cross-table typeahead search — powers both the UI select-or-create flow and
    the MCP search_catalog tool, so agents hit the same de-dup path as humans (§7)."""
    results: list[CatalogSearchResult] = []
    for item_type, model in CATALOG_MODELS.items():
        rows = await session.scalars(
            select(model)
            .where(model.name.icontains(query, autoescape=True))
            .order_by(model.name)
            .limit(limit_per_type)
        )
        results.extend(_to_search_result(item_type, row) for row in rows)
    results.sort(key=lambda r: r.name.lower())
    return results


async def create_tool(session: AsyncSession, data: ToolCreate) -> Tool:
    await acquire_write_gate(session)
    tool = Tool(**data.model_dump())
    session.add(tool)
    await session.flush()
    await session.commit()
    return tool


async def create_consumable(session: AsyncSession, data: ConsumableCreate) -> Consumable:
    await acquire_write_gate(session)
    consumable = Consumable(**data.model_dump())
    session.add(consumable)
    await session.flush()
    await session.commit()
    return consumable


async def create_upgrade(session: AsyncSession, data: UpgradeCreate) -> Upgrade:
    await acquire_write_gate(session)
    upgrade = Upgrade(**data.model_dump())
    session.add(upgrade)
    await session.flush()
    await session.commit()
    return upgrade


async def list_catalog(
    session: AsyncSession, model: type[Tool | Consumable | Upgrade]
) -> list[Tool | Consumable | Upgrade]:
    return list((await session.scalars(select(model).order_by(model.name))).all())


# Fields that exist as NOT NULL columns — an explicit null in a PATCH is rejected.
_NON_NULLABLE = {"name", "category", "manufacturer", "quantity_on_hand"}


async def update_catalog_item(
    session: AsyncSession,
    item_type: ItemType,
    item_id: uuid.UUID,
    data: ToolUpdate | ConsumableUpdate | UpgradeUpdate,
) -> Tool | Consumable | Upgrade:
    await acquire_write_gate(session)
    model = CATALOG_MODELS[item_type]
    # Locked: this is a stock writer like any other — `quantity_on_hand` is a settable
    # field on the PATCH — so it belongs on the same lock as `adjust_stock` and the
    # order dispatch rather than racing them (rule 7).
    row = await lock_catalog_row(session, model, item_id)
    if row is None:
        raise NotFoundError(f"{item_type} {item_id} not found")
    fields = data.model_dump(exclude_unset=True)
    for key, value in fields.items():
        if value is None and key in _NON_NULLABLE:
            raise InvalidInputError(f"{key} cannot be null")
        setattr(row, key, value)
    # After applying, not before: a PATCH carrying one half of the pair is fine when
    # the row already holds the other, so only the merged result can be judged (§6).
    if isinstance(row, Tool) and (
        (row.unit_cost_reference_minor is None) != (row.unit_cost_reference_currency is None)
    ):
        raise InvalidInputError(
            "unit_cost_reference_minor and unit_cost_reference_currency must be set "
            "together or cleared together"
        )
    await session.flush()
    await session.commit()
    return row


async def delete_catalog_item(
    session: AsyncSession, item_type: ItemType, item_id: uuid.UUID
) -> None:
    """History-preserving delete: items referenced by order lines (or, for
    upgrades, recorded applications) cannot be removed — edit them instead."""
    await acquire_write_gate(session)
    model = CATALOG_MODELS[item_type]
    # Locked before the reference counts below, because the counts and the delete have
    # to be one decision. `OrderItem.catalog_ref_id` is polymorphic across three tables
    # and so carries no foreign key — nothing at the database layer would catch an
    # order line that commits into the gap, and the item would simply vanish from
    # underneath it. The order dispatch locks this same row, which is what makes the
    # two serialize.
    row = await lock_catalog_row(session, model, item_id)
    if row is None:
        raise NotFoundError(f"{item_type} {item_id} not found")

    order_refs = await session.scalar(
        select(func.count()).select_from(OrderItem).where(OrderItem.catalog_ref_id == item_id)
    )
    if order_refs:
        raise ConflictError(
            f"'{row.name}' appears on {order_refs} order line(s) — "
            "order history is kept, so it cannot be deleted"
        )
    if item_type is ItemType.UPGRADE:
        applications = await session.scalar(
            select(func.count())
            .select_from(UpgradeApplication)
            .where(UpgradeApplication.upgrade_id == item_id)
        )
        if applications:
            raise ConflictError(
                f"'{row.name}' has been applied to {applications} kit(s) — "
                "build history is kept, so it cannot be deleted"
            )
    await session.delete(row)
    await session.flush()
    await session.commit()


async def adjust_stock(
    session: AsyncSession, catalog_id: uuid.UUID, delta: int, reason: str | None = None
) -> StockAdjustmentResult:
    """Resolve a catalog id across the three fungible tables and adjust its stock."""
    await acquire_write_gate(session)
    for item_type, model in CATALOG_MODELS.items():
        row = await lock_catalog_row(session, model, catalog_id)
        if row is None:
            continue
        new_quantity = row.quantity_on_hand + delta
        if new_quantity < 0:
            raise ConflictError(
                f"cannot adjust {item_type} '{row.name}' by {delta}: "
                f"only {row.quantity_on_hand} on hand"
            )
        row.quantity_on_hand = new_quantity
        await session.flush()
        await session.commit()
        # No audit table in v1 — the reason is logged and echoed, not persisted.
        logger.info(
            "stock adjusted: %s '%s' %+d -> %d (reason: %s)",
            item_type,
            row.name,
            delta,
            new_quantity,
            reason,
        )
        return StockAdjustmentResult(
            item_type=item_type,
            id=row.id,
            name=row.name,
            quantity_on_hand=new_quantity,
            reason=reason,
        )
    raise NotFoundError(f"no tool, consumable, or upgrade with id {catalog_id}")
