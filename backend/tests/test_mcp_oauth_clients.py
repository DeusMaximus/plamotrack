"""The downstream client contract of the MCP OAuth mount, from the wire (§5.5
family 8, §5.9 item 7 (k); #192, Codex #212 round 4).

Which client kinds and authentication methods this authorization server
supports, tested with the forms and headers a client actually sends — built
by hand, never through the SDK's request models or the lifecycle suite's
convenience helpers for the same endpoints — across each kind's whole
lifecycle: registration where there is one, the code exchange, a refresh, a
revocation, and what the store, the audit log and the bearer say afterwards.
The environment is the lifecycle suite's (`tests/test_mcp_oauth.py`: the
enforced OIDC-mode app, the fake provider, the owner's browser at the consent
page); the requests under test are not.

**The contract.** Every dynamically registered client is a **public** client —
`token_endpoint_auth_method=none`, PKCE — whatever it asked for, and the
registration response says exactly that (RFC 7591 §3.2.1: substituted
metadata, described truthfully; no `client_secret`, no
`client_secret_expires_at`). Registration is open, so a downstream secret
would be minted to whoever asks and would authenticate nothing that PKCE and
the rotating refresh token do not; the authority is the owner's upstream
login and the grant machinery. A CIMD client authenticates as its document
says — `none`, or `private_key_jwt` with the document's keys — on `/token`
and on `/revoke` alike, each assertion bound to the endpoint it is sent to
(RFC 7523 §3, the `aud`) and usable once. `client_id` travels in the form on
both endpoints for every kind (RFC 6749 §3.2.1 requires it of a public
client; RFC 7523 §2.2 permits it beside an assertion). A public client sends
no secret, and one it sends anyway is ignored. A wrong or missing assertion
is `401 invalid_client` on either endpoint with the grant untouched — the refresh handle it
was sent with stays redeemable. Round 4 found the registration response
advertising `client_secret_post` and a secret over a stored public client,
the revocation form refusing a public client that sent no secret, and a
`private_key_jwt` client able to link and unable to revoke.
"""

from __future__ import annotations

import secrets
import time

import pytest
from fastmcp.server.auth.cimd import CIMDFetcher
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.auth.mcp_oauth import MCP_OAUTH_ATTR
from app.services import audit
from tests.oidc_fake import OWNER_SUB, FakeIdp
from tests.test_mcp_oauth import (
    BASE,
    CIMD_CB,
    CIMD_ID,
    NATIVE_CB,
    _bind_owner,
    _cimd_document,
    _events,
    _pkce,
    _query,
    _state_rows,
    authorize,
    consent,
    idp_return,
    initialize,
    oauth_app,
)

pytestmark = pytest.mark.anyio

ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
TOKEN_URL = f"{BASE}/mcp/token"
REVOKE_URL = f"{BASE}/mcp/revoke"
#: The registration body a client sends, less the method under test: the
#: literal shape, not the lifecycle suite's helper.
REGISTRATION = {
    "redirect_uris": [NATIVE_CB],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "client_name": "contract client",
}


# --- the wire ------------------------------------------------------------------------


async def browser_leg(client, fake: FakeIdp, client_id: str, redirect_uri: str) -> tuple[str, str]:
    """The owner's half — authorize, consent, the provider's return — which is
    environment here; returns the client's code and its PKCE verifier."""
    verifier, challenge = _pkce()
    started = await authorize(client, client_id, redirect_uri, challenge=challenge)
    assert started.status_code == 302, started.text
    approved = await consent(client, started.headers["location"])
    assert approved.status_code == 302, approved.text
    returned = await idp_return(client, fake, approved.headers["location"])
    assert returned.status_code == 302, returned.text
    return _query(returned.headers["location"])["code"], verifier


def assertion(key: RSAKey, client_id: str, audience: str, **claims) -> str:
    """A private_key_jwt client assertion (RFC 7523 §3): iss and sub the client
    id, aud the endpoint it is for, a fresh jti, two minutes to live."""
    now = int(time.time())
    body = {
        "iss": client_id,
        "sub": client_id,
        "aud": audience,
        "iat": now,
        "exp": now + 120,
        "jti": secrets.token_hex(8),
        **claims,
    }
    return jwt.encode({"alg": "RS256", "kid": key.kid}, body, key)


def cimd(monkeypatch, method: str) -> RSAKey:
    """Play the CIMD fetch with a document declaring `method`; the returned key
    is the one the document publishes (inline JWKS) for private_key_jwt."""
    key = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
    document = _cimd_document(
        token_endpoint_auth_method=method,
        jwks={"keys": [key.as_dict(private=False)]} if method == "private_key_jwt" else None,
    )

    async def fetch(self, client_id_url: str):
        assert client_id_url == CIMD_ID
        return document

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)
    return key


async def stored_client(live, client_id: str):
    return await getattr(live.state, MCP_OAUTH_ATTR).proxy.get_client(client_id)


def grant_records(rows) -> bool:
    return "mcp-upstream-tokens" in {collection for collection, _ in rows}


# --- dynamically registered clients are public ----------------------------------------------


@pytest.mark.parametrize(
    "requested",
    ["absent", None, "none", "client_secret_post", "client_secret_basic", "private_key_jwt"],
)
async def test_every_dynamic_registration_is_a_public_client(requested):
    """RFC 7591 §3.2.1: the registration response describes what was
    registered. Whatever method a registration asks for — none, the SDK's
    default when the field is absent or null, either shared-secret method,
    private_key_jwt — the client is registered public, the response says
    `none` and carries no secret and no secret expiry, and the stored client
    agrees. The whole lifecycle then runs on `client_id` alone: the code
    exchange, a refresh, a revocation that ends the grant. The reviewed head
    answered `client_secret_post` and a generated secret over a stored public
    client, so a client held a credential the server never read (f11)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        body = dict(REGISTRATION)
        if requested != "absent":
            body["token_endpoint_auth_method"] = requested
        registered = await client.post("/mcp/register", json=body)
        assert registered.status_code == 201, registered.text
        advertised = registered.json()
        assert advertised["token_endpoint_auth_method"] == "none", advertised
        assert "client_secret" not in advertised, advertised
        assert "client_secret_expires_at" not in advertised, advertised
        client_id = advertised["client_id"]
        stored = await stored_client(live, client_id)
        assert stored.token_endpoint_auth_method == "none"
        assert stored.client_secret is None
        code, verifier = await browser_leg(client, fake, client_id, NATIVE_CB)
        exchanged = await client.post(
            "/mcp/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": NATIVE_CB,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert exchanged.status_code == 200, exchanged.text
        tokens = exchanged.json()
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        fake.next_refresh = _provider_refresh_for(fake)
        renewed = await client.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
            },
        )
        assert renewed.status_code == 200, renewed.text
        successor = renewed.json()
        assert (await initialize(client, successor["access_token"])).status_code == 200
        revoked = await client.post(
            "/mcp/revoke", data={"token": successor["access_token"], "client_id": client_id}
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.headers.get_list("cache-control") == ["no-store"]
        assert not grant_records(await _state_rows())
        assert (await initialize(client, successor["access_token"])).status_code == 401
        assert (await initialize(client, tokens["access_token"])).status_code == 401
        assert len(fake.revoked) == 1
    ended = await _events(audit.MCP_GRANT_REVOKED)
    assert [(r.detail, r.principal_subject) for r in ended] == [
        (f"client={client_id} presented=access_token", OWNER_SUB)
    ]


def _provider_refresh_for(fake: FakeIdp) -> dict:
    """The provider's answer to a refresh — a new upstream pair, no id_token
    (OpenID Connect Core §12.2 allows it), honoured by the fake."""
    response = {
        "access_token": "upstream-access-" + secrets.token_hex(8),
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "upstream-refresh-" + secrets.token_hex(8),
        "scope": "openid",
    }
    fake.refresh_tokens.add(response["refresh_token"])
    return response


@pytest.mark.parametrize("secret", ["absent", "empty", "stray"])
async def test_a_public_client_sends_no_secret_and_one_it_sends_is_ignored(secret):
    """The value axis of the field a public client does not have: absent — the
    contract's form — an empty string, and a value the server never issued.
    Refresh and revocation accept all three alike; none is read. The reviewed
    head's revocation form made the field required, so the contract's own
    form was `400 invalid_request` and the test helper had been sending an
    empty one on every call, adapting the suite to the defect (f12)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        registered = await client.post(
            "/mcp/register", json={**REGISTRATION, "token_endpoint_auth_method": "none"}
        )
        client_id = registered.json()["client_id"]
        code, verifier = await browser_leg(client, fake, client_id, NATIVE_CB)
        exchanged = await client.post(
            "/mcp/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": NATIVE_CB,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert exchanged.status_code == 200, exchanged.text
        tokens = exchanged.json()
        extra = {"absent": {}, "empty": {"client_secret": ""}, "stray": {"client_secret": "x"}}[
            secret
        ]
        fake.next_refresh = _provider_refresh_for(fake)
        renewed = await client.post(
            "/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": client_id,
                **extra,
            },
        )
        assert renewed.status_code == 200, renewed.text
        successor = renewed.json()
        revoked = await client.post(
            "/mcp/revoke",
            data={"token": successor["refresh_token"], "client_id": client_id, **extra},
        )
        assert revoked.status_code == 200, revoked.text
        assert not grant_records(await _state_rows())
        assert (await initialize(client, successor["access_token"])).status_code == 401


@pytest.mark.parametrize("hint", ["absent", "access_token", "refresh_token"])
@pytest.mark.parametrize("presented", ["access_token", "refresh_token"])
async def test_the_hint_is_advice_and_either_half_ends_the_grant(presented, hint):
    """RFC 7009 §2.1: `token_type_hint` is optional and may be wrong; the
    server tries the other lookup. Every combination of the half presented
    and the hint given ends the grant."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        registered = await client.post(
            "/mcp/register", json={**REGISTRATION, "token_endpoint_auth_method": "none"}
        )
        client_id = registered.json()["client_id"]
        code, verifier = await browser_leg(client, fake, client_id, NATIVE_CB)
        exchanged = await client.post(
            "/mcp/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": NATIVE_CB,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        tokens = exchanged.json()
        form = {"token": tokens[presented], "client_id": client_id}
        if hint != "absent":
            form["token_type_hint"] = hint
        revoked = await client.post("/mcp/revoke", data=form)
        assert revoked.status_code == 200, revoked.text
        assert not grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 401
    assert len(await _events(audit.MCP_GRANT_REVOKED)) == 1


# --- CIMD clients authenticate as their document says ---------------------------------------


async def cimd_link(client, fake: FakeIdp, key: RSAKey | None) -> dict:
    """A CIMD client's link by raw requests: the browser leg, then the code
    exchange with the document's method — `client_id` alone, or an assertion
    for the token endpoint."""
    code, verifier = await browser_leg(client, fake, CIMD_ID, CIMD_CB)
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": CIMD_CB,
        "client_id": CIMD_ID,
        "code_verifier": verifier,
    }
    if key is not None:
        form.update(
            client_assertion_type=ASSERTION_TYPE,
            client_assertion=assertion(key, CIMD_ID, TOKEN_URL),
        )
    exchanged = await client.post("/mcp/token", data=form)
    assert exchanged.status_code == 200, exchanged.text
    return exchanged.json()


@pytest.mark.parametrize("method", ["none", "private_key_jwt"])
async def test_a_cimd_client_authenticates_as_its_document_says(monkeypatch, method):
    """Claude web and ChatGPT web bring a metadata document instead of
    registering; its `token_endpoint_auth_method` is the contract for that
    client on every endpoint that authenticates one. With `none` the client id
    suffices; with `private_key_jwt` each request carries an assertion signed
    by the document's key and addressed to that endpoint — the token endpoint
    for the exchange and the refresh, the revocation endpoint for the
    revocation. The reviewed head authenticated a private_key_jwt client at
    `/token` and refused the same client at `/revoke` as an unsupported
    method, so the grant could be created and never ended (f13)."""
    key = cimd(monkeypatch, method) if method == "private_key_jwt" else None
    if method == "none":
        cimd(monkeypatch, "none")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        upstream_refresh = fake.next_token["refresh_token"]
        fake.next_refresh = _provider_refresh_for(fake)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": CIMD_ID,
        }
        if key is not None:
            form.update(
                client_assertion_type=ASSERTION_TYPE,
                client_assertion=assertion(key, CIMD_ID, TOKEN_URL),
            )
        renewed = await client.post("/mcp/token", data=form)
        assert renewed.status_code == 200, renewed.text
        successor = renewed.json()
        form = {"token": successor["access_token"], "client_id": CIMD_ID}
        if key is not None:
            form.update(
                client_assertion_type=ASSERTION_TYPE,
                client_assertion=assertion(key, CIMD_ID, REVOKE_URL),
            )
        revoked = await client.post("/mcp/revoke", data=form)
        assert revoked.status_code == 200, revoked.text
        assert not grant_records(await _state_rows())
        assert (await initialize(client, successor["access_token"])).status_code == 401
        assert (await initialize(client, tokens["access_token"])).status_code == 401
        # The provider's refresh token the record held at revocation: rotated.
        assert [r["token"] for r in fake.revoked] == [fake.next_refresh["refresh_token"]]
        assert upstream_refresh != fake.next_refresh["refresh_token"]
    ended = await _events(audit.MCP_GRANT_REVOKED)
    assert [(r.detail, r.principal_subject) for r in ended] == [
        (f"client={CIMD_ID} presented=access_token", OWNER_SUB)
    ]


@pytest.mark.parametrize("defect", ["absent", "wrong_key", "wrong_audience", "replayed"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_a_private_key_jwt_client_is_refused_without_a_valid_assertion(
    monkeypatch, endpoint, defect
):
    """The refusal half, on both endpoints: no assertion at all, one signed by
    a key the document does not publish, one addressed to the other endpoint
    (an assertion for `/mcp/token` presented at `/mcp/revoke`, and the
    reverse), and one already used. Each is `401 invalid_client` (RFC 6749
    §5.2, the code RFC 7009 §2.2.1 adopts; the SDK's own revocation handler
    said `unauthorized_client`, its token handler `invalid_client`) with
    the grant untouched — the record stands, the bearer works, nothing is
    audited or forwarded upstream — and the handle the request carried is
    then redeemed with a correct assertion, so a failed authentication
    consumes nothing. The reviewed head's revocation authenticator refused
    the method outright, so no assertion, valid or not, could end a
    private_key_jwt client's grant (f13)."""
    key = cimd(monkeypatch, "private_key_jwt")
    other = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        used = assertion(key, CIMD_ID, audience)
        if defect == "replayed":
            # Spend it once, legitimately, on another grant of the same client.
            if endpoint == "token":
                fake.next_refresh = _provider_refresh_for(fake)
                spent = await client.post(
                    "/mcp/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": tokens["refresh_token"],
                        "client_id": CIMD_ID,
                        "client_assertion_type": ASSERTION_TYPE,
                        "client_assertion": used,
                    },
                )
                assert spent.status_code == 200, spent.text
                tokens = spent.json()
            else:
                second = await cimd_link(client, fake, key)
                spent = await client.post(
                    "/mcp/revoke",
                    data={
                        "token": second["access_token"],
                        "client_id": CIMD_ID,
                        "client_assertion_type": ASSERTION_TYPE,
                        "client_assertion": used,
                    },
                )
                assert spent.status_code == 200, spent.text
        credential = {
            "absent": {},
            "wrong_key": {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": assertion(other, CIMD_ID, audience),
            },
            "wrong_audience": {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": assertion(
                    key, CIMD_ID, REVOKE_URL if endpoint == "token" else TOKEN_URL
                ),
            },
            "replayed": {"client_assertion_type": ASSERTION_TYPE, "client_assertion": used},
        }[defect]
        if endpoint == "token":
            fake.next_refresh = _provider_refresh_for(fake)
            form = {
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
                "client_id": CIMD_ID,
            }
        else:
            form = {"token": tokens["access_token"], "client_id": CIMD_ID}
        asked_before = [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        revoked_before = list(fake.revoked)
        refused = await client.post(f"/mcp/{endpoint}", data={**form, **credential})
        assert refused.status_code == 401, refused.text
        assert refused.json()["error"] == "invalid_client", refused.text
        assert refused.headers.get_list("cache-control") == ["no-store"]
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        # The refused request asked the provider nothing and revoked nothing
        # upstream (the replayed row's legitimate first use did both, once).
        assert fake.revoked == revoked_before
        asked_after = [f for f in fake.token_requests if f.get("grant_type") == "refresh_token"]
        assert asked_after == asked_before
        # The handle survives the failed authentication.
        accepted = await client.post(
            f"/mcp/{endpoint}",
            data={
                **form,
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": assertion(key, CIMD_ID, audience),
            },
        )
        assert accepted.status_code == 200, accepted.text
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())
    assert len(await _events(audit.MCP_GRANT_REVOKED)) == (
        2 if (endpoint, defect) == ("revoke", "replayed") else int(endpoint == "revoke")
    )


# --- the revocation form's edges ---------------------------------------------------------


@pytest.mark.parametrize(
    "omit,status,error",
    [("token", 400, "invalid_request"), ("client_id", 401, "invalid_client")],
)
async def test_a_revocation_missing_a_required_field_is_refused_in_the_envelope(
    omit, status, error
):
    """The two fields the contract requires of a public client's revocation,
    each left out: no client is a client-authentication failure, no token a
    malformed request. Both carry `no-store` (the SDK stamps it on success
    only), and the grant is untouched."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        registered = await client.post(
            "/mcp/register", json={**REGISTRATION, "token_endpoint_auth_method": "none"}
        )
        client_id = registered.json()["client_id"]
        code, verifier = await browser_leg(client, fake, client_id, NATIVE_CB)
        exchanged = await client.post(
            "/mcp/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": NATIVE_CB,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        tokens = exchanged.json()
        form = {"token": tokens["access_token"], "client_id": client_id}
        form.pop(omit)
        refused = await client.post("/mcp/revoke", data=form)
        assert refused.status_code == status, refused.text
        assert refused.json()["error"] == error
        assert refused.headers.get_list("cache-control") == ["no-store"]
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
    assert not await _events(audit.MCP_GRANT_REVOKED)
