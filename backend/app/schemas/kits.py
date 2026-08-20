import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.models.enums import KitStatus
from app.schemas.numeric import Rating


class KitCreate(BaseModel):
    name: str = Field(min_length=1)
    grade: str = Field(min_length=1)
    scale: str | None = None  # derived from grade when omitted (§3.1)
    kit_number: str | None = None
    # Free text like grade/scale (#96) — no registry, so an agent can record a
    # series nobody has listed yet; the distinct-values endpoint is the de-dup aid.
    series: str | None = None
    status: KitStatus = KitStatus.BACKLOG
    # Backfill fields (#94): the dates belong to the user and are settable at
    # creation — a kit migrated from another tool arrives with its real dates.
    # Creation never derives them from `status`; only a live transition stamps a
    # default, so a kit *created* already-complete stays null unless told
    # (the same no-invention rule the importer follows).
    build_started_at: AwareDatetime | None = None
    build_completed_at: AwareDatetime | None = None
    build_notes: str | None = None


class KitUpdate(BaseModel):
    """PATCH payload — only fields actually sent are applied (exclude_unset)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    grade: str | None = Field(default=None, min_length=1)
    scale: str | None = None
    kit_number: str | None = None
    series: str | None = None
    status: KitStatus | None = None
    rating: Rating | None = None
    # Offset-aware ISO 8601; explicit null clears. A status transition in the same
    # PATCH never overwrites a value (or null) supplied here — the derivation
    # stamps only a field the request did not mention and that is null (#94).
    build_started_at: AwareDatetime | None = None
    build_completed_at: AwareDatetime | None = None
    build_notes: str | None = None


class KitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    grade: str
    scale: str | None
    kit_number: str | None
    series: str | None
    status: KitStatus
    status_updated_at: datetime
    rating: int | None
    build_started_at: datetime | None
    build_completed_at: datetime | None
    build_notes: str | None
    order_item_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
