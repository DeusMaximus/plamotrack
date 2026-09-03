"""Local owner authentication routes (§5.5 families 2–3; §5.6; M6-3, #188).

Thin over `services/auth.py` (rule 1): the service owns the state changes and the
audit rows, the router owns the HTTP shell — the session cookie, the setup-token
check that lives in the process rather than the database, and the CSRF token
handed back to the owner. The failure budget is one per instance, on `app.state`
(the service reads it); the setup token's digest lives there too.

Every route here is classified **anonymous** by the registry: setup and login
must answer before any credential exists, and each action does its own check —
the setup token, the password, the presented session. `GET /auth/session` is the
SPA's bootstrap and carries no collection data. The ingress Origin guard and the
CSRF dependency still apply to the unsafe ones (a cookie-borne logout owes the
token; §5.6).
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app import error_codes
from app.auth import credentials
from app.auth.budget import FailureBudget
from app.auth.principal import PrincipalKind
from app.auth.resolver import RAW_SESSION_TOKEN_ATTR
from app.auth.sessions import clear_session_cookie, cookie_is_secure, set_session_cookie
from app.auth.setup_token import setup_token_state
from app.config import get_settings
from app.db import SessionDep
from app.exceptions import GoneError
from app.schemas.auth import LoginRequest, SessionRead, SetupRequest
from app.services import auth as auth_service
from app.services import instance_settings as settings_service

router = APIRouter(prefix="/auth", tags=["auth"])

#: The attribute on `app.state` holding the one login/setup failure budget.
BUDGET_ATTR = "login_budget"


def _budget(request: Request) -> FailureBudget:
    budget = getattr(request.app.state, BUDGET_ATTR, None)
    if budget is None:
        budget = FailureBudget()
        setattr(request.app.state, BUDGET_ATTR, budget)
    return budget


async def _session_read(session, *, state: auth_service.InstanceState, raw_token: str | None):
    settings_row = await settings_service.get_instance_settings(session)
    return SessionRead(
        state=state.value,
        interface_language=settings_row.interface_language,
        formatting_locale=settings_row.formatting_locale,
        csrf_token=(
            credentials.csrf_token_for(raw_token)
            if state is auth_service.InstanceState.OWNER and raw_token
            else None
        ),
    )


@router.get("/session", response_model=SessionRead)
async def read_session(request: Request, session: SessionDep) -> SessionRead:
    """What the SPA needs before it can render: the claim state, whether this
    browser is the owner, the instance language/locale, and (for the owner) the
    CSRF token. `no-store`, no version, no collection data (§5.5, family 2)."""
    principal = getattr(request.state, "principal", None)
    if principal is not None and principal.kind is PrincipalKind.OWNER:
        raw_token = getattr(request.state, RAW_SESSION_TOKEN_ATTR, None)
        return await _session_read(
            session, state=auth_service.InstanceState.OWNER, raw_token=raw_token
        )
    if not await auth_service.is_claimed(session):
        return await _session_read(
            session, state=auth_service.InstanceState.UNCLAIMED, raw_token=None
        )
    return await _session_read(session, state=auth_service.InstanceState.ANONYMOUS, raw_token=None)


@router.post("/setup", response_model=SessionRead)
async def setup(
    request: Request, response: Response, session: SessionDep, payload: SetupRequest
) -> SessionRead:
    """Claim an unclaimed instance with the setup token from the API log and a
    first password. 410 once claimed; 401 on a wrong token; 429 when throttled."""
    token_state = setup_token_state(request.app)
    if await auth_service.is_claimed(session):
        token_state.consume()
        raise GoneError(
            "This instance already has an owner. Sign in instead.",
            code=error_codes.AUTH_SETUP_CLAIMED,
        )
    budget = _budget(request)
    await auth_service.refuse_throttled(session, budget, request=request, target="/auth/setup")
    if not token_state.matches(payload.token):
        await auth_service.record_setup_failure(session, budget, request=request)
    raw = await auth_service.claim_instance(session, password=payload.password, request=request)
    token_state.consume()
    budget.reset()
    set_session_cookie(response, raw, secure=cookie_is_secure(get_settings()))
    return await _session_read(session, state=auth_service.InstanceState.OWNER, raw_token=raw)


@router.post("/login", response_model=SessionRead)
async def login(
    request: Request, response: Response, session: SessionDep, payload: LoginRequest
) -> SessionRead:
    """Sign in. One body and timing for every failure kind (T11); the failure
    budget throttles repeated attempts (T8)."""
    budget = _budget(request)
    raw = await auth_service.login(
        session, password=payload.password, budget=budget, request=request
    )
    set_session_cookie(response, raw, secure=cookie_is_secure(get_settings()))
    return await _session_read(session, state=auth_service.InstanceState.OWNER, raw_token=raw)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, session: SessionDep) -> Response:
    """Revoke the presented session and clear the cookie. A no-op for a request
    with no live session — logout is idempotent."""
    secure = cookie_is_secure(get_settings())
    raw_token = getattr(request.state, RAW_SESSION_TOKEN_ATTR, None)
    if raw_token:
        row = await auth_service.resolve_session(session, raw_token)
        if row is not None:
            principal = getattr(request.state, "principal", None)
            await auth_service.logout(session, row, principal=principal, request=request)
    clear_session_cookie(response, secure=secure)
    response.status_code = 204
    return response
