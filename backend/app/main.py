from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.db import SessionDep
from app.exceptions import ConflictError, DomainError, InvalidInputError, NotFoundError
from app.mcp import mcp
from app.routers import catalog, inventory, kits, meta, orders, portability, retailers

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
):
    app.include_router(router)

app.mount("/mcp", mcp_app)

_DOMAIN_STATUS: dict[type[DomainError], int] = {
    NotFoundError: 404,
    ConflictError: 409,
    InvalidInputError: 422,
}


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    for cls, status_code in _DOMAIN_STATUS.items():
        if isinstance(exc, cls):
            return JSONResponse(status_code=status_code, content={"detail": str(exc)})
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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
