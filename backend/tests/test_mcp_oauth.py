"""MCP OAuth — FastMCP's proxy in front of the OpenID Connect provider (§5.5
family 8; §5.6 proxy trust, open redirect, credential leakage, safe failure;
§5.8 T2/T5/T6/T9/T10/T12/T13; M6-7, #192).

An OIDC-mode app with its lifespan entered — the FastMCP session manager and
the state store's pool live there — is driven as the three parties the protocol
has: the **MCP client** (registration, the authorization request, the token
exchange, the transport with the issued bearer), the **owner's browser** (the
consent page, the provider's return), and the **provider** itself — the fake in
`tests/oidc_fake.py`, wired into both the app's `OidcProvider` and the proxy's
upstream client through `PlamotrackOAuthProxy.upstream_transport`, so the code
exchange, the refresh and the id_token are all real bytes through real handlers
and only the network is played. The shipped local-mode `app` is driven where the
point is that the same paths exist there and answer 404 themselves.

Axes (AGENTS.md, "sweep the values"): the **client kind** — a dynamically
registered client, one under an operator allowlist, the synthesised upstream-id
client, a CIMD client — each with its own redirect-URI binding (T9); the
**identity** behind the upstream code — the bound owner, a stranger, an unbound
instance (T6); the **mode** — the same nine paths in OIDC and local mode (T2's
app half); the **store and key** across a process restart (T13); and the
response profile on every transaction and credential response, failures
included, with discovery asserted to be the public exception (T10).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.cimd import CIMDDocument, CIMDFetcher
from httpx import ASGITransport, AsyncClient
from joserfc import jwk, jwt
from sqlalchemy import select, text
from starlette.routing import Mount

from app import error_codes
from app.auth.mcp_auth import principal_from_access_token
from app.auth.mcp_oauth import (
    ACCESS_TOKEN_LIFETIME,
    GRANT_LOCK_NAMESPACE,
    MCP_OAUTH_ATTR,
    UPSTREAM_AUTHORIZE_PARAMS,
    OwnerVerdict,
    _lock_key,
    storage_key,
)
from app.auth.mode import OIDC_PROVIDER_ATTR
from app.auth.principal import Scope
from app.auth.registry import DISCOVERY_ROUTES, MCP_OAUTH_ROUTES
from app.auth.resolver import INVALID_TOKEN_CHALLENGE
from app.config import Settings
from app.db import get_sessionmaker
from app.main import create_app
from app.models import AuditEvent
from app.services import audit
from app.services import auth as auth_service
from app.services import oidc as oidc_module
from app.services import tokens as token_service
from app.services.oidc import OidcProvider
from tests.oidc_fake import (
    BASE,
    CLIENT_ID,
    CLIENT_SECRET,
    ISSUER,
    OTHER_SIGNING_KEY_HEX,
    OWNER_SUB,
    SIGNING_KEY_HEX,
    STRANGER_SUB,
    FakeIdp,
    oidc_settings,
)

pytestmark = pytest.mark.anyio

LOOPBACK = ("127.0.0.1", 12345)
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test_mcp_oauth", "version": "0"},
    },
}
ISSUER_URL = f"{BASE}/mcp"
RESOURCE_URL = f"{BASE}/mcp/"
CALLBACK = f"{BASE}/mcp/auth/callback"
PRM_URL = f"{BASE}/.well-known/oauth-protected-resource/mcp/"
DISCOVERY_PATHS = sorted(DISCOVERY_ROUTES)
CHILD_PATHS = sorted(MCP_OAUTH_ROUTES)
NATIVE_CB = "http://localhost:3000/cb"
CIMD_ID = "https://client.example/oauth/client.json"
CIMD_CB = "https://client.example/oauth/callback"
_METHOD_UNIVERSE = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE")
#: The verbs each protocol route accepts — a literal, not a reading of the
#: registry (a declaration widened by mistake would otherwise widen this test's
#: expectation with it; the moa-25 mutant found exactly that).
_DECLARED_VERBS: dict[str, set[str]] = {
    "/mcp/register": {"POST", "OPTIONS"},
    "/mcp/authorize": {"GET", "POST"},
    "/mcp/consent": {"GET", "POST"},
    "/mcp/auth/callback": {"GET"},
    "/mcp/token": {"POST", "OPTIONS"},
    "/mcp/revoke": {"POST", "OPTIONS"},
}
_NO_LOCATION = "a family-8 refusal carries no Location (§5.6, proxy trust)"


# --- the harness -------------------------------------------------------------------


@asynccontextmanager
async def oauth_app(fake: FakeIdp, **overrides):
    """An enforced OIDC-mode app, lifespan entered, whose provider *and* whose
    proxy's upstream client both talk to `fake`; one client on it from a
    loopback peer, its cookie jar standing for the owner's browser."""
    settings = oidc_settings(**overrides)
    live = create_app(settings, authorization=True)
    transport = httpx.MockTransport(fake.handler)
    provider = OidcProvider.from_settings(settings, http_client=AsyncClient(transport=transport))
    assert provider is not None
    setattr(live.state, OIDC_PROVIDER_ATTR, provider)
    oauth = getattr(live.state, MCP_OAUTH_ATTR)
    oauth.proxy.upstream_transport = httpx.MockTransport(fake.handler)
    async with live.router.lifespan_context(live):
        async with AsyncClient(
            transport=ASGITransport(app=live, client=LOOPBACK, raise_app_exceptions=False),
            base_url=BASE,
        ) as client:
            yield live, client


async def _bind_owner(sub: str = OWNER_SUB) -> None:
    """The owner as the browser login leaves it: claimed and bound (#191)."""
    async with get_sessionmaker()() as session:
        owner = await auth_service.owner_row(session, for_update=True)
        owner.claimed_at = datetime.now(UTC)
        owner.oidc_issuer = ISSUER
        owner.oidc_subject = sub
        await session.commit()


async def _events(event_type: str) -> list[AuditEvent]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(select(AuditEvent).where(AuditEvent.event_type == event_type))
        return list(rows.scalars())


async def _state_rows() -> list[tuple[str, dict]]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(text("SELECT collection, value FROM mcp_oauth_state"))
        return [(row[0], row[1]) for row in rows]


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


async def register(client, redirect_uris=(NATIVE_CB,), **extra) -> httpx.Response:
    body = {
        "redirect_uris": list(redirect_uris),
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": "test client",
        **extra,
    }
    return await client.post("/mcp/register", json=body)


async def authorize(
    client, client_id: str, redirect_uri: str | None = NATIVE_CB, *, challenge: str, **extra
) -> httpx.Response:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "client-state",
        "scope": "openid",
        **extra,
    }
    if redirect_uri is not None:
        params["redirect_uri"] = redirect_uri
    return await client.get("/mcp/authorize", params=params)


async def consent(client, consent_location: str, *, action: str = "approve") -> httpx.Response:
    """The owner's browser at the consent page: GET it (the state cookie), then
    submit the form with its CSRF token."""
    assert consent_location.startswith(f"{BASE}/mcp/consent?txn_id="), consent_location
    page = await client.get(consent_location)
    assert page.status_code == 200, page.text[:300]
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match, page.text[:300]
    txn_id = _query(consent_location)["txn_id"]
    return await client.post(
        "/mcp/consent",
        data={"txn_id": txn_id, "csrf_token": match.group(1), "action": action},
        headers={"Origin": BASE},
    )


def _provider_tokens(
    fake: FakeIdp, *, sub: str = OWNER_SUB, expires_in: int = 300, **claims
) -> dict:
    """The provider's token response for a code: `expires_in` is the upstream
    access token's lifetime (what bounds a grant); everything else is an
    id_token claim knob."""
    id_token = fake.issue(sub=sub, nonce=None, omit=("nonce",), **claims)
    return {
        "id_token": id_token,
        "access_token": "upstream-access-" + secrets.token_hex(8),
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": "upstream-refresh-" + secrets.token_hex(8),
    }


async def idp_return(client, fake: FakeIdp, upstream_location: str, **token_kw) -> httpx.Response:
    """The provider sends the browser back: what the fake will hand the proxy
    for `GOOD_CODE`, then the callback with the transaction as `state`."""
    params = _query(upstream_location)
    fake.next_token = _provider_tokens(fake, **token_kw)
    fake.refresh_tokens.add(fake.next_token["refresh_token"])
    return await client.get(
        "/mcp/auth/callback", params={"code": FakeIdp.GOOD_CODE, "state": params["state"]}
    )


async def exchange(client, client_id: str, code: str, verifier: str, redirect_uri=NATIVE_CB):
    return await client.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )


async def link(client, fake: FakeIdp, *, sub: str = OWNER_SUB, **token_kw) -> dict:
    """The whole round trip for one native client; returns a dict with the
    client id and the token response (status + body)."""
    registered = await register(client)
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    verifier, challenge = _pkce()
    started = await authorize(client, client_id, challenge=challenge)
    assert started.status_code == 302, started.text
    approved = await consent(client, started.headers["location"])
    assert approved.status_code == 302, approved.text
    returned = await idp_return(client, fake, approved.headers["location"], sub=sub, **token_kw)
    assert returned.status_code == 302, returned.text
    back = _query(returned.headers["location"])
    assert returned.headers["location"].startswith(NATIVE_CB + "?")
    assert back["state"] == "client-state"
    response = await exchange(client, client_id, back["code"], verifier)
    return {
        "client_id": client_id,
        "code": back["code"],
        "verifier": verifier,
        "status": response.status_code,
        "body": response.json(),
        "response": response,
    }


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _sse_json(body: str) -> list[dict]:
    return [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")]


async def mcp_call(client, headers, name: str, arguments: dict) -> dict:
    init = await client.post("/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **headers})
    assert init.status_code == 200, init.text
    common = {**MCP_HEADERS, **headers, "mcp-session-id": init.headers["mcp-session-id"]}
    ack = await client.post(
        "/mcp/", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=common
    )
    assert ack.status_code == 202, ack.text
    call = await client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        headers=common,
    )
    assert call.status_code == 200, call.text
    messages = [m for m in _sse_json(call.text) if m.get("id") == 2]
    assert messages, call.text
    return messages[-1]["result"]


def _decode_issued(token: str, key_hex: str = SIGNING_KEY_HEX) -> dict:
    key = jwk.import_key(bytes.fromhex(key_hex), "oct")
    return dict(jwt.decode(token, key, algorithms=["HS256"]).claims)


# --- discovery (T2, the app half) ----------------------------------------------------


async def test_the_three_root_documents_name_this_instance_and_nothing_else_answers():
    """OIDC mode: the authorization-server document and its OpenID alias name
    `<PUBLIC_BASE_URL>/mcp` as issuer with every endpoint under it; the
    protected-resource document names `…/mcp/` and points back; all three are
    public and cacheable; the bare OpenID document and the child's aliases are
    pruned (§5.5 family 8)."""
    async with oauth_app(FakeIdp()) as (_, client):
        for path in (
            "/.well-known/oauth-authorization-server/mcp",
            "/.well-known/openid-configuration/mcp",
        ):
            resp = await client.get(path)
            assert resp.status_code == 200, (path, resp.text)
            assert resp.headers.get_list("cache-control") == ["public, max-age=3600"], path
            document = resp.json()
            assert document["issuer"] == ISSUER_URL
            for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
                assert document[key].startswith(ISSUER_URL + "/"), (key, document[key])
            assert document["revocation_endpoint"] == f"{ISSUER_URL}/revoke"
            assert document["scopes_supported"] == ["openid"]
            assert document["code_challenge_methods_supported"] == ["S256"]
            assert document["client_id_metadata_document_supported"] is True
            assert "none" in document["token_endpoint_auth_methods_supported"]
        prm = await client.get("/.well-known/oauth-protected-resource/mcp/")
        assert prm.status_code == 200
        assert prm.headers.get_list("cache-control") == ["public, max-age=3600"]
        assert prm.json()["resource"] == RESOURCE_URL
        assert prm.json()["authorization_servers"] == [ISSUER_URL]
        assert prm.json()["scopes_supported"] == ["openid"]
        # HEAD and OPTIONS (a browser client's preflight) are served too.
        assert (await client.head("/.well-known/oauth-authorization-server/mcp")).status_code == 200
        assert (await client.options("/.well-known/openid-configuration/mcp")).status_code == 200
        # Pruned: the bare OpenID document, the child's aliases, an unknown sibling.
        for path in (
            "/.well-known/openid-configuration",
            "/.well-known/oauth-authorization-server",
            "/mcp/.well-known/oauth-authorization-server",
            "/mcp/.well-known/oauth-protected-resource/mcp/",
            "/.well-known/anything",
        ):
            resp = await client.get(path)
            assert resp.status_code == 404, (path, resp.status_code)
            assert "location" not in resp.headers, path


async def test_discovery_resolves_no_principal_so_a_stale_bearer_is_not_a_challenge():
    """Anonymous by protocol: the pre-routing gate passes the namespace through
    unresolved, so a discovery request carrying a garbage bearer is still the
    document, not the resolver's 401 (#204's rule, kept in OIDC mode)."""
    async with oauth_app(FakeIdp()) as (_, client):
        resp = await client.get(
            "/.well-known/oauth-authorization-server/mcp", headers=_bearer("not-a-token")
        )
        assert resp.status_code == 200
        assert "www-authenticate" not in resp.headers


async def test_the_transport_challenge_points_at_the_resource_document_in_oidc_mode(anon_client):
    """T5's pointer: an anonymous MCP initialize in OIDC mode is the SDK's 401
    with `resource_metadata` naming the root document — built from
    `PUBLIC_BASE_URL`, never from Host. Local mode carries no pointer (#189's
    call (a): a pointer at a 404 would be worse than none)."""
    async with oauth_app(FakeIdp()) as (_, client):
        resp = await client.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, "X-Forwarded-Host": "evil.test"}
        )
        assert resp.status_code == 401
        assert resp.headers["www-authenticate"] == f'Bearer resource_metadata="{PRM_URL}"'
        assert resp.headers.get_list("cache-control") == ["no-store"]
    local = await anon_client.post("/mcp/", json=INITIALIZE, headers=MCP_HEADERS)
    assert local.status_code == 401
    assert local.headers["www-authenticate"] == "Bearer"


# --- the mode axis: local mode answers 404 itself (T2) ---------------------------------


@pytest.mark.parametrize("path", [*DISCOVERY_PATHS, *CHILD_PATHS])
async def test_every_family_8_path_is_404_in_local_mode_with_no_location(anon_client, path):
    """The same nine paths exist on the shipped local-mode app and answer their
    own 404 — the envelope naming the mode, never a `Bearer` challenge and never
    a redirect (§5.5: a mode is not a challenge; §5.6: no request-derived
    redirect)."""
    method = (
        "GET" if "GET" in MCP_OAUTH_ROUTES.get(path, DISCOVERY_ROUTES.get(path)).methods else "POST"
    )
    resp = await anon_client.request(
        method, path + ("?code=x&state=y" if "callback" in path else "")
    )
    assert resp.status_code == 404, (path, resp.text)
    assert resp.json()["code"] == error_codes.AUTH_NOT_IN_THIS_MODE
    assert "location" not in resp.headers, _NO_LOCATION
    assert "www-authenticate" not in resp.headers


async def test_the_shipped_local_app_builds_no_proxy(anon_client):
    from app.main import app

    assert not hasattr(app.state, MCP_OAUTH_ATTR)


# --- the verbs: the binding is the boundary, in both modes ---------------------------------


def _local_app():
    return create_app(Settings(), authorization=True)


@pytest.mark.parametrize("mode", ["local", "oidc"])
async def test_each_protocol_route_accepts_exactly_its_declared_verbs(mode):
    """An undeclared verb on any of the six is the `RouteBinding`'s 405 — `Allow`
    naming exactly the declaration, `no-store` stamped — before FastMCP's
    handler or the local-mode stub runs; a declared verb reaches the handler
    (never 404/405). Both modes, because the metadata was cleared on both
    (`declare_child_verbs`); Starlette's own 405 would have carried neither."""
    assert {p: set(policy.methods) for p, policy in MCP_OAUTH_ROUTES.items()} == _DECLARED_VERBS
    fake = FakeIdp()
    context = oauth_app(fake) if mode == "oidc" else _local_client()
    async with context as (_, client):
        for path, declared in _DECLARED_VERBS.items():
            for method in _METHOD_UNIVERSE:
                resp = await client.request(method, path)
                if method in declared:
                    assert resp.status_code not in (404, 405) or mode == "local", (
                        mode,
                        method,
                        path,
                        resp.status_code,
                    )
                    if mode == "local":
                        assert resp.status_code == 404, (method, path, resp.status_code)
                else:
                    assert resp.status_code == 405, (mode, method, path, resp.status_code)
                    allowed = {v.strip() for v in resp.headers["allow"].split(",")}
                    assert allowed == declared, (method, path, allowed)
                    assert resp.headers.get_list("cache-control") == ["no-store"]
                    assert "location" not in resp.headers


@asynccontextmanager
async def _local_client():
    live = _local_app()
    async with live.router.lifespan_context(live):
        async with AsyncClient(
            transport=ASGITransport(app=live, client=LOOPBACK, raise_app_exceptions=False),
            base_url=BASE,
        ) as client:
            yield live, client


@pytest.mark.parametrize(
    "path",
    ["/mcp/authorize/", "/mcp/token/", "/mcp/consent/", "/mcp/auth/callback/?code=x&state=y"],
)
async def test_a_trailing_slash_spelling_is_404_with_no_location_and_no_echo(path):
    """T9: `redirect_slashes` is off on the child, so a non-canonical spelling
    of a callback or authorize path is 404 — never a 3xx whose `Location` is
    built from the request and carries the code along."""
    async with oauth_app(FakeIdp()) as (_, client):
        resp = await client.get(path)
        assert resp.status_code == 404, (path, resp.status_code)
        assert "location" not in resp.headers, _NO_LOCATION
        assert "code=x" not in resp.text


# --- the flow: the owner links a native client (T6, T10) ----------------------------------


async def test_the_owner_links_a_client_and_the_token_drives_the_tools():
    """The whole round trip as the bound owner: register, authorize (to the
    consent page, on `PUBLIC_BASE_URL`), approve (to the provider, with this
    server's callback and PKCE), return (to the client's registered URI with a
    code and its state), exchange (the proxy's own pair) — and the access token
    initialises the transport and calls a write tool as the `mcp` principal
    with the fixed mapping. The audit row names the client, never a token."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        assert outcome["status"] == 200, outcome["body"]
        tokens = outcome["body"]
        assert tokens["token_type"] == "Bearer"
        assert tokens["expires_in"] == ACCESS_TOKEN_LIFETIME
        assert tokens["refresh_token"]
        assert outcome["response"].headers.get_list("cache-control") == ["no-store"]
        # The issued token is bound to this resource and signed with our key.
        claims = _decode_issued(tokens["access_token"])
        assert claims["iss"] == ISSUER_URL
        assert claims["aud"] == RESOURCE_URL
        assert claims["client_id"] == outcome["client_id"]
        # The upstream exchange went to the provider with the canonical
        # callback and the proxy's own PKCE verifier (§5.6: built from
        # PUBLIC_BASE_URL, never from Host).
        exchange_form = next(f for f in fake.token_requests if f.get("code") == FakeIdp.GOOD_CODE)
        assert exchange_form["redirect_uri"] == CALLBACK
        assert exchange_form["code_verifier"]
        assert exchange_form["_authorization"].startswith("Basic ")
        # And the token drives the transport, as an mcp:write principal.
        name = f"MCP OAuth {secrets.token_hex(4)}"
        result = await mcp_call(
            client, _bearer(tokens["access_token"]), "create_retailer", {"retailer": {"name": name}}
        )
        assert not result.get("isError"), result
        listed = await mcp_call(client, _bearer(tokens["access_token"]), "list_retailers", {})
        assert name in json.dumps(listed)
    issued = await _events(audit.MCP_GRANT_ISSUED)
    assert len(issued) == 1
    assert issued[0].principal_kind == "mcp:write"
    assert issued[0].principal_subject == OWNER_SUB
    assert issued[0].detail == f"client={outcome['client_id']}"
    assert issued[0].target == "/mcp/token"
    for secret in (tokens["access_token"], tokens["refresh_token"], fake.next_token["id_token"]):
        assert secret not in (issued[0].detail or "")


async def test_the_upstream_authorization_request_is_built_from_configuration_not_the_request():
    """T9: the provider's authorization endpoint comes from discovery, the
    `redirect_uri` is the canonical callback, `state` is the proxy's
    transaction, PKCE is forwarded, the Google parameters ride along — and a
    forged `X-Forwarded-Host` on every hop changes none of it; the consent
    redirect names `PUBLIC_BASE_URL` too."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client.headers["X-Forwarded-Host"] = "evil.test"
        client.headers["Host"] = "localhost"
        client_id = (await register(client)).json()["client_id"]
        _, challenge = _pkce()
        started = await authorize(client, client_id, challenge=challenge)
        assert started.status_code == 302
        assert started.headers["location"].startswith(f"{BASE}/mcp/consent?txn_id=")
        assert started.headers.get_list("cache-control") == ["no-store"]
        approved = await consent(client, started.headers["location"])
        upstream = approved.headers["location"]
        assert upstream.startswith(f"{ISSUER}/authorize?")
        params = _query(upstream)
        assert params["redirect_uri"] == CALLBACK
        assert params["client_id"] == CLIENT_ID
        assert params["scope"] == "openid"
        assert params["code_challenge_method"] == "S256"
        assert params["code_challenge"] != challenge  # the proxy's own PKCE, not the client's
        assert params["state"] == _query(started.headers["location"])["txn_id"]
        for key, value in UPSTREAM_AUTHORIZE_PARAMS.items():
            assert params[key] == value


async def test_the_owner_can_deny_at_the_consent_page():
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id = (await register(client)).json()["client_id"]
        _, challenge = _pkce()
        started = await authorize(client, client_id, challenge=challenge)
        denied = await consent(client, started.headers["location"], action="deny")
        assert denied.status_code == 302
        assert denied.headers["location"].startswith(NATIVE_CB + "?")
        assert _query(denied.headers["location"]) == {
            "error": "access_denied",
            "state": "client-state",
        }
        assert denied.headers.get_list("cache-control") == ["no-store"]
        assert not fake.token_requests


# --- the identity axis (T6) ---------------------------------------------------------------


async def test_a_stranger_is_refused_at_the_token_endpoint_with_nothing_minted():
    """The spike's finding 7a: the verifier alone would have handed a stranger
    a token pair and refused the first tool call. Here the code exchange runs
    the owner binding first — `invalid_grant`, an audit row naming the subject,
    no upstream token stored, and the code consumed so a retry finds nothing."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake, sub=STRANGER_SUB)
        assert outcome["status"] == 401, outcome["body"]
        assert outcome["body"]["error"] == "invalid_grant"
        assert outcome["response"].headers.get_list("cache-control") == ["no-store"]
        retry = await exchange(client, outcome["client_id"], outcome["code"], outcome["verifier"])
        assert retry.status_code == 401
        assert retry.json()["error"] == "invalid_grant"
    refused = await _events(audit.MCP_IDENTITY_REFUSED)
    assert len(refused) == 1
    assert refused[0].detail == f"subject={STRANGER_SUB} client={outcome['client_id']}"
    assert not await _events(audit.MCP_GRANT_ISSUED)
    collections = {collection for collection, _ in await _state_rows()}
    assert "mcp-upstream-tokens" not in collections
    assert "mcp-jti-mappings" not in collections


async def test_an_unbound_instance_issues_nothing():
    """A fresh instance, or one after `recovery rebind-oidc`, has no bound owner:
    whoever signs in at the provider is refused — the browser's setup token is
    the only way to bind, and the MCP path never binds (§5.6)."""
    fake = FakeIdp()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        assert outcome["status"] == 401
        assert outcome["body"]["error"] == "invalid_grant"
    assert len(await _events(audit.MCP_IDENTITY_REFUSED)) == 1


async def test_the_binding_is_the_issuer_and_subject_not_the_email():
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake, sub=STRANGER_SUB, email="owner@example.test")
        assert outcome["status"] == 401


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"sub": None}, id="no-subject"),
        pytest.param({"aud": "another-client"}, id="audience"),
        pytest.param({"iss": "https://other.idp"}, id="issuer"),
        pytest.param({"exp": 1}, id="expired"),
        pytest.param({"key": "other"}, id="signature"),
    ],
)
async def test_an_id_token_that_fails_the_claim_contract_issues_nothing(tamper):
    """The same validator the browser login applies (`validate_id_token_claims`,
    minus the nonce the proxy never sent): a token that fails it is not the
    owner's, whatever its subject says. Audited as a failed round trip, not as
    an identity refusal — nothing verified."""
    fake = FakeIdp()
    await _bind_owner()
    if tamper.get("key") == "other":
        tamper = {"key": fake.other_key}
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake, **tamper)
        assert outcome["status"] == 401, outcome["body"]
        assert outcome["body"]["error"] == "invalid_grant"
    assert not await _events(audit.MCP_GRANT_ISSUED)
    assert not await _events(audit.MCP_IDENTITY_REFUSED)
    failed = await _events(audit.OIDC_LOGIN_FAILED)
    assert len(failed) == 1 and failed[0].target == "/mcp/token"
    assert failed[0].detail.startswith("id_token_invalid")


async def test_a_rebind_refuses_an_issued_token_at_the_next_request():
    """The per-request half of the binding (the verifier): a token issued to the
    owner stops working the moment the owner row names another identity —
    `recovery rebind-oidc` leaves exactly that state."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = (await link(client, fake))["body"]
        ok = await client.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(tokens["access_token"])}
        )
        assert ok.status_code == 200
        await _bind_owner(sub="somebody-else")
        refused = await client.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(tokens["access_token"])}
        )
        assert refused.status_code == 401
        assert 'error="invalid_token"' in refused.headers["www-authenticate"]


# --- the two bearers on the mount, and the one that REST refuses (T5) ---------------------


async def test_an_mcp_access_token_is_refused_by_rest_as_a_failed_bearer():
    """§5.5: an MCP OAuth token is a delegated grant with `/mcp/` as its
    audience — on a REST route it is a presented-and-failed bearer, the
    resolver's 401 with `invalid_token`, never a downgrade to `anon`."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = (await link(client, fake))["body"]
        for path in ("/kits", "/auth/session", "/healthz"):
            resp = await client.get(path, headers=_bearer(tokens["access_token"]))
            assert resp.status_code == 401, (path, resp.text)
            assert resp.json()["code"] == error_codes.AUTH_BEARER_INVALID
            assert resp.headers["www-authenticate"] == INVALID_TOKEN_CHALLENGE


async def test_a_personal_access_token_still_works_on_the_mount_in_oidc_mode():
    """The owner's own credential is valid in every mode (§5.5): the proxy
    routes a `ptk_` bearer to the token verifier unchanged, and the mount
    requires no OAuth scope of it. A wrong secret is the same `invalid_token`
    401 it always was."""
    fake = FakeIdp()
    async with oauth_app(fake) as (_, client):
        async with get_sessionmaker()() as session:
            raw, _row = await token_service.mint_token(
                session, name="oidc-mode pat", scopes={Scope.WRITE}
            )
        result = await mcp_call(client, _bearer(raw), "list_kit_series", {})
        assert "isError" not in result or not result["isError"]
        wrong = await client.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(raw[:-3] + "xyz")}
        )
        assert wrong.status_code == 401
        assert 'error="invalid_token"' in wrong.headers["www-authenticate"]


def test_the_mcp_kind_maps_to_the_fixed_scopes_and_nothing_else_is_a_principal():
    """The fixed mapping (the spike's 7c): whatever the OAuth `scope` claim says,
    an `mcp` token is `collection:read` + `collection:write` and never admin;
    a token with no kind is refused, not guessed."""
    token = AccessToken(
        token="sha256:x",
        client_id="dcr-client",
        scopes=["openid"],
        claims={"kind": "mcp", "sub": "s"},
    )
    principal = principal_from_access_token(token)
    assert principal.label == "mcp:write"
    assert principal.subject == "s"
    assert principal.has_scope(Scope.WRITE) and not principal.has_scope(Scope.ADMIN)
    with pytest.raises(ToolError):
        principal_from_access_token(
            AccessToken(token="t", client_id="c", scopes=["collection:write"])
        )


# --- refresh, persistence and the key (T13) ----------------------------------------------


async def test_a_refresh_issues_a_new_pair_through_the_provider():
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        tokens = outcome["body"]
        fake.next_refresh = _provider_tokens(fake)
        refreshed = await client.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": outcome["client_id"],
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        assert refreshed.headers.get_list("cache-control") == ["no-store"]
        new = refreshed.json()
        assert new["access_token"] != tokens["access_token"]
        upstream = [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        assert upstream and upstream[-1]["refresh_token"] in fake.refresh_tokens
        ok = await client.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(new["access_token"])}
        )
        assert ok.status_code == 200


async def test_a_refresh_can_be_the_first_thing_a_fresh_process_hears():
    """A client that comes back after a restart with an expired access token
    refreshes before anything else — so the refresh exchange resolves the
    provider's endpoints itself rather than relying on an earlier request in
    the same process having done so (moa-15's witness)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
    fake.next_refresh = _provider_tokens(fake)
    async with oauth_app(fake) as (_, fresh):
        refreshed = await fresh.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": outcome["body"]["refresh_token"],
                "client_id": outcome["client_id"],
            },
        )
        assert refreshed.status_code == 200, refreshed.text
        upstream = [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        assert upstream and upstream[-1]["refresh_token"] in fake.refresh_tokens


async def test_state_survives_a_restart_with_the_same_key_and_not_with_another():
    """T13 through the Postgres store: a second process (a second app on the
    same database and key) accepts the first's access token and refreshes it
    without a registration; a process with **another key** reads nothing —
    the rows decrypt to nothing, the client is unknown (`invalid_client`), the
    token's signature fails — so the client relinks and nothing else is lost."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
    tokens, client_id = outcome["body"], outcome["client_id"]
    async with oauth_app(fake) as (_, second):
        ok = await second.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(tokens["access_token"])}
        )
        assert ok.status_code == 200
        fake.next_refresh = _provider_tokens(fake)
        refreshed = await second.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
            },
        )
        assert refreshed.status_code == 200, refreshed.text
    async with oauth_app(fake, mcp_oauth_signing_key=OTHER_SIGNING_KEY_HEX) as (_, third):
        refused = await third.post(
            "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(tokens["access_token"])}
        )
        assert refused.status_code == 401
        relink = await third.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
            },
        )
        assert relink.status_code == 401, relink.text
        assert relink.json()["error"] == "invalid_client"
        # And a fresh link works: the store is intact, only unreadable.
        assert (await link(third, fake))["status"] == 200


async def test_a_transaction_started_before_a_restart_completes_after_it():
    """The consent transaction is a row, so the provider's return can land on a
    fresh process — one that has resolved nothing upstream yet: the callback
    reads the provider's endpoints itself before the code exchange, and the
    browser that consented (its cookies) is what completes it."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, first):
        client_id = (await register(first)).json()["client_id"]
        verifier, challenge = _pkce()
        started = await authorize(first, client_id, challenge=challenge)
        approved = await consent(first, started.headers["location"])
        jar = first.cookies
    async with oauth_app(fake) as (_, second):
        second.cookies.update(jar)
        returned = await idp_return(second, fake, approved.headers["location"])
        assert returned.status_code == 302, returned.text[:300]
        code = _query(returned.headers["location"])["code"]
        exchanged = await exchange(second, client_id, code, verifier)
        assert exchanged.status_code == 200, exchanged.text


async def test_every_stored_value_is_encrypted_and_holds_no_token_in_clear():
    """§5.6 credential leakage: the state table never holds an upstream token
    in clear — every row is the Fernet envelope, and neither the provider's
    tokens nor the issued ones appear anywhere in it."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = (await link(client, fake))["body"]
    rows = await _state_rows()
    assert rows
    assert {collection for collection, _ in rows} >= {
        "mcp-oauth-proxy-clients",
        "mcp-upstream-tokens",
        "mcp-jti-mappings",
        "mcp-refresh-tokens",
    }
    dump = json.dumps([value for _, value in rows])
    for _, value in rows:
        assert set(value) == {"__encrypted_data__", "__encryption_version__"}, value.keys()
    for secret in (
        fake.next_token["access_token"],
        fake.next_token["refresh_token"],
        fake.next_token["id_token"],
        tokens["access_token"],
        tokens["refresh_token"],
        CLIENT_SECRET,
    ):
        assert secret not in dump


def test_the_storage_key_differs_from_the_signing_key_and_is_a_fernet_key():
    from cryptography.fernet import Fernet

    signing = bytes.fromhex(SIGNING_KEY_HEX)
    derived = storage_key(signing)
    assert base64.urlsafe_b64decode(derived) != signing
    Fernet(derived)  # a valid key
    assert storage_key(bytes.fromhex(OTHER_SIGNING_KEY_HEX)) != derived


# --- client-redirect binding per client kind (T9) ------------------------------------------


@pytest.mark.parametrize(
    "requested,expected",
    [
        (NATIVE_CB, 302),
        ("http://localhost:4000/cb", 302),  # RFC 8252 §7.3: a loopback port may vary
        ("http://127.0.0.1:3000/cb", 400),  # …but the loopback host must match
        ("http://localhost:3000/other", 400),
        ("http://localhost:3000/cb/../x", 400),
        ("http://localhost@evil.example/cb", 400),
        ("https://evil.example/cb", 400),
        ("https://evil.example/cb?next=" + NATIVE_CB, 400),
    ],
)
async def test_a_dcr_client_is_sent_only_to_a_registered_uri(requested, expected):
    fake = FakeIdp()
    async with oauth_app(fake) as (_, client):
        client_id = (await register(client, [NATIVE_CB])).json()["client_id"]
        _, challenge = _pkce()
        resp = await authorize(client, client_id, requested, challenge=challenge)
        assert resp.status_code == expected, (requested, resp.status_code, resp.text[:200])
        if expected == 400:
            assert "location" not in resp.headers, _NO_LOCATION
            assert resp.headers.get_list("cache-control") == ["no-store"]
        else:
            assert resp.headers["location"].startswith(f"{BASE}/mcp/consent?")


@pytest.mark.parametrize(
    "requested",
    [
        "https://evil.example/cb",
        "http://localhost:9999/x",
        # The URI FastMCP registers for the synthesised client, and its
        # loopback-port variant: the registration binding alone would admit
        # these (moa-1's first-pass survivor) — only the explicit refusal of
        # the upstream id stands between them and a consent page.
        "http://localhost/",
        "http://localhost:3000/",
    ],
)
async def test_the_synthesised_upstream_id_client_is_refused(requested):
    """§5.6's reproduced probe: FastMCP synthesises a client for the upstream
    client id that accepts any redirect URI. Nobody uses it (the spike named
    every client's kind), so it is an unknown client here — 400, no Location —
    whatever the URI, its own fake registration included."""
    async with oauth_app(FakeIdp()) as (_, client):
        _, challenge = _pkce()
        resp = await authorize(client, CLIENT_ID, requested, challenge=challenge)
        assert resp.status_code == 400, resp.text[:200]
        assert "location" not in resp.headers, _NO_LOCATION
        assert (
            "not registered" in resp.json()["error_description"].lower()
            or resp.json()["error"] == "invalid_request"
        )


async def test_an_operator_allowlist_narrows_registration_and_keeps_the_registration_binding():
    """Under `MCP_OAUTH_ALLOWED_REDIRECT_URIS=http://localhost:*`: registering a
    URI outside it is refused (`invalid_redirect_uri`); a registered client is
    still bound to what it registered — `localhost:5000/anything-at-all`
    matches the pattern and is 400 all the same (FastMCP alone would have let
    it through: the pattern replaced the registration) — while the loopback
    port still varies."""
    async with oauth_app(FakeIdp(), mcp_oauth_allowed_redirect_uris="http://localhost:*") as (
        _,
        client,
    ):
        outside = await register(client, ["https://client.example/cb"])
        assert outside.status_code == 400, outside.text
        assert outside.json()["error"] == "invalid_redirect_uri"
        client_id = (await register(client, [NATIVE_CB])).json()["client_id"]
        _, challenge = _pkce()
        for requested, expected in (
            (NATIVE_CB, 302),
            ("http://localhost:4000/cb", 302),
            ("http://localhost:5000/anything-at-all", 400),
            ("http://127.0.0.1:3000/cb", 400),
            ("https://evil.example/cb", 400),
        ):
            resp = await authorize(client, client_id, requested, challenge=challenge)
            assert resp.status_code == expected, (requested, resp.status_code, resp.text[:200])
            if expected == 400:
                assert "location" not in resp.headers, _NO_LOCATION


def _cimd_document(**overrides) -> CIMDDocument:
    values = dict(
        client_id=CIMD_ID,
        client_name="Some web client",
        redirect_uris=[CIMD_CB],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        scope="openid",
    )
    values.update(overrides)
    return CIMDDocument(**values)


@pytest.fixture
def cimd_client(monkeypatch):
    """A CIMD client whose metadata document FastMCP would fetch from its
    `https` client id (Claude web, ChatGPT web): the fetch is the one thing
    played here — the SSRF guard refuses anything a test could serve — and
    the manager builds the client from the document exactly as it would."""
    document = _cimd_document()

    async def fetch(self, client_id_url: str) -> CIMDDocument:
        assert client_id_url == CIMD_ID
        return document

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)
    return document


@pytest.mark.parametrize(
    "requested,expected",
    [(CIMD_CB, 302), (None, 302), (CIMD_CB + "2", 400), ("https://evil.example/cb", 400)],
)
async def test_a_cimd_client_is_bound_by_its_document(cimd_client, requested, expected):
    """CIMD per its declaration (§5.6): the document's `redirect_uris` are the
    binding — exactly, a single declared URI standing in when none is sent —
    and the client id itself is the `https` document URL, no registration."""
    async with oauth_app(FakeIdp()) as (_, client):
        _, challenge = _pkce()
        resp = await authorize(client, CIMD_ID, requested, challenge=challenge)
        assert resp.status_code == expected, (requested, resp.status_code, resp.text[:200])
        if expected == 400:
            assert "location" not in resp.headers, _NO_LOCATION
        else:
            assert resp.headers["location"].startswith(f"{BASE}/mcp/consent?")


async def test_an_operator_allowlist_binds_a_cimd_client_too(cimd_client):
    """The measured FastMCP rule, kept and documented: when an allowlist is set
    it applies to every client kind — a CIMD client's declared callback must
    also match it, so an operator who lists only loopback locks the web
    clients out (`.env.example` says so)."""
    async with oauth_app(FakeIdp(), mcp_oauth_allowed_redirect_uris="http://localhost:*") as (
        _,
        client,
    ):
        _, challenge = _pkce()
        resp = await authorize(client, CIMD_ID, CIMD_CB, challenge=challenge)
        assert resp.status_code == 400
        assert "location" not in resp.headers
    async with oauth_app(
        FakeIdp(), mcp_oauth_allowed_redirect_uris="http://localhost:*,https://client.example/*"
    ) as (_, client):
        _, challenge = _pkce()
        resp = await authorize(client, CIMD_ID, CIMD_CB, challenge=challenge)
        assert resp.status_code == 302


async def test_a_cimd_client_links_and_is_named_in_the_audit_row(cimd_client):
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        verifier, challenge = _pkce()
        started = await authorize(client, CIMD_ID, CIMD_CB, challenge=challenge)
        assert started.status_code == 302
        approved = await consent(client, started.headers["location"])
        returned = await idp_return(client, fake, approved.headers["location"])
        assert returned.status_code == 302
        assert returned.headers["location"].startswith(CIMD_CB + "?")
        code = _query(returned.headers["location"])["code"]
        exchanged = await exchange(client, CIMD_ID, code, verifier, redirect_uri=CIMD_CB)
        assert exchanged.status_code == 200, exchanged.text
        claims = _decode_issued(exchanged.json()["access_token"])
        assert claims["client_id"] == CIMD_ID
    issued = await _events(audit.MCP_GRANT_ISSUED)
    assert issued[0].detail == f"client={CIMD_ID}"


async def test_a_resource_for_another_server_is_refused():
    """RFC 8707: a client asking for a token for some other resource is sent
    back with `invalid_target` — a token minted here is for `…/mcp/` only."""
    async with oauth_app(FakeIdp()) as (_, client):
        client_id = (await register(client)).json()["client_id"]
        _, challenge = _pkce()
        resp = await authorize(
            client, client_id, challenge=challenge, resource="https://other.example/mcp"
        )
        assert resp.status_code == 302
        assert resp.headers["location"].startswith(NATIVE_CB + "?")
        # FastMCP raises RFC 8707's `invalid_target`; the MCP SDK's error
        # vocabulary lacks it and rendered the refusal as `server_error` until
        # the proxy's `authorize` took over the redirect (Codex #212 round 7,
        # f22 — the contract suite drives the set; this is the single value).
        assert _query(resp.headers["location"])["error"] == "invalid_target"
        assert "mcp-oauth-transactions" not in {c for c, _ in await _state_rows()}


# --- the consent transaction's own state ----------------------------------------------------


async def test_the_callback_needs_the_consenting_browser():
    """The provider's return in another browser — one without the consent
    binding cookie — is refused: a callback URL cannot be forced onto a victim
    or replayed elsewhere (§5.6 open redirect; FastMCP's confused-deputy control,
    proven to be on)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        client_id = (await register(client)).json()["client_id"]
        _, challenge = _pkce()
        started = await authorize(client, client_id, challenge=challenge)
        approved = await consent(client, started.headers["location"])
        async with AsyncClient(
            transport=ASGITransport(app=live, client=LOOPBACK, raise_app_exceptions=False),
            base_url=BASE,
        ) as other_browser:
            returned = await idp_return(other_browser, fake, approved.headers["location"])
        assert returned.status_code == 403
        assert "location" not in returned.headers, _NO_LOCATION
        assert returned.headers.get_list("cache-control") == ["no-store"]
        assert not fake.token_requests  # the code was never exchanged


async def test_a_consent_form_without_its_csrf_token_is_refused():
    fake = FakeIdp()
    async with oauth_app(fake) as (_, client):
        client_id = (await register(client)).json()["client_id"]
        _, challenge = _pkce()
        started = await authorize(client, client_id, challenge=challenge)
        txn_id = _query(started.headers["location"])["txn_id"]
        await client.get(started.headers["location"])
        forged = await client.post(
            "/mcp/consent",
            data={"txn_id": txn_id, "csrf_token": "guess", "action": "approve"},
            headers={"Origin": BASE},
        )
        assert forged.status_code == 400
        assert "location" not in forged.headers
        assert forged.headers.get_list("cache-control") == ["no-store"]


# --- the response profile (T10) -------------------------------------------------------------


async def test_every_transaction_and_credential_response_is_no_store_and_discovery_is_not():
    """§5.6 credential leakage: consent GET (its state cookie intact) and POST,
    the callback redirect, registration, the token response and its failures,
    revocation and its failures, the authorize errors — all `no-store`, stamped
    by the route binding over whatever FastMCP set (the consent page and the
    redirects carried nothing; revocation's error paths carried nothing).
    Discovery keeps its declared public caching."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        registered = await register(client)
        assert registered.status_code == 201
        assert registered.headers.get_list("cache-control") == ["no-store"]
        client_id = registered.json()["client_id"]
        verifier, challenge = _pkce()
        started = await authorize(client, client_id, challenge=challenge)
        page = await client.get(started.headers["location"])
        assert page.status_code == 200
        assert page.headers.get_list("cache-control") == ["no-store"]
        assert any(
            c.startswith("__MCP_CONSENT_STATE=") for c in page.headers.get_list("set-cookie")
        )
        approved = await consent(client, started.headers["location"])
        assert approved.headers.get_list("cache-control") == ["no-store"]
        assert any(
            c.startswith("__MCP_CONSENT_BINDING=") for c in approved.headers.get_list("set-cookie")
        )
        returned = await idp_return(client, fake, approved.headers["location"])
        assert returned.status_code == 302
        assert returned.headers.get_list("cache-control") == ["no-store"]
        code = _query(returned.headers["location"])["code"]
        exchanged = await exchange(client, client_id, code, verifier)
        assert exchanged.status_code == 200
        assert exchanged.headers.get_list("cache-control") == ["no-store"]
        bad_code = await exchange(client, client_id, "no-such-code", verifier)
        assert bad_code.status_code == 401
        assert bad_code.headers.get_list("cache-control") == ["no-store"]
        # RFC 7009 through the SDK's model: `client_secret` is a required form
        # field even for a public client, so a native client sends it empty.
        revoked = await client.post(
            "/mcp/revoke",
            data={
                "token": exchanged.json()["refresh_token"],
                "client_id": client_id,
                "client_secret": "",
            },
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.headers.get_list("cache-control") == ["no-store"]
        # The upstream revocation itself is FastMCP's own httpx call, not the
        # injectable upstream client, so it is not observed here; the local
        # half — the refresh token gone — is.
        replay = await client.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": exchanged.json()["refresh_token"],
                "client_id": client_id,
            },
        )
        assert replay.status_code == 401
        assert replay.headers.get_list("cache-control") == ["no-store"]
        bad_revoke = await client.post("/mcp/revoke", data={"token": "x"})
        assert bad_revoke.status_code in (400, 401)
        assert bad_revoke.headers.get_list("cache-control") == ["no-store"]
        no_params = await client.get("/mcp/authorize")
        assert no_params.status_code == 400
        assert no_params.headers.get_list("cache-control") == ["no-store"]
        for path in DISCOVERY_PATHS:
            assert (await client.get(path)).headers.get_list("cache-control") == [
                "public, max-age=3600"
            ]


# --- safe failure (§5.6) ---------------------------------------------------------------------


async def test_a_provider_down_at_authorize_is_temporarily_unavailable_to_the_client():
    """A fresh process whose provider is unreachable: discovery still answers
    (nothing upstream in it), `authorize` sends the client back with the OAuth
    error for it rather than a 500 or a redirect to a placeholder, and no
    transaction is stored."""
    fake = FakeIdp()
    async with oauth_app(fake) as (live, client):
        client_id = (await register(client)).json()["client_id"]
        # A second process, so to speak: no cached discovery, and the provider
        # has gone away.
        fresh = OidcProvider.from_settings(
            oidc_settings(), http_client=AsyncClient(transport=httpx.MockTransport(fake.handler))
        )
        setattr(live.state, OIDC_PROVIDER_ATTR, fresh)
        fake.network_down = True
        doc = await client.get("/.well-known/oauth-authorization-server/mcp")
        assert doc.status_code == 200
        _, challenge = _pkce()
        resp = await authorize(client, client_id, challenge=challenge)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith(NATIVE_CB + "?")
        assert _query(resp.headers["location"])["error"] == "temporarily_unavailable"
    assert "mcp-oauth-transactions" not in {c for c, _ in await _state_rows()}


async def test_an_issued_token_keeps_working_through_an_outage_while_its_keys_are_cached():
    """§5.6 safe failure: the provider going away after the link changes nothing
    for a token whose id_token still verifies against the cached keys; a
    refresh, which needs the provider, fails and says so."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        fake.network_down = True
        ok = await client.post(
            "/mcp/",
            json=INITIALIZE,
            headers={**MCP_HEADERS, **_bearer(outcome["body"]["access_token"])},
        )
        assert ok.status_code == 200
        refreshed = await client.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": outcome["body"]["refresh_token"],
                "client_id": outcome["client_id"],
            },
        )
        assert refreshed.status_code == 401, refreshed.text
        assert refreshed.json()["error"] == "invalid_grant"


# --- logs (T10) ------------------------------------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage() + " " + repr(record.args))


async def test_a_full_link_and_tool_run_leaves_no_secret_in_the_logs():
    """Every logger re-enabled and captured at DEBUG — attached to each one,
    not only root, since FastMCP's and uvicorn's do not propagate (the token
    suite's precedent, Codex #202 round 1, f3): across a link, a tool call and
    a refresh, no line carries the provider's tokens, the issued pair, the
    authorization code or the client secret. Bounded as there: no access log
    exists under ASGITransport."""
    fake = FakeIdp()
    await _bind_owner()
    loggers = [
        lg for lg in logging.root.manager.loggerDict.values() if isinstance(lg, logging.Logger)
    ]
    was_disabled = {lg: lg.disabled for lg in loggers}
    levels = {lg: lg.level for lg in loggers}
    capture = _Capture()
    for lg in loggers:
        lg.disabled = False
        lg.setLevel(logging.DEBUG)
        lg.addHandler(capture)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    try:
        async with oauth_app(fake) as (_, client):
            outcome = await link(client, fake)
            assert outcome["status"] == 200
            await mcp_call(client, _bearer(outcome["body"]["access_token"]), "list_kit_series", {})
            fake.next_refresh = _provider_tokens(fake)
            await client.post(
                "/mcp/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": outcome["body"]["refresh_token"],
                    "client_id": outcome["client_id"],
                },
            )
    finally:
        root.removeHandler(capture)
        root.setLevel(previous)
        for lg, disabled in was_disabled.items():
            lg.removeHandler(capture)
            lg.setLevel(levels[lg])
            lg.disabled = disabled
    blob = "\n".join(capture.lines)
    assert capture.lines, "nothing was logged — the capture saw no logger"
    secrets_ = [
        outcome["body"]["access_token"],
        outcome["body"]["refresh_token"],
        outcome["code"],
        fake.next_token["access_token"],
        fake.next_token["refresh_token"],
        fake.next_token["id_token"],
        fake.next_refresh["access_token"],
        CLIENT_SECRET,
    ]
    for secret in secrets_:
        assert secret not in blob, secret[:12]


# --- settings (the env contract) -------------------------------------------------------------


def test_oidc_mode_requires_the_signing_key_and_an_https_or_loopback_base_url():
    with pytest.raises(ValueError, match="MCP_OAUTH_SIGNING_KEY"):
        oidc_settings(mcp_oauth_signing_key="")
    with pytest.raises(ValueError, match="64 hex"):
        oidc_settings(mcp_oauth_signing_key="not-hex")
    with pytest.raises(ValueError, match="64 hex"):
        oidc_settings(mcp_oauth_signing_key="abcd")
    with pytest.raises(ValueError, match="https PUBLIC_BASE_URL"):
        oidc_settings(public_base_url="http://nas.lan:8080")
    for base in ("https://plamo.example", "http://localhost:8080", "http://127.0.0.1:8080"):
        assert oidc_settings(public_base_url=base).public_base_url == base
    # Local mode needs none of it, and a plain-http LAN address stays fine there.
    local = Settings(auth_mode="local", public_base_url="http://nas.lan:8080")
    assert local.mcp_oauth_signing_key_bytes == b""
    assert local.mcp_oauth_allowed_redirect_uri_patterns is None


def test_the_allowlist_setting_is_patterns_or_nothing():
    assert oidc_settings(
        mcp_oauth_allowed_redirect_uris=" http://localhost:* , https://*.example.com/* "
    ).mcp_oauth_allowed_redirect_uri_patterns == ["http://localhost:*", "https://*.example.com/*"]
    with pytest.raises(ValueError, match="MCP_OAUTH_ALLOWED_REDIRECT_URIS"):
        oidc_settings(mcp_oauth_allowed_redirect_uris="localhost:3000/cb")
    with pytest.raises(ValueError, match="MCP_OAUTH_ALLOWED_REDIRECT_URIS"):
        oidc_settings(mcp_oauth_allowed_redirect_uris="javascript:alert(1)")


def test_the_verdict_names_its_reason():
    assert OwnerVerdict(None, "identity", "s").subject == "s"
    assert OwnerVerdict(None, "invalid").binding is None


# --- the grant as one state machine: issuance, refresh, verification, revocation
# --- (Codex #212 round 1, f1–f3, f5) ------------------------------------------------------


async def refresh(client, client_id: str, refresh_token: str) -> httpx.Response:
    return await client.post(
        "/mcp/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
    )


async def revoke(client, client_id: str, token: str, *, hint: str | None = None) -> httpx.Response:
    """RFC 7009 §2.1 as a public client sends it: the token and the client id,
    no secret. (This helper once sent `client_secret=""` because the SDK's
    form model required the field — and so adapted every revocation test to
    a defect a public client would have met: Codex #212 round 4, f12. The
    contract suite, `test_mcp_oauth_clients.py`, drives the form itself.)"""
    form = {"token": token, "client_id": client_id}
    if hint is not None:
        form["token_type_hint"] = hint
    return await client.post("/mcp/revoke", data=form)


async def initialize(client, access_token: str) -> httpx.Response:
    return await client.post(
        "/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **_bearer(access_token)}
    )


def _provider_refresh(fake: FakeIdp, *, id_token: object = "same", **overrides) -> dict:
    """A refresh response the fake will honour: a new upstream pair, and an
    id_token when the provider chooses to send one — `"same"` re-issues the
    owner's, `None` omits it (OpenID Connect Core §12.2 allows both). The
    re-issued token carries a unique `jti`: with identical claims in the same
    second an RS256 token is the same bytes as the one issued at link time,
    and a test meaning to bring a *new* id_token then brought the old one back
    (the moa-49 survivor — green because nothing had drifted)."""
    response = {
        "access_token": "upstream-access-" + secrets.token_hex(8),
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "upstream-refresh-" + secrets.token_hex(8),
        "scope": "openid",
    }
    if id_token == "same":
        response["id_token"] = fake.issue(
            sub=OWNER_SUB, nonce=None, omit=("nonce",), jti=secrets.token_hex(8)
        )
    elif id_token is not None:
        response["id_token"] = id_token
    response.update(overrides)
    fake.refresh_tokens.add(response["refresh_token"])
    return response


def _advance_id_token_clock(monkeypatch, seconds: int) -> None:
    """Move only the id_token claim validator's clock — the proxy's own JWT,
    the upstream token's expiry and the store's TTLs keep real time — so an
    id_token verified at issuance is now past its `exp` and nothing else is."""
    original = oidc_module.validate_id_token_claims

    def later(claims, **kw):
        return original(claims, **{**kw, "now": int(time.time()) + seconds})

    monkeypatch.setattr(oidc_module, "validate_id_token_claims", later)


@pytest.mark.parametrize("presented", ["access_token", "refresh_token"])
async def test_a_successful_revocation_kills_every_credential_of_the_grant(presented):
    """RFC 7009 §2.1: after a 200 from `/revoke` the token is unusable, and
    revoking either half of the pair takes the whole grant with it — the
    access token, the refresh token, and the provider's own refresh token,
    revoked upstream through the injectable client (a witness, at last) after
    the local record is gone. FastMCP alone left the access mapping to its
    hour-long TTL and posted a reference string upstream (Codex #212 f1)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        tokens, client_id = outcome["body"], outcome["client_id"]
        upstream_refresh = fake.next_token["refresh_token"]
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        revoked = await revoke(client, client_id, tokens[presented])
        assert revoked.status_code == 200, revoked.text
        assert revoked.headers.get_list("cache-control") == ["no-store"]
        refused = await initialize(client, tokens["access_token"])
        assert refused.status_code == 401, refused.text
        assert 'error="invalid_token"' in refused.headers["www-authenticate"]
        fake.next_refresh = _provider_refresh(fake)
        replay = await refresh(client, client_id, tokens["refresh_token"])
        assert replay.status_code == 401, replay.text
        assert replay.json()["error"] == "invalid_grant"
        # The provider was told about *its* credential, not ours.
        assert [r["token"] for r in fake.revoked] == [upstream_refresh]
        assert fake.revoked[0].get("token_type_hint") == "refresh_token"
        assert not [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
    collections = {collection for collection, _ in await _state_rows()}
    assert "mcp-upstream-tokens" not in collections
    if presented == "refresh_token":
        # Its own hash entry goes too (an access token cannot name it; that
        # row is dead weight until its TTL, refused through the missing set).
        assert "mcp-refresh-tokens" not in collections
    rows = await _events(audit.MCP_GRANT_REVOKED)
    assert len(rows) == 1
    assert rows[0].principal_kind == "mcp:write"
    assert rows[0].principal_subject == OWNER_SUB
    assert rows[0].detail == f"client={client_id} presented={presented}"
    assert rows[0].target == "/mcp/revoke"
    for secret in (tokens["access_token"], tokens["refresh_token"], upstream_refresh):
        assert secret not in (rows[0].detail or "")


async def test_revocation_is_local_first_so_a_provider_outage_changes_nothing_for_the_client():
    """§5.6 safe failure: the local record goes before the provider is asked,
    so a provider that is down still leaves the client with a dead token and
    a 200 — the upstream half is best effort and is simply not witnessed."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        tokens, client_id = outcome["body"], outcome["client_id"]
        fake.network_down = True
        revoked = await revoke(client, client_id, tokens["access_token"])
        assert revoked.status_code == 200, revoked.text
        assert (await initialize(client, tokens["access_token"])).status_code == 401
        fake.network_down = False
        fake.next_refresh = _provider_refresh(fake)
        assert (await refresh(client, client_id, tokens["refresh_token"])).status_code == 401
        assert fake.revoked == []
    assert len(await _events(audit.MCP_GRANT_REVOKED)) == 1


async def test_a_client_cannot_revoke_another_clients_grant():
    """RFC 7009 §2.1 the other way: a client may revoke only its own tokens.
    The SDK answers 200 either way (an unknown token is not an error); what
    matters is that the other client's grant is untouched and nothing is
    recorded as revoked."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        first = await link(client, fake)
        second = await link(client, fake)
        assert first["status"] == 200 and second["status"] == 200
        crossed = await revoke(client, second["client_id"], first["body"]["access_token"])
        assert crossed.status_code == 200
        assert (await initialize(client, first["body"]["access_token"])).status_code == 200
        assert fake.revoked == []
    assert not await _events(audit.MCP_GRANT_REVOKED)


def _barrier(parties: int):
    """A two-party gate: each caller parks until every party has arrived, then
    all proceed together — an occurrence, not an opportunity (the concurrency
    note in `.agents/testing-and-review.md`). It sits **in front of** the
    exchange, where nothing is held yet, so it cannot be half of a cycle
    with the grant lock the fix takes inside."""
    arrived = 0
    released = asyncio.Event()

    async def wait() -> None:
        nonlocal arrived
        arrived += 1
        if arrived == parties:
            released.set()
        await released.wait()

    return wait


def _gate(proxy, method: str, wait) -> None:
    original = getattr(proxy, method)

    async def gated(*args, **kwargs):
        await wait()
        return await original(*args, **kwargs)

    setattr(proxy, method, gated)


async def test_two_redemptions_of_one_authorization_code_yield_one_grant():
    """RFC 6749 §4.1.2: a code is used once. Two processes (two apps on the
    one Postgres store) both load the code and both reach the exchange — the
    barrier releases them together — and exactly one mints; the other is
    `invalid_grant` with nothing stored for it. FastMCP's own get→mint→delete
    is not atomic and minted twice (Codex #212 f2)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (first_app, first), oauth_app(fake) as (second_app, second):
        client_id = (await register(first)).json()["client_id"]
        verifier, challenge = _pkce()
        started = await authorize(first, client_id, challenge=challenge)
        approved = await consent(first, started.headers["location"])
        returned = await idp_return(first, fake, approved.headers["location"])
        code = _query(returned.headers["location"])["code"]
        wait = _barrier(2)
        for live in (first_app, second_app):
            _gate(getattr(live.state, MCP_OAUTH_ATTR).proxy, "exchange_authorization_code", wait)
        outcomes = await asyncio.gather(
            exchange(first, client_id, code, verifier), exchange(second, client_id, code, verifier)
        )
        statuses = sorted(r.status_code for r in outcomes)
        assert statuses == [200, 401], [(r.status_code, r.text[:120]) for r in outcomes]
        loser = next(r for r in outcomes if r.status_code == 401)
        assert loser.json()["error"] == "invalid_grant"
        winner = next(r for r in outcomes if r.status_code == 200)
        assert (await initialize(first, winner.json()["access_token"])).status_code == 200
    assert len(await _events(audit.MCP_GRANT_ISSUED)) == 1
    rows = await _state_rows()
    assert len([c for c, _ in rows if c == "mcp-upstream-tokens"]) == 1
    assert len([c for c, _ in rows if c == "mcp-refresh-tokens"]) == 1


async def test_two_redemptions_of_one_refresh_token_yield_one_successor_lineage():
    """RFC 9700 §4.14.2: rotation is replay detection, so two winners defeat
    it. Two processes present the same refresh token and reach the exchange
    together; one gets the new pair, the other `invalid_grant`, the provider
    was asked once — and afterwards only the winner's lineage continues: its
    new refresh token refreshes again, the presented one is dead."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (first_app, first), oauth_app(fake) as (second_app, second):
        outcome = await link(first, fake)
        tokens, client_id = outcome["body"], outcome["client_id"]
        fake.next_refresh = _provider_refresh(fake)
        wait = _barrier(2)
        for live in (first_app, second_app):
            _gate(getattr(live.state, MCP_OAUTH_ATTR).proxy, "exchange_refresh_token", wait)
        outcomes = await asyncio.gather(
            refresh(first, client_id, tokens["refresh_token"]),
            refresh(second, client_id, tokens["refresh_token"]),
        )
        statuses = sorted(r.status_code for r in outcomes)
        assert statuses == [200, 401], [(r.status_code, r.text[:120]) for r in outcomes]
        assert next(r for r in outcomes if r.status_code == 401).json()["error"] == "invalid_grant"
        upstream = [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        assert len(upstream) == 1
        successor = next(r for r in outcomes if r.status_code == 200).json()
        assert (await initialize(second, successor["access_token"])).status_code == 200
        fake.next_refresh = _provider_refresh(fake)
        assert (await refresh(first, client_id, successor["refresh_token"])).status_code == 200
        assert (await refresh(second, client_id, tokens["refresh_token"])).status_code == 401
    rows = await _state_rows()
    assert len([c for c, _ in rows if c == "mcp-refresh-tokens"]) == 1


async def test_a_refresh_without_a_new_id_token_keeps_the_grant_usable(monkeypatch):
    """OpenID Connect Core §12.2 permits a refresh response with no id_token.
    The binding is grant state established at issuance and carried by the
    proxy's own tokens, so the refreshed grant keeps working after the original
    id_token's `exp` — FastMCP had kept the old id_token as the thing verified
    per request, and the one validator correctly refused it (Codex #212 f3)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        tokens, client_id = outcome["body"], outcome["client_id"]
        fake.next_refresh = _provider_refresh(fake, id_token=None)
        refreshed = await refresh(client, client_id, tokens["refresh_token"])
        assert refreshed.status_code == 200, refreshed.text
        new = refreshed.json()
        _advance_id_token_clock(monkeypatch, 600)
        ok = await initialize(client, new["access_token"])
        assert ok.status_code == 200, ok.text
        # And the sibling: the original pair, no refresh at all, past the
        # id_token's expiry — the upstream token is what bounds a grant.
        assert (await initialize(client, tokens["access_token"])).status_code == 200


async def test_a_restart_between_the_consent_page_and_its_approval_still_reaches_the_provider():
    """The consent page is shown by one process and approved on a fresh one —
    a container restart in the window. The approval builds the provider's
    authorization URL, so it resolves the endpoints itself; FastMCP's consent
    submission read the placeholder and sent the browser to `.invalid` (Codex
    #212 f5). A provider that is down at that moment is the callback's 503,
    not a redirect anywhere."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, first):
        client_id = (await register(first)).json()["client_id"]
        _, challenge = _pkce()
        started = await authorize(first, client_id, challenge=challenge)
        location = started.headers["location"]
        page = await first.get(location)
        assert page.status_code == 200
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        txn_id = _query(location)["txn_id"]
        jar = first.cookies
    form = {"txn_id": txn_id, "csrf_token": csrf, "action": "approve"}
    async with oauth_app(fake) as (_, second):
        second.cookies.update(jar)
        approved = await second.post("/mcp/consent", data=form, headers={"Origin": BASE})
        assert approved.status_code == 302, approved.text[:300]
        assert approved.headers["location"].startswith(f"{ISSUER}/authorize?"), approved.headers[
            "location"
        ]
    # The same window with the provider unreachable on the fresh process.
    async with oauth_app(fake) as (_, first):
        client_id = (await register(first)).json()["client_id"]
        _, challenge = _pkce()
        started = await authorize(first, client_id, challenge=challenge)
        location = started.headers["location"]
        page = await first.get(location)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        txn_id = _query(location)["txn_id"]
        jar = first.cookies
    form = {"txn_id": txn_id, "csrf_token": csrf, "action": "approve"}
    fake.network_down = True
    async with oauth_app(fake) as (_, second):
        second.cookies.update(jar)
        down = await second.post("/mcp/consent", data=form, headers={"Origin": BASE})
        assert down.status_code == 503, down.text[:300]
        assert "location" not in down.headers, _NO_LOCATION
        assert "Identity provider unavailable" in down.text
        assert down.headers.get_list("cache-control") == ["no-store"]


# --- malformed requests on the protocol routes keep the profile (f4) ------------------------


@pytest.mark.parametrize(
    "body, content_type",
    [
        pytest.param(b"", "application/json", id="empty-json"),
        pytest.param(b"", None, id="empty-no-type"),
        pytest.param(b"not json", "application/json", id="not-json"),
        pytest.param(b"[]", "application/json", id="array"),
        pytest.param(b"null", "application/json", id="null"),
        pytest.param(b'"a string"', "application/json", id="string"),
        pytest.param(b"{}", "application/json", id="empty-object"),
    ],
)
async def test_a_registration_body_that_is_not_client_metadata_is_the_dcr_400(body, content_type):
    """RFC 7591 §3.2.2: a registration the server cannot read is
    `invalid_client_metadata`, 400, with the declared `no-store` — never the
    child app's 500 without it, which is what an empty or non-JSON body reached
    through the SDK's unconditional `request.json()` (Codex #212 f4)."""
    fake = FakeIdp()
    async with oauth_app(fake) as (_, client):
        headers = {"Content-Type": content_type} if content_type else {}
        resp = await client.post("/mcp/register", content=body, headers=headers)
        assert resp.status_code == 400, (resp.status_code, resp.text[:200])
        assert resp.headers.get_list("cache-control") == ["no-store"]
        assert resp.json()["error"] == "invalid_client_metadata"


async def test_an_exception_under_a_protocol_route_still_carries_the_profile():
    """The binding owns the route's response, its failure included: an
    exception escaping a protocol handler is a 500 stamped with the declared
    profile, not the child error layer's plain text without it (Codex #212
    f4 — the generic half; the DCR 400 above is the specific one)."""
    fake = FakeIdp()

    async def boom(scope, receive, send):
        raise RuntimeError("a protocol handler failed")

    async with oauth_app(fake) as (live, client):
        mount = next(r for r in live.routes if isinstance(r, Mount) and r.path == "/mcp")
        route = next(r for r in mount.routes if getattr(r, "path", None) == "/register")
        route.app.app = boom  # inside the RouteBinding
        resp = await client.post("/mcp/register", json={})
        assert resp.status_code == 500
        assert resp.headers.get_list("cache-control") == ["no-store"]
        assert resp.json() == {"detail": "Internal Server Error"}


async def test_the_upstream_token_bounds_a_grant_the_provider_cannot_refresh():
    """What ends a grant once the id_token is no longer re-verified: the
    provider's access token. Expired and unrefreshable (the provider is down),
    the grant's token is refused — the SDK's bearer check on the expiry FastMCP
    patches in from the upstream set — and comes back once a refresh succeeds."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake, expires_in=-5)
        assert outcome["status"] == 200, outcome["body"]
        access = outcome["body"]["access_token"]
        fake.network_down = True
        refused = await initialize(client, access)
        assert refused.status_code == 401, refused.text
        fake.network_down = False
        fake.next_refresh = _provider_refresh(fake)
        assert (await initialize(client, access)).status_code == 200


async def test_a_rebind_refuses_the_refresh_token_too():
    """The state axis of the rebind test: the grant's other half. A refresh
    token issued to the previous owner is `invalid_grant` after the owner row
    names another identity, with the provider never asked."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        await _bind_owner(sub="somebody-else")
        fake.next_refresh = _provider_refresh(fake)
        refused = await refresh(client, outcome["client_id"], outcome["body"]["refresh_token"])
        assert refused.status_code == 401, refused.text
        assert refused.json()["error"] == "invalid_grant"
        assert not [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]


@pytest.mark.parametrize("entry", ["callback", "refresh"])
async def test_a_process_whose_start_missed_the_provider_resolves_at_its_first_request(entry):
    """§5.6 safe failure, the recovery half: a process that started while the
    provider was down (the lifespan's warm-up fails, the start does not) meets
    the provider again at its **first** request — the provider's return, or a
    refresh — because each entry point resolves the endpoints itself rather
    than trusting the warm-up (moa-14/15's witness: with the endpoints a view
    of the cache, the warm-up had made every other test's entry point a
    bystander). A cold `authorize` is the down-at-authorize test's territory —
    its own resolution is what turns the outage into `temporarily_unavailable`
    before a transaction is stored — and a cold consent approval the restart
    test's."""
    fake = FakeIdp()
    await _bind_owner()
    # The state a cold process inherits, made by a warm one.
    async with oauth_app(fake) as (_, warm):
        if entry == "callback":
            client_id = (await register(warm)).json()["client_id"]
            _, challenge = _pkce()
            started = await authorize(warm, client_id, challenge=challenge)
            approved = await consent(warm, started.headers["location"])
            upstream, jar = approved.headers["location"], warm.cookies
        else:
            outcome = await link(warm, fake)
            client_id, tokens = outcome["client_id"], outcome["body"]
    fake.network_down = True
    async with oauth_app(fake) as (_, cold):  # the warm-up failed; the start did not
        fake.network_down = False
        if entry == "callback":
            cold.cookies.update(jar)
            resp = await idp_return(cold, fake, upstream)
            assert resp.status_code == 302, resp.text[:200]
            assert resp.headers["location"].startswith(NATIVE_CB + "?")
        else:
            fake.next_refresh = _provider_refresh(fake)
            resp = await refresh(cold, client_id, tokens["refresh_token"])
            assert resp.status_code == 200, resp.text


# --- the grant record under concurrent and hostile transitions (round 2, f6–f7) --------


class _Held:
    """A gate on one call: the caller parks at `reached` until the test says
    `release` — an occurrence, not an opportunity."""

    def __init__(self) -> None:
        self.reached = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self) -> None:
        self.reached.set()
        await self.release.wait()


def _hold(target, method: str) -> _Held:
    held = _Held()
    original = getattr(target, method)

    async def held_call(*args, **kwargs):
        await held()
        return await original(*args, **kwargs)

    setattr(target, method, held_call)
    return held


def _record_write(proxy):
    """The object whose `put` is the grant record's write: the store behind the
    guard on this head, the SDK's adapter itself on one without a guard."""
    store = proxy._upstream_token_store
    return getattr(store, "_inner", store)


async def _grant_ids() -> list[str]:
    """The grant records' keys — in clear in the state table; the values are
    the encrypted envelopes."""
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            text("SELECT key FROM mcp_oauth_state WHERE collection = 'mcp-upstream-tokens'")
        )
        return [row[0] for row in rows]


async def _blocked_on_the_grant_lock(grant_id: str) -> bool:
    """The exact edge, not a count: a session parked on *this grant's*
    advisory lock whose blocker (`pg_blocking_pids`) is the session holding
    it — the stg-5 shape. A namespace-wide count of waiters is an observation
    a decoy can satisfy (Codex #212 round 3)."""
    async with get_sessionmaker()() as session:
        row = await session.execute(
            text(
                "SELECT count(*) FROM pg_locks AS waiting "
                "JOIN pg_locks AS holder ON holder.locktype = 'advisory' AND holder.granted "
                "AND holder.classid = waiting.classid AND holder.objid = waiting.objid "
                "AND holder.objsubid = waiting.objsubid "
                "WHERE waiting.locktype = 'advisory' AND NOT waiting.granted "
                "AND waiting.classid = :namespace "
                "AND CAST(waiting.objid AS bigint) = CAST(:key AS bigint) "
                "AND holder.pid = ANY (pg_blocking_pids(waiting.pid))"
            ),
            {"namespace": GRANT_LOCK_NAMESPACE, "key": _lock_key(grant_id) & 0xFFFFFFFF},
        )
        return int(row.scalar_one()) > 0


async def _until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not await predicate():
        assert time.monotonic() < deadline, "the condition never arrived"
        await asyncio.sleep(0.02)


@pytest.mark.parametrize("presented", ["access_token", "refresh_token"])
@pytest.mark.parametrize("path", ["explicit", "transparent"])
async def test_a_refresh_in_flight_cannot_recreate_a_grant_that_revocation_removed(path, presented):
    """RFC 7009 §2.1, against the write the grant record gets from a refresh:
    a refresh — the client's own exchange, or the transparent one behind a
    request — holds the provider's answer and is about to write it back when
    another process revokes either half of the grant. Whichever lands first,
    once both have answered nothing of the grant works: the record is gone,
    every token of it is refused, and the provider was asked to revoke the
    refresh token the record held *at revocation*, the rotated one. The
    reviewed head's revocation deleted the record while the refresh writer
    recreated it through the store's upsert (Codex #212 round 2, f6)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (first_app, first), oauth_app(fake) as (_, second):
        outcome = await link(first, fake, expires_in=(-5 if path == "transparent" else 300))
        tokens, client_id = outcome["body"], outcome["client_id"]
        [grant_id] = await _grant_ids()
        fake.next_refresh = _provider_refresh(fake)
        rotated = fake.next_refresh["refresh_token"]
        proxy = getattr(first_app.state, MCP_OAUTH_ATTR).proxy
        held = _hold(_record_write(proxy), "put")
        if path == "explicit":
            in_flight = asyncio.create_task(refresh(first, client_id, tokens["refresh_token"]))
        else:
            in_flight = asyncio.create_task(initialize(first, tokens["access_token"]))
        await asyncio.wait_for(held.reached.wait(), 5)
        revoking = asyncio.create_task(revoke(second, client_id, tokens[presented]))

        async def revocation_landed() -> bool:
            # Either nothing serialises it and it completes here, or it is
            # seen parked on this grant's lock, blocked by the session that
            # holds it for the refresh.
            return revoking.done() or await _blocked_on_the_grant_lock(grant_id)

        await _until(revocation_landed)
        held.release.set()
        completed = await in_flight
        revoked = await revoking
        assert revoked.status_code == 200, revoked.text
        assert completed.status_code == 200, completed.text[:300]
        if path == "explicit":
            successor = completed.json()
            assert (await initialize(first, successor["access_token"])).status_code == 401
            replay = await refresh(first, client_id, successor["refresh_token"])
            assert replay.status_code == 401 and replay.json()["error"] == "invalid_grant"
        for client in (first, second):
            assert (await initialize(client, tokens["access_token"])).status_code == 401
            replay = await refresh(client, client_id, tokens["refresh_token"])
            assert replay.status_code == 401, replay.text
        assert [r["token"] for r in fake.revoked] == [rotated]
    assert "mcp-upstream-tokens" not in {c for c, _ in await _state_rows()}
    assert len(await _events(audit.MCP_GRANT_REVOKED)) == 1


async def test_a_transparent_refresh_that_finds_the_grant_gone_refuses_the_request():
    """The other order, on the path a client never sees: the request loaded
    its grant, decided to refresh (the upstream token inside its threshold —
    not yet expired, so the SDK's own expiry check would still admit the
    loaded set), and revocation completed before the refresh took the grant
    lock. The refresh finds the record gone, asks the provider nothing, and
    the request is refused — the SDK falls back to the object it had loaded
    when a refresh fails, and that fallback must not be an answer (f6)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        outcome = await link(client, fake, expires_in=20)
        tokens, client_id = outcome["body"], outcome["client_id"]
        fake.next_refresh = _provider_refresh(fake)
        proxy = getattr(live.state, MCP_OAUTH_ATTR).proxy
        held = _hold(proxy, "_try_transparent_refresh")
        in_flight = asyncio.create_task(initialize(client, tokens["access_token"]))
        await asyncio.wait_for(held.reached.wait(), 5)
        revoked = await revoke(client, client_id, tokens["refresh_token"])
        assert revoked.status_code == 200
        held.release.set()
        refused = await in_flight
        assert refused.status_code == 401, refused.text[:300]
        assert not [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        assert (await initialize(client, tokens["access_token"])).status_code == 401
    assert "mcp-upstream-tokens" not in {c for c, _ in await _state_rows()}


@pytest.mark.parametrize("response", ["owner", "omitted", "stranger", "forged"])
@pytest.mark.parametrize("path", ["explicit", "transparent"])
async def test_a_refresh_response_becomes_the_grant_only_once_it_is_verified(path, response):
    """The provider's refresh response replaces the grant's upstream set only
    after the identity it carries has been verified against the record's
    binding — on the client's exchange and on the transparent refresh alike
    (OpenID Connect Core §12.2: a refreshed id_token must keep the issuer and
    subject). The owner's re-issued id_token and a response that validly
    omits one carry on; a stranger's, or an owner-shaped token under the
    wrong key, ends the grant: nothing of the response is stored, the
    original tokens are refused even with the provider gone, and the ending
    is audited beside the refusal. The reviewed head persisted the refused set
    before the check on the exchange and never checked it on the transparent
    path (Codex #212 round 2, f7)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake, expires_in=(-5 if path == "transparent" else 300))
        tokens, client_id = outcome["body"], outcome["client_id"]
        id_token = {
            "owner": "same",
            "omitted": None,
            "stranger": fake.issue(sub=STRANGER_SUB, nonce=None, omit=("nonce",)),
            "forged": fake.issue(sub=OWNER_SUB, nonce=None, omit=("nonce",), key=fake.other_key),
        }[response]
        fake.next_refresh = _provider_refresh(fake, id_token=id_token)
        if path == "explicit":
            answered = await refresh(client, client_id, tokens["refresh_token"])
        else:
            answered = await initialize(client, tokens["access_token"])
        hostile = response in ("stranger", "forged")
        if not hostile:
            assert answered.status_code == 200, answered.text[:300]
            if path == "explicit":
                successor = answered.json()["access_token"]
                assert (await initialize(client, successor)).status_code == 200
            assert "mcp-upstream-tokens" in {c for c, _ in await _state_rows()}
            assert not await _events(audit.MCP_IDENTITY_REFUSED)
            assert not await _events(audit.OIDC_LOGIN_FAILED)
            assert not await _events(audit.MCP_GRANT_REVOKED)
            return
        assert answered.status_code == 401, answered.text[:300]
        if path == "explicit":
            assert answered.json()["error"] == "invalid_grant"
        # Nothing left to refresh with: what is stored decides, and nothing is.
        fake.network_down = True
        assert (await initialize(client, tokens["access_token"])).status_code == 401
        fake.network_down = False
        fake.next_refresh = _provider_refresh(fake)
        replay = await refresh(client, client_id, tokens["refresh_token"])
        assert replay.status_code == 401 and replay.json()["error"] == "invalid_grant"
        assert "mcp-upstream-tokens" not in {c for c, _ in await _state_rows()}
    target = "/mcp/token" if path == "explicit" else "/mcp/"
    if response == "stranger":
        refused = await _events(audit.MCP_IDENTITY_REFUSED)
        assert [(r.detail, r.target) for r in refused] == [
            (f"subject={STRANGER_SUB} client={client_id}", target)
        ]
        assert not await _events(audit.OIDC_LOGIN_FAILED)
    else:
        failed = await _events(audit.OIDC_LOGIN_FAILED)
        assert [(r.detail, r.target) for r in failed] == [
            (f"id_token_invalid client={client_id}", target)
        ]
        assert not await _events(audit.MCP_IDENTITY_REFUSED)
    ended = await _events(audit.MCP_GRANT_REVOKED)
    assert [(r.detail, r.target, r.principal_subject) for r in ended] == [
        (f"client={client_id} ended_by=upstream_refresh", target, OWNER_SUB)
    ]
    assert len(await _events(audit.MCP_GRANT_ISSUED)) == 1


async def test_a_binding_verified_on_a_transparent_refresh_carries_to_the_next_exchange(
    monkeypatch,
):
    """The verified binding lives on the record, not in the tokens: a
    transparent refresh brings the owner's new id_token (verified, stored),
    that token then passes its `exp`, and the client's next exchange — the
    provider omitting an id_token this time — carries the record's binding
    forward rather than re-verifying a token it already verified. Comparing
    the stored id_token against the digest the *client's* tokens carried
    would find it "new" and expired — round 1's f3 by another road."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake, expires_in=-5)
        tokens, client_id = outcome["body"], outcome["client_id"]
        fake.next_refresh = _provider_refresh(fake)
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        _advance_id_token_clock(monkeypatch, 600)
        fake.next_refresh = _provider_refresh(fake, id_token=None)
        renewed = await refresh(client, client_id, tokens["refresh_token"])
        assert renewed.status_code == 200, renewed.text
        assert (await initialize(client, renewed.json()["access_token"])).status_code == 200
    assert not await _events(audit.OIDC_LOGIN_FAILED)
    assert not await _events(audit.MCP_GRANT_REVOKED)


# --- Codex #212 round 3: revocation's own lookup; the identity that authorized the grant ----


#: The owner after `recovery rebind-oidc` and the next owner's first login.
REBOUND_SUB = "owner-subject-after-rebind"


@pytest.mark.parametrize("upstream", ["inside_threshold", "expired"])
@pytest.mark.parametrize("presented", ["access_token", "refresh_token"])
async def test_a_revocation_locates_its_grant_without_asking_the_provider(presented, upstream):
    """RFC 7009 §2.1, against the *lookup*: the SDK's revocation handler
    locates the presented token through the provider's `load_access_token`,
    which on this proxy is the bearer path — the upstream set read, refreshed
    when it is near expiry or past it, the new id_token verified. A provider
    whose signing key has rotated and whose JWKS cannot be fetched turns that
    refresh into an `unavailable` verdict, which rightly leaves the verified
    grant standing for a *request* — and the lookup then answered `None`,
    which the handler reads as a token it does not hold: a silent 200, the
    grant intact and usable the moment the keys are reachable again (Codex
    #212 round 3, f9). Revocation now locates the grant by the proxy's own
    signature and the JTI mapping: the provider is asked nothing, no owner
    row is read, and the locked ending runs whatever the provider is doing.
    The refresh-token rows are the control — that lookup was always local."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        lifetime = 20 if upstream == "inside_threshold" else -5
        outcome = await link(client, fake, expires_in=lifetime)
        tokens, client_id = outcome["body"], outcome["client_id"]
        upstream_refresh = fake.next_token["refresh_token"]
        # The provider rotates its key, and its JWKS is not there to learn it from.
        fake.key = fake.other_key
        fake.next_refresh = _provider_refresh(fake)
        fake.unreachable = {"/jwks"}
        revoked = await revoke(client, client_id, tokens[presented])
        assert revoked.status_code == 200, revoked.text
        assert "mcp-upstream-tokens" not in {c for c, _ in await _state_rows()}
        assert not [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        assert [r["token"] for r in fake.revoked] == [upstream_refresh]
        fake.unreachable = set()
        refused = await initialize(client, tokens["access_token"])
        assert refused.status_code == 401, refused.text
        assert 'error="invalid_token"' in refused.headers["www-authenticate"]
        replay = await refresh(client, client_id, tokens["refresh_token"])
        assert replay.status_code == 401, replay.text
        assert replay.json()["error"] == "invalid_grant"
    ended = await _events(audit.MCP_GRANT_REVOKED)
    assert [(r.detail, r.principal_subject, r.target) for r in ended] == [
        (f"client={client_id} presented={presented}", OWNER_SUB, "/mcp/revoke")
    ]
    assert not await _events(audit.OIDC_LOGIN_FAILED)


@pytest.mark.parametrize("presented", ["access_token", "refresh_token"])
async def test_a_client_can_end_a_grant_the_owner_row_no_longer_names(presented):
    """The state axis of the lookup: the grant's binding against the owner row.
    After a rebind the grant is the previous owner's — refused on every request
    and every refresh — and the client holding it may still end it: a
    revocation reduces authority and owes no owner check, only the proxy's
    signature and the client binding. The reviewed head's lookup was the
    per-request owner check and answered `None`: a dead grant's record stayed,
    the provider's refresh token went unrevoked, nothing was audited."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        outcome = await link(client, fake)
        tokens, client_id = outcome["body"], outcome["client_id"]
        upstream_refresh = fake.next_token["refresh_token"]
        await _bind_owner(sub=REBOUND_SUB)
        revoked = await revoke(client, client_id, tokens[presented])
        assert revoked.status_code == 200, revoked.text
        assert "mcp-upstream-tokens" not in {c for c, _ in await _state_rows()}
        assert [r["token"] for r in fake.revoked] == [upstream_refresh]
    ended = await _events(audit.MCP_GRANT_REVOKED)
    assert [(r.detail, r.principal_subject) for r in ended] == [
        (f"client={client_id} presented={presented}", OWNER_SUB)
    ]


@pytest.mark.parametrize("path", ["explicit", "transparent"])
async def test_a_refresh_keeps_the_identity_that_authorized_the_grant(path):
    """OpenID Connect Core §12.2, the other half: a refreshed id_token must keep
    the grant's issuer and subject — continuity with the identity that
    authorized *this* grant, a different question from whether it names the
    owner now. Between a transition's owner check and the record gate's write
    the owner is rebound (`recovery rebind-oidc`, then the next owner's first
    login), and the provider's refresh response carries the new owner's
    id_token. The reviewed head's gate verified the candidate against the
    current owner row and adopted it: the record's binding moved from A to B,
    and B's successor bearer wrote to the collection on A's grant (Codex #212
    round 3, f10). The candidate must name the record's own binding: the grant
    ends, audited as an identity refusal beside the ending, and the new owner
    links afresh — the instance moved on; the grant that ended was A's."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        outcome = await link(client, fake, expires_in=(-5 if path == "transparent" else 300))
        tokens, client_id = outcome["body"], outcome["client_id"]
        fake.next_refresh = _provider_refresh(
            fake, id_token=fake.issue(sub=REBOUND_SUB, nonce=None, omit=("nonce",))
        )
        proxy = getattr(live.state, MCP_OAUTH_ATTR).proxy
        # The record gate itself, not the store behind it: the hold sits after
        # the transition's owner check and before the gate's own.
        held = _hold(proxy._upstream_token_store, "put")
        if path == "explicit":
            in_flight = asyncio.create_task(refresh(client, client_id, tokens["refresh_token"]))
        else:
            in_flight = asyncio.create_task(initialize(client, tokens["access_token"]))
        await asyncio.wait_for(held.reached.wait(), 5)
        await _bind_owner(sub=REBOUND_SUB)
        held.release.set()
        answered = await in_flight
        assert answered.status_code == 401, answered.text[:300]
        if path == "explicit":
            assert answered.json()["error"] == "invalid_grant"
        assert "mcp-upstream-tokens" not in {c for c, _ in await _state_rows()}
        relinked = await link(client, fake, sub=REBOUND_SUB)
        assert relinked["status"] == 200, relinked["body"]
        assert (await initialize(client, relinked["body"]["access_token"])).status_code == 200
    target = "/mcp/token" if path == "explicit" else "/mcp/"
    refused = await _events(audit.MCP_IDENTITY_REFUSED)
    assert [(r.detail, r.target) for r in refused] == [
        (f"subject={REBOUND_SUB} client={client_id}", target)
    ]
    ended = await _events(audit.MCP_GRANT_REVOKED)
    assert [(r.detail, r.target, r.principal_subject) for r in ended] == [
        (f"client={client_id} ended_by=upstream_refresh", target, OWNER_SUB)
    ]
    assert not await _events(audit.OIDC_LOGIN_FAILED)
    assert len(await _events(audit.MCP_GRANT_ISSUED)) == 2
