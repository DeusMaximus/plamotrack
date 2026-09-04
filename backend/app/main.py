from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from fastmcp import settings as fastmcp_settings
from fastmcp.server.http import create_streamable_http_app
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app import __version__, error_codes
from app.auth import sessions, setup_token
from app.auth.dependency import (
    ROUTE_INDEX_ATTR,
    ResponseProfileMiddleware,
    bind_route_policies,
    enforce_route_policy,
)
from app.auth.mcp_auth import PersonalAccessTokenVerifier
from app.auth.prerouting import DispatchTable, PreRoutingAuthMiddleware
from app.auth.registry import build_route_index
from app.config import Settings, get_settings
from app.db import SessionDep, get_sessionmaker
from app.exceptions import (
    ConflictError,
    CredentialRejectedError,
    DomainError,
    ForbiddenError,
    GoneError,
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
    UnauthenticatedError,
)
from app.ingress import (
    ForwardedClientMiddleware,
    HostOriginGuardMiddleware,
    IngressPolicy,
    is_internal_peer,
)
from app.mcp import mcp
from app.routers import (
    auth,
    catalog,
    inventory,
    kits,
    meta,
    orders,
    portability,
    retailers,
    settings,
    tokens,
)
from app.schemas.errors import ERROR_RESPONSES

ROUTERS = (
    kits.router,
    inventory.router,
    catalog.router,
    retailers.router,
    orders.router,
    portability.router,
    meta.router,
    settings.router,
    auth.router,
    tokens.router,
)

_DOMAIN_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    InvalidInputError: 422,
    UnauthenticatedError: 401,
    ForbiddenError: 403,
    CredentialRejectedError: 403,
    GoneError: 410,
    RateLimitedError: 429,
}


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """The envelope (#25): `detail` unchanged from pre-#25, `code`/`params` additive.

    Dispatch is exact-type first; the isinstance walk over the ordered dict only
    catches a future subclass, resolving it to its nearest ancestor by insertion
    order — the three leaves themselves have no subclasses today.
    """
    status_code = _DOMAIN_STATUS.get(type(exc))
    if status_code is None:
        status_code = next(
            (status for cls, status in _DOMAIN_STATUS.items() if isinstance(exc, cls)),
            400,
        )
    headers: dict[str, str] = {}
    # A throttle refusal names when the caller may retry (§5.6, brute force).
    if isinstance(exc, RateLimitedError):
        headers["Retry-After"] = str(exc.retry_after)
    # Every 401 names the scheme it takes (RFC 9110 §15.5.2): `Bearer`, or the
    # RFC 6750 `invalid_token` form when a bearer was presented and failed
    # (#189). The family-3 form failures are `CredentialRejectedError` — 403, so
    # they owe no challenge and advertise none (Codex #202 rounds 1–2, f2/f4).
    if isinstance(exc, UnauthenticatedError) and exc.challenge:
        headers["WWW-Authenticate"] = exc.challenge
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.detail, "code": exc.code, "params": jsonable_encoder(exc.params)},
        headers=headers or None,
    )


async def http_exception_envelope(request: Request, exc: StarletteHTTPException) -> Response:
    """Parser-stage 400s enter the envelope (#169 review, P2): the framework
    raises `HTTPException(400)` for a body it cannot read — multipart with no
    boundary, a malformed multipart payload — before any schema or service
    runs, so they escaped both handlers above. Every other HTTPException —
    Starlette's own 404/405 for unrouted paths and bad verbs — keeps the stock
    `{"detail": ...}` body by delegating to FastAPI's default handler: unrouted
    paths are deliberately outside the API's machine contract. An anonymous
    caller never sees those: the pre-routing gate answers 401 first (§5.5
    family 13, #204), so the 404/405 here is an authenticated principal's."""
    if exc.status_code == 400:
        return JSONResponse(
            status_code=400,
            content={
                "detail": str(exc.detail),
                "code": error_codes.REQUEST_BODY_INVALID,
                "params": {},
            },
            headers=getattr(exc, "headers", None),
        )
    return await http_exception_handler(request, exc)


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's 422, in the envelope. `detail` stays the default list body —
    its list-vs-string shape against a service 422 is load-bearing for clients
    and tests — while `code`/`params` make it machine-readable (#25)."""
    findings = jsonable_encoder(exc.errors())
    return JSONResponse(
        status_code=422,
        content={
            "detail": findings,
            "code": error_codes.REQUEST_VALIDATION,
            "params": {
                "errors": [
                    {
                        # loc[0] is the source ("body", "query", "path"); the rest
                        # is the field path clients can point at.
                        "field": ".".join(str(part) for part in finding.get("loc", [])[1:]),
                        "type": finding.get("type", ""),
                    }
                    for finding in findings
                ]
            },
        },
    )


async def healthz() -> dict:
    """Liveness: the process is up and serving. Deliberately touches nothing else."""
    return {"status": "ok"}


async def readyz(request: Request, session: SessionDep) -> dict:
    """Readiness: the API can actually reach Postgres — for the `internal`
    principal only (§5.5, family 10).

    This is what the container healthcheck watches, from inside the container,
    so its peer is loopback. Any other peer — nginx on the compose network, a
    developer's browser, a stranger — gets the same 404 an unrouted path earns:
    readiness says whether the database is reachable, and that is not something
    to hand to whoever can reach the port. /healthz stays public and says only
    that the process is up. The raw socket peer is what decides; nothing
    forwarded is consulted.
    """
    if not is_internal_peer(request.scope):
        raise HTTPException(status_code=404)
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}


def build_mcp_app(policy: IngressPolicy, *, authorization: bool = False):
    """The FastMCP ASGI child for the `/mcp` mount, guarded with the same lists
    as REST (§5.6, Host spoofing): `host_origin_protection=True` is FastMCP's
    strict mode — Host validated on every request, Origin whenever present —
    and the extras are `IngressPolicy.mcp_allowed_hosts` (the configured names,
    each DNS name dotted as well) / `allowed_origins`, to which the guard adds
    the loopback names itself.

    `authorization` puts the transport behind FastMCP's bearer middleware with
    `PersonalAccessTokenVerifier` (§5.5 family 7; #189): a request with no valid
    `Authorization: Bearer` is the SDK's 401 with `WWW-Authenticate: Bearer`, a
    cookie is never read, and the verified token is what the per-tool scope
    middleware reads. Built through `create_streamable_http_app` rather than
    `mcp.http_app(...)` — the latter reads the provider off the shared server
    object, and the pre-auth app (`create_app()`, the harnesses) must keep an
    open mount in the same process as the enforced one; the arguments are the
    ones `http_app` would pass, with `auth` decided per app.

    Slash redirects are off (§5.6, proxy trust): Starlette builds a redirect's
    `Location` from the request's scheme and Host, query string included, which
    behind TLS would bounce an OAuth code to a plain-http URL (M6-7). A
    non-canonical spelling is 404, never 3xx.
    """
    mcp_app = create_streamable_http_app(
        server=mcp,
        streamable_http_path="/",
        auth=PersonalAccessTokenVerifier() if authorization else None,
        json_response=fastmcp_settings.json_response,
        stateless_http=fastmcp_settings.stateless_http,
        debug=fastmcp_settings.debug,
        host_origin_protection=True,
        allowed_hosts=list(policy.mcp_allowed_hosts),
        allowed_origins=list(policy.allowed_origins),
    )
    mcp_app.router.redirect_slashes = False
    if authorization:
        # With a provider, FastMCP registers the transport with `methods=[GET,
        # POST, DELETE]` (and Starlette adds HEAD) where the open route declares
        # none. Left as is, Starlette's own 405 — plain text, `Allow` naming
        # HEAD, sent without passing through the route's binding, so without the
        # profile — would answer an undeclared verb in front of the registry's
        # `RouteBinding`, which is the declared verb boundary for this mount
        # (Codex #198 round 3, f2). Declare none here too, so the binding stays
        # the one boundary and answers in the SDK's shape with `no-store`.
        for route in mcp_app.router.routes:
            if getattr(route, "path", None) == "/":
                route.methods = None  # type: ignore[attr-defined]
    return mcp_app


def _setup_url(config: Settings) -> str:
    """A best-effort URL for the setup-token log line — the instance's own address
    if configured, else the loopback default the compose stack publishes."""
    return f"{config.public_base_url or 'http://localhost:8080'}/setup"


def _register_docs(app: FastAPI) -> None:
    """Schema and docs as **guarded APIRoutes** (§5.5, family 11): FastAPI's auto
    handlers are `add_route` endpoints the app-level dependency never runs for
    (§5.1), so the constructor disables them (`openapi_url`/`docs_url`/`redoc_url`
    = None) and these re-register the same paths as APIRoutes the dependency
    covers. The Swagger OAuth2 redirect helper is not re-registered (dropped,
    §5.5). Endpoint names match the registry's `_classify` (openapi /
    swagger_ui_html / redoc_html). Ungated when `authorization=False`."""

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi() -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui_html() -> HTMLResponse:
        return get_swagger_ui_html(openapi_url="/openapi.json", title="plamotrack — API docs")

    @app.get("/redoc", include_in_schema=False)
    async def redoc_html() -> HTMLResponse:
        return get_redoc_html(openapi_url="/openapi.json", title="plamotrack — API docs")


def create_app(config: Settings | None = None, *, authorization: bool = False) -> FastAPI:
    """The application, built from one `Settings`. Module-level `app` below is
    the one uvicorn and the suite import; tests that need a different ingress
    policy build their own through here rather than mutating that one.

    `authorization` installs the app-level default-deny dependency (§5.5), builds
    the route policy registry onto `app.state`, and enforces the response profile.
    The shipped `app` runs with it **on** since M6-3 (#188): local owner
    authentication makes default-deny usable — an unclaimed instance fails closed
    and prints a setup token, and the browser session claims the owner. Tests that
    need the pre-auth app (ingress, the packaged-stack harnesses) call
    `create_app()` with the default off."""
    config = config or get_settings()
    policy = IngressPolicy.from_settings(config)

    # REST and MCP share one process and one service layer (§2). The MCP
    # endpoint is mounted at /mcp on the same port — a deliberate simplification
    # of §8's two-port layout; split later if operating them separately matters.
    mcp_app = build_mcp_app(policy, authorization=authorization)

    @asynccontextmanager
    async def lifespan(app_: FastAPI):
        # An unclaimed instance prints a one-time setup token at every start
        # until it is claimed (§5.6 safe failure, §5.7). Only when auth is on —
        # the pre-auth app has no owner to claim.
        if authorization:
            # And which cookie mode the owner's session will run in — the
            # operator's only tell when TLS sits in front of an http-configured
            # instance (§5.6; Codex #200 round 1, f1).
            sessions.announce_cookie_mode(config)
            async with get_sessionmaker()() as session:
                from app.services import auth as auth_service

                if not await auth_service.is_claimed(session):
                    setup_token.announce(app_, setup_url=_setup_url(config))
        async with mcp_app.lifespan(app_):  # the MCP session manager lives here
            yield

    # Default deny, one dependency for every REST route (§5.5) — including the
    # re-registered docs/schema routes below, which are APIRoutes for exactly
    # this reason (the auto handlers are not, §5.1).
    route_dependencies = [Depends(enforce_route_policy)] if authorization else []
    app = FastAPI(
        title="plamotrack",
        version=__version__,
        description="Self-hosted Gunpla/plamo collection & build tracker",
        lifespan=lifespan,
        dependencies=route_dependencies,
        # No request-derived redirects (§5.6): `GET /kits/` is 404, not a 307
        # whose Location is built from the request's Host.
        redirect_slashes=False,
        # Disabled and re-registered as guarded APIRoutes (`_register_docs`).
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.state.ingress_policy = policy

    for router in ROUTERS:
        # One envelope for every router's failures (#25) — declared here so a new
        # router cannot forget it.
        app.include_router(router, responses=ERROR_RESPONSES)

    _register_docs(app)
    app.add_api_route("/healthz", healthz, methods=["GET"], include_in_schema=False)
    app.add_api_route("/readyz", readyz, methods=["GET"], include_in_schema=False)
    app.mount("/mcp", mcp_app)

    if authorization:
        # Resolve every effective route to its declared policy now (raises on
        # an undeclared route); the dependency reads this per request.
        route_index = build_route_index(app)
        setattr(app.state, ROUTE_INDEX_ATTR, route_index)
        # The response profile is applied adjacent to the router that selects
        # the route: the middleware below is added FIRST so it is the innermost
        # user middleware, reading the endpoint FastAPI's router records in the
        # very dict it holds and stamping the final response — replacing whatever
        # the handler set; the mounted MCP transport, whose child may stack its
        # own middleware, is bound at the route instead, where the binding also
        # enforces the transport's declared verbs before the SDK runs. Exports
        # returning their own Response, the deny envelope and the transport's
        # responses all carry no-store (Codex #198 f1; round 2 f1; round 3 f1/f2).
        bind_route_policies(app, route_index)
        app.add_middleware(ResponseProfileMiddleware, index=route_index)
        # Directly above it, the pre-routing gate (§5.5 family 13, #204): the
        # principal resolved once, before Starlette routes and FastAPI parses,
        # so an anonymous caller is refused ahead of the router's 404/405 and
        # the parser's 422 — none of which the dependency can reach. It renders
        # through the same envelope handler the dependency's errors take.
        app.add_middleware(
            PreRoutingAuthMiddleware,
            index=route_index,
            table=DispatchTable.from_app(app),
            render=domain_error_handler,
        )

        async def record_ingress_rejection(event_type: str, scope, setting: str) -> None:
            # Lazy import keeps the ingress policy independent of persistence;
            # the service owns the audit transaction (rule 1).
            from app.services.audit import record_ingress_rejection as record

            await record(event_type, scope, policy=policy, setting=setting)

    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_envelope)
    app.add_exception_handler(RequestValidationError, request_validation_handler)

    # Outermost last: the guard answers a hostile Host before anything else
    # runs, and the forwarded-client resolver sees only requests that passed it.
    app.add_middleware(ForwardedClientMiddleware, policy=policy)
    app.add_middleware(
        HostOriginGuardMiddleware,
        policy=policy,
        rejection_recorder=record_ingress_rejection if authorization else None,
    )
    return app


app = create_app(authorization=True)
