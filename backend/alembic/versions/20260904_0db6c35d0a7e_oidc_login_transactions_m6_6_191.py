"""oidc login transactions (M6-6, #191)

Adds `oidc_login`, the table of in-flight browser logins at the OpenID Connect
provider (§5.6, open redirect and code interception): one row per
`POST /auth/oidc/start`, consumed once by `GET /auth/oidc/callback`, expiring
ten minutes after creation. It holds digests of the `state` and the browser
binding cookie, the `nonce` the id_token must echo, the PKCE verifier for the
code exchange, and whether the setup token matched at start (`claiming`).

Never portable (rule 9, §5.6): absent from `services/portability/spec.py`, like
every other auth table. The owner's binding columns (`oidc_issuer`,
`oidc_subject`, `display_name`) already exist from the M6-2 foundation; this
migration adds no column to `owner`.

Downgrade drops the table. Rows are ten-minute transactions, so the loss is at
most a login in progress, which the owner restarts.

Revision ID: 0db6c35d0a7e
Revises: f1058c5de0f3
Create Date: 2026-09-04 20:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0db6c35d0a7e"
down_revision: str | None = "f1058c5de0f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oidc_login",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(), nullable=False),
        sa.Column("binding_hash", sa.String(), nullable=False),
        sa.Column("nonce", sa.String(), nullable=False),
        sa.Column("code_verifier", sa.String(), nullable=False),
        sa.Column("claiming", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_login")),
    )
    op.create_index(op.f("ix_oidc_login_state_hash"), "oidc_login", ["state_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_oidc_login_state_hash"), table_name="oidc_login")
    op.drop_table("oidc_login")
