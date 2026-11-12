from fastapi import APIRouter

from app.db import SessionDep
from app.schemas.summary import SummaryRead
from app.services.summary import collection_summary

router = APIRouter(prefix="/summary", tags=["summary"])


@router.get("", response_model=SummaryRead)
async def read_summary(session: SessionDep) -> SummaryRead:
    """Kits per pipeline status and orders per stage (§13.2) — what Home's
    headings show, from one snapshot. The same function serves the `get_summary`
    MCP tool."""
    return await collection_summary(session)
