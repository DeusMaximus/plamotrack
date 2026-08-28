from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app import __version__, error_codes
from app.db import SessionDep
from app.exceptions import ConflictError, DomainError, InvalidInputError, NotFoundError
from app.mcp import mcp
from app.routers import catalog, inventory, kits, meta, orders, portability, retailers, settings
from app.schemas.errors import ERROR_RESPONSES

# REST and MCP share one process and one service layer (§2). The MCP endpoint is
# mounted at /mcp on the same port — a deliberate simplification of §8's
# two-port layout; split later if operating them separately ever matters.
mcp_app = mcp.http_app(path="/")

app = FastAPI(
    title="plamotrack",
    version=__version__,
    description="Self-hosted Gunpla/plamo collection & build tracker",
    lifespan=mcp_app.lifespan,  # required for the MCP session manager
)

for router in (
    kits.router,
    inventory.router,
    catalog.router,
    retailers.router,
    orders.router,
    portability.router,
    meta.router,
    settings.router,
):
    # One envelope for every router's failures (#25) — declared here so a new
    # router cannot forget it.
    app.include_router(router, responses=ERROR_RESPONSES)

app.mount("/mcp", mcp_app)

_DOMAIN_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    InvalidInputError: 422,
}


@app.exception_handler(DomainError)
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


@app.exception_handler(StarletteHTTPException)
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


@app.exception_handler(RequestValidationError)
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


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict:
    """Liveness: the process is up and serving. Deliberately touches nothing else."""
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
async def readyz(session: SessionDep) -> dict:
    """Readiness: the API can actually reach Postgres.

    This is what the container healthcheck watches. /healthz answers happily
    while the database is unreachable, which would let compose report a stack
    healthy that cannot serve a single request.
    """
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
