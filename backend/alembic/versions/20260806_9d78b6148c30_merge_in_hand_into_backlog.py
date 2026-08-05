"""merge in_hand into backlog

Revision ID: 9d78b6148c30
Revises: 04315056a82f
Create Date: 2026-08-06 02:41:46.797011

in_hand and backlog were functionally the same pile (physically here, not
started). Merge: in_hand kits become backlog; backlog takes in_hand's pipeline
position (after in_transit). Hand-written — enum value changes are invisible
to autogenerate with non-native enums.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9d78b6148c30"
down_revision: str | None = "04315056a82f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_STATUSES = "('pre_ordered', 'ordered', 'in_transit', 'backlog', 'building', 'complete')"
_OLD_STATUSES = (
    "('backlog', 'pre_ordered', 'ordered', 'in_transit', 'in_hand', 'building', 'complete')"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_kits_kit_status"), "kits", type_="check")
    op.execute("UPDATE kits SET status = 'backlog' WHERE status = 'in_hand'")
    op.create_check_constraint(op.f("ck_kits_kit_status"), "kits", f"status IN {_NEW_STATUSES}")


def downgrade() -> None:
    # Which backlog kits were formerly in_hand is unknowable — data stays merged;
    # only the constraint reverts to accepting both values.
    op.drop_constraint(op.f("ck_kits_kit_status"), "kits", type_="check")
    op.create_check_constraint(op.f("ck_kits_kit_status"), "kits", f"status IN {_OLD_STATUSES}")
