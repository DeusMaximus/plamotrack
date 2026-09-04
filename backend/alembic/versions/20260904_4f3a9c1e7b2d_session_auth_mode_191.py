"""session auth_mode (M6-6, #191; Codex #209 round 1, f1)

Adds `session.auth_mode` — the authentication mode (`local` or `oidc`) that
minted each browser session. A session is authority only in the mode that
minted it: the resolver refuses one presented under the other mode, and the
API's start in a new mode revokes every live session the old one left, so a
mode switch signs everyone out — as `docs/operations.md` already said — and
switching back cannot resurrect a cookie. Text plus CHECK, not a native enum
(rule 5), matching the model's `text_enum`.

Backfill: every session that exists before this revision is stamped `local`.
That is the fact for every released instance — OIDC mode ships on the same
branch as this migration, so nothing released could have minted a session any
other way. (A development database that ran the unreleased branch in OIDC mode
gets those sessions stamped `local` too; its next OIDC-mode start refuses and
revokes them, which is one sign-out on a throwaway database.)

Downgrade drops the constraint and the column; sessions survive, unstamped.

Revision ID: 4f3a9c1e7b2d
Revises: 0db6c35d0a7e
Create Date: 2026-09-04 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4f3a9c1e7b2d"
down_revision: str | None = "0db6c35d0a7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("session", sa.Column("auth_mode", sa.String(length=20), nullable=True))
    op.execute(sa.text("UPDATE session SET auth_mode = 'local'"))
    op.alter_column("session", "auth_mode", nullable=False)
    # Bare name — the ck_%(table_name)s_%(constraint_name)s convention in
    # models/base.py expands it to the name the model's `text_enum` declares.
    op.create_check_constraint("auth_mode", "session", "auth_mode IN ('local', 'oidc')")


def downgrade() -> None:
    op.drop_constraint("auth_mode", "session", type_="check")
    op.drop_column("session", "auth_mode")
