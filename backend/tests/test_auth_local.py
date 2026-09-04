"""Local owner authentication — the flows (§5.5 families 2–3, §5.6; §5.8 T4/T7/T8/T11;
M6-3, #188).

These drive the **shipped** app (`app`, default-deny since M6-3) as a real
anonymous browser: `anon_client` clears the suite's injected owner, so the
principal comes from the session cookie the flows set. The setup token is issued
onto `app.state` here rather than read from a log line (the lifespan announce does
not run under the in-memory transport); `conftest` resets the token and the
failure budget between tests.

Login and setup happen with no cookie — the SPA shows those screens only when
there is no valid session — so tests exercise them through a `fresh_client` (a
cookie-less browser). Doing them through the client that just claimed, which now
carries the owner cookie, would make the request cookie-borne and CSRF-gated: a
state the real flow never reaches.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app import error_codes
from app.auth import credentials
from app.auth.budget import BASE_DELAY, FailureBudget
from app.auth.sessions import (
    CSRF_HEADER,
    PLAIN_COOKIE_NAME,
    SECURE_COOKIE_NAME,
    SESSION_ABSOLUTE,
)
from app.auth.setup_token import setup_token_state
from app.config import Settings
from app.db import get_sessionmaker
from app.main import app, create_app
from app.models import AuditEvent, Owner
from app.models import Session as SessionRow
from app.routers.auth import BUDGET_ATTR
from app.services import audit

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery-staple"
ORIGIN = {"Origin": "http://test"}  # same-origin: base_url is http://test


def _issue_setup_token() -> str:
    return setup_token_state(app).issue()


def _reset_budget() -> None:
    setattr(app.state, BUDGET_ATTR, FailureBudget())


@asynccontextmanager
async def fresh_client():
    """A cookie-less client on the shipped app — a real anonymous browser."""
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as c:
        yield c


async def _claim(client, *, password: str = PASSWORD) -> str:
    """Claim the (reset-to-unclaimed) instance and return the CSRF token; the
    client keeps the session cookie."""
    token = _issue_setup_token()
    resp = await client.post(
        "/auth/setup", json={"token": token, "password": password}, headers=ORIGIN
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]


async def _audit_count(event_type: str) -> int:
    async with get_sessionmaker()() as session:
        return await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == event_type)
        )


# --- family 2: GET /auth/session ------------------------------------------------


async def test_session_reports_unclaimed_then_owner(anon_client):
    unclaimed = await anon_client.get("/auth/session")
    assert unclaimed.status_code == 200
    body = unclaimed.json()
    assert body["state"] == "unclaimed"
    assert body["csrf_token"] is None
    # It carries what a login screen needs and nothing else — no version.
    assert body["interface_language"] and body["formatting_locale"]
    assert "version" not in body

    csrf = await _claim(anon_client)
    owner_view = await anon_client.get("/auth/session")
    assert owner_view.json()["state"] == "owner"
    # The CSRF token is stable per session, so the one setup returned still matches.
    assert owner_view.json()["csrf_token"] == csrf


async def test_session_reports_anonymous_when_claimed_without_a_cookie(anon_client):
    await _claim(anon_client)
    async with fresh_client() as fresh:
        body = (await fresh.get("/auth/session")).json()
    assert body["state"] == "anonymous"
    assert body["csrf_token"] is None


async def test_session_carries_no_store(anon_client):
    assert (await anon_client.get("/auth/session")).headers.get("cache-control") == "no-store"


# --- T7: lifecycle --------------------------------------------------------------


async def test_unclaimed_instance_fails_every_collection_route_closed(anon_client):
    assert (await anon_client.get("/kits")).status_code == 401


async def test_setup_claims_opens_a_working_session_and_then_410s(anon_client):
    csrf = await _claim(anon_client)
    # The session works: a read, and a write with the CSRF token.
    assert (await anon_client.get("/kits")).status_code == 200
    created = await anon_client.post(
        "/retailers",
        json={"name": f"Auth Local {uuid.uuid4().hex[:8]}"},
        headers={**ORIGIN, CSRF_HEADER: csrf},
    )
    assert created.status_code == 201
    # A second setup — from a fresh browser, token or not — is 410: claimed.
    async with fresh_client() as other:
        again = await other.post(
            "/auth/setup",
            json={"token": _issue_setup_token(), "password": PASSWORD},
            headers=ORIGIN,
        )
    assert again.status_code == 410
    assert again.json()["code"] == error_codes.AUTH_SETUP_CLAIMED
    assert await _audit_count(audit.SETUP_CLAIMED) == 1


async def test_a_wrong_setup_token_is_403_and_leaves_the_instance_unclaimed(anon_client):
    _issue_setup_token()
    resp = await anon_client.post(
        "/auth/setup", json={"token": "not-the-token", "password": PASSWORD}, headers=ORIGIN
    )
    # 403, not 401: a 401 owes a challenge and this route refuses the only
    # scheme the app speaks (`CredentialRejectedError`; Codex #202 round 2).
    assert resp.status_code == 403
    assert resp.json()["code"] == error_codes.AUTH_SETUP_TOKEN_INVALID
    # Still unclaimed, and no session was opened.
    assert (await anon_client.get("/auth/session")).json()["state"] == "unclaimed"


async def test_setup_token_is_single_use(anon_client):
    token = _issue_setup_token()
    first = await anon_client.post(
        "/auth/setup", json={"token": token, "password": PASSWORD}, headers=ORIGIN
    )
    assert first.status_code == 200
    # The same token again, from a fresh browser: the instance is claimed → 410.
    async with fresh_client() as other:
        again = await other.post(
            "/auth/setup", json={"token": token, "password": PASSWORD}, headers=ORIGIN
        )
    assert again.status_code == 410


async def test_login_then_logout_revokes_the_session(anon_client):
    await _claim(anon_client)  # the instance is now claimed
    async with fresh_client() as c:
        login = await c.post("/auth/login", json={"password": PASSWORD}, headers=ORIGIN)
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        assert (await c.get("/kits")).status_code == 200
        out = await c.post("/auth/logout", headers={**ORIGIN, CSRF_HEADER: csrf})
        assert out.status_code == 204
        # The cookie is cleared and the session revoked: the collection is closed.
        assert (await c.get("/auth/session")).json()["state"] == "anonymous"
        assert (await c.get("/kits")).status_code == 401


async def test_a_wrong_password_is_403(anon_client):
    await _claim(anon_client)
    async with fresh_client() as c:
        resp = await c.post("/auth/login", json={"password": "wrong-password"}, headers=ORIGIN)
    assert resp.status_code == 403
    assert "www-authenticate" not in resp.headers
    assert resp.json()["code"] == error_codes.AUTH_LOGIN_FAILED


async def test_an_expired_session_is_401(anon_client):
    await _claim(anon_client)
    # Age every session past the absolute lifetime, directly in the database.
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(SessionRow))).scalars().all()
        for row in rows:
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert (await anon_client.get("/kits")).status_code == 401


async def test_a_short_password_is_422(anon_client):
    token = _issue_setup_token()
    resp = await anon_client.post(
        "/auth/setup", json={"token": token, "password": "short"}, headers=ORIGIN
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == error_codes.AUTH_PASSWORD_TOO_SHORT
    # The token was NOT consumed by a failed-password setup — retry works.
    assert (await anon_client.get("/auth/session")).json()["state"] == "unclaimed"


# --- T4: CSRF -------------------------------------------------------------------


async def test_a_cookie_write_without_the_csrf_token_is_403(anon_client):
    await _claim(anon_client)
    resp = await anon_client.post("/retailers", json={"name": "No CSRF"}, headers=ORIGIN)
    assert resp.status_code == 403
    assert resp.json()["code"] == error_codes.AUTH_CSRF_FAILED


async def test_a_cookie_write_without_an_origin_is_403(anon_client):
    csrf = await _claim(anon_client)
    resp = await anon_client.post(
        "/retailers", json={"name": "No Origin"}, headers={CSRF_HEADER: csrf}
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == error_codes.AUTH_ORIGIN_REQUIRED


async def test_a_hostile_origin_on_a_cookie_write_is_403(anon_client):
    csrf = await _claim(anon_client)
    resp = await anon_client.post(
        "/retailers",
        json={"name": "Hostile"},
        headers={"Origin": "https://evil.example", CSRF_HEADER: csrf},
    )
    # The ingress guard refuses the hostile origin first (its own code).
    assert resp.status_code == 403
    assert resp.json()["code"] == error_codes.INGRESS_ORIGIN_NOT_ALLOWED


async def test_the_csrf_token_admits_the_write(anon_client):
    csrf = await _claim(anon_client)
    resp = await anon_client.post(
        "/retailers",
        json={"name": f"Good {uuid.uuid4().hex[:8]}"},
        headers={**ORIGIN, CSRF_HEADER: csrf},
    )
    assert resp.status_code == 201


async def test_the_multipart_import_route_needs_the_csrf_token(anon_client):
    """Named individually (§5.8 T4): the CORS-safelistable multipart routes are the
    ones a form could POST cross-site, so the token is required there too."""
    csrf = await _claim(anon_client)
    files = {"file": ("retailers.csv", b"name\nCSRF Import\n", "text/csv")}
    without = await anon_client.post(
        "/import/preview", files=files, data={"mode": "merge"}, headers=ORIGIN
    )
    assert without.status_code == 403
    assert without.json()["code"] == error_codes.AUTH_CSRF_FAILED
    with_token = await anon_client.post(
        "/import/preview",
        files=files,
        data={"mode": "merge"},
        headers={**ORIGIN, CSRF_HEADER: csrf},
    )
    assert with_token.status_code == 200


# --- T8: brute force ------------------------------------------------------------


async def test_repeated_failures_throttle_then_a_success_resets(anon_client):
    await _claim(anon_client)
    # A controllable clock so the test pins the doubling without sleeping.
    now = {"t": 1000.0}
    setattr(app.state, BUDGET_ATTR, FailureBudget(clock=lambda: now["t"]))
    async with fresh_client() as c:
        first = await c.post("/auth/login", json={"password": "nope"}, headers=ORIGIN)
        assert first.status_code == 403  # the failure is recorded, the gate now shut
        throttled = await c.post("/auth/login", json={"password": PASSWORD}, headers=ORIGIN)
        assert throttled.status_code == 429
        assert throttled.headers["retry-after"] == str(int(BASE_DELAY))
        assert throttled.json()["code"] == error_codes.AUTH_TOO_MANY_ATTEMPTS
        # Past the delay, the correct password is accepted and the budget resets.
        now["t"] += BASE_DELAY + 0.01
        ok = await c.post("/auth/login", json={"password": PASSWORD}, headers=ORIGIN)
        assert ok.status_code == 200
    assert app.state.login_budget.failures == 0


async def test_failures_are_audited(anon_client):
    await _claim(anon_client)
    before = await _audit_count(audit.LOGIN_FAILED)
    async with fresh_client() as c:
        await c.post("/auth/login", json={"password": "nope"}, headers=ORIGIN)
    after = await _audit_count(audit.LOGIN_FAILED)
    assert after == before + 1


# --- T11: timing shape ----------------------------------------------------------


async def test_an_unclaimed_login_and_a_wrong_password_are_byte_identical(anon_client):
    """The two failure kinds — no credential at all (unclaimed) and a wrong
    password (claimed) — return the identical status, code and body, so an
    attacker cannot tell one instance state from the other (§5.8 T11). The
    constant-time construction: an unclaimed instance verifies against
    `DUMMY_HASH`, doing the full Argon2 work (asserted directly below)."""
    async with fresh_client() as c0:
        unclaimed = await c0.post("/auth/login", json={"password": PASSWORD}, headers=ORIGIN)
    # The unclaimed attempt recorded a budget failure; clear it so the claimed
    # attempt is judged on its own merits rather than throttled.
    _reset_budget()
    await _claim(anon_client)
    async with fresh_client() as c1:
        wrong = await c1.post("/auth/login", json={"password": "the-wrong-one"}, headers=ORIGIN)
    assert unclaimed.status_code == wrong.status_code == 403
    assert unclaimed.json() == wrong.json()


def test_no_credential_verifies_against_the_dummy_hash(monkeypatch):
    """The code path, not a stopwatch (§5.8 T11): `verify_password(None, ...)` runs
    the real verifier against `DUMMY_HASH` and returns False — it does not
    short-circuit on the absent hash, which is what makes the timing equal. The
    verifier is spied on, so a short-circuit that returns False *without* the
    Argon2 work fails here rather than passing on the answer alone (Codex #200
    round 1, f3: the previous assertion was on the return value only)."""
    seen: list[str] = []
    real_hasher = credentials._hasher

    class SpyingHasher:
        def verify(self, encoded: str, password: str) -> bool:
            seen.append(encoded)
            return real_hasher.verify(encoded, password)

        def __getattr__(self, name):
            return getattr(real_hasher, name)

    monkeypatch.setattr(credentials, "_hasher", SpyingHasher())
    assert credentials.verify_password(None, "anything at all") is False
    assert seen == [credentials.DUMMY_HASH]
    # And a real verifier round-trips, so the False above is a mismatch, not a
    # broken verifier.
    encoded = credentials.hash_password(PASSWORD)
    assert credentials.verify_password(encoded, PASSWORD) is True
    assert credentials.verify_password(encoded, "other") is False


def _spy_compare_digest(monkeypatch) -> list[tuple[str, str]]:
    """Record every constant-time compare so a test can assert the compare *was*
    constant-time — a plain `==` gives the same answers (Codex #200 round 1, f3)."""
    calls: list[tuple[str, str]] = []
    real = credentials.hmac.compare_digest

    def spying(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(credentials.hmac, "compare_digest", spying)
    return calls


def test_opaque_tokens_are_compared_on_their_digests(monkeypatch):
    calls = _spy_compare_digest(monkeypatch)
    token = credentials.new_token()
    expected = credentials.digest(token)
    assert credentials.tokens_match(token, expected) is True
    assert credentials.tokens_match("guess", expected) is False
    # Both compares went through compare_digest, on the digests (fixed length).
    assert calls == [(expected, expected), (credentials.digest("guess"), expected)]


def test_csrf_token_is_bound_to_the_session(monkeypatch):
    calls = _spy_compare_digest(monkeypatch)
    a, b = credentials.new_token(), credentials.new_token()
    token_a = credentials.csrf_token_for(a)
    assert credentials.csrf_tokens_match(token_a, a) is True
    # A token for one session does not validate another.
    assert credentials.csrf_tokens_match(token_a, b) is False
    assert credentials.csrf_tokens_match(None, a) is False
    # Two compares, each constant-time and against the session-bound value; the
    # None case never reaches the compare.
    assert calls == [(token_a, token_a), (token_a, credentials.csrf_token_for(b))]


# --- the cookie -----------------------------------------------------------------


async def test_the_session_cookie_is_httponly_and_lax(anon_client):
    raw_token = _issue_setup_token()
    resp = await anon_client.post(
        "/auth/setup", json={"token": raw_token, "password": PASSWORD}, headers=ORIGIN
    )
    set_cookie = resp.headers["set-cookie"]
    # Plain HTTP (no PUBLIC_BASE_URL): the non-Secure name, HttpOnly, Lax.
    assert PLAIN_COOKIE_NAME in set_cookie
    assert SECURE_COOKIE_NAME not in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert f"Max-Age={int(SESSION_ABSOLUTE.total_seconds())}" in set_cookie


class _LogRecorder:
    """Stands in for the `plamotrack.auth` module logger. Not caplog: the session
    conftest runs alembic, whose `fileConfig` disables every already-imported app
    logger, so records from app modules never reach pytest's handler in this
    suite (`test_integrity.py` has the same note). Patching the logger asserts
    the call itself, which is the named control."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def warning(self, msg, *args) -> None:
        self.warnings.append(msg % args)

    def info(self, msg, *args) -> None:
        self.infos.append(msg % args)


async def _lifespan_log(monkeypatch, *, public_base_url: str) -> _LogRecorder:
    """Enter the lifespan of an auth-enabled app built from `public_base_url` and
    return what it logged through `sessions.log` and `setup_token.log`. The
    startup announcement is the operator's only tell of the cookie mode (§5.6;
    #188)."""
    from app.auth import sessions, setup_token

    recorder = _LogRecorder()
    monkeypatch.setattr(sessions, "log", recorder, raising=False)
    monkeypatch.setattr(setup_token, "log", recorder, raising=False)
    live = create_app(Settings(public_base_url=public_base_url), authorization=True)
    async with live.router.lifespan_context(live):
        pass
    return recorder


async def test_plain_http_cookie_mode_is_announced_at_startup(anon_client, monkeypatch):
    """On plain http the session cookie cannot be `Secure`; the startup log says
    so, whether or not the instance is claimed (Codex #200 round 1, f1)."""
    log = await _lifespan_log(monkeypatch, public_base_url="")
    assert [m for m in log.warnings if "NOT Secure" in m and PLAIN_COOKIE_NAME in m], log.warnings
    # And on a claimed instance too — the warning is not the setup-token banner,
    # which a claimed instance no longer prints.
    await _claim(anon_client)
    log = await _lifespan_log(monkeypatch, public_base_url="")
    assert [m for m in log.warnings if "NOT Secure" in m and PLAIN_COOKIE_NAME in m], log.warnings
    assert not any("setup token" in m for m in log.warnings), log.warnings


async def test_https_cookie_mode_is_not_warned_about(monkeypatch):
    log = await _lifespan_log(monkeypatch, public_base_url="https://plamotrack.example")
    assert not any(PLAIN_COOKIE_NAME in m for m in log.warnings), log.warnings
    assert any(SECURE_COOKIE_NAME in m for m in log.infos), log.infos


# --- recovery (T13; the host-side break-glass, never an HTTP route) --------------


async def test_recovery_reset_password_claims_and_revokes(anon_client):
    from app.services.auth import recovery_reset_password

    csrf = await _claim(anon_client)
    # A live session before recovery; a write works.
    assert (
        await anon_client.post(
            "/retailers", json={"name": "Before Recovery"}, headers={**ORIGIN, CSRF_HEADER: csrf}
        )
    ).status_code == 201

    # Pin the claim time: recovery on a claimed instance must not re-stamp it
    # (Codex #200 round 1, f3 — an unconditional re-stamp survived the old test).
    claimed_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    async with get_sessionmaker()() as session:
        owner_before = (await session.execute(select(Owner))).scalar_one()
        owner_before.claimed_at = claimed_at
        await session.commit()

    revoked_before = await _audit_count(audit.SESSIONS_REVOKED)
    async with get_sessionmaker()() as session:
        revoked = await recovery_reset_password(session, password="a-brand-new-passphrase")
    assert revoked == 1  # the setup session

    async with get_sessionmaker()() as session:
        owner_after = (await session.execute(select(Owner))).scalar_one()
        assert owner_after.claimed_at == claimed_at
        # The bulk revocation is its own audit event (#188: "session revoked"),
        # beside the record that recovery ran (f2).
        events = (
            (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.event_type == audit.SESSIONS_REVOKED)
                )
            )
            .scalars()
            .all()
        )
        assert len(events) == revoked_before + 1
        assert events[-1].detail == "count=1"
        assert events[-1].target == "recovery reset-password"
        assert events[-1].client_address == "host"
    assert await _audit_count(audit.RECOVERY_RUN) == 1

    # The old cookie no longer authenticates.
    assert (await anon_client.get("/kits")).status_code == 401
    # The new password logs in.
    async with fresh_client() as c:
        login = await c.post(
            "/auth/login", json={"password": "a-brand-new-passphrase"}, headers=ORIGIN
        )
        assert login.status_code == 200


async def test_recovery_revoke_sessions_is_audited_with_its_count(anon_client):
    from app.services.auth import recovery_revoke_sessions

    await _claim(anon_client)
    async with fresh_client() as c:
        assert (
            await c.post("/auth/login", json={"password": PASSWORD}, headers=ORIGIN)
        ).status_code == 200
    async with get_sessionmaker()() as session:
        assert await recovery_revoke_sessions(session) == 2
        events = (
            (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.event_type == audit.SESSIONS_REVOKED)
                )
            )
            .scalars()
            .all()
        )
    assert [(e.detail, e.target, e.client_address) for e in events] == [
        ("count=2", "recovery revoke-sessions", "host")
    ]
    assert (await anon_client.get("/kits")).status_code == 401


async def test_recovery_on_an_unclaimed_instance_claims_it(anon_client):
    from app.services.auth import is_claimed, recovery_reset_password

    async with get_sessionmaker()() as session:
        assert await is_claimed(session) is False
        await recovery_reset_password(session, password="fresh-owner-password")
    async with get_sessionmaker()() as session:
        assert await is_claimed(session) is True
    async with fresh_client() as c:
        assert (
            await c.post("/auth/login", json={"password": "fresh-owner-password"}, headers=ORIGIN)
        ).status_code == 200
