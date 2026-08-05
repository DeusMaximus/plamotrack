import uuid
from datetime import date

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import ItemType, text_enum


class Retailer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "retailers"

    name: Mapped[str] = mapped_column(index=True)
    url: Mapped[str | None]
    notes: Mapped[str | None]


class Order(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "orders"

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    order_date: Mapped[date]
    delivery_service: Mapped[str | None]  # null = local pickup/purchase (§3.8)
    tracking_number: Mapped[str | None]
    tracking_url: Mapped[str | None]
    shipping_cost_minor: Mapped[int | None]
    currency_code: Mapped[str] = mapped_column(String(3))

    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(UUIDPrimaryKeyMixin, Base):
    """Dispatch point between orders and the four catalog tables (§3.9).

    Quantity semantics differ by item_type — kit lines fan out into new `kits`
    rows, catalog lines increment `quantity_on_hand`. The dispatch lives in
    app/services/orders.py.
    """

    __tablename__ = "order_items"

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    item_type: Mapped[ItemType] = mapped_column(text_enum(ItemType, "item_type"))
    # Points into tools/consumables/upgrades depending on item_type; null for kit
    # lines (kits are spawned fresh). No DB-level FK is possible across three tables.
    catalog_ref_id: Mapped[uuid.UUID | None]
    quantity: Mapped[int]
    unit_price_minor: Mapped[int]
    currency_code: Mapped[str] = mapped_column(String(3))
    converted_price_aud_minor: Mapped[int | None]  # snapshot at entry time (§6)

    order: Mapped[Order] = relationship(back_populates="items")
    # Kits spawned by this line (kit-type lines only); read-only convenience.
    kits: Mapped[list["Kit"]] = relationship(viewonly=True)

    @property
    def spawned_kit_ids(self) -> list[uuid.UUID]:
        """Requires `kits` to be eager-loaded; feeds OrderItemRead serialization."""
        return [kit.id for kit in self.kits]

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_minor >= 0", name="unit_price_non_negative"),
    )


from app.models.kits import Kit  # noqa: E402  (resolve "Kit" for the viewonly relationship)
