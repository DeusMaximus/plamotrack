import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ItemType


class ToolCreate(BaseModel):
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    quantity_on_hand: int = Field(default=0, ge=0)
    unit_cost_reference: Decimal | None = None
    condition_notes: str | None = None


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    quantity_on_hand: int
    unit_cost_reference: Decimal | None
    condition_notes: str | None


class ConsumableCreate(BaseModel):
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    quantity_on_hand: int = Field(default=0, ge=0)
    low_stock_threshold: int | None = Field(default=None, ge=0)


class ConsumableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    quantity_on_hand: int
    low_stock_threshold: int | None


class UpgradeCreate(BaseModel):
    name: str = Field(min_length=1)
    manufacturer: str = Field(min_length=1)
    quantity_on_hand: int = Field(default=0, ge=0)


class UpgradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    manufacturer: str
    quantity_on_hand: int


class UpgradeApplyRequest(BaseModel):
    kit_id: uuid.UUID
    quantity: int = Field(gt=0)


class UpgradeApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    upgrade_id: uuid.UUID
    kit_id: uuid.UUID
    quantity_used: int
    applied_at: datetime


class CatalogSearchResult(BaseModel):
    """Type-tagged row from the cross-table typeahead search (§4)."""

    item_type: ItemType
    id: uuid.UUID
    name: str
    category: str | None = None  # tools/consumables
    manufacturer: str | None = None  # upgrades
    quantity_on_hand: int


class StockAdjustmentResult(BaseModel):
    item_type: ItemType
    id: uuid.UUID
    name: str
    quantity_on_hand: int
    reason: str | None = None
