from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.config import get_settings

router = APIRouter(prefix="/meta", tags=["meta"])


class MetaRead(BaseModel):
    """Instance-level settings a client needs before it can render a form."""

    version: str
    #: Default currency for new entries and for the conversion snapshot (§6).
    #: Stored per row at entry time, so changing this never restates history.
    reference_currency: str


@router.get("", response_model=MetaRead)
async def read_meta() -> MetaRead:
    return MetaRead(version=__version__, reference_currency=get_settings().reference_currency)
