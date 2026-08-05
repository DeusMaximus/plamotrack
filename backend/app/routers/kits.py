import uuid

from fastapi import APIRouter

from app.db import SessionDep
from app.models.enums import KitStatus
from app.schemas.kits import KitCreate, KitRead, KitUpdate
from app.services import kits as kits_service

router = APIRouter(prefix="/kits", tags=["kits"])


@router.get("", response_model=list[KitRead])
async def list_kits(
    session: SessionDep,
    status: KitStatus | None = None,
    grade: str | None = None,
):
    return await kits_service.list_kits(session, status=status, grade=grade)


@router.post("", response_model=KitRead, status_code=201)
async def create_kit(data: KitCreate, session: SessionDep):
    return await kits_service.create_kit(session, data)


@router.get("/{kit_id}", response_model=KitRead)
async def get_kit(kit_id: uuid.UUID, session: SessionDep):
    return await kits_service.get_kit(session, kit_id)


@router.patch("/{kit_id}", response_model=KitRead)
async def update_kit(kit_id: uuid.UUID, data: KitUpdate, session: SessionDep):
    """Partial update — this is also what a Kanban drag calls (status change)."""
    return await kits_service.update_kit(session, kit_id, data)


@router.delete("/{kit_id}", status_code=204)
async def delete_kit(kit_id: uuid.UUID, session: SessionDep):
    await kits_service.delete_kit(session, kit_id)
