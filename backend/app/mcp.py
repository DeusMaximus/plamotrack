"""MCP tools (§7) — thin wrappers over the same service layer the REST API uses,
so agents hit identical business logic (fan-out/increment dispatch, de-dup search,
stock guards) without any duplicated rules."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime

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
    DisplayItemRead,
    DisplayItemUpdate,
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
    OrderUpdate,
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
        "an existing item's id — free-text duplicates fragment the catalog. A new_item "
        "or create_retailer whose name matches an existing row case-insensitively is "
        "refused with a conflict naming that row; a near-miss ('Tamiya cement' vs "
        "'Tamiya Extra Thin Cement') is not, which is why searching first still matters."
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


def _parse_instant(value: str, field: str = "received_at") -> datetime:
    """A timeline instant supplied by an agent: ISO 8601, offset required (#93).

    The offset is the only local calendar the app has until the instance grows a
    time zone (M5.1) — a naive datetime would silently mean whatever the server's
    clock means, which is exactly the ambiguity being refused. `field` names the
    argument in the refusal — received_at and shipped_at (#95) share the rule."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ToolError(
            f"{field} {value!r} is not ISO 8601 — e.g. 2026-05-04T14:30:00+10:00"
        ) from None
    if parsed.tzinfo is None:
        raise ToolError(
            f"{field} {value!r} has no UTC offset — include one "
            "(e.g. 2026-05-04T14:30:00+10:00, or a trailing Z for UTC)"
        )
    return parsed


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
async def list_kits(
    status: str | None = None, grade: str | None = None, series: str | None = None
) -> list[dict]:
    """List kits in the collection, optionally filtered by pipeline status
    (pre_ordered, ordered, in_transit, backlog, building, complete — backlog
    means in hand but not started), grade (HG, RG, MG, PG, SD, ...) and/or
    series (exact name, case-insensitively — get the spellings in use from
    list_kit_series)."""
    parsed_status = _parse_status(status) if status else None
    async with _tool_session() as session:
        kits = await kits_service.list_kits(
            session, status=parsed_status, grade=grade, series=series
        )
        return [KitRead.model_validate(k).model_dump(mode="json") for k in kits]


@mcp.tool
async def list_kit_series() -> list[str]:
    """The series names already in use on kits, most frequent first. ALWAYS check
    this before writing a series onto a kit and reuse an existing spelling when
    one matches — series is free text, so "IBO" and "Iron-Blooded Orphans" would
    otherwise fragment into two filter entries for one series."""
    async with _tool_session() as session:
        return await kits_service.list_kit_series(session)


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
    hand, not started), building, complete. Entering building/complete stamps
    build_started_at/build_completed_at with now — only when that date is still
    null, so a real date already recorded is never overwritten; use update_kit
    to backfill or correct the dates themselves."""
    parsed_id = _parse_uuid(kit_id, "kit_id")
    parsed_status = _parse_status(status)
    async with _tool_session() as session:
        kit = await kits_service.update_kit(session, parsed_id, KitUpdate(status=parsed_status))
        return KitRead.model_validate(kit).model_dump(mode="json")


@mcp.tool
async def update_kit(kit_id: str, changes: _KitPatch) -> dict:
    """Edit a kit's details: name, grade, scale, kit_number, series, status,
    rating (1-5), build_notes, build_started_at, build_completed_at. Before
    setting a series, check list_kit_series and reuse an existing spelling. Only
    the fields present in `changes` are touched, so this is safe to call with a
    single field; sending an
    explicit null clears a nullable one (build_notes: null erases the notes, and a
    rating can be taken back the same way). Name, grade and status cannot be
    nulled — they are always set on a kit. The build dates are offset-aware ISO
    8601 (e.g. "2026-02-08T00:00:00+10:00") and belong to the user: a status
    transition stamps one only when it is null, so supply a value here to backfill
    the real date and it will never be overwritten by a later move.
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
    """Search tools, consumables, upgrades, and display items by name (same search
    the UI typeahead uses). ALWAYS call this before adding catalog items to an order
    — reuse an existing item's id as catalog_ref_id instead of creating a duplicate.

    Results carry `item_type`, so filter on that to search within one kind. Display
    items also carry `scale` ("1/144") and a `category`."""
    async with _tool_session() as session:
        results = await catalog_service.search(session, query)
        return [r.model_dump(mode="json") for r in results]


@mcp.tool
async def list_retailers() -> list[dict]:
    """List every shop on record, with rating, packing quality, shipping speed and
    notes. Call this before create_retailer to find the spelling and id a shop already
    has: create_order matches an existing shop by name (case-insensitively, whitespace
    trimmed), and create_retailer refuses a name that matches one."""
    async with _tool_session() as session:
        retailers = await orders_service.list_retailers(session)
        return [RetailerRead.model_validate(r).model_dump(mode="json") for r in retailers]


@mcp.tool
async def create_retailer(retailer: RetailerCreate) -> dict:
    """Add a shop with its full detail. Only `name` is required — a retailer named
    on create_order is created with nothing but a name, and update_retailer fills in
    the rest afterwards. A name that matches an existing shop case-insensitively
    (surrounding whitespace ignored) is refused with a conflict naming that shop and
    its id — reuse it, or update_retailer if its spelling is what is wrong."""
    async with _tool_session() as session:
        row = await orders_service.create_retailer(session, retailer)
        return RetailerRead.model_validate(row).model_dump(mode="json")


@mcp.tool
async def update_retailer(retailer_id: str, changes: RetailerUpdate) -> dict:
    """Rate or annotate a shop: rating (1-5), packing_quality, shipping_speed,
    would_order_again, url, notes, name. Only the fields present in `changes` are
    touched; an explicit null clears a nullable one (notes: null erases the notes).
    Name cannot be nulled, and cannot be changed to a name another shop already
    holds (case-insensitively) — that is a conflict. Ids come from list_retailers.

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
    received_at: str | None = None,
    shipped_at: str | None = None,
) -> dict:
    """Record a purchase. The retailer is matched by name case-insensitively and
    created if new; order_date is ISO format (YYYY-MM-DD). Item lines follow the
    order's dispatch semantics: a `kit` line needs `kit` details (name, grade,
    optional kit_number; status defaults to `ordered`, use `pre_ordered` for
    pre-orders) and spawns one collection row per quantity. A tool, consumable,
    upgrade or display line needs either `catalog_ref_id` (an id from search_catalog
    — always search first) or `new_item` details; a `new_item` whose name matches an
    existing row of that table case-insensitively is refused with a conflict naming the row,
    and the whole order with it. A new tool, consumable or display item needs a
    `category`; a new upgrade needs a `manufacturer` (optional on display items).
    Catalog stock does NOT increase until the order is received: pass
    received=true for store purchases already in hand, or call
    mark_order_received when a shipment arrives. When logging a purchase that
    arrived before now (a backlog entry, an old confirmation email), also pass
    received_at — offset-aware ISO 8601, e.g. "2026-05-04T14:30:00+10:00" — so the
    order and the kits it delivered carry the real arrival instead of entry time;
    received_at requires received=true and may not be in the future. A parcel
    already on its way when logged can pass shipped_at (same format, needs no
    flag): spawned kits land in_transit stamped with it instead of ordered.
    Include the
    retailer's order_number from the confirmation email when available (support
    reference — only unique per retailer, never treat it as an identifier). Prices
    are integer minor units (cents/yen) with an ISO 4217 currency_code; omit
    currency_code to use the instance's own reference currency (see the `meta`
    resource)."""
    try:
        parsed_date = date.fromisoformat(order_date)
    except ValueError:
        raise ToolError(f"order_date {order_date!r} is not ISO format (YYYY-MM-DD)") from None
    parsed_received_at = _parse_instant(received_at) if received_at is not None else None
    if parsed_received_at is not None and not received:
        raise ToolError(
            "received_at asserts the order arrived — pass received=true with it, or omit the date"
        )
    parsed_shipped_at = _parse_instant(shipped_at, "shipped_at") if shipped_at is not None else None
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
            received_at=parsed_received_at,
            shipped_at=parsed_shipped_at,
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
async def get_order(order_id: str) -> dict:
    """Read one order in full: header fields, received state, and every line with
    its id, prices, the §6 conversion snapshot, and the kits it spawned. ALWAYS
    read the order with this before editing it with update_order — line edits are
    keyed by the line ids this returns, and the full line set you must restate
    comes from here. Ids come from list_orders."""
    parsed = _parse_uuid(order_id, "order_id")
    async with _tool_session() as session:
        order = await orders_service.get_order(session, parsed)
        return OrderRead.model_validate(order).model_dump(mode="json")


@mcp.tool
async def update_order(
    order_id: str, changes: OrderUpdate, remove_missing_lines: bool = False
) -> dict:
    """Correct an order after entry: header fields (order_date, order_number,
    tracking, shipping_cost_minor, currency_code, retailer_id) and/or the line
    set. Read the order with get_order first. Only the fields present in
    `changes` are touched.

    `changes.items`, when present, is the FULL replacement set: a line with an
    `id` (from get_order) updates that line, a line without one is added — and a
    stored line you leave out is DELETED, its kits removed and its applied stock
    reversed. To guard against that, an items list that omits stored lines is
    refused (naming them) unless you pass remove_missing_lines=true; restate
    every line you are not changing. Line edits re-run the dispatch: kit details
    propagate to spawned kits, quantity changes spawn or remove kits, and stock
    follows on received orders. Kits that are building/complete, rated, or have
    photos, and stock already consumed, block destructive edits with a conflict.
    A line's item_type cannot change. Omit converted_price_minor /
    converted_currency_code to keep a line's stored entry-time conversion
    snapshot — never restate that pair from guesswork; an explicit null clears
    it. `received_at` (offset-aware ISO 8601) corrects a receipt date already
    set and moves the kits that receipt delivered; on a pending order it is a
    conflict — use mark_order_received to record an arrival. `shipped_at` is
    the same correction-only shape: it re-dates kits still in_transit from that
    shipment, 409s on a never-shipped order (use mark_order_shipped), and
    cannot be nulled — un-shipping is not supported."""
    parsed = _parse_uuid(order_id, "order_id")
    async with _tool_session() as session:
        order = await orders_service.update_order(
            session, parsed, changes, allow_line_removal=remove_missing_lines
        )
        return OrderRead.model_validate(order).model_dump(mode="json")


@mcp.tool
async def mark_order_received(order_id: str, received_at: str | None = None) -> dict:
    """Mark an order as arrived/delivered: catalog stock increments are applied
    and kits still in the ordering pipeline (pre_ordered/ordered/in_transit)
    move to backlog. Find the order with list_orders(pending_only=true).
    If the delivery actually arrived earlier — logging it after the fact — pass
    received_at as offset-aware ISO 8601 (e.g. "2026-05-04T14:30:00+10:00"); the
    order and the kits it advances are stamped with that instant instead of now.
    It may not be in the future."""
    parsed = _parse_uuid(order_id, "order_id")
    parsed_received_at = _parse_instant(received_at) if received_at is not None else None
    async with _tool_session() as session:
        order = await orders_service.receive_order(session, parsed, parsed_received_at)
        return OrderRead.model_validate(order).model_dump(mode="json")


@mcp.tool
async def mark_order_shipped(order_id: str, shipped_at: str | None = None) -> dict:
    """Mark an order as shipped by the retailer: kits still ahead of transit
    (pre_ordered/ordered) move to in_transit. Applies NO stock — that happens
    when the order is received on arrival, and an order can still be received
    without ever being marked shipped. If the parcel actually left earlier —
    logging a shipping notification after the fact — pass shipped_at as
    offset-aware ISO 8601 (e.g. "2026-05-04T14:30:00+10:00"); the order and the
    kits it advances are stamped with that instant instead of now. It may not
    be in the future. To correct a ship date already recorded, use
    update_order."""
    parsed = _parse_uuid(order_id, "order_id")
    parsed_shipped_at = _parse_instant(shipped_at, "shipped_at") if shipped_at is not None else None
    async with _tool_session() as session:
        order = await orders_service.mark_order_shipped(session, parsed, parsed_shipped_at)
        return OrderRead.model_validate(order).model_dump(mode="json")


@mcp.tool
async def adjust_stock(catalog_id: str, delta: Int4, reason: str | None = None) -> dict:
    """Adjust on-hand quantity of any catalog item — tool, consumable, upgrade or
    display item — by a signed delta (e.g. -1 when a consumable runs out). Get ids
    from search_catalog. Fails if the adjustment would take stock below zero."""
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
    edit the row must hold both or neither. Ids come from search_catalog. A rename
    onto a name another tool already holds (case-insensitively) is a conflict.

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
    A rename onto a name another consumable already holds (case-insensitively) is a
    conflict.

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
    touched. Ids come from search_catalog. A rename onto a name another upgrade
    already holds (case-insensitively) is a conflict.

    To count stock up or down, prefer adjust_stock — see update_catalog_tool."""
    parsed = _parse_uuid(upgrade_id, "upgrade_id")
    async with _tool_session() as session:
        row = await catalog_service.update_catalog_item(session, ItemType.UPGRADE, parsed, changes)
        return UpgradeRead.model_validate(row).model_dump(mode="json")


@mcp.tool
async def update_catalog_display(display_item_id: str, changes: DisplayItemUpdate) -> dict:
    """Edit a display item (action stands, system bases, diorama scenery, backdrop
    panels — anything bought to display models rather than to become part of one):
    name, category, scale, manufacturer, quantity_on_hand, notes. Only the fields
    present in `changes` are touched; an explicit null clears a nullable one. Ids
    come from search_catalog. A rename onto a name another display item already
    holds (case-insensitively) is a conflict.

    Display items are tracked by quantity only — there is deliberately no link to
    the kits they are used with, because a stand moves between kits freely. Do not
    look for one, and do not encode it in the notes as if it were structured.

    To count stock up or down, prefer adjust_stock — see update_catalog_tool."""
    parsed = _parse_uuid(display_item_id, "display_item_id")
    async with _tool_session() as session:
        row = await catalog_service.update_catalog_item(session, ItemType.DISPLAY, parsed, changes)
        return DisplayItemRead.model_validate(row).model_dump(mode="json")


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
