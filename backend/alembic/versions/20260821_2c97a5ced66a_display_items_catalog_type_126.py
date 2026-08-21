"""display_items catalog type (#126)

Revision ID: 2c97a5ced66a
Revises: bcdb375e32d0
Create Date: 2026-08-21 10:16:02.094503

A fourth fungible catalog table — stands, bases, diorama scenery — plus the
`display` value on order_items.item_type so the purchases are orderable.

Hand-written. Autogenerate produced the new table correctly and then proposed
dropping `ck_kits_kit_status`, `ck_order_items_item_type` and all three retailer
enum constraints without recreating any of them: text enums with
`create_constraint=True` are invisible to its comparison, so it reads every one
of them as removed (the same blindness `merge_in_hand_into_backlog` records).
Only the item_type constraint genuinely changes here.

No data migration. Nothing existing becomes a display item — the value is new and
the table starts empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2c97a5ced66a"
down_revision: str | None = "bcdb375e32d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_ITEM_TYPES = "('kit', 'tool', 'consumable', 'upgrade', 'display')"
_OLD_ITEM_TYPES = "('kit', 'tool', 'consumable', 'upgrade')"


def upgrade() -> None:
    op.create_table(
        "display_items",
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("scale", sa.String(), nullable=True),
        sa.Column("manufacturer", sa.String(), nullable=True),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "quantity_on_hand >= 0", name=op.f("ck_display_items_quantity_non_negative")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_display_items")),
    )
    op.create_index(op.f("ix_display_items_name"), "display_items", ["name"], unique=False)

    op.drop_constraint(op.f("ck_order_items_item_type"), "order_items", type_="check")
    op.create_check_constraint(
        op.f("ck_order_items_item_type"), "order_items", f"item_type IN {_NEW_ITEM_TYPES}"
    )


def downgrade() -> None:
    # Refuse rather than delete, on two counts — and they are two, not one
    # (#129 review, P2-3).
    #
    # `display_items` itself: dropping the table discards inventory the owner
    # entered, and silently destroying records to make a schema change fit is the
    # opposite of what this application is for (§6). The first version of this
    # migration guarded only the order-line case, so a standalone stand — bought
    # before there was anywhere to record the order, which is exactly why the table
    # exists — went from `alembic downgrade -1` to gone, exit 0.
    #
    # `order_items` as well, and NOT instead: `catalog_ref_id` is polymorphic with
    # no foreign key, so a display line can point at a row that is already missing.
    # That case has an empty `display_items` and still must not proceed, because
    # dropping the value from the CHECK constraint would leave the line unreadable
    # by the enum it is stored under.
    #
    # A collection that never recorded a display item — including the empty database
    # the test suite migrates both ways on every run — is unaffected by either.
    conn = op.get_bind()
    rows = conn.scalar(sa.text("SELECT count(*) FROM display_items"))
    if rows:
        raise RuntimeError(
            f"display_items holds {rows} row(s) and this downgrade drops the table. "
            "Export them (Data → Export, or GET /export/display_items.csv) and delete "
            "them first if you really mean to go back."
        )
    lines = conn.scalar(sa.text("SELECT count(*) FROM order_items WHERE item_type = 'display'"))
    if lines:
        raise RuntimeError(
            f"{lines} order line(s) are display lines, and this downgrade removes the "
            "item_type they are stored under. Delete or re-type those lines first if "
            "you really mean to go back."
        )

    op.drop_constraint(op.f("ck_order_items_item_type"), "order_items", type_="check")
    op.create_check_constraint(
        op.f("ck_order_items_item_type"), "order_items", f"item_type IN {_OLD_ITEM_TYPES}"
    )
    op.drop_index(op.f("ix_display_items_name"), table_name="display_items")
    op.drop_table("display_items")
