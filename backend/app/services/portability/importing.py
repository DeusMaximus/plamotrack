"""Import: parse, plan, then apply.

Planning and applying are deliberately separate. Planning is a pure read — it
resolves every incoming row against what's already in the database, classifies it
(create / update / unchanged / skip / error), and works out the derived side
effects, without writing anything. That plan *is* the preview payload.

Applying re-parses and re-plans, compares the resulting `plan_hash` against the
one the user was shown, and refuses with a 409 if they differ. Nothing is stored
between the two calls: the plan can't go stale in a cache, survives a container
restart, and the recheck closes the window between looking and committing.

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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.exceptions import ConflictError, InvalidInputError
from app.models import ItemType, Kit, Order, OrderItem
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
from app.services.kits import default_scale_for_grade
from app.services.orders import spawn_kits
from app.services.portability import starter_sheet
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
    major_to_minor,
    render,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
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


def _read_csv_text(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text_content = raw.decode("utf-8-sig", errors="replace")
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


def _read_zip(content: bytes) -> ParsedUpload:
    tables: dict[str, list[dict[str, str]]] = {}
    warnings: list[str] = []
    errors: list[str] = []
    manifest: ManifestInfo | None = None

    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise InvalidInputError("that zip file is corrupt or not a zip archive") from exc

    with archive:
        names = [n for n in archive.namelist() if not n.endswith("/") and "__MACOSX" not in n]
        manifest_name = next((n for n in names if n.rsplit("/", 1)[-1] == MANIFEST_NAME), None)
        if manifest_name:
            try:
                manifest = _read_manifest(json.loads(archive.read(manifest_name)))
            except (json.JSONDecodeError, ValueError) as exc:
                warnings.append(f"manifest.json could not be read ({exc}) — continuing without it")
        else:
            warnings.append(
                "no manifest.json in this zip, so it's being read as a loose set of CSVs"
            )

        for entry in names:
            if not entry.lower().endswith(".csv"):
                continue
            header, rows = _read_csv_text(archive.read(entry))
            if starter_sheet.is_starter_sheet(header):
                for key, expanded in starter_sheet.expand(rows).items():
                    tables.setdefault(key, []).extend(expanded)
                continue
            table_key = _detect_table(entry, header)
            if table_key is None:
                warnings.append(f"{entry}: not recognised as any known table — skipped")
                continue
            tables.setdefault(table_key, []).extend(rows)

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
    header, rows = _read_csv_text(content)
    if starter_sheet.is_starter_sheet(header):
        return ParsedUpload(source="starter-sheet", tables=starter_sheet.expand(rows))
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
    label: str = ""
    matched_id: uuid.UUID | None = None
    matched_by: str | None = None
    target: Any = None
    changes: list[FieldChange] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    error: str | None = None
    new_id: uuid.UUID | None = None


@dataclass
class _Spawn:
    order_item_id: uuid.UUID
    count: int
    name: str
    grade: str
    scale: str | None
    kit_number: str | None
    status: str
    row_number: int


@dataclass
class ExecutionPlan:
    mode: ImportMode
    rows: dict[str, list[_Row]]
    spawns: list[_Spawn]
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
        self.warnings: list[str] = list(upload.warnings)
        self.blocking: list[str] = list(upload.errors)
        self.catalog_names: dict[uuid.UUID, str] = {}
        self.claimed_lines: set[uuid.UUID] = set()

    # -- loading ---------------------------------------------------------------

    async def load_existing(self) -> None:
        for spec in TABLE_SPECS:
            stmt = select(spec.model)
            if spec.key == "orders":
                stmt = stmt.options(selectinload(Order.items).selectinload(OrderItem.kits))
            elif spec.key == "order_items":
                stmt = stmt.options(selectinload(OrderItem.kits))
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

        for column in spec.columns:
            if column.name not in raw:
                continue
            present.add(column.name)
            cell = raw[column.name]
            try:
                values[column.name] = column.parse(cell)
            except ValueError as exc:
                errors.append(f"{column.name}: {exc}")
                values[column.name] = None

        for column in spec.columns:
            if column.required and column.name in present and values.get(column.name) is None:
                errors.append(f"{column.name} is required")

        _pair_converted_snapshot(spec, values, present)

        row = _Row(
            table=spec.key,
            row_number=row_number,
            action=RowAction.ERROR if errors else RowAction.CREATE,
            values=values,
            present=present,
        )
        row.label = spec.label(values)
        if errors:
            row.error = "; ".join(errors)
        return row

    # -- reference resolution --------------------------------------------------

    def _resolve_ref(self, row: _Row, spec: TableSpec, column) -> None:
        """Point a foreign key at the right local row: remap it, accept it if it's
        already local or arriving in this import, or fall back to the readable
        mirror column."""
        table = column.ref_table
        if table == "catalog":
            item_type = row.values.get("item_type")
            if item_type is None:
                return
            table = CATALOG_TABLE_BY_ITEM_TYPE.get(str(item_type))
            if table is None:  # kit lines don't reference the catalog
                row.values[column.name] = None
                return

        raw_id = row.values.get(column.name)
        if raw_id is not None:
            mapped = self.remap.get((table, raw_id))
            if mapped is not None:
                row.values[column.name] = mapped
                return
            if raw_id in self.by_id[table] or raw_id in self.created_ids[table]:
                return
            row.values[column.name] = None  # unknown uuid — try the readable mirror

        alt = next(
            (c for c in spec.columns if c.role is ColumnRole.ALT_REF and c.mirrors == column.name),
            None,
        )
        if alt is None:
            return
        name = _norm_name(row.values.get(alt.name))
        if not name:
            return

        # Resolving through the readable mirror counts as the row supplying this
        # column, even though the uuid column itself was blank or absent.
        row.present.add(column.name)

        match = next(
            (instance for instance in self.existing[table] if _norm_name(instance.name) == name),
            None,
        )
        if match is not None:
            row.values[column.name] = match.id
            return
        # Named but unknown: created on the fly, like the select-or-create flow does.
        pending = self._pending_by_name(table, name)
        if pending is not None:
            row.values[column.name] = pending
            return
        row.values[column.name] = self._create_stub(table, row.values.get(alt.name), row)

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
        self, item_type: Any, ref_name: str, quantity: Any, unit_price: Any
    ) -> tuple:
        return (
            str(item_type or ""),
            _norm_name(ref_name),
            int(quantity or 0),
            int(unit_price or 0),
        )

    def _existing_line_fingerprint(self, item: OrderItem) -> tuple:
        if item.item_type is ItemType.KIT:
            ref_name = item.kits[0].name if item.kits else ""
        else:
            ref_name = self.catalog_names.get(item.catalog_ref_id, "")
        return self._line_fingerprint(
            item.item_type, ref_name, item.quantity, item.unit_price_minor
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
            item_type, ref_name, values.get("quantity"), values.get("unit_price_minor")
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

    # -- the main pass ---------------------------------------------------------

    async def build(self) -> ExecutionPlan:
        await self.load_existing()
        replace_all = self.mode is ImportMode.REPLACE_ALL

        # Order matching needs the incoming lines, which live in a table processed
        # later — group them up front.
        incoming_lines: dict[uuid.UUID, list[dict]] = {}
        for raw in self.upload.tables.get("order_items", []):
            spec = SPEC_BY_KEY["order_items"]
            parsed = self._parse_row(spec, raw)
            order_id = parsed.values.get("order_id")
            if order_id is not None:
                incoming_lines.setdefault(order_id, []).append(parsed.values)

        for spec in TABLE_SPECS:
            raw_rows = self.upload.tables.get(spec.key, [])
            planned = self.rows.setdefault(spec.key, [])
            for raw in raw_rows:
                row = self._parse_row(spec, raw)
                self._resolve_all_refs(spec, row)
                self._apply_money_alternates(spec, row)

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

                self._annotate(spec, row, replace_all)
                planned.append(row)

        self._plan_spawns(replace_all)
        return self._finish()

    def _resolve_all_refs(self, spec: TableSpec, row: _Row) -> None:
        if row.action is RowAction.ERROR:
            return
        for column in spec.columns:
            if column.role is ColumnRole.REF:
                self._resolve_ref(row, spec, column)
                if column.required and row.values.get(column.name) is None:
                    row.action = RowAction.ERROR
                    target = column.ref_table
                    row.error = (
                        f"{column.name}: no matching {target} found — "
                        "add it to the import or fix the reference"
                    )

    def _apply_money_alternates(self, spec: TableSpec, row: _Row) -> None:
        """Major units fill in only where the canonical minor-unit column is absent
        or blank — §6 keeps integer minor units authoritative."""
        for column in spec.columns:
            if column.role is not ColumnRole.ALT_MONEY:
                continue
            if row.values.get(column.mirrors) is not None:
                continue
            major = row.values.get(column.name)
            if major is None:
                continue
            try:
                row.values[column.mirrors] = major_to_minor(major, row.values.get("currency_code"))
                row.present.add(column.mirrors)
            except (ArithmeticError, ValueError):
                row.action = RowAction.ERROR
                row.error = f"{column.name}: '{major}' is not a valid amount"

    def _annotate(self, spec: TableSpec, row: _Row, replace_all: bool) -> None:
        """Warnings that need a human eye rather than blocking the import."""
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

    def _plan_spawns(self, replace_all: bool) -> None:
        """Hybrid dispatch: a kit line spawns only the kits nothing else provides."""
        kit_rows = self.rows.get("kits", [])
        for row in self.rows.get("order_items", []):
            if row.action in (RowAction.ERROR, RowAction.SKIP):
                continue
            if row.values.get("item_type") is not ItemType.KIT:
                continue
            line_id = row.matched_id or row.new_id
            if line_id is None:
                continue

            covered = sum(
                1
                for kit in kit_rows
                if kit.action is RowAction.CREATE and kit.values.get("order_item_id") == line_id
            )
            existing = 0
            if not replace_all and row.target is not None:
                existing = len(row.target.kits)
            wanted = int(row.values.get("quantity") or 0)
            missing = wanted - covered - existing
            if missing <= 0:
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
            self.spawns.append(
                _Spawn(
                    order_item_id=line_id,
                    count=missing,
                    name=name,
                    grade=grade,
                    scale=row.values.get("kit_scale"),
                    kit_number=row.values.get("kit_number"),
                    status=str(status) if status else "",
                    row_number=row.row_number,
                )
            )
            row.messages.append(f"will create {missing} kit(s) from this line")

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
        derived = DerivedEffects(
            kits_spawned=sum(spawn.count for spawn in self.spawns),
            stock_changes=0,
            stock_note=(
                "Stock levels come from the tools/consumables/upgrades files. "
                "Importing orders never changes what you have on hand."
            ),
            rows_deleted=deletes,
        )

        plan = ImportPlan(
            plan_hash="",
            mode=self.mode,
            source=self.upload.source,
            manifest=self.upload.manifest,
            tables=table_plans,
            derived=derived,
            warnings=self.warnings,
            blocking_errors=self.blocking,
        )
        plan.plan_hash = _hash_plan(plan)
        return ExecutionPlan(mode=self.mode, rows=self.rows, spawns=self.spawns, plan=plan)


def _hash_plan(plan: ImportPlan) -> str:
    """Fingerprints the decisions, not the file: if the collection changed under a
    preview such that any row would now resolve differently, the hash moves."""
    payload = {
        "mode": plan.mode.value,
        "source": plan.source,
        "tables": [
            {
                "table": table.table,
                "rows": [
                    [
                        row.row_number,
                        row.action.value,
                        str(row.matched_id) if row.matched_id else None,
                        [[c.field, c.before, c.after] for c in row.changes],
                    ]
                    for row in table.rows
                ],
            }
            for table in plan.tables
        ],
        "derived": {
            "kits_spawned": plan.derived.kits_spawned,
            "rows_deleted": plan.derived.rows_deleted,
        },
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

    execution = await plan_import(session, filename, content, mode)
    plan = execution.plan

    if plan.blocking_errors:
        raise ConflictError("; ".join(plan.blocking_errors))
    if plan_hash and plan_hash != plan.plan_hash:
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
        rows_deleted=plan.derived.rows_deleted,
        warnings=plan.warnings,
    )


def _pair_converted_snapshot(spec: TableSpec, values: dict[str, Any], present: set[str]) -> None:
    """Keep the §6 snapshot's two halves consistent, mirroring `_converted_snapshot`
    in services/orders.py — the REST and MCP paths get this from the service layer,
    but the importer writes model rows directly and would otherwise bypass it.

    An amount with a blank currency cell is what the column help promises means
    "the instance default"; without this it reached Postgres as NULL and tripped
    the paired CHECK constraint as an unhandled 500. Resolved here rather than at
    write time so the preview shows the value that will actually land.
    """
    if spec.key != "order_items" or "converted_price_minor" not in present:
        return
    if values.get("converted_price_minor") is None:
        # No amount means no snapshot: a currency on its own records nothing.
        values["converted_currency_code"] = None
        present.add("converted_currency_code")
    elif values.get("converted_currency_code") is None:
        values["converted_currency_code"] = get_settings().reference_currency
        present.add("converted_currency_code")


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
