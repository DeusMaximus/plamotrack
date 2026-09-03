from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app import __version__, error_codes
from app.auth.dependency import (
    ROUTE_INDEX_ATTR,
    ResponseProfileMiddleware,
    bind_route_policies,
    enforce_route_policy,
)
from app.auth.registry import build_route_index
from app.config import Settings, get_settings
from app.db import SessionDep
from app.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    UnauthenticatedError,
)
from app.ingress import (
    ForwardedClientMiddleware,
    HostOriginGuardMiddleware,
    IngressPolicy,
    is_internal_peer,
)
from app.mcp import mcp
from app.routers import catalog, inventory, kits, meta, orders, portability, retailers, settings
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
)

_DOMAIN_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    InvalidInputError: 422,
    UnauthenticatedError: 401,
    ForbiddenError: 403,
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
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.detail, "code": exc.code, "params": jsonable_encoder(exc.params)},
    )


async def http_exception_envelope(request: Request, exc: StarletteHTTPException) -> Response:
    """Parser-stage 400s enter the envelope (#169 review, P2): the framework
    raises `HTTPException(400)` for a body it cannot read — multipart with no
    boundary, a malformed multipart payload — before any schema or service
    runs, so they escaped both handlers above. Every other HTTPException —
    Starlette's own 404/405 for unrouted paths and bad verbs — keeps the stock
    `{"detail": ...}` body by delegating to FastAPI's default handler: unrouted
    paths are deliberately outside the API's machine contract."""
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


def build_mcp_app(policy: IngressPolicy):
    """The FastMCP ASGI child for the `/mcp` mount, guarded with the same lists
    as REST (§5.6, Host spoofing): `host_origin_protection=True` is FastMCP's
    strict mode — Host validated on every request, Origin whenever present —
    and the extras are `IngressPolicy.mcp_allowed_hosts` (the configured names,
    each DNS name dotted as well) / `allowed_origins`, to which the guard adds
    the loopback names itself.

    Slash redirects are off (§5.6, proxy trust): Starlette builds a redirect's
    `Location` from the request's scheme and Host, query string included, which
    behind TLS would bounce an OAuth code to a plain-http URL (M6-7). A
    non-canonical spelling is 404, never 3xx.
    """
    mcp_app = mcp.http_app(
        path="/",
        host_origin_protection=True,
        allowed_hosts=list(policy.mcp_allowed_hosts),
        allowed_origins=list(policy.allowed_origins),
    )
    mcp_app.router.redirect_slashes = False
    return mcp_app


def create_app(config: Settings | None = None, *, authorization: bool = False) -> FastAPI:
    """The application, built from one `Settings`. Module-level `app` below is
    the one uvicorn and the suite import; tests that need a different ingress
    policy build their own through here rather than mutating that one.

    `authorization` installs the app-level default-deny dependency (§5.5,
    M6-2) and builds the route policy registry onto `app.state`. It is off
    on the shipped app until the credential mechanisms exist (#188/#189) —
    the "activate once credentials work" sequencing — and on for the
    authorization matrix, which drives the real route graph through it."""
    config = config or get_settings()
    policy = IngressPolicy.from_settings(config)

    # REST and MCP share one process and one service layer (§2). The MCP
    # endpoint is mounted at /mcp on the same port — a deliberate simplification
    # of §8's two-port layout; split later if operating them separately matters.
    mcp_app = build_mcp_app(policy)

    # Default deny, one dependency for every REST route (§5.5) — not on the
    # auto /openapi.json and /docs, which are add_route handlers an app-level
    # dependency never runs for; those move behind the registry in #188.
    route_dependencies = [Depends(enforce_route_policy)] if authorization else []
    app = FastAPI(
        title="plamotrack",
        version=__version__,
        description="Self-hosted Gunpla/plamo collection & build tracker",
        lifespan=mcp_app.lifespan,  # required for the MCP session manager
        dependencies=route_dependencies,
        # No request-derived redirects (§5.6): `GET /kits/` is 404, not a 307
        # whose Location is built from the request's Host.
        redirect_slashes=False,
    )
    app.state.ingress_policy = policy

    for router in ROUTERS:
        # One envelope for every router's failures (#25) — declared here so a new
        # router cannot forget it.
        app.include_router(router, responses=ERROR_RESPONSES)

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

    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_envelope)
    app.add_exception_handler(RequestValidationError, request_validation_handler)

    # Outermost last: the guard answers a hostile Host before anything else
    # runs, and the forwarded-client resolver sees only requests that passed it.
    app.add_middleware(ForwardedClientMiddleware, policy=policy)
    app.add_middleware(HostOriginGuardMiddleware, policy=policy)
    return app


app = create_app()
