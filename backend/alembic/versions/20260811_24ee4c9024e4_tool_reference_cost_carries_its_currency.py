"""tool reference cost carries its currency

Revision ID: 24ee4c9024e4
Revises: 2b293c6fd496
Create Date: 2026-08-11 14:26:25.543303

Brings the last amount in the schema under §6 (#19). `tools.unit_cost_reference`
was a Numeric(10, 2) with no currency column anywhere on the table, so a recorded
45.00 meant nothing in particular and a KWD tool could not be represented at all —
Postgres rounded 1.234 to 1.23 on the way in.

**This migration guesses, and the guess is disclosed rather than made quietly.**
Existing rows record an amount and no currency, so there is nothing to convert
*from*; the instance's configured REFERENCE_CURRENCY is the only candidate, and it
is an assumption about what the person entering the number meant. Instances that
bought tools abroad should check those rows after upgrading. That is the same
standard #12 and #6 were held to, and the reason this lands immediately after a
tagged release (docs/operations.md: export an archive before upgrading).

The exponent used for the conversion is that currency's, not a flat 100: a JPY
instance's 45.00 is ¥45 (45 minor units), not 4500.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.config import get_settings
from app.services.currency import minor_fraction_digits

revision: str = "24ee4c9024e4"
down_revision: str | None = "2b293c6fd496"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _reference() -> tuple[str, int]:
    """The code the backfill assumes, and the power of ten it scales by."""
    code = get_settings().reference_currency
    return code, 10 ** minor_fraction_digits(code)


def upgrade() -> None:
    code, factor = _reference()
    op.add_column("tools", sa.Column("unit_cost_reference_minor", sa.Integer(), nullable=True))
    op.add_column(
        "tools", sa.Column("unit_cost_reference_currency", sa.String(length=3), nullable=True)
    )
    # Backfill before the constraints go on: the paired CHECK would reject the
    # intermediate state where the amount has moved across and the code has not.
    op.execute(
        sa.text(
            "UPDATE tools "
            f"SET unit_cost_reference_minor = ROUND(unit_cost_reference * {factor})::bigint, "
            "    unit_cost_reference_currency = :code "
            "WHERE unit_cost_reference IS NOT NULL"
        ).bindparams(code=code)
    )
    # Bare names — the ck_%(table_name)s_%(constraint_name)s convention in
    # models/base.py expands these, and passing an expanded name double-prefixes it.
    op.create_check_constraint(
        "unit_cost_reference_non_negative",
        "tools",
        "unit_cost_reference_minor >= 0",
    )
    op.create_check_constraint(
        "unit_cost_reference_currency_paired",
        "tools",
        "(unit_cost_reference_minor IS NULL) = (unit_cost_reference_currency IS NULL)",
    )
    op.drop_column("tools", "unit_cost_reference")


def downgrade() -> None:
    code, factor = _reference()
    op.add_column(
        "tools", sa.Column("unit_cost_reference", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    # Lossy on purpose, like 2b293c6fd496's. The restored column cannot state a
    # currency, so only amounts in the instance's own reference currency can move
    # back into it without becoming a number that means something else; anything
    # else is dropped rather than silently relabelled. A reference currency with
    # three or four decimals also loses precision here, because scale 2 is the
    # shape being restored — take a backup first (docs/operations.md).
    op.execute(
        sa.text(
            "UPDATE tools "
            f"SET unit_cost_reference = ROUND(unit_cost_reference_minor::numeric / {factor}, 2) "
            "WHERE unit_cost_reference_currency = :code"
        ).bindparams(code=code)
    )
    op.drop_constraint("unit_cost_reference_currency_paired", "tools", type_="check")
    op.drop_constraint("unit_cost_reference_non_negative", "tools", type_="check")
    op.drop_column("tools", "unit_cost_reference_currency")
    op.drop_column("tools", "unit_cost_reference_minor")
