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
    """Refuse while the collection holds display data of any kind.

    One invariant, not two tripwires: this migration drops the `display_items`
    table *and* the `display` value from the item_type CHECK, so it is destructive
    unless nothing anywhere is using either. Both states are read before anything
    is raised, because they interact — which is what two review rounds on this
    function were really about (#129 rounds 1 and 2).

    Round 1: only order lines were guarded, so a standalone stand — bought before
    there was anywhere to record the order, which is the case the table exists for —
    went from `alembic downgrade -1` to gone, exit 0.

    Round 2: guarding both, but raising on the first one hit, produced advice the
    operator could not follow. With a stored row *and* a line referencing it, the
    row check fired first and said to delete the item — which the application
    correctly refuses with a 409 while an order line points at it (rule 3). The
    order matters and only a message that has read both counts can state it.

    An empty collection — including the database the test suite migrates both ways
    on every run — is unaffected.
    """
    conn = op.get_bind()
    rows = conn.scalar(sa.text("SELECT count(*) FROM display_items"))
    # Counted separately from the table: `order_items.catalog_ref_id` is polymorphic
    # with no foreign key, so a display line can outlive the row it points at. That
    # state has an empty `display_items` and still must not proceed.
    lines = conn.scalar(sa.text("SELECT count(*) FROM order_items WHERE item_type = 'display'"))

    if rows or lines:
        holds = " and ".join(
            part
            for part in (
                f"{rows} display item(s)" if rows else "",
                f"{lines} display order line(s)" if lines else "",
            )
            if part
        )
        steps = []
        if lines:
            steps.append(
                f"remove or re-type the {lines} display order line(s) (or delete those "
                "orders) — this has to come first, because the app refuses with a 409 "
                "to delete a display item an order line still points at"
            )
        if rows:
            steps.append(
                ("then delete " if lines else "delete ")
                + f"the {rows} display item(s) — export them first if you want to keep "
                "them: Settings → Data management → Export, or GET /export/display_items.csv"
            )
        ordered = "".join(f"\n  {n}. {step}" for n, step in enumerate(steps, 1))
        raise RuntimeError(
            f"this downgrade drops the display_items table and the 'display' item_type, "
            f"and the collection holds {holds}. To go back:{ordered}"
        )

    op.drop_constraint(op.f("ck_order_items_item_type"), "order_items", type_="check")
    op.create_check_constraint(
        op.f("ck_order_items_item_type"), "order_items", f"item_type IN {_OLD_ITEM_TYPES}"
    )
    op.drop_index(op.f("ix_display_items_name"), table_name="display_items")
    op.drop_table("display_items")
