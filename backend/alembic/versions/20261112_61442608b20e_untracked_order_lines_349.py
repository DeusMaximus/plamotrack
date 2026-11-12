"""order_items: the `other` item type and its description (#349)

An order line the collection does not track: a non-Gunpla item in a mixed basket,
an add-on, anything bought on the order that is neither a kit nor a catalog row.
It dispatches nothing (no kits, no stock), so all it holds is a description and
its price.

Hand-written, for the reason `2c97a5ced66a` records: a text enum's CHECK is
invisible to autogenerate, which proposes dropping every one of them.

No data migration. No stored line becomes an `other` line, and `description`
starts null on every one, which is what the first new CHECK requires of them.

Revision ID: 61442608b20e
Revises: 8e41c7d2a9f6
Create Date: 2026-11-12 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "61442608b20e"
down_revision: str | None = "8e41c7d2a9f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ITEM_TYPES = "('kit', 'tool', 'consumable', 'upgrade', 'display', 'other')"
_OLD_ITEM_TYPES = "('kit', 'tool', 'consumable', 'upgrade', 'display')"


def upgrade() -> None:
    op.add_column("order_items", sa.Column("description", sa.String(), nullable=True))
    op.drop_constraint(op.f("ck_order_items_item_type"), "order_items", type_="check")
    op.create_check_constraint(
        op.f("ck_order_items_item_type"), "order_items", f"item_type IN {_NEW_ITEM_TYPES}"
    )
    op.create_check_constraint(
        op.f("ck_order_items_description_only_on_other"),
        "order_items",
        "(item_type = 'other') = (description IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_order_items_other_has_no_catalog_ref"),
        "order_items",
        "item_type <> 'other' OR catalog_ref_id IS NULL",
    )


def downgrade() -> None:
    """Refuse while any order holds an `other` line.

    The old CHECK has no `other` value, so those lines cannot stay, and dropping
    them would change what their orders say was bought and paid. That is the
    owner's edit to make, not a migration's. With none stored, `description` is
    null on every line and dropping the column loses nothing.
    """
    conn = op.get_bind()
    lines = conn.scalar(sa.text("SELECT count(*) FROM order_items WHERE item_type = 'other'"))
    if lines:
        raise RuntimeError(
            f"this downgrade drops the 'other' item_type, and the collection holds "
            f"{lines} order line(s) of that type. Remove those lines from their orders "
            "first (Orders, then edit each order), or export the collection if you want "
            "a record of them: Settings → Data management → Export"
        )
    op.drop_constraint(
        op.f("ck_order_items_other_has_no_catalog_ref"), "order_items", type_="check"
    )
    op.drop_constraint(
        op.f("ck_order_items_description_only_on_other"), "order_items", type_="check"
    )
    op.drop_constraint(op.f("ck_order_items_item_type"), "order_items", type_="check")
    op.create_check_constraint(
        op.f("ck_order_items_item_type"), "order_items", f"item_type IN {_OLD_ITEM_TYPES}"
    )
    op.drop_column("order_items", "description")
