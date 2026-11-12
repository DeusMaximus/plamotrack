"""auth foundation tables (M6-2, #187)

Creates the five authentication and audit tables the rest of Milestone 6 fills
in (§5.5–§5.6): `owner`, `credential`, `session`, `personal_access_token` and
`audit_event`. Nothing writes them yet — local auth (#188), personal access
tokens (#189) and audit (#193) do — so this migration only lands the schema and
seeds the one owner singleton **unclaimed** (`claimed_at` null), the state a
fresh install and an upgraded instance both start in and the state that fails
every collection route closed (§5.6 safe failure).

None of these tables is portable (rule 9, §5.6): they are absent from
`services/portability/spec.py`, so an export can never carry a credential and an
import can never forge a session or token.

Downgrade drops all five. Nothing runtime writes them at this revision, so the
downgrade is lossless here; once #188/#189 populate them a downgrade discards
sessions and tokens, disclosed at that revision.

(Autogenerate also emitted the usual drop/recreate churn for the other tables'
non-native enum CHECK constraints — the known false positive — removed by hand,
as every migration since the initial schema has.)

Revision ID: f1058c5de0f3
Revises: f9979ec7b9cb
Create Date: 2026-09-03 20:35:00.454498

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1058c5de0f3"
down_revision: str | None = "f9979ec7b9cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owner",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("oidc_issuer", sa.String(), nullable=True),
        sa.Column("oidc_subject", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
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
        sa.CheckConstraint("id = 1", name=op.f("ck_owner_singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owner")),
    )
    # The single owner row, unclaimed. Mirrors instance_settings' seed: the row
    # exists from the first migration so #188 claims it with an UPDATE rather
    # than racing to insert it, and an unclaimed instance has a definite state.
    op.execute(sa.text("INSERT INTO owner (id, claimed_at) VALUES (1, NULL)"))

    op.create_table(
        "credential",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("secret_hash", sa.String(), nullable=False),
        sa.Column("algorithm", sa.String(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credential")),
    )

    op.create_table(
        "session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session")),
    )
    op.create_index(op.f("ix_session_token_hash"), "session", ["token_hash"], unique=True)

    op.create_table(
        "personal_access_token",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_prefix", sa.String(), nullable=False),
        sa.Column("secret_hash", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("scopes", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personal_access_token")),
    )
    op.create_index(
        op.f("ix_personal_access_token_token_prefix"),
        "personal_access_token",
        ["token_prefix"],
        unique=True,
    )

    op.create_table(
        "audit_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("principal_kind", sa.String(), nullable=True),
        sa.Column("principal_subject", sa.String(), nullable=True),
        sa.Column("client_address", sa.String(), nullable=True),
        sa.Column("target", sa.String(), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_event")),
    )
    op.create_index(op.f("ix_audit_event_event_type"), "audit_event", ["event_type"], unique=False)
    op.create_index(
        op.f("ix_audit_event_occurred_at"), "audit_event", ["occurred_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_event_occurred_at"), table_name="audit_event")
    op.drop_index(op.f("ix_audit_event_event_type"), table_name="audit_event")
    op.drop_table("audit_event")
    op.drop_index(op.f("ix_personal_access_token_token_prefix"), table_name="personal_access_token")
    op.drop_table("personal_access_token")
    op.drop_index(op.f("ix_session_token_hash"), table_name="session")
    op.drop_table("session")
    op.drop_table("credential")
    op.drop_table("owner")
