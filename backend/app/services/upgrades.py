import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app import error_codes
from app.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Kit, Upgrade, UpgradeApplication
from app.services.catalog import guard_stock_ceiling, lock_catalog_row
from app.services.numeric import require_int4
from app.services.write_gate import acquire_write_gate


async def apply_upgrade(
    session: AsyncSession,
    upgrade_id: uuid.UUID,
    kit_id: uuid.UUID,
    quantity: int,
) -> UpgradeApplication:
    """Record an upgrade being used on a kit and decrement stock atomically.
    Row-locked so concurrent writers (UI, REST, MCP agents) can't oversell stock."""
    if quantity <= 0:
        raise InvalidInputError(
            "quantity must be a positive integer",
            code=error_codes.UPGRADE_APPLICATION_QUANTITY_INVALID,
            params={"quantity": quantity},
        )
    # Both bounds here rather than only the floor, and for the same reason the floor
    # is here rather than in the schema: `UpgradeApplyRequest` binds the REST caller,
    # and the MCP tool passes a bare int to this function (rule 1 — the invariant
    # belongs where both callers meet). Without it the two front doors answered the
    # same value differently: REST 422, MCP "insufficient stock … 2147483648
    # requested" as a 409, because the stock check happened to catch it first. That
    # is the wrong answer even though it is a refusal — an unstorable quantity is the
    # caller's mistake, not the stored state's, at any stock level (#74).
    try:
        require_int4(quantity, f"quantity '{quantity:,}'")
    except ValueError as exc:
        raise InvalidInputError(
            str(exc),
            code=error_codes.VALUE_OUT_OF_RANGE,
            params={"value": quantity},
        ) from exc

    await acquire_write_gate(session)
    # Catalog row first, then the kit — the order every writer takes (see
    # `_lock_catalog_targets`). Reversing it here would put this back in a cycle with
    # order edits, which lock catalog targets and then the kits a line spawned.
    upgrade = await lock_catalog_row(session, Upgrade, upgrade_id)
    if upgrade is None:
        raise NotFoundError(
            f"upgrade {upgrade_id} not found",
            code=error_codes.CATALOG_ITEM_NOT_FOUND,
            params={"item_type": "upgrade", "item_id": upgrade_id},
        )
    kit = await session.get(Kit, kit_id)
    if kit is None:
        raise NotFoundError(
            f"kit {kit_id} not found",
            code=error_codes.KIT_NOT_FOUND,
            params={"kit_id": kit_id},
        )

    if upgrade.quantity_on_hand < quantity:
        raise ConflictError(
            f"insufficient stock for '{upgrade.name}': "
            f"{upgrade.quantity_on_hand} on hand, {quantity} requested",
            code=error_codes.STOCK_INSUFFICIENT,
            params={
                "name": upgrade.name,
                "on_hand": upgrade.quantity_on_hand,
                "requested": quantity,
            },
        )

    upgrade.quantity_on_hand -= quantity
    application = UpgradeApplication(upgrade_id=upgrade.id, kit_id=kit.id, quantity_used=quantity)
    session.add(application)
    await session.flush()
    await session.commit()
    return application


async def list_kit_applications(
    session: AsyncSession, kit_id: uuid.UUID
) -> list[UpgradeApplication]:
    """The upgrade applications on one kit, upgrade rows eager-loaded, oldest first.

    The read side of withdrawal (#61): before this existed nothing exposed a kit's
    applications, so the guards that referenced them pointed at records the caller
    could not see. REST serves it at GET /kits/{id}/applications; the MCP get_kit
    embeds it — one loader for both (rule 1).
    """
    kit = await session.get(Kit, kit_id)
    if kit is None:
        raise NotFoundError(
            f"kit {kit_id} not found",
            code=error_codes.KIT_NOT_FOUND,
            params={"kit_id": kit_id},
        )
    stmt = (
        select(UpgradeApplication)
        .where(UpgradeApplication.kit_id == kit_id)
        .options(selectinload(UpgradeApplication.upgrade))
        .order_by(UpgradeApplication.applied_at, UpgradeApplication.id)
    )
    return list((await session.scalars(stmt)).all())


@dataclass(frozen=True)
class UpgradeWithdrawal:
    """What a withdrawal did — echoed by the MCP tool; REST answers 204 instead."""

    application_id: uuid.UUID
    upgrade_id: uuid.UUID
    kit_id: uuid.UUID
    quantity_used: int
    stock_restored: bool
    quantity_on_hand: int


async def withdraw_upgrade_application(
    session: AsyncSession,
    application_id: uuid.UUID,
    *,
    restore_stock: bool,
    upgrade_id: uuid.UUID | None = None,
) -> UpgradeWithdrawal:
    """Remove a recorded application; the caller states whether stock returns (§3.6, #61).

    `restore_stock` is required and has no default on any surface, deliberately:
    whether the part goes back into stock is a fact about the physical world —
    recorded against the wrong kit means it never left the box; a decal torn on
    the way down is destroyed — and nothing stored can infer it. Whichever default
    we picked would be silently wrong half the time, so the caller says.

    A withdrawal removes the whole application: it is one event, not a running
    balance, so restoring returns all of `quantity_used`. A restore that would
    push stock past what the column holds is refused (the stored state refusing,
    #74) and the application stays.

    `upgrade_id`, when given, is the REST route's pairing check — the application
    must belong to that upgrade or the URL named a row that isn't there (404).
    """
    await acquire_write_gate(session)
    application = await session.get(UpgradeApplication, application_id)
    if application is None:
        raise NotFoundError(
            f"upgrade application {application_id} not found",
            code=error_codes.UPGRADE_APPLICATION_NOT_FOUND,
            params={"application_id": application_id},
        )
    if upgrade_id is not None and application.upgrade_id != upgrade_id:
        raise NotFoundError(
            f"application {application_id} does not belong to upgrade {upgrade_id}",
            code=error_codes.UPGRADE_APPLICATION_NOT_FOUND,
            params={"application_id": application_id},
        )
    # Same lock, same ordering, as apply_upgrade: the catalog row serializes every
    # stock writer (rule 7), and it is taken whether or not stock moves so the two
    # withdrawal flavours hold identical ground against a concurrent apply/delete.
    upgrade = await lock_catalog_row(session, Upgrade, application.upgrade_id)
    if upgrade is None:
        # Unreachable while delete_catalog_item refuses applied upgrades and the FK
        # cascades — kept so this function refuses rather than shrugs if that changes.
        raise NotFoundError(
            f"upgrade {application.upgrade_id} not found",
            code=error_codes.CATALOG_ITEM_NOT_FOUND,
            params={"item_type": "upgrade", "item_id": application.upgrade_id},
        )
    if restore_stock:
        upgrade.quantity_on_hand = guard_stock_ceiling(
            upgrade.name, upgrade.quantity_on_hand + application.quantity_used
        )
    result = UpgradeWithdrawal(
        application_id=application.id,
        upgrade_id=upgrade.id,
        kit_id=application.kit_id,
        quantity_used=application.quantity_used,
        stock_restored=restore_stock,
        quantity_on_hand=upgrade.quantity_on_hand,
    )
    await session.delete(application)
    await session.flush()
    await session.commit()
    return result
