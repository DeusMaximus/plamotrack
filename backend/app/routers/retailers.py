import uuid

from fastapi import APIRouter

from app.db import SessionDep
from app.schemas.orders import RetailerCreate, RetailerRead, RetailerUpdate
from app.services import orders as orders_service

router = APIRouter(prefix="/retailers", tags=["retailers"])


@router.get("", response_model=list[RetailerRead])
async def list_retailers(session: SessionDep):
    return await orders_service.list_retailers(session)


@router.post("", response_model=RetailerRead, status_code=201)
async def create_retailer(data: RetailerCreate, session: SessionDep):
    return await orders_service.create_retailer(session, data)


@router.patch("/{retailer_id}", response_model=RetailerRead)
async def update_retailer(retailer_id: uuid.UUID, data: RetailerUpdate, session: SessionDep):
    return await orders_service.update_retailer(session, retailer_id, data)


@router.delete("/{retailer_id}", status_code=204)
async def delete_retailer(retailer_id: uuid.UUID, session: SessionDep):
    """409 if the retailer has orders — order history is kept."""
    await orders_service.delete_retailer(session, retailer_id)
