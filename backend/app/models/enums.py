import enum

from sqlalchemy import Enum as SAEnum


class KitStatus(enum.StrEnum):
    """Pipeline order. `backlog` = physically in hand, not started — the former
    separate in_hand status was merged into it (they were functionally the same
    pile); kits not yet arrived live in the ordering states before it."""

    PRE_ORDERED = "pre_ordered"
    ORDERED = "ordered"
    IN_TRANSIT = "in_transit"
    BACKLOG = "backlog"
    BUILDING = "building"
    COMPLETE = "complete"


class ItemType(enum.StrEnum):
    KIT = "kit"
    TOOL = "tool"
    CONSUMABLE = "consumable"
    UPGRADE = "upgrade"
    DISPLAY = "display"


class PackingQuality(enum.StrEnum):
    EXCELLENT = "excellent"
    GOOD = "good"
    AVERAGE = "average"
    BELOW_AVERAGE = "below_average"
    POOR = "poor"


class ShippingSpeed(enum.StrEnum):
    VERY_FAST = "very_fast"
    FAST = "fast"
    AVERAGE = "average"
    SLOW = "slow"
    VERY_SLOW = "very_slow"


class WouldOrderAgain(enum.StrEnum):
    YES = "yes"
    MAYBE = "maybe"
    NO = "no"


class DateStyle(enum.StrEnum):
    """How the browser renders dates (§6.1). `locale` defers to the formatting
    locale's own convention; the rest are the `Intl.DateTimeFormat` dateStyle
    values, so the setting maps straight onto the formatter that consumes it."""

    LOCALE = "locale"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    FULL = "full"


class HourCycle(enum.StrEnum):
    """12- or 24-hour clock (§6.1). `locale` defers to the formatting locale;
    `h12` and `h23` are the two `Intl.DateTimeFormat` hourCycle values in real-world
    use (h11 and h24 exist in CLDR but no region defaults to them)."""

    LOCALE = "locale"
    H12 = "h12"
    H23 = "h23"


def text_enum(enum_cls: type[enum.StrEnum], name: str) -> SAEnum:
    """Text column + CHECK constraint instead of a native Postgres enum, so future
    taxonomy changes are a data migration rather than an ALTER TYPE dance (§9.1)."""
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
        length=20,
    )
