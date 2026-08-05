import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import ConflictError, InvalidInputError, NotFoundError
from app.models import Kit, Upgrade, UpgradeApplication


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

    upgrade = await session.get(Upgrade, upgrade_id, with_for_update=True)
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
