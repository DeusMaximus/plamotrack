import enum
import uuid
from typing import Any

from pydantic import BaseModel, Field


class Diagnostic(BaseModel):
    """One import-preview finding, on the #25 contract (#26).

    The same three members as the REST error envelope, because it is the same
    idea landing inside a successful payload: `code` a stable
    `<domain>.<condition>` from `app/error_codes.py`, `params` the structured
    values a translation may interpolate (snake_case, JSON-serialisable),
    `detail` the useful English fallback an API client or an unknown-code
    browser reads. The browser renders known codes through the catalogue
    (`api.<code>`), exactly as `resolveApiError` does for a failed response.

    Wording lives only in `detail`, which the plan fingerprint never covers —
    translating or rewording a diagnostic can't invalidate an outstanding
    preview (§6.1).
    """

    # All three required, matching the envelope (#169 review, P3): every
    # construction site supplies all three — the params audit depends on the
    # literal dict being there — so a generated client may rely on them too.
    code: str
    params: dict[str, Any]
    detail: str


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
    messages: list[Diagnostic] = Field(default_factory=list)
    #: Each problem stands alone (#26) — a row that fails to parse in three cells
    #: carries three diagnostics, not one semicolon-joined sentence. Empty means
    #: the row is clean; non-empty implies `action == ERROR`.
    errors: list[Diagnostic] = Field(default_factory=list)


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
    #: The rule-10 note ("stock comes from the catalog files"), as a diagnostic
    #: so the browser can translate it. None only in the model default; `_finish`
    #: always supplies it.
    stock_note: Diagnostic | None = None
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
    warnings: list[Diagnostic] = Field(default_factory=list)
    #: Non-empty means apply will refuse.
    blocking_errors: list[Diagnostic] = Field(default_factory=list)


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
    warnings: list[Diagnostic] = Field(default_factory=list)
