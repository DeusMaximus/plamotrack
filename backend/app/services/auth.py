"""Local owner authentication — the service layer (§5.5 families 2–3, §5.6; M6-3, #188).

The single owner claims the instance once with the setup token, then logs in
with a password; a browser session is an opaque id whose digest sits in
`session`. Everything here is a mutation of auth state and takes the write gate
first (rule 7.1) — the owner row is the decision every claim reads, and two
concurrent claims must serialize on it rather than both succeed.

What this module deliberately does **not** know: cookies, headers, the request.
Those are the router's and the resolver's (`app/auth/*`); the functions here
take and return raw tokens and rows so the recovery command (`app/auth/
recovery.py`) can drive the same paths from a shell with no HTTP in the way.

Failure audit rows are committed **before** the refusal is raised — a raise
rolls the transaction back, and an attempt that leaves no trace is exactly what
§5.6's audit row is there to prevent.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app import error_codes
from app.auth import credentials
from app.auth.budget import FailureBudget
from app.auth.principal import Principal, anonymous, internal
from app.auth.sessions import LAST_USED_WRITE_INTERVAL, SESSION_ABSOLUTE, SESSION_IDLE
from app.exceptions import (
    CredentialRejectedError,
    GoneError,
    InvalidInputError,
    RateLimitedError,
)
from app.models import Credential, Owner
from app.models import Session as SessionRow
from app.models.auth import OWNER_ROW_ID
from app.models.enums import AuthMode
from app.services import audit
from app.services.write_gate import acquire_write_gate

log = logging.getLogger("plamotrack.auth")


class InstanceState(StrEnum):
    """What `GET /auth/session` reports (§5.5, family 2)."""

    UNCLAIMED = "unclaimed"
    ANONYMOUS = "anonymous"
    OWNER = "owner"


_LOGIN_FAILED = "That password isn't right."
_SETUP_TOKEN_INVALID = "That setup token isn't right. The current one is in the API log."
_SETUP_CLAIMED = "This instance already has an owner. Sign in instead."
_THROTTLED = "Too many failed attempts. Try again in {seconds} seconds."

_MISSING_OWNER_ROW = "the owner row is missing — migrations create it; run `alembic upgrade head`"


def _now() -> datetime:
    return datetime.now(UTC)


# --- the owner row --------------------------------------------------------------


async def owner_row(session: AsyncSession, *, for_update: bool = False) -> Owner:
    row = await session.get(Owner, OWNER_ROW_ID, with_for_update=for_update)
    if row is None:
        # Deployment breakage, not client error (the instance_settings precedent).
        raise RuntimeError(_MISSING_OWNER_ROW)
    return row


async def is_claimed(session: AsyncSession) -> bool:
    return (await owner_row(session)).claimed_at is not None


# --- passwords ------------------------------------------------------------------


def validate_password(password: str) -> None:
    """Length is the one rule (see `credentials`). Raised as the 422 envelope so
    the form can point at the field."""
    if len(password) < credentials.MIN_PASSWORD_LENGTH:
        raise InvalidInputError(
            f"The password needs at least {credentials.MIN_PASSWORD_LENGTH} characters.",
            code=error_codes.AUTH_PASSWORD_TOO_SHORT,
            params={"min": credentials.MIN_PASSWORD_LENGTH},
        )
    if len(password) > credentials.MAX_PASSWORD_LENGTH:
        raise InvalidInputError(
            f"The password can't be longer than {credentials.MAX_PASSWORD_LENGTH} characters.",
            code=error_codes.AUTH_PASSWORD_TOO_LONG,
            params={"max": credentials.MAX_PASSWORD_LENGTH},
        )


async def _replace_credential(session: AsyncSession, password: str) -> None:
    """The local credential is one row; setting it replaces whatever was there.
    Caller holds the gate and has validated the password."""
    await session.execute(delete(Credential))
    session.add(
        Credential(secret_hash=credentials.hash_password(password), algorithm=credentials.ALGORITHM)
    )


async def _the_credential(session: AsyncSession) -> Credential | None:
    return (await session.execute(select(Credential).limit(1))).scalar_one_or_none()


# --- sessions -------------------------------------------------------------------


def new_session_row(now: datetime, *, auth_mode: AuthMode) -> tuple[str, SessionRow]:
    """A fresh session: the raw token for the cookie and the row holding its
    digest, stamped with the mode that mints it. Shared with the OIDC flow
    (`services/oidc.py`), which mints sessions the same way after its own
    credential check."""
    raw = credentials.new_token()
    row = SessionRow(
        token_hash=credentials.digest(raw),
        auth_mode=auth_mode,
        last_used_at=now,
        expires_at=now + SESSION_ABSOLUTE,
    )
    return raw, row


async def resolve_session(
    session: AsyncSession, raw_token: str, *, auth_mode: AuthMode
) -> SessionRow | None:
    """The live session row a presented cookie names, or None when it names no
    session, a revoked one, an expired one (idle or absolute), or one minted in
    an authentication mode other than `auth_mode` — the one the app is running
    in. A session is authority only in the mode that minted it: a password-flow
    cookie kept across a switch to OIDC mode is not the owner there, nor a
    provider-minted one after the switch back (Codex #209 round 1, f1); the
    start-up sweep (`revoke_sessions_of_other_modes`) revokes them, this is
    the per-request refusal that does not depend on it having run. Touches
    `last_used_at` at most every `LAST_USED_WRITE_INTERVAL`; the caller's
    transaction commits that."""
    row = (
        await session.execute(
            select(SessionRow).where(SessionRow.token_hash == credentials.digest(raw_token))
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None or row.auth_mode != auth_mode:
        return None
    now = _now()
    if row.expires_at is not None and now >= row.expires_at:
        return None
    last_used = row.last_used_at or row.created_at
    if last_used is not None and now - last_used >= SESSION_IDLE:
        return None
    if last_used is None or now - last_used >= LAST_USED_WRITE_INTERVAL:
        row.last_used_at = now
    return row


async def revoke_all_sessions(
    session: AsyncSession,
    *,
    target: str,
    principal: Principal | None = None,
    request: Request | None = None,
    client_address: str | None = None,
) -> int:
    """Every live session revoked — logout-everywhere, the credential change and
    the recovery command all end here (§5.6), and each records the bulk
    revocation as its own audit event (#188: "session revoked"), with the count,
    in the caller's transaction. Returns how many were live."""
    result = await session.execute(
        update(SessionRow).where(SessionRow.revoked_at.is_(None)).values(revoked_at=_now())
    )
    revoked = result.rowcount or 0
    await audit.record_event(
        session,
        audit.SESSIONS_REVOKED,
        principal=principal,
        request=request,
        target=target,
        detail=f"count={revoked}",
        client_address=client_address,
    )
    return revoked


async def revoke_sessions_of_other_modes(session: AsyncSession, *, auth_mode: AuthMode) -> int:
    """The API's start in `auth_mode` (the lifespan; #191): every live session
    minted in any other mode is revoked, with the bulk-revocation audit row and
    an `auth.mode_changed` row naming the mode and the count. The resolver
    already refuses the other mode's cookie on every request; this makes the
    refusal durable, so switching back does not find those sessions live again
    (Codex #209 round 1, f1). A restart in the same mode revokes nothing and
    records nothing. Returns how many were live."""
    await acquire_write_gate(session)
    result = await session.execute(
        update(SessionRow)
        .where(SessionRow.revoked_at.is_(None), SessionRow.auth_mode != auth_mode)
        .values(revoked_at=_now())
    )
    revoked = result.rowcount or 0
    if revoked:
        await audit.record_event(
            session,
            audit.SESSIONS_REVOKED,
            principal=internal(),
            target="startup",
            detail=f"count={revoked}",
            client_address="host",
        )
        await audit.record_event(
            session,
            audit.AUTH_MODE_CHANGED,
            principal=internal(),
            target="startup",
            detail=f"auth_mode={auth_mode} sessions_revoked={revoked}",
            client_address="host",
        )
        log.warning(
            "Auth mode is now %s: %d browser session(s) from the previous mode signed out.",
            auth_mode,
            revoked,
        )
    await session.commit()
    return revoked


# --- the flows ------------------------------------------------------------------


async def claim_instance(
    session: AsyncSession,
    *,
    password: str,
    request: Request | None = None,
) -> str:
    """`POST /auth/setup` after the token matched: claim the owner row, set the
    credential, open the first session. Returns the raw session token. 410 when
    the instance is already claimed — the token check happens before this and
    is the router's, because the token lives in the process, not the database."""
    await acquire_write_gate(session)
    owner = await owner_row(session, for_update=True)
    if owner.claimed_at is not None:
        raise GoneError(_SETUP_CLAIMED, code=error_codes.AUTH_SETUP_CLAIMED)
    validate_password(password)
    now = _now()
    await _replace_credential(session, password)
    owner.claimed_at = now
    raw, row = new_session_row(now, auth_mode=AuthMode.LOCAL)
    session.add(row)
    await session.flush()
    await audit.record_event(
        session,
        audit.SETUP_CLAIMED,
        principal=owner_principal(row),
        request=request,
        target="/auth/setup",
    )
    await session.commit()
    return raw


def owner_principal(row: SessionRow) -> Principal:
    from app.auth.principal import owner

    return owner(subject=str(row.id), via="session")


async def refuse_throttled(
    session: AsyncSession,
    budget: FailureBudget,
    *,
    request: Request | None,
    target: str,
) -> None:
    """Raise the 429 when the budget is shut — with the audit row committed
    first, since the raise rolls back."""
    retry_after = budget.retry_after()
    if retry_after is None:
        return
    await audit.record_event(
        session,
        audit.LOGIN_THROTTLED,
        principal=anonymous(),
        request=request,
        target=target,
        detail=f"retry_after={retry_after}",
    )
    await session.commit()
    raise RateLimitedError(
        _THROTTLED.format(seconds=retry_after),
        code=error_codes.AUTH_TOO_MANY_ATTEMPTS,
        params={"retry_after": retry_after},
        retry_after=retry_after,
    )


async def record_setup_failure(
    session: AsyncSession,
    budget: FailureBudget,
    *,
    request: Request | None,
    target: str = "/auth/setup",
) -> None:
    """A wrong setup token: counts against the budget, audited, refused as a
    rejected form credential (403 — see `CredentialRejectedError`). The OIDC
    start presents the same token (#191) and names its own route as `target`."""
    budget.record_failure()
    await audit.record_event(
        session,
        audit.SETUP_FAILED,
        principal=anonymous(),
        request=request,
        target=target,
    )
    await session.commit()
    raise CredentialRejectedError(_SETUP_TOKEN_INVALID, code=error_codes.AUTH_SETUP_TOKEN_INVALID)


async def login(
    session: AsyncSession,
    *,
    password: str,
    budget: FailureBudget,
    request: Request | None = None,
) -> str:
    """`POST /auth/login`. Returns the raw session token for the cookie.

    One failure path for both failure kinds (T11): the password is verified
    against the stored verifier or, when there is none — an unclaimed instance —
    against `DUMMY_HASH`, so the work done and the status, code and body
    returned are identical. The refusal is 403 (`CredentialRejectedError`), not a
    401 that could carry no honest challenge. Every failure counts against the budget and is
    audited; a success resets the budget and re-hashes a verifier made with
    older parameters."""
    await refuse_throttled(session, budget, request=request, target="/auth/login")
    await acquire_write_gate(session)
    credential = await _the_credential(session)
    verified = credentials.verify_password(
        credential.secret_hash if credential is not None else None, password
    )
    if not (verified and credential is not None):
        budget.record_failure()
        await audit.record_event(
            session,
            audit.LOGIN_FAILED,
            principal=anonymous(),
            request=request,
            target="/auth/login",
        )
        await session.commit()
        raise CredentialRejectedError(_LOGIN_FAILED, code=error_codes.AUTH_LOGIN_FAILED)
    budget.reset()
    if credentials.password_needs_rehash(credential.secret_hash):
        credential.secret_hash = credentials.hash_password(password)
    raw, row = new_session_row(_now(), auth_mode=AuthMode.LOCAL)
    session.add(row)
    await session.flush()
    await audit.record_event(
        session,
        audit.LOGIN_SUCCEEDED,
        principal=owner_principal(row),
        request=request,
        target="/auth/login",
    )
    await session.commit()
    return raw


async def logout(
    session: AsyncSession,
    row: SessionRow,
    *,
    principal: Principal | None = None,
    request: Request | None = None,
) -> None:
    """Revoke the presented session. Idempotent on an already-revoked row."""
    await acquire_write_gate(session)
    if row.revoked_at is None:
        row.revoked_at = _now()
    await audit.record_event(
        session, audit.LOGGED_OUT, principal=principal, request=request, target="/auth/logout"
    )
    await session.commit()


async def recovery_reset_password(session: AsyncSession, *, password: str) -> int:
    """The host-side break-glass (§5.6, credentials lost): claim the owner row if
    it is unclaimed, replace the credential, revoke every session. Never an HTTP
    endpoint. Returns the number of sessions revoked."""
    validate_password(password)
    await acquire_write_gate(session)
    owner = await owner_row(session, for_update=True)
    if owner.claimed_at is None:
        owner.claimed_at = _now()
    await _replace_credential(session, password)
    revoked = await revoke_all_sessions(
        session,
        target="recovery reset-password",
        principal=internal(),
        client_address="host",
    )
    await audit.record_event(
        session,
        audit.RECOVERY_RUN,
        principal=internal(),
        target="recovery reset-password",
        detail=f"sessions_revoked={revoked}",
        client_address="host",
    )
    await session.commit()
    return revoked


async def recovery_revoke_sessions(session: AsyncSession) -> int:
    await acquire_write_gate(session)
    revoked = await revoke_all_sessions(
        session,
        target="recovery revoke-sessions",
        principal=internal(),
        client_address="host",
    )
    await audit.record_event(
        session,
        audit.RECOVERY_RUN,
        principal=internal(),
        target="recovery revoke-sessions",
        detail=f"sessions_revoked={revoked}",
        client_address="host",
    )
    await session.commit()
    return revoked
