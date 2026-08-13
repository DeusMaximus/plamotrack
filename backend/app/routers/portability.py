from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response

from app.db import SessionDep
from app.schemas.portability import ImportMode, ImportPlan, ImportResult
from app.services import portability
from app.services.portability import exporting, importing

router = APIRouter(tags=["import/export"])


def _attachment(content: bytes | str, filename: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/archive")
async def export_archive(session: SessionDep) -> Response:
    """The whole collection as a zip of CSVs plus a manifest carrying the export
    and schema versions. Re-importable, and readable in any spreadsheet."""
    return _attachment(
        await exporting.export_archive(session),
        exporting.archive_filename(),
        "application/zip",
    )


@router.get("/export/templates")
async def export_templates() -> Response:
    """Blank, header-only CSVs in the export's exact shape, plus a column guide
    and the starter sheet."""
    return _attachment(portability.template_pack(), "plamotrack-templates.zip", "application/zip")


@router.get("/export/starter-sheet.csv")
async def export_starter_sheet(examples: bool = True) -> Response:
    """One row per kit — the onboarding path for someone coming off a spreadsheet."""
    return _attachment(
        portability.starter_sheet_csv(with_examples=examples),
        "plamotrack-starter-sheet.csv",
        "text/csv; charset=utf-8",
    )


@router.get("/export/{table_key}.csv")
async def export_table(table_key: str, session: SessionDep) -> Response:
    return _attachment(
        await exporting.export_table_csv(session, table_key),
        f"plamotrack-{table_key}.csv",
        "text/csv; charset=utf-8",
    )


@router.post("/import/preview", response_model=ImportPlan)
async def preview_import(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    mode: Annotated[ImportMode, Form()] = ImportMode.MERGE,
) -> ImportPlan:
    """Read-only: resolves every row against the collection and returns exactly what
    an apply would do. Nothing is written."""
    return await importing.preview_import(
        session, file.filename or "upload.csv", await file.read(), mode
    )


@router.post("/import/apply", response_model=ImportResult)
async def apply_import(
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    mode: Annotated[ImportMode, Form()] = ImportMode.MERGE,
    plan_hash: Annotated[str | None, Form()] = None,
    confirm: Annotated[str | None, Form()] = None,
) -> ImportResult:
    """Re-plans the same file and refuses (409) if the outcome no longer matches the
    previewed `plan_hash`. Runs as one transaction — any bad row imports nothing.

    `plan_hash` is required and stays typed as optional here so the service raises
    the domain error (422) that says *why*, rather than FastAPI rejecting the form
    field with a validation shape that doesn't mention previewing (rule 6)."""
    return await importing.apply_import(
        session, file.filename or "upload.csv", await file.read(), mode, plan_hash, confirm
    )
