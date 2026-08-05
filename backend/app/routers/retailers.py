from fastapi import APIRouter

from app.db import SessionDep
from app.schemas.orders import RetailerCreate, RetailerRead
from app.services import orders as orders_service

router = APIRouter(prefix="/retailers", tags=["retailers"])


@router.get("", response_model=list[RetailerRead])
async def list_retailers(session: SessionDep):
    return await orders_service.list_retailers(session)


@router.post("", response_model=RetailerRead, status_code=201)
async def create_retailer(data: RetailerCreate, session: SessionDep):
    return await orders_service.create_retailer(session, data)
