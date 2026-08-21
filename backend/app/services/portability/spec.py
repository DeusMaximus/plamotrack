"""Declarative description of every portable table.

This registry is the single source of truth for the CSV shape: export, import,
and blank-template generation all read it, so the three can never drift apart.
Adding a column to a model means adding one `col(...)` line here and nothing else.

Column roles matter:

- ``ID``       the row's own primary key. Present in exports; optional on import
               (a hand-written sheet won't have one).
- ``REF``      a uuid foreign key. Rewritten through the import id-remap so an
               archive lands correctly in an instance that already holds the
               referenced row under a different uuid.
- ``ALT_REF``  a human-readable mirror of a REF ("Hobby Link Japan" next to the
               retailer uuid). Exported for legibility; on import it's the
               fallback when the uuid is missing or unknown.
- ``ALT_MONEY`` a major-unit mirror of an integer ``*_minor`` column (§6 keeps
               minor units canonical — this column exists so a human can type
               "49.99" instead of "4999").

ALT columns are never authoritative: the uuid / minor-unit column wins whenever
it is present and resolvable.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from operator import attrgetter
from typing import Any

from app.models import (
    Base,
    Consumable,
    DisplayItem,
    Kit,
    KitPhoto,
    Order,
    OrderItem,
    Retailer,
    Tool,
    Upgrade,
    UpgradeApplication,
)
from app.models.enums import (
    ItemType,
    KitStatus,
    PackingQuality,
    ShippingSpeed,
    WouldOrderAgain,
)
from app.services.numeric import require_int4, strip_numeric_grouping

# --- cell parsers --------------------------------------------------------------

_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0"}


def parse_text(raw: str) -> str | None:
    value = raw.strip()
    return value or None


def parse_int(raw: str) -> int | None:
    """A whole number, or a ValueError naming the cell.

    Was `int(Decimal(value))`, which truncated rather than refusing: `1.9` imported
    as `1` and `-0.5` as `0`, so a mistyped quantity became a different quantity
    instead of a question. Anything with a fractional part is now an error — the
    sheet has to say which whole number it means.

    `3.0` still reads as 3. Spreadsheets format integer columns that way constantly
    and it states one number, unambiguously.
    """
    value = strip_numeric_grouping(raw)
    if not value:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"'{raw}' is not a whole number") from exc
    # `inf` and `nan` parse fine and then raise OverflowError out of int() — which
    # `_parse_row` did not catch, so a three-character cell was a 500 rather than a
    # row error.
    if not number.is_finite():
        raise ValueError(f"'{raw}' is not a whole number")
    # Before `to_integral_value`, so an absurd exponent is refused by comparison
    # rather than expanded into a million-digit integer first.
    require_int4(number, f"'{raw}'")
    if number != number.to_integral_value():
        raise ValueError(f"'{raw}' is not a whole number — it has a fractional part")
    return int(number)


def parse_decimal(raw: str) -> Decimal | None:
    """A major-unit amount. Range is not checked here — the minor-unit integer it
    scales into is, once the currency is known (`_apply_money_alternates`)."""
    value = strip_numeric_grouping(raw)
    if not value:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"'{raw}' is not a number") from exc
    if not number.is_finite():
        raise ValueError(f"'{raw}' is not a number")
    return number


def parse_bool(raw: str) -> bool | None:
    value = raw.strip().lower()
    if not value:
        return None
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"'{raw}' is not a yes/no value")


def parse_uuid(raw: str) -> uuid.UUID | None:
    value = raw.strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(f"'{raw}' is not a valid id") from exc


def parse_date(raw: str) -> date | None:
    value = raw.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    try:  # last resort: a full ISO timestamp in a date column
        return datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise ValueError(f"'{raw}' is not a date (use YYYY-MM-DD)") from exc


def parse_datetime(raw: str) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed_date = parse_date(value)
        if parsed_date is None:
            raise ValueError(f"'{raw}' is not a timestamp") from None
        parsed = datetime.combine(parsed_date, datetime.min.time())
    # Naive input is read as UTC — every timestamp column in the schema is tz-aware.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_currency(raw: str) -> str | None:
    value = raw.strip().upper()
    if not value:
        return None
    if len(value) != 3 or not value.isalpha():
        raise ValueError(f"'{raw}' is not a 3-letter ISO 4217 currency code")
    return value


def enum_parser(enum_cls: type[StrEnum], *, aliases: dict[str, str] | None = None) -> Callable:
    """Case/spacing-tolerant enum parsing — "In Transit" and "in_transit" both work,
    matching the leniency the MCP layer already extends to agents."""
    lookup = {member.value.lower(): member for member in enum_cls}
    lookup |= {member.value.replace("_", " ").lower(): member for member in enum_cls}
    for alias, target in (aliases or {}).items():
        lookup[alias.lower()] = enum_cls(target)

    def _parse(raw: str) -> StrEnum | None:
        value = raw.strip().lower()
        if not value:
            return None
        found = (
            lookup.get(value)
            or lookup.get(value.replace(" ", "_"))
            or lookup.get(value.replace("-", "_"))
        )
        if found is None:
            allowed = ", ".join(member.value for member in enum_cls)
            raise ValueError(f"'{raw}' is not valid here (expected one of: {allowed})")
        return found

    return _parse


# --- rendering (python value -> csv cell) --------------------------------------


def render(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date | uuid.UUID | Decimal):
        return str(value)
    return str(value)


# --- specs ---------------------------------------------------------------------


class ColumnRole(StrEnum):
    DATA = "data"
    ID = "id"
    REF = "ref"
    ALT_REF = "alt_ref"
    ALT_MONEY = "alt_money"


@dataclass(frozen=True)
class ColumnSpec:
    name: str
    parse: Callable[[str], Any]
    get: Callable[[Any], Any]
    role: ColumnRole = ColumnRole.DATA
    required: bool = False
    #: REF/ALT_REF only — table key this points at. "catalog" resolves dynamically
    #: against the catalog tables using the row's item_type.
    ref_table: str | None = None
    #: ALT_* only — the canonical column this mirrors.
    mirrors: str | None = None
    #: ALT_MONEY only — the column holding the code this amount is denominated in.
    #: Orders and order lines carry a single `currency_code`; a table whose money
    #: names its currency differently says so here, or its major units get scaled by
    #: the two-decimal default and a JPY or KWD amount silently lands wrong.
    currency_column: str = "currency_code"
    #: Exists in the CSV but not on the model — order_items' kit_* columns mirror
    #: the kits a line spawned, which are rows of their own.
    virtual: bool = False
    #: Header names this column used to ship under. Accepted on import and mapped
    #: to `name`; never exported, so an archive only ever names the current column.
    #: This is what keeps re-importing an older export a no-op (§12.5).
    aliases: tuple[str, ...] = ()
    #: Sibling cells to fill when a row arrived under an alias and left them blank.
    #: A retired name can carry meaning the current one spreads across columns —
    #: converted_price_aud_minor stated its currency, converted_price_minor doesn't.
    alias_fills: tuple[tuple[str, str], ...] = ()
    help: str = ""

    @property
    def is_alternate(self) -> bool:
        return self.role in (ColumnRole.ALT_REF, ColumnRole.ALT_MONEY)

    @property
    def persisted(self) -> bool:
        """Backed by a real column on the model — safe to read from and write to it."""
        return not self.is_alternate and not self.virtual


def col(
    name: str,
    parse: Callable[[str], Any],
    *,
    get: Callable[[Any], Any] | None = None,
    role: ColumnRole = ColumnRole.DATA,
    required: bool = False,
    ref_table: str | None = None,
    mirrors: str | None = None,
    currency_column: str = "currency_code",
    virtual: bool = False,
    aliases: tuple[str, ...] = (),
    alias_fills: tuple[tuple[str, str], ...] = (),
    help: str = "",
) -> ColumnSpec:
    return ColumnSpec(
        name=name,
        parse=parse,
        get=get if get is not None else attrgetter(name),
        role=role,
        required=required,
        ref_table=ref_table,
        mirrors=mirrors,
        currency_column=currency_column,
        virtual=virtual,
        aliases=aliases,
        alias_fills=alias_fills,
        help=help,
    )


def id_col() -> ColumnSpec:
    return col(
        "id",
        parse_uuid,
        role=ColumnRole.ID,
        help="Leave blank on hand-written rows — one is generated.",
    )


@dataclass(frozen=True)
class TableSpec:
    key: str
    model: type[Base]
    columns: tuple[ColumnSpec, ...]
    label: Callable[[dict], str]
    #: Fallback identity for rows with no id. None = id-only matching, i.e. never
    #: auto-matched (kits: a second RX-78 is a second physical kit, not a duplicate).
    natural_key: Callable[[dict], tuple | None] | None = None
    depends_on: tuple[str, ...] = ()
    #: (amount, currency) column pairs whose currency half is *optional* in the sheet
    #: and defaults to the instance reference currency. Listed here so the importer's
    #: pair handling is declared with the shape rather than hardcoded per table (rule
    #: 9). A pair whose currency column is `required` does not belong here — there is
    #: no blank to fill, e.g. order_items' unit_price_minor / currency_code.
    money_pairs: tuple[tuple[str, str], ...] = ()
    #: Handled by dedicated importer logic rather than the generic row path.
    special: bool = False
    description: str = ""
    _by_name: dict[str, ColumnSpec] = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        self._by_name.update({column.name: column for column in self.columns})
        # Retired header names resolve to their current column, so an archive
        # exported by an older version is understood rather than warned about.
        for column in self.columns:
            for alias in column.aliases:
                self._by_name.setdefault(alias, column)

    @property
    def filename(self) -> str:
        return f"{self.key}.csv"

    @property
    def header(self) -> list[str]:
        return [column.name for column in self.columns]

    def column(self, name: str) -> ColumnSpec | None:
        """Resolves current names and retired aliases alike."""
        return self._by_name.get(name)

    def money_mirror(self, amount_column: str) -> str | None:
        """The major-unit column that can fill `amount_column`, if the table has one.

        Needed because a sheet may supply only the major-unit twin, and the currency
        has to be settled before that twin is scaled — the exponent comes from the
        code, so a code resolved afterwards reads 1200 JPY as 120000.
        """
        for column in self.columns:
            if column.role is ColumnRole.ALT_MONEY and column.mirrors == amount_column:
                return column.name
        return None

    def canonicalise(self, raw: dict[str, str]) -> dict[str, str]:
        """Rewrite retired header names to their current ones, plus whatever the
        retired name implied (`alias_fills`).

        A file carrying both names is not a conflict worth erroring over — the
        current column wins and the alias is dropped, which is the same rule the
        ALT_* columns already follow.
        """
        matched = [
            (key, column)
            for key in raw
            if (column := self._by_name.get(key)) is not None and column.name != key
        ]
        if not matched:
            return raw

        superseded = {key for key, column in matched if column.name in raw}
        renamed = {key: column.name for key, column in matched if key not in superseded}
        out = {renamed.get(key, key): value for key, value in raw.items() if key not in superseded}
        for key, column in matched:
            if key in superseded:
                continue
            for sibling, value in column.alias_fills:
                if not out.get(sibling, "").strip():
                    out[sibling] = value
        return out

    def to_row(self, instance: Any) -> dict[str, str]:
        """Model instance -> csv cells. ALT columns are filled by the exporter."""
        return {column.name: render(column.get(instance)) for column in self.columns}


# --- natural keys --------------------------------------------------------------


def _name_key(row: dict) -> tuple | None:
    """Case-insensitive name — the same de-dup rule `get_or_create_retailer` and the
    §3.9 select-or-create catalog flow already use."""
    name = (row.get("name") or "").strip().lower()
    return ("name", name) if name else None


def _application_key(row: dict) -> tuple | None:
    upgrade_id, kit_id = row.get("upgrade_id"), row.get("kit_id")
    if not upgrade_id or not kit_id:
        return None
    applied = row.get("applied_at")
    return ("application", str(upgrade_id), str(kit_id), applied.isoformat() if applied else "")


def _photo_key(row: dict) -> tuple | None:
    kit_id, path = row.get("kit_id"), (row.get("file_path") or "").strip()
    return ("photo", str(kit_id), path) if kit_id and path else None


# --- the registry --------------------------------------------------------------

_MONEY_HELP = (
    "Integer minor units — cents for AUD, whole yen for JPY, fils for KWD. "
    "Wins over the major-unit column when both are set."
)

# The vocabulary agents and old exports still use for what is now `backlog` — the
# same aliases app/mcp.py extends, so a status spelled "In Hand" imports cleanly.
_KIT_STATUS_PARSER = enum_parser(
    KitStatus, aliases={"in hand": "backlog", "in_hand": "backlog", "arrived": "backlog"}
)

RETAILERS = TableSpec(
    key="retailers",
    model=Retailer,
    description="Shops you order from, plus the experience report card (§3.7).",
    columns=(
        id_col(),
        col("name", parse_text, required=True),
        col("url", parse_text),
        col("rating", parse_int, help="Overall, 1-5."),
        col("packing_quality", enum_parser(PackingQuality)),
        col("shipping_speed", enum_parser(ShippingSpeed)),
        col("would_order_again", enum_parser(WouldOrderAgain)),
        col("notes", parse_text),
    ),
    label=lambda row: row.get("name") or "(unnamed retailer)",
    natural_key=_name_key,
)

TOOLS = TableSpec(
    key="tools",
    model=Tool,
    description="Durable, quantity-tracked gear (§3.3).",
    columns=(
        id_col(),
        col("name", parse_text, required=True),
        col("category", parse_text, required=True, help="cutting / filing / gluing / ..."),
        col("quantity_on_hand", parse_int, help="Physically on hand. Not derived from orders."),
        col("unit_cost_reference_minor", parse_int, help=_MONEY_HELP),
        col(
            # Pre-0.2.3 exports named this column and held major units in it, with no
            # currency anywhere on the table — which is the ambiguity #19 removed. It
            # keeps working as the major-unit mirror, and a row arriving without a code
            # is stamped with the instance default like any other blank currency cell.
            "unit_cost_reference",
            parse_decimal,
            get=lambda t: None,
            role=ColumnRole.ALT_MONEY,
            mirrors="unit_cost_reference_minor",
            currency_column="unit_cost_reference_currency",
            help="Major units, e.g. 12.50.",
        ),
        col(
            "unit_cost_reference_currency",
            parse_currency,
            help="Currency the price was recorded in. Blank = the instance default.",
        ),
        col("condition_notes", parse_text),
    ),
    label=lambda row: row.get("name") or "(unnamed tool)",
    natural_key=_name_key,
    money_pairs=(("unit_cost_reference_minor", "unit_cost_reference_currency"),),
)

CONSUMABLES = TableSpec(
    key="consumables",
    model=Consumable,
    description="Depletable supplies (§3.4).",
    columns=(
        id_col(),
        col("name", parse_text, required=True),
        col("category", parse_text, required=True, help="paint / cement / blades / ..."),
        col("quantity_on_hand", parse_int, help="Physically on hand. Not derived from orders."),
        col("low_stock_threshold", parse_int),
    ),
    label=lambda row: row.get("name") or "(unnamed consumable)",
    natural_key=_name_key,
)

UPGRADES = TableSpec(
    key="upgrades",
    model=Upgrade,
    description="Third-party parts and decals (§3.5).",
    columns=(
        id_col(),
        col("name", parse_text, required=True),
        col("manufacturer", parse_text, required=True),
        col("quantity_on_hand", parse_int, help="Physically on hand. Not derived from orders."),
    ),
    label=lambda row: row.get("name") or "(unnamed upgrade)",
    natural_key=_name_key,
)

DISPLAY_ITEMS = TableSpec(
    key="display_items",
    model=DisplayItem,
    description="Stands, bases and diorama scenery — display gear (§3.5a).",
    columns=(
        id_col(),
        col("name", parse_text, required=True),
        col(
            "category",
            parse_text,
            required=True,
            help="stand / base / scenery / structure / figures / backdrop / ...",
        ),
        col(
            "scale",
            parse_text,
            help="Kit scale the piece suits, e.g. 1/144. Blank = non-scale or not recorded.",
        ),
        col("manufacturer", parse_text, help="Optional — a scratch-built piece has none."),
        col("quantity_on_hand", parse_int, help="Physically on hand. Not derived from orders."),
        col("notes", parse_text),
    ),
    label=lambda row: row.get("name") or "(unnamed display item)",
    natural_key=_name_key,
)

ORDERS = TableSpec(
    key="orders",
    model=Order,
    description="Purchases (§3.8). Matched on retailer + order_number, else on date + lines.",
    depends_on=("retailers",),
    special=True,
    columns=(
        id_col(),
        col("retailer_id", parse_uuid, role=ColumnRole.REF, ref_table="retailers"),
        col(
            "retailer_name",
            parse_text,
            get=lambda o: None,  # filled by the exporter, which has the retailer loaded
            role=ColumnRole.ALT_REF,
            ref_table="retailers",
            mirrors="retailer_id",
            help="Used when retailer_id is blank or unknown; created if no such shop exists.",
        ),
        col("order_date", parse_date, required=True),
        col("order_number", parse_text, help="The retailer's own reference. Not unique."),
        col("delivery_service", parse_text, help="Blank = local pickup/purchase."),
        col("tracking_number", parse_text),
        col("tracking_url", parse_text),
        col("shipping_cost_minor", parse_int, help=_MONEY_HELP),
        col(
            "shipping_cost",
            parse_decimal,
            get=lambda o: None,
            role=ColumnRole.ALT_MONEY,
            mirrors="shipping_cost_minor",
            help="Major units, e.g. 12.50.",
        ),
        col("currency_code", parse_currency, required=True),
        col(
            "shipped_at",
            parse_datetime,
            help="Blank = not marked shipped. Set = left the retailer; never moves stock (#95).",
        ),
        col(
            "received_at",
            parse_datetime,
            help="Blank = still pending. Set = arrived; stock is stated, never re-derived.",
        ),
    ),
    label=lambda row: (
        f"order {row.get('order_number') or '(no number)'} — {render(row.get('order_date'))}"
    ),
)

ORDER_ITEMS = TableSpec(
    key="order_items",
    model=OrderItem,
    description=(
        "Order lines (§3.9). kit_* columns only matter when no kits row covers the line — "
        "then they drive the fan-out."
    ),
    depends_on=("orders", "tools", "consumables", "upgrades", "display_items"),
    special=True,
    columns=(
        id_col(),
        col("order_id", parse_uuid, role=ColumnRole.REF, ref_table="orders", required=True),
        col(
            "item_type",
            enum_parser(ItemType),
            required=True,
            help="kit / tool / consumable / upgrade / display",
        ),
        col(
            "catalog_ref_id",
            parse_uuid,
            role=ColumnRole.REF,
            ref_table="catalog",
            help="Blank for kit lines — kits are spawned fresh, not referenced.",
        ),
        col(
            "catalog_name",
            parse_text,
            get=lambda i: None,
            role=ColumnRole.ALT_REF,
            ref_table="catalog",
            mirrors="catalog_ref_id",
            help="Used when catalog_ref_id is blank or unknown; created at quantity 0 if new.",
        ),
        col("quantity", parse_int, required=True, help="Kit lines fan out into this many kits."),
        col("unit_price_minor", parse_int, help=_MONEY_HELP),
        col(
            "unit_price",
            parse_decimal,
            get=lambda i: None,
            role=ColumnRole.ALT_MONEY,
            mirrors="unit_price_minor",
            help="Major units, e.g. 49.99.",
        ),
        col("currency_code", parse_currency, required=True),
        col(
            "converted_price_minor",
            parse_int,
            # Pre-0.2 exports named this converted_price_aud_minor and had no
            # companion currency column. The retired name asserted AUD, so rows
            # arriving under it are stamped AUD rather than silently reinterpreted
            # as whatever this instance happens to use as its reference currency.
            aliases=("converted_price_aud_minor",),
            alias_fills=(("converted_currency_code", "AUD"),),
            help="Entry-time snapshot in the reference currency — never recomputed.",
        ),
        col(
            "converted_currency_code",
            parse_currency,
            help="Currency the snapshot was taken in. Blank = the instance default.",
        ),
        # Kit details live on the spawned kits, not the line. Exported from them for
        # legibility; on import they only matter when nothing else supplies the kits.
        col("kit_name", parse_text, get=lambda i: None, virtual=True),
        col(
            "kit_grade",
            parse_text,
            get=lambda i: None,
            virtual=True,
            help="HG / RG / MG / PG / SD / ...",
        ),
        col(
            "kit_scale",
            parse_text,
            get=lambda i: None,
            virtual=True,
            help="Blank = derived from the grade.",
        ),
        col("kit_number", parse_text, get=lambda i: None, virtual=True),
        col("kit_status", _KIT_STATUS_PARSER, get=lambda i: None, virtual=True),
    ),
    label=lambda row: (
        f"{render(row.get('item_type'))} × {render(row.get('quantity'))}"
        + (f" — {row['catalog_name']}" if row.get("catalog_name") else "")
        + (f" — {row['kit_name']}" if row.get("kit_name") else "")
    ),
    money_pairs=(("converted_price_minor", "converted_currency_code"),),
)

KITS = TableSpec(
    key="kits",
    model=Kit,
    description=(
        "One row per physical kit (§3.1). Never auto-matched by name: two of the same "
        "kit are two kits, so only a matching id updates an existing row."
    ),
    depends_on=("order_items",),
    natural_key=None,
    columns=(
        id_col(),
        col("name", parse_text, required=True),
        col("grade", parse_text, required=True, help="HG / RG / MG / PG / SD / ..."),
        col("scale", parse_text, help="Blank = derived from the grade."),
        col("kit_number", parse_text),
        col("series", parse_text, help="e.g. Iron-Blooded Orphans. Free text (#96)."),
        col(
            "status",
            _KIT_STATUS_PARSER,
            help="pre_ordered / ordered / in_transit / backlog / building / complete",
        ),
        col("status_updated_at", parse_datetime),
        col(
            "build_started_at",
            parse_datetime,
            help="When the build began (#94). Blank = not recorded — never invented.",
        ),
        col(
            "build_completed_at",
            parse_datetime,
            help="When it was declared finished. Blank = not recorded — never invented.",
        ),
        col("rating", parse_int, help="1-5, set on completion."),
        col("build_notes", parse_text),
        col(
            "order_item_id",
            parse_uuid,
            role=ColumnRole.REF,
            ref_table="order_items",
            help="Which order line bought this kit. Blank = added directly.",
        ),
        col("created_at", parse_datetime),
        col("updated_at", parse_datetime),
    ),
    label=lambda row: (
        f"{row.get('name') or '(unnamed kit)'}" + (f" ({row['grade']})" if row.get("grade") else "")
    ),
)

UPGRADE_APPLICATIONS = TableSpec(
    key="upgrade_applications",
    model=UpgradeApplication,
    description="Which upgrades went onto which kits (§3.6).",
    depends_on=("upgrades", "kits"),
    columns=(
        id_col(),
        col("upgrade_id", parse_uuid, role=ColumnRole.REF, ref_table="upgrades", required=True),
        col(
            "upgrade_name",
            parse_text,
            get=lambda a: None,
            role=ColumnRole.ALT_REF,
            ref_table="upgrades",
            mirrors="upgrade_id",
        ),
        col("kit_id", parse_uuid, role=ColumnRole.REF, ref_table="kits", required=True),
        col("quantity_used", parse_int, required=True),
        col("applied_at", parse_datetime),
    ),
    label=lambda row: f"upgrade application × {render(row.get('quantity_used'))}",
    natural_key=_application_key,
)

KIT_PHOTOS = TableSpec(
    key="kit_photos",
    model=KitPhoto,
    description="Gallery entries (§3.2). Empty until photo upload lands (Milestone 7).",
    depends_on=("kits",),
    columns=(
        id_col(),
        col("kit_id", parse_uuid, role=ColumnRole.REF, ref_table="kits", required=True),
        col("file_path", parse_text, required=True),
        col("caption", parse_text),
        col("taken_at", parse_datetime),
        col("created_at", parse_datetime),
    ),
    label=lambda row: row.get("file_path") or "(photo)",
    natural_key=_photo_key,
)

#: Declaration order IS import order — it follows the FK graph (kits after
#: order_items for the provenance FK, applications and photos last).
TABLE_SPECS: tuple[TableSpec, ...] = (
    RETAILERS,
    TOOLS,
    CONSUMABLES,
    UPGRADES,
    DISPLAY_ITEMS,
    ORDERS,
    ORDER_ITEMS,
    KITS,
    UPGRADE_APPLICATIONS,
    KIT_PHOTOS,
)

SPEC_BY_KEY: dict[str, TableSpec] = {spec.key: spec for spec in TABLE_SPECS}

#: Catalog tables an order line can point at, by item_type value.
CATALOG_TABLE_BY_ITEM_TYPE: dict[str, str] = {
    ItemType.TOOL.value: "tools",
    ItemType.CONSUMABLE.value: "consumables",
    ItemType.UPGRADE.value: "upgrades",
    ItemType.DISPLAY.value: "display_items",
}
