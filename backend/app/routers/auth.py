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
from fastapi.responses import RedirectResponse

from app import error_codes
from app.auth import credentials
from app.auth.budget import FailureBudget
from app.auth.principal import PrincipalKind
from app.auth.resolver import RAW_SESSION_TOKEN_ATTR
from app.auth.sessions import (
    clear_oidc_login_cookie,
    clear_session_cookie,
    cookie_is_secure,
    oidc_cookie_name,
    set_oidc_login_cookie,
    set_session_cookie,
)
from app.auth.setup_token import setup_token_state
from app.config import get_settings
from app.db import SessionDep
from app.exceptions import GoneError, NotFoundError
from app.schemas.auth import (
    LoginRequest,
    OidcStartRead,
    OidcStartRequest,
    SessionRead,
    SetupRequest,
)
from app.services import auth as auth_service
from app.services import instance_settings as settings_service
from app.services import oidc as oidc_service
from app.services.oidc import OidcLoginRefused, OidcProvider

router = APIRouter(prefix="/auth", tags=["auth"])

#: The attribute on `app.state` holding the one login/setup failure budget.
BUDGET_ATTR = "login_budget"
#: The attribute on `app.state` holding the configured `OidcProvider` — set by
#: `create_app` in OIDC mode, absent in local mode (#191). Its presence *is* the
#: mode as the routes see it.
OIDC_PROVIDER_ATTR = "oidc_provider"

_NOT_IN_THIS_MODE = "This instance does not sign in that way; see AUTH_MODE."
#: The query parameter the callback hands a failed round trip back to the SPA
#: in — a code from `error_codes.OIDC_ERROR_*`, never a description.
AUTH_ERROR_PARAM = "auth_error"


def _budget(request: Request) -> FailureBudget:
    budget = getattr(request.app.state, BUDGET_ATTR, None)
    if budget is None:
        budget = FailureBudget()
        setattr(request.app.state, BUDGET_ATTR, budget)
    return budget


def _oidc(request: Request) -> OidcProvider | None:
    return getattr(request.app.state, OIDC_PROVIDER_ATTR, None)


def _require_mode(request: Request, *, oidc: bool) -> OidcProvider | None:
    """The route belongs to one authentication mode (§5.4, mutually exclusive):
    in the other it is 404 — registered and answering itself, so the
    anonymous fallback cannot turn a mode into a challenge (§5.5)."""
    provider = _oidc(request)
    if (provider is not None) != oidc:
        raise NotFoundError(_NOT_IN_THIS_MODE, code=error_codes.AUTH_NOT_IN_THIS_MODE)
    return provider


async def _session_read(
    request: Request,
    session,
    *,
    state: auth_service.InstanceState,
    raw_token: str | None,
):
    settings_row = await settings_service.get_instance_settings(session)
    provider = _oidc(request)
    return SessionRead(
        state=state.value,
        interface_language=settings_row.interface_language,
        formatting_locale=settings_row.formatting_locale,
        csrf_token=(
            credentials.csrf_token_for(raw_token)
            if state is auth_service.InstanceState.OWNER and raw_token
            else None
        ),
        auth_mode="oidc" if provider is not None else "local",
        oidc_issuer=provider.issuer if provider is not None else None,
    )


async def _needs_setup(request: Request, session) -> bool:
    """`unclaimed` as the SPA should see it: no owner yet in local mode; in OIDC
    mode also a claimed owner with no binding (a mode switch, a rebind)."""
    if _oidc(request) is not None:
        return await oidc_service.owner_is_unbound(session)
    return not await auth_service.is_claimed(session)


@router.get("/session", response_model=SessionRead)
async def read_session(request: Request, session: SessionDep) -> SessionRead:
    """What the SPA needs before it can render: the claim state, whether this
    browser is the owner, the instance language/locale, and (for the owner) the
    CSRF token. `no-store`, no version, no collection data (§5.5, family 2)."""
    principal = getattr(request.state, "principal", None)
    if principal is not None and principal.kind is PrincipalKind.OWNER:
        raw_token = getattr(request.state, RAW_SESSION_TOKEN_ATTR, None)
        return await _session_read(
            request, session, state=auth_service.InstanceState.OWNER, raw_token=raw_token
        )
    if await _needs_setup(request, session):
        return await _session_read(
            request, session, state=auth_service.InstanceState.UNCLAIMED, raw_token=None
        )
    return await _session_read(
        request, session, state=auth_service.InstanceState.ANONYMOUS, raw_token=None
    )


@router.post("/setup", response_model=SessionRead)
async def setup(
    request: Request, response: Response, session: SessionDep, payload: SetupRequest
) -> SessionRead:
    """Claim an unclaimed instance with the setup token from the API log and a
    first password. 410 once claimed; 403 on a wrong token; 429 when throttled.
    Local mode only — in OIDC mode the claim is the first provider login."""
    _require_mode(request, oidc=False)
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
    return await _session_read(
        request, session, state=auth_service.InstanceState.OWNER, raw_token=raw
    )


@router.post("/login", response_model=SessionRead)
async def login(
    request: Request, response: Response, session: SessionDep, payload: LoginRequest
) -> SessionRead:
    """Sign in. One body and timing for every failure kind (T11); the failure
    budget throttles repeated attempts (T8). Local mode only."""
    _require_mode(request, oidc=False)
    budget = _budget(request)
    raw = await auth_service.login(
        session, password=payload.password, budget=budget, request=request
    )
    set_session_cookie(response, raw, secure=cookie_is_secure(get_settings()))
    return await _session_read(
        request, session, state=auth_service.InstanceState.OWNER, raw_token=raw
    )


@router.post("/oidc/start", response_model=OidcStartRead)
async def oidc_start(
    request: Request, response: Response, session: SessionDep, payload: OidcStartRequest
) -> OidcStartRead:
    """Begin a login at the identity provider (OIDC mode only; §5.6 open
    redirect). Answers the authorization URL for the browser to go to and sets
    the login-binding cookie; the SPA navigates. A POST, not a redirecting GET:
    the setup token an unbound instance needs travels in a JSON body, never a
    query string (T10), and an unsafe method gets the Origin check every
    family-3 action has (§5.6, CSRF) — a hostile page cannot start a login the
    owner did not ask for."""
    provider = _require_mode(request, oidc=True)
    assert provider is not None
    url, binding = await oidc_service.begin_login(
        session,
        provider,
        request=request,
        setup_token=payload.setup_token,
        setup_state=setup_token_state(request.app),
        budget=_budget(request),
    )
    set_oidc_login_cookie(response, binding, secure=cookie_is_secure(get_settings()))
    return OidcStartRead(authorization_url=url)


@router.get("/oidc/callback", response_class=RedirectResponse, include_in_schema=True)
async def oidc_callback(
    request: Request,
    session: SessionDep,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """The provider's redirect back (OIDC mode only). A browser navigation, so
    every outcome is a 302 to the SPA's root built from `PUBLIC_BASE_URL` (never
    from Host): with the session cookie on success, with `?auth_error=<code>`
    on refusal. The login-binding cookie is cleared either way."""
    provider = _require_mode(request, oidc=True)
    assert provider is not None
    secure = cookie_is_secure(get_settings())
    binding = request.cookies.get(oidc_cookie_name(secure))
    try:
        raw = await oidc_service.complete_login(
            session,
            provider,
            request=request,
            state=state,
            code=code,
            error=error,
            binding=binding,
            setup_state=setup_token_state(request.app),
        )
    except OidcLoginRefused as refused:
        response = RedirectResponse(
            f"{provider.home_url}?{AUTH_ERROR_PARAM}={refused.code}", status_code=302
        )
        clear_oidc_login_cookie(response, secure=secure)
        return response
    response = RedirectResponse(provider.home_url, status_code=302)
    clear_oidc_login_cookie(response, secure=secure)
    set_session_cookie(response, raw, secure=secure)
    return response


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
