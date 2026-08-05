from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import ConflictError, DomainError, InvalidInputError, NotFoundError
from app.mcp import mcp
from app.routers import catalog, inventory, kits, orders, retailers

# REST and MCP share one process and one service layer (§2). The MCP endpoint is
# mounted at /mcp on the same port — a deliberate simplification of §8's
# two-port layout; split later if operating them separately ever matters.
mcp_app = mcp.http_app(path="/")

app = FastAPI(
    title="plamotrack",
    version="0.1.0",
    description="Self-hosted Gunpla/plamo collection & build tracker",
    lifespan=mcp_app.lifespan,  # required for the MCP session manager
)

for router in (kits.router, inventory.router, catalog.router, retailers.router, orders.router):
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
    return {"status": "ok"}
