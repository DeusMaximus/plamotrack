import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin


class Tool(UUIDPrimaryKeyMixin, Base):
    """Fungible, durable — catalog + on-hand quantity in one row (§3.3)."""

    __tablename__ = "tools"

    name: Mapped[str] = mapped_column(index=True)
    category: Mapped[str]
    quantity_on_hand: Mapped[int] = mapped_column(default=0)
    # Informational "last known price" (§6). Integer minor units plus the code they
    # were recorded under, like every other amount — a bare number here could not be
    # compared or converted, and read differently depending on who was looking.
    unit_cost_reference_minor: Mapped[int | None]
    unit_cost_reference_currency: Mapped[str | None] = mapped_column(String(3))
    condition_notes: Mapped[str | None]

    __table_args__ = (
        CheckConstraint("quantity_on_hand >= 0", name="quantity_non_negative"),
        CheckConstraint("unit_cost_reference_minor >= 0", name="unit_cost_reference_non_negative"),
        CheckConstraint(
            "(unit_cost_reference_minor IS NULL) = (unit_cost_reference_currency IS NULL)",
            name="unit_cost_reference_currency_paired",
        ),
    )


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


class DisplayItem(UUIDPrimaryKeyMixin, Base):
    """Fungible, durable, and deliberately *not* linked to kits (§3.5a, #126).

    Stands, bases, diorama scenery, backdrop panels — bought to display models
    rather than to become part of one. Structurally this is `Tool` without the
    cost pair: catalog and on-hand quantity in one row.

    No join table to `kits`, unlike `upgrades`, and the difference is the point.
    `upgrade_applications` decrements stock because an applied upgrade is *spent* —
    a decal sheet is consumed, metal thrusters stay installed. Display gear is the
    opposite: the stand under one kit this month is under another the next, so a
    recorded link would be wrong most of the time, and every link row would still
    need the guard machinery `upgrade_applications` carries to protect a fact with
    no durability. Quantity is the whole of what is worth knowing.

    No build status either. A row reading `quantity_on_hand: 5` cannot carry one
    honestly, which is exactly why `kits` is one row per physical item (§3.1).
    Something that genuinely needs individual build state is kit-shaped.
    """

    __tablename__ = "display_items"

    name: Mapped[str] = mapped_column(index=True)
    # Required, and load-bearing rather than decoration: it is the only field that
    # answers "how many stands do I have" without inferring stand-ness from product
    # names, which is what an MCP agent would otherwise have to do (#126, #127).
    category: Mapped[str]
    # Which kit scale the piece suits — "1/144", "1/100". Free text and nullable,
    # following `kits.scale`, but with no grade to derive a default from. Null means
    # non-scale or simply not recorded.
    scale: Mapped[str | None]
    # Nullable, unlike `upgrades.manufacturer`: a commercial set has one, a
    # scratch-built terrain piece does not, and requiring it is friction with no
    # invariant behind it.
    manufacturer: Mapped[str | None]
    quantity_on_hand: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str | None]

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

    # Read-only convenience for the surfaces that list a kit's applications (#61);
    # writes go through the id column, and the CASCADE lives on the FK, not here.
    upgrade: Mapped["Upgrade"] = relationship(viewonly=True)

    __table_args__ = (CheckConstraint("quantity_used > 0", name="quantity_used_positive"),)
