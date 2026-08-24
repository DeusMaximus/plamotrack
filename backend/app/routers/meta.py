from fastapi import APIRouter

from app.schemas.meta import MetaRead
from app.services.meta import instance_meta

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("", response_model=MetaRead)
async def read_meta() -> MetaRead:
    return instance_meta()
