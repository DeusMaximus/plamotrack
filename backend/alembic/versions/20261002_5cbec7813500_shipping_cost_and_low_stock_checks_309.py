"""shipping cost and low-stock threshold CHECKs (#309)

Two integer columns every writer has treated as non-negative had no CHECK behind
them: `orders.shipping_cost_minor` and `consumables.low_stock_threshold`. REST
and MCP refuse a negative through `NonNegativeInt4`, and since #305 so does the
CSV importer. Before #305 the importer did not, so an instance that imported
such a sheet holds rows these constraints would refuse, and adding them blind
would fail the upgrade.

So the upgrade first clears what can't be kept. A negative becomes **null**,
never 0: null is "not recorded" for a shipping cost and "no alert" for a
threshold, while 0 would assert free shipping or an alert at zero, which
nobody stated (the owner's call, 2026-10-02). It logs how many rows it cleared.

Downgrade drops the two constraints. It cannot restore the cleared values.

Revision ID: 5cbec7813500
Revises: d5e9362140ea
Create Date: 2026-10-02 09:00:00.000000

"""

import logging
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "5cbec7813500"
down_revision: str | None = "d5e9362140ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger("alembic.runtime.migration")

#: (table, column, bare constraint name). The ck_%(table_name)s_%(constraint_name)s
#: convention in models/base.py expands each name to the one the model declares.
CHECKS = (
    ("orders", "shipping_cost_minor", "shipping_cost_non_negative"),
    ("consumables", "low_stock_threshold", "low_stock_threshold_non_negative"),
)


def upgrade() -> None:
    bind = op.get_bind()
    for table, column, name in CHECKS:
        cleared = bind.execute(
            sa.text(f"UPDATE {table} SET {column} = NULL WHERE {column} < 0")
        ).rowcount
        if cleared:
            log.info("%s.%s: cleared %d negative value(s) to null (#309)", table, column, cleared)
        op.create_check_constraint(name, table, f"{column} >= 0")


def downgrade() -> None:
    for table, _column, name in CHECKS:
        op.drop_constraint(name, table, type_="check")
