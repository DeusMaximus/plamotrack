import uuid

from fastapi import APIRouter

from app.db import SessionDep
from app.models import Consumable, ItemType, Tool, Upgrade
from app.schemas.catalog import (
    ConsumableCreate,
    ConsumableRead,
    ConsumableUpdate,
    ToolCreate,
    ToolRead,
    ToolUpdate,
    UpgradeApplicationRead,
    UpgradeApplyRequest,
    UpgradeCreate,
    UpgradeRead,
    UpgradeUpdate,
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


@router.patch("/tools/{tool_id}", response_model=ToolRead)
async def update_tool(tool_id: uuid.UUID, data: ToolUpdate, session: SessionDep):
    return await catalog_service.update_catalog_item(session, ItemType.TOOL, tool_id, data)


@router.delete("/tools/{tool_id}", status_code=204)
async def delete_tool(tool_id: uuid.UUID, session: SessionDep):
    await catalog_service.delete_catalog_item(session, ItemType.TOOL, tool_id)


@router.get("/consumables", response_model=list[ConsumableRead])
async def list_consumables(session: SessionDep):
    return await catalog_service.list_catalog(session, Consumable)


@router.post("/consumables", response_model=ConsumableRead, status_code=201)
async def create_consumable(data: ConsumableCreate, session: SessionDep):
    return await catalog_service.create_consumable(session, data)


@router.patch("/consumables/{consumable_id}", response_model=ConsumableRead)
async def update_consumable(consumable_id: uuid.UUID, data: ConsumableUpdate, session: SessionDep):
    return await catalog_service.update_catalog_item(
        session, ItemType.CONSUMABLE, consumable_id, data
    )


@router.delete("/consumables/{consumable_id}", status_code=204)
async def delete_consumable(consumable_id: uuid.UUID, session: SessionDep):
    await catalog_service.delete_catalog_item(session, ItemType.CONSUMABLE, consumable_id)


@router.get("/upgrades", response_model=list[UpgradeRead])
async def list_upgrades(session: SessionDep):
    return await catalog_service.list_catalog(session, Upgrade)


@router.post("/upgrades", response_model=UpgradeRead, status_code=201)
async def create_upgrade(data: UpgradeCreate, session: SessionDep):
    return await catalog_service.create_upgrade(session, data)


@router.patch("/upgrades/{upgrade_id}", response_model=UpgradeRead)
async def update_upgrade(upgrade_id: uuid.UUID, data: UpgradeUpdate, session: SessionDep):
    return await catalog_service.update_catalog_item(session, ItemType.UPGRADE, upgrade_id, data)


@router.delete("/upgrades/{upgrade_id}", status_code=204)
async def delete_upgrade(upgrade_id: uuid.UUID, session: SessionDep):
    await catalog_service.delete_catalog_item(session, ItemType.UPGRADE, upgrade_id)


@router.post("/upgrades/{upgrade_id}/apply", response_model=UpgradeApplicationRead, status_code=201)
async def apply_upgrade(
    upgrade_id: uuid.UUID,
    data: UpgradeApplyRequest,
    session: SessionDep,
):
    """Record an upgrade used on a kit; decrements stock (§4)."""
    return await upgrades_service.apply_upgrade(session, upgrade_id, data.kit_id, data.quantity)
