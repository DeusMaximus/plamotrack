import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ItemType
from app.schemas.numeric import NonNegativeInt4, PositiveInt4
from app.services.currency import CURRENCY_CODE_PATTERN

_COST_HELP = "Integer minor units — cents for AUD, whole yen for JPY, fils for KWD."


class ToolCreate(BaseModel):
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    quantity_on_hand: NonNegativeInt4 = 0
    unit_cost_reference_minor: NonNegativeInt4 | None = Field(default=None, description=_COST_HELP)
    unit_cost_reference_currency: str | None = Field(default=None, pattern=CURRENCY_CODE_PATTERN)
    condition_notes: str | None = None

    @model_validator(mode="after")
    def _validate_cost_pair(self) -> "ToolCreate":
        # Mirrors the ck_tools_unit_cost_reference_currency_paired constraint, so the
        # caller gets a 422 naming the field instead of an integrity error naming a
        # constraint. An amount without a code is the ambiguity this column pair exists
        # to remove; a code without an amount states a currency for nothing.
        if (self.unit_cost_reference_minor is None) != (self.unit_cost_reference_currency is None):
            raise ValueError(
                "unit_cost_reference_minor and unit_cost_reference_currency must be set "
                "together or left out together"
            )
        return self


class ToolUpdate(BaseModel):
    # No pair validator here: a PATCH may legitimately send one half and leave the
    # other on the row. The resulting pair is checked in services/catalog.py, which
    # is the only place that can see both the payload and the stored row.
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1)
    quantity_on_hand: NonNegativeInt4 | None = None
    unit_cost_reference_minor: NonNegativeInt4 | None = Field(default=None, description=_COST_HELP)
    unit_cost_reference_currency: str | None = Field(default=None, pattern=CURRENCY_CODE_PATTERN)
    condition_notes: str | None = None


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    quantity_on_hand: int
    unit_cost_reference_minor: int | None
    unit_cost_reference_currency: str | None
    condition_notes: str | None


class ConsumableCreate(BaseModel):
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    quantity_on_hand: NonNegativeInt4 = 0
    low_stock_threshold: NonNegativeInt4 | None = None


class ConsumableUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1)
    quantity_on_hand: NonNegativeInt4 | None = None
    low_stock_threshold: NonNegativeInt4 | None = None


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
    quantity_on_hand: NonNegativeInt4 = 0


class UpgradeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    manufacturer: str | None = Field(default=None, min_length=1)
    quantity_on_hand: NonNegativeInt4 | None = None


class UpgradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    manufacturer: str
    quantity_on_hand: int


class UpgradeApplyRequest(BaseModel):
    kit_id: uuid.UUID
    quantity: PositiveInt4


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
