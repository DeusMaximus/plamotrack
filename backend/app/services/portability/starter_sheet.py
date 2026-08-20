"""The one-file onboarding sheet.

Someone migrating off a spreadsheet has a kit list, not a normalized purchase
ledger. This module defines a single denormalized CSV — one row per kit, with the
retailer and price inline — and expands it into the normalized table rows the
regular importer already understands. Everything downstream (matching, preview,
apply) is then the same code path as an archive import.

Rows that name a retailer become an order; rows that don't become standalone kits.
Rows sharing a retailer + date + order number collapse into one order with several
lines, so a five-kit haul is five rows here and one order in the app.
"""

import uuid
from collections import OrderedDict
from dataclasses import dataclass

from app.config import get_settings
from app.exceptions import InvalidInputError
from app.models.enums import KitStatus
from app.services.orders import require_line_quantity
from app.services.portability.spec import (
    ColumnSpec,
    col,
    enum_parser,
    parse_bool,
    parse_date,
    parse_datetime,
    parse_decimal,
    parse_int,
    parse_text,
)

# Stable namespace so the same sheet always synthesizes the same order ids —
# re-importing then matches on id rather than relying on the fingerprint fallback.
_NAMESPACE = uuid.UUID("6f9b1f4e-3c2a-4d0e-9a71-5b8e2c1d7a90")

#: Carries the source CSV line number through expansion, so a preview error still
#: points at the row the human typed rather than a synthesized one.
_ROW_MARKER = "_source_row"

_KIT_STATUS = enum_parser(
    KitStatus, aliases={"in hand": "backlog", "in_hand": "backlog", "arrived": "backlog"}
)

#: Column order here is the order a human reads them in — kit first, purchase second.
STARTER_SHEET_COLUMNS: tuple[ColumnSpec, ...] = (
    col("kit_name", parse_text, required=True, help="e.g. RX-79(G) Ground Type"),
    col("grade", parse_text, required=True, help="HG / RG / MG / PG / SD / ..."),
    col("scale", parse_text, help="Blank = derived from the grade (HG -> 1/144)."),
    col("kit_number", parse_text, help="Manufacturer product code."),
    col("series", parse_text, help="e.g. Iron-Blooded Orphans. Free text."),
    col(
        "status",
        _KIT_STATUS,
        help="pre_ordered / ordered / in_transit / backlog / building / complete. "
        "Blank = backlog (in hand, not started).",
    ),
    col(
        "build_started",
        parse_datetime,
        help="YYYY-MM-DD — when you started building it. Blank = not recorded.",
    ),
    col(
        "build_completed",
        parse_datetime,
        help="YYYY-MM-DD — when you finished it. Blank = not recorded.",
    ),
    col("rating", parse_int, help="1-5, if you've finished it."),
    col("build_notes", parse_text),
    col(
        "quantity",
        parse_int,
        help="How many of this kit. Blank = 1, at most 1000 — you get that many "
        "kits whether or not the row names a retailer.",
    ),
    col("retailer", parse_text, help="Where you bought it. Blank = no order recorded."),
    col("order_date", parse_date, help="YYYY-MM-DD. Required if a retailer is named."),
    col("order_number", parse_text, help="The shop's reference, if you have it."),
    col("unit_price", parse_decimal, help="Major units per kit, e.g. 49.99."),
    col(
        "currency",
        parse_text,
        help="3-letter ISO code, e.g. JPY. Blank = this instance's reference currency.",
    ),
    col(
        "received",
        parse_bool,
        help="yes/no — has it arrived? Blank = yes. State it on any row of an "
        "order; rows of the same order must not contradict each other.",
    ),
)

STARTER_SHEET_HEADER: list[str] = [column.name for column in STARTER_SHEET_COLUMNS]

#: Placeholder resolved by `starter_sheet_examples()`. A downloaded template full
#: of somebody else's currency is exactly the AUD assumption this stopped baking in.
_INSTANCE_CURRENCY = "\0currency\0"

_STARTER_SHEET_EXAMPLES: list[dict[str, str]] = [
    {
        "kit_name": "RX-79(G) Ground Type",
        "grade": "HG",
        "series": "",
        "scale": "",
        "kit_number": "HGUC 210",
        "status": "backlog",
        "build_started": "",
        "build_completed": "",
        "rating": "",
        "build_notes": "",
        "quantity": "1",
        "retailer": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-88213",
        "unit_price": "24.50",
        "currency": _INSTANCE_CURRENCY,
        "received": "yes",
    },
    {
        "kit_name": "MSN-04 Sazabi Ver.Ka",
        "grade": "MG",
        "series": "",
        "scale": "",
        "kit_number": "",
        "status": "building",
        "build_started": "",
        "build_completed": "",
        "rating": "",
        "build_notes": "Panel-lined, waiting on decals.",
        "quantity": "1",
        "retailer": "Hobby Link Japan",
        "order_date": "2026-03-14",
        "order_number": "HLJ-88213",
        "unit_price": "112.00",
        "currency": _INSTANCE_CURRENCY,
        "received": "yes",
    },
    {
        "kit_name": "RX-78-2 Gundam Ver.3.0",
        "grade": "MG",
        "series": "Mobile Suit Gundam",
        "scale": "",
        "kit_number": "",
        "status": "complete",
        "build_started": "2026-01-10",
        "build_completed": "2026-02-08",
        "rating": "5",
        "build_notes": "First MG. Still proud of it.",
        "quantity": "1",
        "retailer": "",
        "order_date": "",
        "order_number": "",
        "unit_price": "",
        "currency": "",
        "received": "",
    },
]


def starter_sheet_examples() -> list[dict[str, str]]:
    """Sample rows for the downloadable template, in this instance's currency."""
    currency = get_settings().reference_currency
    return [
        {name: (currency if value == _INSTANCE_CURRENCY else value) for name, value in row.items()}
        for row in _STARTER_SHEET_EXAMPLES
    ]


def is_starter_sheet(header: list[str]) -> bool:
    """`kit_name` also exists on order_items, so the absence of `order_id` is what
    actually distinguishes the flat sheet from a normalized one."""
    names = {name.strip().lower() for name in header}
    return "kit_name" in names and "order_id" not in names


def _order_key(retailer: str, order_date: str, order_number: str) -> str:
    return "|".join((retailer.strip().lower(), order_date.strip(), order_number.strip().lower()))


def _present(source_row: str, **cells: str) -> dict[str, str]:
    """Keep only the cells this sheet actually says something about.

    A column that's present but blank means "set this to nothing" everywhere else
    in the importer — which is right for a full archive and wrong here. The flat
    sheet has no opinion on a retailer's packing quality, so it must not emit that
    column at all, or importing a kit list would wipe the report card off a shop
    you've already rated.
    """
    row = {name: value for name, value in cells.items() if value != ""}
    row[_ROW_MARKER] = source_row
    return row


def _standalone_count(cell: str) -> int:
    """How many kits a retailer-free row stands for.

    Blank is one, as the sheet's guidance says. Anything else has to be a whole
    number of at least one, and is held to the same ceiling as an order line: this
    branch is the one route to a kit that produces no order line, so it is also the
    one route `_check_line_quantity` never sees.
    """
    try:
        count = parse_int(cell)
    except (ArithmeticError, ValueError) as exc:
        raise InvalidInputError(f"quantity: {exc}") from exc
    if count is None:
        return 1
    # The whole range, from the shared invariant — not a second lower bound written
    # out here, which is how the two branches of this sheet came to disagree about
    # what `quantity: 0` means in the first place.
    return require_line_quantity(count)


#: How a resolved receipt reads back in a diagnostic, so the message quotes the
#: sheet's own vocabulary rather than Python's.
_YES_NO = {True: "yes", False: "no"}


@dataclass(frozen=True)
class _Receipt:
    """An explicit `received` value, and the row that stated it."""

    stated: bool
    row: str


def _received(cell: str) -> bool | None:
    """What one row's `received` cell states, or None if it states nothing.

    Anything that isn't blank has to actually parse as yes/no, so a typo like
    `maybe` is a row error rather than a silent "received". The blank default is
    *not* applied here: this sheet is denormalized, so several rows can describe
    one order, and a blank cell on one of them has to stay distinguishable from
    an explicit `no` on another until the whole group has been read (`_resolve_
    receipt`).
    """
    try:
        return parse_bool(cell)
    except ValueError as exc:
        raise InvalidInputError(f"received: {exc}") from exc


def expand(
    rows: list[dict[str, str]],
    *,
    row_budget: int,
) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    """Flat sheet rows -> normalized {table_key: [row, ...]}, plus what wouldn't go.

    Cells stay strings: the output is fed straight back through the normal parsing
    and planning path, so the flat sheet gets identical validation and matching to
    a hand-written orders.csv. Row provenance is carried on `_source_row` so
    preview errors can still point at the line the human actually typed.

    The second return value carries rows this expansion could not honour. They
    become blocking errors on the upload rather than an exception, so a bad
    quantity is shown in the preview beside the good rows — the same contract every
    other row error gets. A retailer-free row has no order line for the importer to
    hang an error on, which is why it has to be reported from here.
    """
    retailers: OrderedDict[str, dict[str, str]] = OrderedDict()
    orders: OrderedDict[str, dict[str, str]] = OrderedDict()
    #: Explicit receipt statements per order key. An order with no entry was
    #: never told either way, and falls back to the documented "blank = yes".
    receipts: dict[str, _Receipt] = {}
    order_items: list[dict[str, str]] = []
    kits: list[dict[str, str]] = []
    problems: list[str] = []
    produced = 0

    def spend(count: int) -> None:
        """Charge for rows *before* building them.

        A kit line fans out one dictionary per unit, so this sheet is the one place
        an import amplifies: 51 rows at `quantity: 1000` is 51,000 rows out of under
        2 KB in. `MAX_ROWS` is checked by `plan_import` on what expansion returned,
        which is far too late to be a budget — by then the rows exist. Charging up
        front is what makes the refusal cheap.
        """
        nonlocal produced
        produced += count
        if produced > row_budget:
            raise InvalidInputError(
                f"this sheet expands to more than {row_budget:,} rows — the import "
                "limit. Split it into separate files, or use fewer per row."
            )

    for row in rows:
        source_row = row.get(_ROW_MARKER, "")
        retailer_name = (row.get("retailer") or "").strip()
        currency = (row.get("currency") or "").strip().upper() or (
            get_settings().reference_currency
        )
        quantity = (row.get("quantity") or "").strip() or "1"
        status = (row.get("status") or "").strip()

        if not retailer_name:
            # No purchase record — kits that just exist in the collection. One row
            # per unit, exactly as the retailer-bearing branch fans out through
            # `spawn_kits`. This branch used to emit a single kit and drop
            # `quantity` on the floor, so `quantity: 3` with no shop named silently
            # became one kit — and the ceiling could not reach a field nothing read.
            # A column cannot mean "how many of this kit" when a shop is named and
            # nothing at all when one isn't.
            try:
                count = _standalone_count(quantity)
            except InvalidInputError as exc:
                problems.append(f"row {source_row}: {exc}")
                continue
            spend(count)
            for _ in range(count):
                kits.append(
                    _present(
                        source_row,
                        name=row.get("kit_name", ""),
                        grade=row.get("grade", ""),
                        scale=row.get("scale", ""),
                        kit_number=row.get("kit_number", ""),
                        series=row.get("series", ""),
                        status=status or KitStatus.BACKLOG.value,
                        build_started_at=row.get("build_started", ""),
                        build_completed_at=row.get("build_completed", ""),
                        rating=row.get("rating", ""),
                        build_notes=row.get("build_notes", ""),
                    )
                )
            continue

        order_date = (row.get("order_date") or "").strip()
        order_number = (row.get("order_number") or "").strip()
        key = _order_key(retailer_name, order_date, order_number)

        # Every retailer-bearing row, not only the one that opens the group. A
        # five-kit haul is five rows and one order, so parsing `received` on the
        # first alone left a typo on rows 2-5 silently meaning "received", and an
        # explicit `no` down there ignored outright.
        try:
            stated = _received(row.get("received") or "")
        except InvalidInputError as exc:
            problems.append(f"row {source_row}: {exc}")
            continue

        if retailer_name.lower() not in retailers:
            spend(1)
            retailers[retailer_name.lower()] = _present(source_row, name=retailer_name)

        if key not in orders:
            spend(1)
            orders[key] = _present(
                source_row,
                id=str(uuid.uuid5(_NAMESPACE, key)),
                retailer_name=retailer_name,
                order_date=order_date,
                order_number=order_number,
                currency_code=currency,
            )
        if stated is not None:
            settled = receipts.get(key)
            if settled is not None and settled.stated != stated:
                problems.append(
                    f"row {source_row}: received is '{_YES_NO[stated]}', but row "
                    f"{settled.row} of the same order ({retailer_name}"
                    f"{', ' + order_number if order_number else ''}) says "
                    f"'{_YES_NO[settled.stated]}' — an order either arrived or it "
                    "didn't, so every row of one order has to agree"
                )
                continue
            receipts[key] = _Receipt(stated=stated, row=source_row)

        spend(1)
        order_items.append(
            _present(
                source_row,
                order_id=orders[key]["id"],
                item_type="kit",
                quantity=quantity,
                unit_price=row.get("unit_price", ""),
                currency_code=currency,
                kit_name=row.get("kit_name", ""),
                kit_grade=row.get("grade", ""),
                kit_scale=row.get("scale", ""),
                kit_number=row.get("kit_number", ""),
                kit_status=status,
            )
        )

    # Settled after the whole sheet has been read, because any row of a group may
    # be the one that states it — and set unconditionally, bypassing `_present`.
    # `_present` drops empty cells so a kit list can't blank a shop's report card,
    # but an explicit `no` is the sheet having an opinion, and it can only be
    # carried as a present-and-empty `received_at`: absent means "says nothing",
    # which left a re-import unable to un-receive an order it had marked received.
    for key, order_row in orders.items():
        settled = receipts.get(key)
        received = settled.stated if settled is not None else True
        # Received-on defaults to the order date rather than today, so a migrated
        # collection doesn't claim it all arrived on import day.
        order_row["received_at"] = order_row.get("order_date", "") if received else ""

    expanded: dict[str, list[dict[str, str]]] = {}
    if retailers:
        expanded["retailers"] = list(retailers.values())
    if orders:
        expanded["orders"] = list(orders.values())
    if order_items:
        expanded["order_items"] = order_items
    if kits:
        expanded["kits"] = kits
    return expanded, problems
