"""kits: build dates (#94) and series (#96)

Revision ID: 8352bee9229f
Revises: 24ee4c9024e4
Create Date: 2026-08-20 11:18:55.862563

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8352bee9229f"
down_revision: str | None = "24ee4c9024e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Purely additive: three nullable columns on kits (#94, #96). Deliberately no
    # data half — build_completed_at is NOT backfilled from status_updated_at for
    # kits already complete, because a backfilled date is indistinguishable from an
    # asserted one (decision on #94). Autogenerate also emitted drop_constraint
    # noise for the text-enum CHECKs it cannot see; removed by hand.
    op.add_column("kits", sa.Column("series", sa.String(), nullable=True))
    op.add_column("kits", sa.Column("build_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "kits", sa.Column("build_completed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    # Lossy for any values written into the three columns; structure-safe.
    op.drop_column("kits", "build_completed_at")
    op.drop_column("kits", "build_started_at")
    op.drop_column("kits", "series")
