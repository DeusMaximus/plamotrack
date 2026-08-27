from fastapi import APIRouter

from app.db import SessionDep
from app.schemas.settings import InstanceSettingsRead, InstanceSettingsUpdate
from app.services import instance_settings as settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=InstanceSettingsRead)
async def read_settings(session: SessionDep):
    """The effective instance settings — one row, shared by every client (§6.1)."""
    return await settings_service.get_instance_settings(session)


@router.patch("", response_model=InstanceSettingsRead)
async def update_settings(session: SessionDep, payload: InstanceSettingsUpdate):
    """Update only the supplied fields. Values are validated and canonicalised by
    the service; concurrent updates serialize on the write gate."""
    return await settings_service.update_instance_settings(session, payload)
