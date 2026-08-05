import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import InvalidInputError, NotFoundError
from app.models import Kit, KitStatus
from app.schemas.kits import KitCreate, KitUpdate

# Derived default scale per grade, overridable per kit (§3.1). SD kits are non-scale.
GRADE_DEFAULT_SCALE: dict[str, str | None] = {
    "HG": "1/144",
    "RG": "1/144",
    "EG": "1/144",
    "MG": "1/100",
    "MGEX": "1/100",
    "MGSD": None,
    "RE/100": "1/100",
    "FM": "1/100",
    "PG": "1/60",
    "SD": None,
}


def default_scale_for_grade(grade: str) -> str | None:
    return GRADE_DEFAULT_SCALE.get(grade.strip().upper())


async def create_kit(session: AsyncSession, data: KitCreate) -> Kit:
    kit = Kit(**data.model_dump())
    if kit.scale is None:
        kit.scale = default_scale_for_grade(kit.grade)
    session.add(kit)
    await session.flush()
    return kit


async def list_kits(
    session: AsyncSession,
    status: KitStatus | None = None,
    grade: str | None = None,
) -> list[Kit]:
    stmt = select(Kit).order_by(Kit.created_at, Kit.id)
    if status is not None:
        stmt = stmt.where(Kit.status == status)
    if grade is not None:
        stmt = stmt.where(Kit.grade.ilike(grade))
    return list((await session.scalars(stmt)).all())


async def get_kit(session: AsyncSession, kit_id: uuid.UUID) -> Kit:
    kit = await session.get(Kit, kit_id)
    if kit is None:
        raise NotFoundError(f"kit {kit_id} not found")
    return kit


async def update_kit(session: AsyncSession, kit_id: uuid.UUID, data: KitUpdate) -> Kit:
    kit = await get_kit(session, kit_id)
    fields = data.model_dump(exclude_unset=True)
    for non_nullable in ("name", "grade", "status"):
        if non_nullable in fields and fields[non_nullable] is None:
            raise InvalidInputError(f"{non_nullable} cannot be null")
    if "status" in fields and fields["status"] != kit.status:
        kit.status_updated_at = datetime.now(UTC)
    for key, value in fields.items():
        setattr(kit, key, value)
    await session.flush()
    # updated_at is generated server-side on UPDATE; refresh so serialization
    # after commit doesn't trigger a lazy load outside the async context.
    await session.refresh(kit)
    return kit


async def delete_kit(session: AsyncSession, kit_id: uuid.UUID) -> None:
    kit = await get_kit(session, kit_id)
    await session.delete(kit)
    await session.flush()
