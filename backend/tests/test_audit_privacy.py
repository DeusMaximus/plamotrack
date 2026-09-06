"""Audit representations at the real ingress/OIDC/MCP boundaries (#208 f5/f6)."""

import hashlib

import httpx
import pytest

from app.services import audit, oidc
from tests import test_auth_oidc as browser
from tests import test_ingress as ingress
from tests import test_mcp_oauth as mcp
from tests.oidc_fake import FakeIdp, oidc_app

pytestmark = pytest.mark.anyio

# Literal cases shared by the pure resolver and both persisted refusal surfaces.
# A malformed hop is a boundary: even a valid address to its left is not evidence.
_FORWARDING = [
    ("", "198.51.100.7"),
    ("203.0.113.8", "203.0.113.8"),
    ("203.0.113.8:4321", "203.0.113.8"),
    ("[2001:0DB8:0:0::8]:4321", "2001:db8::8"),
    ("2001:0DB8:0:0::8", "2001:db8::8"),
    ("203.0.113.8, 198.51.100.9", "203.0.113.8"),
    ("203.0.113.8, [2001:db8::9]:4321, 198.51.100.9", "203.0.113.8"),
    ("192.0.2.1, 203.0.113.8, 198.51.100.9", "203.0.113.8"),
    ("not-an-ip-address", "198.51.100.7"),
    ("credential=query-marker", "198.51.100.7"),
    ("203.0.113.8, bad, 198.51.100.9", "198.51.100.9"),
    ("203.0.113.8, , 198.51.100.9", "198.51.100.9"),
    ("203.0.113.8,   , 198.51.100.9", "198.51.100.9"),
    ("203.0.113.8,", "198.51.100.7"),
    ("bad, 203.0.113.8, 198.51.100.9", "203.0.113.8"),
    ("[2001:db8::8", "198.51.100.7"),
    ("[2001:db8::8]trailing", "198.51.100.7"),
    ("[2001:db8::8]:bad", "198.51.100.7"),
    ("203.0.113.8:bad", "198.51.100.7"),
    ("203.0.113.8:", "198.51.100.7"),
    ("203.0.113.8:65536", "198.51.100.7"),
    ("fe80::1%credential=query-marker", "198.51.100.7"),
]
_TRUSTED = "198.51.100.0/24,2001:db8::9"


@pytest.mark.parametrize("forwarded,expected", _FORWARDING)
def test_forwarded_audit_address_is_the_last_validated_ip(forwarded, expected):
    policy = ingress.IngressPolicy.from_settings(ingress.make_settings(trusted_proxies=_TRUSTED))
    assert policy.resolve_client_address("198.51.100.7", forwarded) == expected
    assert policy.resolve_client_address("192.0.2.2", forwarded) == "192.0.2.2"


@pytest.mark.parametrize("forwarded,expected", _FORWARDING)
@pytest.mark.parametrize("guard", ["host", "origin"])
async def test_refusal_audit_persists_only_validated_forwarded_addresses(
    guard, forwarded, expected
):
    settings = ingress.make_settings(trusted_proxies=_TRUSTED)
    async with ingress.running_client(
        settings,
        peer=("198.51.100.7", 5000),
        host="evil.example" if guard == "host" else "localhost",
        authorization=True,
    ) as client:
        response = await client.post(
            "/retailers?token=query-marker",
            json={"name": "body-marker"},
            headers={"Origin": "https://evil.example", "X-Forwarded-For": forwarded},
        )
    assert response.status_code == (421 if guard == "host" else 403)
    assert response.json()["code"] == (
        "ingress.host_not_allowed" if guard == "host" else "ingress.origin_not_allowed"
    )
    event = audit.HOST_REJECTED if guard == "host" else audit.ORIGIN_REJECTED
    (row,) = await ingress._audit_rows(event)
    assert row.client_address == expected
    assert row.principal_kind == "anon"
    assert row.target == "/retailers"


def _fingerprint(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


@pytest.mark.parametrize(
    "suffix",
    ["?credential=client-query-marker", "?credential=client-query-marker#client-fragment-marker"],
)
@pytest.mark.parametrize(
    "flow",
    [
        "issue",
        "identity",
        "claim",
        "explicit-identity",
        "explicit-claim",
        "transparent-identity",
        "transparent-claim",
        "revoke-access",
        "revoke-refresh",
    ],
)
async def test_oauth_client_audit_references_do_not_copy_external_values(monkeypatch, suffix, flow):
    client_id = mcp.CIMD_ID + suffix
    document = mcp._cimd_document(client_id=client_id)

    async def fetch(self, client_id_url):
        assert client_id_url == client_id
        return document

    monkeypatch.setattr(mcp.CIMDFetcher, "fetch", fetch)
    fake = FakeIdp()
    await mcp._bind_owner()
    async with mcp.oauth_app(fake) as (_, client):
        verifier, challenge = mcp._pkce()
        started = await mcp.authorize(client, client_id, mcp.CIMD_CB, challenge=challenge)
        assert started.status_code == 302, started.text
        approved = await mcp.consent(client, started.headers["location"])
        assert approved.status_code == 302, approved.text
        sub = "subject=subject-query-marker" if flow == "identity" else mcp.OWNER_SUB
        claims = {"aud": "other-client"} if flow == "claim" else {}
        returned = await mcp.idp_return(
            client,
            fake,
            approved.headers["location"],
            sub=sub,
            expires_in=-5 if flow.startswith("transparent") else 300,
            **claims,
        )
        assert returned.status_code == 302, returned.text
        code = mcp._query(returned.headers["location"])["code"]
        exchanged = await mcp.exchange(client, client_id, code, verifier, redirect_uri=mcp.CIMD_CB)
        assert exchanged.status_code == (401 if flow in {"identity", "claim"} else 200), (
            exchanged.text
        )
        if flow == "identity":
            events = [audit.MCP_IDENTITY_REFUSED]
        elif flow == "claim":
            events = [audit.OIDC_LOGIN_FAILED]
        elif flow.startswith(("explicit", "transparent")):
            tokens = exchanged.json()
            subject = "subject=subject-query-marker" if flow.endswith("identity") else mcp.OWNER_SUB
            key = fake.key if flow.endswith("identity") else fake.other_key
            fake.next_refresh = mcp._provider_refresh(
                fake, id_token=fake.issue(sub=subject, nonce=None, omit=("nonce",), key=key)
            )
            answer = (
                (await mcp.refresh(client, client_id, tokens["refresh_token"]))
                if flow.startswith("explicit")
                else (await mcp.initialize(client, tokens["access_token"]))
            )
            assert answer.status_code == 401, answer.text
            events = [
                audit.MCP_IDENTITY_REFUSED
                if flow.endswith("identity")
                else audit.OIDC_LOGIN_FAILED,
                audit.MCP_GRANT_REVOKED,
            ]
            assert "mcp-upstream-tokens" not in {c for c, _ in await mcp._state_rows()}
        elif flow.startswith("revoke"):
            tokens = exchanged.json()
            half = "access_token" if flow.endswith("access") else "refresh_token"
            answer = await mcp.revoke(client, client_id, tokens[half])
            assert answer.status_code == 200, answer.text
            events = [audit.MCP_GRANT_REVOKED]
            assert "mcp-upstream-tokens" not in {c for c, _ in await mcp._state_rows()}
        else:
            events = [audit.MCP_GRANT_ISSUED]
    for event in events:
        (row,) = await mcp._events(event)
        assert "client-query-marker" not in row.detail
        assert "client-fragment-marker" not in row.detail
        assert "subject-query-marker" not in row.detail
        assert f"client={_fingerprint(client_id)}" in row.detail
        if event == audit.MCP_IDENTITY_REFUSED:
            assert f"subject={_fingerprint('subject=subject-query-marker')}" in row.detail


@pytest.mark.parametrize(
    "error,category",
    [
        (None, "missing_code"),
        ("", "other"),
        ("access_denied", "access_denied"),
        ("access_denied ", "other"),
        ("credential=provider-query-marker", "other"),
        ("other", "other"),
    ],
)
async def test_browser_callback_audit_uses_only_fixed_error_categories(error, category):
    fake = FakeIdp()
    async with oidc_app(fake) as (live, client):
        token = browser._issue_setup_token(live)
        started = await browser._start(client, setup_token=token)
        state = browser._params(started.json()["authorization_url"])["state"]
        query = {} if error is None else {"error": error}
        result = await browser._callback(
            client, state=state, code=None if error is None else FakeIdp.GOOD_CODE, **query
        )
        assert browser._auth_error(result) == (
            oidc.CallbackError.DENIED if error == "access_denied" else oidc.CallbackError.FAILED
        )
    (row,) = await browser._events(audit.OIDC_LOGIN_FAILED)
    assert row.detail == f"provider_error={category}"
    assert row.principal_kind == "anon"
    assert await browser._session_count() == 0
    assert fake.token_requests == []


async def test_browser_identity_audit_fingerprints_the_external_subject():
    fake = FakeIdp()
    await mcp._bind_owner()
    async with oidc_app(fake) as (_, client):
        result = await browser._sign_in(fake, client, sub="subject=subject-query-marker")
        assert browser._auth_error(result) == oidc.CallbackError.IDENTITY_REFUSED
    (row,) = await browser._events(audit.OIDC_IDENTITY_REFUSED)
    assert row.detail == "subject=" + _fingerprint("subject=subject-query-marker")
    assert await browser._session_count() == 0


@pytest.mark.parametrize(
    "value",
    [None, "provider-body-marker", ["provider-body-marker"], {"secret": "provider-body-marker"}],
)
async def test_browser_token_error_logs_do_not_copy_provider_values(monkeypatch, value):
    records = []

    class Recorder:
        def warning(self, msg, *args):
            records.append(msg % args)

        info = warning

    monkeypatch.setattr(oidc, "log", Recorder())
    fake = FakeIdp()
    handler = fake.handler

    def refusing(request):
        if request.url.path == "/token":
            return httpx.Response(400, json={"error": value})
        return handler(request)

    fake.handler = refusing
    async with oidc_app(fake) as (live, client):
        token = browser._issue_setup_token(live)
        result = await browser._sign_in(fake, client, setup_token=token)
        assert browser._auth_error(result) == oidc.CallbackError.FAILED
    assert any("status=400" in line for line in records)
    assert "provider-body-marker" not in "\n".join(records)
    assert await browser._session_count() == 0


@pytest.mark.parametrize("error", ["access_denied", "credential=callback-error-marker"])
async def test_live_mcp_failed_callback_keeps_audit_and_diagnostics_private(error):
    import logging

    import fastmcp.server.auth.oauth_proxy.proxy as library

    logger = library.logger
    capture = mcp._Capture()
    disabled, level = logger.disabled, logger.level
    logger.disabled = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(capture)
    try:
        fake = FakeIdp()
        await mcp._bind_owner()
        async with mcp.oauth_app(fake) as (_, client):
            client_id = (await mcp.register(client)).json()["client_id"]
            _, challenge = mcp._pkce()
            started = await mcp.authorize(client, client_id, challenge=challenge)
            approved = await mcp.consent(client, started.headers["location"])
            state = mcp._query(approved.headers["location"])["state"]
            answer = await client.get(
                "/mcp/auth/callback",
                params={
                    "state": state,
                    "error": error,
                    "error_description": "callback-description-marker",
                },
            )
            assert answer.status_code == 302
            assert answer.headers["location"].startswith(mcp.NATIVE_CB + "?")
            assert mcp._query(answer.headers["location"])["state"] == "client-state"
    finally:
        logger.removeHandler(capture)
        logger.disabled, logger.level = disabled, level
    assert capture.lines
    rows = await mcp._events(audit.OIDC_LOGIN_FAILED)
    stored = "\n".join(capture.lines + [r.detail or "" for r in rows])
    assert "callback-error-marker" not in stored
    assert "callback-description-marker" not in stored
    assert not await mcp._events(audit.MCP_GRANT_ISSUED)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " ",
        "opaque-client",
        "https://client.example/path?credential=one",
        "https://client.example/path?credential=two",
        "https://user:secret@client.example/path#fragment",
        "secret-in-path",
        "\ud800",
        "\r\ncredential=marker",
    ],
)
def test_external_audit_reference_is_bounded_and_correlates_the_complete_value(value):
    expected = "none" if value is None else _fingerprint(value)
    assert audit.external_reference(value) == expected
    assert len(expected) <= 71


@pytest.mark.parametrize(
    "value,expected",
    [
        ("203.0.113.8", "203.0.113.8"),
        ("[2001:0DB8::8]:4321", "2001:db8::8"),
        ("garbage", "198.51.100.7"),
        ("[2001:db8::8]trailing", "198.51.100.7"),
        ("203.0.113.8:bad", "198.51.100.7"),
        ("fe80::1%credential=marker", "198.51.100.7"),
    ],
)
def test_bundled_audit_address_validates_the_whole_ip_spelling(value, expected):
    from app.ingress import client_address_from_scope

    policy = ingress.IngressPolicy.from_settings(
        ingress.make_settings(plamotrack_bundled_ingress=True)
    )
    scope = {
        "type": "http",
        "client": ("198.51.100.7", 5000),
        "headers": [(b"x-plamotrack-client-address", value.encode())],
    }
    assert client_address_from_scope(scope, policy) == expected
    assert scope["client"] == ("198.51.100.7", 5000)
