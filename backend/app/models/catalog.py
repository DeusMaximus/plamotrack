import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class Tool(UUIDPrimaryKeyMixin, Base):
    """Fungible, durable — catalog + on-hand quantity in one row (§3.3)."""

    __tablename__ = "tools"

    name: Mapped[str] = mapped_column(index=True)
    category: Mapped[str]
    quantity_on_hand: Mapped[int] = mapped_column(default=0)
    unit_cost_reference: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    condition_notes: Mapped[str | None]

    __table_args__ = (CheckConstraint("quantity_on_hand >= 0", name="quantity_non_negative"),)


class Consumable(UUIDPrimaryKeyMixin, Base):
    """Fungible, depletable — decrement on use, no row-level state tracking (§3.4)."""

    __tablename__ = "consumables"

    name: Mapped[str] = mapped_column(index=True)
    category: Mapped[str]
    quantity_on_hand: Mapped[int] = mapped_column(default=0)
    low_stock_threshold: Mapped[int | None]

    __table_args__ = (CheckConstraint("quantity_on_hand >= 0", name="quantity_non_negative"),)


class Upgrade(UUIDPrimaryKeyMixin, Base):
    """Fungible stock plus a relationship to the kits it's applied to (§3.5)."""

    __tablename__ = "upgrades"

    name: Mapped[str] = mapped_column(index=True)
    manufacturer: Mapped[str]
    quantity_on_hand: Mapped[int] = mapped_column(default=0)

    __table_args__ = (CheckConstraint("quantity_on_hand >= 0", name="quantity_non_negative"),)


class UpgradeApplication(UUIDPrimaryKeyMixin, Base):
    """Join table: which upgrades have been used on which kits (§3.6)."""

    __tablename__ = "upgrade_applications"

    upgrade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("upgrades.id", ondelete="CASCADE"), index=True
    )
    kit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kits.id", ondelete="CASCADE"), index=True)
    quantity_used: Mapped[int]
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (CheckConstraint("quantity_used > 0", name="quantity_used_positive"),)
