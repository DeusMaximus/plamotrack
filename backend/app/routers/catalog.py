import uuid

from fastapi import APIRouter, Query

from app.db import SessionDep
from app.schemas.catalog import (
    CatalogSearchResult,
    StockAdjustmentRequest,
    StockAdjustmentResult,
)
from app.services import catalog as catalog_service

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/search", response_model=list[CatalogSearchResult])
async def search_catalog(
    session: SessionDep,
    q: str = Query(min_length=1),
):
    """Typeahead across tools/consumables/upgrades — the select-or-create flow's
    search half (§3.9 duplicate-catalog prevention)."""
    return await catalog_service.search(session, q)


@router.post("/{catalog_id}/adjust", response_model=StockAdjustmentResult)
async def adjust_stock(catalog_id: uuid.UUID, data: StockAdjustmentRequest, session: SessionDep):
    """Adjust stock by a signed delta, resolving the id across the three catalog
    tables — the same service call the MCP `adjust_stock` tool has always made
    (rule 1). Lives on `/catalog` rather than `/inventory/{type}/{id}` because the
    service resolves the type itself, exactly as the cross-table search does.

    409 if the result would be negative; 404 if no tool, consumable or upgrade
    carries that id."""
    return await catalog_service.adjust_stock(session, catalog_id, data.delta, data.reason)
