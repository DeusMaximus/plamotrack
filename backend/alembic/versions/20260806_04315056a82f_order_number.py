"""order number

Revision ID: 04315056a82f
Revises: e720578b82de
Create Date: 2026-08-06 01:51:20.869061

Autogenerate's spurious enum CHECK drops (kits, order_items, retailers)
removed by hand — known false positive for non-native enum CHECKs.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "04315056a82f"
down_revision: str | None = "e720578b82de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Retailer's own reference number — informational only, unique per retailer
    # at best, so deliberately no uniqueness constraint.
    op.add_column("orders", sa.Column("order_number", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "order_number")
