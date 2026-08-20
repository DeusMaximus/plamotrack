import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import KitStatus, text_enum


class Kit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per *physical* kit — duplicate purchases are separate rows (§3.1)."""

    __tablename__ = "kits"

    name: Mapped[str]
    grade: Mapped[str]
    scale: Mapped[str | None]
    kit_number: Mapped[str | None]
    # Which series the subject is from ("Iron-Blooded Orphans"). Free text like
    # grade/scale — user-extensible, no registry (#96); a distinct-values endpoint
    # feeds the typeahead so near-miss spellings stay rare rather than impossible.
    series: Mapped[str | None]
    status: Mapped[KitStatus] = mapped_column(
        text_enum(KitStatus, "kit_status"), default=KitStatus.BACKLOG, index=True
    )
    status_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    rating: Mapped[int | None]
    # When the build started / was declared finished (#94). Nullable, owned by the
    # user: a transition to building/complete stamps one only when it is null, and
    # both stay editable afterwards — the app records when you told it, and you
    # correct it to when it actually happened. Deliberately two columns, not a
    # status-event table, so they measure elapsed time, not active time (§3.1).
    # Never backfilled by migration: a guessed date is indistinguishable from an
    # asserted one. The importer never invents them either (rule 10 analogy).
    build_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    build_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    build_notes: Mapped[str | None] = mapped_column(Text)
    # Provenance: which order line spawned this kit. Nullable — Backlog kits and
    # direct additions exist before/without any order.
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("order_items.id", ondelete="SET NULL")
    )

    photos: Mapped[list["KitPhoto"]] = relationship(
        back_populates="kit", cascade="all, delete-orphan"
    )
    # Read-only, and deliberately no ORM cascade. `upgrade_applications.kit_id` is
    # ON DELETE CASCADE at the database, which is what silently erased build history
    # (and left the stock it consumed still consumed) whenever a kit was deleted.
    # This relationship exists so the service layer can *see* those rows and refuse,
    # per rule 3: history is fact. Adding a delete cascade here would automate the
    # very thing the guard exists to prevent.
    upgrade_applications: Mapped[list["UpgradeApplication"]] = relationship(viewonly=True)

    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)


class KitPhoto(UUIDPrimaryKeyMixin, Base):
    """Single gallery per kit (§4.6); caption/taken_at kept as cheap future-proofing."""

    __tablename__ = "kit_photos"

    kit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kits.id", ondelete="CASCADE"), index=True)
    file_path: Mapped[str]
    caption: Mapped[str | None]
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    kit: Mapped[Kit] = relationship(back_populates="photos")


from app.models.catalog import UpgradeApplication  # noqa: E402,F401  (resolve the string above)
