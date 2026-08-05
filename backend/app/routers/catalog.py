from fastapi import APIRouter, Query

from app.db import SessionDep
from app.schemas.catalog import CatalogSearchResult
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
