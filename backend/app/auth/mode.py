"""Which authentication mode a running app is in, as the resolver and the
routes read it (§5.4; #191).

The mode is the operator's `AUTH_MODE`, env-only; `create_app` turns it into
one thing on `app.state` — the configured `OidcProvider` in OIDC mode, nothing
in local mode — and that presence *is* the mode everywhere the app decides by
it: the family-3 routes answer 404 in the other mode, the lifespan warms and
announces by it, and the resolver refuses a browser session minted in the other
mode (a session is authority only in the mode that minted it; Codex #209 round
1, f1). One source, so a test can build an OIDC-mode app beside the shipped
local one in the same process.
"""

from __future__ import annotations

from starlette.applications import Starlette

from app.models.enums import AuthMode

#: The `app.state` attribute holding the configured `OidcProvider` — set by
#: `create_app` in OIDC mode, absent in local mode.
OIDC_PROVIDER_ATTR = "oidc_provider"


def auth_mode_of(app: Starlette) -> AuthMode:
    """The mode this app runs in, read from the provider's presence."""
    if getattr(app.state, OIDC_PROVIDER_ATTR, None) is not None:
        return AuthMode.OIDC
    return AuthMode.LOCAL
