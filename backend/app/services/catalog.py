import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, NotFoundError
from app.models import Consumable, ItemType, Tool, Upgrade
from app.schemas.catalog import (
    CatalogSearchResult,
    ConsumableCreate,
    StockAdjustmentResult,
    ToolCreate,
    UpgradeCreate,
)

logger = logging.getLogger(__name__)

# The three fungible catalog tables an order line (or stock adjustment) can target.
CATALOG_MODELS: dict[ItemType, type[Tool | Consumable | Upgrade]] = {
    ItemType.TOOL: Tool,
    ItemType.CONSUMABLE: Consumable,
    ItemType.UPGRADE: Upgrade,
}


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
    tool = Tool(**data.model_dump())
    session.add(tool)
    await session.flush()
    return tool


async def create_consumable(session: AsyncSession, data: ConsumableCreate) -> Consumable:
    consumable = Consumable(**data.model_dump())
    session.add(consumable)
    await session.flush()
    return consumable


async def create_upgrade(session: AsyncSession, data: UpgradeCreate) -> Upgrade:
    upgrade = Upgrade(**data.model_dump())
    session.add(upgrade)
    await session.flush()
    return upgrade


async def list_catalog(
    session: AsyncSession, model: type[Tool | Consumable | Upgrade]
) -> list[Tool | Consumable | Upgrade]:
    return list((await session.scalars(select(model).order_by(model.name))).all())


async def adjust_stock(
    session: AsyncSession, catalog_id: uuid.UUID, delta: int, reason: str | None = None
) -> StockAdjustmentResult:
    """Resolve a catalog id across the three fungible tables and adjust its stock."""
    for item_type, model in CATALOG_MODELS.items():
        row = await session.get(model, catalog_id, with_for_update=True)
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
