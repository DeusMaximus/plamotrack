import uuid

from fastapi import APIRouter

from app.db import SessionDep
from app.models import Consumable, Tool, Upgrade
from app.schemas.catalog import (
    ConsumableCreate,
    ConsumableRead,
    ToolCreate,
    ToolRead,
    UpgradeApplicationRead,
    UpgradeApplyRequest,
    UpgradeCreate,
    UpgradeRead,
)
from app.services import catalog as catalog_service
from app.services import upgrades as upgrades_service

router = APIRouter(tags=["inventory"])


@router.get("/tools", response_model=list[ToolRead])
async def list_tools(session: SessionDep):
    return await catalog_service.list_catalog(session, Tool)


@router.post("/tools", response_model=ToolRead, status_code=201)
async def create_tool(data: ToolCreate, session: SessionDep):
    return await catalog_service.create_tool(session, data)


@router.get("/consumables", response_model=list[ConsumableRead])
async def list_consumables(session: SessionDep):
    return await catalog_service.list_catalog(session, Consumable)


@router.post("/consumables", response_model=ConsumableRead, status_code=201)
async def create_consumable(data: ConsumableCreate, session: SessionDep):
    return await catalog_service.create_consumable(session, data)


@router.get("/upgrades", response_model=list[UpgradeRead])
async def list_upgrades(session: SessionDep):
    return await catalog_service.list_catalog(session, Upgrade)


@router.post("/upgrades", response_model=UpgradeRead, status_code=201)
async def create_upgrade(data: UpgradeCreate, session: SessionDep):
    return await catalog_service.create_upgrade(session, data)


@router.post("/upgrades/{upgrade_id}/apply", response_model=UpgradeApplicationRead, status_code=201)
async def apply_upgrade(
    upgrade_id: uuid.UUID,
    data: UpgradeApplyRequest,
    session: SessionDep,
):
    """Record an upgrade used on a kit; decrements stock (§4)."""
    return await upgrades_service.apply_upgrade(session, upgrade_id, data.kit_id, data.quantity)
