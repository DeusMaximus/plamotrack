import logging
import uuid
from typing import Any

from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import (
    Consumable,
    DisplayItem,
    ItemType,
    OrderItem,
    Tool,
    Upgrade,
    UpgradeApplication,
)
from app.schemas.catalog import (
    CatalogSearchResult,
    ConsumableCreate,
    ConsumableUpdate,
    DisplayItemCreate,
    DisplayItemUpdate,
    StockAdjustmentResult,
    ToolCreate,
    ToolUpdate,
    UpgradeCreate,
    UpgradeUpdate,
)
from app.services.names import (
    WHITESPACE,
    clean_optional_text,
    clean_required_text,
    require_unique_name,
)
from app.services.numeric import require_int4
from app.services.write_gate import acquire_write_gate

logger = logging.getLogger(__name__)

#: Any row of a fungible catalog table. Named once so a fifth type is one line
#: here rather than an edit at every signature that carries the union.
type CatalogRow = Tool | Consumable | Upgrade | DisplayItem


def guard_stock_ceiling(name: str, quantity: int) -> int:
    """`quantity`, or a 409 saying it won't fit in the column.

    The third route into #74, and the one no request schema can close. Bounding the
    input fields stops a caller *stating* a number int4 can't hold; it does nothing
    about a legal number **derived** out of range — 2,000,000,000 on hand and a
    receipt of 200,000,000 more are each perfectly valid on their own. Left
    unchecked that lands as an `IntegrityError` at flush: a 500 naming a constraint,
    after the rest of the transaction has already been written.

    A conflict rather than invalid input, and deliberately the same class of error
    as its opposite: "you cannot take 5 from 3 on hand" and "you cannot add 5 to a
    number already at the ceiling" are both the stored state refusing the operation,
    not the caller mistyping something. The floors stay written out at each call
    site — their messages say what was being removed and suggest what to do about
    it, and one merged message would say less at both.
    """
    try:
        return require_int4(quantity, f"'{name}' would hold {quantity:,}")
    except ValueError as exc:
        raise ConflictError(str(exc)) from exc


#: The fungible catalog tables an order line (or stock adjustment) can target.
#: Adding one here is most of what a new catalog type costs — search, stock
#: adjustment, the order dispatch, locking and deletion all read this rather than
#: naming the tables (#126).
CATALOG_MODELS: dict[ItemType, type[CatalogRow]] = {
    ItemType.TOOL: Tool,
    ItemType.CONSUMABLE: Consumable,
    ItemType.UPGRADE: Upgrade,
    ItemType.DISPLAY: DisplayItem,
}

#: The catalog tables that carry a `category` column — today all but `upgrades`,
#: which was considered for one and decided against (#127; §3.5). Derived from the
#: mapped columns rather than restated, so the category filter, the distinct-values
#: surface and the canonicalisation below pick a table up the moment it grows the
#: column, with no second list to update.
CATEGORISED_MODELS: dict[ItemType, type[CatalogRow]] = {
    item_type: model
    for item_type, model in CATALOG_MODELS.items()
    if "category" in model.__table__.columns
}


async def lock_catalog_row(
    session: AsyncSession, model: type[CatalogRow], item_id: uuid.UUID
) -> CatalogRow | None:
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


def _to_search_result(item_type: ItemType, row: CatalogRow) -> CatalogSearchResult:
    return CatalogSearchResult(
        item_type=item_type,
        id=row.id,
        name=row.name,
        category=getattr(row, "category", None),
        manufacturer=getattr(row, "manufacturer", None),
        scale=getattr(row, "scale", None),
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


async def canonical_category(
    session: AsyncSession,
    model: type[CatalogRow],
    category: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """The spelling `category` is stored under: an existing category of this table
    matching case-insensitively is reused, otherwise the input stands as given (#127).

    Reuse rather than refuse — the opposite lean from `require_unique_name` — because
    a category is a *grouping*, not an identity: two tools named alike are a
    conflict, two tools categorised "Cutting" and "cutting" are one group fragmented.
    Where legacy rows already hold several spellings of one key, the most frequent
    wins — the same entry `list_catalog_categories` puts on top, so what a write
    folds onto is exactly what the typeahead offers. Ties break by byte order under
    `COLLATE "C"`, pinned explicitly because the winner is *stored*: the database's
    own collation orders case differently between libc flavours, and the dev Mac
    and CI must not canonicalise onto different spellings. Per-table, like every
    name predicate: a tool category and a consumable category are separate
    vocabularies.

    `exclude_id` is the update path's own row (`require_unique_name`'s #107 shape):
    re-casing the category on the only row holding it is the user correcting the
    vocabulary entry itself, and without the exclusion the row's stored spelling
    would silently win over the correction.

    Callers hold the write gate (every caller is a writer already), which is what
    keeps two concurrent writers from each minting their own spelling of a new
    category. Folding and trimming both happen in Postgres, stored side trimmed with
    the Python whitespace set — the `names._same_key` rule, for the same #49/#109
    reasons. What is selected and returned is the *trimmed* stored spelling, not the
    raw cell: a legacy row can carry padding from before trimming existed, and
    reusing its bytes would write that padding onto every new row that folds onto
    it (#130 review, P2-2). The spelling is the vocabulary entry; the padding is
    an accident of one row.
    """
    trimmed = func.btrim(model.category, WHITESPACE)
    stmt = (
        select(trimmed)
        .where(func.lower(trimmed) == func.lower(category.strip()))
        .group_by(trimmed)
        .order_by(func.count().desc(), trimmed.collate("C"))
        .limit(1)
    )
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    existing = await session.scalar(stmt)
    return existing if existing is not None else category


async def _create_catalog_row(
    session: AsyncSession,
    model: type[CatalogRow],
    data: ToolCreate | ConsumableCreate | UpgradeCreate | DisplayItemCreate,
) -> CatalogRow:
    """The one insert behind every catalog create, so the name rule is applied once.

    Gate first, then the name check, then the insert: the check is a read the insert
    depends on, and only the gate makes two callers naming the same new item at once
    produce one row and one 409 (rule 7.1). Refused rather than merged — see
    `create_retailer` (#107).
    """
    await acquire_write_gate(session)
    fields = data.model_dump()
    _normalise_text(model, fields)
    fields["name"] = await require_unique_name(session, model, data.name)
    if fields.get("category"):
        fields["category"] = await canonical_category(session, model, fields["category"])
    row = model(**fields)
    session.add(row)
    await session.flush()
    await session.commit()
    return row


async def create_tool(session: AsyncSession, data: ToolCreate) -> Tool:
    return await _create_catalog_row(session, Tool, data)


async def create_consumable(session: AsyncSession, data: ConsumableCreate) -> Consumable:
    return await _create_catalog_row(session, Consumable, data)


async def create_upgrade(session: AsyncSession, data: UpgradeCreate) -> Upgrade:
    return await _create_catalog_row(session, Upgrade, data)


async def create_display_item(session: AsyncSession, data: DisplayItemCreate) -> DisplayItem:
    return await _create_catalog_row(session, DisplayItem, data)


async def list_catalog(
    session: AsyncSession, model: type[CatalogRow], category: str | None = None
) -> list[CatalogRow]:
    stmt = select(model).order_by(model.name)
    if category is not None:
        if "category" not in model.__table__.columns:
            # Reachable through the MCP tool, whose item_type and category are
            # independent arguments; the REST routes never declare the parameter
            # on a table without the column.
            raise InvalidInputError(
                f"{model.__tablename__} have no category column, so they cannot be filtered by one"
            )
        # Case-insensitive equality, not ILIKE — the `list_kits` grade/series
        # predicate shape, for the same #49 reasons: `%` and `_` in a category are
        # characters, and both sides fold in Postgres so the folds cannot disagree.
        # The stored side is additionally trimmed: a legacy padded row is the same
        # logical category as its trimmed spelling, and the vocabulary below offers
        # the trimmed form — a filter that can't find what the vocabulary offered
        # would be the two surfaces disagreeing (#130 review, P2-2).
        trimmed = func.btrim(model.category, WHITESPACE)
        stmt = stmt.where(func.lower(trimmed) == func.lower(category.strip()))
    return list((await session.scalars(stmt)).all())


async def list_catalog_categories(session: AsyncSession, model: type[CatalogRow]) -> list[str]:
    """The category values in use on one catalog table, most frequent first (#127).

    `list_kit_series`'s shape (#96), for the same reason: category is free text, so
    the select-or-create device for it is a vocabulary the form's typeahead and the
    MCP tool both read before writing. Frequency order puts the spelling the
    collection actually uses on top; ties break alphabetically (case-insensitively,
    then by byte order under `COLLATE "C"` for the case-variant pairs legacy rows
    can hold — the same pin `canonical_category` carries, so the listing is stable
    across libc flavours). Per-table — a tool category and a consumable category
    are separate vocabularies, exactly as their names are separate namespaces.
    """
    if "category" not in model.__table__.columns:
        raise InvalidInputError(
            f"{model.__tablename__} have no category column, so there is no "
            "category vocabulary to list"
        )
    # category is NOT NULL on every table that has it, but rows written before
    # #129's blank refusal can hold whitespace — the btrim guard hides those the
    # way `list_kit_series`'s does, with the same whitespace set (#109's lesson).
    # Selected and grouped *trimmed*, like `canonical_category` and the filter: a
    # padded legacy row and its clean siblings are one vocabulary entry, offered
    # in the spelling a filter can actually find (#130 review, P2-2).
    trimmed = func.btrim(model.category, WHITESPACE)
    stmt = (
        select(trimmed)
        .where(trimmed != "")
        .group_by(trimmed)
        .order_by(func.count().desc(), func.lower(trimmed), trimmed.collate("C"))
    )
    return list((await session.scalars(stmt)).all())


#: Fields that are NOT NULL on at least one catalog table — an explicit null in a
#: PATCH is rejected *where the column actually forbids it*. `manufacturer` is the
#: reason for that qualifier: NOT NULL on upgrades, nullable on display items, so
#: membership here is a shortlist to check rather than the answer (`_is_nullable`).
_NON_NULLABLE = {"name", "category", "manufacturer", "quantity_on_hand"}


def _is_nullable(model: type[CatalogRow], field: str) -> bool:
    column = model.__table__.columns.get(field)
    return column is not None and column.nullable


def _normalise_text(model: type[CatalogRow], fields: dict[str, Any]) -> None:
    """Trim every free-text column in place; refuse blank where the column is NOT
    NULL, store None where it is nullable.

    Driven off the mapped columns rather than a list of field names, for the same
    reason `_is_nullable` is: `manufacturer` is required on upgrades and optional on
    display items, and one hardcoded set cannot be right for both. `name` is skipped
    — `require_unique_name` calls `clean_name` on it, which is the same rule plus
    the uniqueness check (#129 review, P3-4).
    """
    for key, value in list(fields.items()):
        column = model.__table__.columns.get(key)
        if column is None or not isinstance(column.type, String) or key == "name":
            continue
        if column.nullable:
            fields[key] = clean_optional_text(value)
        elif value is not None:
            fields[key] = clean_required_text(value, key)


async def update_catalog_item(
    session: AsyncSession,
    item_type: ItemType,
    item_id: uuid.UUID,
    data: ToolUpdate | ConsumableUpdate | UpgradeUpdate | DisplayItemUpdate,
) -> CatalogRow:
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
        # Checked against the column rather than the name: `manufacturer` is NOT
        # NULL on upgrades and nullable on display items, so a shared name set
        # alone would refuse a legitimate clear on the latter.
        if value is None and key in _NON_NULLABLE and not _is_nullable(model, key):
            raise InvalidInputError(f"{key} cannot be null")
    _normalise_text(model, fields)
    if fields.get("name") is not None:
        # A rename onto a name another row of this table holds is a 409; the row's
        # own id is excluded so it may keep or re-case its name (#107).
        fields["name"] = await require_unique_name(
            session, model, fields["name"], exclude_id=item_id
        )
    if fields.get("category"):
        # Same exclusion, opposite lean: another row's spelling is reused rather
        # than refused, and the row's own is excluded so a re-case can correct it.
        fields["category"] = await canonical_category(
            session, model, fields["category"], exclude_id=item_id
        )
    for key, value in fields.items():
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
    """Resolve a catalog id across the fungible tables and adjust its stock."""
    # Both callers now bound `delta` at their own edge — `Int4` on the MCP tool
    # argument and on `StockAdjustmentRequest` (#55) — but the check stays here
    # because the service is where they meet (rule 1), and a bound enforced only at
    # two edges is a bound the next caller can skip. A 3-billion delta is the caller
    # mistyping, which is a 422, while a delta that *derives* out of range is the
    # stored state refusing, below (#74).
    try:
        require_int4(delta, f"delta '{delta:,}'")
    except ValueError as exc:
        raise InvalidInputError(str(exc)) from exc

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
        guard_stock_ceiling(row.name, new_quantity)
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
    raise NotFoundError(f"no catalog item with id {catalog_id}")
