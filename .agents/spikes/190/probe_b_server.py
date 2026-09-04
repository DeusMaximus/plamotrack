"""#190 spike, phase B — a probe MCP server behind FastMCP's OIDCProxy.

Mounted like app/main.py mounts the child (create_streamable_http_app at
"/", redirect_slashes off, /.well-known/* pruned from the child, the three
root documents installed on the parent). Every request is logged to
access.log with method, path, status, Origin and User-Agent so the discovery
URLs each client actually requests can be read back per client.

Env:
  SPIKE_OIDC_CONFIG_URL   e.g. http://localhost:8081/realms/plamotrack/.well-known/openid-configuration
  SPIKE_CLIENT_ID / SPIKE_CLIENT_SECRET
  SPIKE_BASE_URL          default http://127.0.0.1:8000
  SPIKE_STORE_DIR         FileTreeStore directory (persisted across restarts)
  SPIKE_JWT_KEY_HEX       32-byte hex signing key (explicit, not derived)
  SPIKE_BARE_OPENID=1     also install the bare /.well-known/openid-configuration
  SPIKE_REQUIRED_SCOPES   space-separated, default "openid"
  SPIKE_VERIFY_ID_TOKEN=1 verify the upstream id_token (JWKS) instead of the access token
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet
from fastmcp import FastMCP
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.http import create_streamable_http_app
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Mount, Route

HERE = Path(__file__).parent
BASE = os.environ.get("SPIKE_BASE_URL", "http://127.0.0.1:8000")
STORE_DIR = Path(os.environ.get("SPIKE_STORE_DIR", HERE / "store"))
LOG = HERE / "access.log"

jwt_key = bytes.fromhex(os.environ["SPIKE_JWT_KEY_HEX"])
STORE_DIR.mkdir(parents=True, exist_ok=True)
enc_key = derive_jwt_key(high_entropy_material=jwt_key.decode("latin-1"), salt="spike-storage")
file_store = FileTreeStore(
    data_directory=STORE_DIR,
    key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(STORE_DIR),
    collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(STORE_DIR),
)
if os.environ.get("SPIKE_PG_URL"):
    from key_value.aio.stores.postgresql import PostgreSQLStore
    inner_store = PostgreSQLStore(url=os.environ["SPIKE_PG_URL"], table_name="mcp_oauth_state")
else:
    inner_store = file_store
storage = FernetEncryptionWrapper(key_value=inner_store, fernet=Fernet(key=enc_key), raise_on_decryption_error=False)

from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier
import httpx as _httpx


class OwnerBoundVerifier(TokenVerifier):
    """The thin owner constraint: the upstream (issuer, subject) must equal the
    bound owner; anything else is refused as if the token were invalid."""

    def __init__(self, inner: TokenVerifier, issuer: str, subject: str):
        super().__init__(required_scopes=["openid"])  # advertised + default; the inner id_token verifier checks none
        self.inner, self.issuer, self.subject = inner, issuer, subject

    async def verify_token(self, token: str):
        tok = await self.inner.verify_token(token)
        if tok is None:
            return None
        if (tok.claims.get("iss"), tok.claims.get("sub")) != (self.issuer, self.subject):
            print(json.dumps({"owner_refused": {"iss": tok.claims.get("iss"), "sub": tok.claims.get("sub"), "email": tok.claims.get("email")}}), flush=True)
            return None
        return tok


verifier = None
if os.environ.get("SPIKE_OWNER_SUB"):
    disc = _httpx.get(os.environ["SPIKE_OIDC_CONFIG_URL"]).json()
    verifier = OwnerBoundVerifier(
        JWTVerifier(jwks_uri=disc["jwks_uri"], issuer=disc["issuer"], audience=os.environ["SPIKE_CLIENT_ID"]),
        issuer=disc["issuer"], subject=os.environ["SPIKE_OWNER_SUB"],
    )

from mcp.server.auth.provider import TokenError


class OwnerProxy(OIDCProxy):
    """Owner binding at issuance (#192): the upstream identity behind an
    authorization code must verify as the owner before any token is minted.
    The verifier's per-request check stays as defence in depth."""

    async def exchange_authorization_code(self, client, authorization_code):
        code_model = await self._code_store.get(key=authorization_code.code)
        if code_model is not None:
            idp = code_model.idp_tokens
            upstream = idp.get("id_token") if os.environ.get("SPIKE_VERIFY_ID_TOKEN") == "1" else idp.get("access_token")
            if upstream is None or await self._token_validator.verify_token(upstream) is None:
                await self._code_store.delete(key=authorization_code.code)
                print(json.dumps({"owner_refused_at_issuance": authorization_code.client_id}), flush=True)
                raise TokenError("invalid_grant", "The signed-in identity is not this instance's owner")
        return await super().exchange_authorization_code(client, authorization_code)


class LoggingProxy(OIDCProxy):
    """Record the shape of the upstream token response (keys and expiry only)."""

    async def exchange_authorization_code(self, client, authorization_code):
        code_model = await self._code_store.get(key=authorization_code.code)
        if code_model is not None:
            idp = code_model.idp_tokens
            print(json.dumps({"idp_token_response": {"keys": sorted(idp), "expires_in": idp.get("expires_in"), "scope": idp.get("scope"), "has_refresh": bool(idp.get("refresh_token"))}}), flush=True)
        return await super().exchange_authorization_code(client, authorization_code)


ProxyClass = OwnerProxy if os.environ.get("SPIKE_OWNER_AT_ISSUANCE") == "1" else LoggingProxy
proxy = ProxyClass(
    config_url=os.environ["SPIKE_OIDC_CONFIG_URL"],
    client_id=os.environ["SPIKE_CLIENT_ID"],
    client_secret=os.environ.get("SPIKE_CLIENT_SECRET") or None,
    base_url=f"{BASE}/mcp",
    token_verifier=verifier,
    required_scopes=None if verifier else os.environ.get("SPIKE_REQUIRED_SCOPES", "openid").split(),
    jwt_signing_key=jwt_key,
    client_storage=storage,
    require_authorization_consent=True,
    verify_id_token=os.environ.get("SPIKE_VERIFY_ID_TOKEN") == "1",
    extra_authorize_params=dict(x.split("=", 1) for x in os.environ.get("SPIKE_EXTRA_AUTHORIZE", "").split("&") if x) or None,
)

mcp = FastMCP("plamotrack-spike")


@mcp.tool
def whoami() -> dict:
    """Return the verified token's claims as the server sees them."""
    tok = get_access_token()
    return {"client_id": tok.client_id, "scopes": tok.scopes, "claims": tok.claims}


child = create_streamable_http_app(server=mcp, streamable_http_path="/", auth=proxy, json_response=True, stateless_http=False)
child.router.redirect_slashes = False
child.router.routes[:] = [r for r in child.router.routes if not (isinstance(r, Route) and r.path.startswith("/.well-known/"))]
well_known = [
    r
    for r in proxy.get_well_known_routes("/")
    if os.environ.get("SPIKE_BARE_OPENID") == "1" or r.path != "/.well-known/openid-configuration"
]


class AccessLog(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        t = time.time()
        resp = await call_next(request)
        rec = {
            "t": round(t, 3),
            "m": request.method,
            "p": request.url.path,
            "q": sorted(request.query_params.keys()),
            "s": resp.status_code,
            "origin": request.headers.get("origin"),
            "ua": (request.headers.get("user-agent") or "")[:80],
            "host": request.headers.get("host"),
            "auth": (request.headers.get("authorization") or "")[:6],
            "loc": (resp.headers.get("location") or "")[:60],
            "cc": resp.headers.get("cache-control"),
        }
        with LOG.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        return resp


parent = Starlette(routes=[*well_known, Mount("/mcp", app=child)], lifespan=child.router.lifespan_context)
parent.router.redirect_slashes = False
parent.add_middleware(AccessLog)

print(json.dumps({
    "issuer": str(proxy.issuer_url),
    "upstream_authorize": proxy._upstream_authorization_endpoint,
    "upstream_token": proxy._upstream_token_endpoint,
    "upstream_revocation": proxy._upstream_revocation_endpoint,
    "parent_routes": [r.path for r in well_known],
    "child_routes": [(r.path, sorted(r.methods or [])) for r in child.router.routes if isinstance(r, Route)],
    "store": type(inner_store).__name__ + (" " + str(STORE_DIR) if not os.environ.get("SPIKE_PG_URL") else " table=mcp_oauth_state"),
}, indent=1), flush=True)

if __name__ == "__main__":
    uvicorn.run(parent, host=os.environ.get("SPIKE_BIND", "127.0.0.1"), port=int(os.environ.get("SPIKE_PORT", "8000")), proxy_headers=False, access_log=False, log_level="info")
