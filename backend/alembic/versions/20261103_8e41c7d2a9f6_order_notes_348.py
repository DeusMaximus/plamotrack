"""orders.notes (#348)

Free text for what no other order field holds: how it was paid, a substitution, a
partial refund, a damage claim against this purchase. Nullable, with no default, so
every order on record reads as having no note.

Downgrade drops the column and every note in it. Nothing else holds them.

Revision ID: 8e41c7d2a9f6
Revises: 5cbec7813500
Create Date: 2026-11-03 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8e41c7d2a9f6"
down_revision: str | None = "5cbec7813500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("notes", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "notes")
