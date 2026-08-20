import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Kit, KitStatus
from app.schemas.kits import KitCreate, KitUpdate
from app.services.write_gate import acquire_write_gate

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


#: Which build date entering a status stamps (#94). One map, consulted by every
#: *live* status writer — `update_kit` (the direct edit and the board drag) and
#: `receive_order`'s pipeline advance — so the derivation cannot drift between
#: them. The CSV importer deliberately does NOT derive: an imported kit whose
#: sheet says `complete` with no completion date stays null rather than acquiring
#: the import's own clock (rule 10 by analogy — import never invents timestamps),
#: and a re-imported archive stays a no-op.
_BUILD_STAMPS: dict[KitStatus, str] = {
    KitStatus.BUILDING: "build_started_at",
    KitStatus.COMPLETE: "build_completed_at",
}


def stamp_build_date(
    kit: Kit,
    entered: KitStatus,
    now: datetime,
    *,
    supplied: frozenset[str] = frozenset(),
) -> None:
    """Entering `building` stamps `build_started_at`; entering `complete` stamps
    `build_completed_at` — each **only when null** (#94).

    Only-when-null is what makes the dates the user's: a value someone set — by
    backfill, by correction, or by an earlier pass through the status — is never
    overwritten by a later drag, and `building` → `backlog` → `building` keeps the
    original start. `supplied` names the fields the same request set explicitly
    (including to null); the derivation never fights an explicit value.
    """
    field = _BUILD_STAMPS.get(entered)
    if field is None or field in supplied:
        return
    if getattr(kit, field) is None:
        setattr(kit, field, now)


async def create_kit(session: AsyncSession, data: KitCreate) -> Kit:
    await acquire_write_gate(session)
    kit = Kit(**data.model_dump())
    if kit.scale is None:
        kit.scale = default_scale_for_grade(kit.grade)
    session.add(kit)
    await session.flush()
    await session.commit()  # durable before the response goes out — see db.session_scope
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
        # Case-insensitive equality, not ILIKE — `M_` is a grade filter, not a
        # pattern that also matches MG (#49). Both sides folded by Postgres, as in
        # `get_or_create_retailer`, so the two folds cannot disagree.
        stmt = stmt.where(func.lower(Kit.grade) == func.lower(grade))
    return list((await session.scalars(stmt)).all())


async def get_kit(session: AsyncSession, kit_id: uuid.UUID) -> Kit:
    kit = await session.get(Kit, kit_id)
    if kit is None:
        raise NotFoundError(f"kit {kit_id} not found")
    return kit


async def update_kit(session: AsyncSession, kit_id: uuid.UUID, data: KitUpdate) -> Kit:
    await acquire_write_gate(session)
    kit = await get_kit(session, kit_id)
    fields = data.model_dump(exclude_unset=True)
    for non_nullable in ("name", "grade", "status"):
        if non_nullable in fields and fields[non_nullable] is None:
            raise InvalidInputError(f"{non_nullable} cannot be null")
    entered: KitStatus | None = None
    if "status" in fields and fields["status"] != kit.status:
        entered = fields["status"]
        kit.status_updated_at = datetime.now(UTC)
    for key, value in fields.items():
        setattr(kit, key, value)
    if entered is not None:
        # After the explicit fields land, so the stamp sees what the request said
        # and yields to it. Same instant as status_updated_at — one clock, not two.
        stamp_build_date(kit, entered, kit.status_updated_at, supplied=frozenset(fields))
    await session.flush()
    # updated_at is generated server-side on UPDATE; refresh so serialization
    # after commit doesn't trigger a lazy load outside the async context.
    await session.refresh(kit)
    await session.commit()
    return kit


def has_applied_upgrades(kit: Kit) -> bool:
    """Whether upgrade stock is recorded as having gone onto this kit.

    Requires `upgrade_applications` to be eager-loaded; a lazy load here would
    raise outside the async context.

    Rule 3 governs both ends of this join, and only one end was guarded.
    `delete_catalog_item` refuses to remove an upgrade that has been applied,
    because the application explains where the stock went. Nothing said the same
    about the kit, so the `ON DELETE CASCADE` on `upgrade_applications.kit_id`
    dropped that history from the other direction — silently, and with the stock
    still counted as consumed.
    """
    return len(kit.upgrade_applications) > 0


async def delete_kit(session: AsyncSession, kit_id: uuid.UUID) -> None:
    await acquire_write_gate(session)
    # FOR UPDATE, because the check below and the delete after it have to be one
    # decision. `apply_upgrade` locks the *upgrade* row, not this one, so without a
    # lock here it can commit an application between the two — and the DELETE then
    # cascades the brand-new row away, which is the exact inconsistency this guard
    # exists to stop. The insert takes FOR KEY SHARE on this row, which conflicts,
    # so holding FOR UPDATE makes the concurrent application wait and then fail its
    # foreign key rather than being silently swallowed.
    kit = await session.scalar(
        select(Kit)
        .where(Kit.id == kit_id)
        .options(selectinload(Kit.upgrade_applications))
        .with_for_update()
    )
    if kit is None:
        raise NotFoundError(f"kit {kit_id} not found")
    if kit.order_item_id is not None:
        # Deleting a spawned kit directly would leave its order line claiming a
        # quantity the collection no longer backs. Undo happens at the order.
        raise ConflictError(
            f"'{kit.name}' was spawned by an order line — edit that order "
            "(reduce the line quantity or remove the line) instead, so the "
            "purchase record and the collection stay consistent"
        )
    if has_applied_upgrades(kit):
        # Deliberately a hard stop with no escape hatch offered, because there
        # isn't one: applications can be recorded but not withdrawn. Saying
        # "remove the application first" would send someone looking for a route
        # that does not exist. The same dead end already applies from the upgrade
        # side, so this is symmetric rather than new.
        raise ConflictError(
            f"'{kit.name}' has {len(kit.upgrade_applications)} upgrade(s) applied to it — "
            "that record is what explains the stock they used, so the kit is kept. "
            "Withdrawing an application isn't supported yet"
        )
    await session.delete(kit)
    await session.flush()
    await session.commit()
