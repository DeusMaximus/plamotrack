"""MCP tools (§7) — thin wrappers over the same service layer the REST API uses,
so agents hit identical business logic (fan-out/increment dispatch, de-dup search,
stock guards) without any duplicated rules."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_scope
from app.exceptions import DomainError
from app.models.enums import KitStatus
from app.schemas.kits import KitRead, KitUpdate
from app.schemas.orders import OrderCreate, OrderItemCreate, OrderRead
from app.services import catalog as catalog_service
from app.services import kits as kits_service
from app.services import orders as orders_service
from app.services import upgrades as upgrades_service

mcp = FastMCP(
    "plamotrack",
    instructions=(
        "Track a Gunpla/plamo collection: kits move through a pipeline "
        "(pre_ordered → ordered → in_transit → backlog → building → complete; "
        "backlog = physically in hand but not started); "
        "tools, consumables, and upgrades are quantity-tracked stock. "
        "Before adding catalog items to an order, ALWAYS search_catalog first and reuse "
        "an existing item's id — free-text duplicates fragment the catalog."
    ),
)


@asynccontextmanager
async def _tool_session() -> AsyncIterator[AsyncSession]:
    """One transaction per tool call; domain errors surface as MCP tool errors."""
    try:
        async with session_scope() as session:
            yield session
    except DomainError as exc:
        raise ToolError(str(exc)) from exc


# Friendly aliases for vocabulary agents may carry over from emails or the old
# status model ("your order has arrived", the retired in_hand status).
_STATUS_ALIASES = {"in_hand": "backlog", "arrived": "backlog", "received": "backlog"}


def _parse_status(value: str) -> KitStatus:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    normalized = _STATUS_ALIASES.get(normalized, normalized)
    try:
        return KitStatus(normalized)
    except ValueError:
        valid = ", ".join(s.value for s in KitStatus)
        raise ToolError(f"invalid status {value!r} — valid statuses: {valid}") from None


def _parse_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ToolError(f"{what} {value!r} is not a valid UUID") from None


@mcp.tool
async def list_kits(status: str | None = None, grade: str | None = None) -> list[dict]:
    """List kits in the collection, optionally filtered by pipeline status
    (pre_ordered, ordered, in_transit, backlog, building, complete — backlog
    means in hand but not started) and/or grade (HG, RG, MG, PG, SD, ...)."""
    parsed_status = _parse_status(status) if status else None
    async with _tool_session() as session:
        kits = await kits_service.list_kits(session, status=parsed_status, grade=grade)
        return [KitRead.model_validate(k).model_dump(mode="json") for k in kits]


@mcp.tool
async def get_kit(kit_id: str) -> dict:
    """Get a single kit by id, including status, rating, and build notes."""
    parsed = _parse_uuid(kit_id, "kit_id")
    async with _tool_session() as session:
        kit = await kits_service.get_kit(session, parsed)
        return KitRead.model_validate(kit).model_dump(mode="json")


@mcp.tool
async def update_kit_status(kit_id: str, status: str) -> dict:
    """Move a kit to a new pipeline status (equivalent to dragging its Kanban
    card). Valid statuses: pre_ordered, ordered, in_transit, backlog (= in
    hand, not started), building, complete."""
    parsed_id = _parse_uuid(kit_id, "kit_id")
    parsed_status = _parse_status(status)
    async with _tool_session() as session:
        kit = await kits_service.update_kit(session, parsed_id, KitUpdate(status=parsed_status))
        return KitRead.model_validate(kit).model_dump(mode="json")


@mcp.tool
async def search_catalog(query: str) -> list[dict]:
    """Search tools, consumables, and upgrades by name (same search the UI
    typeahead uses). ALWAYS call this before adding catalog items to an order —
    reuse an existing item's id as catalog_ref_id instead of creating a duplicate."""
    async with _tool_session() as session:
        results = await catalog_service.search(session, query)
        return [r.model_dump(mode="json") for r in results]


@mcp.tool
async def create_order(
    retailer: str,
    order_date: str,
    items: list[OrderItemCreate],
    currency_code: str = "AUD",
    order_number: str | None = None,
    shipping_cost_minor: int | None = None,
    delivery_service: str | None = None,
    tracking_number: str | None = None,
    tracking_url: str | None = None,
    received: bool = False,
) -> dict:
    """Record a purchase. The retailer is matched by name case-insensitively and
    created if new; order_date is ISO format (YYYY-MM-DD). Item lines follow the
    order's dispatch semantics: a `kit` line needs `kit` details (name, grade,
    optional kit_number; status defaults to `ordered`, use `pre_ordered` for
    pre-orders) and spawns one collection row per quantity. A tool/consumable/
    upgrade line needs either `catalog_ref_id` (an id from search_catalog — always
    search first) or `new_item` details. Catalog stock does NOT increase until the
    order is received: pass received=true for store purchases already in hand, or
    call mark_order_received when a shipment arrives. Include the retailer's
    order_number from the confirmation email when available (support reference —
    only unique per retailer, never treat it as an identifier). Prices are integer
    minor units (cents/yen) with an ISO 4217 currency_code."""
    try:
        parsed_date = date.fromisoformat(order_date)
    except ValueError:
        raise ToolError(f"order_date {order_date!r} is not ISO format (YYYY-MM-DD)") from None
    async with _tool_session() as session:
        retailer_row = await orders_service.get_or_create_retailer(session, retailer)
        data = OrderCreate(
            retailer_id=retailer_row.id,
            order_date=parsed_date,
            order_number=order_number,
            delivery_service=delivery_service,
            tracking_number=tracking_number,
            tracking_url=tracking_url,
            shipping_cost_minor=shipping_cost_minor,
            currency_code=currency_code,
            received=received,
            items=items,
        )
        order = await orders_service.create_order(session, data)
        return OrderRead.model_validate(order).model_dump(mode="json")


@mcp.tool
async def list_orders(pending_only: bool = False) -> list[dict]:
    """List orders (newest first), including received state and line items.
    Use pending_only=true to see orders still awaiting delivery — e.g. to find
    which order a shipping-notification email belongs to."""
    async with _tool_session() as session:
        orders = await orders_service.list_orders(session)
        if pending_only:
            orders = [order for order in orders if order.received_at is None]
        return [OrderRead.model_validate(order).model_dump(mode="json") for order in orders]


@mcp.tool
async def mark_order_received(order_id: str) -> dict:
    """Mark an order as arrived/delivered: catalog stock increments are applied
    and kits still in the ordering pipeline (pre_ordered/ordered/in_transit)
    move to backlog. Find the order with list_orders(pending_only=true)."""
    parsed = _parse_uuid(order_id, "order_id")
    async with _tool_session() as session:
        order = await orders_service.receive_order(session, parsed)
        return OrderRead.model_validate(order).model_dump(mode="json")


@mcp.tool
async def adjust_stock(catalog_id: str, delta: int, reason: str | None = None) -> dict:
    """Adjust on-hand quantity of a tool, consumable, or upgrade by a signed delta
    (e.g. -1 when a consumable runs out). Get ids from search_catalog. Fails if
    the adjustment would take stock below zero."""
    parsed = _parse_uuid(catalog_id, "catalog_id")
    async with _tool_session() as session:
        result = await catalog_service.adjust_stock(session, parsed, delta, reason)
        return result.model_dump(mode="json")


@mcp.tool
async def apply_upgrade(upgrade_id: str, kit_id: str, quantity: int = 1) -> dict:
    """Record that an upgrade (decals, metal parts, ...) was used on a kit:
    decrements upgrade stock and links it to the kit."""
    parsed_upgrade = _parse_uuid(upgrade_id, "upgrade_id")
    parsed_kit = _parse_uuid(kit_id, "kit_id")
    async with _tool_session() as session:
        application = await upgrades_service.apply_upgrade(
            session, parsed_upgrade, parsed_kit, quantity
        )
        return {
            "id": str(application.id),
            "upgrade_id": str(application.upgrade_id),
            "kit_id": str(application.kit_id),
            "quantity_used": application.quantity_used,
            "applied_at": application.applied_at.isoformat(),
        }
