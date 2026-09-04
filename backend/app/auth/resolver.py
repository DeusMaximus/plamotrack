"""Resolving a request to a `Principal` (§5.5).

M6-2 laid the seam; M6-3 filled in the browser session (#188); M6-4 the bearer
(#189). The order is fixed by §5.5: the pytest injection seam first (a test-only
`app.state` attribute the shipped image never sets); then a presented
`Authorization` header — a personal access token, **strictly**: presented and
failed is 401, never `anon`; then the owner's session cookie; `anon` when there
is neither.

**A non-resolving session cookie is `anon`, not 401** (deliberate divergence from
§5.5's literal "presented-and-failed → 401", recorded in PR #200). The session
cookie is `HttpOnly`, so a browser cannot clear a stale one from script; a 401 on
a cookie the client cannot drop would wedge `GET /auth/session` — the very
endpoint the SPA bootstraps and recovers through — in a loop. Treating a stale
cookie as absent keeps recovery automatic: `GET /auth/session` answers
`anonymous`, and the next login overwrites the cookie. The strict rule stands for
the **bearer**, where the client owns the header and there is nothing to wedge:
an unknown id, a wrong secret, a revoked or expired token, a header that is not
a bearer at all — each is 401 `auth.bearer_invalid` with `WWW-Authenticate:
Bearer error="invalid_token"`, on every route the dependency covers, the
anonymous families included (a stale bearer on `POST /auth/login` is 401, and
retrying without it enters the normal login flow). A bearer beside a cookie is
decided as a bearer: the request is bearer-borne, so the CSRF controls do not
apply and the cookie is not consulted.

Only the header is read. A token in a query parameter lands in access logs and
`Referer` (§5.6), so it is never a credential here — it is simply ignored and
the request resolves as if it carried nothing.

**A session is authority only in the mode that minted it** (#191; Codex #209
round 1, f1). The cookie is resolved against the mode this app runs in
(`app.auth.mode`): a password-flow session kept across the switch to OIDC mode,
or a provider-minted one kept across the switch back, is `anon` here — the same
stale-cookie rule — and the lifespan's sweep revokes it for good.

The readiness route's `internal` principal is not decided here: it is the raw TCP
peer, read by the route from `scope["client"]` (`app/ingress.is_internal_peer`),
because a forwarded header must never be able to claim it (§5.6, proxy trust).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app import error_codes
from app.auth import tokens as token_format
from app.auth.mode import auth_mode_of
from app.auth.principal import VIA_SESSION, Principal, anonymous, owner
from app.auth.sessions import cookie_is_secure, cookie_name
from app.config import get_settings
from app.exceptions import UnauthenticatedError

#: The `app.state` attribute the pytest harness sets to force a principal for a
#: request. Absent on the shipped app, so production always falls through to the
#: real resolution below. There is no `AUTH_MODE=disabled` and no settings row
#: that turns authentication off (§5.6, route bypass): this is the only bypass,
#: and it exists only in the test image.
INJECTED_PRINCIPAL_ATTR = "authorization_injected_principal"

#: Where the resolved owner's raw session token is stashed for the dependency's
#: CSRF check to key on (never leaves the process; not the digest, the raw value).
RAW_SESSION_TOKEN_ATTR = "raw_session_token"

#: The challenge a presented-and-failed bearer earns (RFC 6750 §3.1).
INVALID_TOKEN_CHALLENGE = 'Bearer error="invalid_token"'

_BEARER_INVALID = "That access token isn't valid."


async def resolve_principal(request: Request, session: AsyncSession) -> Principal:
    """The principal for this request: the injected test principal if the harness
    set one; otherwise the bearer if an `Authorization` header is present (401
    if it fails); otherwise the owner's session cookie, or `anon`.

    Resolves on the session the caller passes, and takes none of its own. On the
    shipped app that caller is the **pre-routing gate** (`app/auth/prerouting.py`,
    #204): a short `session_scope()` opened before the router runs and closed —
    committing the `last_used_at` touch `resolve_session`/`resolve_bearer` may
    make — before the handler's transaction opens, with the principal stashed on
    the request state for the dependency to reuse. The dependency resolves here
    itself only as the fallback for an app built without the gate, on the
    request's own session, where the touch is committed by that transaction's
    teardown. What must hold either way is **no overlap**: a second session left
    open across the handler holds a read lock on `session`/`owner` while the
    handler's transaction runs and deadlocks against anything taking `ACCESS
    EXCLUSIVE` on those tables (the test teardown's TRUNCATE found it
    immediately when this was first tried as a second session per request). A
    read never takes the write gate (rule 7.1)."""
    injected = getattr(request.app.state, INJECTED_PRINCIPAL_ATTR, None)
    if injected is not None:
        return injected

    presented = token_format.bearer_from_headers(request.headers)
    if presented is not None:
        return await _resolve_bearer(request, session, presented)

    raw_token = request.cookies.get(cookie_name(cookie_is_secure(get_settings())))
    if not raw_token:
        return anonymous()

    from app.services import auth as auth_service

    row = await auth_service.resolve_session(
        session, raw_token, auth_mode=auth_mode_of(request.app)
    )
    if row is None:
        return anonymous()
    setattr(request.state, RAW_SESSION_TOKEN_ATTR, raw_token)
    return owner(subject=str(row.id), via=VIA_SESSION)


async def _resolve_bearer(request: Request, session: AsyncSession, presented: object) -> Principal:
    from app.services import tokens as token_service

    if presented is token_format.MALFORMED:
        raise UnauthenticatedError(
            _BEARER_INVALID,
            code=error_codes.AUTH_BEARER_INVALID,
            challenge=INVALID_TOKEN_CHALLENGE,
        )
    assert isinstance(presented, str)
    resolution = await token_service.resolve_bearer(session, presented, request=request)
    if not resolution.ok:
        # The refusal rolls the request transaction back; the use-after-revoke
        # audit row (if any) has to land first (the login-failure precedent).
        await session.commit()
        raise UnauthenticatedError(
            _BEARER_INVALID,
            code=error_codes.AUTH_BEARER_INVALID,
            challenge=INVALID_TOKEN_CHALLENGE,
        )
    return resolution.principal
