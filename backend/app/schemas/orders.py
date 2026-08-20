import uuid
from datetime import date, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    ItemType,
    KitStatus,
    PackingQuality,
    ShippingSpeed,
    WouldOrderAgain,
)
from app.schemas.kits import KitRead
from app.schemas.numeric import NonNegativeInt4, PositiveInt4, Rating
from app.services.currency import CURRENCY_CODE_PATTERN as _CURRENCY_PATTERN


class RetailerCreate(BaseModel):
    name: str = Field(min_length=1)
    url: str | None = None
    rating: Rating | None = None
    packing_quality: PackingQuality | None = None
    shipping_speed: ShippingSpeed | None = None
    would_order_again: WouldOrderAgain | None = None
    notes: str | None = None


class RetailerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    url: str | None = None
    rating: Rating | None = None
    packing_quality: PackingQuality | None = None
    shipping_speed: ShippingSpeed | None = None
    would_order_again: WouldOrderAgain | None = None
    notes: str | None = None


class RetailerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str | None
    rating: int | None
    packing_quality: PackingQuality | None
    shipping_speed: ShippingSpeed | None
    would_order_again: WouldOrderAgain | None
    notes: str | None


class OrderKitDetails(BaseModel):
    """Details for the kit rows a kit-type order line spawns."""

    name: str = Field(min_length=1)
    grade: str = Field(min_length=1)
    scale: str | None = None
    kit_number: str | None = None
    status: KitStatus = KitStatus.ORDERED  # use pre_ordered for pre-orders


class NewCatalogItem(BaseModel):
    """Inline creation for the select-or-create flow (§3.9). Which fields are
    required depends on the line's item_type; validated in the service."""

    name: str = Field(min_length=1)
    category: str | None = None  # tools/consumables
    manufacturer: str | None = None  # upgrades
    low_stock_threshold: NonNegativeInt4 | None = None
    # Tools only. Minor units, with no currency field of its own — the line already
    # states the currency this was bought in, and asking twice invites the two to
    # disagree. The service stamps the line's code onto the row it creates.
    unit_cost_reference_minor: NonNegativeInt4 | None = None
    condition_notes: str | None = None


class OrderItemCreate(BaseModel):
    item_type: ItemType
    quantity: PositiveInt4
    unit_price_minor: NonNegativeInt4
    currency_code: str = Field(pattern=_CURRENCY_PATTERN)
    # Entry-time conversion snapshot (§6). Omit the code and the instance's
    # reference currency is stamped in; it is never re-read afterwards.
    converted_price_minor: NonNegativeInt4 | None = Field(
        default=None,
        description=(
            "Entry-time conversion snapshot: what this line cost in the currency "
            "below, recorded once and never recomputed. On an update, omitting this "
            "field keeps the stored snapshot — clearing it takes an explicit null."
        ),
    )
    converted_currency_code: str | None = Field(
        default=None,
        pattern=_CURRENCY_PATTERN,
        description=(
            "The currency the snapshot above was taken in. Omit it and the "
            "instance's reference currency is stamped in at write time, so moving "
            "that setting later never restates what past purchases cost. On an "
            "update it falls back to the code already recorded on the line before "
            "the instance default, so correcting only the amount cannot relabel "
            "the currency. Sent without an amount it is an error."
        ),
    )
    kit: OrderKitDetails | None = None
    catalog_ref_id: uuid.UUID | None = None
    new_item: NewCatalogItem | None = None

    @model_validator(mode="after")
    def _validate_converted_snapshot(self) -> "OrderItemCreate":
        if self.converted_currency_code is not None and self.converted_price_minor is None:
            raise ValueError(
                "converted_currency_code without converted_price_minor: a currency "
                "with no amount doesn't record anything — send the amount too, which "
                "is also how an update changes an existing snapshot's currency"
            )
        return self

    @model_validator(mode="after")
    def _validate_dispatch_payload(self) -> "OrderItemCreate":
        if self.item_type is ItemType.KIT:
            if self.kit is None:
                raise ValueError("kit lines require 'kit' details (name, grade, ...)")
            if self.catalog_ref_id is not None or self.new_item is not None:
                raise ValueError("kit lines must not set catalog_ref_id or new_item")
        else:
            if self.kit is not None:
                raise ValueError(f"{self.item_type} lines must not set 'kit' details")
            if (self.catalog_ref_id is None) == (self.new_item is None):
                raise ValueError(
                    f"{self.item_type} lines require exactly one of catalog_ref_id "
                    "(existing item) or new_item (create new)"
                )
        return self


class OrderCreate(BaseModel):
    retailer_id: uuid.UUID
    order_date: date
    order_number: str | None = None  # retailer's reference — informational only
    delivery_service: str | None = None  # null = local pickup/purchase
    tracking_number: str | None = None
    tracking_url: str | None = None
    shipping_cost_minor: NonNegativeInt4 | None = None
    currency_code: str = Field(pattern=_CURRENCY_PATTERN)
    # True = already in hand (store purchase / arrived before entry): stock is
    # applied and spawned kits start at backlog instead of ordered.
    received: bool = False
    # When the delivery actually arrived, for orders entered after the fact (#93).
    # Offset-aware ISO 8601 — the caller supplies its own offset until the
    # instance grows a time zone (M5.1). Omitted = now. Supplying it asserts the
    # order was received, so it requires `received=true` — a date on a pending
    # order is a contradiction, refused rather than silently ignored.
    received_at: AwareDatetime | None = None
    # When the retailer shipped it, for orders entered after the fact (#95).
    # Unlike received_at it needs no flag: a non-null instant *is* the assertion,
    # there being no separate "shipped" boolean anywhere. On its own it lands
    # spawned kits in_transit; alongside received=true it is a timeline record
    # only (the kits are already past that stage).
    shipped_at: AwareDatetime | None = None
    items: list[OrderItemCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def _received_at_implies_received(self) -> "OrderCreate":
        if self.received_at is not None and not self.received:
            raise ValueError(
                "received_at asserts the order arrived — pass received=true with it, "
                "or omit the date"
            )
        return self


class OrderItemUpsert(OrderItemCreate):
    """A line in an order edit: with id = update that line, without = new line.
    Existing lines omitted from the edit payload are removed (dispatch undone).

    A supplied line replaces the stored one field for field, with one deliberate
    exception: the `converted_*` snapshot pair. Omit those and the stored snapshot
    survives the edit; send an explicit null to clear it (issue #3). They are a
    recorded fact rather than a restatable value — an editor that never had the
    entry-time rate shouldn't destroy one by changing a quantity."""

    id: uuid.UUID | None = None


class OrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retailer_id: uuid.UUID | None = None
    order_date: date | None = None
    order_number: str | None = None
    delivery_service: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None
    shipping_cost_minor: NonNegativeInt4 | None = None
    currency_code: str | None = Field(default=None, pattern=_CURRENCY_PATTERN)
    # Correction only (#93): adjusts a receipt date that is already set. On an
    # order not yet received it 409s — the pending → received transition stays in
    # receive_order, where the stock dispatch lives, and never here. Explicit null
    # is refused: un-receiving an order is not a supported operation.
    received_at: AwareDatetime | None = None
    # Correction only, the same shape (#95): adjusts a ship date that is already
    # set; 409 on a never-shipped order (the transition stays in
    # mark_order_shipped); explicit null refused — un-shipping is not supported.
    shipped_at: AwareDatetime | None = None
    # None = leave line items untouched; a list is the full replacement set.
    items: list[OrderItemUpsert] | None = Field(default=None, min_length=1)


class OrderReceive(BaseModel):
    """Optional body for POST /orders/{id}/receive (#93). No body, an empty
    object and an explicit null all mean the same thing: the order arrived now."""

    model_config = ConfigDict(extra="forbid")

    received_at: AwareDatetime | None = None


class OrderShip(BaseModel):
    """Optional body for POST /orders/{id}/ship (#95), OrderReceive's mirror:
    no body, an empty object and an explicit null all mean "it shipped now"."""

    model_config = ConfigDict(extra="forbid")

    shipped_at: AwareDatetime | None = None


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_type: ItemType
    catalog_ref_id: uuid.UUID | None
    quantity: int
    unit_price_minor: int
    currency_code: str
    converted_price_minor: int | None
    converted_currency_code: str | None
    spawned_kit_ids: list[uuid.UUID] = []
    # The spawned kits themselves, not just their ids (#65). The rows are already
    # eager-loaded for `spawned_kit_ids`, so this costs nothing — and it means an
    # editor can read a line's kit details from the order it is editing instead of
    # joining the ids against a separately cached kit list. That second cache going
    # stale is how a warm page reverted a kit somebody had just changed.
    kits: list[KitRead] = []


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    retailer_id: uuid.UUID
    order_date: date
    order_number: str | None
    delivery_service: str | None
    tracking_number: str | None
    tracking_url: str | None
    shipping_cost_minor: int | None
    currency_code: str
    shipped_at: datetime | None
    received_at: datetime | None
    items: list[OrderItemRead]
