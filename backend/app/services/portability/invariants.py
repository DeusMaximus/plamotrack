"""What an import plan is not allowed to do to an order (#44).

`apply_import` writes model rows by direct `setattr`, so every column is freely
mutable and the importer can do things REST and MCP refuse. Rule 1 — "routers and
MCP tools are thin wrappers over the same service functions" — was written when
there were two writers; the CSV importer is a third, reaching the same tables by a
different road.

**Rerouting import through `services/orders.py` is not the fix**, and is ruled out
on purpose. `receive_order` applies stock, which rule 10 forbids an import from
deriving; `_update_line` fights the §3.9 hybrid dispatch that only spawns the kits
nothing else supplies. What the two sides share is the *predicates* —
`kit_progressed`, `PROGRESSED_STATUSES` and `IMMUTABLE_LINE_COLUMNS` all live in
`services/orders.py` and are imported here — while each keeps its own mutation
path.

Everything in this module is a refusal at **preview** time: the row is marked
ERROR and named in the plan, so `_finish` raises it as a blocking error and the
operator reads it before confirming rather than after applying. A row already in
ERROR is left alone — it has a diagnosis, and a second one describing a value the
importer failed to parse in the first place would be noise.

### Receipt is a refusal, not a representation (#44 case 4)

`orders.received_at` is an ordinary DATA column, so a merge import can move it in
either direction with none of the accounting a receive implies. The ambiguity it
creates — an order that says "received" while its catalog stock says otherwise —
is not one this codebase can hold: `received_at is not None` is the proxy for
"stock was applied" in four separate places in `services/orders.py`
(`create_order`, `update_order`, `receive_order`, `delete_order`). Teaching four
stock mutators to tell "received" from "received but unapplied" needs a column,
and the column has no correct backfill and no answer in the CSV (rule 9). So the
state is deleted instead of represented: an import may not flip the flag on an
order whose lines would have moved stock.

**Only the flip, and only where stock is at stake.** A kit-only order transitions
in both directions exactly as #79 made it — that is the starter-sheet path, where
a receipt arriving by import is the normal case. A create is not a transition: a
full archive restores received orders and their post-receipt `quantity_on_hand`
together (rule 10), and that is how the invariant survives today. A timestamp
corrected from one non-null value to another is not a transition either.
"""

import uuid
from typing import TYPE_CHECKING, Any

from app.models import ItemType
from app.schemas.portability import RowAction
from app.services.orders import IMMUTABLE_LINE_COLUMNS
from app.services.portability.spec import CATALOG_TABLE_BY_ITEM_TYPE

if TYPE_CHECKING:  # pragma: no cover - typing only, and importing.py imports us
    from app.services.portability.importing import _Row


def check(
    rows: dict[str, list["_Row"]],
    *,
    by_id: dict[str, dict[uuid.UUID, Any]],
    created_ids: dict[str, set[uuid.UUID]],
    replace_all: bool,
) -> None:
    """Run every order invariant over a built plan, marking rows that fail.

    Called once, after the table pass and *before* `_plan_spawns`: a line this
    refuses must not also contribute a fan-out or a removal, and `_plan_spawns`
    already skips ERROR rows.
    """
    _check_immutable_line_columns(rows)
    _check_catalog_targets(rows, by_id=by_id, created_ids=created_ids, replace_all=replace_all)
    _check_receipt_transitions(rows)


def _writes(row: "_Row") -> bool:
    """Whether this row will actually be written. ERROR is already diagnosed and
    SKIP (add_only) leaves the stored row exactly as it is, so neither can break
    an invariant about what lands."""
    return row.action not in (RowAction.ERROR, RowAction.SKIP)


def _change(row: "_Row", field: str):
    return next((change for change in row.changes if change.field == field), None)


# --- an existing line's identity is settled (cases 1 and 3) ----------------------


def _check_immutable_line_columns(rows: dict[str, list["_Row"]]) -> None:
    """A stored order line may not change `item_type` or `order_id`.

    Reads `row.changes` rather than comparing values, so a sheet that merely
    restates the column it already holds is silent — the same reading
    `_advance_kits_for_newly_received_orders` takes of `received_at`, and the
    reason a full archive re-import stays a no-op.
    """
    for row in rows.get("order_items", []):
        if row.action is not RowAction.UPDATE or row.target is None:
            continue
        for column in IMMUTABLE_LINE_COLUMNS:
            change = _change(row, column)
            if change is None:
                continue
            row.action = RowAction.ERROR
            row.error = _immutable_message(column, change.before, change.after)
            break


def _immutable_message(column: str, before: str, after: str) -> str:
    if column == "item_type":
        return (
            f"item_type: this row would turn a stored {before} line into a {after} one, and a "
            f"line's item_type cannot change — the two dispatch differently ({before} lines "
            f"and {after} lines already had their side effects). Remove the line and add a "
            "new one, the same as the app requires"
        )
    return (
        f"order_id: this row would move the line from order {before} to order {after}, and a "
        "line cannot change orders — that is the purchase record, and its kits would follow "
        "it across with no stock or lifecycle effect. Leave order_id as it is, and add a new "
        "line to the other order if that is what you meant"
    )


# --- a catalog line points at something (the third preview refusal) --------------


def effective_item_type(row: "_Row") -> Any:
    """What this row's line will be once written — the sheet's `item_type` where it
    states one, otherwise the stored line's. A partial sheet legitimately omits the
    column, and reading `values` alone would then treat every such row as typeless
    and skip the check that matters most.

    Public because `_plan_spawns` needs the same reading and did not have it: it
    tested `row.values.get("item_type") is not ItemType.KIT` directly, so an update
    omitting the column skipped the fan-out entirely and a reduced quantity left
    every kit attached (external review of #86). One definition, because two
    readings of "what type is this line" is how that happened — the correct one
    already existed here when the wrong one was written one module over."""
    if "item_type" in row.present and row.values.get("item_type") is not None:
        return row.values["item_type"]
    return getattr(row.target, "item_type", None)


def _check_catalog_targets(
    rows: dict[str, list["_Row"]],
    *,
    by_id: dict[str, dict[uuid.UUID, Any]],
    created_ids: dict[str, set[uuid.UUID]],
    replace_all: bool,
) -> None:
    """A tool/consumable/upgrade line has to resolve to a row in *its own* catalog
    table.

    `catalog_ref_id` is polymorphic across three tables, so no foreign key can hold
    it (see the model) and nothing downstream notices a line pointing nowhere. Such
    a line can never apply stock on receive and can never have it reversed on
    delete — it is the same dangling shape as #63, arriving by a route anyone can
    reach. Rule 3's select-or-create keeps REST and MCP off it entirely: they take
    a `catalog_ref_id` or a `new_item` and refuse a line with neither.

    Only asked of a row that says something about the reference: a create always
    does, and an update does when the sheet carries the column at all — including
    as a blank cell, which would null a stored reference rather than leave it
    alone.
    """
    for row in rows.get("order_items", []):
        if not _writes(row):
            continue
        if row.action is not RowAction.CREATE and "catalog_ref_id" not in row.present:
            continue
        item_type = effective_item_type(row)
        if item_type is None or item_type is ItemType.KIT:
            continue
        table = CATALOG_TABLE_BY_ITEM_TYPE.get(str(item_type))
        if table is None:
            continue
        ref_id = row.values.get("catalog_ref_id")
        resolved = ref_id is not None and (
            ref_id in created_ids[table] or (not replace_all and ref_id in by_id[table])
        )
        if resolved:
            continue
        row.action = RowAction.ERROR
        row.error = (
            f"catalog_ref_id: a {item_type} line has to point at a row in {table}.csv, and "
            f"this one points at "
            + (f"{ref_id}, which no {table} row has" if ref_id else "nothing")
            + f". Give it a catalog_ref_id, or name the item in catalog_name and one will be "
            f"created in {table}.csv at 0 on hand"
        )


# --- receipt state carries accounting (case 4) ----------------------------------


def _catalog_types_on(row: "_Row", incoming: dict[uuid.UUID, list["_Row"]]) -> set[str]:
    """Every non-kit item_type this order will hold once the import lands — the
    lines already stored on it, plus the lines this upload puts on it.

    The union, not either half. A line the upload adds to an order it also receives
    is stock left just as unaccounted as one that was already there, and a stored
    catalog line is unaccounted whether or not this upload mentions it.
    """
    types: set[str] = set()
    for item in row.target.items:
        if item.item_type is not ItemType.KIT:
            types.add(str(item.item_type))
    for line in incoming.get(row.matched_id, []):
        item_type = effective_item_type(line)
        if item_type is not None and item_type is not ItemType.KIT:
            types.add(str(item_type))
    return types


def _catalog_files(types: set[str]) -> str:
    files = sorted(
        f"{CATALOG_TABLE_BY_ITEM_TYPE[item_type]}.csv"
        for item_type in types
        if item_type in CATALOG_TABLE_BY_ITEM_TYPE
    )
    if len(files) <= 1:
        return files[0] if files else "the catalog files"
    return f"{', '.join(files[:-1])} and {files[-1]}"


def _check_receipt_transitions(rows: dict[str, list["_Row"]]) -> None:
    """Refuse a `received_at` flip on an order whose lines move stock.

    `before`/`after` are `render()` output, so `""` is null — the same reading
    `_advance_kits_for_newly_received_orders` relies on, and the only one that
    tells a first arrival apart from a correction between two non-null timestamps.

    **`replace_all` is carried by the `UPDATE` test, not by a mode check.** An
    explicit `if replace_all: return` sat here first and was removed: in that mode
    `build` marks every row `CREATE` and never matches a target, so the guard could
    not be reached, and a mutation-test build with it removed changed nothing. What
    actually keeps an archive restore importable is that a create is not a
    transition — the archive
    carries the received order and the post-receipt `quantity_on_hand` together
    (rule 10) — and `test_a_received_order_with_catalog_lines_still_restores_from_
    an_archive` drives both modes over it.
    """
    incoming: dict[uuid.UUID, list[_Row]] = {}
    for line in rows.get("order_items", []):
        if not _writes(line):
            continue
        order_id = line.values.get("order_id")
        if order_id is not None:
            incoming.setdefault(order_id, []).append(line)

    for row in rows.get("orders", []):
        change = _change(row, "received_at")
        if change is None:
            continue
        # A `received_at` *change* exists only against a stored row: `_classify`
        # fills `changes` by diffing a matched target and leaves it empty
        # otherwise, so a create cannot reach here — which covers every row of a
        # `replace_all` and a brand-new order in a merge, and is what keeps an
        # archive of a received order importable. An explicit
        # `if row.action is not RowAction.UPDATE` guard sat here first and was
        # removed: `changes` non-empty is exactly equivalent to UPDATE, so
        # nothing could make the guard decide, and a mutation-test build with it
        # removed changed nothing. #41 learned the same thing from the other side — a create's
        # `changes` is empty, so any rule written against it is silent there.
        arriving = not change.before and bool(change.after)
        clearing = bool(change.before) and not change.after
        if not (arriving or clearing):
            continue
        types = _catalog_types_on(row, incoming)
        if not types:
            # Kit-only, in both directions: #79's reviewed behaviour, and the
            # starter sheet's normal case. Nothing on this order moved stock, so
            # nothing about the flip can leave stock unaccounted for.
            continue
        row.action = RowAction.ERROR
        row.error = _receipt_message(arriving, types)


def _receipt_message(arriving: bool, types: set[str]) -> str:
    files = _catalog_files(types)
    listed = ", ".join(sorted(types))
    if arriving:
        return (
            f"received_at: marking this order received would leave the stock its {listed} "
            f"line(s) bought unaccounted for — an import never changes what you have on hand "
            f"(rule 10), and afterwards the app can't apply it either, because the order "
            f"already reads as received. State the on-hand quantity in {files}, or take "
            f"received_at out of this sheet and receive the order in the app, which does "
            f"apply it"
        )
    return (
        f"received_at: clearing it would leave the stock this order's {listed} line(s) "
        f"already added to your on-hand counts exactly where it is, while making the order "
        f"receivable again — the next receive would add it a second time. Un-receiving an "
        f"order isn't supported anywhere in plamotrack, by import or otherwise: if the "
        f"receipt was a mistake, delete the order — that reverses the stock it applied — "
        f"and enter it again as pending. To correct the count on its own and leave the "
        f"order alone, state it in {files}"
    )
