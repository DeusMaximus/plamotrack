"""Resolving a request to a `Principal` (§5.5).

M6-2 lays the seam; the credential mechanisms fill it in. Today the only
principal a real request carries is `anon` — there is no session (#188) and no
bearer (#189) to read — so `resolve_principal` returns `anonymous()` unless the
in-process test seam has injected one. The readiness route's `internal`
principal is not decided here: it is the raw TCP peer, read by the dependency
(`app/ingress.is_internal_peer`), because a forwarded header must never be able
to claim it (§5.6, proxy trust).

The seam is a single attribute on `app.state`, set only by the test harness and
never by `create_app`, so the shipped image cannot be made to inject a
principal — there is no `AUTH_MODE=disabled` and no settings row that turns
authentication off (§5.6, route bypass). When #188/#189 add real credential
parsing it happens here, ahead of the `anon` fallback: an *absent* credential is
`anon`, a *presented and failed* one is 401 (raised here, never a silent
downgrade), per §5.5.
"""

from __future__ import annotations

from starlette.requests import Request

from app.auth.principal import Principal, anonymous

#: The `app.state` attribute the pytest harness sets to force a principal for a
#: request. Absent on the shipped app, so production always falls through to the
#: real resolution below (which is `anon` until #188/#189).
INJECTED_PRINCIPAL_ATTR = "authorization_injected_principal"


def resolve_principal(request: Request) -> Principal:
    """The principal for this request. The injected test principal if the harness
    set one; otherwise the credential-borne principal, which is `anon` until the
    session (#188) and bearer (#189) mechanisms exist."""
    injected = getattr(request.app.state, INJECTED_PRINCIPAL_ATTR, None)
    if injected is not None:
        return injected
    return anonymous()
