"""instance settings singleton (#23)

Creates the one-row `instance_settings` table (§6.1) and seeds it. The seed reads
`REFERENCE_CURRENCY` through the same config the app reads (env vars plus the
repo/backend .env files), so an installation that configured a currency keeps it:
after this migration the database row is the setting and the env var is only ever
a first-run bootstrap. Everything else seeds the documented defaults — en-AU
language and formatting, UTC, locale-default date style and hour cycle.

Downgrade drops the table. The settings it held are the singleton's whole state,
so a downgrade reverts the instance to env-configured behaviour losslessly —
except for any values changed since the upgrade, which is disclosed in the
release notes rather than guessed at here.

(Autogenerate also emitted drop/recreate churn for the other tables' enum CHECK
constraints — the known false positive with non-native enums — removed by hand,
as every migration since the initial schema has.)

Revision ID: f9979ec7b9cb
Revises: 2c97a5ced66a
Create Date: 2026-08-27 16:19:52.220152

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.config import get_settings

revision: str = "f9979ec7b9cb"
down_revision: str | None = "2c97a5ced66a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instance_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("interface_language", sa.String(), nullable=False),
        sa.Column("formatting_locale", sa.String(), nullable=False),
        sa.Column("time_zone", sa.String(), nullable=False),
        sa.Column(
            "date_style",
            sa.Enum(
                "locale",
                "short",
                "medium",
                "long",
                "full",
                name="date_style",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "hour_cycle",
            sa.Enum(
                "locale",
                "h12",
                "h23",
                name="hour_cycle",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("reference_currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_instance_settings_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instance_settings")),
    )
    op.execute(
        sa.text(
            "INSERT INTO instance_settings "
            "(id, interface_language, formatting_locale, time_zone, date_style, hour_cycle, "
            " reference_currency) "
            "VALUES (1, 'en-AU', 'en-AU', 'UTC', 'locale', 'locale', :reference_currency)"
        ).bindparams(reference_currency=get_settings().reference_currency)
    )


def downgrade() -> None:
    op.drop_table("instance_settings")
