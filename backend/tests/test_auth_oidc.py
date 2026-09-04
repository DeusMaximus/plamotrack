"""Browser OpenID Connect login — the flows (§5.4 OIDC mode; §5.5 family 3; §5.6 open
redirect, code interception, safe failure; §5.8 T6/T7/T10; M6-6, #191).

An app built in OIDC mode (`create_app(Settings(auth_mode="oidc", …))`) is driven
as a real anonymous browser against an in-process **fake provider**: an RSA key,
a discovery document, a JWKS and a token endpoint served through an httpx
`MockTransport`, so every id_token axis — issuer, audience, nonce, expiry,
signature, subject — is a knob the test turns. The shipped local-mode `app` is
driven only where the point is that the OIDC routes do not exist there.

The state axis (AGENTS.md, "sweep the values"): the owner row is unbound
(fresh, or after a rebind), bound to the identity signing in, or bound to a
different one; the transaction row is live, used, expired, or missing; and the
browser presents the binding cookie or not. Each refusal is asserted by the
`auth_error` code the SPA receives, by the absence of a session cookie *and* of
a session row, and by the audit row that names it.
"""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from joserfc import jwt
from joserfc.jwk import KeySet, RSAKey
from sqlalchemy import select, update

from app import error_codes
from app.auth import recovery
from app.auth.budget import FailureBudget
from app.auth.dependency import ROUTE_INDEX_ATTR
from app.auth.registry import RouteIndex
from app.auth.sessions import PLAIN_COOKIE_NAME, PLAIN_OIDC_COOKIE_NAME
from app.auth.setup_token import setup_token_state
from app.config import Settings
from app.db import get_sessionmaker
from app.main import app as local_app
from app.main import create_app
from app.models import AuditEvent, OidcLogin, Owner
from app.models import Session as SessionRow
from app.routers.auth import BUDGET_ATTR, OIDC_PROVIDER_ATTR
from app.services import audit, oidc
from app.services.oidc import CallbackError, OidcProvider

pytestmark = pytest.mark.anyio

ISSUER = "https://idp.test"
CLIENT_ID = "plamotrack-web"
CLIENT_SECRET = "a-client-secret-nobody-logs"
BASE = "http://plamo.test"
ORIGIN = {"Origin": BASE}
OWNER_SUB = "owner-subject-1"
STRANGER_SUB = "stranger-subject-2"


# --- the fake provider ---------------------------------------------------------------


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
            if form.get("code") != self.GOOD_CODE or self.next_token is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self.next_token)
        return httpx.Response(404)


@asynccontextmanager
async def oidc_app(fake: FakeIdp, *, issuer: str = ISSUER):
    """An auth-enabled OIDC-mode app whose provider talks to `fake`, and an
    anonymous browser on it. The shipped app's injected owner never reaches it."""
    settings = Settings(
        auth_mode="oidc",
        oidc_issuer=issuer,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret=CLIENT_SECRET,
        public_base_url=BASE,
    )
    live = create_app(settings, authorization=True)
    transport = httpx.MockTransport(fake.handler)
    provider = OidcProvider.from_settings(settings, http_client=AsyncClient(transport=transport))
    assert provider is not None
    setattr(live.state, OIDC_PROVIDER_ATTR, provider)
    async with AsyncClient(
        transport=ASGITransport(app=live, raise_app_exceptions=False), base_url=BASE
    ) as browser:
        yield live, browser


def fresh_browser(live) -> AsyncClient:
    """A cookie-less browser on the same app. A signed-in browser's later POSTs
    are cookie-borne and CSRF-gated (§5.6) — a state the login screens never
    reach — so a second login starts from a fresh jar, as in the local tests."""
    return AsyncClient(transport=ASGITransport(app=live, raise_app_exceptions=False), base_url=BASE)


def _issue_setup_token(live) -> str:
    return setup_token_state(live).issue()


async def _start(browser, *, setup_token: str | None = None) -> httpx.Response:
    body = {"setup_token": setup_token} if setup_token is not None else {}
    return await browser.post("/auth/oidc/start", json=body, headers=ORIGIN)


def _params(authorization_url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(authorization_url).query).items()}


async def _callback(browser, *, state: str | None, code: str | None = FakeIdp.GOOD_CODE, **q):
    params = {}
    if state is not None:
        params["state"] = state
    if code is not None:
        params["code"] = code
    params.update(q)
    return await browser.get("/auth/oidc/callback", params=params)


def _auth_error(response: httpx.Response) -> str | None:
    assert response.status_code == 302, (response.status_code, response.text[:200])
    location = response.headers["location"]
    assert location.startswith(BASE + "/"), location
    return _params(location).get("auth_error")


def _set_cookies(response: httpx.Response) -> list[str]:
    return response.headers.get_list("set-cookie")


async def _sign_in(fake: FakeIdp, browser, *, sub: str = OWNER_SUB, setup_token=None, **claims):
    """The whole round trip for one identity; returns the callback response."""
    started = await _start(browser, setup_token=setup_token)
    assert started.status_code == 200, started.text
    params = _params(started.json()["authorization_url"])
    fake.next_token = {
        "id_token": fake.issue(sub=sub, nonce=params["nonce"], **claims),
        "access_token": "opaque-access-token",
        "token_type": "Bearer",
    }
    return await _callback(browser, state=params["state"])


async def _owner() -> Owner:
    async with get_sessionmaker()() as session:
        return await session.get(Owner, 1)


async def _events(event_type: str) -> list[AuditEvent]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(select(AuditEvent).where(AuditEvent.event_type == event_type))
        return list(rows.scalars())


async def _session_count() -> int:
    async with get_sessionmaker()() as session:
        return len((await session.execute(select(SessionRow))).scalars().all())


# --- the mode ------------------------------------------------------------------------


async def test_session_reports_oidc_mode_and_unclaimed_on_a_fresh_instance():
    async with oidc_app(FakeIdp()) as (_, browser):
        response = await browser.get("/auth/session")
    body = response.json()
    assert body["state"] == "unclaimed"
    assert body["auth_mode"] == "oidc"
    assert body["oidc_issuer"] == ISSUER
    assert body["csrf_token"] is None


async def test_the_shipped_local_app_reports_local_mode(anon_client):
    body = (await anon_client.get("/auth/session")).json()
    assert body["auth_mode"] == "local"
    assert body["oidc_issuer"] is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/auth/login", {"password": "whatever-this-is"}),
        ("POST", "/auth/setup", {"token": "x", "password": "twelve-characters"}),
    ],
)
async def test_the_password_routes_are_404_in_oidc_mode(method, path, body):
    """Mutually exclusive modes (§5.4): a password can neither claim nor sign in
    to an OIDC instance. 404, not 401 — a mode is not a challenge."""
    async with oidc_app(FakeIdp()) as (_, browser):
        response = await browser.request(method, path, json=body, headers=ORIGIN)
    assert response.status_code == 404
    assert response.json()["code"] == error_codes.AUTH_NOT_IN_THIS_MODE
    assert "www-authenticate" not in response.headers


async def test_the_oidc_routes_are_404_in_local_mode(anon_client):
    started = await anon_client.post("/auth/oidc/start", json={}, headers={"Origin": "http://test"})
    assert started.status_code == 404
    assert started.json()["code"] == error_codes.AUTH_NOT_IN_THIS_MODE
    callback = await anon_client.get("/auth/oidc/callback", params={"state": "x", "code": "y"})
    assert callback.status_code == 404
    assert callback.json()["code"] == error_codes.AUTH_NOT_IN_THIS_MODE
    assert "location" not in callback.headers


def test_the_registry_declares_the_mode_axis():
    """The mode each family-3 action exists in is a declaration the matrix reads
    (§5.5), not something inferred from a 404."""
    index: RouteIndex = getattr(local_app.state, ROUTE_INDEX_ATTR)
    by_path = {
        (route.path, method): index.by_endpoint[route.endpoint]
        for route in index.routes
        for method in route.methods
    }
    assert by_path[("/auth/login", "POST")].modes == frozenset({"local"})
    assert by_path[("/auth/setup", "POST")].modes == frozenset({"local"})
    assert by_path[("/auth/oidc/start", "POST")].modes == frozenset({"oidc"})
    assert by_path[("/auth/oidc/callback", "GET")].modes == frozenset({"oidc"})
    assert by_path[("/auth/session", "GET")].modes == frozenset({"local", "oidc"})
    assert by_path[("/auth/logout", "POST")].modes == frozenset({"local", "oidc"})


# --- starting a login -------------------------------------------------------------------


async def test_start_on_an_unbound_instance_needs_the_setup_token():
    """The claim gate (§5.6 safe failure; T8): no token → 403 like a wrong
    password, audited against the OIDC start, counted by the budget."""
    async with oidc_app(FakeIdp()) as (live, browser):
        _issue_setup_token(live)
        missing = await _start(browser)
        wrong = await _start(browser, setup_token="not-the-token")
    assert missing.status_code == 403
    assert missing.json()["code"] == error_codes.AUTH_SETUP_TOKEN_INVALID
    # The budget shuts after the first failure, as it does for the password
    # routes (T8): the next attempt is throttled before the token is looked at.
    assert wrong.status_code == 429
    assert wrong.json()["code"] == error_codes.AUTH_TOO_MANY_ATTEMPTS
    (failure,) = await _events(audit.SETUP_FAILED)
    assert failure.target == "/auth/oidc/start"
    (throttled,) = await _events(audit.LOGIN_THROTTLED)
    assert throttled.target == "/auth/oidc/start"
    assert getattr(live.state, BUDGET_ATTR).failures == 1
    async with get_sessionmaker()() as session:
        assert (await session.execute(select(OidcLogin))).scalars().all() == []


async def test_start_builds_the_provider_url_from_discovery_and_binds_the_browser():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
    assert started.status_code == 200
    url = started.json()["authorization_url"]
    assert url.startswith(f"{ISSUER}/authorize?")
    params = _params(url)
    assert params["response_type"] == "code"
    assert params["client_id"] == CLIENT_ID
    # The callback is built from PUBLIC_BASE_URL, never from Host (§5.6).
    assert params["redirect_uri"] == f"{BASE}/api/auth/oidc/callback"
    assert params["scope"] == oidc.SCOPES
    assert params["code_challenge_method"] == "S256"
    assert len(params["state"]) >= 32 and len(params["nonce"]) >= 16
    (cookie,) = _set_cookies(started)
    assert cookie.startswith(PLAIN_OIDC_COOKIE_NAME + "=")
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower() and "Max-Age=600" in cookie
    assert "GET /.well-known/openid-configuration" in fake.calls
    async with get_sessionmaker()() as session:
        (row,) = (await session.execute(select(OidcLogin))).scalars().all()
    assert row.claiming is True and row.used_at is None
    # The token was matched, not consumed: only the callback's bind consumes it.
    assert setup_token_state(live).digest is not None


async def test_a_hostile_origin_cannot_start_a_login():
    """A hostile page cannot start a login the owner did not ask for (§5.6, CSRF):
    the POST carries the page's Origin and the ingress guard refuses it before
    the route runs — no transaction, no budget hit. (An *absent* Origin passes
    with no session, as on every family-3 action since #186 call (a).)"""
    async with oidc_app(FakeIdp()) as (live, browser):
        token = _issue_setup_token(live)
        response = await browser.post(
            "/auth/oidc/start",
            json={"setup_token": token},
            headers={"Origin": "https://evil.test"},
        )
    assert response.status_code == 403
    assert response.json()["code"] == error_codes.INGRESS_ORIGIN_NOT_ALLOWED
    async with get_sessionmaker()() as session:
        assert (await session.execute(select(OidcLogin))).scalars().all() == []
    budget = getattr(live.state, BUDGET_ATTR, None)
    assert budget is None or budget.failures == 0


async def test_start_ignores_a_forwarded_host_for_the_callback():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await browser.post(
            "/auth/oidc/start",
            json={"setup_token": token},
            headers={
                "Origin": "http://localhost",
                "Host": "localhost",
                "X-Forwarded-Host": "evil.test",
            },
        )
    assert started.status_code == 200, started.text
    assert _params(started.json()["authorization_url"])["redirect_uri"].startswith(BASE)


# --- the claim and the login -----------------------------------------------------------


async def test_the_first_login_with_the_setup_token_binds_the_owner():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        done = await _sign_in(fake, browser, setup_token=token, name="The Owner")
        assert _auth_error(done) is None
        assert done.headers["location"] == BASE + "/"
        cookies = _set_cookies(done)
        assert any(c.startswith(PLAIN_COOKIE_NAME + "=") and "HttpOnly" in c for c in cookies)
        assert any(c.startswith(PLAIN_OIDC_COOKIE_NAME + "=") and "Max-Age=0" in c for c in cookies)
        # The browser is the owner now, and the token is spent.
        session = await browser.get("/auth/session")
        assert session.json()["state"] == "owner"
        assert session.json()["csrf_token"]
        assert setup_token_state(live).digest is None
    owner = await _owner()
    assert (owner.oidc_issuer, owner.oidc_subject) == (ISSUER, OWNER_SUB)
    assert owner.claimed_at is not None
    assert owner.display_name == "owner@example.test"
    (claimed,) = await _events(audit.SETUP_CLAIMED)
    assert claimed.target == "/auth/oidc/callback" and claimed.detail == "via=oidc"
    assert claimed.principal_kind == "owner"
    # What the provider was sent: the PKCE verifier that matches the challenge,
    # the canonical redirect URI, and the client secret as Basic auth.
    (exchange,) = fake.token_requests
    assert exchange["redirect_uri"] == f"{BASE}/api/auth/oidc/callback"
    assert exchange["grant_type"] == "authorization_code"
    assert exchange["code_verifier"]
    assert exchange["_authorization"].startswith("Basic ")


async def test_the_callback_redirects_to_public_base_url_whatever_the_host():
    """§5.6 proxy trust: the self redirect names PUBLIC_BASE_URL, not the
    request's Host — reached here by an allowed loopback name."""
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
        params = _params(started.json()["authorization_url"])
        fake.next_token = {"id_token": fake.issue(nonce=params["nonce"])}
        response = await browser.get(
            "/auth/oidc/callback",
            params={"state": params["state"], "code": FakeIdp.GOOD_CODE},
            headers={"Host": "localhost", "X-Forwarded-Host": "evil.test"},
        )
    assert response.status_code == 302
    assert response.headers["location"] == BASE + "/"


async def test_a_bound_owner_signs_in_again_without_the_token():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        assert _auth_error(await _sign_in(fake, browser, setup_token=token)) is None
        async with fresh_browser(live) as second:
            again = await _sign_in(fake, second, email="renamed@example.test")
            assert _auth_error(again) is None
            assert (await second.get("/auth/session")).json()["state"] == "owner"
    assert await _session_count() == 2
    (login,) = await _events(audit.LOGIN_SUCCEEDED)
    assert login.target == "/auth/oidc/callback" and login.detail == "via=oidc"
    assert (await _owner()).display_name == "renamed@example.test"


async def test_a_different_identity_is_refused_with_an_audit_row_and_no_session():
    """T6: the binding is `(issuer, subject)`; the same email on another subject
    is a stranger."""
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        assert _auth_error(await _sign_in(fake, browser, setup_token=token)) is None
        async with fresh_browser(live) as other:
            stranger = await _sign_in(fake, other, sub=STRANGER_SUB, email="owner@example.test")
            assert _auth_error(stranger) == CallbackError.IDENTITY_REFUSED
            assert not any(c.startswith(PLAIN_COOKIE_NAME + "=") for c in _set_cookies(stranger))
            assert (await other.get("/auth/session")).json()["state"] == "anonymous"
    assert await _session_count() == 1
    (refused,) = await _events(audit.OIDC_IDENTITY_REFUSED)
    assert refused.detail == f"subject={STRANGER_SUB}"
    assert refused.target == "/auth/oidc/callback"
    assert (await _owner()).oidc_subject == OWNER_SUB


async def test_an_unbound_owner_without_the_token_at_start_cannot_bind_at_the_callback():
    """The state axis: bound at start, unbound by a rebind before the callback.
    The transaction did not carry the token, so the identity is not bound."""
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        assert _auth_error(await _sign_in(fake, browser, setup_token=token)) is None
        async with fresh_browser(live) as second:
            started = await _start(second)
            params = _params(started.json()["authorization_url"])
            async with get_sessionmaker()() as session:
                await oidc.recovery_rebind_oidc(session)
            fake.next_token = {"id_token": fake.issue(nonce=params["nonce"])}
            response = await _callback(second, state=params["state"])
            assert _auth_error(response) == CallbackError.SETUP_REQUIRED
    assert (await _owner()).oidc_subject is None


async def test_the_binding_is_the_issuer_too_not_the_subject_alone():
    """The value axis of the binding: the same subject asserted by a different
    issuer — the operator repointed `OIDC_ISSUER` at another provider whose
    subjects happen to collide — is not the owner."""
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        assert _auth_error(await _sign_in(fake, browser, setup_token=token)) is None
        other_idp = FakeIdp()
        other_idp.issuer = "https://other-idp.test"
        moved = OidcProvider(
            issuer=other_idp.issuer,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            public_base_url=BASE,
            http_client=AsyncClient(transport=httpx.MockTransport(other_idp.handler)),
        )
        setattr(live.state, OIDC_PROVIDER_ATTR, moved)
        async with fresh_browser(live) as second:
            started = await _start(second)
            params = _params(started.json()["authorization_url"])
            other_idp.next_token = {
                "id_token": other_idp.issue(sub=OWNER_SUB, nonce=params["nonce"])
            }
            response = await _callback(second, state=params["state"])
            assert _auth_error(response) == CallbackError.IDENTITY_REFUSED
    assert await _session_count() == 1
    (refused,) = await _events(audit.OIDC_IDENTITY_REFUSED)
    assert refused.detail == f"subject={OWNER_SUB}"


async def test_an_id_token_signed_with_the_client_secret_is_refused():
    """Algorithm confusion: an HMAC-signed token keyed by the client secret must
    never verify — only the provider's asymmetric keys may sign an id_token."""
    from joserfc.jwk import OctKey

    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
        params = _params(started.json()["authorization_url"])
        forged = jwt.encode(
            {"alg": "HS256"},
            {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "sub": OWNER_SUB,
                "nonce": params["nonce"],
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
            },
            OctKey.import_key(CLIENT_SECRET),
        )
        fake.next_token = {"id_token": forged}
        response = await _callback(browser, state=params["state"])
        assert _auth_error(response) == CallbackError.FAILED
    assert await _session_count() == 0
    assert (await _owner()).claimed_at is None


# --- the transaction ---------------------------------------------------------------------


async def test_the_callback_needs_a_live_transaction_and_the_binding_cookie():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
        params = _params(started.json()["authorization_url"])
        fake.next_token = {"id_token": fake.issue(nonce=params["nonce"])}
        # The right state from a browser without the cookie names nothing, and
        # leaves the transaction untouched.
        async with fresh_browser(live) as other:
            refused = await _callback(other, state=params["state"])
            assert _auth_error(refused) == CallbackError.EXPIRED
        binding_cookie = browser.cookies.get(PLAIN_OIDC_COOKIE_NAME)
        assert binding_cookie
        # The transaction is still live for the right browser…
        assert _auth_error(await _callback(browser, state=params["state"])) is None
        # …and spent afterwards: a replay names nothing, even one that re-presents
        # the binding cookie the success cleared (a client that keeps it). Every
        # refusal also clears the cookie, which is why these follow the success.
        browser.cookies.set(PLAIN_OIDC_COOKIE_NAME, binding_cookie)
        replay = await _callback(browser, state=params["state"])
        assert _auth_error(replay) == CallbackError.EXPIRED
        assert not any(c.startswith(PLAIN_COOKIE_NAME + "=") for c in _set_cookies(replay))
        unknown = await _callback(browser, state="not-a-state")
        assert _auth_error(unknown) == CallbackError.EXPIRED
        missing = await _callback(browser, state=None)
        assert _auth_error(missing) == CallbackError.EXPIRED
    assert await _session_count() == 1
    failed = await _events(audit.OIDC_LOGIN_FAILED)
    assert len(failed) == 4 and {event.detail for event in failed} == {"no live transaction"}


async def test_an_expired_transaction_is_refused():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
        params = _params(started.json()["authorization_url"])
        async with get_sessionmaker()() as session:
            await session.execute(
                update(OidcLogin).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
            await session.commit()
        fake.next_token = {"id_token": fake.issue(nonce=params["nonce"])}
        assert _auth_error(await _callback(browser, state=params["state"])) == CallbackError.EXPIRED
    assert fake.token_requests == []


async def test_the_owner_cancelling_at_the_provider_spends_the_transaction():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
        state = _params(started.json()["authorization_url"])["state"]
        fake.next_token = {"id_token": "would-not-be-verified"}
        # The error wins even when a code rides beside it: no exchange is attempted.
        denied = await _callback(browser, state=state, error="access_denied")
        assert _auth_error(denied) == CallbackError.DENIED
        replay = await _callback(browser, state=state, code=None, error="access_denied")
        assert _auth_error(replay) == CallbackError.EXPIRED
    (event, _) = await _events(audit.OIDC_LOGIN_FAILED)
    assert event.detail == "provider_error=access_denied"
    assert fake.token_requests == []


# --- the id_token ------------------------------------------------------------------------


_NOW = int(time.time())


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"nonce": "some-other-nonce"}, id="nonce"),
        pytest.param({"aud": "another-client"}, id="audience"),
        pytest.param({"iss": "https://other-idp.test"}, id="issuer"),
        pytest.param({"exp": _NOW - 600}, id="expired"),
        pytest.param({"key": "other"}, id="signature"),
        pytest.param({"sub": None}, id="no-subject"),
        # The shapes that name no client, no login, or no issue time (Codex
        # #209 round 1, f2; OpenID Connect Core §2 and §3.1.3.7 steps 3–5, 9–10):
        # `nonce` is *the* string, not a list holding it or a null; `aud` is
        # exactly this client — an additional audience is untrusted whatever
        # `azp` says — and `azp`, when present, is this client; `iat` is
        # required and, like `exp` and `nbf`, a number.
        pytest.param({"nonce": lambda expected: [expected]}, id="nonce-list"),
        pytest.param({"nonce": None}, id="nonce-null"),
        pytest.param({"omit": ("nonce",)}, id="nonce-missing"),
        pytest.param(
            {"aud": [CLIENT_ID, "another-client"], "azp": "another-client"},
            id="extra-audience-other-azp",
        ),
        pytest.param(
            {"aud": [CLIENT_ID, "another-client"], "azp": CLIENT_ID}, id="extra-audience-own-azp"
        ),
        pytest.param({"aud": [CLIENT_ID, "another-client"]}, id="extra-audience-no-azp"),
        pytest.param({"aud": ["another-client"]}, id="audience-list-other"),
        pytest.param({"aud": []}, id="audience-empty"),
        pytest.param({"aud": [CLIENT_ID, 7]}, id="audience-mixed-types"),
        pytest.param({"omit": ("aud",)}, id="audience-missing"),
        pytest.param({"azp": "another-client"}, id="azp-other"),
        pytest.param({"azp": [CLIENT_ID]}, id="azp-list"),
        pytest.param({"azp": None}, id="azp-null"),
        pytest.param({"omit": ("iat",)}, id="iat-missing"),
        pytest.param({"iat": None}, id="iat-null"),
        pytest.param({"iat": str(_NOW)}, id="iat-string"),
        pytest.param({"iat": True}, id="iat-bool"),
        pytest.param({"iat": _NOW + 3600}, id="iat-future"),
        pytest.param({"omit": ("exp",)}, id="exp-missing"),
        pytest.param({"exp": str(_NOW + 300)}, id="exp-string"),
        pytest.param({"nbf": _NOW + 3600}, id="nbf-future"),
        pytest.param({"nbf": "soon"}, id="nbf-string"),
        pytest.param({"iss": [ISSUER]}, id="issuer-list"),
        pytest.param({"omit": ("iss",)}, id="issuer-missing"),
        pytest.param({"sub": ""}, id="subject-empty"),
        pytest.param({"sub": 12345}, id="subject-number"),
        # A NumericDate is a JSON number, and JSON has no NaN or Infinity (RFC
        # 7519 §2, RFC 8259 §6); Python's parser admits them, and every clock
        # comparison against NaN is false (Codex #209 round 2, f3).
        pytest.param({"exp": float("nan")}, id="exp-nan"),
        pytest.param({"exp": float("inf")}, id="exp-inf"),
        pytest.param({"exp": float("-inf")}, id="exp-neg-inf"),
        pytest.param({"iat": float("nan")}, id="iat-nan"),
        pytest.param({"iat": float("inf")}, id="iat-inf"),
        pytest.param({"iat": float("-inf")}, id="iat-neg-inf"),
        pytest.param({"nbf": float("nan")}, id="nbf-nan"),
        pytest.param({"nbf": float("inf")}, id="nbf-inf"),
        pytest.param({"nbf": float("-inf")}, id="nbf-neg-inf"),
    ],
)
async def test_an_id_token_that_fails_a_check_opens_no_session(tamper):
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
        params = _params(started.json()["authorization_url"])
        kwargs = dict(tamper)
        if kwargs.get("key") == "other":
            kwargs["key"] = fake.other_key
        nonce = kwargs.pop("nonce", params["nonce"])
        if callable(nonce):
            nonce = nonce(params["nonce"])
        fake.next_token = {"id_token": fake.issue(nonce=nonce, **kwargs)}
        response = await _callback(browser, state=params["state"])
        assert _auth_error(response) == CallbackError.FAILED
        assert not any(c.startswith(PLAIN_COOKIE_NAME + "=") for c in _set_cookies(response))
    assert await _session_count() == 0
    assert (await _owner()).claimed_at is None
    (failed,) = await _events(audit.OIDC_LOGIN_FAILED)
    # One validator speaks for every claim (the `sub` check included).
    assert failed.detail == "id_token_rejected"


@pytest.mark.parametrize(
    "shape",
    [
        pytest.param({"aud": [CLIENT_ID]}, id="single-audience-as-list"),
        pytest.param({"azp": CLIENT_ID}, id="azp-this-client"),
        pytest.param({"aud": [CLIENT_ID], "azp": CLIENT_ID}, id="list-audience-with-azp"),
        pytest.param({"nbf": _NOW - 5}, id="nbf-past"),
    ],
)
async def test_the_claim_shapes_real_providers_send_are_accepted(shape):
    """The other half of the matrix — the state axis of the audience: one
    audience as a string (Keycloak), as a single-element array, with `azp`
    naming this client (Google). Strictness must not refuse a conforming
    provider."""
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        done = await _sign_in(fake, browser, setup_token=token, **shape)
        assert _auth_error(done) is None
        assert (await browser.get("/auth/session")).json()["state"] == "owner"
    assert await _session_count() == 1


def test_the_claim_validator_holds_the_clock_leeway_at_its_edges():
    """The time boundaries, driven with a pinned clock: `exp` may be up to the
    leeway in the past, `iat` and `nbf` up to the leeway in the future, and one
    second beyond each is refused."""
    from app.services.oidc import CLOCK_LEEWAY, OidcLoginRefused, validate_id_token_claims

    now = 1_800_000_000

    def check(**overrides) -> None:
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": OWNER_SUB,
            "iat": now,
            "exp": now + 300,
            "nonce": "n",
            **overrides,
        }
        validate_id_token_claims(claims, issuer=ISSUER, client_id=CLIENT_ID, nonce="n", now=now)

    check(exp=now - CLOCK_LEEWAY)
    check(iat=now + CLOCK_LEEWAY)
    check(nbf=now + CLOCK_LEEWAY)
    for edge in (
        {"exp": now - CLOCK_LEEWAY - 1},
        {"iat": now + CLOCK_LEEWAY + 1},
        {"nbf": now + CLOCK_LEEWAY + 1},
    ):
        with pytest.raises(OidcLoginRefused) as refused:
            check(**edge)
        assert refused.value.code == CallbackError.FAILED


def test_the_claim_validator_admits_only_finite_numeric_dates():
    """The value domain, not the Python type (Codex #209 round 2, f3): NaN and
    the infinities are floats a permissive parser hands over, and a comparison
    against NaN is always false, so the predicate names the domain — a finite
    number. Integers stay on their own branch: a huge one is a valid instant,
    and `math.isfinite` on it would raise rather than answer."""
    from app.services.oidc import OidcLoginRefused, validate_id_token_claims

    now = 1_800_000_000

    def check(**overrides) -> None:
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": OWNER_SUB,
            "iat": now,
            "exp": now + 300,
            "nonce": "n",
            **overrides,
        }
        validate_id_token_claims(claims, issuer=ISSUER, client_id=CLIENT_ID, nonce="n", now=now)

    check(exp=10**400)
    check(iat=-(10**400), nbf=-(10**400))
    check(exp=float(now + 300), iat=float(now))
    for claim in ("exp", "iat", "nbf"):
        for value in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(OidcLoginRefused) as refused:
                check(**{claim: value})
            assert refused.value.code == CallbackError.FAILED, (claim, value)


async def test_a_provider_that_refuses_the_code_opens_no_session():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
        state = _params(started.json()["authorization_url"])["state"]
        response = await _callback(browser, state=state, code="a-code-the-provider-rejects")
        assert _auth_error(response) == CallbackError.FAILED
    assert await _session_count() == 0


async def test_a_provider_down_during_the_exchange_fails_the_login_only():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        started = await _start(browser, setup_token=token)
        state = _params(started.json()["authorization_url"])["state"]
        fake.network_down = True
        response = await _callback(browser, state=state)
        assert _auth_error(response) == CallbackError.FAILED
    (failed,) = await _events(audit.OIDC_LOGIN_FAILED)
    assert failed.detail == "provider_unavailable"


# --- safe failure -----------------------------------------------------------------------


async def test_a_provider_down_at_start_is_503_and_existing_sessions_survive():
    """§5.6 safe failure: an outage fails new logins with a clear status and
    touches nothing the owner already holds."""
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        assert _auth_error(await _sign_in(fake, browser, setup_token=token)) is None
        # A second process, so to speak: no cached discovery, and the provider
        # has gone away.
        fresh = OidcProvider.from_settings(
            Settings(
                auth_mode="oidc",
                oidc_issuer=ISSUER,
                oidc_client_id=CLIENT_ID,
                oidc_client_secret=CLIENT_SECRET,
                public_base_url=BASE,
            ),
            http_client=AsyncClient(transport=httpx.MockTransport(fake.handler)),
        )
        setattr(live.state, OIDC_PROVIDER_ATTR, fresh)
        fake.network_down = True
        async with fresh_browser(live) as other:
            started = await _start(other)
        assert started.status_code == 503
        assert started.json()["code"] == error_codes.AUTH_OIDC_PROVIDER_UNAVAILABLE
        assert (await browser.get("/auth/session")).json()["state"] == "owner"
        assert (await browser.get("/kits")).status_code == 200


async def test_a_discovery_document_with_another_issuer_is_refused():
    fake = FakeIdp()
    fake.issuer = "https://someone-else.test"
    async with oidc_app(fake) as (live, browser):
        _issue_setup_token(live)
        started = await _start(browser, setup_token="irrelevant")
    assert started.status_code == 503
    assert started.json()["code"] == error_codes.AUTH_OIDC_PROVIDER_UNAVAILABLE


async def test_warm_up_never_raises():
    fake = FakeIdp()
    fake.network_down = True
    provider = OidcProvider(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        public_base_url=BASE,
        http_client=AsyncClient(transport=httpx.MockTransport(fake.handler)),
    )
    assert await provider.warm_up() is False
    fake.network_down = False
    assert await provider.warm_up() is True


# --- the mode switch (T7's sibling; Codex #209 round 1, f1) ------------------------------


async def _claim_locally(anon_client) -> str:
    """Claim the shipped local-mode app through the password flow; returns the
    raw session cookie that browser now holds, proven live on a collection route."""
    token = setup_token_state(local_app).issue()
    claimed = await anon_client.post(
        "/auth/setup",
        json={"token": token, "password": "correct-horse-battery-staple"},
        headers={"Origin": "http://test"},
    )
    assert claimed.status_code == 200, claimed.text
    assert (await anon_client.get("/kits")).status_code == 200
    return anon_client.cookies[PLAIN_COOKIE_NAME]


async def test_a_local_mode_session_is_not_the_owner_in_oidc_mode(anon_client):
    """A browser session is authority only in the mode that minted it. The
    instance switched to OIDC mode with the owner unbound: the retained
    password-flow cookie is not an owner, `GET /auth/session` reports
    `unclaimed` (the setup token is the gate), and a collection route is 401."""
    raw = await _claim_locally(anon_client)
    async with oidc_app(FakeIdp()) as (_, browser):
        browser.cookies.set(PLAIN_COOKIE_NAME, raw)
        assert (await browser.get("/auth/session")).json()["state"] == "unclaimed"
        assert (await browser.get("/kits")).status_code == 401


async def test_an_oidc_session_is_not_the_owner_in_local_mode(anon_client):
    """The reverse state: bound and signed in at the provider, then the instance
    switched back to local mode. The owner is claimed but holds no password, so
    the instance is `anonymous`, and the provider-minted cookie opens nothing."""
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        assert _auth_error(await _sign_in(fake, browser, setup_token=token)) is None
        raw = browser.cookies[PLAIN_COOKIE_NAME]
    anon_client.cookies.set(PLAIN_COOKIE_NAME, raw)
    assert (await anon_client.get("/auth/session")).json()["state"] == "anonymous"
    assert (await anon_client.get("/kits")).status_code == 401


async def test_starting_in_the_other_mode_revokes_its_sessions_for_good(anon_client):
    """The switch is durable, not a per-request refusal alone: the start in the
    new mode revokes every session the old one minted, with an audit row, so
    switching back does not resurrect a cookie the operator was told is signed
    out (docs/operations.md, "sessions are signed out")."""
    await _claim_locally(anon_client)
    async with oidc_app(FakeIdp()) as (live, _):
        async with live.router.lifespan_context(live):
            pass
    async with get_sessionmaker()() as session:
        (row,) = (await session.execute(select(SessionRow))).scalars().all()
    assert row.revoked_at is not None
    (changed,) = await _events(audit.AUTH_MODE_CHANGED)
    assert changed.detail == "auth_mode=oidc sessions_revoked=1"
    assert changed.client_address == "host"
    (revoked,) = await _events(audit.SESSIONS_REVOKED)
    assert revoked.detail == "count=1"
    # Back in local mode — the shipped app — the cookie is dead, not dormant.
    assert (await anon_client.get("/auth/session")).json()["state"] == "anonymous"
    assert (await anon_client.get("/kits")).status_code == 401


async def test_a_restart_in_the_same_mode_signs_nobody_out(anon_client):
    await _claim_locally(anon_client)
    live = create_app(Settings(), authorization=True)
    async with live.router.lifespan_context(live):
        pass
    assert (await anon_client.get("/kits")).status_code == 200
    assert await _events(audit.AUTH_MODE_CHANGED) == []
    assert await _events(audit.SESSIONS_REVOKED) == []


# --- rebind (T7) -------------------------------------------------------------------------


async def test_rebind_revokes_every_session_and_the_next_login_needs_the_token():
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        assert _auth_error(await _sign_in(fake, browser, setup_token=token)) is None
        assert (await browser.get("/kits")).status_code == 200
        async with get_sessionmaker()() as session:
            revoked = await oidc.recovery_rebind_oidc(session)
        assert revoked == 1
        # The old cookie is dead and the instance is unbound; a login without
        # the token is refused, and a *different* identity with the new token
        # becomes the owner — the recovery path.
        assert (await browser.get("/kits")).status_code == 401
        assert (await browser.get("/auth/session")).json()["state"] == "unclaimed"
        assert (await _start(browser)).status_code == 403
        setattr(live.state, BUDGET_ATTR, FailureBudget())  # past the throttle; T8 is above
        new_token = _issue_setup_token(live)
        rebound = await _sign_in(fake, browser, sub=STRANGER_SUB, setup_token=new_token)
        assert _auth_error(rebound) is None
    owner = await _owner()
    assert owner.oidc_subject == STRANGER_SUB and owner.claimed_at is not None
    assert await _events(audit.OIDC_REBIND)
    (run,) = await _events(audit.RECOVERY_RUN)
    assert run.target == "recovery rebind-oidc" and run.detail == "sessions_revoked=1"


async def test_the_recovery_command_rebinds(capsys):
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        assert _auth_error(await _sign_in(fake, browser, setup_token=token)) is None
    import asyncio

    def run():
        return recovery.main(["rebind-oidc"])

    assert await asyncio.to_thread(run) == 0
    assert "OIDC binding cleared. 1 session(s) revoked." in capsys.readouterr().out
    assert (await _owner()).oidc_subject is None


# --- leakage (T10) -----------------------------------------------------------------------


async def test_nothing_secret_reaches_the_log_or_the_audit_rows(monkeypatch):
    """The client secret, the authorization code and the id_token never appear
    in a log line or an audit row, across a success and every failure kind."""
    records: list[str] = []

    class Recorder:
        def warning(self, msg, *args, **kw):
            records.append(msg % args if args else str(msg))

        info = error = debug = warning

    monkeypatch.setattr(oidc, "log", Recorder())
    fake = FakeIdp()
    async with oidc_app(fake) as (live, browser):
        token = _issue_setup_token(live)
        good = await _sign_in(fake, browser, setup_token=token)
        assert _auth_error(good) is None
        async with fresh_browser(live) as other:
            started = await _start(other)
            params = _params(started.json()["authorization_url"])
            bad_token = fake.issue(nonce="wrong", sub=OWNER_SUB)
            fake.next_token = {"id_token": bad_token}
            failed = await _callback(other, state=params["state"])
            assert _auth_error(failed) == CallbackError.FAILED
            rejected = await _callback(other, state="zzz", code="leaky-code")
            assert _auth_error(rejected) == CallbackError.EXPIRED
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(AuditEvent))).scalars()
        details = [row.detail or "" for row in rows]
    haystack = "\n".join(records + details)
    for secret in (CLIENT_SECRET, FakeIdp.GOOD_CODE, "leaky-code", bad_token):
        assert secret not in haystack


async def test_the_login_table_is_never_portable():
    from app.services.portability.spec import TABLE_SPECS

    assert OidcLogin not in {spec.model for spec in TABLE_SPECS}
    assert json  # the fake's documents are JSON; the spec never lists this table
