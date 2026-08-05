import enum

from sqlalchemy import Enum as SAEnum


class KitStatus(enum.StrEnum):
    BACKLOG = "backlog"
    PRE_ORDERED = "pre_ordered"
    ORDERED = "ordered"
    IN_TRANSIT = "in_transit"
    IN_HAND = "in_hand"
    BUILDING = "building"
    COMPLETE = "complete"


class ItemType(enum.StrEnum):
    KIT = "kit"
    TOOL = "tool"
    CONSUMABLE = "consumable"
    UPGRADE = "upgrade"


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
