"""order_adjustments: what came off an order's price (#350)

A discount, a promo code, a voucher or a gift card applied to an order, one row
each, so an order can say what was actually paid without anyone deflating a line
price to make the sum come out.

No data migration: no stored order has one.

Revision ID: b7d4f0a3c915
Revises: 61442608b20e
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d4f0a3c915"
down_revision: str | None = "61442608b20e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_adjustments",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_order_adjustments_amount_positive")),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_order_adjustments_position_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_adjustments_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_adjustments")),
    )
    op.create_index(
        op.f("ix_order_adjustments_order_id"), "order_adjustments", ["order_id"], unique=False
    )


def downgrade() -> None:
    """Refuse while any order holds an adjustment.

    Dropping the table would leave those orders saying more was paid than was,
    with nothing recording that anything had been lost. Removing them is the
    owner's edit to make, not a migration's.
    """
    conn = op.get_bind()
    held = conn.scalar(sa.text("SELECT count(*) FROM order_adjustments"))
    if held:
        raise RuntimeError(
            f"this downgrade drops order adjustments, and the collection holds {held} "
            "of them. Remove them from their orders first (Orders, then edit each "
            "order), or export the collection if you want a record of them: "
            "Settings → Data management → Export"
        )
    op.drop_index(op.f("ix_order_adjustments_order_id"), table_name="order_adjustments")
    op.drop_table("order_adjustments")
