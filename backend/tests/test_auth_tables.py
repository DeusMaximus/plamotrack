"""The auth foundation tables (§5.5–§5.6; #187).

Two things this pins that no other suite does: the auth tables are **not
portable** (rule 9, §5.6 leakage) — an export cannot become a credential dump —
and the owner singleton is seeded **unclaimed**, the fail-closed state a fresh
install and an upgrade both start in (§5.6 safe failure). The credential
mechanisms that write these tables arrive with #188/#189/#193; this file guards
the shape they slot into.
"""

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.db import get_sessionmaker
from app.models import (
    AuditEvent,
    Credential,
    OidcLogin,
    Owner,
    PersonalAccessToken,
    Session,
)
from app.models.auth import OWNER_ROW_ID
from app.services.portability.spec import TABLE_SPECS

_AUTH_MODELS = (Owner, Credential, Session, PersonalAccessToken, AuditEvent, OidcLogin)


def test_no_auth_table_is_portable():
    """Rule 9 / §5.6: none of the auth tables is in the CSV spec registry, so
    export/import/templates never touch them. The registry is the single source
    of the portable shape — an auth model appearing here would put credentials in
    an archive."""
    portable_models = {spec.model for spec in TABLE_SPECS}
    for model in _AUTH_MODELS:
        assert model not in portable_models, f"{model.__name__} must never be portable (rule 9)"


def test_no_auth_table_name_is_portable():
    """The same guard by table name, so a future spec that referenced a table by
    string rather than by model class is caught too."""
    portable_tables = {spec.model.__tablename__ for spec in TABLE_SPECS}
    for model in _AUTH_MODELS:
        assert model.__tablename__ not in portable_tables


async def test_owner_is_seeded_unclaimed_and_singular():
    """The migration seeds exactly one owner row, unclaimed. This is the state
    §5.6 fails closed from and the row #188 claims with an UPDATE."""
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(Owner))).scalars().all()
        assert len(rows) == 1
        owner = rows[0]
        assert owner.id == OWNER_ROW_ID
        assert owner.claimed_at is None
        assert owner.oidc_issuer is None and owner.oidc_subject is None


async def test_the_owner_singleton_constraint_refuses_a_second_row():
    """A second owner is a constraint violation, not a second identity — the same
    guarantee `instance_settings` has (§5.5, one owner)."""
    async with get_sessionmaker()() as session:
        with pytest.raises(IntegrityError):
            await session.execute(text("INSERT INTO owner (id, claimed_at) VALUES (2, NULL)"))
            await session.flush()
        await session.rollback()


async def test_the_auth_tables_exist_and_start_empty():
    """The foundation lands the tables; nothing at this revision writes
    credential, session, token or audit rows."""
    async with get_sessionmaker()() as session:
        for model in (Credential, Session, PersonalAccessToken, AuditEvent):
            count = await session.scalar(select(func.count()).select_from(model))
            assert count == 0, f"{model.__tablename__} should be empty at M6-2"


async def test_secret_columns_are_digests_not_recoverable_secrets():
    """A shape check, not a behaviour one: the token/credential/session tables
    expose only `*_hash` / prefix columns, never a plaintext secret column —
    so a schema drift that added one is caught here (§5.6 credential leakage)."""
    session_columns = set(Session.__table__.columns.keys())
    assert "token_hash" in session_columns
    assert not any(c in session_columns for c in ("token", "secret", "password"))

    pat_columns = set(PersonalAccessToken.__table__.columns.keys())
    assert {"token_prefix", "secret_hash"} <= pat_columns
    assert "secret" not in pat_columns and "token" not in pat_columns

    cred_columns = set(Credential.__table__.columns.keys())
    assert "secret_hash" in cred_columns
    assert "password" not in cred_columns and "secret" not in cred_columns


def test_audit_event_is_append_only_and_carries_no_body():
    """Audit rows have no `updated_at` (append-only) and no column that would
    hold a request body or a secret — only the who/where/what §5.6 lists."""
    columns = set(AuditEvent.__table__.columns.keys())
    assert "updated_at" not in columns
    assert {
        "event_type",
        "principal_kind",
        "principal_subject",
        "client_address",
        "target",
    } <= columns
    assert not any(c in columns for c in ("body", "payload", "secret", "token"))
