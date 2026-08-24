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
from app.services.orders import IMMUTABLE_LINE_COLUMNS, receipt_is_future
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
    _check_lines_joining_received_orders(rows, by_id=by_id, replace_all=replace_all)
    _check_receipt_transitions(rows)
    _check_future_receipts(rows)
    _check_ship_dates(rows)


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
    `importing._Planner._newly_set` takes of `received_at`, and the
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


def effective_item_type(row: "_Row", stored: Any | None = None) -> Any:
    """What this row's line will be once written — the sheet's `item_type` where it
    states one, otherwise the stored line's. A partial sheet legitimately omits the
    column, and reading `values` alone would then treat every such row as typeless
    and skip the check that matters most.

    Public because `_plan_spawns` needs the same reading and did not have it: it
    tested `row.values.get("item_type") is not ItemType.KIT` directly, so an update
    omitting the column skipped the fan-out entirely and a reduced quantity left
    every kit attached (external review of #86). One definition, because two
    readings of "what type is this line" is how that happened — the correct one
    already existed here when the wrong one was written one module over.

    `stored` is for the one caller that runs before matching has bound
    `row.target`: `_resolve_ref` dispatches the catalog reference by this same
    reading, and at that point the stored line is a lookup it has to make itself
    (#90). Precedence is unchanged — the sheet's stated type always wins."""
    if "item_type" in row.present and row.values.get("item_type") is not None:
        return row.values["item_type"]
    return getattr(row.target if row.target is not None else stored, "item_type", None)


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


def _check_lines_joining_received_orders(
    rows: dict[str, list["_Row"]],
    *,
    by_id: dict[str, dict[uuid.UUID, Any]],
    replace_all: bool,
) -> None:
    """Refuse a NEW catalog line joining an order that was already received (#87).

    #44 case 4a's end state, reached from the other side: `_check_receipt_transitions`
    refuses the *flip* on an order with catalog lines; this refuses the *line*
    joining an order whose stored `received_at` is already set. Either way the state
    that never gets represented is "received, with stock unaccounted" (rule 2.1) —
    without this, the line imported cleanly, its stock was never applied (rule 10),
    and the order became undeletable with a message blaming consumption that never
    happened, while a quantity edit moved stock by a delta from a phantom baseline.

    Only a **create**, and only against a **stored** parent. An UPDATE's stock was
    applied when the line originally dispatched, and a line on an order this same
    upload creates is an archive restoring a received order together with its
    post-receipt counts — the same create-is-a-restore reading as the transition
    check. Kit lines stay legal in every shape: kits carry no stock, and a kit
    joining a received order is the ordinary backdated-line case (#93).

    **The `replace_all` return is load-bearing, unlike the transition check's
    (whose docstring explains why it has none).** `by_id` is loaded from the
    database that mode is about to truncate, and an archive exported from this
    same instance keeps its uuids — so without the return, restoring a received
    catalog order over itself would find its own doomed row as the "stored"
    parent and refuse its own restore. The archive is judged against itself, the
    same reason `_check_catalog_targets` skips the stored lookup in that mode.

    A same-file flip needs no case here: the transition check reads the union of
    stored and incoming lines, so an upload that both flips `received_at` and
    adds the catalog line is already refused on the order row. This check reads
    the stored state alone.
    """
    if replace_all:
        return
    for row in rows.get("order_items", []):
        if row.action is not RowAction.CREATE:
            continue
        item_type = effective_item_type(row)
        if item_type is None or item_type is ItemType.KIT:
            continue
        parent = by_id["orders"].get(row.values.get("order_id"))
        if parent is None or parent.received_at is None:
            continue
        row.action = RowAction.ERROR
        row.error = _joining_received_message(str(item_type))


def _joining_received_message(item_type: str) -> str:
    return (
        f"order_id: this {item_type} line would join an order that's already received, "
        f"and an import never changes what you have on hand (rule 10) — the units would "
        f"read as bought but never counted, and deleting or editing the order later "
        f"would move stock that was never applied. Add the line in the app instead, "
        f"which applies the stock as it saves, or restore a full archive with "
        f"replace_all"
    )


def _check_receipt_transitions(rows: dict[str, list["_Row"]]) -> None:
    """Refuse a `received_at` flip on an order whose lines move stock.

    `before`/`after` are `render()` output, so `""` is null — the same reading
    `importing._Planner._newly_set` relies on, and the only one that
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


def _check_future_receipts(rows: dict[str, list["_Row"]]) -> None:
    """Refuse a `received_at` this upload writes onto a date that hasn't happened.

    The same calendar judgment every other writer applies — `receipt_is_future`
    from `services/orders.py`, the instant's own offset (#93) — surfaced as a
    preview-time row error. Entry, receive and correction already refuse it on
    REST and MCP; without this the importer was the one writer that accepted it,
    and the arrival stamps would carry the impossible date onto the Board
    (Codex round five, P2).

    Reads the *change*, not the cell, for the same reason the transition check
    above does: a stored future value — admitted before this check existed —
    restates and round-trips untouched, and a create is a restore rather than a
    data-entry path (§12.5's create rule, applied to the date), so an archive
    carrying a legacy future receipt stays importable. That is stated policy,
    not accident: the cost, accepted, is that a hand-written CSV can still
    *create* a future order. Both arrival (null → future) and correction
    (non-null → future) are caught — the transition check is deliberately silent
    on corrections, so this is the only voice on that shape.
    """
    for row in rows.get("orders", []):
        if row.action is RowAction.ERROR:
            # Already refused — the transition check's stock story is the more
            # instructive message on a catalog-order arrival, future-dated or not.
            continue
        change = _change(row, "received_at")
        if change is None or not change.after:
            continue
        value = row.values.get("received_at")
        if value is not None and receipt_is_future(value):
            row.action = RowAction.ERROR
            row.error = (
                f"received_at: {value.isoformat()} is in the future — an arrival can be "
                f"backdated, not predicted (the same refusal the app gives). State the day "
                f"the order actually arrived, or take received_at out of this sheet"
            )


def _check_ship_dates(rows: dict[str, list["_Row"]]) -> None:
    """`shipped_at` under the same two rules its live writers apply (#95):
    un-shipping is not supported anywhere, and a shipment cannot be in the
    future.

    Shipping applies no stock, so — unlike the receipt — the null → non-null
    direction is free on every order, catalog lines included; the kits it
    advances are `_plan_advances`' job, as hash-bound descriptors (#119).
    Clearing mirrors REST's refusal (rule 1): there is no un-ship transition
    anywhere, so a sheet may not be the way around. The future rule reads the
    change, not the cell, exactly as `_check_future_receipts` above — a stored
    legacy value restates as a no-op, and a create is a restore (§12.5's create
    rule, applied to the date).
    """
    for row in rows.get("orders", []):
        if row.action is RowAction.ERROR:
            continue
        change = _change(row, "shipped_at")
        if change is None:
            continue
        if change.before and not change.after:
            row.action = RowAction.ERROR
            row.error = (
                "shipped_at: clearing it would un-ship the order, and un-shipping isn't "
                "supported anywhere in plamotrack, by import or otherwise. To correct the "
                "date, state the actual one; to leave it alone, take shipped_at out of "
                "this sheet"
            )
            continue
        value = row.values.get("shipped_at")
        if value is not None and change.after and receipt_is_future(value):
            row.action = RowAction.ERROR
            row.error = (
                f"shipped_at: {value.isoformat()} is in the future — a shipment can be "
                f"backdated, not predicted (the same refusal the app gives). State the day "
                f"it actually shipped, or take shipped_at out of this sheet"
            )


def _receipt_message(arriving: bool, types: set[str]) -> str:
    files = _catalog_files(types)
    listed = ", ".join(sorted(types))
    if arriving:
        # One remedy, not two. An earlier wording offered "state the on-hand
        # quantity in consumables.csv" as an alternative, and it is not one: this
        # check never reads the catalog files, so an upload that states the count
        # *and* flips received_at is refused again with the same message. Measured
        # (pre-round on #86) — the operator following it lands back here. A count
        # stated on its own is the *clearing* message's remedy, where the order is
        # left alone; here the order is being flipped, and only the app can do
        # that with the stock accounted for.
        return (
            f"received_at: marking this order received would leave the stock its {listed} "
            f"line(s) bought unaccounted for — an import never changes what you have on hand "
            f"(rule 10), and the app couldn't apply it afterwards either, because the order "
            f"would already read as received. Take received_at out of this sheet and receive "
            f"the order in the app, which applies the stock. A count stated in {files} "
            f"doesn't stand in for that: it corrects a number, and this receipt is still "
            f"refused"
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
