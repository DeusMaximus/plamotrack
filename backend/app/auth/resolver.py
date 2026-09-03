"""Resolving a request to a `Principal` (§5.5).

M6-2 laid the seam; M6-3 fills in the browser session (#188), M6-4 the bearer
(#189). The order is fixed by §5.5: the pytest injection seam first (a test-only
`app.state` attribute the shipped image never sets), then the real credential —
today the owner's session cookie, `anon` when there is none.

**A non-resolving session cookie is `anon`, not 401** (deliberate divergence from
§5.5's literal "presented-and-failed → 401", recorded in the PR). The session
cookie is `HttpOnly`, so a browser cannot clear a stale one from script; a 401 on
a cookie the client cannot drop would wedge `GET /auth/session` — the very
endpoint the SPA bootstraps and recovers through — in a loop. Treating a stale
cookie as absent keeps recovery automatic: `GET /auth/session` answers
`anonymous`, and the next login overwrites the cookie. The strict rule stands for
the **bearer** (#189), where the client owns the header and there is nothing to
wedge. An *absent* cookie was always `anon`.

The readiness route's `internal` principal is not decided here: it is the raw TCP
peer, read by the route from `scope["client"]` (`app/ingress.is_internal_peer`),
because a forwarded header must never be able to claim it (§5.6, proxy trust).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.auth.principal import VIA_SESSION, Principal, anonymous, owner
from app.auth.sessions import cookie_is_secure, cookie_name
from app.config import get_settings

#: The `app.state` attribute the pytest harness sets to force a principal for a
#: request. Absent on the shipped app, so production always falls through to the
#: real resolution below. There is no `AUTH_MODE=disabled` and no settings row
#: that turns authentication off (§5.6, route bypass): this is the only bypass,
#: and it exists only in the test image.
INJECTED_PRINCIPAL_ATTR = "authorization_injected_principal"

#: Where the resolved owner's raw session token is stashed for the dependency's
#: CSRF check to key on (never leaves the process; not the digest, the raw value).
RAW_SESSION_TOKEN_ATTR = "raw_session_token"


async def resolve_principal(request: Request, session: AsyncSession) -> Principal:
    """The principal for this request: the injected test principal if the harness
    set one; otherwise the owner's session cookie, or `anon`.

    Resolves on the **request's own session** (the one the handler will use), not a
    session of its own — a second connection per request both costs a connection
    and, holding a read lock on `session`/`owner` while the handler's transaction
    runs, deadlocks against anything taking `ACCESS EXCLUSIVE` on those tables
    (the test teardown's TRUNCATE found it immediately). The `last_used_at` touch
    `resolve_session` may make is committed by the request's own transaction
    teardown; a read never takes the write gate (rule 7.1)."""
    injected = getattr(request.app.state, INJECTED_PRINCIPAL_ATTR, None)
    if injected is not None:
        return injected

    raw_token = request.cookies.get(cookie_name(cookie_is_secure(get_settings())))
    if not raw_token:
        return anonymous()

    from app.services import auth as auth_service

    row = await auth_service.resolve_session(session, raw_token)
    if row is None:
        return anonymous()
    setattr(request.state, RAW_SESSION_TOKEN_ATTR, raw_token)
    return owner(subject=str(row.id), via=VIA_SESSION)
