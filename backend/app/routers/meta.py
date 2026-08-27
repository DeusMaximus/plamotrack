from fastapi import APIRouter

from app.db import SessionDep
from app.schemas.meta import MetaRead
from app.services.meta import instance_meta

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("", response_model=MetaRead)
async def read_meta(session: SessionDep) -> MetaRead:
    return await instance_meta(session)
