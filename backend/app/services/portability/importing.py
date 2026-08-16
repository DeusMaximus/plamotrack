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
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
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
from app.services.currency import is_known_currency, major_to_minor, minor_fraction_digits
from app.services.kits import default_scale_for_grade
from app.services.numeric import is_lone_group, require_int4
from app.services.orders import (
    ARRIVAL_ELIGIBLE,
    kit_progressed,
    require_line_quantity,
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

#: Same list tests/conftest.py truncates — every table a replace-all restore owns.
_PORTABLE_TABLES = (
    "kits, kit_photos, tools, consumables, upgrades, "
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


def read_upload(filename: str, content: bytes) -> ParsedUpload:
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidInputError(
            f"that file is {len(content) // 1024 // 1024} MB — the import limit is "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB. Split it into separate files."
        )
    name = (filename or "upload").lower()
    if name.endswith(".zip") or content[:2] == b"PK":
        return _read_zip(content)
    if name.endswith(".csv") or b"," in content[:4096]:
        return _read_single_csv(filename, content)
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


def _read_zip(content: bytes) -> ParsedUpload:
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
                    rows, row_budget=max(0, MAX_ROWS - spent)
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


def _read_single_csv(filename: str, content: bytes) -> ParsedUpload:
    header, rows = _read_csv_text(content, filename or "upload")
    if starter_sheet.is_starter_sheet(header):
        expanded, problems = starter_sheet.expand(rows, row_budget=MAX_ROWS)
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


@dataclass
class _Removal:
    """A stored kit a line's reduced quantity no longer accounts for (#44 case 2)."""

    kit_id: uuid.UUID
    order_item_id: uuid.UUID
    row_number: int


@dataclass
class ExecutionPlan:
    mode: ImportMode
    rows: dict[str, list[_Row]]
    spawns: list[_Spawn]
    removals: list[_Removal]
    plan: ImportPlan


def _instance_dict(spec: TableSpec, instance: Any) -> dict[str, Any]:
    return {column.name: column.get(instance) for column in spec.columns if column.persisted}


def _norm_name(value: Any) -> str:
    return str(value or "").strip().lower()


class _Planner:
    def __init__(self, session: AsyncSession, upload: ParsedUpload, mode: ImportMode) -> None:
        self.session = session
        self.upload = upload
        self.mode = mode
        self.remap: dict[tuple[str, uuid.UUID], uuid.UUID] = {}
        self.existing: dict[str, list[Any]] = {}
        self.by_id: dict[str, dict[uuid.UUID, Any]] = {}
        self.by_natural: dict[str, dict[tuple, list[Any]]] = {}
        self.created_ids: dict[str, set[uuid.UUID]] = {key: set() for key in SPEC_BY_KEY}
        self.rows: dict[str, list[_Row]] = {}
        self.spawns: list[_Spawn] = []
        self.removals: list[_Removal] = []
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

        for table in ("tools", "consumables", "upgrades"):
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
        _default_money_currency(spec, values, present, filled)

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
            item_type = row.values.get("item_type")
            if item_type is None:
                return None
            table = CATALOG_TABLE_BY_ITEM_TYPE.get(str(item_type))
            if table is None:  # kit lines don't reference the catalog
                row.values[column.name] = None
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
        zero — stock is stated in the catalog CSVs, never inferred from an order."""
        spec = SPEC_BY_KEY[table]
        new_id = uuid.uuid4()
        values: dict[str, Any] = {"id": new_id, "name": (name or "").strip()}
        present = {"id", "name"}
        if table in ("tools", "consumables"):
            values["category"] = "uncategorised"
            present.add("category")
        if table == "upgrades":
            values["manufacturer"] = "unknown"
            present.add("manufacturer")
        if table in ("tools", "consumables", "upgrades"):
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
        self._defer_generated_status_stamp(spec, row)

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

                if not replace_all and row.action is not RowAction.ERROR:
                    if spec.key == "orders":
                        self._match_order(row, incoming_lines)
                    elif spec.key == "order_items":
                        self._match_order_item(row)
                    else:
                        self._match_generic(spec, row)

                if replace_all:
                    if row.action is not RowAction.ERROR:
                        row.action = RowAction.CREATE
                        row.new_id = row.values.get("id") or uuid.uuid4()
                        self.created_ids[spec.key].add(row.new_id)
                else:
                    self._classify(spec, row)

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
        self._plan_spawns(replace_all)
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

    def _order_received(self, order_id: uuid.UUID) -> bool:
        """Whether the order a kit line belongs to has arrived, so a spawned kit
        lands in the right status instead of always `_initial_kit_status`'s default
        of "still on the way" (#47). Checks this import's own orders rows first —
        covering both a freshly created order and an existing one this import
        updates — and falls back to the persisted row for an order the upload
        doesn't touch at all.
        """
        for row in self.rows.get("orders", []):
            candidate = row.new_id if row.action is RowAction.CREATE else row.matched_id
            if candidate != order_id:
                continue
            # Only a row that will actually be written can answer from the file —
            # `add_only` deliberately leaves a matched order untouched (SKIP), so
            # its uploaded `received_at` cell describes nothing that will land.
            writes = row.action in (RowAction.CREATE, RowAction.UPDATE)
            if writes and "received_at" in row.present:
                return row.values.get("received_at") is not None
            if row.target is not None:
                return row.target.received_at is not None
            return False
        existing = self.by_id["orders"].get(order_id)
        return existing is not None and existing.received_at is not None

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

    def _plan_spawns(self, replace_all: bool) -> None:
        """Hybrid dispatch: a kit line spawns only the kits nothing else provides,
        and gives up the kits its quantity no longer accounts for."""
        kit_rows = self.rows.get("kits", [])
        reconciled: set[uuid.UUID] = set()
        for row in self.rows.get("order_items", []):
            if row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            # The *effective* type, from the shared reading in `invariants`: an
            # update may legitimately omit `item_type`, and testing `values` alone
            # read every such row as typeless and skipped reconciliation entirely,
            # so a partial sheet reducing a quantity left every kit attached
            # (external review of #86).
            if invariants.effective_item_type(row) is not ItemType.KIT:
                continue
            line_id = row.matched_id or row.new_id
            if line_id is None:
                continue

            reconciled.add(line_id)
            covered = sum(
                1
                for kit in kit_rows
                if kit.action is RowAction.CREATE and kit.values.get("order_item_id") == line_id
            )
            stored = list(row.target.kits) if row.target is not None else []
            attached = self._attached_after(line_id, stored, kit_rows)
            wanted = int(row.values.get("quantity") or 0)
            missing = wanted - covered - len(attached)
            if missing < 0:
                self._plan_removals(row, surplus=-missing, kit_rows=kit_rows, attached=attached)
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
                    received=self._order_received(order_id),
                )
            )
            row.messages.append(f"will create {missing} kit(s) from this line")

        self._refuse_unreconciled_kit_moves(kit_rows, reconciled)

    def _refuse_unreconciled_kit_moves(
        self, kit_rows: list[_Row], reconciled: set[uuid.UUID]
    ) -> None:
        """A kits-side write may not leave a line disagreeing with its own quantity.

        The loop above visits the lines this upload *states a quantity for*. A
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
        it is. The fan-out spawns and removes because *the line stated a quantity* —
        that is what a quantity means. A kits row moving provenance says nothing
        about how many kits the line bought, so conjuring a replacement kit or
        deleting a real one on the strength of it would be inventing intent the file
        never expressed. It would also make `add_only` delete, which is the one
        thing that mode promises never to do. So the upload is told it contradicts
        itself, and the operator settles it by saying both halves out loud.

        A line the upload does restate is not checked here — the loop above already
        reconciled it, with the same post-write set. And `replace_all` cannot reach
        the stored lookup: every line is created by the upload and therefore
        reconciled, and a kits row naming a line the upload lacks is already a
        `_resolve_ref` error (#45).
        """
        touched: dict[uuid.UUID, list[_Row]] = {}
        for kit_row in kit_rows:
            if kit_row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            if "order_item_id" not in kit_row.present:
                continue
            # Both ends of the move: the line it lands on, and — for a row that
            # matched a stored kit — the one it leaves. Either can be left holding
            # the wrong number, and only one of them is named in the cell.
            ends = {kit_row.values.get("order_item_id")}
            if kit_row.target is not None:
                ends.add(kit_row.target.order_item_id)
            for line_id in ends:
                if line_id is not None:
                    touched.setdefault(line_id, []).append(kit_row)

        for line_id, rows in touched.items():
            if line_id in reconciled:
                continue
            item = self.by_id["order_items"].get(line_id)
            if item is None or item.item_type is not ItemType.KIT:
                continue
            created = sum(
                1
                for kit in kit_rows
                if kit.action is RowAction.CREATE and kit.values.get("order_item_id") == line_id
            )
            after = len(self._attached_after(line_id, list(item.kits), kit_rows)) + created
            if after == item.quantity:
                continue
            for row in rows:
                row.action = RowAction.ERROR
                row.error = (
                    f"order_item_id: this would leave order line {line_id} holding {after} "
                    f"kit(s) while the line itself says it bought {item.quantity}. Nothing in "
                    "this upload restates that line's quantity, so there is no way to tell "
                    "which of the two you mean — add an order_items.csv row for it stating "
                    "the quantity, or leave order_item_id as it is"
                )

    def _plan_removals(
        self, row: _Row, *, surplus: int, kit_rows: list[_Row], attached: list[Kit]
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
        stated = row.values.get("quantity") if "quantity" in row.present else None
        if row.target is None or not isinstance(stated, int):
            return

        described = {
            kit.matched_id
            for kit in kit_rows
            if kit.matched_id is not None and kit.action is not RowAction.ERROR
        }
        candidates = [
            kit for kit in attached if kit.id not in described and not kit_progressed(kit)
        ]
        if len(candidates) < surplus:
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
        deletes = (
            {key: len(rows) for key, rows in self.existing.items() if rows} if replace_all else {}
        )
        # The preview shows counts, but the hash has to cover *which* rows go: two
        # collections of the same size are the same number and a different loss.
        deleted_ids = (
            {
                key: sorted(str(instance.id) for instance in rows)
                for key, rows in self.existing.items()
                if rows
            }
            if replace_all
            else {}
        )
        derived = DerivedEffects(
            kits_spawned=sum(spawn.count for spawn in self.spawns),
            kits_removed=len(self.removals),
            stock_changes=0,
            stock_note=(
                "Stock levels come from the tools/consumables/upgrades files. "
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
            plan=plan,
        )


def _plan_fingerprint(
    mode: ImportMode,
    source: str,
    rows: dict[str, list[_Row]],
    spawns: list[_Spawn],
    removals: list[_Removal],
    deleted_ids: dict[str, list[str]],
) -> str:
    """Fingerprints what would be written, not the file it came from.

    Covers the resolved value set of every row, the spawn descriptors and the
    deletion set — so a second file that merely *plans the same shape* (same row
    count, same actions) no longer passes a hash taken against the first. The
    previous fingerprint read only `(row_number, action, matched_id, changes)`,
    which a CREATE contributes nothing to beyond its position and the word
    "create".

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
    upload = read_upload(filename, content)
    total = sum(len(rows) for rows in upload.tables.values())
    if total > MAX_ROWS:
        raise InvalidInputError(
            f"that import holds {total:,} rows — the limit is {MAX_ROWS:,}. Split it up."
        )
    upload.warnings.extend(await check_compatibility(session, upload))
    planner = _Planner(session, upload, mode)
    return await planner.build()


async def preview_import(
    session: AsyncSession, filename: str, content: bytes, mode: ImportMode
) -> ImportPlan:
    return (await plan_import(session, filename, content, mode)).plan


def _advance_kits_for_newly_received_orders(execution: ExecutionPlan) -> None:
    """Mirror `receive_order()`'s kit-arrival side effect (rule 2) for a kit that
    already existed before this apply, under an order this same apply is the one
    marking received.

    A kit this apply spawns already lands `backlog` on its own, through
    `spawn.received` (#47). A pre-existing kit under that same order — one
    nothing in this upload otherwise mentions — used to just sit wherever it
    already was: the importer writes model rows directly, so none of
    `receive_order()`'s side effects ran, even though the REST/MCP path never
    allows an order to become received without advancing every arrival-eligible
    kit on it (review of #79/#47).

    Deliberately narrower than `receive_order()`: this never touches
    `quantity_on_hand` (rule 10 keeps stock out of anything import derives from a
    receipt) and never overrides a kit this same upload explicitly gives its own
    `status` cell — an explicit value in the file always wins over a derived one.
    Only the explicit `unreceived -> received` transition counts as an arrival —
    correcting an already-received order's timestamp to a different non-null
    value is not one, and clearing `received_at` doesn't have an established
    "un-arrive" equivalent to mirror, so both are left alone.

    Reads whether the order was received *before* this apply from `row.changes`
    rather than `row.target`: this runs after the main write loop, which already
    applied `setattr` to every changed field on `row.target`, so its
    `received_at` is the new value by the time this function sees it. `changes`
    was computed during planning, before that mutation, and `FieldChange.before`
    is `render()`'s output for the old value — `""` for `None`, and non-empty for
    an already-set timestamp — so it's the one place that still distinguishes a
    genuine arrival from a same-state correction (review of #79/#47).
    """
    explicit_status_ids = {
        row.matched_id
        for row in execution.rows.get("kits", [])
        if row.matched_id is not None and "status" in row.present
    }
    now = datetime.now(UTC)
    for row in execution.rows.get("orders", []):
        if row.action is not RowAction.UPDATE or row.target is None:
            continue
        received_change = next((c for c in row.changes if c.field == "received_at"), None)
        if received_change is None or received_change.before:
            # `received_at` wasn't touched, or it already held a value before
            # this apply — a timestamp correction and a clear-while-received
            # both leave `before` non-empty, and neither is an arrival. Only
            # `before == ""` (was null) with a change registered at all — which
            # therefore can only be a transition to non-null — is one.
            continue
        for item in row.target.items:
            if item.item_type is not ItemType.KIT:
                continue
            for kit in item.kits:
                if kit.id in explicit_status_ids:
                    continue
                if kit.status in ARRIVAL_ELIGIBLE:
                    kit.status = KitStatus.BACKLOG
                    kit.status_updated_at = now


def _stamp_generated_status_changes(execution: ExecutionPlan) -> None:
    """Give every kit this apply moved a `status_updated_at` of now (#44 case 5).

    The decision was made at plan time by `_defer_generated_status_stamp`, which
    dropped the column from `present` precisely so the clock stays out of the plan
    hash; this is where the clock is finally read. `"status_updated_at" not in
    present` therefore covers both shapes it has to — a sheet that never carried
    the column, and one that carried it blank — while a sheet that stated a time
    keeps it in `present` and is left exactly as written.

    Runs after the write loop for the same reason
    `_advance_kits_for_newly_received_orders` does: `row.target` is the mapped
    instance the loop just wrote through, so setting the attribute here marks it
    dirty again and the flush before commit carries it.

    Deliberately not merged into that function. This is the general
    `kits.csv` status move; that one is the receipt derivation, keyed off an order
    row, and it already skips any kit this upload gives an explicit status — so a
    kit reachable by both is stamped here, once.
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
    _advance_kits_for_newly_received_orders(execution)

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
        rows_deleted=plan.derived.rows_deleted,
        warnings=plan.warnings,
    )


def _default_money_currency(
    spec: TableSpec, values: dict[str, Any], present: set[str], filled: set[str]
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
        values[currency_column] = get_settings().reference_currency
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
            continue  # let the model default apply rather than writing NULL
        fields[column.name] = value

    for column_name, default in _COLUMN_DEFAULTS.get(spec.key, {}).items():
        fields.setdefault(column_name, default() if callable(default) else default)

    if spec.key == "kits" and not fields.get("scale"):
        fields["scale"] = default_scale_for_grade(fields.get("grade") or "")
    return spec.model(**fields)


#: Values a hand-written row is allowed to omit entirely.
_COLUMN_DEFAULTS: dict[str, dict[str, Any]] = {
    "tools": {"quantity_on_hand": 0},
    "consumables": {"quantity_on_hand": 0},
    "upgrades": {"quantity_on_hand": 0},
    "kits": {"status": "backlog", "status_updated_at": lambda: datetime.now(UTC)},
    "order_items": {
        "unit_price_minor": 0,
        # Both halves of the snapshot stay absent together — the paired CHECK
        # constraint rejects an amount with no currency, and vice versa.
        "converted_price_minor": None,
        "converted_currency_code": None,
    },
    "upgrade_applications": {"applied_at": lambda: datetime.now(UTC)},
    "kit_photos": {"created_at": lambda: datetime.now(UTC)},
}


async def collection_is_empty(session: AsyncSession) -> bool:
    return not await session.scalar(select(Kit.id).limit(1)) and not await session.scalar(
        select(Order.id).limit(1)
    )
