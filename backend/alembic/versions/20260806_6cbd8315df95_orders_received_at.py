"""orders received_at

Revision ID: 6cbd8315df95
Revises: 71ddc06de024
Create Date: 2026-08-06 01:19:14.404998

Note: autogenerate also proposed dropping the ck_kits_kit_status /
ck_order_items_item_type CHECK constraints — a known false positive for
non-native enum CHECKs; those lines were removed by hand.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6cbd8315df95"
down_revision: str | None = "71ddc06de024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("received_at", sa.DateTime(timezone=True), nullable=True))
    # Orders that predate the pending→received model already had their stock
    # increments applied at entry, so they are received by definition.
    op.execute("UPDATE orders SET received_at = order_date")


def downgrade() -> None:
    op.drop_column("orders", "received_at")
