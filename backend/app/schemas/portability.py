import enum
import uuid

from pydantic import BaseModel, Field


class ImportMode(enum.StrEnum):
    #: Update what matches, add what doesn't.
    MERGE = "merge"
    #: Add what's new, leave everything that already exists alone. The safe re-run.
    ADD_ONLY = "add_only"
    #: Wipe the collection and restore the file over the top. Needs confirm="REPLACE".
    REPLACE_ALL = "replace_all"


class RowAction(enum.StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    SKIP = "skip"
    ERROR = "error"


class FieldChange(BaseModel):
    field: str
    before: str
    after: str


class PlannedRow(BaseModel):
    #: Line number in the source CSV, so an error points at what the human typed.
    row_number: int
    action: RowAction
    label: str
    #: Primary key of the stored row this one resolved to. Every collection table
    #: keys on a uuid; the int is the instance_settings singleton (#23), whose key
    #: is the constant 1.
    matched_id: uuid.UUID | int | None = None
    #: How it was matched — "id", "name", "retailer + order number", ...
    matched_by: str | None = None
    changes: list[FieldChange] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)
    error: str | None = None


class TablePlan(BaseModel):
    table: str
    counts: dict[str, int]
    rows: list[PlannedRow]


class DerivedEffects(BaseModel):
    """Side effects beyond the rows themselves — the §3.9 dispatch, spelled out."""

    kits_spawned: int = 0
    #: Kits a reduced order-line quantity gives up (#44). Destructive and derived,
    #: so it is stated in the preview next to `rows_deleted` rather than discovered
    #: afterwards — nothing in the row list mentions these kits.
    kits_removed: int = 0
    #: Pre-existing kits an order this upload marks shipped or received moves
    #: (in_transit / backlog). Derived, hash-bound as plan descriptors (#119),
    #: and named by no row — the per-order messages say which way each moves.
    kits_advanced: int = 0
    stock_changes: int = 0
    stock_note: str = ""
    rows_deleted: dict[str, int] = Field(default_factory=dict)


class ManifestInfo(BaseModel):
    format: str | None = None
    export_version: int | None = None
    schema_version: str | None = None
    app_version: str | None = None
    exported_at: str | None = None


class ImportPlan(BaseModel):
    """What an import would do. Returned by preview; re-derived and hash-checked on apply."""

    plan_hash: str
    mode: ImportMode
    source: str
    manifest: ManifestInfo | None = None
    tables: list[TablePlan] = Field(default_factory=list)
    derived: DerivedEffects = Field(default_factory=DerivedEffects)
    warnings: list[str] = Field(default_factory=list)
    #: Non-empty means apply will refuse.
    blocking_errors: list[str] = Field(default_factory=list)


class ImportResult(BaseModel):
    mode: ImportMode
    source: str
    created: int
    updated: int
    skipped: int
    kits_spawned: int
    kits_removed: int = 0
    kits_advanced: int = 0
    rows_deleted: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
