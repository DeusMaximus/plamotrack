"""mcp oauth state (M6-7, #192)

Adds `mcp_oauth_state`, the MCP OAuth proxy's state store (§5.5 family 8, §5.6
credential leakage): one key-value table holding the proxy's six collections —
dynamically registered clients, consent transactions, authorization codes, the
provider's upstream tokens, the mapping from issued token ids to those, and
refresh-token metadata. Every `value` is written through a Fernet wrapper keyed
from `MCP_OAUTH_SIGNING_KEY`, so the database never holds an upstream token in
clear (`app/auth/mcp_oauth.py`).

The shape is the `py-key-value-aio` PostgreSQL store's own DDL, owned here so
the schema has one owner: the store's `CREATE TABLE IF NOT EXISTS` finds the
table and becomes a no-op. The index name is the store's too. Never portable
(rule 9, §5.6): absent from `services/portability/spec.py`, like every other
auth table, so an export cannot carry a token and `replace_all` cannot truncate
a live MCP link. The backup set stays the database plus `.env` (§5.6).

Downgrade drops the table. Its rows are MCP links: clients re-authorise, the
owner signs in at the provider again; data, sessions and access tokens are
untouched (§5.6 safe failure, the T13 rows).

Revision ID: d5e9362140ea
Revises: 4f3a9c1e7b2d
Create Date: 2026-09-05 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d5e9362140ea"
down_revision: str | None = "4f3a9c1e7b2d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The store's own index name, kept so its `CREATE INDEX IF NOT EXISTS` is a no-op.
INDEX = "idx_mcp_oauth_state_expires_at"


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_state",
        sa.Column("collection", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ttl", sa.Double(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("collection", "key", name=op.f("pk_mcp_oauth_state")),
    )
    op.create_index(
        INDEX,
        "mcp_oauth_state",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="mcp_oauth_state")
    op.drop_table("mcp_oauth_state")
