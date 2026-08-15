import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Kit, Upgrade, UpgradeApplication
from app.services.catalog import lock_catalog_row
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
        raise InvalidInputError("quantity must be a positive integer")

    await acquire_write_gate(session)
    # Catalog row first, then the kit — the order every writer takes (see
    # `_lock_catalog_targets`). Reversing it here would put this back in a cycle with
    # order edits, which lock catalog targets and then the kits a line spawned.
    upgrade = await lock_catalog_row(session, Upgrade, upgrade_id)
    if upgrade is None:
        raise NotFoundError(f"upgrade {upgrade_id} not found")
    kit = await session.get(Kit, kit_id)
    if kit is None:
        raise NotFoundError(f"kit {kit_id} not found")

    if upgrade.quantity_on_hand < quantity:
        raise ConflictError(
            f"insufficient stock for '{upgrade.name}': "
            f"{upgrade.quantity_on_hand} on hand, {quantity} requested"
        )

    upgrade.quantity_on_hand -= quantity
    application = UpgradeApplication(upgrade_id=upgrade.id, kit_id=kit.id, quantity_used=quantity)
    session.add(application)
    await session.flush()
    await session.commit()
    return application
