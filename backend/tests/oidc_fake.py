"""The fake OpenID Connect provider the OIDC-mode suites drive (#191, #192).

An RSA key, a discovery document, a JWKS, a token endpoint and a revocation
endpoint served through an httpx `MockTransport`, so every id_token axis —
issuer, audience, nonce, expiry, signature, subject — is a knob a test turns.
`oidc_app` builds an auth-enabled OIDC-mode app whose `OidcProvider` talks to
it; the MCP OAuth suite additionally points the proxy's upstream client at the
same handler (`PlamotrackOAuthProxy.upstream_transport`).
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

import httpx
from httpx import ASGITransport, AsyncClient
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey

from app.auth.mode import OIDC_PROVIDER_ATTR
from app.config import Settings
from app.main import create_app
from app.services.oidc import OidcProvider

ISSUER = "https://idp.test"
CLIENT_ID = "plamotrack-web"
CLIENT_SECRET = "a-client-secret-nobody-logs"
# Loopback, not a made-up name: in OIDC mode `PUBLIC_BASE_URL` is also the MCP
# OAuth issuer (`…/mcp`), which RFC 8414 and the MCP SDK require to be https or
# loopback (#192). Every cookie below is therefore the plain-http one.
BASE = "http://localhost"
ORIGIN = {"Origin": BASE}
OWNER_SUB = "owner-subject-1"
STRANGER_SUB = "stranger-subject-2"


# --- the fake provider ---------------------------------------------------------------


#: 32 bytes as hex — `MCP_OAUTH_SIGNING_KEY` for the test apps (#192).
SIGNING_KEY_HEX = "0123456789abcdef" * 4
#: A second key, for the "same store, other key" row (T13).
OTHER_SIGNING_KEY_HEX = "fedcba9876543210" * 4


class FakeIdp:
    """The provider as the app sees it over HTTP. `issue()` mints id_tokens; the
    token endpoint hands out whatever `next_token` holds for the code
    `GOOD_CODE`, refuses any other code with `invalid_grant`, and records the
    form it was sent so a test can assert the PKCE verifier and redirect URI."""

    GOOD_CODE = "good-code"

    def __init__(self) -> None:
        self.key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
        self.other_key = RSAKey.generate_key(2048, parameters={"kid": "k2"})
        self.issuer = ISSUER
        self.next_token: dict | None = None
        self.token_requests: list[dict] = []
        #: The MCP OAuth proxy's refresh path (#192): upstream refresh tokens
        #: this provider will honour, and what it answers with.
        self.refresh_tokens: set[str] = set()
        self.next_refresh: dict | None = None
        self.revoked: list[dict] = []
        self.discovery_status = 200
        self.token_status: int | None = None  # None → decided by the code
        self.network_down = False
        self.calls: list[str] = []

    def issue(
        self,
        *,
        nonce: object,
        sub: object = OWNER_SUB,
        email: str | None = "owner@example.test",
        iss: object = None,
        aud: object = None,
        exp: object = None,
        key: RSAKey | None = None,
        omit: tuple[str, ...] = (),
        **extra,
    ) -> str:
        """A signed id_token in which every claim is a knob: pass any value —
        a list, a null, a string where a number belongs — to put that shape in
        the token, or name a claim in `omit` to leave it out (`sub=None` omits
        it too, the older spelling of the no-subject case)."""
        now = int(time.time())
        claims = {
            "iss": self.issuer if iss is None else iss,
            "aud": CLIENT_ID if aud is None else aud,
            "iat": now,
            "exp": now + 300 if exp is None else exp,
            "nonce": nonce,
            **extra,
        }
        if sub is not None:
            claims["sub"] = sub
        if email is not None:
            claims["email"] = email
        for name in omit:
            claims.pop(name, None)
        signing = key or self.key
        return jwt.encode({"alg": "RS256", "kid": signing.kid}, claims, signing)

    def jwks(self) -> dict:
        return KeySet([self.key]).as_dict(private=False)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.path}")
        if self.network_down:
            raise httpx.ConnectError("provider down", request=request)
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            if self.discovery_status != 200:
                return httpx.Response(self.discovery_status, text="nope")
            return httpx.Response(
                200,
                json={
                    "issuer": self.issuer,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                    "revocation_endpoint": f"{ISSUER}/revoke",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if path == "/jwks":
            return httpx.Response(200, json=self.jwks())
        if path == "/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            form["_authorization"] = request.headers.get("authorization", "")
            self.token_requests.append(form)
            if self.token_status is not None:
                return httpx.Response(self.token_status, json={"error": "server_error"})
            if form.get("grant_type") == "refresh_token":
                if form.get("refresh_token") in self.refresh_tokens and self.next_refresh:
                    return httpx.Response(200, json=self.next_refresh)
                return httpx.Response(400, json={"error": "invalid_grant"})
            if form.get("code") != self.GOOD_CODE or self.next_token is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self.next_token)
        if path == "/revoke":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.revoked.append(form)
            return httpx.Response(200)
        return httpx.Response(404)


def oidc_settings(*, issuer: str = ISSUER, **overrides) -> Settings:
    """OIDC-mode settings for a test app: the browser login's provider and
    client (#191) plus the MCP OAuth signing key the mode requires (#192).
    `BASE` is loopback because the MCP OAuth issuer must be https or loopback."""
    values = dict(
        auth_mode="oidc",
        oidc_issuer=issuer,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret=CLIENT_SECRET,
        public_base_url=BASE,
        mcp_oauth_signing_key=SIGNING_KEY_HEX,
    )
    values.update(overrides)
    return Settings(**values)


@asynccontextmanager
async def oidc_app(fake: FakeIdp, *, issuer: str = ISSUER, **overrides):
    """An auth-enabled OIDC-mode app whose provider talks to `fake`, and an
    anonymous browser on it. The shipped app's injected owner never reaches it.
    The lifespan is not entered — the MCP OAuth suite has its own fixture for
    the mount, which needs the session manager and the state store's pool."""
    settings = oidc_settings(issuer=issuer, **overrides)
    live = create_app(settings, authorization=True)
    transport = httpx.MockTransport(fake.handler)
    provider = OidcProvider.from_settings(settings, http_client=AsyncClient(transport=transport))
    assert provider is not None
    setattr(live.state, OIDC_PROVIDER_ATTR, provider)
    async with AsyncClient(
        transport=ASGITransport(app=live, raise_app_exceptions=False), base_url=BASE
    ) as browser:
        yield live, browser
