import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.enums import (
    ItemType,
    PackingQuality,
    ShippingSpeed,
    WouldOrderAgain,
    text_enum,
)


class Retailer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "retailers"

    name: Mapped[str] = mapped_column(index=True)
    url: Mapped[str | None]
    # Experience report card (all optional — filled in after you've dealt with them)
    rating: Mapped[int | None]  # overall, 1–5
    packing_quality: Mapped[PackingQuality | None] = mapped_column(
        text_enum(PackingQuality, "packing_quality")
    )
    shipping_speed: Mapped[ShippingSpeed | None] = mapped_column(
        text_enum(ShippingSpeed, "shipping_speed")
    )
    would_order_again: Mapped[WouldOrderAgain | None] = mapped_column(
        text_enum(WouldOrderAgain, "would_order_again")
    )
    notes: Mapped[str | None]

    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)


class Order(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "orders"

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    order_date: Mapped[date]
    # The retailer's own reference number, for support contact ("order lost",
    # "item missing"). Informational only — deliberately NOT unique: it's only
    # unique per retailer, never rely on it as an identifier internally.
    order_number: Mapped[str | None]
    delivery_service: Mapped[str | None]  # null = local pickup/purchase (§3.8)
    tracking_number: Mapped[str | None]
    tracking_url: Mapped[str | None]
    shipping_cost_minor: Mapped[int | None]
    currency_code: Mapped[str] = mapped_column(String(3))
    # Null = pending (not yet arrived). Catalog stock increments are applied when
    # the order is received, not at entry — quantity_on_hand means "physically
    # on hand", not "on hand + on order".
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
    # What this line cost in the instance's reference currency, captured at entry
    # time and never recomputed (§6). The code is stored per row rather than read
    # from config on the way out: an amount whose currency can be changed from an
    # env var isn't a snapshot, it's a number that quietly means something else.
    converted_price_minor: Mapped[int | None]
    converted_currency_code: Mapped[str | None] = mapped_column(String(3))

    order: Mapped[Order] = relationship(back_populates="items")
    # Kits spawned by this line (kit-type lines only); read-only convenience.
    # Ordered to match `_line_kits`, because "the first spawned kit" is a value the
    # order editor hydrates from and the service compares against — unordered, the
    # same line could seed the form from a different kit on every load.
    kits: Mapped[list["Kit"]] = relationship(viewonly=True, order_by="(Kit.created_at, Kit.id)")

    @property
    def spawned_kit_ids(self) -> list[uuid.UUID]:
        """Requires `kits` to be eager-loaded; feeds OrderItemRead serialization."""
        return [kit.id for kit in self.kits]

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_minor >= 0", name="unit_price_non_negative"),
        CheckConstraint("converted_price_minor >= 0", name="converted_price_non_negative"),
        # A converted amount with no currency is the bug this pair replaced.
        CheckConstraint(
            "(converted_price_minor IS NULL) = (converted_currency_code IS NULL)",
            name="converted_price_currency_paired",
        ),
    )


from app.models.kits import Kit  # noqa: E402  (resolve "Kit" for the viewonly relationship)
