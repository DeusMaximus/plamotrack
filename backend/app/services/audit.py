"""Audit events (§5.6, log and audit hygiene; M6-3 wrote the first rows and
M6-8/#193 completed ingress recording and retention).

One row per security-relevant event, carrying who (the principal's kind and its
credential subject — an id, never the secret), where from (the client address as
resolved behind `TRUSTED_PROXIES`, the raw peer otherwise), and what (the route
or tool, a short structured note). **Never a secret, never a request body.**
Appended inside the caller's transaction, so an event and the state change it
records commit or roll back together.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.types import Scope

from app.auth.principal import Principal, anonymous, internal
from app.db import session_scope
from app.ingress import CLIENT_ADDRESS_KEY, IngressPolicy, client_address_from_scope
from app.models import AuditEvent
from app.services.write_gate import acquire_write_gate

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

# --- ingress and maintenance vocabulary (#193) ---------------------------------
HOST_REJECTED = "ingress.host_rejected"
ORIGIN_REJECTED = "ingress.origin_rejected"
AUDIT_PRUNED = "auth.audit_pruned"

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


async def record_ingress_rejection(
    event_type: str,
    scope: Scope,
    *,
    policy: IngressPolicy,
    setting: str,
) -> None:
    """Persist a Host/Origin refusal before routing.

    The guard deliberately runs before credential resolution, so the caller is
    recorded as anonymous and no credential-bearing header is inspected. The
    target is the decoded path only — never the query string or request body.
    This owns its transaction because a rejected request never reaches FastAPI's
    request-scoped database session.
    """
    async with session_scope() as session:
        await record_event(
            session,
            event_type,
            principal=anonymous(),
            target=scope.get("path"),
            detail=f"method={scope.get('method', '')} setting={setting}",
            client_address=client_address_from_scope(scope, policy),
        )


async def prune_events(
    session: AsyncSession,
    *,
    before: datetime,
) -> int:
    """Delete audit rows older than ``before`` and record the maintenance act.

    This is host-side maintenance, not an HTTP route. The strict ``<`` boundary
    makes a row exactly at the requested cutoff a keeper, and the prune event is
    appended after the delete so it cannot remove itself.
    """
    await acquire_write_gate(session)
    result = await session.execute(delete(AuditEvent).where(AuditEvent.occurred_at < before))
    deleted = result.rowcount or 0
    await record_event(
        session,
        AUDIT_PRUNED,
        principal=internal(),
        target="maintenance prune-audit",
        detail=f"deleted={deleted} before={before.isoformat()}",
        client_address="host",
    )
    await session.commit()
    return deleted
