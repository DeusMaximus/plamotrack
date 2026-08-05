import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ItemType, KitStatus

_CURRENCY_PATTERN = r"^[A-Z]{3}$"


class RetailerCreate(BaseModel):
    name: str = Field(min_length=1)
    url: str | None = None
    notes: str | None = None


class RetailerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str | None
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
    low_stock_threshold: int | None = Field(default=None, ge=0)
    unit_cost_reference: Decimal | None = None
    condition_notes: str | None = None


class OrderItemCreate(BaseModel):
    item_type: ItemType
    quantity: int = Field(gt=0)
    unit_price_minor: int = Field(ge=0)
    currency_code: str = Field(pattern=_CURRENCY_PATTERN)
    converted_price_aud_minor: int | None = Field(default=None, ge=0)
    kit: OrderKitDetails | None = None
    catalog_ref_id: uuid.UUID | None = None
    new_item: NewCatalogItem | None = None

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
    delivery_service: str | None = None  # null = local pickup/purchase
    tracking_number: str | None = None
    tracking_url: str | None = None
    shipping_cost_minor: int | None = Field(default=None, ge=0)
    currency_code: str = Field(pattern=_CURRENCY_PATTERN)
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    item_type: ItemType
    catalog_ref_id: uuid.UUID | None
    quantity: int
    unit_price_minor: int
    currency_code: str
    converted_price_aud_minor: int | None
    spawned_kit_ids: list[uuid.UUID] = []


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    retailer_id: uuid.UUID
    order_date: date
    delivery_service: str | None
    tracking_number: str | None
    tracking_url: str | None
    shipping_cost_minor: int | None
    currency_code: str
    items: list[OrderItemRead]
