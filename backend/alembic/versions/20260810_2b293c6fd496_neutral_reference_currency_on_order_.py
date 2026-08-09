"""neutral reference currency on order items

Revision ID: 2b293c6fd496
Revises: 9d78b6148c30
Create Date: 2026-08-10 10:41:02.118374

Drops the AUD assumption from the entry-time conversion snapshot (§6). The
amount column is renamed rather than replaced so existing snapshots survive,
and the currency it was captured under becomes explicit instead of implied by
the column name.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2b293c6fd496"
down_revision: str | None = "9d78b6148c30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rename, don't drop-and-add: the whole point of the snapshot is that the
    # number recorded at entry time is still there afterwards.
    op.alter_column(
        "order_items",
        "converted_price_aud_minor",
        new_column_name="converted_price_minor",
    )
    op.add_column(
        "order_items",
        sa.Column("converted_currency_code", sa.String(length=3), nullable=True),
    )
    # Every pre-existing snapshot was AUD by definition — that was the column
    # name. Making it explicit is what lets the instance default move later
    # without retroactively changing what these rows mean.
    op.execute(
        "UPDATE order_items SET converted_currency_code = 'AUD' "
        "WHERE converted_price_minor IS NOT NULL"
    )
    op.create_check_constraint(
        "converted_price_non_negative",
        "order_items",
        "converted_price_minor >= 0",
    )
    op.create_check_constraint(
        "converted_price_currency_paired",
        "order_items",
        "(converted_price_minor IS NULL) = (converted_currency_code IS NULL)",
    )


def downgrade() -> None:
    # Bare names — the ck_%(table_name)s_%(constraint_name)s convention in
    # models/base.py expands these, and passing an expanded name double-prefixes it.
    op.drop_constraint("converted_price_currency_paired", "order_items", type_="check")
    op.drop_constraint("converted_price_non_negative", "order_items", type_="check")
    # Lossy on purpose. The old column name asserts the amount is AUD, so a
    # snapshot taken in any other currency cannot move back into it without
    # becoming wrong data. Clearing those is the honest option; take a backup
    # before downgrading (docs/operations.md).
    op.execute(
        "UPDATE order_items SET converted_price_minor = NULL "
        "WHERE converted_currency_code IS DISTINCT FROM 'AUD'"
    )
    op.drop_column("order_items", "converted_currency_code")
    op.alter_column(
        "order_items",
        "converted_price_minor",
        new_column_name="converted_price_aud_minor",
    )
