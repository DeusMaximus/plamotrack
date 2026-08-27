"""Import: parse, plan, then apply.

Planning and applying are deliberately separate. Planning is a pure read — it
resolves every incoming row against what's already in the database, classifies it
(create / update / unchanged / skip / error), and works out the derived side
effects, without writing anything. That plan *is* the preview payload.

Applying re-parses and re-plans, compares the resulting `plan_hash` against the
one the user was shown, and refuses with a 409 if they differ. The hash is
required — an apply without one is a 422, because it is an apply nobody reviewed.
Nothing is stored between the two calls: the plan can't go stale in a cache,
survives a container restart, and the recheck closes the window between looking
and committing. What the hash does and does not cover is `_plan_fingerprint`.

Two rules do most of the work of not duplicating things:

  * ids are preserved. A row imported into an empty instance keeps its uuid, so
    an archive's internal references need no rewriting at all.
  * when a row *matches* an existing record under a different uuid, that mapping
    is recorded in the id-remap and every later reference is rewritten through
    it. That's what lets an archive land in an instance that already has "Hobby
    Link Japan" without ending up with two of them.
"""

import csv
import hashlib
import io
import json
import uuid
import zipfile
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import ConflictError, DomainError, InvalidInputError
from app.models import ItemType, Kit, Order, OrderItem
from app.models.enums import KitStatus
from app.schemas.portability import (
    DerivedEffects,
    FieldChange,
    ImportMode,
    ImportPlan,
    ImportResult,
    ManifestInfo,
    PlannedRow,
    RowAction,
    TablePlan,
)
from app.services import instance_settings
from app.services.currency import is_known_currency, major_to_minor, minor_fraction_digits
from app.services.kits import default_scale_for_grade
from app.services.numeric import is_lone_group, require_int4
from app.services.orders import (
    ARRIVAL_ELIGIBLE,
    PROGRESSED_STATUSES,
    SHIP_ELIGIBLE,
    kit_progressed,
    require_line_quantity,
    require_total_fanout,
    spawn_kits,
)
from app.services.portability import invariants, starter_sheet
from app.services.portability.exporting import (
    ARCHIVE_FORMAT,
    EXPORT_VERSION,
    MANIFEST_NAME,
    schema_version,
)
from app.services.portability.spec import (
    CATALOG_TABLE_BY_ITEM_TYPE,
    SPEC_BY_KEY,
    TABLE_SPECS,
    ColumnRole,
    TableSpec,
    parse_currency,
    render,
)
from app.services.write_gate import acquire_write_gate

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
#: What a zip is allowed to expand to, cumulatively across its members. The upload
#: limit bounds *compressed* bytes, which says nothing about what they unpack to —
#: 10 MB of repeated text is gigabytes of CSV (#43). A full 50,000-row export is
#: comfortably under 50 MB, so this is headroom, not a working constraint.
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
_EXPAND_CHUNK = 64 * 1024
MAX_ROWS = 50_000

#: Every catalog table an order line can point at, by spec key. Derived, so a fifth
#: catalog type reaches the stub builder and the name map without an edit here.
CATALOG_TABLES: frozenset[str] = frozenset(CATALOG_TABLE_BY_ITEM_TYPE.values())

#: What a synthesized stub puts in a required column it was given no value for.
#: Keyed by *column*, not by table, so two tables requiring `category` answer the
#: same way and a new table requiring one is covered without being named.
STUB_PLACEHOLDERS: dict[str, str] = {
    "category": "uncategorised",
    "manufacturer": "unknown",
}


def _check_stub_placeholders() -> None:
    """Every required column a stub may have to fill has a placeholder.

    Run at import. `_create_stub` reads this dict by column name, so a spec gaining
    a required column without an entry here would raise KeyError mid-apply — a 500
    on a preview that reported no error, which is the defect this replaced.
    `name` is excluded: the stub exists precisely because something named it.
    """
    required = {
        column.name
        for key in CATALOG_TABLES | {"retailers"}
        for column in SPEC_BY_KEY[key].columns
        if column.required and column.name != "name"
    }
    missing = required - STUB_PLACEHOLDERS.keys()
    if missing:
        raise RuntimeError(
            f"portability stub placeholders are missing required column(s): "
            f"{', '.join(sorted(missing))} — add them to STUB_PLACEHOLDERS"
        )


_check_stub_placeholders()

#: Same list tests/conftest.py truncates — every table a replace-all restore owns.
#: `instance_settings` is deliberately not here: a replace_all wipes the
#: *collection*, not the instance's identity. The singleton row survives and the
#: archive's settings sheet, if any, is applied to it as an update (#23).
_PORTABLE_TABLES = (
    "kits, kit_photos, tools, consumables, upgrades, display_items, "
    "upgrade_applications, retailers, orders, order_items"
)

_ROW_MARKER = "_source_row"


# --- reading the upload ---------------------------------------------------------


@dataclass
class ParsedUpload:
    source: str
    tables: dict[str, list[dict[str, str]]]
    manifest: ManifestInfo | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _read_csv_text(raw: bytes, source: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        # Strict, not `errors="replace"` (#42): a mis-encoded name used to import as
        # U+FFFD and look like a successful import of a slightly wrong retailer.
        # A file that isn't UTF-8 is a file the user has to re-save, and they can
        # only do that if they're told which one and where.
        text_content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        line = raw.count(b"\n", 0, exc.start) + 1
        raise InvalidInputError(
            f"{source}: line {line} isn't valid UTF-8 (byte {exc.start}, "
            f"{bytes(raw[exc.start : exc.end])!r}). Re-save the file as UTF-8 "
            "— in Excel, 'CSV UTF-8' — and import it again."
        ) from exc
    reader = csv.DictReader(io.StringIO(text_content))
    header = [name.strip() for name in (reader.fieldnames or [])]
    rows: list[dict[str, str]] = []
    for index, raw_row in enumerate(reader, start=2):  # line 1 is the header
        row = {
            (key or "").strip(): (value or "") for key, value in raw_row.items() if key is not None
        }
        if not any(value.strip() for value in row.values()):
            continue  # blank spreadsheet filler line
        row[_ROW_MARKER] = str(index)
        rows.append(row)
    return header, rows


def _detect_table(filename: str, header: list[str]) -> str | None:
    stem = filename.rsplit("/", 1)[-1].removesuffix(".csv").strip().lower()
    if stem in SPEC_BY_KEY:
        return stem
    # Fall back to the header signature, so a file renamed by a download folder
    # ("kits (1).csv") still lands in the right table.
    names = {name.strip().lower() for name in header}
    best, best_score = None, 0
    for spec in TABLE_SPECS:
        # Aliases count towards the signature — a renamed older export should
        # still be recognised as the table it is.
        expected = {column.name for column in spec.columns}
        expected |= {alias for column in spec.columns for alias in column.aliases}
        score = len(names & expected)
        if score > best_score and score >= max(2, len(expected) // 2):
            best, best_score = spec.key, score
    return best


def read_upload(filename: str, content: bytes, *, reference_currency: str) -> ParsedUpload:
    """`reference_currency` is the settings-row value (#23), read by the caller —
    parsing is sync and sessionless, and only the starter-sheet expansion spends
    it (a priced row naming no currency is priced in the instance's own)."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidInputError(
            f"that file is {len(content) // 1024 // 1024} MB — the import limit is "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB. Split it into separate files."
        )
    name = (filename or "upload").lower()
    if name.endswith(".zip") or content[:2] == b"PK":
        return _read_zip(content, reference_currency)
    if name.endswith(".csv") or b"," in content[:4096]:
        return _read_single_csv(filename, content, reference_currency)
    raise InvalidInputError("unsupported file — import a .csv or a .zip archive")


class _ExpansionBudget:
    """A cumulative ceiling on the bytes a zip may unpack to.

    Members are streamed against one shared remaining count, so the budget is hit
    *while* reading rather than after the archive is already resident — which is
    the whole point, since the thing being defended against is a small file that
    expands without bound (#43).
    """

    def __init__(self, limit: int | None = None) -> None:
        # Read off the module rather than defaulting the argument, which would bind
        # the constant once at import and leave no way to drive the boundary.
        self.limit = MAX_EXPANDED_BYTES if limit is None else limit
        self.remaining = self.limit

    def read(self, archive: zipfile.ZipFile, entry: str) -> bytes:
        chunks: list[bytes] = []
        try:
            with archive.open(entry) as stream:
                while chunk := stream.read(_EXPAND_CHUNK):
                    self.remaining -= len(chunk)
                    if self.remaining < 0:
                        raise InvalidInputError(
                            f"that archive unpacks to more than "
                            f"{self.limit // 1024 // 1024} MB, which is the import "
                            "limit. Split it into separate files."
                        )
                    chunks.append(chunk)
        except DomainError:
            # The budget above raises through here. Re-raised explicitly so it stays
            # a budget refusal no matter what the tuple below grows to hold.
            raise
        except (
            zipfile.BadZipFile,
            EOFError,
            zlib.error,
            RuntimeError,
            NotImplementedError,
        ) as exc:
            # Everything `zipfile` throws for a member it cannot hand back. Damage —
            # a bad CRC, a payload that ends early — is invisible to `ZipFile()`
            # construction, which only reads the central directory. The other two are
            # not damage but are just as much the uploader's business: `RuntimeError`
            # for an encrypted member, `NotImplementedError` for a compression method
            # this build has no decompressor for. All three are properties of a file
            # someone uploaded, so under rule 6 none of them is a 500.
            raise InvalidInputError(
                f"{entry} could not be unpacked ({exc}) — the archive may be damaged, "
                "encrypted, or written with a compression method plamotrack can't "
                "read. Export it again."
            ) from exc
        return b"".join(chunks)


@dataclass
class _Declaration:
    """One entry from the manifest's `tables` block, with its table key kept."""

    table: str
    filename: str
    rows: int


@dataclass
class _Member:
    """One CSV member of the archive, and what the importer actually did with it."""

    path: str
    #: The table its rows were routed to, `_STARTER_SHEET` if it was expanded, or
    #: None if it was recognised as nothing and skipped.
    routed: str | None
    rows: int

    @property
    def filename(self) -> str:
        return self.path.rsplit("/", 1)[-1]


_STARTER_SHEET = "<starter sheet>"


def _json_shape(data: Any) -> str:
    """Name what a manifest turned out to be, for a message that says which wrong
    thing it was — `null` and `[]` are different mistakes with different fixes."""
    if data is None:
        return "null"
    return {bool: "a boolean", int: "a number", float: "a number", str: "a string"}.get(
        type(data), "a list"
    )


def _declared_tables(data: dict) -> list[_Declaration]:
    """The `tables` block `build_manifest` writes, table key included.

    The key is kept, not discarded: `{"kits": {"file": "retailers.csv"}}` is a
    manifest that disagrees with itself, and reducing the block to
    `filename -> count` is what made that indistinguishable from an intact archive.

    Deliberately tolerant about *shape*: a hand-edited or older manifest that says
    something unexpected here just can't be reconciled, and must not become a parse
    error on a file that is otherwise fine.
    """
    declared: list[_Declaration] = []
    block = data.get("tables")
    if not isinstance(block, dict):
        return declared
    for table, entry in block.items():
        if not isinstance(entry, dict) or not isinstance(table, str):
            continue
        name, rows = entry.get("file"), entry.get("rows")
        if isinstance(name, str) and isinstance(rows, int) and not isinstance(rows, bool):
            declared.append(_Declaration(table, name.rsplit("/", 1)[-1], rows))
    return declared


def _reconcile_manifest(
    declared: list[_Declaration],
    members: list[_Member],
    warnings: list[str],
    errors: list[str],
) -> None:
    """Hold the archive to what its own manifest claims (#42).

    The counts were written and then never read, so a truncated or partly extracted
    archive imported whatever survived and said nothing.

    The reconciliation is **over the rows the importer actually consumed**, not over
    the names in the zip. Matching declarations to a flat `basename -> count` map
    let the two diverge while this reported clean: an undeclared member imported
    alongside the declared ones, two directories contributing the same basename, and
    a declaration whose file routes to a table other than the one it is filed under
    were all invisible. So each declaration is resolved to exactly one member, and
    every consumed member has to be claimed by exactly one declaration.

    Severity follows the same rule throughout: **data that isn't there, or a zip
    that can't say what it holds, blocks; data that is there and merely disagrees
    with the manifest warns.** A hand-trimmed export is a legitimate thing to
    import, and the preview lists every row either way.
    """
    if not declared:
        return  # nothing claimed, so nothing to hold it to

    # Indexed once, not re-scanned per declaration. Both sides of this comparison are
    # attacker-scaled — a manifest declares as many tables as it likes, and a 10 MB
    # zip holds on the order of 100,000 empty members — so a nested walk here is a
    # DoS in the middle of the code added to prevent one.
    by_filename: dict[str, list[_Member]] = {}
    for member in members:
        by_filename.setdefault(member.filename, []).append(member)

    claimed: set[str] = set()
    for declaration in sorted(declared, key=lambda d: d.filename):
        matches = by_filename.get(declaration.filename, [])
        if not matches:
            errors.append(
                f"the manifest lists {declaration.filename}, but it isn't in this "
                "archive — the zip is truncated or was only partly extracted"
            )
            continue
        if len(matches) > 1:
            paths = sorted({member.path for member in matches})
            claimed.update(paths)
            if len(paths) > 1:
                # Distinct paths, one basename — `a/kits.csv` and `b/kits.csv`. Two
                # members under one *path* is a different fault and has already been
                # reported against the path itself; saying it twice helps nobody.
                errors.append(
                    f"this archive holds {len(paths)} files named "
                    f"{declaration.filename} ({', '.join(paths)}) — which one the "
                    "manifest describes can't be told, so the row counts can't be "
                    "trusted"
                )
            continue

        member = matches[0]
        claimed.add(member.path)
        if member.routed is not None and member.routed != declaration.table:
            warnings.append(
                f"the manifest files {member.filename} under '{declaration.table}', "
                f"but its columns are {member.routed} — importing it as {member.routed}"
            )
        if member.rows != declaration.rows:
            warnings.append(
                f"{member.filename}: the manifest says {declaration.rows:,} row(s) but "
                f"{member.rows:,} could be read — this archive isn't intact"
            )

    for member in members:
        # Only rows that actually went somewhere. A member recognised as nothing has
        # already warned on its own account and contributed no data to be surprised by.
        if member.path not in claimed and member.routed is not None:
            warnings.append(
                f"{member.path} isn't listed in this archive's manifest, but "
                f"{member.rows:,} row(s) were read from it as {member.routed} — "
                "the manifest doesn't describe everything in this zip"
            )


def _read_zip(content: bytes, reference_currency: str) -> ParsedUpload:
    tables: dict[str, list[dict[str, str]]] = {}
    warnings: list[str] = []
    errors: list[str] = []
    manifest: ManifestInfo | None = None
    declared: list[_Declaration] = []
    members: list[_Member] = []
    budget = _ExpansionBudget()

    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise InvalidInputError("that zip file is corrupt or not a zip archive") from exc

    with archive:
        names = [n for n in archive.namelist() if not n.endswith("/") and "__MACOSX" not in n]
        # A zip may legally hold two members under one path, and `archive.open(name)`
        # resolves to whichever was written last — so iterating `namelist()` reads
        # that one twice and the other never. Manifest or no manifest, an archive
        # that names the same file twice cannot say what it holds.
        #
        # Counted in one pass. `names.count(...)` per entry re-walked the whole list
        # every time, which is quadratic on a member list the uploader chooses the
        # length of, and it ran before a single byte of member content was read — so
        # the expansion budget below could not have helped.
        for path, count in sorted(Counter(names).items()):
            if count > 1:
                errors.append(
                    f"this archive holds more than one member called {path} — it "
                    "can't be read reliably, so nothing will be imported from it"
                )

        manifest_names = [n for n in names if n.rsplit("/", 1)[-1] == MANIFEST_NAME]
        if len(manifest_names) > 1:
            # Taking the first left the governing manifest decided by member order,
            # so re-zipping the same files in a different order changed what the
            # archive claimed. By the rule above, a zip that cannot say what it holds
            # blocks rather than picking one.
            errors.append(
                f"this archive holds {len(manifest_names)} manifests "
                f"({', '.join(sorted(manifest_names))}) — there is no telling which "
                "one describes it, so nothing will be imported from it"
            )
        elif manifest_names:
            try:
                data = json.loads(budget.read(archive, manifest_names[0]))
            except (json.JSONDecodeError, ValueError) as exc:
                warnings.append(f"manifest.json could not be read ({exc}) — continuing without it")
            else:
                # `else`, not a `data is None` sentinel: `null` is valid JSON that
                # parses to None, so a sentinel of None made a null manifest
                # indistinguishable from a failed parse and it slipped through
                # unremarked while `[]` and `"text"` warned.
                if isinstance(data, dict):
                    # Declarations first, and deliberately not inside the guard
                    # below: `tables` is validated on its own terms by
                    # `_declared_tables`, so an `exported_at` of the wrong type says
                    # nothing about whether the file list is readable. Losing the
                    # reconciliation over a bad metadata field would be discarding
                    # the more useful half.
                    declared = _declared_tables(data)
                    try:
                        manifest = _read_manifest(data)
                    except ValidationError as exc:
                        # `ManifestInfo` is a Pydantic model, so a field of the wrong
                        # type raises here — and `ValidationError` is a `ValueError`,
                        # which is why this was covered for free while the parse and
                        # the model build were one expression inside the `try` above.
                        # Splitting them to tell `null` apart from a parse failure
                        # took the cover away without replacing it (rule 6).
                        #
                        # Named fields, not `{exc}`: a Pydantic report runs to
                        # several lines and a docs URL, and this lands in a preview
                        # panel someone is reading to decide whether to import.
                        fields = ", ".join(
                            str(error["loc"][0]) for error in exc.errors() if error.get("loc")
                        )
                        warnings.append(
                            f"manifest.json has metadata this instance can't read "
                            f"({fields or 'unknown field'}) — continuing without it"
                        )
                else:
                    warnings.append(
                        f"manifest.json is {_json_shape(data)}, not an object, so it "
                        "says nothing about this archive — continuing without it"
                    )
        else:
            warnings.append(
                "no manifest.json in this zip, so it's being read as a loose set of CSVs"
            )

        for entry in names:
            if not entry.lower().endswith(".csv"):
                continue
            header, rows = _read_csv_text(budget.read(archive, entry), entry)
            if starter_sheet.is_starter_sheet(header):
                # Cumulative across members: a zip of starter sheets must not get
                # a fresh budget per file.
                spent = sum(len(existing) for existing in tables.values())
                expanded_tables, problems = starter_sheet.expand(
                    rows, row_budget=max(0, MAX_ROWS - spent), reference_currency=reference_currency
                )
                for key, expanded in expanded_tables.items():
                    tables.setdefault(key, []).extend(expanded)
                errors.extend(problems)
                members.append(_Member(entry, _STARTER_SHEET, len(rows)))
                continue
            table_key = _detect_table(entry, header)
            members.append(_Member(entry, table_key, len(rows)))
            if table_key is None:
                warnings.append(f"{entry}: not recognised as any known table — skipped")
                continue
            tables.setdefault(table_key, []).extend(rows)

        _reconcile_manifest(declared, members, warnings, errors)

    if not tables:
        errors.append("that archive contained no readable table data")
    return ParsedUpload(
        source="archive" if manifest else "csv-set",
        tables=tables,
        manifest=manifest,
        warnings=warnings,
        errors=errors,
    )


def _read_single_csv(filename: str, content: bytes, reference_currency: str) -> ParsedUpload:
    header, rows = _read_csv_text(content, filename or "upload")
    if starter_sheet.is_starter_sheet(header):
        expanded, problems = starter_sheet.expand(
            rows, row_budget=MAX_ROWS, reference_currency=reference_currency
        )
        return ParsedUpload(source="starter-sheet", tables=expanded, errors=problems)
    table_key = _detect_table(filename, header)
    if table_key is None:
        known = ", ".join(spec.filename for spec in TABLE_SPECS)
        raise InvalidInputError(
            f"couldn't tell which table '{filename}' holds. Name it after the table "
            f"({known}), or use the starter sheet template."
        )
    return ParsedUpload(source=f"csv:{table_key}", tables={table_key: rows})


def _read_manifest(data: dict) -> ManifestInfo:
    return ManifestInfo(
        format=data.get("format"),
        export_version=data.get("export_version"),
        schema_version=data.get("schema_version"),
        app_version=data.get("app_version"),
        exported_at=data.get("exported_at"),
    )


# --- planning -------------------------------------------------------------------


@dataclass
class _Row:
    """One incoming row, resolved. Carries everything apply needs."""

    table: str
    row_number: int
    action: RowAction
    values: dict[str, Any]
    present: set[str]
    #: Columns this importer synthesised rather than read from the sheet. They are
    #: in `present` because they will be written, but the sheet never said them —
    #: which is the difference between a default and an instruction (#12).
    filled: set[str] = field(default_factory=set)
    label: str = ""
    matched_id: uuid.UUID | None = None
    matched_by: str | None = None
    target: Any = None
    changes: list[FieldChange] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    error: str | None = None
    new_id: uuid.UUID | None = None
    #: ALT_MONEY columns whose cell was grouped in a way a decimal separator could
    #: equally explain (`1,234`). Valid grammar, but only the currency settles which
    #: number it is, and that isn't known until `_apply_money_alternates`.
    lone_grouped: set[str] = field(default_factory=set)
    #: This row's `id` was minted here rather than read from the sheet — a stub
    #: conjured from a reference. Sheet-supplied ids are facts about the file and
    #: hash as themselves; minted ones are fresh on every run, so
    #: `_plan_fingerprint` replaces them with a positional token.
    synthetic_id: bool = False
    #: Optional REF columns whose cell named an id that resolved to nothing —
    #: `column -> (table, the id it named)`. `_resolve_all_refs` nulls the value
    #: (#82: the row imports without the link) and records it here, because on an
    #: update the null it left behind is indistinguishable from a blank cell, and
    #: the two are different instructions once there is a stored link to lose
    #: (`_refuse_unresolved_overwrite`).
    unresolved: dict[str, tuple[str, uuid.UUID]] = field(default_factory=dict)


@dataclass
class _Spawn:
    order_item_id: uuid.UUID
    order_id: uuid.UUID
    count: int
    name: str
    grade: str
    scale: str | None
    kit_number: str | None
    status: str
    row_number: int
    received: bool
    #: The order's post-write receipt instant, resolved at plan time
    #: (`_order_receipt`) and hash-bound like every other value a spawn writes.
    received_at: datetime | None
    #: The same one stage earlier (#95): the post-write ship instant, so a kit
    #: landing in_transit carries it. Hash-bound for the same reason.
    shipped_at: datetime | None


@dataclass
class _Removal:
    """A stored kit a line's reduced quantity no longer accounts for (#44 case 2)."""

    kit_id: uuid.UUID
    order_item_id: uuid.UUID
    row_number: int


@dataclass
class _Advance:
    """A pre-existing kit this apply's own ship/receive transition moves (#119).

    The `_Spawn` precedent extended from rows the plan creates to rows it moves:
    resolved at plan time, hash-bound, and consumed verbatim by the apply. The
    old shape decided from `kit.status` *at apply*, after the hash check, so the
    set of kits an approved preview implied would move was not the set the apply
    moved — a kit progressed between preview and apply was silently skipped (or
    a fresh one silently taken) under a hash that still matched.
    """

    kit_id: uuid.UUID
    before: KitStatus
    after: KitStatus
    #: The order's post-write instant that lands as `status_updated_at` — the
    #: ship instant for a kit landing in_transit, the receipt for backlog (#93,
    #: #95). Always the transition the descriptor exists for, never the clock.
    stamp: datetime


@dataclass
class ExecutionPlan:
    mode: ImportMode
    rows: dict[str, list[_Row]]
    spawns: list[_Spawn]
    removals: list[_Removal]
    advances: list[_Advance]
    plan: ImportPlan


def _instance_dict(spec: TableSpec, instance: Any) -> dict[str, Any]:
    return {column.name: column.get(instance) for column in spec.columns if column.persisted}


def _norm_name(value: Any) -> str:
    return str(value or "").strip().lower()


def _dangling_optional_message(column: str, table: str, missing: uuid.UUID) -> str:
    """#82's wording for an optional reference that named nothing, in one place so
    `_refuse_unresolved_overwrite` can withdraw it precisely when it turns out to
    be untrue for the row."""
    return (
        f"{column}: no {table} here has id {missing}, so this row imports "
        f"without it. Add that {table} row, or fill it in afterwards"
    )


class _Planner:
    def __init__(
        self, session: AsyncSession, upload: ParsedUpload, mode: ImportMode, reference_currency: str
    ) -> None:
        self.session = session
        self.upload = upload
        self.mode = mode
        # The settings-row value (#23), read once by `plan_import` before parsing
        # began, so the fill below and the starter expansion that may have produced
        # this upload agree on what "the instance default" was.
        self.reference_currency = reference_currency
        self.remap: dict[tuple[str, uuid.UUID], uuid.UUID] = {}
        self.existing: dict[str, list[Any]] = {}
        self.by_id: dict[str, dict[uuid.UUID, Any]] = {}
        self.by_natural: dict[str, dict[tuple, list[Any]]] = {}
        self.created_ids: dict[str, set[uuid.UUID]] = {key: set() for key in SPEC_BY_KEY}
        self.rows: dict[str, list[_Row]] = {}
        self.spawns: list[_Spawn] = []
        self.removals: list[_Removal] = []
        self.advances: list[_Advance] = []
        self.warnings: list[str] = list(upload.warnings)
        self.blocking: list[str] = list(upload.errors)
        self.catalog_names: dict[uuid.UUID, str] = {}
        self.claimed_lines: set[uuid.UUID] = set()
        # Upload-local identity, which `by_id`/`by_natural` cannot supply: those are
        # built once from the database and never learn what this upload is planning.
        # Row number of the row that claimed each, so the second one can point at it.
        # Three, not one — the id a row writes, the row it resolves to, and the name
        # it goes by are three different identities that come apart from each other.
        self.claimed_source_ids: dict[str, dict[uuid.UUID, int]] = {key: {} for key in SPEC_BY_KEY}
        self.claimed_targets: dict[str, dict[uuid.UUID, int]] = {key: {} for key in SPEC_BY_KEY}
        self.claimed_natural: dict[str, dict[tuple, int]] = {key: {} for key in SPEC_BY_KEY}

    # -- loading ---------------------------------------------------------------

    async def load_existing(self) -> None:
        for spec in TABLE_SPECS:
            stmt = select(spec.model)
            # `kit_progressed` reads photos and upgrade_applications, and the
            # downward reconciliation in `_plan_spawns` asks it about every kit on
            # a shrinking line. Lazy-loading either raises outside the async
            # context, so both come along with the kits themselves.
            kit_evidence = (
                selectinload(Kit.photos),
                selectinload(Kit.upgrade_applications),
            )
            if spec.key == "orders":
                stmt = stmt.options(
                    selectinload(Order.items).selectinload(OrderItem.kits).options(*kit_evidence)
                )
            elif spec.key == "order_items":
                stmt = stmt.options(selectinload(OrderItem.kits).options(*kit_evidence))
            elif spec.key == "kits":
                # A kit `_attached_after` moves *onto* a line comes from here rather
                # than from the line's own collection, and lands in the same removal
                # candidacy question. Today `described` excludes it before
                # `kit_progressed` is reached, so this is not load-bearing — it is
                # here so that stops being a thing anyone has to know.
                stmt = stmt.options(*kit_evidence)
            instances = list((await self.session.scalars(stmt)).all())
            self.existing[spec.key] = instances
            self.by_id[spec.key] = {instance.id: instance for instance in instances}
            index: dict[tuple, list[Any]] = {}
            if spec.natural_key is not None:
                for instance in instances:
                    key = spec.natural_key(_instance_dict(spec, instance))
                    if key is not None:
                        index.setdefault(key, []).append(instance)
            self.by_natural[spec.key] = index

        # Every catalog table, from the registry rather than a literal list. This
        # map is what lets an order line arriving under a foreign uuid resolve by
        # `catalog_name` and match a stored order instead of duplicating it; a table
        # missing here is silently unmatched, not an error (#129 review, P2-2).
        for table in CATALOG_TABLES:
            self.catalog_names.update(
                {instance.id: instance.name for instance in self.existing[table]}
            )

    # -- parsing ---------------------------------------------------------------

    def _parse_row(self, spec: TableSpec, raw: dict[str, str]) -> _Row:
        # Retired header names become current ones before anything looks at the
        # row, so the rest of this method only ever sees the spec's own vocabulary.
        raw = spec.canonicalise(raw)
        row_number = int(raw.get(_ROW_MARKER, 0) or 0)
        values: dict[str, Any] = {}
        present: set[str] = set()
        errors: list[str] = []

        for key in raw:
            if key == _ROW_MARKER:
                continue
            if spec.column(key) is None and key.strip():
                message = f"column '{key}' isn't a {spec.key} column and was ignored"
                if message not in self.warnings:
                    self.warnings.append(message)

        lone_grouped: set[str] = set()
        for column in spec.columns:
            if column.name not in raw:
                continue
            present.add(column.name)
            cell = raw[column.name]
            if column.role is ColumnRole.ALT_MONEY and is_lone_group(cell):
                lone_grouped.add(column.name)
            try:
                values[column.name] = column.parse(cell)
            except (ArithmeticError, ValueError) as exc:
                # ArithmeticError as well as ValueError: a cell is data, and no
                # arrangement of it should be able to leave here as a 500. `inf` in
                # an integer column used to raise OverflowError straight past this.
                errors.append(f"{column.name}: {exc}")
                values[column.name] = None

        for column in spec.columns:
            if column.required and column.name in present and values.get(column.name) is None:
                errors.append(f"{column.name} is required")

        filled: set[str] = set()
        _default_money_currency(spec, values, present, filled, self.reference_currency)

        row = _Row(
            table=spec.key,
            row_number=row_number,
            action=RowAction.ERROR if errors else RowAction.CREATE,
            values=values,
            present=present,
            filled=filled,
            lone_grouped=lone_grouped,
        )
        row.label = spec.label(values)
        if errors:
            row.error = "; ".join(errors)
        return row

    # -- reference resolution --------------------------------------------------

    def _alt_for(self, spec: TableSpec, column) -> Any:
        """The readable mirror column that stands in for this uuid, if the spec has
        one — `retailer_name` for `retailer_id`, `catalog_name` for
        `catalog_ref_id`."""
        return next(
            (c for c in spec.columns if c.role is ColumnRole.ALT_REF and c.mirrors == column.name),
            None,
        )

    def _resolve_ref(
        self, row: _Row, spec: TableSpec, column, replace_all: bool
    ) -> tuple[str, uuid.UUID] | None:
        """Point a foreign key at the right local row: remap it, accept it if it's
        already local or arriving in this import, or fall back to the readable
        mirror column.

        Returns the `(table, id)` it could not resolve, so the caller can say which
        row is missing; `None` when the reference landed somewhere or the row never
        supplied one.

        **`replace_all` may not resolve against the live database (#45).** Every
        portable table is truncated before this plan is written, so a uuid found in
        `by_id`, or a name matched against `existing`, points at a row that will not
        be there afterwards. `order_items.catalog_ref_id` is polymorphic across three
        tables and therefore has no foreign key, so that one commits a line holding a
        dead uuid and nothing complains; the columns that do have a foreign key fail
        at flush instead — a rollback rather than corruption, but a 500 raised after
        the operator confirmed a preview that promised otherwise. In this mode the
        upload is the only world there is: `created_ids` and the planned rows.
        """
        table = column.ref_table
        if table == "catalog":
            # Matching hasn't bound `row.target` yet, and a row that omits
            # `item_type` can only ever match by id (the line fingerprint carries
            # the type), so the stored line the sheet's id names is exactly what
            # matching will bind — look it up rather than read the row as typeless
            # and pass the reference through unresolved (#90). Not under
            # `replace_all`: the stored line is truncated before the plan lands
            # (#45), and the typeless create is refused for the missing column.
            stored = None if replace_all else self.by_id[spec.key].get(row.values.get("id"))
            item_type = invariants.effective_item_type(row, stored=stored)
            if item_type is None:
                return None
            table = CATALOG_TABLE_BY_ITEM_TYPE.get(str(item_type))
            if table is None:  # kit lines don't reference the catalog
                # Dropped, and said out loud for the same reason as any other
                # discarded reference (#82): the operator filled the cell in. This
                # one never reaches the `dangling` path below, because there is no
                # catalog table to fail to find it in — kits are spawned fresh, so
                # the column means nothing here whatever it holds.
                discarded = row.values.get(column.name)
                row.values[column.name] = None
                if discarded is not None:
                    row.messages.append(
                        f"{column.name}: a kit line doesn't reference the catalog — its kits "
                        f"are spawned fresh, so {discarded} was ignored"
                    )
                return None

        dangling: tuple[str, uuid.UUID] | None = None
        raw_id = row.values.get(column.name)
        if raw_id is not None:
            mapped = self.remap.get((table, raw_id))
            if mapped is not None:
                row.values[column.name] = mapped
                return None
            arriving = raw_id in self.created_ids[table]
            if arriving or (not replace_all and raw_id in self.by_id[table]):
                return None
            row.values[column.name] = None  # unknown uuid — try the readable mirror
            dangling = (table, raw_id)

        alt = self._alt_for(spec, column)
        if alt is None:
            return dangling
        name = _norm_name(row.values.get(alt.name))
        if not name:
            return dangling

        # Resolving through the readable mirror counts as the row supplying this
        # column, even though the uuid column itself was blank or absent.
        row.present.add(column.name)

        if not replace_all:
            match = next(
                (item for item in self.existing[table] if _norm_name(item.name) == name),
                None,
            )
            if match is not None:
                row.values[column.name] = match.id
                return None
        # Named but unknown: created on the fly, like the select-or-create flow does.
        # This is also why a *name* needs no `replace_all` special case where a uuid
        # does — the name is satisfiable by creating what it names, so an archive
        # supplying `retailer_name` with no retailers.csv still works, and gets a
        # retailer that exists after the truncate rather than a pointer to one that
        # doesn't.
        pending = self._pending_by_name(table, name)
        if pending is not None:
            row.values[column.name] = pending
            return None
        row.values[column.name] = self._create_stub(table, row.values.get(alt.name), row)
        return None

    def _pending_by_name(self, table: str, name: str) -> uuid.UUID | None:
        for planned in self.rows.get(table, []):
            if planned.action is RowAction.ERROR:
                continue
            if _norm_name(planned.values.get("name")) == name:
                return planned.matched_id or planned.new_id
        return None

    def _create_stub(self, table: str, name: str | None, source: _Row) -> uuid.UUID:
        """A referenced-but-undeclared catalog item or retailer. Created at quantity
        zero — stock is stated in the catalog CSVs, never inferred from an order.

        The placeholders come from the spec's own `required` flags, not a list of
        table names. Three literal tuples here previously decided which stubs got a
        category, a manufacturer and a stock count, and a fourth catalog table
        matched none of them: the stub was built without its NOT NULL `category`, so
        preview reported a clean CREATE and apply died at flush with a 500 — the
        shape rule 6 exists to prevent (#129 review, P2-1). `STUB_PLACEHOLDERS` is
        checked against the registry at import, so a new required column fails
        loudly here rather than at someone's flush.
        """
        spec = SPEC_BY_KEY[table]
        new_id = uuid.uuid4()
        values: dict[str, Any] = {"id": new_id, "name": (name or "").strip()}
        present = {"id", "name"}
        for column in spec.columns:
            if column.required and column.name not in values:
                values[column.name] = STUB_PLACEHOLDERS[column.name]
                present.add(column.name)
        if table in CATALOG_TABLES:
            values["quantity_on_hand"] = 0
            present.add("quantity_on_hand")

        stub = _Row(
            table=table,
            row_number=source.row_number,
            action=RowAction.CREATE,
            values=values,
            present=present,
            label=spec.label(values),
            new_id=new_id,
            synthetic_id=True,
            messages=[
                f"created from a reference on {source.table} row {source.row_number}"
                + (" at 0 on hand" if table != "retailers" else "")
            ],
        )
        self.rows.setdefault(table, []).append(stub)
        self.created_ids[table].add(new_id)
        return new_id

    # -- matching --------------------------------------------------------------

    def _match_generic(self, spec: TableSpec, row: _Row) -> None:
        row_id = row.values.get("id")
        if row_id is not None:
            found = self.by_id[spec.key].get(row_id)
            if found is not None:
                row.matched_id, row.matched_by, row.target = row_id, "id", found
                return
        if spec.natural_key is None:
            return
        key = spec.natural_key(row.values)
        if key is None:
            return
        candidates = self.by_natural[spec.key].get(key, [])
        if len(candidates) == 1:
            row.matched_id = candidates[0].id
            row.matched_by = key[0]
            row.target = candidates[0]
        elif len(candidates) > 1:
            row.action = RowAction.ERROR
            row.error = (
                f"{len(candidates)} existing {spec.key} rows match this one — "
                "set the id column to say which one you mean"
            )

    def _line_fingerprint(
        self, item_type: Any, ref_name: str, quantity: Any, unit_price: Any, currency: Any
    ) -> tuple:
        """What makes two order lines the same purchase.

        `currency` is part of it because the price alone is not a number — it is a
        number *in* something (§6, rule 4). Without it a stored ¥1000 line and an
        incoming A$1000 line fingerprint identically, the incoming row matches, and
        the apply writes `currency_code: AUD` over the yen line as an ordinary
        field update. That is #12's relabelling reached from a different direction:
        no arithmetic is wrong anywhere, the amount simply stops meaning what it
        meant. Two prices in different currencies are two different purchases, and
        the fingerprint has to say so before the diff is ever computed.
        """
        return (
            str(item_type or ""),
            _norm_name(ref_name),
            int(quantity or 0),
            int(unit_price or 0),
            (currency or "").strip().upper(),
        )

    def _existing_line_fingerprint(self, item: OrderItem) -> tuple:
        if item.item_type is ItemType.KIT:
            ref_name = item.kits[0].name if item.kits else ""
        else:
            ref_name = self.catalog_names.get(item.catalog_ref_id, "")
        return self._line_fingerprint(
            item.item_type, ref_name, item.quantity, item.unit_price_minor, item.currency_code
        )

    def _incoming_line_fingerprint(self, values: dict[str, Any]) -> tuple:
        item_type = values.get("item_type")
        if item_type is ItemType.KIT:
            ref_name = values.get("kit_name") or ""
        else:
            ref_name = values.get("catalog_name") or self.catalog_names.get(
                values.get("catalog_ref_id"), ""
            )
        return self._line_fingerprint(
            item_type,
            ref_name,
            values.get("quantity"),
            values.get("unit_price_minor"),
            values.get("currency_code"),
        )

    def _match_order(self, row: _Row, incoming_lines: dict[uuid.UUID, list[dict]]) -> None:
        row_id = row.values.get("id")
        if row_id is not None:
            found = self.by_id["orders"].get(row_id)
            if found is not None:
                row.matched_id, row.matched_by, row.target = row_id, "id", found
                return

        retailer_id = row.values.get("retailer_id")
        if retailer_id is None:
            return
        candidates = [o for o in self.existing["orders"] if o.retailer_id == retailer_id]

        number = _norm_name(row.values.get("order_number"))
        if number:
            matches = [o for o in candidates if _norm_name(o.order_number) == number]
            label = "retailer + order number"
        else:
            wanted = sorted(
                self._incoming_line_fingerprint(line) for line in incoming_lines.get(row_id, [])
            )
            order_date = row.values.get("order_date")
            matches = [
                o
                for o in candidates
                if o.order_date == order_date
                and sorted(self._existing_line_fingerprint(i) for i in o.items) == wanted
            ]
            label = "retailer + date + lines"

        if len(matches) == 1:
            row.matched_id, row.matched_by, row.target = matches[0].id, label, matches[0]
        elif len(matches) > 1:
            row.action = RowAction.ERROR
            row.error = (
                f"{len(matches)} existing orders match this one ({label}) — "
                "set the id column to say which one you mean"
            )

    def _match_order_item(self, row: _Row) -> None:
        row_id = row.values.get("id")
        if row_id is not None:
            found = self.by_id["order_items"].get(row_id)
            if found is not None:
                row.matched_id, row.matched_by, row.target = row_id, "id", found
                return
        order_id = row.values.get("order_id")
        parent = self.by_id["orders"].get(order_id) if order_id else None
        if parent is None:
            return
        wanted = self._incoming_line_fingerprint(row.values)
        for item in parent.items:
            if item.id in self.claimed_lines:
                continue
            if self._existing_line_fingerprint(item) == wanted:
                self.claimed_lines.add(item.id)
                row.matched_id, row.matched_by, row.target = item.id, "order + line", item
                return

    def _claim_source_id(self, spec: TableSpec, row: _Row) -> None:
        """The id the *file* wrote, claimed before anything resolves it.

        This runs ahead of matching, and has to. The resolved target is not the same
        identity as the id in the cell, and they come apart exactly when two rows
        carrying one id resolve differently:

            retailers.csv  id=X, name=Gundam Base   → natural-matches local row A
            retailers.csv  id=X, name=Other Shop    → no match, creates at X

        The targets are `A` and `X` — two distinct values, nothing to report — so a
        target-only check previews `unchanged` + `create` and applies cleanly. But
        row 2 recorded `remap[X] → A`, so every later row in the archive naming
        `retailer_id=X` is rewritten to **Gundam Base**, while the row actually
        created at X is **Other Shop**. The file's own id has been given two
        meanings, and the import silently picks one. Found by external review of
        #46's first cut, which claimed only the target.

        Claiming before matching is the point: an id-duplicating row must not get as
        far as contributing a `remap` entry that later tables resolve through, even
        though the blocking error stops the apply either way. A preview that shows
        references following a rewrite made by a row it is reporting as broken is
        not a truthful preview.
        """
        if row.action is RowAction.ERROR:
            return
        source_id = row.values.get("id")
        if source_id is None:
            return
        first = self.claimed_source_ids[spec.key].get(source_id)
        if first is not None:
            row.action = RowAction.ERROR
            row.error = (
                f"row {first} of {spec.key}.csv already uses id {source_id} — "
                "two rows in one upload cannot carry the same id"
            )
            return
        self.claimed_source_ids[spec.key][source_id] = row.row_number

    def _claim_identity(self, spec: TableSpec, row: _Row) -> None:
        """No two rows in one upload may name the same thing.

        `by_id` and `by_natural` are built once, from the database, and never learn
        what this upload is planning — so every duplicate-detection question about
        the *file itself* went unasked. Two rows carrying the same explicit `id`
        both reached `session.add` with one primary key and died as an
        `IntegrityError`: a 500 out of the apply, after a preview that listed two
        clean creates. Two rows naming the same new retailer were both planned as
        creates, quietly producing the duplicate the whole select-or-create design
        exists to prevent (rule 3).

        Three questions in all, because no one of these identities implies another.
        `_claim_source_id` above asks the first, before matching. The two here are
        asked after it, once the row's fate is known:

        * **the target** — the row a plan writes, `matched_id` for an update and
          `new_id` for a create. Catches two rows landing on one existing row from
          *different* source ids, which neither other check can see.
        * **the natural key**, but only for a row that supplied no `id`. Two new
          retailers called "Gundam Base" get different random `new_id`s, so the
          target check cannot see them either. Restricting it to id-less rows is
          what keeps a legitimate archive importable: nothing stops a collection
          holding two retailers with the same name, an export writes both, and each
          of those rows carries the id that says which is which.

        Reported rather than merged. A file listing one thing twice is a mistake in
        the file, and quietly folding the rows together is how an import surprises
        someone — the preview names both row numbers instead.
        """
        if row.action in (RowAction.ERROR, RowAction.SKIP):
            return

        target = row.matched_id or row.new_id
        if target is not None:
            first = self.claimed_targets[spec.key].get(target)
            if first is not None:
                row.action = RowAction.ERROR
                row.error = (
                    f"row {first} of {spec.key}.csv already claims this row — "
                    "two rows in one upload cannot describe the same record"
                )
                return
            self.claimed_targets[spec.key][target] = row.row_number

        if row.values.get("id") is not None or spec.natural_key is None:
            return
        key = spec.natural_key(row.values)
        if key is None:
            return
        first = self.claimed_natural[spec.key].get(key)
        if first is not None:
            row.action = RowAction.ERROR
            row.error = (
                f"row {first} of {spec.key}.csv already describes this "
                f"{key[0]} — give one of them an id if they are meant to be different"
            )
            return
        self.claimed_natural[spec.key][key] = row.row_number

    # -- classification --------------------------------------------------------

    def _keep_stored_where_unstatable(self, spec: TableSpec, row: _Row) -> None:
        """A blank cell never writes NULL into a column that cannot hold one (#88).

        "A blank cell in a column you included means empty this field" is the
        documented rule and archive fidelity needs it — but it was applied to every
        column, including the ones the database refuses to leave empty. Nine of
        them across six tables previewed clean and died at flush as an
        `IntegrityError`: a bare 500 naming no row, after the operator was told the
        import was fine (rule 6).

        On an **update** the answer is the stored value. You cannot unset a
        creation time or a retailer, so a blank in such a column is closer to an
        omission than an instruction — and an omitted column is already left alone,
        which is the same answer arriving by the same reasoning. The cell is
        dropped from `present` so no change is planned for it, and the row says so
        rather than pretending the edit landed.

        Runs late in `_classify` on purpose: `_resolve_all_refs` and
        `_apply_money_alternates` have both already had their turn, so a blank
        `retailer_id` beside a filled `retailer_name`, or a blank
        `unit_price_minor` beside a filled `unit_price`, has been settled from its
        mirror and never reaches here. This is only for a value nothing else could
        supply.

        Creates are `_refuse_unfillable_creates`'s problem — there is no stored
        value to keep, so the answer there is a row error rather than silence.
        """
        for column in spec.columns:
            if column.name == "id" or not column.persisted or column.name not in row.present:
                continue
            if row.values.get(column.name) is not None:
                continue
            if _column_is_nullable(spec, column.name):
                continue
            row.present.discard(column.name)
            row.messages.append(
                f"{column.name}: left as it was — this column can't be emptied, and nothing "
                "in this row supplies a new value"
            )

    def _refuse_unresolved_overwrite(self, spec: TableSpec, row: _Row) -> bool:
        """An id that names nothing may not clear a link the stored row has.

        `_resolve_all_refs` nulls an optional reference it cannot resolve and says
        so (#82) — right for the case that rule was written for, a `kits.csv`
        arriving in a fresh instance whose lines were never here, where the null
        changes nothing. On an **update** the same null overwrites a stored value:
        a kit that *is* on an order line, whose row carries a mistyped or foreign
        `order_item_id`, was quietly detached from the line that bought it, and
        the fan-out (#44) then read the departure as a shortfall and spawned a
        replacement — a duplicate kit and a lost purchase link, at 200, from one
        wrong cell in an otherwise pristine archive. The same cell in `kits.csv`
        alone was already a 409, because that line's quantity was never restated.

        Refused rather than kept, and the reason is the one `_resolve_all_refs`
        already gives for `replace_all`: the row said which line bought this kit,
        and dropping that on the floor loses provenance the operator never agreed
        to lose. A blank cell is the instruction to detach; an id the importer
        cannot read is not the same instruction wearing a different value. #82's
        test drove only the create, so this state was never varied.

        Runs inside `_classify`, after matching and before the change diff, and
        only ever fires against a stored non-null value: a create has no link to
        lose and keeps #82's behaviour exactly.
        """
        for column_name, (table, missing) in row.unresolved.items():
            if column_name not in row.present:
                continue
            column = spec.column(column_name)
            if column is None or column.get(row.target) is None:
                continue
            # The "imports without it" line was true when it was written and is
            # not any more; the error below is what the operator should read.
            told = _dangling_optional_message(column_name, table, missing)
            row.messages = [message for message in row.messages if message != told]
            row.action = RowAction.ERROR
            # "Leave the column out" rather than "leave the cell blank": omitting a
            # column always means "leave it as it is", while a blank means detach
            # for `order_item_id` and is itself refused for `catalog_ref_id`
            # (`_check_catalog_targets`), so only the first is a remedy for both.
            row.error = (
                f"{column_name}: no {table} here has id {missing}, and this row currently "
                f"points at {table} {column.get(row.target)} — an id that names nothing "
                "can't be what clears that link. Fix the id, or leave the column out of "
                "this sheet to keep the link as it is"
            )
            return True
        return False

    def _refuse_unfillable_creates(self, spec: TableSpec, row: _Row) -> None:
        """The create half of the same rule: nothing to fall back on, so say so.

        A new row missing a value its column requires has no stored value to keep
        and no default to take, so it can only be refused — but as a named row in
        the preview rather than as the `IntegrityError` it used to be.

        A column is fillable if the *schema* defaults it (`quantity_on_hand`,
        `status`, every `*_at`) or the importer does (`_COLUMN_DEFAULTS`, which
        carries the choices the schema has no opinion on, like a hand-written order
        line being allowed to omit its price). Reading the schema as well as the
        list is what closes this: `kits.created_at` and `kits.updated_at` have
        server defaults and were absent from the list, which is precisely why those
        two blanks were a 500 while the seven around them were not.
        """
        if row.action is not RowAction.CREATE:
            return
        supplied = _COLUMN_DEFAULTS.get(spec.key, {})
        for column in spec.columns:
            if column.name == "id" or not column.persisted:
                continue
            if row.values.get(column.name) is not None:
                continue
            if _column_is_nullable(spec, column.name) or column.name in supplied:
                continue
            if _column_has_own_default(spec, column.name):
                continue
            row.action = RowAction.ERROR
            row.error = (
                f"{column.name}: a new {spec.key} row needs this, and this one has no value "
                "for it. Fill the column in"
            )
            # Take the id back. `_classify` mints `new_id` into `created_ids` before
            # this runs, and every later table resolves references through that set —
            # so a refused order stayed resolvable, its lines planned as clean
            # creates, and the fan-out promised kits for an order that was never
            # going to exist. The apply was safe (the blocking error stops it) but
            # the preview was not, which is #86's "refusal ordered after the thing it
            # refuses" arriving here by another road (external review of #89).
            if row.new_id is not None:
                self.created_ids[spec.key].discard(row.new_id)
                # The `discard` is the load-bearing half; clearing `new_id` is
                # measured dead for outcomes — `_claim_identity` returns on ERROR
                # before it reads the field, and `_plan_fingerprint` handles a
                # minted id either way (external review of #89, round two, which
                # ran both mutants). Kept anyway, and this is the difference from
                # the four conditions removed on #86 for being dead: those were
                # *decisions* with a covering condition left in place, so removing
                # them left nothing stale behind. This is *state* — an ERROR row
                # holding a minted id nobody will create is a trap laid for the
                # next person who reads `new_id` without checking `action`.
                row.new_id = None
            return

    def _classify(self, spec: TableSpec, row: _Row) -> None:
        if row.action is RowAction.ERROR:
            return
        if row.matched_id is None:
            row.action = RowAction.CREATE
            row.new_id = row.values.get("id") or uuid.uuid4()
            self.created_ids[spec.key].add(row.new_id)
            return

        source_id = row.values.get("id")
        if source_id is not None and source_id != row.matched_id:
            self.remap[(spec.key, source_id)] = row.matched_id

        if self.mode is ImportMode.ADD_ONLY:
            row.action = RowAction.SKIP
            return

        _defer_filled_money_currency(spec, row)
        # Order matters, and only one of the two is honest. `_defer_generated_status
        # _stamp` takes `status_updated_at` out of `present` when the row moves a
        # kit's status without saying when, so the apply can stamp the clock;
        # `_keep_stored_where_unstatable` then finds nothing to keep and says
        # nothing. The other order has keep-stored claim the column was "left as it
        # was" *and* the deferral stamp it anyway — a preview that contradicts
        # itself and then contradicts the outcome. Neither branch could see this on
        # its own; it was found by reading both trees at once during #89's review.
        self._defer_generated_status_stamp(spec, row)
        self._keep_stored_where_unstatable(spec, row)
        if self._refuse_unresolved_overwrite(spec, row):
            return

        changes = []
        for column in spec.columns:
            if column.name == "id" or not column.persisted or column.name not in row.present:
                continue
            new_value = row.values.get(column.name)
            old_value = column.get(row.target)
            if render(old_value) != render(new_value):
                changes.append(
                    FieldChange(
                        field=column.name, before=render(old_value), after=render(new_value)
                    )
                )
        row.changes = changes
        row.action = RowAction.UPDATE if changes else RowAction.UNCHANGED

    def _classify_singleton(self, spec: TableSpec, row: _Row) -> None:
        """A singleton (#23) has exactly one fate: update the row migrations made.

        Not a create — the stored row always exists, and the table's CHECK holds
        it to one — and not a delete, in any mode. `_classify` then answers the
        rest: add_only skips it, a diff becomes an UPDATE the preview shows
        field-by-field, and a second row in the file dies on `_claim_identity`
        because both resolve to the same target.
        """
        if row.action is RowAction.ERROR:
            return
        if row.target is None:
            row.action = RowAction.ERROR
            row.error = (
                f"this instance holds no {spec.key} row to update — migrations "
                "create it; run `alembic upgrade head` before importing"
            )
            return
        self._classify(spec, row)

    def _defer_generated_status_stamp(self, spec: TableSpec, row: _Row) -> None:
        """A kit whose status this sheet moves, without the sheet saying when (#44
        case 5).

        `update_kit` stamps `status_updated_at` on every status change, because the
        board's "most recently moved" ordering is read off it. The importer assigns
        `status` directly, so a merge that moved a kit from `ordered` to `building`
        left the timestamp reading whenever it last moved for real — the board
        silently lied about it, and the further back the original move was, the
        further from the truth.

        Deferred rather than filled in here: the value is `datetime.now(UTC)`, and
        `_plan_fingerprint` hashes every value in `row.present`. A clock reading in
        the plan is a different hash on every pass, so preview and apply could
        never agree and every status-moving import would 409. What the plan carries
        instead is the *absence* — the column is dropped from `present`, which is
        the instruction `_stamp_generated_status_changes` reads at write time. The
        drop is deterministic from the sheet and the stored row, so the hash is
        stable, and it still moves the moment the stored status changes underneath
        a preview, which is exactly when it should.

        Dropping it also settles a blank cell, which the export template ships and
        a hand-edited archive is full of. `status_updated_at` is NOT NULL, so
        writing the blank through was an IntegrityError — a 500 out of the apply,
        on the same row that needed a generated timestamp anyway.

        An explicit timestamp always wins. A sheet that states both a status and a
        time is describing a move it knows about, and inventing one over the top of
        that is the same "config never overwrites a record" mistake `§6` keeps out
        of money.
        """
        if spec.key != "kits" or row.target is None or "status" not in row.present:
            return
        if render(row.values.get("status")) == render(row.target.status):
            return
        if row.values.get("status_updated_at") is not None:
            return
        row.present.discard("status_updated_at")
        row.messages.append(
            "status_updated_at will be set to the time of this import — this row moves "
            "the status without saying when it moved"
        )

    # -- the main pass ---------------------------------------------------------

    async def build(self) -> ExecutionPlan:
        await self.load_existing()
        replace_all = self.mode is ImportMode.REPLACE_ALL

        # Order matching needs the incoming lines, which live in a table processed
        # later — group them up front.
        #
        # `_apply_money_alternates` runs here too, and has to: it is what turns a
        # sheet's major-unit `unit_price` into the `unit_price_minor` the
        # fingerprint reads, and the *stored* side of that comparison is always in
        # minor units. Parsing alone left a row that wrote only `unit_price` with
        # `unit_price_minor` still None, fingerprinting as 0 against a stored 2450,
        # so the "retailer + date + lines" fallback silently failed to match and
        # the order was re-created rather than updated. The row built here is a
        # throwaway used for its values — any error it raises is reported by the
        # real pass below, which parses the same row again.
        incoming_lines: dict[uuid.UUID, list[dict]] = {}
        line_spec = SPEC_BY_KEY["order_items"]
        for raw in self.upload.tables.get("order_items", []):
            parsed = self._parse_row(line_spec, raw)
            self._apply_money_alternates(line_spec, parsed)
            order_id = parsed.values.get("order_id")
            if order_id is not None:
                incoming_lines.setdefault(order_id, []).append(parsed.values)

        for spec in TABLE_SPECS:
            raw_rows = self.upload.tables.get(spec.key, [])
            planned = self.rows.setdefault(spec.key, [])
            for raw in raw_rows:
                row = self._parse_row(spec, raw)
                self._check_line_quantity(spec, row)
                self._resolve_all_refs(spec, row, replace_all)
                self._apply_money_alternates(spec, row)
                _clear_orphan_money_currency(spec, row)
                # Before matching: a row that duplicates a file id must not reach
                # `_classify` and leave a `remap` entry behind it.
                self._claim_source_id(spec, row)

                if (not replace_all or spec.singleton) and row.action is not RowAction.ERROR:
                    if spec.key == "orders":
                        self._match_order(row, incoming_lines)
                    elif spec.key == "order_items":
                        self._match_order_item(row)
                    else:
                        self._match_generic(spec, row)

                if spec.singleton:
                    # A singleton is only ever updated: replace_all does not
                    # truncate it, so the CREATE branch below would try to insert
                    # a second row into a table whose CHECK allows one (#23).
                    self._classify_singleton(spec, row)
                elif replace_all:
                    if row.action is not RowAction.ERROR:
                        row.action = RowAction.CREATE
                        row.new_id = row.values.get("id") or uuid.uuid4()
                        self.created_ids[spec.key].add(row.new_id)
                else:
                    self._classify(spec, row)

                # Both modes: a create carries no stored value to fall back on, so
                # a column the database requires and nothing supplies is refused
                # here rather than at flush (#88).
                self._refuse_unfillable_creates(spec, row)

                self._claim_identity(spec, row)
                self._annotate(spec, row, replace_all)
                planned.append(row)

        # Before the fan-out, not after: a line this refuses must not also
        # contribute a spawn or a removal to the plan the operator is shown (#44).
        invariants.check(
            self.rows,
            by_id=self.by_id,
            created_ids=self.created_ids,
            replace_all=replace_all,
        )
        # After the invariants (a row they refuse must not fold) and before the
        # plan is finished, so the fingerprint hashes the folded values (#130, P2-3).
        self._fold_new_categories(replace_all)
        self._plan_spawns(replace_all)
        # The aggregate mate of the per-line ceiling `_check_line_quantity`
        # enforces (#77): every line can be individually legal while the plan as
        # a whole derives an absurd number of kits — the reachable total was
        # MAX_ROWS × MAX_LINE_QUANTITY. Counts *spawns*, not stated quantities,
        # so a full-archive restore of any size stays importable: its kits are
        # explicit rows, spawn nothing, and answer to MAX_ROWS instead. Blocking
        # rather than a row error because no single row is wrong — and blocking
        # at preview is also the apply refusal, since apply re-plans and rejects
        # a plan holding blocking errors before the hash check.
        try:
            require_total_fanout(
                sum(spawn.count for spawn in self.spawns),
                label="the kits this import would create from order lines",
            )
        except InvalidInputError as exc:
            self.blocking.append(str(exc))
        self._plan_advances()
        return self._finish()

    def _check_line_quantity(self, spec: TableSpec, row: _Row) -> None:
        """The fan-out ceiling, as a row diagnostic rather than a raised error.

        `spawn_kits` enforces the same limit, but reaching it means the whole upload
        dies on one cell with no line number attached. An import's contract is that a
        bad row is named in the preview alongside the good ones (#43), so the ceiling
        is asked about here — from the service that owns it, not a second copy of the
        number — and answered as a row error.
        """
        if spec.key != "order_items" or row.action is RowAction.ERROR:
            return
        quantity = row.values.get("quantity")
        if not isinstance(quantity, int):
            return  # absent, blank, or already reported as unparseable
        try:
            require_line_quantity(quantity)
        except InvalidInputError as exc:
            row.action = RowAction.ERROR
            row.error = str(exc)

    def _resolve_all_refs(self, spec: TableSpec, row: _Row, replace_all: bool) -> None:
        if row.action is RowAction.ERROR:
            return
        for column in spec.columns:
            if column.role is not ColumnRole.REF:
                continue
            dangling = self._resolve_ref(row, spec, column, replace_all)
            if row.values.get(column.name) is not None:
                continue
            if replace_all and dangling is not None:
                # Named a row this upload doesn't contain. Blocked rather than
                # nulled even where the column is optional: the row said which
                # order line bought this kit, and quietly dropping that on the
                # floor loses provenance the operator never agreed to lose.
                target, missing = dangling
                fix = f"add that {target} row"
                alt = self._alt_for(spec, column)
                if alt is not None:
                    fix += f", or name it in {alt.name} and one will be created"
                row.action = RowAction.ERROR
                row.error = (
                    f"{column.name}: no {target} row with id {missing} in this upload — "
                    f"a replace-all import deletes everything the upload doesn't "
                    f"contain, so {fix}"
                )
            elif column.required:
                row.action = RowAction.ERROR
                target = column.ref_table
                row.error = (
                    f"{column.name}: no matching {target} found — "
                    "add it to the import or fix the reference"
                )
            elif dangling is not None and _column_is_nullable(spec, column.name):
                # Optional, **and able to hold null** — the id named nothing here or
                # in the upload, and dropping it is what will actually happen (#82).
                #
                # The nullability half is not decoration. `orders.retailer_id` is
                # optional in the sheet (it has `retailer_name`) and NOT NULL in the
                # database, so without it both rules fired and contradicted each
                # other: this message said the row "imports without it" while
                # `_keep_stored_where_unstatable` quietly kept the stored shop, or
                # `_refuse_unfillable_creates` refused the row outright. Telling the
                # operator a link was lost, and to go and add a shop, was simply
                # untrue (external review of #89).
                # Not blocked: "import just kits.csv into a fresh instance" is a
                # documented onboarding path, and every row of that file names an
                # order line the new instance has never had. But it is not silent
                # either — the operator filled the cell in, and it is being
                # discarded. Said per row rather than as a summary, because which
                # rows lost their link is the part a count cannot give back.
                target, missing = dangling
                row.unresolved[column.name] = dangling
                row.messages.append(_dangling_optional_message(column.name, target, missing))

    def _apply_money_alternates(self, spec: TableSpec, row: _Row) -> None:
        """Major units fill in only where the canonical minor-unit column is absent
        or blank — §6 keeps integer minor units authoritative.

        This is the **second** way a value reaches an int4 money column, and it does
        not pass through `parse_int`: three ALT_MONEY columns scale a major-unit
        amount into `*_minor` here instead. So the range has to be re-checked on the
        product — the scaling is what breaks the bound, since a major amount well
        inside int4 is a hundred or a thousand times larger once counted in minor
        units. Without this a large `unit_price` was an IntegrityError at flush,
        which is a 500 rather than a row diagnostic (#43).

        It is also where a **lone grouped amount** is settled. `1,234` is valid
        grouping and an equally valid European spelling of `1.234`, and the two are a
        thousand apart — `1,234` KWD is either 1,234,000 fils or the 1234 fils that
        §6 exists over. Only the currency can decide, and only in one direction: where
        it has no minor unit there is nowhere for a decimal reading to land, so
        `1,234` JPY is unambiguously ¥1234. Everywhere else it is refused rather than
        guessed at. Making the sheet's numeric locale explicit is the real answer and
        belongs with the import diagnostics work in M5.1.
        """
        for column in spec.columns:
            if column.role is not ColumnRole.ALT_MONEY:
                continue
            if row.values.get(column.mirrors) is not None:
                continue
            major = row.values.get(column.name)
            if major is None:
                continue
            code = row.values.get(column.currency_column)
            if column.name in row.lone_grouped and minor_fraction_digits(code) != 0:
                row.action = RowAction.ERROR
                row.error = (
                    f"{column.name}: a comma is ambiguous in {code or 'this currency'} — "
                    f"this cell reads as {render(major)} if the comma groups thousands, "
                    f"or {major / 1000} if it is a decimal point. Write it with a decimal "
                    "point, or with no separator at all."
                )
                continue
            try:
                minor = require_int4(major_to_minor(major, code), f"{column.name}: '{major}'")
                row.values[column.mirrors] = minor
                row.present.add(column.mirrors)
            except (ArithmeticError, ValueError) as exc:
                row.action = RowAction.ERROR
                row.error = f"{column.name}: {exc}"

    def _warn_unknown_currency(self, spec: TableSpec, row: _Row) -> None:
        """A code outside ISO 4217 is stored as typed, with its decimals guessed.

        Accepting it is deliberate: an instance already holding an obscure code
        should not be locked out of its own archive. But two decimal places is then
        an assumption rather than a fact, and a mistyped code is indistinguishable
        from a real one — so the preview says so out loud, while the human looking
        at it can still fix a typo for free.
        """
        for column in spec.columns:
            if column.parse is not parse_currency:
                continue
            code = row.values.get(column.name)
            if code and not is_known_currency(code):
                row.messages.append(
                    f"{column.name}: '{code}' isn't a currency code we recognise — it will be "
                    "stored as typed, and its amounts read as having 2 decimal places"
                )

    def _annotate(self, spec: TableSpec, row: _Row, replace_all: bool) -> None:
        """Warnings that need a human eye rather than blocking the import."""
        if row.action is RowAction.ERROR:
            return
        # Not gated on `replace_all` below: a guessed exponent is worth saying
        # whether the row is landing in an empty instance or an existing one.
        self._warn_unknown_currency(spec, row)
        if replace_all:
            # Everything existing is deleted first, so "you already have one of
            # these" is not only useless here, it's actively misleading.
            return
        if spec.key == "kits" and row.action is RowAction.CREATE:
            name = _norm_name(row.values.get("name"))
            if not name:
                return
            same = sum(1 for kit in self.existing["kits"] if _norm_name(kit.name) == name)
            if same:
                row.messages.append(
                    f"you already have {same} kit(s) called '{row.values.get('name')}' — "
                    "importing adds another, since two of the same kit are two kits"
                )

    def _fold_new_categories(self, replace_all: bool) -> None:
        """#127's canonicalisation, for the importer's one honest case (#130, P2-3).

        An id-less row classified CREATE states no prior spelling to preserve — the
        row exists only after apply, and the first export records whatever this
        writes — so it folds onto the vocabulary like every live writer. Everything
        that *restores* stays verbatim: an UPDATE and an id-bearing
        create-is-a-restore each assert a stored fact, and rewriting one would make
        a re-imported archive a rewrite (rule 10 by analogy). Stubs fold too —
        `synthetic_id` marks an id this plan minted rather than one the upload
        stated.

        Folded in Python (`strip().lower()`), the importer's own key (`_norm_name`,
        §12.4), not the live writers' Postgres fold. Plan-time on purpose: the
        folded value lands in `row.values`, so the fingerprint binds it and apply
        writes exactly what was planned — a spelling landing between preview and
        apply stales the hash instead of silently changing the outcome (#86 round
        5's rule).

        The vocabulary consulted is the **effective post-write multiset** (#130
        round 2, P2-5) — what each key's spellings will be AFTER this plan
        applies, not before, and counted rather than first-seen:

        * a stored row an UPDATE in this upload rewrites votes with the spelling
          it will hold, not the one the import is erasing;
        * under replace_all the stored rows are doomed, so only the upload's own
          verbatim rows vote;
        * every verbatim row is a vote in a multiset — the winner is the same
          most-frequent / byte-order pick `canonical_category` makes, so sheet
          order cannot decide a spelling.

        Only a key nothing verbatim holds falls back to first-claim among the
        fold-eligible creates themselves — there any deterministic pick is
        equally right, and a create's own stated spelling should not be rewritten
        by a later row.
        """

        def stated_category(row: _Row) -> str | None:
            value = row.values.get("category")
            if isinstance(value, str) and value.strip():
                return value.strip()
            return None

        def folds(row: _Row) -> bool:
            return row.action is RowAction.CREATE and (
                row.synthetic_id or row.values.get("id") is None
            )

        for spec in TABLE_SPECS:
            if "category" not in spec.model.__table__.columns:
                continue
            rows = self.rows.get(spec.key, [])
            if not rows:
                continue

            # Overlay: the spelling each targeted stored row will hold after this
            # plan. An UPDATE that does not state a category leaves the stored
            # spelling in place, so only `present` columns overlay.
            overlays: dict[uuid.UUID, str | None] = {}
            for row in rows:
                if row.action is RowAction.UPDATE and row.matched_id is not None:
                    if "category" in row.present:
                        overlays[row.matched_id] = stated_category(row)

            spellings: dict[str, Counter[str]] = defaultdict(Counter)
            if not replace_all:
                for instance in self.existing[spec.key]:
                    if instance.id in overlays:
                        effective = overlays[instance.id]
                    else:
                        effective = (instance.category or "").strip() or None
                    if effective:
                        spellings[effective.lower()][effective] += 1
            for row in rows:
                if row.action is RowAction.CREATE and not folds(row):
                    # An id-bearing create-is-a-restore votes; UPDATEs already
                    # voted through the overlay of the row they rewrite.
                    value = stated_category(row)
                    if value is not None:
                        spellings[value.lower()][value] += 1

            vocab = {
                # Most frequent, ties by byte order — `canonical_category`'s pick,
                # computed over the same trimmed spellings.
                key: min(counted.items(), key=lambda item: (-item[1], item[0]))[0]
                for key, counted in spellings.items()
            }

            for row in rows:
                if not folds(row):
                    continue
                value = stated_category(row)
                if value is None:
                    continue
                key = value.lower()
                if key not in vocab:
                    vocab[key] = value
                elif vocab[key] != value:
                    row.values["category"] = vocab[key]
                    row.messages.append(
                        f"category '{value}' will be stored as '{vocab[key]}', "
                        "matching the spelling already in use"
                    )

    def _order_instant(self, order_id: uuid.UUID, column: str) -> datetime | None:
        """The post-write value of one of an order's timeline instants
        (`received_at`, `shipped_at`) — null when it will be unset — so a
        spawned kit lands in the right status instead of always
        `initial_kit_status`'s default of "still on the way" (#47), and carries
        the right `status_updated_at` (#93, #95). Checks this import's own
        orders rows first — covering both a freshly created order and an
        existing one this import updates — and falls back to the persisted row
        for an order the upload doesn't touch at all.

        Resolved at *plan* time and carried on `_Spawn`, so the instant a spawn
        will stamp is part of the plan the fingerprint binds: a correction
        landing between preview and apply changes the re-plan's hash and the
        stale apply 409s, instead of stamping a value the operator never saw
        (Codex round five, P3).
        """
        for row in self.rows.get("orders", []):
            candidate = row.new_id if row.action is RowAction.CREATE else row.matched_id
            if candidate != order_id:
                continue
            # Only a row that will actually be written can answer from the file —
            # `add_only` deliberately leaves a matched order untouched (SKIP), so
            # its uploaded cell describes nothing that will land.
            writes = row.action in (RowAction.CREATE, RowAction.UPDATE)
            if writes and column in row.present:
                return row.values.get(column)
            if row.target is not None:
                return getattr(row.target, column)
            return None
        existing = self.by_id["orders"].get(order_id)
        return getattr(existing, column) if existing is not None else None

    def _order_receipt(self, order_id: uuid.UUID) -> datetime | None:
        return self._order_instant(order_id, "received_at")

    def _order_shipment(self, order_id: uuid.UUID) -> datetime | None:
        return self._order_instant(order_id, "shipped_at")

    def _attached_after(
        self, line_id: uuid.UUID, stored: list[Kit], kit_rows: list[_Row]
    ) -> list[Kit]:
        """The kits this line will hold once the upload lands — not the ones it holds
        now.

        `kits.order_item_id` is an ordinary REF column, so the same upload that
        states a line's quantity can also move kits onto or off that line. Counting
        `len(row.target.kits)` reads the database *before* those writes, and the
        fan-out arithmetic on both sides of it is then answering about a state that
        will not exist by the time it is applied. Measured on the first cut of this
        branch: a `kits.csv` row attaching a loose kit to a two-kit line applied at
        200 and left the line saying 2 with three kits on it, planning neither a
        spawn nor a removal — case 2's own disagreement, reached through the kits
        table instead of the order_items one, and invisible to a reconciliation that
        counts stored rows.

        So the count is taken over the post-write set: stored kits the upload does
        not move away, plus stored kits it moves in from elsewhere. A row has to
        carry `order_item_id` to move anything — one that never mentions the column
        leaves the kit where it is, which is the ordinary partial-sheet case and the
        reason this reads `present` rather than values alone.

        Takes `stored` rather than reading an order-item row, because a line the
        upload *creates* has no stored kits and can still be moved onto: an
        `order_items.csv` create plus a `kits.csv` update pointing an existing kit
        at it supplies that line's kit, and `covered` cannot see it because
        `covered` counts kit *creates*. Reading `row.target is None` as "nothing is
        attached" spawned a second kit for a quantity-one line (external review of
        #86). The `kept` half is genuinely empty there; the `arriving` half is not.

        Empty under `replace_all` without saying so: everything is truncated first,
        `stored` is `[]`, and every kits row is a create with no `matched_id`, so
        both loops below produce nothing. An explicit mode guard here would be one
        no mutation of it could ever kill.
        """
        # kit id -> (post-write parent line, the stored Kit)
        reparented: dict[uuid.UUID, tuple[Any, Kit]] = {}
        for kit_row in kit_rows:
            if kit_row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            if kit_row.matched_id is None or kit_row.target is None:
                continue
            if "order_item_id" not in kit_row.present:
                continue
            reparented[kit_row.matched_id] = (kit_row.values.get("order_item_id"), kit_row.target)

        on_line = {kit.id for kit in stored}
        kept = [kit for kit in stored if reparented.get(kit.id, (line_id, kit))[0] == line_id]
        arriving = [
            kit
            for kit_id, (parent, kit) in reparented.items()
            if parent == line_id and kit_id not in on_line
        ]
        return kept + arriving

    @staticmethod
    def _stated_quantity(row: _Row) -> int | None:
        """The quantity this row *says*, or None where it says nothing.

        A sheet may name a line and leave `quantity` out — `required` only bites on
        a blank cell in a column the file carries, not on an absent column. That is
        the difference between an instruction and a silence, and reading
        `values.get("quantity") or 0` collapses the two: zero asks for nothing
        counting upward and for everything counting downward.
        """
        stated = row.values.get("quantity") if "quantity" in row.present else None
        return stated if isinstance(stated, int) else None

    @staticmethod
    def _writes_quantity(row: _Row) -> bool:
        """Whether this upload *writes* the line's quantity: a create, or an update
        whose `quantity` is among its changes. A row that merely restates the
        stored number — every line of a full archive — describes the line and
        instructs nothing; a row with no `quantity` column has no change to carry
        and is covered by the same test."""
        if row.action is RowAction.CREATE:
            return True
        return any(change.field == "quantity" for change in row.changes)

    def _reconcilable_lines(self) -> set[uuid.UUID]:
        """The lines this upload *authorises* the fan-out to reconcile.

        A line qualifies only if it will be written, is a kit line, and **writes**
        its quantity — a create, or an update that changes it. That is what
        "reconcile" means here: the number of kits a line holds is brought to the
        number this upload says it bought, by spawning or by deleting, so the
        authority to do that has to come from a quantity the operator put in this
        file. Two readings were tried and retired:

        * *visited* — a set filled as a side effect of the fan-out loop, so a
          partial `order_items.csv` naming a line without a `quantity` column was
          "reconciled" and a kits row moving alongside it applied at 200 in either
          direction (external review of #86);
        * *stated* — any row carrying a quantity, changed or not. Every full
          archive restates every line, so an unchanged row was what turned a
          refused kit move into a delete: `kits.csv` alone moving a kit onto a
          quantity-one line was a 409, and the same move beside the archive's own
          unchanged `order_items.csv` deleted the incumbent (announced, at 200).
          A restated line is a description, not an instruction, and rule 10 wants
          a re-imported archive to be a no-op whatever the collection holds.

        A kit move against a line this upload does not authorise is
        `_refuse_unreconciled_kit_moves`'s to refuse — with the stated quantity
        named, so the operator can say what the line should now hold.
        """
        lines: set[uuid.UUID] = set()
        for row in self.rows.get("order_items", []):
            if row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            # The *effective* type, from the shared reading in `invariants`: an
            # update may legitimately omit `item_type`, and testing `values` alone
            # read every such row as typeless and skipped reconciliation entirely.
            if invariants.effective_item_type(row) is not ItemType.KIT:
                continue
            if not self._writes_quantity(row):
                continue
            line_id = row.matched_id or row.new_id
            if line_id is not None:
                lines.add(line_id)
        return lines

    def _protected_kits(self) -> set[uuid.UUID]:
        """Every kit that will carry progression evidence once this upload lands.

        `kit_progressed` is the shared predicate (rule 1) and it reads a *stored*
        row: status, rating, photos, applied upgrades. That is the whole truth for
        the Orders page, which mutates one thing at a time. It is only part of the
        truth for an import, which writes the kit, its status and its children in
        one transaction — and both halves of that gap were reachable (external
        review of #86, round three):

        * a `kits.csv` row promoting a kit to `building` in the same upload that
          strips its purchase provenance;
        * an `upgrade_applications.csv` or `kit_photos.csv` row creating a child for
          the very kit `_plan_removals` had already picked as its victim. The child
          was created during the table loop and cascaded away with its kit
          moments later, so the result counted a create that a later export could
          not find — and for an application that is consumed stock with nothing
          left to explain it.

        The union of stored and planned evidence, never the difference. A sheet
        that *lowers* a kit out of `building` does not thereby unprotect it: an
        upload being able to talk itself out of a guard is the shape of every
        bypass on this branch, and the cost of being conservative is a refusal the
        operator can lift by editing one cell.
        """
        protected = {kit.id for kit in self.existing["kits"] if kit_progressed(kit)}

        for row in self.rows.get("kits", []):
            if row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            kit_id = row.matched_id or row.new_id
            if kit_id is None:
                continue
            status = row.values.get("status") if "status" in row.present else None
            if status is not None and KitStatus(status) in PROGRESSED_STATUSES:
                protected.add(kit_id)
            if "rating" in row.present and row.values.get("rating") is not None:
                protected.add(kit_id)

        # Every child row that will be written, at the kit it will be written
        # *to* — not only the creates. `upgrade_applications.kit_id` and
        # `kit_photos.kit_id` are ordinary REF columns, so an update can carry an
        # existing child from one kit to another, and the kit it arrives at gains
        # exactly the evidence a create would have given it. Reading `CREATE` alone
        # let the arrival be chosen as a removal victim: the child moved onto it
        # and was cascaded away with it, leaving an upgrade's stock spent with no
        # application left to explain it (external review of #86, round four).
        #
        # The kit a child *leaves* stays protected by the stored evidence above.
        # That is conservative and deliberate — see the union rule in the paragraph
        # before this one.
        for table in ("upgrade_applications", "kit_photos"):
            for row in self.rows.get(table, []):
                if row.action in (RowAction.ERROR, RowAction.SKIP):
                    continue
                # Only what the row *states*. A child row that doesn't restate
                # `kit_id` leaves the child where it is, and that kit already
                # carries it as stored evidence in the first line of this
                # function — a fallback to `row.target.kit_id` sat here and was
                # removed as dead: no mutation of it could change an outcome.
                kit_id = row.values.get("kit_id") if "kit_id" in row.present else None
                if kit_id is not None:
                    protected.add(kit_id)
        return protected

    def _refuse_stripping_protected_provenance(
        self, kit_rows: list[_Row], protected: set[uuid.UUID]
    ) -> None:
        """A protected kit keeps the order line that bought it.

        The count check asks whether a line ends up holding the right number of
        kits. A *swap* satisfies it perfectly — detach one kit, attach another, one
        in and one out — while the kit that left takes its purchase record with it.
        That record is what `delete_order` reads to refuse, so an order holding a
        `building` kit went from a 409 before the import to a **204** after it
        (external review of #86, round three).

        Moving a protected kit to a different line is the same bypass wearing a
        different hat — the guard follows the kit and the original order becomes
        deletable — so the test is "the link changed", not "the link was cleared".

        `KitUpdate` exposes no `order_item_id` at all, so neither REST nor MCP can
        reach this; the importer was the only writer that could.
        """
        for row in kit_rows:
            if row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            if row.matched_id is None or row.target is None:
                continue
            if "order_item_id" not in row.present:
                continue
            before = row.target.order_item_id
            if before is None or row.values.get("order_item_id") == before:
                continue
            if row.matched_id not in protected:
                continue
            row.action = RowAction.ERROR
            row.error = (
                "order_item_id: this kit is building or complete, rated, photographed, or has "
                "upgrades applied to it, so the order line that bought it is what stops that "
                "order being deleted out from under it. An import can't take that link away — "
                "leave order_item_id as it is"
            )

    def _planned_line(self, line_id: uuid.UUID) -> _Row | None:
        """The order-items row this upload will write for `line_id`, if any.

        `SKIP` deliberately doesn't count: `add_only` leaves the stored line exactly
        as it is, so the stored row — not the uploaded one — is what describes it
        afterwards.
        """
        for row in self.rows.get("order_items", []):
            if row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            if (row.matched_id or row.new_id) == line_id:
                return row
        return None

    def _plan_spawns(self, replace_all: bool) -> None:
        """Hybrid dispatch: a kit line spawns only the kits nothing else provides,
        and gives up the kits its quantity no longer accounts for."""
        kit_rows = self.rows.get("kits", [])
        reconciled = self._reconcilable_lines()
        protected = self._protected_kits()

        # Refusals first, and the ordering is load-bearing. A kit move refused
        # below still contributed to the post-write set while the fan-out ran
        # ahead of it, so a removal derived from a move that will never happen
        # stayed in the plan: the preview promised `kits_removed: 1` and the apply
        # 409'd and removed nothing (external review of #86). Erroring the kits row
        # first takes it out of `_attached_after`, and the surplus it invented
        # stops existing rather than being cleaned up afterwards.
        self._refuse_stripping_protected_provenance(kit_rows, protected)
        self._refuse_unreconciled_kit_moves(kit_rows, reconciled, replace_all)

        for row in self.rows.get("order_items", []):
            line_id = row.matched_id or row.new_id
            if line_id is None or line_id not in reconciled:
                continue

            covered = sum(
                1
                for kit in kit_rows
                if kit.action is RowAction.CREATE and kit.values.get("order_item_id") == line_id
            )
            stored = list(row.target.kits) if row.target is not None else []
            attached = self._attached_after(line_id, stored, kit_rows)
            wanted = self._stated_quantity(row) or 0
            missing = wanted - covered - len(attached)
            if missing < 0:
                self._plan_removals(
                    row,
                    surplus=-missing,
                    kit_rows=kit_rows,
                    attached=attached,
                    protected=protected,
                )
                continue
            if missing == 0:
                continue

            name = row.values.get("kit_name")
            grade = row.values.get("kit_grade")
            if not name or not grade:
                row.action = RowAction.ERROR
                row.error = (
                    f"this kit line needs {missing} more kit(s), but has no kit_name/kit_grade "
                    "to create them from — fill those in, or supply the kits in kits.csv"
                )
                continue
            status = row.values.get("kit_status")
            # order_id is a required REF, already validated by `_resolve_all_refs` —
            # a row that reached here without one would already be RowAction.ERROR.
            order_id = row.values["order_id"]
            receipt = self._order_receipt(order_id)
            self.spawns.append(
                _Spawn(
                    order_item_id=line_id,
                    order_id=order_id,
                    count=missing,
                    name=name,
                    grade=grade,
                    scale=row.values.get("kit_scale"),
                    kit_number=row.values.get("kit_number"),
                    status=str(status) if status else "",
                    row_number=row.row_number,
                    received=receipt is not None,
                    received_at=receipt,
                    shipped_at=self._order_shipment(order_id),
                )
            )
            row.messages.append(f"will create {missing} kit(s) from this line")

    def _refuse_unreconciled_kit_moves(
        self, kit_rows: list[_Row], reconciled: set[uuid.UUID], replace_all: bool
    ) -> None:
        """A kits-side write may not leave a line disagreeing with its own quantity.

        The loop above visits the lines this upload *writes a quantity for*. A
        `kits.csv` row writing `order_item_id` changes what a line holds without
        being one of those, so a line reached only from the kits side was never
        reconciled at all — two shapes, both a clean preview and a 200 (external
        review of #86):

            add_only, line quantity 1: its own order_items row is SKIP, so the loop
            above skips it, while a new kits.csv row attaches a second kit
                -> quantity 1, two kits attached

            merge, kits.csv only: an update blanks a spawned kit's order_item_id
                -> quantity 1, no kits attached

        **Refused rather than reconciled**, and the distinction is whose instruction
        it is. The fan-out spawns and removes because *the line wrote a quantity* —
        that is what a quantity means. A kits row moving provenance says nothing
        about how many kits the line bought, so conjuring a replacement kit or
        deleting a real one on the strength of it would be inventing intent the file
        never expressed. It would also make `add_only` delete, which is the one
        thing that mode promises never to do. So the upload is told it contradicts
        itself, and the operator settles it by saying both halves out loud.

        A line the upload *does* authorise — writes its quantity, see
        `_reconcilable_lines` — is not checked here; the fan-out reconciles it,
        from the same post-write set. A line whose row is present but leaves the
        quantity as it is falls to this check like an absent one, and the message
        says so, because "restated" and "absent" call for different edits.

        **The stored row is consulted only in merge.** An earlier cut argued that
        `replace_all` could never reach it, because every line in that mode is
        created by the upload and therefore reconciled. That was wrong, and wrong
        in the direction that corrupts: a *non-kit* line leaves the fan-out before
        it is ever marked reconciled, so an upload reusing a stored kit line's uuid
        for a tool line looked the line up in `by_id` — rows `TRUNCATE` is about to
        remove — and read their kits. The same upload previewed as two errors with
        the stored order present and cleanly without it (#45's rule, external
        review of #86). Under `replace_all` the upload is the only world there is,
        and a kits row naming a line it doesn't contain is already a `_resolve_ref`
        error.

        **A kit's provenance has to be a kit line.** A non-kit line is refused here
        rather than skipped: `kits.order_item_id` records which order line bought
        the kit, and a paint line never bought one. §3.9 gives catalog lines a
        different dispatch entirely, REST and MCP expose no way to write the column
        at all, and skipping the case left the importer the only writer in the
        application that could attach a kit to a consumable (external review of
        #86).
        """
        touched: dict[uuid.UUID, list[_Row]] = {}
        for kit_row in kit_rows:
            if kit_row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            if "order_item_id" not in kit_row.present:
                continue
            after_line = kit_row.values.get("order_item_id")
            before_line = kit_row.target.order_item_id if kit_row.target is not None else None
            # Only a *move*. A row restating the line its kit is already on — every
            # kits row of a full archive — changes what no line holds, and reading
            # it as a claim to check would refuse the re-import of an archive whose
            # collection had drifted before this rule existed (rule 10: a no-op).
            if after_line == before_line:
                continue
            # Both ends of the move: the line it lands on, and — for a row that
            # matched a stored kit — the one it leaves. Either can be left holding
            # the wrong number, and only one of them is named in the cell.
            for line_id in (before_line, after_line):
                if line_id is not None:
                    touched.setdefault(line_id, []).append(kit_row)

        for line_id, rows in touched.items():
            if line_id in reconciled:
                continue
            planned = self._planned_line(line_id)
            # `replace_all` truncates every stored row before this plan is written,
            # so in that mode the upload is the only source of truth about a line.
            #
            # **Currently shadowed, and kept anyway.** Since #82/#88 landed, a create
            # missing a NOT NULL column is refused and has its id retracted from
            # `created_ids` — so under `replace_all` a kits row naming such a line
            # fails #45's dangling check first and never reaches here, and a line
            # that *was* created has a quantity and is therefore reconciled. No
            # input found that reaches this expression with `replace_all` true.
            #
            # It stays because removing it would move the protection into a rule in
            # another module that exists for unrelated reasons. That is the
            # difference from the conditions deleted elsewhere on this branch for
            # being dead: those left an equivalent test in the same function, this
            # would leave a #45 violation — reading rows `TRUNCATE` is about to
            # remove — one distant edit away. Its mutant is out of the harness for
            # the same reason: a case that can never be killed trains people to
            # ignore the report. The unreachability argument is reasoned, not
            # measured; it is on the list for the next review.
            stored = None if replace_all else self.by_id["order_items"].get(line_id)

            if planned is not None:
                item_type = invariants.effective_item_type(planned)
            elif stored is not None:
                item_type = stored.item_type
            else:
                continue

            if item_type is not ItemType.KIT:
                self._error_rows(
                    rows,
                    f"order_item_id: order line {line_id} is a {item_type} line, and a kit's "
                    "order_item_id records which line bought it — a catalog line buys stock, "
                    "not kits. Point these kits at a kit line, or leave the column blank",
                )
                continue

            quantity = self._stated_quantity(planned) if planned is not None else None
            if quantity is None and stored is not None:
                quantity = stored.quantity
            stored_kits = list(stored.kits) if stored is not None else []
            created = sum(
                1
                for kit in kit_rows
                if kit.action is RowAction.CREATE and kit.values.get("order_item_id") == line_id
            )
            after = len(self._attached_after(line_id, stored_kits, kit_rows)) + created

            if quantity is None:
                self._error_rows(
                    rows,
                    f"order_item_id: this would leave order line {line_id} holding {after} "
                    "kit(s), and nothing in this upload says how many that line bought — its "
                    "order_items.csv row has no quantity column. State the quantity there, or "
                    "leave order_item_id as it is",
                )
            elif after != quantity and planned is not None:
                # The line's row is here and leaves its quantity as it is — a
                # restated archive line, or an edit to some other column. That
                # row describes the line; it does not authorise deleting or
                # spawning kits to make the move fit, so the operator says which.
                self._error_rows(
                    rows,
                    f"order_item_id: this would leave order line {line_id} holding {after} "
                    f"kit(s) while the line says it bought {quantity}, and its "
                    "order_items.csv row leaves that quantity as it is — a line is reconciled "
                    "only where this upload changes its quantity. Set the quantity there to "
                    "what the line should hold, or leave order_item_id as it is",
                )
            elif after != quantity:
                self._error_rows(
                    rows,
                    f"order_item_id: this would leave order line {line_id} holding {after} "
                    f"kit(s) while the line says it bought {quantity}. Nothing in this upload "
                    "restates that line's quantity, so there is no way to tell which of the "
                    "two you mean — add an order_items.csv row for it stating the quantity, "
                    "or leave order_item_id as it is",
                )

    @staticmethod
    def _error_rows(rows: list[_Row], message: str) -> None:
        for row in rows:
            row.action = RowAction.ERROR
            row.error = message

    def _plan_removals(
        self,
        row: _Row,
        *,
        surplus: int,
        kit_rows: list[_Row],
        attached: list[Kit],
        protected: set[uuid.UUID],
    ) -> None:
        """The other half of §3.9 reconciliation: a line whose quantity dropped
        gives up the kits it no longer accounts for (#44 case 2).

        `_plan_spawns` only ever counted upward and returned early on a surplus, so
        reducing a kit line's quantity through `order_items.csv` left every spawned
        kit in place — the line said 1 and the collection held 2, permanently, with
        nothing anywhere recording the disagreement. `_update_line` has always
        removed them, so this is the importer catching up to the writer beside it
        rather than new behaviour.

        Three things are never a candidate, and the order they are excluded in is
        the order they matter in:

        * **A quantity the sheet never stated.** `quantity` is required, but only
          when the column is *there* — a partial sheet may leave it out entirely,
          and `values.get("quantity") or 0` reads that absence as zero. Counting
          upward, zero asks for nothing; counting downward it asks for everything,
          so a sheet correcting a tracking number would delete the order's kits.
          Asked once, as `present` *and* a value: `present` alone is not load-
          bearing today (nothing fills `quantity`, so an absent column is also a
          `None` value) and a second guard whose outcome the first already decides
          is a guard no test can find missing — #74 paid for that lesson.
        * **A kit this upload describes.** An upload asserting a kit exists and a
          quantity implying it doesn't is contradicting itself, and picking a
          winner silently is how an import surprises someone. Excluded from the
          candidates, so the shortfall below reports it.
        * **A kit that has progressed.** Same predicate as the Orders page, from
          `services/orders.py` rather than a second copy of the list — building or
          complete, rated, photographed, or carrying an applied upgrade, which is
          stock already spent that a cascade would leave unexplained.

        `attached` is `_attached_after`'s post-write set, not `row.target.kits`: a
        kit this same upload is moving off the line is not this line's to give up,
        and one it is moving on is.

        Newest first among what's left, matching `_delete_line_kits`: the kits are
        interchangeable, and the one added last is the one least likely to be the
        one someone has been looking at.
        """
        stated = self._stated_quantity(row)
        if not isinstance(stated, int):
            return

        described = {
            kit.matched_id
            for kit in kit_rows
            if kit.matched_id is not None and kit.action is not RowAction.ERROR
        }
        candidates = [
            kit for kit in attached if kit.id not in described and kit.id not in protected
        ]
        if len(candidates) < surplus:
            if not attached:
                # Nothing stored to give up: the surplus is entirely kits this
                # upload itself supplies, which is the file contradicting itself
                # rather than the collection disagreeing with it. Reachable on a
                # line the upload *creates*, where an earlier `row.target is None`
                # guard returned before saying anything at all and the line landed
                # holding more kits than it claimed, in every mode (external review
                # of #86, round four).
                row.action = RowAction.ERROR
                row.error = (
                    f"this line says quantity {stated}, but this upload supplies "
                    f"{surplus + stated} kit(s) for it in kits.csv. Take out the extra kit "
                    "rows, or raise the quantity to match them"
                )
                return
            row.action = RowAction.ERROR
            row.error = (
                f"this line says quantity {stated}, which is {surplus} fewer "
                f"than the {len(attached)} kit(s) attached to it, but only {len(candidates)} "
                "can be removed safely — the rest are building/complete, rated, have photos, "
                "have upgrades applied, or are described by this upload. Move or edit those "
                "kits first, or leave the quantity as it was"
            )
            return

        for kit in list(reversed(candidates))[:surplus]:
            self.removals.append(
                _Removal(kit_id=kit.id, order_item_id=row.target.id, row_number=row.row_number)
            )
        row.messages.append(f"will remove {surplus} kit(s) from this line")

    @staticmethod
    def _newly_set(row: _Row, column: str) -> datetime | None:
        """The post-write instant iff this row is `column`'s null -> non-null
        transition — None for an untouched, restated, corrected or cleared cell.

        Reads the before-state from `row.changes` rather than `row.target`,
        because `FieldChange.before` is `render()`'s output for the *stored*
        value — `""` for null, non-empty for an already-set timestamp — computed
        during planning and immune to what the apply later writes through. A
        change registered with an empty `before` can only be a transition to
        non-null (null -> null renders equal and registers nothing), so the
        value in `row.values` is a real instant whenever this returns one
        (review of #79/#47).
        """
        change = next((c for c in row.changes if c.field == column), None)
        if change is None or change.before:
            return None
        return row.values.get(column)

    def _plan_advances(self) -> None:
        """Both derived kit advances — ship and receive — as plan descriptors (#119).

        Mirrors `mark_order_shipped()` / `receive_order()`'s kit side effects
        (rule 2) for a kit that already existed before this apply, under an
        order this same apply is the one marking shipped or received. A kit this
        apply spawns lands in the right status on its own, through `_Spawn`
        (#47/#95); a pre-existing kit nothing else in the upload mentions used
        to just sit wherever it was, because the importer writes model rows
        directly and none of the live writers' side effects ran (review of
        #79/#47).

        Resolved here rather than at apply time so the fingerprint binds the
        set: kit id, before-status, landing status and stamp. The apply consumes
        the descriptors verbatim — a kit progressed between preview and apply
        changes the re-plan's advance list and the stale hash 409s, instead of
        the apply silently moving a different set of kits than the preview
        implied (#119, from the review of #118).

        Deliberately narrower than the live writers: never touches
        `quantity_on_hand` (rule 10 keeps stock out of anything import derives
        from a receipt — shipping has no stock semantics at all), and never
        overrides a kit this same upload gives its own `status` cell — an
        explicit value in the file always wins over a derived one. Only the
        null -> non-null transition counts (`_newly_set`): a correction is not a
        shipment or an arrival, and clearing has no "un-ship"/"un-arrive" to
        mirror. Ship composes with receive the way the pipeline does — a row
        setting both instants lands its eligible kits in backlog carrying the
        receipt stamp, one descriptor per kit stating the terminal state, since
        the pass through in_transit is unobservable inside one transaction.

        Empty under `replace_all` without saying so: every order row is a
        CREATE there, and only an UPDATE can be a transition on a pre-existing
        order. Empty under `add_only` the same way — a matched order is a SKIP,
        and `_newly_set` reads `changes`, which a SKIP never carries.
        """
        explicit_status_ids = {
            row.matched_id
            for row in self.rows.get("kits", [])
            if row.matched_id is not None and "status" in row.present
        }
        for row in self.rows.get("orders", []):
            if row.action is not RowAction.UPDATE or row.target is None:
                continue
            newly_shipped = self._newly_set(row, "shipped_at")
            newly_received = self._newly_set(row, "received_at")
            if newly_shipped is None and newly_received is None:
                continue
            moved: dict[KitStatus, int] = {}
            for item in row.target.items:
                if item.item_type is not ItemType.KIT:
                    continue
                for kit in item.kits:
                    if kit.id in explicit_status_ids:
                        continue
                    after = kit.status
                    stamp = None
                    if newly_shipped is not None and after in SHIP_ELIGIBLE:
                        after, stamp = KitStatus.IN_TRANSIT, newly_shipped
                    if newly_received is not None and after in ARRIVAL_ELIGIBLE:
                        after, stamp = KitStatus.BACKLOG, newly_received
                    if stamp is None:
                        continue
                    self.advances.append(
                        _Advance(kit_id=kit.id, before=kit.status, after=after, stamp=stamp)
                    )
                    moved[after] = moved.get(after, 0) + 1
            if moved.get(KitStatus.IN_TRANSIT):
                row.messages.append(
                    f"marking this order shipped moves "
                    f"{moved[KitStatus.IN_TRANSIT]} kit(s) to in transit"
                )
            if moved.get(KitStatus.BACKLOG):
                row.messages.append(
                    f"marking this order received moves "
                    f"{moved[KitStatus.BACKLOG]} kit(s) to backlog"
                )

    def _finish(self) -> ExecutionPlan:
        table_plans: list[TablePlan] = []
        error_count = 0
        for spec in TABLE_SPECS:
            rows = self.rows.get(spec.key, [])
            if not rows:
                continue
            counts = {action.value: 0 for action in RowAction}
            for row in rows:
                counts[row.action.value] += 1
            error_count += counts[RowAction.ERROR.value]
            table_plans.append(
                TablePlan(
                    table=spec.key,
                    counts=counts,
                    rows=[
                        PlannedRow(
                            row_number=row.row_number,
                            action=row.action,
                            label=row.label,
                            matched_id=row.matched_id,
                            matched_by=row.matched_by,
                            changes=row.changes,
                            messages=row.messages,
                            error=row.error,
                        )
                        for row in rows
                    ],
                )
            )

        if error_count:
            self.blocking.append(
                f"{error_count} row(s) couldn't be read — nothing will be imported "
                "until they're fixed or removed"
            )

        replace_all = self.mode is ImportMode.REPLACE_ALL
        # Singletons sit outside the TRUNCATE (#23): a replace_all neither deletes
        # the settings row nor lists it as a loss, so it stays out of both maps.
        deletes = (
            {
                key: len(rows)
                for key, rows in self.existing.items()
                if rows and not SPEC_BY_KEY[key].singleton
            }
            if replace_all
            else {}
        )
        # The preview shows counts, but the hash has to cover *which* rows go: two
        # collections of the same size are the same number and a different loss.
        deleted_ids = (
            {
                key: sorted(str(instance.id) for instance in rows)
                for key, rows in self.existing.items()
                if rows and not SPEC_BY_KEY[key].singleton
            }
            if replace_all
            else {}
        )
        derived = DerivedEffects(
            kits_spawned=sum(spawn.count for spawn in self.spawns),
            kits_removed=len(self.removals),
            kits_advanced=len(self.advances),
            stock_changes=0,
            stock_note=(
                "Stock levels come from the catalog files. "
                "Importing orders never changes what you have on hand."
            ),
            rows_deleted=deletes,
        )

        plan = ImportPlan(
            plan_hash=_plan_fingerprint(
                self.mode,
                self.upload.source,
                self.rows,
                self.spawns,
                self.removals,
                self.advances,
                deleted_ids,
            ),
            mode=self.mode,
            source=self.upload.source,
            manifest=self.upload.manifest,
            tables=table_plans,
            derived=derived,
            warnings=self.warnings,
            blocking_errors=self.blocking,
        )
        return ExecutionPlan(
            mode=self.mode,
            rows=self.rows,
            spawns=self.spawns,
            removals=self.removals,
            advances=self.advances,
            plan=plan,
        )


def _plan_fingerprint(
    mode: ImportMode,
    source: str,
    rows: dict[str, list[_Row]],
    spawns: list[_Spawn],
    removals: list[_Removal],
    advances: list[_Advance],
    deleted_ids: dict[str, list[str]],
) -> str:
    """Fingerprints what would be written, not the file it came from.

    Covers the resolved value set of every row, the spawn, removal and advance
    descriptors and the deletion set — so a second file that merely *plans the
    same shape* (same row count, same actions) no longer passes a hash taken
    against the first. The previous fingerprint read only `(row_number, action,
    matched_id, changes)`, which a CREATE contributes nothing to beyond its
    position and the word "create".

    Two families of value must stay out of it, or preview and apply can never
    agree on a sheet that supplies no ids:

    * **Minted uuids.** `_classify` mints one for every id-less create and
      `_create_stub` mints another per conjured reference, freshly random each
      run. They are replaced here by a positional token, which keeps what
      actually matters — *which planned row* a foreign key lands on — while
      dropping the part that is noise. Any reference pointing at one is rewritten
      through the same map, so an id-less retailer named by an order still hashes
      stably.
    * **Clock-derived defaults.** `_COLUMN_DEFAULTS` holds three
      `datetime.now(UTC)` lambdas. They stay out for free because that table is
      applied in `_build_instance` at apply time and never reaches a planned
      row's values — if that ever moves into planning, it has to be excluded
      here explicitly.

    Rendered English stays out as well, and deliberately: `row.label` and
    `row.error` are both wording (`"(unnamed retailer)"`, `"upgrade application
    × 2"`), and §6.1 holds that neither wording nor the active language may
    participate in the hash — otherwise translating a diagnostic silently
    invalidates every outstanding preview. Nothing is lost by omitting them. A
    label is derived from values that are hashed here in full, and an error is
    already carried by the row's action, which cannot reach the comparison
    anyway: `apply_import` rejects a plan holding blocking errors first.
    """
    synthetic: dict[uuid.UUID, str] = {}
    for spec in TABLE_SPECS:
        for index, row in enumerate(rows.get(spec.key, [])):
            # Minted, not read: `_classify` falls back to `uuid4()` whenever the
            # sheet supplied no id, so a `new_id` that doesn't equal the row's own
            # `id` value was invented here. Testing `"id" in present` instead would
            # miss the common case by a mile — every export template ships the
            # column, so a hand-added row has the id *column* and an empty *cell*.
            # Stubs need the flag as well: they set `values["id"]` to the uuid they
            # just minted, so the two match and only the flag can tell them apart.
            if row.new_id is not None and (row.synthetic_id or row.values.get("id") != row.new_id):
                synthetic[row.new_id] = f"new:{spec.key}:{index}"

    def canon(value: Any) -> str:
        if isinstance(value, uuid.UUID):
            return synthetic.get(value, str(value))
        return render(value)

    payload = {
        "mode": mode.value,
        "source": source,
        "deletes": deleted_ids,
        "tables": [
            {
                "table": spec.key,
                "rows": [
                    {
                        "row": row.row_number,
                        "action": row.action.value,
                        "matched": str(row.matched_id) if row.matched_id else None,
                        # Sorted so that reordering a column in the spec doesn't
                        # invalidate every hash for no behavioural reason.
                        "values": sorted(
                            [column.name, canon(row.values.get(column.name))]
                            for column in spec.columns
                            if column.persisted and column.name in row.present
                        ),
                        # `c.after` is `render(new_value)` — already rendered, so a
                        # minted uuid would go in raw and move the hash every pass.
                        # Re-canonicalise from the row's own value instead. `before`
                        # is safe as-is: it renders what the database already holds,
                        # which is never a uuid this planner invented, and it has to
                        # stay in so a target changing under the preview is caught.
                        "changes": [
                            [c.field, c.before, canon(row.values.get(c.field))] for c in row.changes
                        ],
                    }
                    for row in rows.get(spec.key, [])
                ],
            }
            for spec in TABLE_SPECS
            if rows.get(spec.key)
        ],
        "spawns": [
            [
                canon(spawn.order_item_id),
                spawn.count,
                spawn.name,
                spawn.grade,
                spawn.scale or "",
                spawn.kit_number or "",
                spawn.status,
                spawn.row_number,
                spawn.received,
                canon(spawn.received_at),
                canon(spawn.shipped_at),
            ]
            for spawn in spawns
        ],
        # Which kits go, not how many. Two collections of the same size are the
        # same number and a different loss — the same reason `deletes` above
        # carries ids rather than counts. Every one of these is a stored uuid, so
        # none of them needs `canon`.
        "removals": sorted(
            [str(removal.kit_id), str(removal.order_item_id), str(removal.row_number)]
            for removal in removals
        ),
        # Which pre-existing kits this apply's own ship/receive flip moves, from
        # which status to which, stamped with what (#119). A spawned kit is
        # never an advance, so the ids are all stored and need no `canon`;
        # sorted because the set is enumerated off loaded relationship
        # collections, whose ordering is not part of the plan.
        "advances": sorted(
            [str(advance.kit_id), advance.before.value, advance.after.value, canon(advance.stamp)]
            for advance in advances
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:32]


# --- public service API ---------------------------------------------------------


async def check_compatibility(session: AsyncSession, upload: ParsedUpload) -> list[str]:
    warnings: list[str] = []
    manifest = upload.manifest
    if manifest is None:
        return warnings
    if manifest.format and manifest.format != ARCHIVE_FORMAT:
        warnings.append(f"this archive says it's '{manifest.format}', not a plamotrack export")
    if manifest.export_version and manifest.export_version > EXPORT_VERSION:
        raise InvalidInputError(
            f"this archive was written by a newer version of plamotrack "
            f"(export format {manifest.export_version}, this instance reads "
            f"{EXPORT_VERSION}). Update before importing it."
        )
    current = await schema_version(session)
    if manifest.schema_version and current and manifest.schema_version != current:
        warnings.append(
            f"the archive was exported from schema {manifest.schema_version} and this "
            f"instance is on {current} — importing anyway, but check the result"
        )
    return warnings


async def plan_import(
    session: AsyncSession, filename: str, content: bytes, mode: ImportMode
) -> ExecutionPlan:
    # One read, before parsing: the starter expansion and the planner's money
    # fill both spend this value, and reading it twice would let a concurrent
    # settings change hand the two halves of one plan different defaults.
    reference = await instance_settings.reference_currency(session)
    upload = read_upload(filename, content, reference_currency=reference)
    total = sum(len(rows) for rows in upload.tables.values())
    if total > MAX_ROWS:
        raise InvalidInputError(
            f"that import holds {total:,} rows — the limit is {MAX_ROWS:,}. Split it up."
        )
    upload.warnings.extend(await check_compatibility(session, upload))
    planner = _Planner(session, upload, mode, reference)
    return await planner.build()


async def preview_import(
    session: AsyncSession, filename: str, content: bytes, mode: ImportMode
) -> ImportPlan:
    return (await plan_import(session, filename, content, mode)).plan


async def _apply_planned_advances(session: AsyncSession, execution: ExecutionPlan) -> int:
    """Consume the plan's `_Advance` descriptors (#119) — the derived ship/receive
    kit moves, decided by `_plan_advances` and bound by the fingerprint.

    Deliberately re-decides nothing: the hash check just proved the re-plan's
    descriptors equal the previewed ones, so reading live status here again
    would only reopen the gap the descriptor exists to close. `session.get` on
    a row the plan just loaded is an identity-map hit, and a miss means the row
    vanished mid-transaction — impossible under the write gate, tolerated the
    same way the removal loop tolerates it.

    Runs after the write loop for the same reason
    `_stamp_generated_status_changes` does: the loaded `row.target` instances
    were just written through, and setting attributes here marks the kits dirty
    again so the flush before commit carries them. The stamp is the descriptor's
    — the order's post-write ship or receipt instant, backdated included (#93,
    #95), never the clock.
    """
    advanced = 0
    for advance in execution.advances:
        kit = await session.get(Kit, advance.kit_id)
        if kit is None:
            continue
        kit.status = advance.after
        kit.status_updated_at = advance.stamp
        advanced += 1
    return advanced


def _stamp_generated_status_changes(execution: ExecutionPlan) -> None:
    """Give every kit this apply moved a `status_updated_at` of now (#44 case 5).

    The decision was made at plan time by `_defer_generated_status_stamp`, which
    dropped the column from `present` precisely so the clock stays out of the plan
    hash; this is where the clock is finally read. `"status_updated_at" not in
    present` therefore covers both shapes it has to — a sheet that never carried
    the column, and one that carried it blank — while a sheet that stated a time
    keeps it in `present` and is left exactly as written.

    Runs after the write loop for the same reason
    `_apply_planned_advances` does: `row.target` is the mapped
    instance the loop just wrote through, so setting the attribute here marks it
    dirty again and the flush before commit carries it.

    Deliberately not merged into the advances. This is the general
    `kits.csv` status move; those are the ship/receipt derivation, keyed off an
    order row, and `_plan_advances` already skips any kit this upload gives an
    explicit status — so a kit reachable by both is stamped here, once.
    """
    now = datetime.now(UTC)
    for row in execution.rows.get("kits", []):
        if row.action is not RowAction.UPDATE or row.target is None:
            continue
        if "status_updated_at" in row.present:
            continue
        if any(change.field == "status" for change in row.changes):
            row.target.status_updated_at = now


async def apply_import(
    session: AsyncSession,
    filename: str,
    content: bytes,
    mode: ImportMode,
    plan_hash: str | None,
    confirm: str | None = None,
) -> ImportResult:
    if mode is ImportMode.REPLACE_ALL and (confirm or "").strip().upper() != "REPLACE":
        raise InvalidInputError(
            "replacing everything wipes the current collection first — "
            "send confirm='REPLACE' to go ahead"
        )
    # Before parsing anything: an apply with no hash is an apply nobody reviewed.
    # This used to short-circuit on falsy further down, which meant *omitting* the
    # field skipped the recheck entirely rather than failing it.
    plan_hash = (plan_hash or "").strip()
    if not plan_hash:
        raise InvalidInputError(
            "preview this import first and send back the plan_hash it returned — "
            "an apply is only allowed to do what a preview showed"
        )

    # Before the re-plan, not merely before the writes. Everything this function
    # decides — which rows match, what the hash comes to, which kits the fan-out
    # owes, what `replace_all` is about to destroy — is read here and acted on
    # below, so the read and the write have to be one serialized unit. Gating
    # after the plan would leave exactly the window that makes a plan stale:
    # a parent order deleted in it turns a create into a foreign-key 500, and a
    # row created in it is truncated away by a `replace_all` whose approved
    # preview never listed it.
    await acquire_write_gate(session)

    execution = await plan_import(session, filename, content, mode)
    plan = execution.plan

    if plan.blocking_errors:
        raise ConflictError("; ".join(plan.blocking_errors))
    if plan_hash != plan.plan_hash:
        raise ConflictError(
            "the collection changed since you previewed this import, so the preview "
            "no longer matches what would happen — run the preview again"
        )

    if mode is ImportMode.REPLACE_ALL:
        await session.execute(text(f"TRUNCATE {_PORTABLE_TABLES} CASCADE"))

    created = updated = skipped = 0
    for spec in TABLE_SPECS:
        for row in execution.rows.get(spec.key, []):
            if row.action is RowAction.CREATE:
                session.add(_build_instance(spec, row))
                created += 1
            elif row.action is RowAction.UPDATE:
                for change in row.changes:
                    setattr(row.target, change.field, row.values.get(change.field))
                updated += 1
            elif row.action is RowAction.SKIP:
                skipped += 1
        await session.flush()

    _stamp_generated_status_changes(execution)
    advanced = await _apply_planned_advances(session, execution)

    removed = 0
    for removal in execution.removals:
        kit = await session.get(Kit, removal.kit_id)
        if kit is None:
            continue
        await session.delete(kit)
        removed += 1
    await session.flush()

    spawned = 0
    for spawn in execution.spawns:
        item = await session.get(OrderItem, spawn.order_item_id)
        if item is None:
            continue
        # The receipt instant is the plan's post-write resolution
        # (`_order_receipt`), hash-bound with the rest of the spawn descriptor:
        # a kit landing in backlog carries the order's `received_at` — backdated
        # included — the same instant REST and MCP stamp (#93), and a correction
        # landing between preview and apply changes the re-plan's fingerprint,
        # so the stale hash 409s before this line runs. `spawn_kits` itself
        # keeps the stamp off any kit spawned with an explicitly asserted later
        # status.
        await spawn_kits(
            session,
            item,
            name=spawn.name,
            grade=spawn.grade,
            scale=spawn.scale if spawn.scale else default_scale_for_grade(spawn.grade),
            kit_number=spawn.kit_number,
            status=spawn.status or None,
            count=spawn.count,
            received=spawn.received,
            received_at=spawn.received_at,
            shipped=spawn.shipped_at is not None,
            shipped_at=spawn.shipped_at,
        )
        spawned += spawn.count

    await session.flush()
    await session.commit()
    return ImportResult(
        mode=mode,
        source=plan.source,
        created=created,
        updated=updated,
        skipped=skipped,
        kits_spawned=spawned,
        kits_removed=removed,
        kits_advanced=advanced,
        rows_deleted=plan.derived.rows_deleted,
        warnings=plan.warnings,
    )


def _default_money_currency(
    spec: TableSpec,
    values: dict[str, Any],
    present: set[str],
    filled: set[str],
    reference_currency: str,
) -> None:
    """Settle each optional pair's currency, mirroring `_converted_snapshot` in
    services/orders.py — the REST and MCP paths get this from the service layer, but
    the importer writes model rows directly and would otherwise bypass it.

    An amount with a blank currency cell is what the column help promises means
    "the instance default"; without this it reached Postgres as NULL and tripped
    the paired CHECK constraint as an unhandled 500. Resolved here rather than at
    write time so the preview shows the value that will actually land.

    Runs **before** `_apply_money_alternates`, and counts a major-unit twin as an
    amount, because that scaling reads its exponent from this code: settle it
    afterwards and a pre-0.2.3 tools.csv carrying only `unit_cost_reference` gets
    ¥1200 stored as ¥120000 on the way to a paired-CHECK violation.

    Anything this function invents is recorded in `filled`, because a currency the
    sheet never mentioned must not overwrite one already recorded — see
    `_defer_filled_money_currency`.

    Driven by `spec.money_pairs` rather than a table name: the snapshot on order lines
    and a tool's reference cost are the same shape, and the second one only arrived
    (#19) because the first was written as a special case.
    """
    for amount_column, currency_column in spec.money_pairs:
        mirror = spec.money_mirror(amount_column)
        has_amount = values.get(amount_column) is not None or (
            mirror is not None and values.get(mirror) is not None
        )
        if not has_amount or values.get(currency_column) is not None:
            continue
        supplied = currency_column in present
        values[currency_column] = reference_currency
        present.add(currency_column)
        if not supplied:
            filled.add(currency_column)


def _clear_orphan_money_currency(spec: TableSpec, row: _Row) -> None:
    """A currency with no amount beside it denominates nothing, so it is never stored.

    Runs **after** `_apply_money_alternates`, which is the last chance for a
    major-unit twin to supply the amount — judging this at parse time would drop the
    code off a row whose amount had not been scaled across yet.

    Two shapes, and the difference matters:

      * The amount column is there and blank. The sheet has said "no amount", so the
        code is cleared alongside it.
      * The amount column isn't in the file at all. Then a lone currency cell is not
        a redenomination request — `OrderItemCreate` refuses exactly this shape, and
        the importer must not quietly do what the API forbids. Writing it would
        relabel a recorded amount (#12) on an existing row, or land a code beside a
        NULL and trip the paired CHECK on a new one. It is dropped, and the preview
        says so rather than swallowing it.
    """
    for amount_column, currency_column in spec.money_pairs:
        if currency_column not in row.present:
            continue
        if amount_column not in row.present:
            supplied = row.values.get(currency_column) is not None
            row.present.discard(currency_column)
            row.values.pop(currency_column, None)
            if supplied:
                row.messages.append(
                    f"{currency_column}: ignored — this file has no {amount_column} "
                    "column, and a currency can't be changed without restating the "
                    "amount it applies to"
                )
            continue
        if row.values.get(amount_column) is None:
            row.values[currency_column] = None
            row.present.add(currency_column)


def _defer_filled_money_currency(spec: TableSpec, row: _Row) -> None:
    """A currency this importer invented never overwrites one already recorded (#12).

    The same rule the API follows since #3: a sheet that carries an amount and no
    currency *column at all* hasn't asked to relabel anything, so an existing row
    keeps the code it recorded — otherwise correcting an amount would reissue a
    GBP snapshot as whatever this instance happens to use, changing what the number
    means by an exchange rate nobody supplied.

    A blank *cell* in a column the sheet does carry is different, and stays as it
    was: the column help promises blank means the instance default, and a sheet
    that includes the column has said something. New rows are unaffected — they
    have no recorded code to defer to.

    Runs where the row knows its target, so the diff below compares against the
    value that will really be written and the preview stays honest.
    """
    for amount_column, currency_column in spec.money_pairs:
        if currency_column not in row.filled:
            continue
        if row.values.get(amount_column) is None:
            continue
        stored = getattr(row.target, currency_column, None)
        if stored is not None:
            row.values[currency_column] = stored


def _build_instance(spec: TableSpec, row: _Row) -> Any:
    fields: dict[str, Any] = {"id": row.new_id}
    for column in spec.columns:
        if column.name == "id" or not column.persisted:
            continue
        if column.name not in row.present:
            continue
        value = row.values.get(column.name)
        if value is None and column.name in _COLUMN_DEFAULTS.get(spec.key, {}):
            # Only the format's own defaults need omitting here. A column the
            # *schema* defaults looks after itself even when the insert names it
            # as NULL, so a `_column_has_own_default` clause added alongside this
            # one was removed as dead — no mutation of it changed an outcome, and
            # `_refuse_unfillable_creates` is where that predicate earns its keep.
            continue
        fields[column.name] = value

    for column_name, default in _COLUMN_DEFAULTS.get(spec.key, {}).items():
        fields.setdefault(column_name, default() if callable(default) else default)

    if spec.key == "kits" and not fields.get("scale"):
        fields["scale"] = default_scale_for_grade(fields.get("grade") or "")
    return spec.model(**fields)


def _column_is_nullable(spec: TableSpec, name: str) -> bool:
    """Whether the database will accept NULL here. Read off the model rather than
    restated in the spec (rule 9) — a second list is a list that drifts, and this
    one has already drifted once: `_COLUMN_DEFAULTS` was missing two columns the
    schema defaults, and those two were the 500s (#88)."""
    column = spec.model.__table__.columns.get(name)
    return column is None or column.nullable


def _column_has_own_default(spec: TableSpec, name: str) -> bool:
    """Whether the column fills itself in when the insert leaves it out."""
    column = spec.model.__table__.columns.get(name)
    return column is not None and (column.default is not None or column.server_default is not None)


#: Values a hand-written row is allowed to omit entirely.
#:
#: Importer policy, not schema fact — the omissions the *file format* forgives
#: where the database has no opinion (a hand-written order line may leave its price
#: out). Columns the schema already defaults do not belong here; they are read from
#: the model by `_column_has_own_default`. The version of this list that tried to be
#: both was missing `kits.created_at` and `kits.updated_at`, and those two were the
#: 500s (#88). A contract test holds the two apart.
_COLUMN_DEFAULTS: dict[str, dict[str, Any]] = {
    "order_items": {
        # No schema default: the database has no opinion about what a line cost,
        # and this is the file format saying a hand-written row may omit it.
        "unit_price_minor": 0,
        # Both halves of the snapshot stay absent together — the paired CHECK
        # constraint rejects an amount with no currency, and vice versa.
        "converted_price_minor": None,
        "converted_currency_code": None,
    },
}


async def collection_is_empty(session: AsyncSession) -> bool:
    return not await session.scalar(select(Kit.id).limit(1)) and not await session.scalar(
        select(Order.id).limit(1)
    )
