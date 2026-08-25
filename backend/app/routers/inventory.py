import uuid

from fastapi import APIRouter

from app.db import SessionDep
from app.models import Consumable, DisplayItem, ItemType, Tool, Upgrade
from app.schemas.catalog import (
    ConsumableCreate,
    ConsumableRead,
    ConsumableUpdate,
    DisplayItemCreate,
    DisplayItemRead,
    DisplayItemUpdate,
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
async def list_tools(session: SessionDep, category: str | None = None):
    """Optionally filtered by category — exact value, case-insensitively; the
    spellings in use come from /tools/categories (#127)."""
    return await catalog_service.list_catalog(session, Tool, category=category)


# Declared before any parameterised sibling out of the same caution as /kits/series;
# today the only /tools/{...} routes are PATCH and DELETE, so GET cannot collide.
@router.get("/tools/categories", response_model=list[str])
async def list_tool_categories(session: SessionDep):
    """Distinct tool categories in use, most frequent first — feeds the tool form's
    typeahead so free text stays de-duplicated in practice (#127, the #96 shape)."""
    return await catalog_service.list_catalog_categories(session, Tool)


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
async def list_consumables(session: SessionDep, category: str | None = None):
    return await catalog_service.list_catalog(session, Consumable, category=category)


@router.get("/consumables/categories", response_model=list[str])
async def list_consumable_categories(session: SessionDep):
    return await catalog_service.list_catalog_categories(session, Consumable)


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


@router.delete("/upgrades/{upgrade_id}/applications/{application_id}", status_code=204)
async def withdraw_upgrade_application(
    upgrade_id: uuid.UUID,
    application_id: uuid.UUID,
    restore_stock: bool,
    session: SessionDep,
):
    """Withdraw a recorded application (§3.6, #61). `restore_stock` is required —
    no default, deliberately: true when the part never actually left the box
    (wrong kit, mis-click), false when it was consumed or destroyed. plamotrack
    cannot infer which happened, so the caller states it."""
    await upgrades_service.withdraw_upgrade_application(
        session, application_id, restore_stock=restore_stock, upgrade_id=upgrade_id
    )


@router.get("/display-items", response_model=list[DisplayItemRead])
async def list_display_items(session: SessionDep, category: str | None = None):
    return await catalog_service.list_catalog(session, DisplayItem, category=category)


@router.get("/display-items/categories", response_model=list[str])
async def list_display_item_categories(session: SessionDep):
    return await catalog_service.list_catalog_categories(session, DisplayItem)


@router.post("/display-items", response_model=DisplayItemRead, status_code=201)
async def create_display_item(data: DisplayItemCreate, session: SessionDep):
    """Stands, bases, diorama scenery — display gear, tracked by quantity only and
    deliberately not linked to kits (§3.5a)."""
    return await catalog_service.create_display_item(session, data)


@router.patch("/display-items/{display_item_id}", response_model=DisplayItemRead)
async def update_display_item(
    display_item_id: uuid.UUID, data: DisplayItemUpdate, session: SessionDep
):
    return await catalog_service.update_catalog_item(
        session, ItemType.DISPLAY, display_item_id, data
    )


@router.delete("/display-items/{display_item_id}", status_code=204)
async def delete_display_item(display_item_id: uuid.UUID, session: SessionDep):
    await catalog_service.delete_catalog_item(session, ItemType.DISPLAY, display_item_id)
