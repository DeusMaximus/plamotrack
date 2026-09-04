"""Audit events (§5.6, log and audit hygiene; M6-3 writes the first rows, #193
owns retention and the rest of the vocabulary).

One row per security-relevant event, carrying who (the principal's kind and its
credential subject — an id, never the secret), where from (the client address as
resolved behind `TRUSTED_PROXIES`, the raw peer otherwise), and what (the route
or tool, a short structured note). **Never a secret, never a request body.**
Appended inside the caller's transaction, so an event and the state change it
records commit or roll back together.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.auth.principal import Principal
from app.ingress import CLIENT_ADDRESS_KEY
from app.models import AuditEvent

# --- the M6-3 vocabulary --------------------------------------------------------
SETUP_CLAIMED = "auth.setup_claimed"
SETUP_FAILED = "auth.setup_failed"
LOGIN_SUCCEEDED = "auth.login_succeeded"
LOGIN_FAILED = "auth.login_failed"
LOGIN_THROTTLED = "auth.login_throttled"
LOGGED_OUT = "auth.logged_out"
SESSIONS_REVOKED = "auth.sessions_revoked"
RECOVERY_RUN = "auth.recovery_run"

# --- the M6-4 vocabulary (#189) -------------------------------------------------
TOKEN_MINTED = "auth.token_minted"
TOKEN_REVOKED = "auth.token_revoked"
#: A revoked token presented with its correct secret: the credential leaked or a
#: client was never updated — either way worth a row (§5.6, log and audit).
TOKEN_USE_AFTER_REVOKE = "auth.token_use_after_revoke"

# --- the M6-6 vocabulary (#191) -------------------------------------------------
#: A signed-in identity that is not the bound owner: refused, no session (T6).
OIDC_IDENTITY_REFUSED = "auth.oidc_identity_refused"
#: A login round trip that did not produce a session — the provider returned an
#: error, no live transaction matched, or the id_token failed validation.
OIDC_LOGIN_FAILED = "auth.oidc_login_failed"
#: The owner's OIDC binding cleared by the recovery command (T7); the next
#: provider login with the setup token binds afresh.
OIDC_REBIND = "auth.oidc_rebind"
#: The API started in an authentication mode other than the one that minted
#: the live browser sessions — a mode switch — and revoked them (T7's sibling;
#: Codex #209 round 1, f1). `detail` names the mode now running and the count.
AUTH_MODE_CHANGED = "auth.mode_changed"

# --- the M6-7 vocabulary (#192) -------------------------------------------------
#: The MCP OAuth proxy issued an access/refresh token pair to a client after the
#: bound owner signed in at the provider (§5.5 family 8). `detail` names the
#: MCP client id — a DCR id or a CIMD URL — never a token.
MCP_GRANT_ISSUED = "auth.mcp_grant_issued"
#: A provider identity other than the bound owner completed the MCP OAuth
#: round trip and was refused at issuance — nothing minted, nothing stored
#: (§5.6 open redirect; T6). `detail` names the subject, as the browser login's
#: refusal does.
MCP_IDENTITY_REFUSED = "auth.mcp_identity_refused"
#: A client revoked one of its issued tokens at `/mcp/revoke` and the whole grant
#: went with it — the access token, the refresh token and, best effort, the
#: provider's own refresh token (RFC 7009 §2.1; Codex #212 round 1, f1).
#: `detail` names the client and which half was presented, never a token.
MCP_GRANT_REVOKED = "auth.mcp_grant_revoked"


def client_address_of(request: Request | None) -> str | None:
    if request is None:
        return None
    resolved = request.scope.get("state", {}).get(CLIENT_ADDRESS_KEY)
    if resolved:
        return resolved
    client = request.scope.get("client")
    return client[0] if client else None


async def record_event(
    session: AsyncSession,
    event_type: str,
    *,
    principal: Principal | None = None,
    request: Request | None = None,
    target: str | None = None,
    detail: str | None = None,
    client_address: str | None = None,
) -> AuditEvent:
    """Append one event to the caller's transaction. `detail` is capped at the
    column's 500 characters; nothing here ever formats a body or a secret into it."""
    event = AuditEvent(
        event_type=event_type,
        principal_kind=principal.label if principal is not None else None,
        principal_subject=principal.subject if principal is not None else None,
        client_address=client_address or client_address_of(request),
        target=target if target is not None else (request.url.path if request else None),
        detail=detail[:500] if detail else None,
    )
    session.add(event)
    return event
