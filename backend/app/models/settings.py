"""The instance-settings singleton (§6.1, #23).

plamotrack is a single-owner, single-collection application, so interface
language, formatting locale, time zone, date style, hour cycle, and reference
currency are properties of the *instance* — every browser and every agent reads
the same values, rather than each device quietly inferring its own.

Exactly one row, created by the migration that creates the table. The CHECK pins
the primary key to ``SINGLETON_ROW_ID`` so a second row is a constraint violation
rather than a second set of preferences.
"""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import DateStyle, HourCycle, text_enum

#: The one primary-key value the singleton CHECK allows.
SINGLETON_ROW_ID = 1


class InstanceSettings(TimestampMixin, Base):
    __tablename__ = "instance_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=SINGLETON_ROW_ID)
    # BCP 47 tag of the interface language. en-AU is the canonical source
    # catalogue and fallback (§6.1); additional languages ship with the repo.
    interface_language: Mapped[str]
    # BCP 47 tag driving date/number/money *presentation*. Deliberately separate
    # from the language — choosing 日本語 must not silently reformat dates the
    # owner set up on purpose (§6.1).
    formatting_locale: Mapped[str]
    # IANA zone name, e.g. Australia/Sydney. One explicit instance-wide value,
    # never inferred independently per browser.
    time_zone: Mapped[str]
    date_style: Mapped[DateStyle] = mapped_column(text_enum(DateStyle, "date_style"))
    hour_cycle: Mapped[HourCycle] = mapped_column(text_enum(HourCycle, "hour_cycle"))
    # Default currency for *new* entries only (§6) — changing it never restates a
    # stored amount or an already-taken conversion snapshot.
    reference_currency: Mapped[str] = mapped_column(String(3))

    __table_args__ = (CheckConstraint(f"id = {SINGLETON_ROW_ID}", name="singleton"),)
