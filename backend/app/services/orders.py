import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import (
    Consumable,
    DisplayItem,
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
from app.services.catalog import (
    CATALOG_MODELS,
    CATEGORISED_MODELS,
    CatalogRow,
    canonical_category,
    guard_stock_ceiling,
    lock_catalog_row,
)
from app.services.kits import default_scale_for_grade, has_applied_upgrades, stamp_build_date
from app.services.names import (
    clean_name,
    clean_optional_text,
    find_by_name,
    require_unique_name,
)
from app.services.write_gate import acquire_write_gate

#: The most units one order line may hold.
#:
#: Not a field bound: a kit line fans out into this many `kits` rows at entry
#: (§3.9), so the number is an insert count that a single cell decides, and
#: nothing downstream of `quantity > 0` limited it (#43). int4 is no help — a
#: quantity PostgreSQL stores happily is still two billion inserts.
#:
#: Set where one line stops being a plausible personal purchase for a
#: single-collection tracker. A genuine bulk buy says so on more than one line,
#: which is also how it reads on the order it came from.
MAX_LINE_QUANTITY = 1_000


def require_line_quantity(quantity: int, *, label: str = "quantity") -> int:
    """The whole valid range REST, MCP and the CSV importer all answer to (rule 1).

    Three writers reach the same fan-out by three different routes, and a limit
    enforced on one of them is not a limit. `label` exists so the importer can name
    the column it read rather than a payload field the sheet has never heard of.

    **Both ends, not just the ceiling.** REST and MCP get the lower bound from
    `Field(gt=0)` on `OrderItemCreate`, but the importer builds models directly and
    never constructs one — so while this checked `> MAX` alone, a `quantity` of 0 or
    -2 in a CSV planned as a clean create and hit the `quantity_positive` database
    constraint at flush, which is a 500 rather than a row diagnostic. A shared
    invariant that covers one end of the range is two invariants, and the half that
    isn't shared is the half that drifts.
    """
    if quantity < 1:
        raise InvalidInputError(
            f"{label} is {quantity:,} — that has to be at least 1. "
            "To record nothing, leave the line out."
        )
    if quantity > MAX_LINE_QUANTITY:
        raise InvalidInputError(
            f"{label} is {quantity:,} — an order line holds at most "
            f"{MAX_LINE_QUANTITY:,}. Split it across several lines."
        )
    return quantity


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

    The currency falls back to the one already recorded before it falls back to
    the instance default: correcting a typo'd amount on a GBP snapshot must not
    relabel it AUD, which is the same "config never overwrites a record" rule the
    rest of this function exists to enforce. A brand-new snapshot has nothing to
    inherit, so it still takes the reference currency.
    """
    if "converted_price_minor" not in line.model_fields_set:
        return
    if line.converted_price_minor is None:
        item.converted_price_minor = None
        item.converted_currency_code = None
        return
    item.converted_price_minor = line.converted_price_minor
    item.converted_currency_code = (
        line.converted_currency_code
        or item.converted_currency_code
        or get_settings().reference_currency
    )


# A kit that has visibly progressed is never silently deleted by order edits.
PROGRESSED_STATUSES = {KitStatus.BUILDING, KitStatus.COMPLETE}
# Statuses that a delivery arrival naturally advances to backlog (in hand, unbuilt).
ARRIVAL_ELIGIBLE = {KitStatus.PRE_ORDERED, KitStatus.ORDERED, KitStatus.IN_TRANSIT}
# Statuses a shipment naturally advances to in_transit (#95) — one stage before
# ARRIVAL_ELIGIBLE, which is why in_transit itself is not in it.
SHIP_ELIGIBLE = {KitStatus.PRE_ORDERED, KitStatus.ORDERED}

#: Columns of a stored order line no edit may change, whichever writer it arrives
#: through (#44).
#:
#: Both are settled at entry and mean something the line cannot restate later:
#:
#: * ``item_type`` picks the §3.9 dispatch. A kit line has fanned out into `kits`
#:   rows; a catalog line has (or will have) moved `quantity_on_hand`. Changing it
#:   leaves the old side effect in place with nothing left pointing at it.
#: * ``order_id`` is purchase provenance. Moving a line — and the kits it spawned —
#:   between orders silently rewrites what was bought where, and can move it across
#:   a receipt boundary with no stock or lifecycle effect at all.
#:
#: REST enforces the two by different mechanisms, which is why nothing named them
#: together before: `_update_line` refuses an `item_type` change outright, and
#: `order_id` is unreachable there because an id that isn't already on the order is
#: rejected by `update_order` as not belonging to it. The CSV importer writes every
#: column directly and needs them as one set — `services/portability/invariants.py`
#: reads this tuple.
IMMUTABLE_LINE_COLUMNS: tuple[str, ...] = ("item_type", "order_id")


def receipt_is_future(received_at: datetime) -> bool:
    """Whether a receipt date has not happened yet — a typo, not a plan (#93).

    Judged as a calendar date in the datetime's *own* offset, not as an instant
    against the server clock. The caller asserts "it arrived on this date, in my
    time zone" — comparing instants would refuse an honest "today" over nothing
    more than clock skew between the browser (or an MCP agent's machine) and the
    server, while a whole calendar day of slack never turns a real backdate into
    a refusal. The instance has no time zone of its own until M5.1; the supplied
    offset is the only local calendar available.

    Deliberately NOT judged here: a receipt earlier than the order's own
    `order_date`. `order_date` is a plain date with no offset, so the comparison
    is not well-defined across time zones — a same-day store purchase entered in
    UTC+10 can hold a receipt instant that is "yesterday" in UTC — and backfilled
    collections carry approximate dates. Odd is allowed; impossible is not.

    The predicate is separate from the refusal so the CSV importer can apply the
    same calendar judgment as a preview-time row error (rule 1) — every writer
    refuses the same set of values, in one place.
    """
    today_in_own_offset = datetime.now(received_at.tzinfo).date()
    return received_at.date() > today_in_own_offset


def _refuse_future_receipt(received_at: datetime) -> None:
    if receipt_is_future(received_at):
        raise InvalidInputError(
            f"received_at {received_at.isoformat()} is in the future — "
            "an arrival can be backdated, not predicted"
        )


def _refuse_future_ship(shipped_at: datetime) -> None:
    # Same calendar judgment as the receipt (#95 borrows #93's rule wholesale);
    # only the column named differs.
    if receipt_is_future(shipped_at):
        raise InvalidInputError(
            f"shipped_at {shipped_at.isoformat()} is in the future — "
            "a shipment can be backdated, not predicted"
        )


# --- retailers -----------------------------------------------------------------


async def create_retailer(session: AsyncSession, data: RetailerCreate) -> Retailer:
    await acquire_write_gate(session)
    fields = data.model_dump()
    # Refused, not merged: a REST or MCP caller that named an existing shop gets a 409
    # naming it, and decides. Merging silently would hand back a row the caller did
    # not ask for and could not tell apart from a create (#107, rule 3).
    fields["name"] = await require_unique_name(session, Retailer, data.name)
    retailer = Retailer(**fields)
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
    a failed order creation rolls the new retailer back too — no partial data.

    Gated even though it doesn't commit, and gated *before* the lookup: this is a
    check-then-insert, so two agents naming the same new shop would otherwise both
    see nothing and both insert it — fragmenting the retailer list, which is the
    one thing this function exists to prevent. MCP's create_order calls this
    before the gated `create_order`, so without the gate here that read happens
    outside it."""
    await acquire_write_gate(session)
    wanted = clean_name(name)
    # Equality after case-folding, not ILIKE: a pattern match reads `%` and `_` in
    # the *agent's* input as wildcards, so a shop named "%" attached its order to
    # whichever retailer sorted first, and read `\` as its escape, so a shop with a
    # backslash in its name was never reused (#49). The predicate itself lives in
    # `services/names.py` — the same one the create and rename paths refuse on
    # (#107), so what this reuses and what they refuse can never disagree.
    retailer = await find_by_name(session, Retailer, wanted)
    if retailer is None:
        retailer = Retailer(name=wanted)
        session.add(retailer)
        await session.flush()
    return retailer


async def update_retailer(
    session: AsyncSession, retailer_id: uuid.UUID, data: RetailerUpdate
) -> Retailer:
    await acquire_write_gate(session)
    retailer = await session.get(Retailer, retailer_id)
    if retailer is None:
        raise NotFoundError(f"retailer {retailer_id} not found")
    fields = data.model_dump(exclude_unset=True)
    if fields.get("name") is None and "name" in fields:
        raise InvalidInputError("name cannot be null")
    if fields.get("name") is not None:
        # `exclude_id`: a row may keep or re-case its own name; only *another* row
        # already holding it is a conflict (#107).
        fields["name"] = await require_unique_name(
            session, Retailer, fields["name"], exclude_id=retailer.id
        )
    for key, value in fields.items():
        setattr(retailer, key, value)
    await session.flush()
    await session.commit()
    return retailer


async def delete_retailer(session: AsyncSession, retailer_id: uuid.UUID) -> None:
    await acquire_write_gate(session)
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


async def _build_catalog_row(
    session: AsyncSession, item_type: ItemType, new_item: NewCatalogItem, currency_code: str
) -> CatalogRow:
    """The catalog row a `new_item` line creates — or a 409 if one already answers to
    that name.

    `new_item` is the select-or-create flow's *create* half (§3.9); the select half
    is `search_catalog`, and it is only a gate if the caller used it. An agent that
    skipped it, or a human who typed past the typeahead, was making a second row with
    the same name — which the importer then reads as an ambiguous natural key (#107).
    The check is here rather than in the two callers so a line added at entry and a
    line added on edit answer to one rule. Two `new_item` lines in one request naming
    the same thing refuse as well: the first is flushed before the second is checked,
    and the whole order rolls back with it (rule 2) — say it on one line with the
    quantity, or pick the row the first line created.
    """
    # Trimmed before it is judged, and the trimmed value is what gets stored.
    # `not "   "` is False, so whitespace passed every one of these checks and landed
    # in a NOT NULL column verbatim (#129 review, P3-4). `clean_optional_text` is the
    # same rule for the columns where blank legitimately means "not recorded".
    category = clean_optional_text(new_item.category)
    manufacturer = clean_optional_text(new_item.manufacturer)
    if item_type in (ItemType.TOOL, ItemType.CONSUMABLE, ItemType.DISPLAY) and not category:
        raise InvalidInputError(f"new {item_type} items require a category")
    if category is not None and item_type in CATEGORISED_MODELS:
        # Same rule as the direct create/update paths (#127): a category matching an
        # existing one case-insensitively reuses that spelling. Three live writers
        # reach these tables and the vocabulary only holds if all three fold.
        # Gated on the tables that carry the column: `NewCatalogItem` is one schema
        # for every line type, so an upgrade line may state a category, and the
        # standing behaviour is to ignore it — not to 500 on a column upgrades
        # don't have (#130 review, P2-1).
        category = await canonical_category(session, CATEGORISED_MODELS[item_type], category)
    name = await require_unique_name(session, CATALOG_MODELS[item_type], new_item.name)
    if item_type is ItemType.TOOL:
        # The line's own currency, not the instance default: this row is being created
        # from a purchase that states what it was bought in, and that is the one place
        # a tool's cost ever arrives with its currency already known (§6).
        cost_minor = new_item.unit_cost_reference_minor
        return Tool(
            name=name,
            category=category,
            quantity_on_hand=0,
            unit_cost_reference_minor=cost_minor,
            unit_cost_reference_currency=currency_code if cost_minor is not None else None,
            condition_notes=clean_optional_text(new_item.condition_notes),
        )
    if item_type is ItemType.CONSUMABLE:
        return Consumable(
            name=name,
            category=category,
            quantity_on_hand=0,
            low_stock_threshold=new_item.low_stock_threshold,
        )
    if item_type is ItemType.DISPLAY:
        # `manufacturer` is optional here, unlike upgrades below: a commercial set
        # states one and a scratch-built piece has none (#126).
        return DisplayItem(
            name=name,
            category=category,
            scale=clean_optional_text(new_item.scale),
            manufacturer=manufacturer,
            quantity_on_hand=0,
            notes=clean_optional_text(new_item.notes),
        )
    if not manufacturer:
        raise InvalidInputError("new upgrade items require a manufacturer")
    return Upgrade(
        name=name,
        manufacturer=manufacturer,
        quantity_on_hand=0,
    )


async def _lock_catalog_targets(
    session: AsyncSession,
    *,
    items: Iterable[OrderItem] = (),
    lines: Iterable[OrderItemCreate] = (),
) -> None:
    """Take every catalog lock this order write will need, before it needs any of them.

    Order writes are the only place in the application that holds more than one row
    lock at a time, so they are the only place that can deadlock, and they were doing
    it two ways. Both surface as a 500 on an edit that was never wrong — Postgres
    breaks the cycle itself, so integrity is never at risk, but neither is the owner's
    edit ever going to succeed on retry-by-hand if the ordering is what's wrong.

    * **Catalog against catalog.** Locks were taken in payload order, so two edits
      naming the same two items in opposite orders could each end up holding what the
      other was waiting for. Sorting by uuid gives every writer the same sequence;
      whoever arrives second simply waits.
    * **Catalog against kits.** `_line_kits` locks kits and `_adjust_ref` locks catalog
      rows, in whatever order the lines happen to appear — while `apply_upgrade` locks
      the upgrade and *then* needs FOR KEY SHARE on the kit to record an application.
      Held at once those are a cycle. Draining the catalog locks here, before the first
      kit lock is taken, puts order writes on `apply_upgrade`'s catalog → kits path.

    Both arguments are supplied where both exist: an edit can drop a target the stored
    line still holds, and adopt one only the payload names. Rows that turn out not to
    exist are skipped rather than reported — the per-line code raises that, with the
    message that knows which item was asked for.
    """
    targets: dict[uuid.UUID, type[CatalogRow]] = {}
    for referrer in (*items, *lines):
        ref_id = referrer.catalog_ref_id
        if referrer.item_type is not ItemType.KIT and ref_id is not None:
            targets[ref_id] = CATALOG_MODELS[referrer.item_type]
    for ref_id in sorted(targets):
        await lock_catalog_row(session, targets[ref_id], ref_id)


async def _adjust_ref(
    session: AsyncSession, item_type: ItemType, ref_id: uuid.UUID, delta: int
) -> None:
    """Row-locked stock adjustment with a can't-go-negative guard.

    Called after `_lock_catalog_targets` has already taken this row's lock, so the
    re-lock here is free — it exists so the arithmetic reads the row it is about to
    write, whether or not the caller pre-locked.
    """
    model = CATALOG_MODELS[item_type]
    row = await lock_catalog_row(session, model, ref_id)
    if row is None:
        # Reachable only from a stored reference, never a payload one — every caller
        # either passes `item.catalog_ref_id` or a target this transaction has just
        # validated under its lock. So this is not "you named something that doesn't
        # exist", it is a line left dangling by the unlocked delete this release fixed,
        # and 404 sends the owner looking for a request they never made. It is a
        # conflict with what is stored, and there is currently no way out of it
        # through the API — every path that touches the line reverses its stock first
        # and lands back here. Filed as #63; the message says so rather than
        # suggesting a repair that doesn't work.
        raise ConflictError(
            f"this order line points at a {item_type} ({ref_id}) that is no longer in "
            "the catalog, so its stock cannot be adjusted. A pre-0.2.4 catalog delete "
            "could race an order and leave a line behind like this; the row needs "
            "repairing in the database"
        )
    new_quantity = row.quantity_on_hand + delta
    if new_quantity < 0:
        raise ConflictError(
            f"cannot remove {-delta}× '{row.name}': only {row.quantity_on_hand} on hand "
            "(already consumed?) — adjust its stock first"
        )
    row.quantity_on_hand = guard_stock_ceiling(row.name, new_quantity)
    await session.flush()


def initial_kit_status(requested: KitStatus, received: bool, shipped: bool = False) -> KitStatus:
    """Where a kit entering the collection actually starts, given its order's state.

    Public because it is a shared predicate (rule 1): the starter-sheet expansion
    emits explicit kit rows for retailer-bearing rows (#112) and has to land them
    on the same status `spawn_kits` would have, or the two routes to an
    order-backed kit drift apart."""
    # Received wins over shipped: an order can hold both instants, and the box
    # being in hand is the later fact.
    if received and requested in ARRIVAL_ELIGIBLE:
        return KitStatus.BACKLOG
    if shipped and requested in SHIP_ELIGIBLE:
        return KitStatus.IN_TRANSIT
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
    received_at: datetime | None = None,
    shipped: bool = False,
    shipped_at: datetime | None = None,
) -> None:
    """The §3.9 fan-out: one physical `kits` row per unit on a kit-type order line.

    Shared with the CSV importer, which needs the same fan-out for order lines that
    arrive without their kits — hence the loose keyword signature rather than an
    `OrderKitDetails`, which is a REST-payload shape the importer doesn't have.

    The ceiling is re-checked here rather than trusted from the caller, because this
    is the function that does the inserting and it is reachable from a route that
    never saw an `OrderItemCreate`. The importer stops a bad line long before this,
    with a message naming the column; this is the backstop for the loop itself.
    """
    require_line_quantity(count, label="the number of kits on this line")
    requested = KitStatus(status) if status else KitStatus.ORDERED
    final_status = initial_kit_status(requested, received, shipped)
    resolved_scale = scale if scale is not None else default_scale_for_grade(grade)
    # A kit landing in backlog on a received order entered the collection when the
    # box did, so it carries the order's receipt time — which may be backdated
    # (#93) — instead of the entry time the server default would stamp. A kit
    # spawned with an explicitly asserted later status (building, complete) keeps
    # the default: the receipt is not when that status began, and "when you told
    # me" is the honest fallback.
    stamp = received_at if final_status is KitStatus.BACKLOG else None
    # The same rule one stage earlier (#95): a kit a shipment lands in transit
    # left the retailer when the parcel did. No guard on `shipped` — on an
    # unshipped order `shipped_at` is None and the server default stands, the
    # exact shape of the backlog line above.
    if final_status is KitStatus.IN_TRANSIT:
        stamp = shipped_at
    for _ in range(count):
        kit = Kit(
            name=name,
            grade=grade,
            scale=resolved_scale,
            kit_number=kit_number,
            status=final_status,
            order_item_id=item.id,
        )
        if stamp is not None:
            kit.status_updated_at = stamp
        session.add(kit)
    await session.flush()


async def _spawn_from_details(
    session: AsyncSession,
    item: OrderItem,
    details: OrderKitDetails,
    count: int,
    received: bool,
    received_at: datetime | None = None,
    shipped_at: datetime | None = None,
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
        received_at=received_at,
        shipped=shipped_at is not None,
        shipped_at=shipped_at,
    )


async def _line_kits(session: AsyncSession, item_id: uuid.UUID) -> list[Kit]:
    """This line's kits, row-locked. Every caller mutates or deletes them.

    The order lock in `_get_order_for_write` serializes order mutations against each
    other, but `apply_upgrade` never touches the order row — so it can commit an
    application between the progression check below and the delete that follows,
    and the cascade then removes it. Locking the kits closes that window: the
    application's insert needs FOR KEY SHARE on these rows, which conflicts.
    """
    stmt = (
        select(Kit)
        .where(Kit.order_item_id == item_id)
        .options(selectinload(Kit.photos), selectinload(Kit.upgrade_applications))
        .order_by(Kit.created_at, Kit.id)
        .with_for_update()
    )
    return list((await session.scalars(stmt)).all())


def kit_progressed(kit: Kit) -> bool:
    """Visible evidence that this kit is more than a row an order created.

    Applied upgrades count for a different reason than the rest: status, rating and
    photos are effort that would be lost, while an application is stock already
    spent. Deleting the kit cascades the application away and leaves that stock
    unexplained, so the same predicate covers line reduction, line removal and
    order deletion in one place.

    Public because the CSV importer's downward reconciliation asks the same
    question of the same kits (#44). Sharing the predicate is the point — sharing
    the *mutation path* is what rule 10 forbids — so a kit the Orders page won't
    delete is a kit `order_items.csv` can't delete either, by construction rather
    than by two lists agreeing.

    Requires `photos` and `upgrade_applications` to be eager-loaded; a lazy load
    here raises outside the async context.
    """
    return (
        kit.status in PROGRESSED_STATUSES
        or kit.rating is not None
        or len(kit.photos) > 0
        or has_applied_upgrades(kit)
    )


async def _delete_line_kits(session: AsyncSession, item: OrderItem, count: int | None) -> None:
    """Delete `count` spawned kits (None = all). Progressed kits are protected."""
    kits = await _line_kits(session, item.id)
    safe = [kit for kit in kits if not kit_progressed(kit)]
    needed = len(kits) if count is None else count
    if len(safe) < needed:
        raise ConflictError(
            f"cannot remove {needed} kit(s) from this line: only {len(safe)} can be "
            "deleted safely — the rest are building/complete, rated, have photos, or "
            "have upgrades applied to them. Move or edit those kits first."
        )
    targets = safe if count is None else list(reversed(safe))[:count]  # newest first
    for kit in targets:
        await session.delete(kit)
    await session.flush()


async def _add_line(
    session: AsyncSession,
    order: Order,
    line: OrderItemCreate,
    received: bool,
    received_at: datetime | None = None,
    shipped_at: datetime | None = None,
) -> OrderItem:
    """The §3.9 dispatch: kit lines FAN OUT into kits rows immediately; catalog
    lines INCREMENT stock — but only once the order is received.

    `received_at` is the receipt instant kits landing in backlog are stamped with
    (#93) — the order's stored receipt for an edit, the entry-supplied or fresh
    one for a create. None when the order is pending. `shipped_at` is the same
    thing one stage earlier (#95): non-null means the order is shipped, so kits
    land in_transit carrying it — unless received wins."""
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
        await _spawn_from_details(
            session, item, line.kit, line.quantity, received, received_at, shipped_at
        )
    else:
        if line.new_item is not None:
            row = await _build_catalog_row(
                session, line.item_type, line.new_item, line.currency_code
            )
            session.add(row)
            await session.flush()
        else:
            model = CATALOG_MODELS[line.item_type]
            row = await lock_catalog_row(session, model, line.catalog_ref_id)
            if row is None:
                raise NotFoundError(f"{line.item_type} {line.catalog_ref_id} not found")
        item.catalog_ref_id = row.id
        if received:
            row.quantity_on_hand = guard_stock_ceiling(
                row.name, row.quantity_on_hand + line.quantity
            )
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
    session: AsyncSession,
    item: OrderItem,
    line: OrderItemCreate,
    received: bool,
    received_at: datetime | None = None,
    shipped_at: datetime | None = None,
) -> None:
    if line.item_type != item.item_type:
        raise InvalidInputError(
            "a line's item_type cannot change — remove the line and add a new one"
        )

    if item.item_type is ItemType.KIT:
        details = line.kit
        line_kits = await _line_kits(session, item.id)
        # Kit details propagate to every kit this line spawned — but only the fields
        # this edit actually restated (#65).
        #
        # Propagation exists so "I misspelled the name at order entry" has one place
        # to fix (rule 2). Applied unconditionally it also meant an edit that never
        # mentioned the kits — a tracking number, a unit price — rewrote all of them
        # from whatever the caller happened to echo back, flattening kits the owner
        # had deliberately made different. Spawned kits are allowed to diverge from
        # their line; only a value that changed is worth pushing down.
        #
        # "Changed" is judged against the first spawned kit, because that is what
        # every client renders for the line and therefore what it echoes back
        # unedited. Judging it server-side rather than trusting the caller to send a
        # partial payload keeps REST and MCP on the same footing as the browser —
        # neither has to opt in to not destroying data.
        #
        # `scale` is compared exactly as sent, never resolved to the grade's default
        # first. A kit may legitimately have *no* scale — the Kits page can clear one
        # — and a client echoes that back as null, which is indistinguishable from
        # "I didn't mention it". Deriving before comparing made that untouched null
        # read as a change (`1/144 != None`) and a price edit rewrote every kit on the
        # line. So an unstated scale is never a restated one; resetting one to the
        # grade default means typing it. Spawning still derives (`spawn_kits`), which
        # is the only place a missing scale legitimately means "work one out".
        #
        # The same reading covers `kit_number`, the other nullable one: null is "not
        # mentioned", so clearing either belongs on the Kits page, which can say null
        # and mean it. `name` and `grade` are required, so the guard never sees them.
        if line_kits:
            reference = line_kits[0]
            restated = {
                field: value
                for field, value in (
                    ("name", details.name),
                    ("grade", details.grade),
                    ("scale", details.scale),
                    ("kit_number", details.kit_number),
                )
                if value is not None and value != getattr(reference, field)
            }
            for kit in line_kits:
                for field, value in restated.items():
                    setattr(kit, field, value)
        # Diff against the actual surviving kit count, not item.quantity —
        # defense in depth should the two ever drift.
        delta = line.quantity - len(line_kits)
        if delta > 0:
            await _spawn_from_details(
                session, item, details, delta, received, received_at, shipped_at
            )
        elif delta < 0:
            await _delete_line_kits(session, item, count=-delta)
    else:
        old_ref = item.catalog_ref_id
        if line.new_item is not None:
            new_row = await _build_catalog_row(
                session, line.item_type, line.new_item, line.currency_code
            )
            session.add(new_row)
            await session.flush()
            new_ref = new_row.id
        else:
            new_ref = line.catalog_ref_id
            if new_ref != old_ref:
                # Locked, not merely checked: an unlocked existence check leaves the
                # row free to be deleted before this edit commits, and the line would
                # be left pointing at nothing (there is no FK to stop it). The lock
                # also has to be held even when the order isn't received and no stock
                # moves — the reference is the thing being protected, not the count.
                model = CATALOG_MODELS[line.item_type]
                if await lock_catalog_row(session, model, new_ref) is None:
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
    await acquire_write_gate(session)
    for line in data.items:
        # Up front, before the retailer lookup and before `_lock_catalog_targets`
        # takes anything: an absurd payload should not get as far as holding row
        # locks other writers are waiting on.
        require_line_quantity(line.quantity)

    retailer = await session.get(Retailer, data.retailer_id)
    if retailer is None:
        raise NotFoundError(f"retailer {data.retailer_id} not found")

    order = Order(**data.model_dump(exclude={"items", "received", "received_at", "shipped_at"}))
    received_at: datetime | None = None
    if data.received:
        # The schema guarantees received_at only arrives alongside received=true.
        if data.received_at is not None:
            _refuse_future_receipt(data.received_at)
        received_at = data.received_at or datetime.now(UTC)
        order.received_at = received_at
    # Entry-time shipped (#95): date-or-nothing, no flag and no "now" default —
    # unlike receipt there is no separate boolean anywhere, so the instant is the
    # whole assertion. Alongside received=true it is a timeline record only.
    if data.shipped_at is not None:
        _refuse_future_ship(data.shipped_at)
        order.shipped_at = data.shipped_at
    session.add(order)
    await session.flush()

    await _lock_catalog_targets(session, lines=data.items)
    for line in data.items:
        await _add_line(
            session,
            order,
            line,
            received=data.received,
            received_at=received_at,
            shipped_at=data.shipped_at,
        )

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


async def update_order(
    session: AsyncSession,
    order_id: uuid.UUID,
    data: OrderUpdate,
    *,
    allow_line_removal: bool = True,
) -> Order:
    """Edit header fields and/or replace the line-item set (§3.9, rule 2).

    `data.items` is a FULL replacement set — deliberate REST semantics — so a
    stored line the payload does not restate is deleted, its kits removed and
    its applied stock reversed. `allow_line_removal=False` turns that omission
    into a refusal that names the lines (#97): the check runs here, under the
    order's FOR UPDATE lock, so it cannot race a concurrent line addition the
    way a read-then-write in a caller would. REST keeps the default; the MCP
    tool passes False unless the agent explicitly opts in, because an agent
    reconstructing an order from a listing is the writer most likely to send a
    partial set and least able to notice the silent deletions."""
    await acquire_write_gate(session)
    for line in data.items or ():
        require_line_quantity(line.quantity)

    order = await _get_order_for_write(session, order_id)
    received = order.received_at is not None
    await _lock_catalog_targets(session, items=order.items, lines=data.items or ())

    header = data.model_dump(exclude_unset=True, exclude={"items"})
    if "retailer_id" in header:
        if header["retailer_id"] is None:
            raise InvalidInputError("retailer_id cannot be null")
        if await session.get(Retailer, header["retailer_id"]) is None:
            raise NotFoundError(f"retailer {header['retailer_id']} not found")
    for non_nullable in ("order_date", "currency_code"):
        if non_nullable in header and header[non_nullable] is None:
            raise InvalidInputError(f"{non_nullable} cannot be null")
    if "received_at" in header:
        # Correction only (#93): a receipt date can be adjusted once it exists.
        # The pending → received transition stays in receive_order, where the
        # stock dispatch lives — letting PATCH perform it would put that dispatch
        # in two places.
        new_receipt = header.pop("received_at")
        if new_receipt is None:
            raise InvalidInputError(
                "received_at cannot be cleared — un-receiving an order is not "
                "supported; delete and re-enter the order instead"
            )
        if order.received_at is None:
            raise ConflictError(
                "order is not received yet — record the arrival through the "
                "receive endpoint; an edit only corrects a date already set"
            )
        _refuse_future_receipt(new_receipt)
        if new_receipt != order.received_at:
            await _restamp_receipt_kits(session, order, order.received_at, new_receipt)
            order.received_at = new_receipt
    if "shipped_at" in header:
        # The same correction-only shape (#95): the pending → shipped transition
        # stays in mark_order_shipped, where the kit advance lives.
        new_ship = header.pop("shipped_at")
        if new_ship is None:
            raise InvalidInputError(
                "shipped_at cannot be cleared — un-shipping an order is not supported"
            )
        if order.shipped_at is None:
            raise ConflictError(
                "order is not marked shipped yet — record the shipment through the "
                "ship endpoint; an edit only corrects a date already set"
            )
        _refuse_future_ship(new_ship)
        if new_ship != order.shipped_at:
            # Stamp equality alone is NOT enough here: a receipt recorded at the
            # same instant (one shared local midnight) stamps backlog kits with a
            # value equal to the old shipment, and those belong to the receipt.
            # Only a kit still in_transit is the shipment's to re-date.
            await _restamp_receipt_kits(
                session, order, order.shipped_at, new_ship, only_status=KitStatus.IN_TRANSIT
            )
            order.shipped_at = new_ship
    for key, value in header.items():
        setattr(order, key, value)

    if data.items is not None:
        existing = {item.id: item for item in order.items}
        if not allow_line_removal:
            payload_ids = {line.id for line in data.items if line.id is not None}
            omitted = [item for item in order.items if item.id not in payload_ids]
            if omitted:
                labels = "; ".join(
                    f"{item.id} ({item.item_type.value} × {item.quantity})" for item in omitted
                )
                raise InvalidInputError(
                    f"the items list omits {len(omitted)} stored line(s): {labels} — an "
                    "omitted line is deleted (its kits removed, applied stock reversed). "
                    "Restate every line you are not changing, or pass "
                    "remove_missing_lines=true to delete the omitted ones"
                )
        seen: set[uuid.UUID] = set()
        for line in data.items:
            if line.id is not None:
                if line.id not in existing:
                    raise InvalidInputError(f"order item {line.id} does not belong to this order")
                if line.id in seen:
                    raise InvalidInputError(f"order item {line.id} appears twice")
                seen.add(line.id)
                await _update_line(
                    session, existing[line.id], line, received, order.received_at, order.shipped_at
                )
            else:
                await _add_line(session, order, line, received, order.received_at, order.shipped_at)
        for item_id, item in existing.items():
            if item_id not in seen:
                await _remove_line(session, item, received)

    await session.flush()
    result = await get_order(session, order.id)
    await session.commit()
    return result


async def _restamp_receipt_kits(
    session: AsyncSession,
    order: Order,
    old: datetime,
    new: datetime,
    *,
    only_status: KitStatus | None = None,
) -> None:
    """A corrected receipt date follows the kits whose stamp *was* the receipt (#93).

    Receiving stamps the kits it advances with the same instant it writes to the
    order, so equality against the old value identifies exactly the kits whose
    last transition was that receipt — a kit dragged onward (or back) since then
    carries the drag's own time and is left alone. Status is deliberately not part
    of the RECEIPT match: the timestamp is the receipt's signature, and a status
    check would either restate the same fact or wrongly exclude a kit the entry
    itself stamped.

    `only_status` is the SHIP correction's narrower ownership rule (#95, review
    round one P2): a ship and a receive can legitimately share an instant — two
    date inputs on one calendar day both serialise as the same local midnight —
    and the receipt owns the backlog kit, so the ship correction follows only
    kits still in_transit whose stamp equals the old shipment. The receipt call
    keeps stamp-equality alone; do not tighten it, that contract is #93's."""
    for item in order.items:
        if item.item_type is not ItemType.KIT:
            continue
        for kit in await _line_kits(session, item.id):
            if only_status is not None and kit.status is not only_status:
                continue
            if kit.status_updated_at == old:
                kit.status_updated_at = new


async def mark_order_shipped(
    session: AsyncSession, order_id: uuid.UUID, shipped_at: datetime | None = None
) -> Order:
    """Mark an order shipped: record the instant and advance kits still ahead of
    transit (pre_ordered / ordered → in_transit), mirroring `receive_order` one
    stage earlier (#95). Applies NO stock — `received_at` stays the sole proxy
    for "stock was applied" (rule 2), which is also why there is nothing to lock
    beyond the order row itself.

    `shipped_at` backdates the shipment (#93's rule, borrowed wholesale);
    omitted, it shipped now. The kits this advances are stamped with the same
    instant either way. Legal on an already-received order: the ship date is
    chronologically prior information worth recording after the fact, and the
    kits are past the stage, so the advance naturally moves nothing.
    Double-shipping 409s like double-receiving. Deliberately NOT cross-validated
    against `order_date` (not comparable across time zones, #93) or
    `received_at` (#113's rule: the user owns the values, and a service-side
    check would diverge from the importer)."""
    await acquire_write_gate(session)
    order = await _get_order_for_write(session, order_id)
    if order.shipped_at is not None:
        raise ConflictError("order is already marked shipped")
    if shipped_at is not None:
        _refuse_future_ship(shipped_at)
    now = shipped_at or datetime.now(UTC)
    order.shipped_at = now
    for item in order.items:
        if item.item_type is ItemType.KIT:
            for kit in await _line_kits(session, item.id):
                if kit.status in SHIP_ELIGIBLE:
                    kit.status = KitStatus.IN_TRANSIT
                    kit.status_updated_at = now
                    # A no-op for in_transit today, same wiring rule as the
                    # receive advance (#94): every live status writer goes
                    # through the one derivation.
                    stamp_build_date(kit, KitStatus.IN_TRANSIT, now)

    await session.flush()
    result = await get_order(session, order.id)
    await session.commit()
    return result


async def receive_order(
    session: AsyncSession, order_id: uuid.UUID, received_at: datetime | None = None
) -> Order:
    """Mark an order arrived: apply catalog stock increments and advance kits
    still in the ordering pipeline to backlog (in hand, unbuilt).

    `received_at` backdates the arrival for orders received before they were
    logged (#93); omitted, the arrival is now. The kits this advances are stamped
    with the same instant either way."""
    await acquire_write_gate(session)
    order = await _get_order_for_write(session, order_id)
    if order.received_at is not None:
        raise ConflictError("order is already marked received")
    await _lock_catalog_targets(session, items=order.items)

    if received_at is not None:
        _refuse_future_receipt(received_at)
    now = received_at or datetime.now(UTC)
    order.received_at = now
    for item in order.items:
        if item.item_type is ItemType.KIT:
            for kit in await _line_kits(session, item.id):
                if kit.status in ARRIVAL_ELIGIBLE:
                    kit.status = KitStatus.BACKLOG
                    kit.status_updated_at = now
                    # A no-op for backlog today, but every live status writer goes
                    # through the one derivation (#94) so an advance that one day
                    # lands elsewhere cannot silently skip the build stamps.
                    stamp_build_date(kit, KitStatus.BACKLOG, now)
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
    await acquire_write_gate(session)
    order = await _get_order_for_write(session, order_id)
    received = order.received_at is not None
    await _lock_catalog_targets(session, items=order.items)
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
