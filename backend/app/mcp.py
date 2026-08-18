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

from app import __version__
from app.config import get_settings
from app.db import session_scope
from app.exceptions import DomainError
from app.models import ItemType
from app.models.enums import KitStatus
from app.schemas.catalog import (
    ConsumableRead,
    ConsumableUpdate,
    ToolRead,
    ToolUpdate,
    UpgradeRead,
    UpgradeUpdate,
)
from app.schemas.kits import KitRead, KitUpdate
from app.schemas.numeric import Int4, NonNegativeInt4, PositiveInt4
from app.schemas.orders import (
    OrderCreate,
    OrderItemCreate,
    OrderRead,
    RetailerCreate,
    RetailerRead,
    RetailerUpdate,
)
from app.services import catalog as catalog_service
from app.services import kits as kits_service
from app.services import orders as orders_service
from app.services import upgrades as upgrades_service

mcp = FastMCP(
    "plamotrack",
    # Left unset this reports FastMCP's own version, so a client would show
    # "plamotrack 3.4.5" — the framework's number wearing the app's name.
    version=__version__,
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


class _KitPatch(KitUpdate):
    """`KitUpdate` with the agent-tolerant status vocabulary the kit tools already
    accept ("In Transit", "arrived") in place of the strict enum.

    Subclassed rather than restated so a field added to `KitUpdate` — #94's build
    dates, #96's series — reaches this tool without anyone remembering to edit a
    second copy of the list. Only `status` is overridden; everything else is
    inherited, including `extra="forbid"`.
    """

    status: str | None = None


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
async def update_kit(kit_id: str, changes: _KitPatch) -> dict:
    """Edit a kit's details: name, grade, scale, kit_number, status, rating (1-5),
    build_notes. Only the fields present in `changes` are touched, so this is safe
    to call with a single field; sending an explicit null clears a nullable one
    (build_notes: null erases the notes, and a rating can be taken back the same
    way). Name, grade and status cannot be nulled — they are always set on a kit.
    `update_kit_status` is the status-only shortcut for this tool."""
    parsed_id = _parse_uuid(kit_id, "kit_id")
    fields = changes.model_dump(exclude_unset=True)
    if fields.get("status") is not None:
        fields["status"] = _parse_status(fields["status"])
    async with _tool_session() as session:
        kit = await kits_service.update_kit(session, parsed_id, KitUpdate(**fields))
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
async def list_retailers() -> list[dict]:
    """List every shop on record, with rating, packing quality, shipping speed and
    notes. Call this before create_retailer: nothing in the schema stops the same
    shop being added twice, and create_order matches an existing one by name."""
    async with _tool_session() as session:
        retailers = await orders_service.list_retailers(session)
        return [RetailerRead.model_validate(r).model_dump(mode="json") for r in retailers]


@mcp.tool
async def create_retailer(retailer: RetailerCreate) -> dict:
    """Add a shop with its full detail. Only `name` is required — a retailer named
    on create_order is created with nothing but a name, and update_retailer fills in
    the rest afterwards. Check list_retailers first so an existing shop is reused."""
    async with _tool_session() as session:
        row = await orders_service.create_retailer(session, retailer)
        return RetailerRead.model_validate(row).model_dump(mode="json")


@mcp.tool
async def update_retailer(retailer_id: str, changes: RetailerUpdate) -> dict:
    """Rate or annotate a shop: rating (1-5), packing_quality, shipping_speed,
    would_order_again, url, notes, name. Only the fields present in `changes` are
    touched; an explicit null clears a nullable one (notes: null erases the notes).
    Name cannot be nulled. Ids come from list_retailers.

    This is how "the box arrived crushed" or "don't order from them again" gets
    recorded — the fields exist on every retailer and were previously reachable
    only from the browser."""
    parsed = _parse_uuid(retailer_id, "retailer_id")
    async with _tool_session() as session:
        row = await orders_service.update_retailer(session, parsed, changes)
        return RetailerRead.model_validate(row).model_dump(mode="json")


@mcp.tool
async def create_order(
    retailer: str,
    order_date: str,
    items: list[OrderItemCreate],
    currency_code: str | None = None,
    order_number: str | None = None,
    shipping_cost_minor: NonNegativeInt4 | None = None,
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
    minor units (cents/yen) with an ISO 4217 currency_code; omit currency_code to
    use the instance's own reference currency (see the `meta` resource)."""
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
            currency_code=currency_code or get_settings().reference_currency,
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
async def adjust_stock(catalog_id: str, delta: Int4, reason: str | None = None) -> dict:
    """Adjust on-hand quantity of a tool, consumable, or upgrade by a signed delta
    (e.g. -1 when a consumable runs out). Get ids from search_catalog. Fails if
    the adjustment would take stock below zero."""
    parsed = _parse_uuid(catalog_id, "catalog_id")
    async with _tool_session() as session:
        result = await catalog_service.adjust_stock(session, parsed, delta, reason)
        return result.model_dump(mode="json")


@mcp.tool
async def update_catalog_tool(tool_id: str, changes: ToolUpdate) -> dict:
    """Edit a hobby tool (nippers, files, an airbrush): name, category,
    quantity_on_hand, unit_cost_reference_minor + unit_cost_reference_currency,
    condition_notes. Only the fields present in `changes` are touched; an explicit
    null clears a nullable one. The two unit-cost fields are one pair — after the
    edit the row must hold both or neither. Ids come from search_catalog.

    To count stock up or down, prefer adjust_stock: it takes a signed delta, so it
    cannot overwrite a quantity that changed between your read and your write."""
    parsed = _parse_uuid(tool_id, "tool_id")
    async with _tool_session() as session:
        row = await catalog_service.update_catalog_item(session, ItemType.TOOL, parsed, changes)
        return ToolRead.model_validate(row).model_dump(mode="json")


@mcp.tool
async def update_catalog_consumable(consumable_id: str, changes: ConsumableUpdate) -> dict:
    """Edit a consumable (paint, cement, sanding sticks): name, category,
    quantity_on_hand, low_stock_threshold. Only the fields present in `changes` are
    touched; an explicit null clears a nullable one. Ids come from search_catalog.

    To count stock up or down, prefer adjust_stock — see update_catalog_tool."""
    parsed = _parse_uuid(consumable_id, "consumable_id")
    async with _tool_session() as session:
        row = await catalog_service.update_catalog_item(
            session, ItemType.CONSUMABLE, parsed, changes
        )
        return ConsumableRead.model_validate(row).model_dump(mode="json")


@mcp.tool
async def update_catalog_upgrade(upgrade_id: str, changes: UpgradeUpdate) -> dict:
    """Edit a third-party upgrade (decals, metal parts, resin conversions): name,
    manufacturer, quantity_on_hand. Only the fields present in `changes` are
    touched. Ids come from search_catalog.

    To count stock up or down, prefer adjust_stock — see update_catalog_tool."""
    parsed = _parse_uuid(upgrade_id, "upgrade_id")
    async with _tool_session() as session:
        row = await catalog_service.update_catalog_item(session, ItemType.UPGRADE, parsed, changes)
        return UpgradeRead.model_validate(row).model_dump(mode="json")


@mcp.tool
async def apply_upgrade(upgrade_id: str, kit_id: str, quantity: PositiveInt4 = 1) -> dict:
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
