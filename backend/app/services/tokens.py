"""Personal access tokens — the service layer (§5.5 family 6 for management,
`pat:*` as a principal; §5.6; M6-4, #189).

Management — mint, list, revoke — happens only under the owner's session (the
routes are family 6, `instance:admin`, so a token cannot mint a token); each is
a mutation and takes the write gate first (rule 7.1). Resolution — turning a
presented bearer into the row it names, or a refusal — is `resolve_bearer`, the
**one** helper the REST resolver (`app/auth/resolver.py`) and the MCP verifier
(`app/auth/tokens.py`'s `PersonalAccessTokenVerifier`) both call, so the two
surfaces cannot drift on what a valid token is (§5.6, scope escalation).

The rules `resolve_bearer` applies, in order, all answering the same refusal:
the string must be shaped like a token (`ptk_<id>_<secret>`); the public id must
name a row — when it does not, the compare still runs, against `DUMMY_DIGEST`
(T11); the digest must match; the row must not be revoked — a revoked row whose
secret matched is audited as use-after-revoke, because that is a leaked or
never-rotated credential, not a guess; and the row must not be expired. A
successful resolution touches `last_used_at` at most every
`LAST_USED_WRITE_INTERVAL`, committed by the caller's transaction.

What this module does not know: headers, requests, cookies. The resolver and
the verifier own those.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app import error_codes
from app.auth import credentials
from app.auth import tokens as token_format
from app.auth.principal import VIA_BEARER, Principal, Scope, pat
from app.auth.sessions import LAST_USED_WRITE_INTERVAL
from app.exceptions import InvalidInputError, NotFoundError
from app.models import PersonalAccessToken
from app.services import audit
from app.services.write_gate import acquire_write_gate

#: `TokenCreate.name` after stripping must be non-empty and no longer than this.
MAX_NAME_LENGTH = 100

_NAME_BLANK = "The token needs a name."
_SCOPE_INVALID = (
    "A token holds collection:read, or collection:read and collection:write — "
    "nothing else, and never instance:admin."
)
_EXPIRY_IN_PAST = "The expiry has to be in the future."
_NOT_FOUND = "That access token no longer exists."


def _now() -> datetime:
    return datetime.now(UTC)


# --- what a resolved token is -----------------------------------------------------


@dataclass(frozen=True)
class BearerResolution:
    """The outcome of presenting one bearer: the live row (and its principal),
    or a refusal naming why — `malformed`, `unknown`, `mismatch`, `revoked`,
    `expired`. The reason is for audit and tests; the wire answer is one status,
    code and body for every reason (T11)."""

    row: PersonalAccessToken | None
    reason: str | None

    @property
    def ok(self) -> bool:
        return self.row is not None

    @property
    def principal(self) -> Principal:
        assert self.row is not None
        return principal_for(self.row)


def principal_for(row: PersonalAccessToken) -> Principal:
    scopes = token_format.decode_scopes(row.scopes)
    return pat(write=Scope.WRITE in scopes, subject=str(row.id), via=VIA_BEARER)


async def resolve_bearer(
    session: AsyncSession,
    raw: str,
    *,
    request: Request | None = None,
    client_address: str | None = None,
) -> BearerResolution:
    """The row a presented bearer names, or the refusal. Never raises for a bad
    token — the caller decides the wire shape (401 on REST, the SDK's challenge
    on MCP). The audit row for use-after-revoke and the `last_used_at` touch are
    added to `session`; the caller commits (before raising, on the REST side —
    a raise rolls the transaction back)."""
    public_id = token_format.public_id_of(raw)
    if public_id is None:
        return BearerResolution(None, "malformed")
    row = (
        await session.execute(
            select(PersonalAccessToken).where(PersonalAccessToken.token_prefix == public_id)
        )
    ).scalar_one_or_none()
    # The compare runs whether or not the id named a row (T11): same work, same
    # answer shape, and `compare_digest` by construction.
    expected = row.secret_hash if row is not None else token_format.DUMMY_DIGEST
    matched = credentials.tokens_match(raw, expected)
    if row is None:
        return BearerResolution(None, "unknown")
    if not matched:
        return BearerResolution(None, "mismatch")
    if row.revoked_at is not None:
        await audit.record_event(
            session,
            audit.TOKEN_USE_AFTER_REVOKE,
            principal=principal_for(row),
            request=request,
            target=request.url.path if request is not None else "/mcp/",
            detail=f"token={row.id}",
            client_address=client_address,
        )
        return BearerResolution(None, "revoked")
    now = _now()
    if row.expires_at is not None and now >= row.expires_at:
        return BearerResolution(None, "expired")
    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_WRITE_INTERVAL:
        row.last_used_at = now
    return BearerResolution(row, None)


# --- management (family 6) --------------------------------------------------------


def validate_scopes(requested: list[Scope] | set[Scope] | frozenset[Scope]) -> frozenset[Scope]:
    """The granted set for a mint request: non-empty and within the grantable
    two. Admin is refused here, not silently dropped — a request that asked for
    it should hear no (§5.5, no admin tokens in M6)."""
    granted = frozenset(requested)
    if not granted or not granted <= token_format.GRANTABLE_SCOPES:
        raise InvalidInputError(_SCOPE_INVALID, code=error_codes.AUTH_TOKEN_SCOPE_INVALID)
    return granted


def validate_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        raise InvalidInputError(_NAME_BLANK, code=error_codes.NAME_BLANK)
    if len(stripped) > MAX_NAME_LENGTH:
        raise InvalidInputError(
            f"The token name can't be longer than {MAX_NAME_LENGTH} characters.",
            code=error_codes.VALUE_OUT_OF_RANGE,
            params={"value": len(stripped)},
        )
    return stripped


def validate_expiry(expires_at: datetime | None, *, now: datetime) -> datetime | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        # Pydantic hands over aware datetimes for offset-bearing input; a naive
        # one would compare wrongly, so it is refused as an invalid value.
        raise InvalidInputError(
            "The expiry needs a UTC offset.",
            code=error_codes.SETTINGS_VALUE_INVALID,
            params={"field": "expires_at"},
        )
    if expires_at <= now:
        raise InvalidInputError(_EXPIRY_IN_PAST, code=error_codes.AUTH_TOKEN_EXPIRY_IN_PAST)
    return expires_at


async def mint_token(
    session: AsyncSession,
    *,
    name: str,
    scopes: list[Scope] | set[Scope] | frozenset[Scope],
    expires_at: datetime | None = None,
    principal: Principal | None = None,
    request: Request | None = None,
) -> tuple[str, PersonalAccessToken]:
    """Mint a token: returns `(raw, row)`. The raw value is shown once and never
    stored; the row holds its digest. Audited as `auth.token_minted` naming the
    token id and scopes — never the secret."""
    await acquire_write_gate(session)
    now = _now()
    clean_name = validate_name(name)
    granted = validate_scopes(scopes)
    expiry = validate_expiry(expires_at, now=now)
    public_id, raw = token_format.mint_raw()
    row = PersonalAccessToken(
        token_prefix=public_id,
        secret_hash=credentials.digest(raw),
        name=clean_name,
        scopes=token_format.encode_scopes(granted),
        expires_at=expiry,
    )
    session.add(row)
    await session.flush()
    await audit.record_event(
        session,
        audit.TOKEN_MINTED,
        principal=principal,
        request=request,
        target="/auth/tokens",
        detail=f"token={row.id} scopes={row.scopes}",
    )
    await session.commit()
    return raw, row


async def list_tokens(session: AsyncSession) -> list[PersonalAccessToken]:
    """Every token, newest first, revoked ones included — a revoked token is
    history the owner may want to see (when it was last used, that it is gone)."""
    result = await session.execute(
        select(PersonalAccessToken).order_by(
            PersonalAccessToken.created_at.desc(), PersonalAccessToken.id
        )
    )
    return list(result.scalars().all())


async def revoke_token(
    session: AsyncSession,
    token_id: uuid.UUID,
    *,
    principal: Principal | None = None,
    request: Request | None = None,
) -> PersonalAccessToken:
    """Revoke one token: `revoked_at` set, the row kept. Idempotent — revoking a
    revoked token changes nothing and is still audited, so a repeated click is
    not an error. 404 for an id no token has."""
    await acquire_write_gate(session)
    row = await session.get(PersonalAccessToken, token_id, with_for_update=True)
    if row is None:
        raise NotFoundError(_NOT_FOUND, code=error_codes.AUTH_TOKEN_NOT_FOUND)
    if row.revoked_at is None:
        row.revoked_at = _now()
    await audit.record_event(
        session,
        audit.TOKEN_REVOKED,
        principal=principal,
        request=request,
        target=f"/auth/tokens/{row.id}",
        detail=f"token={row.id}",
    )
    await session.commit()
    return row
