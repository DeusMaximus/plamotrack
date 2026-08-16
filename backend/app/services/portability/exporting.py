"""Export: the whole collection as a zip of CSVs, single-table CSVs, and blank templates.

The CSVs are deliberately readable as well as machine-restorable — every uuid
foreign key sits next to a human-readable mirror column, and every integer
minor-unit money column next to its major-unit form. Open orders.csv in a
spreadsheet and you see "Hobby Link Japan" and "112.00", not two uuids and 11200.
"""

import csv
import io
import json
import zipfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import __version__
from app.exceptions import NotFoundError
from app.models import (
    Consumable,
    ItemType,
    Kit,
    Order,
    OrderItem,
    Retailer,
    Tool,
    Upgrade,
    UpgradeApplication,
)
from app.services.currency import minor_to_major
from app.services.portability import starter_sheet
from app.services.portability.spec import (
    SPEC_BY_KEY,
    TABLE_SPECS,
    ColumnRole,
    TableSpec,
    render,
)
from app.services.read_snapshot import begin_read_snapshot

#: Bumped when the CSV shape changes in a way an older importer couldn't read.
EXPORT_VERSION = 1
ARCHIVE_FORMAT = "plamotrack-archive"
MANIFEST_NAME = "manifest.json"

_README = """plamotrack export
=================

This archive is your collection, in plain CSV. Nothing in here is locked to
plamotrack — open the files in any spreadsheet, keep them as a backup, or edit
them and import them back.

  manifest.json    what this archive is, and which schema version wrote it
  *.csv            one file per table

To restore or merge it: plamotrack -> Data -> Import, and drop this zip in.
You get a full preview of what will change before anything is written.

Two things worth knowing if you plan to edit these by hand:

  * Every `*_id` column has a readable twin (`retailer_name`, `catalog_name`).
    Fill in either one. The id wins when both are set and the id is known.
  * Money is stored as whole minor units (`unit_price_minor` = cents), with a
    major-unit twin (`unit_price` = 49.99) beside it. Same rule: the minor
    column wins when both are set.

Leave the `id` column blank on rows you add by hand and one will be generated.
"""


def _write_csv(header: list[str], rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    # QUOTE_MINIMAL + \r\n keeps Excel, Numbers, and LibreOffice all happy.
    writer = csv.DictWriter(buffer, fieldnames=header, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


async def _load_all(session: AsyncSession) -> dict[str, list[Any]]:
    """One pass over every table. A personal collection is small enough that
    loading it whole is simpler and faster than per-row lookups while filling
    the readable mirror columns.

    One statement per table means one `READ COMMITTED` snapshot per table, and a
    write landing between two of them produces an archive that combines states
    that never coexisted (#48). The snapshot is taken here rather than in the two
    callers because this is the multi-statement read: everything downstream —
    including `build_manifest`'s schema-version lookup — rides in the same
    transaction, and no future caller of this function can forget it."""
    await begin_read_snapshot(session)
    orders = (await session.scalars(select(Order).order_by(Order.order_date, Order.id))).all()
    order_items = (
        await session.scalars(
            select(OrderItem).options(selectinload(OrderItem.kits)).order_by(OrderItem.id)
        )
    ).all()
    return {
        "retailers": list((await session.scalars(select(Retailer).order_by(Retailer.name))).all()),
        "tools": list((await session.scalars(select(Tool).order_by(Tool.name))).all()),
        "consumables": list(
            (await session.scalars(select(Consumable).order_by(Consumable.name))).all()
        ),
        "upgrades": list((await session.scalars(select(Upgrade).order_by(Upgrade.name))).all()),
        "orders": list(orders),
        "order_items": list(order_items),
        "kits": list((await session.scalars(select(Kit).order_by(Kit.created_at, Kit.id))).all()),
        "upgrade_applications": list(
            (
                await session.scalars(
                    select(UpgradeApplication).order_by(UpgradeApplication.applied_at)
                )
            ).all()
        ),
        # Schema-only until Milestone 7; exported empty so the archive shape is
        # already correct when photos land.
        "kit_photos": [],
    }


def _fill_alternates(spec: TableSpec, row: dict[str, str], instance: Any, data: dict) -> None:
    """Populate the readable mirror columns the model itself can't provide."""
    names = {
        "retailers": {r.id: r.name for r in data["retailers"]},
        "upgrades": {u.id: u.name for u in data["upgrades"]},
    }
    catalog_names = {
        ItemType.TOOL: {t.id: t.name for t in data["tools"]},
        ItemType.CONSUMABLE: {c.id: c.name for c in data["consumables"]},
        ItemType.UPGRADE: {u.id: u.name for u in data["upgrades"]},
    }

    for column in spec.columns:
        if column.role is ColumnRole.ALT_MONEY:
            minor = getattr(instance, column.mirrors, None)
            if minor is not None:
                # `column.currency_column`, not a hardcoded "currency_code": that is
                # the mechanism #19 added so a table whose money names its currency
                # differently still scales by the right exponent. Tools have no
                # `currency_code` at all, so the literal resolved to None and every
                # zero-decimal tool cost exported a hundred times too small — ¥1200
                # written out as 12.00. The importer already reads this field; the
                # exporter is the half of the pair that was never updated.
                row[column.name] = minor_to_major(
                    minor, getattr(instance, column.currency_column, None)
                )
        elif column.role is ColumnRole.ALT_REF:
            ref_id = getattr(instance, column.mirrors, None)
            if ref_id is None:
                continue
            if column.ref_table == "catalog":
                row[column.name] = render(catalog_names.get(instance.item_type, {}).get(ref_id))
            else:
                row[column.name] = render(names.get(column.ref_table, {}).get(ref_id))

    if spec.key == "order_items" and instance.item_type is ItemType.KIT and instance.kits:
        # Kit details live on the spawned kits, not the line — mirror the first one
        # (an order edit keeps them all in sync) so the line is readable on its own
        # and can drive a fan-out if it's ever imported without a kits.csv.
        kit = instance.kits[0]
        row["kit_name"] = render(kit.name)
        row["kit_grade"] = render(kit.grade)
        row["kit_scale"] = render(kit.scale)
        row["kit_number"] = render(kit.kit_number)
        row["kit_status"] = render(kit.status)


def _rows_for(spec: TableSpec, data: dict) -> list[dict[str, str]]:
    rows = []
    for instance in data[spec.key]:
        row = spec.to_row(instance)
        _fill_alternates(spec, row, instance, data)
        rows.append(row)
    return rows


async def schema_version(session: AsyncSession) -> str | None:
    """The live Alembic revision — the honest answer to "which schema wrote this",
    and what lets an importer refuse an archive from a newer version of the app."""
    try:
        return await session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception:  # noqa: BLE001 — a missing table just means "unknown"
        return None


async def export_table_csv(session: AsyncSession, table_key: str) -> str:
    spec = SPEC_BY_KEY.get(table_key)
    if spec is None:
        raise NotFoundError(f"no exportable table named '{table_key}'")
    data = await _load_all(session)
    return _write_csv(spec.header, _rows_for(spec, data))


async def build_manifest(session: AsyncSession, counts: dict[str, int]) -> dict:
    return {
        "format": ARCHIVE_FORMAT,
        "export_version": EXPORT_VERSION,
        "schema_version": await schema_version(session),
        "app_version": __version__,
        "exported_at": datetime.now(UTC).isoformat(),
        "tables": {
            spec.key: {"file": spec.filename, "rows": counts.get(spec.key, 0)}
            for spec in TABLE_SPECS
        },
    }


async def export_archive(session: AsyncSession) -> bytes:
    data = await _load_all(session)
    table_rows = {spec.key: _rows_for(spec, data) for spec in TABLE_SPECS}
    manifest = await build_manifest(session, {key: len(rows) for key, rows in table_rows.items()})

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
        archive.writestr("README.txt", _README)
        for spec in TABLE_SPECS:
            archive.writestr(spec.filename, _write_csv(spec.header, table_rows[spec.key]))
    return buffer.getvalue()


def archive_filename(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    return f"plamotrack-export-{stamp}.zip"


# --- blank templates -----------------------------------------------------------


def _column_guide(spec: TableSpec) -> str:
    lines = [f"{spec.key}.csv — {spec.description}", ""]
    for column in spec.columns:
        bits = []
        if column.required:
            bits.append("required")
        if column.is_alternate:
            bits.append(f"optional alternative to {column.mirrors}")
        if column.help:
            bits.append(column.help)
        lines.append(f"  {column.name}: {'; '.join(bits) if bits else 'optional'}")
    return "\n".join(lines) + "\n"


def template_pack() -> bytes:
    """Blank, header-only CSVs in exactly the export's shape, plus a per-file guide.

    Generated from the same specs as the export, so a template can never describe
    a column the importer doesn't accept.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        guides = []
        for spec in TABLE_SPECS:
            archive.writestr(spec.filename, _write_csv(spec.header, []))
            guides.append(_column_guide(spec))
        archive.writestr("starter-sheet.csv", starter_sheet_csv(with_examples=True))
        archive.writestr(
            "COLUMNS.txt",
            "plamotrack import templates\n"
            "===========================\n\n"
            "Fill in whichever files you have data for and import the folder as a\n"
            "zip (or one file at a time). Every file is optional. Leave `id` blank\n"
            "on rows you write by hand.\n\n"
            "If you just want to get your kit list in, ignore all of these and use\n"
            "starter-sheet.csv instead — one row per kit, and the app works out the\n"
            "retailers, orders, and order lines for you.\n\n" + "\n".join(guides),
        )
    return buffer.getvalue()


def starter_sheet_csv(*, with_examples: bool = True) -> str:
    rows = starter_sheet.starter_sheet_examples() if with_examples else []
    return _write_csv(starter_sheet.STARTER_SHEET_HEADER, rows)
