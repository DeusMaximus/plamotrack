"""The two protocol eras on the MCP mount (§7.1; M6.1, #243).

FastMCP 4 / MCP SDK 2 serve the `2026-07-28` revision — no initialize
handshake, no session, `server/discover`, routing headers, `no-store` — and
the handshake era from the one endpoint, deciding the era per request from
`MCP-Protocol-Version`. Every control on the mount was written for the
handshake era; these cases drive each through the modern era as well, and the
in-memory client through both, so a control the modern path bypasses is red
here rather than found by a client.

The modern requests are literal wire fixtures, not the SDK's client: the
`_meta` keys and headers were read from MCP SDK 2.2.0's
`client/session.py::_make_modern_stamp` and `mcp_types/_types.py`, and
corroborated against captured traffic from a real SDK 2 client during the
M6.1 spike (`.agents/spikes/241/`). The refusal contract asserted for a
missing or failed bearer is the mount's own — the RFC 6750 challenge the
handshake-era cases in `tests/test_auth_tokens.py` pin — not REST's envelope.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request

from app.auth.mcp_auth import INJECTED_MCP_PRINCIPAL_ATTR, ToolScopeMiddleware
from app.auth.principal import Scope, pat
from app.auth.registry import PROTOCOL_BODY_LIMIT
from app.auth.resolver import INVALID_TOKEN_CHALLENGE
from app.main import app
from app.mcp import mcp as mcp_server
from tests.oidc_fake import STRANGER_SUB, FakeIdp
from tests.test_auth_tokens import _mcp_call_tool, _mint_direct
from tests.test_mcp_oauth import (
    MCP_OAUTH_ATTR,
    _bind_owner,
    _decode_issued,
    link,
    oauth_app,
)

pytestmark = pytest.mark.anyio
MODERN = "2026-07-28"
#: The handshake-era revisions SDK 2 still negotiates — a literal, so a client
#: that lands on none of them fails here rather than wherever the SDK's list
#: happens to be read from.
LEGACY = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}


def modern_request(method, params=None, *, version=MODERN):
    return {
        "jsonrpc": "2.0",
        "id": 41,
        "method": method,
        "params": {
            **(params or {}),
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientInfo": {"name": "test_mcp_eras", "version": "1"},
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }


def modern_headers(method, *, token=None, name=None, version=MODERN):
    headers = {
        "Host": "localhost",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def rpc(response):
    """The JSON-RPC document for request 41 — a JSON reply as is, an SSE reply
    by its `data:` lines."""
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    messages = [
        json.loads(line[5:].strip())
        for line in response.text.splitlines()
        if line.startswith("data:")
    ]
    return next((m for m in messages if m.get("id") == 41), {})


# --- in memory: the tool middleware in both eras -----------------------------------------


@pytest.mark.parametrize("era", ["auto", "legacy"])
async def test_in_memory_both_eras_list_call_and_scope_refusal(era, monkeypatch):
    """`ToolScopeMiddleware.on_call_tool` runs once per call in each era, before
    the tool's arguments are parsed (the refusal names the scope, not the
    missing argument), and the in-memory transport carries no HTTP request in
    either era — so the injected principal is what decides. The default client
    negotiates the modern era; `mode="legacy"` the handshake era."""
    monkeypatch.setattr(mcp_server, INJECTED_MCP_PRINCIPAL_ATTR, pat(write=False))
    calls = []
    original = ToolScopeMiddleware.on_call_tool

    async def observed(self, context, call_next):
        with pytest.raises(RuntimeError):
            get_http_request()
        calls.append(context.message.name)
        return await original(self, context, call_next)

    monkeypatch.setattr(ToolScopeMiddleware, "on_call_tool", observed)
    async with Client(mcp_server, mode=era) as client:
        assert "list_retailers" in {t.name for t in await client.list_tools()}
        await client.call_tool("list_retailers", {})
        with pytest.raises(ToolError, match="collection:write"):
            await client.call_tool("create_retailer", {})  # required argument absent
        assert calls == ["list_retailers", "create_retailer"]
        if era == "auto":
            assert client.protocol_version == MODERN
        else:
            assert client.protocol_version in LEGACY


# --- over HTTP: the modern era against every control on the mount -----------------------


@pytest.mark.parametrize("method", ["tools/list", "server/discover"])
async def test_modern_pat_request_needs_no_initialize(http_client, method):
    """A personal access token opens no session: a modern request is answered
    on its own, with no `mcp-session-id` and the mount's `no-store`."""
    async with app.router.lifespan_context(app):
        token, _ = await _mint_direct(scopes=(Scope.READ,))
        response = await http_client.post(
            "/mcp/", json=modern_request(method), headers=modern_headers(method, token=token)
        )
        assert response.status_code == 200, response.text
        body = rpc(response)
        assert "result" in body, body
        assert "mcp-session-id" not in response.headers
        assert response.headers["cache-control"] == "no-store"
        if method == "tools/list":
            assert "list_retailers" in {t["name"] for t in body["result"]["tools"]}
        else:
            assert MODERN in body["result"]["supportedVersions"]


@pytest.mark.parametrize("method", ["tools/list", "server/discover"])
@pytest.mark.parametrize("credential", ["absent", "failed"])
async def test_modern_auth_refusal_is_the_mounts_challenge(http_client, method, credential):
    """The mount's refusal contract, in the modern era as in the handshake era
    (`test_mcp_takes_a_bearer_and_never_a_cookie`,
    `test_mcp_refuses_a_failed_bearer_the_same_way`): an absent credential
    earns the bare RFC 6750 challenge and an empty body (FastMCP's
    `RequireAuthMiddleware._send_missing_auth`), a presented-and-failed one
    `error="invalid_token"` with the SDK's JSON body (`_send_auth_error`) —
    never REST's `auth.bearer_invalid` envelope, which the mount does not
    speak — with `no-store` and no session either way; each pair is
    byte-identical across the eras (Codex #246 round 1). The bare `Bearer` is
    local mode's, the shipped `app` here — OIDC mode's challenge adds
    `resource_metadata`. `server/discover` is protected too: discovery of the
    *protocol* is not the anonymous family."""
    async with app.router.lifespan_context(app):
        headers = modern_headers(
            method, token="not-a-valid-bearer" if credential == "failed" else None
        )
        response = await http_client.post("/mcp/", json=modern_request(method), headers=headers)
        assert response.status_code == 401, response.text
        assert "mcp-session-id" not in response.headers
        assert response.headers["cache-control"] == "no-store"
        challenge = response.headers["www-authenticate"]
        if credential == "absent":
            assert challenge == "Bearer"
        else:
            assert challenge.startswith(INVALID_TOKEN_CHALLENGE), challenge
            assert response.json()["error"] == "invalid_token"
        assert b"auth.bearer_invalid" not in response.content


async def test_modern_undeclared_verb_is_the_route_binding_405(http_client):
    """The registry's verb boundary (`RouteBinding`) is in front of the
    transport whatever era the headers name: the SDK's own 405 document, the
    declared `Allow`, `no-store`, no session."""
    async with app.router.lifespan_context(app):
        response = await http_client.patch("/mcp/", headers=modern_headers("tools/list"))
        assert response.status_code == 405, response.text
        assert response.headers["allow"] == "GET, POST, DELETE"
        assert response.json() == {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Method Not Allowed"},
        }
        assert "mcp-session-id" not in response.headers
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("era", ["modern", "legacy"])
async def test_http_scope_hook_once_before_tool_arguments(era, http_client, monkeypatch):
    """Over HTTP the hook sees the request (`get_http_request`) in both eras,
    runs once per call, and refuses a read token's write before the missing
    argument is noticed. The lifespan is entered in the test task: a live
    legacy session owns a task group that must not cross a fixture's yield."""
    token, _ = await _mint_direct(scopes=(Scope.READ,))
    calls = []
    original = ToolScopeMiddleware.on_call_tool

    async def observed(self, context, call_next):
        assert get_http_request().url.path.endswith("/mcp/")
        calls.append(context.message.name)
        return await original(self, context, call_next)

    monkeypatch.setattr(ToolScopeMiddleware, "on_call_tool", observed)
    async with app.router.lifespan_context(app):
        if era == "modern":
            response = await http_client.post(
                "/mcp/",
                json=modern_request("tools/call", {"name": "create_retailer", "arguments": {}}),
                headers=modern_headers("tools/call", token=token, name="create_retailer"),
            )
            assert response.status_code == 200, response.text
            body = rpc(response)
            assert "result" in body, body
            result = body["result"]
            assert "mcp-session-id" not in response.headers
        else:
            result = await _mcp_call_tool(
                http_client,
                {"Host": "localhost", "Authorization": f"Bearer {token}"},
                "create_retailer",
                {},
            )
    assert result["isError"] is True, result
    assert "collection:write" in json.dumps(result), result
    assert calls == ["create_retailer"]


@pytest.mark.parametrize("routing_headers", [True, False])
async def test_routing_headers_never_grant_authority(http_client, routing_headers):
    """`Mcp-Method` and `Mcp-Name` route; they decide nothing about who may
    call. With them, an absent or failed bearer is still 401 and a read token
    still cannot write. Without them, the SDK refuses the request as malformed
    before dispatch (a protocol error, not a different permission) — and the
    credential is still judged first: 401 before the protocol refusal."""
    async with app.router.lifespan_context(app):
        token, _ = await _mint_direct(scopes=(Scope.READ,))
        body = modern_request("tools/call", {"name": "create_retailer", "arguments": {}})
        for credential in [None, "not-a-valid-bearer", token]:
            headers = modern_headers("tools/call", token=credential, name="create_retailer")
            if not routing_headers:
                headers.pop("Mcp-Method")
                headers.pop("Mcp-Name")
            response = await http_client.post("/mcp/", json=body, headers=headers)
            assert "mcp-session-id" not in response.headers
            if credential != token:
                assert response.status_code == 401, response.text
            elif routing_headers:
                assert response.status_code == 200, response.text
                result = rpc(response)
                assert result.get("result", {}).get("isError") is True, result
                assert "collection:write" in json.dumps(result), result
            else:
                assert response.status_code == 400, response.text
                refusal = rpc(response)["error"]
                assert refusal["code"] == -32020, refusal  # the SDK's routing-header mismatch
                assert "mcp-method" in refusal["message"].lower(), refusal


async def test_modern_registration_keeps_the_body_budget():
    """The anonymous body budget (#221 item 1) is the pre-routing gate's,
    decided before any transport reads the era headers."""
    async with oauth_app(FakeIdp()) as (_, client):
        response = await client.post(
            "/mcp/register",
            content=b"{}" + b" " * PROTOCOL_BODY_LIMIT,
            headers={**modern_headers("tools/list"), "Content-Type": "application/json"},
        )
        assert response.status_code == 413, response.text
        assert response.json()["code"] == "ingress.body_too_large"
        assert response.headers["cache-control"] == "no-store"


async def test_modern_oauth_token_keeps_the_per_request_owner_binding():
    """A proxy-issued token is compared with the owner row on every request
    (§5.5 family 8) — in the modern era there is no session to have checked
    it at, so the per-request comparison is the whole control: the bound owner
    is 200, and after a rebind the same token is 401 on the next request.
    The issuer the token names is the mount's, unchanged by the bump."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        outcome = await link(client, fake)
        assert outcome["status"] == 200, outcome["body"]
        token = outcome["body"]["access_token"]
        proxy = getattr(live.state, MCP_OAUTH_ATTR).proxy
        assert (
            _decode_issued(token)["iss"]
            == str(proxy.issuer_url)
            == str(proxy.base_url)
            == "http://localhost/mcp"
        )
        for rebound, expected in [(False, 200), (True, 401)]:
            if rebound:
                await _bind_owner(STRANGER_SUB)
            response = await client.post(
                "/mcp/",
                json=modern_request("tools/list"),
                headers=modern_headers("tools/list", token=token),
            )
            assert response.status_code == expected, response.text
            assert "mcp-session-id" not in response.headers
            if not rebound:
                assert "result" in rpc(response), response.text


async def test_unknown_only_protocol_reports_supported_versions(http_client):
    """A revision the server does not serve is refused with the list it does
    (the SDK's -32022), with no session — after the credential was judged."""
    async with app.router.lifespan_context(app):
        token, _ = await _mint_direct(scopes=(Scope.READ,))
        response = await http_client.post(
            "/mcp/",
            json=modern_request("server/discover", version="2099-01-01"),
            headers=modern_headers("server/discover", token=token, version="2099-01-01"),
        )
        body = rpc(response)
        assert response.status_code == 400, response.text
        assert body["error"]["code"] == -32022, body
        assert MODERN in body["error"]["data"]["supported"], body
        assert "mcp-session-id" not in response.headers
        unauthenticated = await http_client.post(
            "/mcp/",
            json=modern_request("server/discover", version="2099-01-01"),
            headers=modern_headers("server/discover", version="2099-01-01"),
        )
        assert unauthenticated.status_code == 401, unauthenticated.text
