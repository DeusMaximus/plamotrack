import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import KitStatus
from app.schemas.numeric import Rating


class KitCreate(BaseModel):
    name: str = Field(min_length=1)
    grade: str = Field(min_length=1)
    scale: str | None = None  # derived from grade when omitted (§3.1)
    kit_number: str | None = None
    status: KitStatus = KitStatus.BACKLOG
    build_notes: str | None = None


class KitUpdate(BaseModel):
    """PATCH payload — only fields actually sent are applied (exclude_unset)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    grade: str | None = Field(default=None, min_length=1)
    scale: str | None = None
    kit_number: str | None = None
    status: KitStatus | None = None
    rating: Rating | None = None
    build_notes: str | None = None


class KitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    grade: str
    scale: str | None
    kit_number: str | None
    status: KitStatus
    status_updated_at: datetime
    rating: int | None
    build_notes: str | None
    order_item_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
