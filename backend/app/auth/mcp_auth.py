"""Bearer authentication and per-tool scope on the MCP mount (§5.5 family 7,
§5.6 scope escalation; M6-4, #189).

Two pieces, both reading what the REST side reads:

- **`PersonalAccessTokenVerifier`** — the FastMCP `TokenVerifier` the mount is
  built with when authorization is on. FastMCP's own bearer middleware parses
  the `Authorization` header (and nothing else — the transport never sees a
  cookie, §5.5 family 7), hands the token here, and its `RequireAuthMiddleware`
  answers `401` with `WWW-Authenticate: Bearer` for a request that resolves to
  nothing. `verify_token` opens a session of its own (there is no request
  transaction on this path) and calls `services/tokens.resolve_bearer` — the same
  helper the REST resolver calls — so a token is valid on both surfaces or on
  neither. The returned `AccessToken` carries the token's **public id**, never
  the raw value, in its `token` field: the SDK keeps the object on the request
  scope for the connection's life, and an accidental repr should leak nothing.
- **`ToolScopeMiddleware`** — a FastMCP middleware on `tools/call` that decides
  the principal for the call and refuses a tool whose declared scope
  (`registry.MCP_TOOL_SCOPES`) the principal does not hold. One place for every
  tool, reading the registry (rule 9's shape), so a write tool cannot be more
  permissive than its REST twin and a new tool lands with a scope or fails the
  enumeration test. The principal comes from, in order: the access token the
  HTTP layer verified; failing that, if an HTTP request is in flight, **refusal**
  (fail closed — behind the verifier this cannot happen, and under the pre-auth
  app there is no credential to honour); failing that — the in-memory transport
  the tests use, which carries no HTTP request — the injected principal the
  pytest harness sets on the server (`INJECTED_MCP_PRINCIPAL_ATTR`), the
  `app.state` seam's twin; and with none of those, refusal.

The refusal is a `ToolError` naming the tool and the scope, so an agent reads
why rather than a generic failure (T6: "on every write tool → tool error").
"""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types as mt

from app.auth.principal import VIA_BEARER, Principal, PrincipalKind, Scope, pat
from app.auth.registry import MCP_TOOL_SCOPES
from app.db import session_scope
from app.ingress import current_client_address

#: The attribute on the FastMCP server object the pytest harness sets to force a
#: principal for in-memory tool calls — the twin of `resolver.INJECTED_PRINCIPAL_ATTR`.
#: Read only when no HTTP request is in flight, so it can never stand in for a
#: missing bearer on the wire.
INJECTED_MCP_PRINCIPAL_ATTR = "authorization_injected_principal"

_UNAUTHENTICATED = "Authentication required: present a personal access token as a bearer."


class PersonalAccessTokenVerifier(TokenVerifier):
    """FastMCP's verifier hook, over `services/tokens.resolve_bearer`. No
    `base_url`: in local mode there is no authorization server and no protected-
    resource document to point at, so the SDK's challenge carries no
    `resource_metadata` — a pointer at a 404 would be worse than none (M6-7
    adds the document and the pointer with it)."""

    def __init__(self) -> None:
        super().__init__(base_url=None, required_scopes=[])

    async def verify_token(self, token: str) -> AccessToken | None:
        from app.services import tokens as token_service

        async with session_scope() as session:
            resolution = await token_service.resolve_bearer(
                session,
                token,
                request=None,
                client_address=current_client_address(),
            )
            if not resolution.ok:
                # The use-after-revoke audit row (if any) commits with the scope.
                return None
            row = resolution.row
            assert row is not None
            principal = resolution.principal
            return AccessToken(
                token=row.token_prefix,
                client_id=str(row.id),
                scopes=[scope.value for scope in Scope if scope in principal.scopes],
                expires_at=int(row.expires_at.timestamp()) if row.expires_at else None,
                claims={"kind": principal.kind.value},
            )


def principal_from_access_token(token: AccessToken) -> Principal:
    """The `Principal` an SDK access token stands for. Today every token the
    verifier issues is a PAT; the MCP OAuth grant (#192) will carry its own
    `claims["kind"]` and map to `mcp(...)` here."""
    scopes = frozenset(Scope(s) for s in token.scopes)
    if token.claims.get("kind") == PrincipalKind.PAT.value:
        return pat(write=Scope.WRITE in scopes, subject=token.client_id, via=VIA_BEARER)
    raise ToolError(_UNAUTHENTICATED)


def _http_request_in_flight() -> bool:
    try:
        get_http_request()
    except RuntimeError:
        return False
    return True


class ToolScopeMiddleware(Middleware):
    """Per-tool scope enforcement from the registry's tool map (see the module
    docstring for the principal order)."""

    def __init__(self, server) -> None:
        self.server = server

    def principal_for_call(self) -> Principal:
        token = get_access_token()
        if token is not None:
            return principal_from_access_token(token)
        if _http_request_in_flight():
            raise ToolError(_UNAUTHENTICATED)
        injected = getattr(self.server, INJECTED_MCP_PRINCIPAL_ATTR, None)
        if injected is None:
            raise ToolError(_UNAUTHENTICATED)
        return injected

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, object],
    ):
        name = context.message.name
        principal = self.principal_for_call()
        required = MCP_TOOL_SCOPES.get(name)
        if required is None:
            # Undeclared: the enumeration test refuses this at build; fail closed
            # here as well rather than guess a scope for it.
            raise ToolError(f"tool {name!r} has no declared scope and cannot be called")
        if not principal.has_scope(required):
            raise ToolError(
                f"{required.value} is required to call {name}; this credential holds "
                + (
                    ", ".join(s.value for s in Scope if s in principal.scopes)
                    if principal.scopes
                    else "no collection scope"
                )
            )
        return await call_next(context)
