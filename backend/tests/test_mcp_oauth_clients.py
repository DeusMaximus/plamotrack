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
(RFC 7523 §3, the `aud`) and usable once per process. **Discovery says the
same** (RFC 8414 §2): both authorization-server documents publish exactly
those two methods for the token endpoint and for the revocation endpoint,
and `RS256` as the one assertion algorithm the pinned verifier accepts; the
shared-secret methods the SDK's metadata listed are not there. `client_id`
travels in the form on both endpoints for every kind — RFC 6749 §3.2.1
requires it of a public client; beside an assertion it is a **compatibility
restriction** of this server (RFC 7521 §4.2 makes it optional; FastMCP's
token endpoint requires it and the revocation endpoint matches). A public
client sends no secret, and one it sends anyway is ignored. A wrong or
missing assertion is `401 invalid_client` on either endpoint with the grant
untouched — the refresh handle it was sent with stays redeemable. The value
space of every field is the protocol's, unrecognised values included: a
`token_type_hint` the server does not know is ignored (RFC 7009 §2.2), never
refused. Round 4 found the registration response advertising
`client_secret_post` and a secret over a stored public client, the
revocation form refusing a public client that sent no secret, and a
`private_key_jwt` client able to link and unable to revoke; round 5 found
discovery advertising the SDK's shared-secret methods and no algorithm, and
an unknown hint turning a valid revocation into `400 invalid_request`.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from types import SimpleNamespace

import pytest
from fastmcp.server.auth.cimd import CIMDFetcher
from fastmcp.server.auth.providers.jwt import JWTVerifier
from joserfc import jwt
from joserfc.jwk import ECKey, RSAKey

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


def cimd(monkeypatch, method: str, key=None):
    """Play the CIMD fetch with a document declaring `method`; the returned key
    is the one the document publishes (inline JWKS) for private_key_jwt — an
    RSA key unless the test brings another."""
    key = key or RSAKey.generate_key(2048, parameters={"kid": "client-key"})
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


@pytest.mark.parametrize("hint", ["absent", "access_token", "refresh_token", "", "unknown_type"])
@pytest.mark.parametrize("presented", ["access_token", "refresh_token"])
async def test_the_hint_is_advice_and_either_half_ends_the_grant(presented, hint):
    """RFC 7009 §2.1–§2.2: `token_type_hint` is optional, may be wrong, and
    when the server does not recognise it "the server MUST ignore it" — the
    value space is the protocol's: absent, either recognised value (the wrong
    one for the half presented included), empty, and a value nobody defined.
    Every combination with the half presented ends the grant. The reviewed
    head typed the field as a two-value enum, so an empty or unknown hint
    turned a valid, authenticated revocation into `400 invalid_request` with
    the grant intact (Codex #212 round 5, f15)."""
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


# --- discovery describes the same contract ----------------------------------------------


@pytest.mark.parametrize(
    "path", ["/.well-known/oauth-authorization-server/mcp", "/.well-known/openid-configuration/mcp"]
)
async def test_discovery_advertises_exactly_the_admitted_client_authentication(path):
    """RFC 8414 §2: the two documents a client reads before it registers list
    the client-authentication methods each endpoint accepts and, once a JWT
    method is among them, the signing algorithms. Both spellings publish
    literally `none` and `private_key_jwt` for the token endpoint *and* the
    revocation endpoint, and `RS256` alone — what the pinned verifier accepts
    (`test_an_assertion_algorithm_not_advertised_is_refused` measures the
    edge). Each advertised method is one this suite drives end to end:
    `none` in the registration and hint rows, `private_key_jwt` in the CIMD
    rows. The reviewed head served the SDK's metadata: both shared-secret
    methods at the token endpoint, *only* the shared-secret methods at the
    revocation endpoint — neither admitted anywhere — and no algorithm (Codex
    #212 round 5, f14)."""
    async with oauth_app(FakeIdp()) as (_, client):
        response = await client.get(path)
        assert response.status_code == 200, response.text
        document = response.json()
    assert document["token_endpoint_auth_methods_supported"] == ["none", "private_key_jwt"]
    assert document["revocation_endpoint_auth_methods_supported"] == ["none", "private_key_jwt"]
    assert document["token_endpoint_auth_signing_alg_values_supported"] == ["RS256"]
    assert document["revocation_endpoint_auth_signing_alg_values_supported"] == ["RS256"]
    for field in (
        "token_endpoint_auth_methods_supported",
        "revocation_endpoint_auth_methods_supported",
    ):
        assert not {"client_secret_post", "client_secret_basic"} & set(document[field]), field
    # The rest of the document is FastMCP's, still: the endpoints under the
    # issuer, PKCE, the one scope, CIMD advertised.
    assert document["issuer"] == f"{BASE}/mcp"
    assert document["token_endpoint"] == TOKEN_URL
    assert document["revocation_endpoint"] == REVOKE_URL
    assert document["registration_endpoint"] == f"{BASE}/mcp/register"
    assert document["code_challenge_methods_supported"] == ["S256"]
    assert document["scopes_supported"] == ["openid"]
    assert document["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert document["client_id_metadata_document_supported"] is True


async def test_an_assertion_algorithm_not_advertised_is_refused(monkeypatch):
    """The other half of the advertised algorithm list: a CIMD document that
    publishes an EC key, and a client that signs its assertion `ES256` with
    it, cannot authenticate — `401 invalid_client` at the code exchange,
    nothing issued, no grant record — because the pinned verifier accepts
    `RS256` alone, which is what discovery says."""
    key = ECKey.generate_key("P-256", parameters={"kid": "client-key"})
    cimd(monkeypatch, "private_key_jwt", key=key)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        code, verifier = await browser_leg(client, fake, CIMD_ID, CIMD_CB)
        now = int(time.time())
        signed = jwt.encode(
            {"alg": "ES256", "kid": key.kid},
            {
                "iss": CIMD_ID,
                "sub": CIMD_ID,
                "aud": TOKEN_URL,
                "iat": now,
                "exp": now + 120,
                "jti": secrets.token_hex(8),
            },
            key,
        )
        refused = await client.post(
            "/mcp/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CIMD_CB,
                "client_id": CIMD_ID,
                "code_verifier": verifier,
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": signed,
            },
        )
        assert refused.status_code == 401, refused.text
        assert refused.json()["error"] == "invalid_client"
        assert not grant_records(await _state_rows())
    assert not await _events(audit.MCP_GRANT_ISSUED)


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


# --- Codex #212 round 6: the SDK-to-application boundary, field by field ------------------
#
# Registration normalisation, request decoding, assertion claims and a generated
# URL each need an explicit owner; fixing the one field a review names leaves its
# siblings inherited. The rows below are the value spaces the round enumerated.


def _clock(monkeypatch, seconds: int) -> None:
    """Move every clock an assertion is judged by — this module's claim
    validator, the SDK's assertion validator and its JWT verifier — by
    `seconds`, leaving `monotonic` (the SDK's cache housekeeping) real."""
    import fastmcp.server.auth.cimd as cimd_module
    import fastmcp.server.auth.providers.jwt as jwt_module

    from app.auth import mcp_oauth as mcp_oauth_module

    later = SimpleNamespace(time=lambda: time.time() + seconds, monotonic=time.monotonic)
    for module in (cimd_module, jwt_module, mcp_oauth_module):
        monkeypatch.setattr(module, "time", later)


def signed(key, client_id: str, audience: str, *, alg: str = "RS256", **claims) -> str:
    """An assertion with any claim overridden — a value of `OMIT` leaves the
    claim out — and the JOSE `alg` a knob."""
    now = int(time.time())
    body = {
        "iss": client_id,
        "sub": client_id,
        "aud": audience,
        "iat": now,
        "exp": now + 120,
        "jti": secrets.token_hex(8),
    }
    for name, value in claims.items():
        if value is OMIT:
            body.pop(name, None)
        else:
            body[name] = value
    return jwt.encode({"alg": alg, "kid": key.kid}, body, key)


OMIT = object()
#: The names only; the values are dated when the test runs (`_claim_defect`).
CLAIM_DEFECTS = (
    "nbf_future",
    "nbf_string",
    "nbf_null",
    "nbf_bool",
    "nbf_huge",
    "nbf_beyond_bound",
    "iat_bool",
    "iat_huge",
    "exp_string",
    "exp_missing",
    "exp_huge",
    "exp_infinite",
    "jti_number",
    "jti_list",
    "jti_missing",
    "sub_missing",
    "aud_number",
)


def _claim_defect(name: str) -> dict:
    """One claim outside the contract, dated **now** — a table computed at
    import put `nbf_future` 240 s past the module's load, which a suite
    reaching the row 210 s later found inside the 30 s skew: CI's full run
    failed both endpoint rows on `200 == 401` while a focused run passed
    (Codex #212 round 7, f23). The range rows are round 7's f21: a 401-digit
    integer overflowed the float conversion behind `math.isfinite` and the
    endpoint answered 500."""
    now = int(time.time())
    return {
        "nbf_future": {"nbf": now + 240, "exp": now + 270},
        "nbf_string": {"nbf": "later"},
        "nbf_null": {"nbf": None},
        "nbf_bool": {"nbf": False},
        "nbf_huge": {"nbf": 10**400},
        "nbf_beyond_bound": {"nbf": -(2**53) - 1},
        "iat_bool": {"iat": False},
        "iat_huge": {"iat": 10**400},
        "exp_string": {"exp": "soon"},
        "exp_missing": {"exp": OMIT},
        "exp_huge": {"exp": 10**400},
        "exp_infinite": {"exp": float("inf")},
        "jti_number": {"jti": 12345},
        "jti_list": {"jti": ["a", "b"]},
        "jti_missing": {"jti": OMIT},
        "sub_missing": {"sub": OMIT},
        "aud_number": {"aud": 7},
    }[name]


async def _endpoint_request(
    client,
    endpoint: str,
    tokens: dict,
    fake: FakeIdp,
    credential: dict,
    *,
    client_id: str = CIMD_ID,
    headers: dict | None = None,
):
    """The request under test on `endpoint` with the grant's handle: a refresh
    on the token endpoint, the access token on the revocation endpoint."""
    if endpoint == "token":
        fake.next_refresh = _provider_refresh_for(fake)
        form = {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client_id,
        }
    else:
        form = {"token": tokens["access_token"], "client_id": client_id}
    return await client.post(f"/mcp/{endpoint}", data={**form, **credential}, headers=headers)


@pytest.mark.parametrize("defect", CLAIM_DEFECTS)
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_a_client_assertion_claim_that_fails_the_contract_is_refused_first(
    monkeypatch, endpoint, defect
):
    """RFC 7523 §3 and RFC 7519 §4.1, on both endpoints: the assertion's claims
    have a contract — `exp` required, `exp`/`iat`/`nbf` NumericDates within
    ±2^53 (RFC 7493 §2.2) and never booleans, `nbf` respected (with the SDK's
    30 s skew), `jti` a non-empty string, `sub` present, `aud` a string or a
    list of strings — and a claim outside it is `401 invalid_client`
    **before** the SDK verifies the assertion, so nothing is spent: the grant
    stands, no provider call, no audit row, and the same handle is then
    redeemed with a correct assertion. The reviewed head accepted an
    assertion before its `nbf`, accepted booleans and strings where dates
    belong, and answered **500** to a list or object `jti` — the SDK's
    validator never checked `nbf` and used the raw `jti` as a dictionary key
    (Codex #212 round 6, f16); round 6's own range check then answered
    **500** to a 401-digit date — `math.isfinite` overflowed converting it
    (round 7, f21): the `huge`, `infinite` and `beyond_bound` rows."""
    key = cimd(monkeypatch, "private_key_jwt")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        bad = signed(key, CIMD_ID, audience, **_claim_defect(defect))
        asked_before = list(fake.token_requests)
        refused = await _endpoint_request(
            client,
            endpoint,
            tokens,
            fake,
            {"client_assertion_type": ASSERTION_TYPE, "client_assertion": bad},
        )
        assert refused.status_code == 401, (defect, refused.status_code, refused.text[:200])
        assert refused.json()["error"] == "invalid_client"
        assert refused.headers.get_list("cache-control") == ["no-store"]
        assert grant_records(await _state_rows())
        assert fake.token_requests == asked_before
        assert fake.revoked == []
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        accepted = await _endpoint_request(
            client,
            endpoint,
            tokens,
            fake,
            {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": signed(key, CIMD_ID, audience),
            },
        )
        assert accepted.status_code == 200, accepted.text[:300]
    assert not await _events(audit.MCP_IDENTITY_REFUSED)


@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_an_assertion_not_yet_valid_is_the_same_assertion_later(monkeypatch, endpoint):
    """The `nbf` refusal spends nothing: the very same signed assertion, refused
    before its not-before time, is accepted once the clocks pass it — the
    refusal happened before the SDK's replay cache saw the `jti`."""
    key = cimd(monkeypatch, "private_key_jwt")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        now = int(time.time())
        early = signed(key, CIMD_ID, audience, nbf=now + 240, exp=now + 270)
        credential = {"client_assertion_type": ASSERTION_TYPE, "client_assertion": early}
        refused = await _endpoint_request(client, endpoint, tokens, fake, credential)
        assert refused.status_code == 401, refused.text[:200]
        assert refused.json()["error"] == "invalid_client"
        _clock(monkeypatch, 241)
        accepted = await _endpoint_request(client, endpoint, tokens, fake, credential)
        assert accepted.status_code == 200, accepted.text[:300]
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())


@pytest.mark.parametrize("shape", ["fractional_dates", "no_iat", "aud_list", "nbf_at_bound"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_a_valid_but_unusual_assertion_shape_is_accepted(monkeypatch, endpoint, shape):
    """The contract's positive edge: fractional NumericDates, an omitted
    optional `iat`, an `aud` given as a one-element list, and an `nbf` at the
    supported range's own bound (−2^53, long past) are all valid (RFC 7519
    §4.1, RFC 7493 §2.2) and are accepted on both endpoints."""
    key = cimd(monkeypatch, "private_key_jwt")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        now = time.time()
        claims = {
            "fractional_dates": {"iat": now - 0.5, "exp": now + 119.5},
            "no_iat": {"iat": OMIT},
            "aud_list": {"aud": [audience]},
            "nbf_at_bound": {"nbf": -(2**53)},
        }[shape]
        accepted = await _endpoint_request(
            client,
            endpoint,
            tokens,
            fake,
            {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": signed(key, CIMD_ID, audience, **claims),
            },
        )
        assert accepted.status_code == 200, accepted.text[:300]


# --- registration: every substituted field describes the stored client ----------------------


@pytest.mark.parametrize(
    "variation",
    [
        "null_redirects",
        "extra_response_type",
        "empty_scope",
        "padded_scope",
        "extra_grant",
        "display",
        "jwks",
        "jwks_uri",
        "both_key_sources",
    ],
)
async def test_the_registration_response_describes_the_stored_client(variation):
    """RFC 7591 §3.2.1, the neighbouring fields of round 4's method: the
    server substitutes what it does not offer and the response says what it
    registered — and the stored client is that same object, field for field.
    A `null` redirect list is refused (`invalid_client_metadata`: this server
    issues authorization codes only, and the reviewed head invented
    `http://localhost/` for it); `response_types` beyond `code` and
    `grant_types` beyond the two are substituted to what is offered; an empty
    or padded `scope` is the default; the display and software fields are
    echoed *and* stored. The reviewed head returned what was asked and stored
    what FastMCP's registration constructed (Codex #212 round 6, f17). And
    the admitted metadata obeys its own cross-field rule: `jwks` and
    `jwks_uri` "MUST NOT both be present in the same request or response"
    (RFC 7591 §2) — either alone is echoed and stored, both together is
    `invalid_client_metadata`, where the reviewed head echoed and stored the
    pair (round 7, f26)."""
    body = dict(REGISTRATION)
    body["token_endpoint_auth_method"] = "none"
    expected: dict = {}
    public_key = RSAKey.generate_key(2048, parameters={"kid": "registered"}).as_dict(private=False)
    if variation == "null_redirects":
        body["redirect_uris"] = None
    elif variation == "jwks":
        body["jwks"] = {"keys": [public_key]}
        expected["jwks"] = {"keys": [public_key]}
    elif variation == "jwks_uri":
        body["jwks_uri"] = "https://keys.example/jwks.json"
        expected["jwks_uri"] = "https://keys.example/jwks.json"
    elif variation == "both_key_sources":
        body["jwks"] = {"keys": [public_key]}
        body["jwks_uri"] = "https://keys.example/jwks.json"
    elif variation == "extra_response_type":
        body["response_types"] = ["code", "token"]
        expected["response_types"] = ["code"]
    elif variation == "empty_scope":
        body["scope"] = ""
        expected["scope"] = "openid"
    elif variation == "padded_scope":
        body["scope"] = "  openid  "
        expected["scope"] = "openid"
    elif variation == "extra_grant":
        body["grant_types"] = ["authorization_code", "refresh_token", "implicit"]
        expected["grant_types"] = ["authorization_code", "refresh_token"]
    else:
        body.update(
            client_uri="https://client.example/",
            contacts=["ops@client.example"],
            software_id="contract-suite",
            software_version="1",
        )
        expected.update(
            client_uri="https://client.example/",
            contacts=["ops@client.example"],
            software_id="contract-suite",
            software_version="1",
        )
    async with oauth_app(FakeIdp()) as (live, client):
        registered = await client.post("/mcp/register", json=body)
        if variation in ("null_redirects", "both_key_sources"):
            assert registered.status_code == 400, registered.text
            assert registered.json()["error"] == "invalid_client_metadata"
            assert registered.headers.get_list("cache-control") == ["no-store"]
            return
        assert registered.status_code == 201, registered.text
        advertised = registered.json()
        for field, value in expected.items():
            assert advertised[field] == value, (field, advertised)
        stored = json.loads((await stored_client(live, advertised["client_id"])).model_dump_json())
        for field, value in advertised.items():
            assert stored.get(field) == value, (field, value, stored.get(field))


# --- request decoding: multiplicity, emptiness, the protocol's own errors ---------------------


async def _public_grant(client, fake: FakeIdp) -> tuple[str, str, str, dict | None]:
    """A public DCR client with a code in hand: returns client id, code,
    verifier — and no tokens (the exchange is the test's)."""
    registered = await client.post(
        "/mcp/register", json={**REGISTRATION, "token_endpoint_auth_method": "none"}
    )
    client_id = registered.json()["client_id"]
    code, verifier = await browser_leg(client, fake, client_id, NATIVE_CB)
    return client_id, code, verifier, None


def _encoded(pairs: list[tuple[str, str]]) -> tuple[str, dict]:
    """A form body with the pairs in this order — including a name twice, which
    a dict cannot express — and its content type."""
    from urllib.parse import urlencode

    return urlencode(pairs), {"Content-Type": "application/x-www-form-urlencoded"}


@pytest.mark.parametrize("field", ["grant_type", "client_id", "code_verifier"])
async def test_a_repeated_token_parameter_is_refused_and_the_code_survives(field):
    """RFC 6749 §3.2: parameters "MUST NOT be included more than once". A code
    exchange carrying `grant_type`, `client_id` or `code_verifier` twice — an
    invalid value first, the valid one last — is `400 invalid_request` before
    anything is redeemed: the code is then exchanged cleanly. The reviewed
    head's form parsing kept the last value and minted (Codex #212 round 6,
    f18)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id, code, verifier, _ = await _public_grant(client, fake)
        pairs = [
            ("grant_type", "authorization_code"),
            ("code", code),
            ("redirect_uri", NATIVE_CB),
            ("client_id", client_id),
            ("code_verifier", verifier),
        ]
        wrong = {"grant_type": "password", "client_id": "someone-else", "code_verifier": "x" * 43}
        doubled = [(field, wrong[field])] + pairs
        body, headers = _encoded(doubled)
        refused = await client.post("/mcp/token", content=body, headers=headers)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"] == "invalid_request"
        assert refused.headers.get_list("cache-control") == ["no-store"]
        body, headers = _encoded(pairs)
        exchanged = await client.post("/mcp/token", content=body, headers=headers)
        assert exchanged.status_code == 200, exchanged.text
    assert len(await _events(audit.MCP_GRANT_ISSUED)) == 1


@pytest.mark.parametrize("field", ["client_id", "token", "token_type_hint"])
async def test_a_repeated_revocation_parameter_is_refused_and_the_grant_stands(field):
    """The same rule at `/revoke`: `client_id`, `token` or `token_type_hint`
    twice is `400 invalid_request` with the grant untouched; the clean form
    then ends it."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id, code, verifier, _ = await _public_grant(client, fake)
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
        pairs = [("token", tokens["access_token"]), ("client_id", client_id)]
        wrong = {"client_id": "someone-else", "token": "not-a-token", "token_type_hint": "x"}
        doubled = [(field, wrong[field])] + pairs + [("token_type_hint", "access_token")]
        body, headers = _encoded(doubled)
        refused = await client.post("/mcp/revoke", content=body, headers=headers)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"] == "invalid_request"
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        body, headers = _encoded(pairs)
        revoked = await client.post("/mcp/revoke", content=body, headers=headers)
        assert revoked.status_code == 200, revoked.text
        assert not grant_records(await _state_rows())
    assert len(await _events(audit.MCP_GRANT_REVOKED)) == 1


@pytest.mark.parametrize("field", ["state", "client_id"])
async def test_a_repeated_authorization_parameter_is_refused_without_a_redirect(field):
    """RFC 6749 §3.1 at `/authorize`: `state` or `client_id` twice is a `400`
    answered directly — never a redirect through a client URI chosen from an
    ambiguous request — and no transaction is created."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        registered = await client.post(
            "/mcp/register", json={**REGISTRATION, "token_endpoint_auth_method": "none"}
        )
        client_id = registered.json()["client_id"]
        _, challenge = _pkce()
        pairs = [
            ("client_id", client_id),
            ("response_type", "code"),
            ("redirect_uri", NATIVE_CB),
            ("code_challenge", challenge),
            ("code_challenge_method", "S256"),
            ("state", "client-state"),
            ("scope", "openid"),
        ]
        first = {"state": "other-state", "client_id": "someone-else"}
        from urllib.parse import urlencode

        refused = await client.get("/mcp/authorize?" + urlencode([(field, first[field])] + pairs))
        assert refused.status_code == 400, refused.text
        assert "location" not in refused.headers
        assert refused.json()["error"] == "invalid_request"
        assert refused.headers.get_list("cache-control") == ["no-store"]


async def test_an_empty_value_is_an_omitted_one():
    """RFC 6749 §3.1: "parameters sent without a value MUST be treated as if
    they were omitted". An empty `token` at `/revoke` is a missing required
    parameter (`400 invalid_request`, the grant untouched); an empty `scope`
    at `/authorize` is no scope, so the default applies and the transaction
    is created. The reviewed head revoked nothing and answered 200 to the
    first, and redirected `invalid_scope` for the second."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id, code, verifier, _ = await _public_grant(client, fake)
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
        refused = await client.post("/mcp/revoke", data={"token": "", "client_id": client_id})
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"] == "invalid_request"
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        _, challenge = _pkce()
        started = await authorize(client, client_id, NATIVE_CB, challenge=challenge, scope="")
        assert started.status_code == 302, started.text
        assert started.headers["location"].startswith(f"{BASE}/mcp/consent?txn_id="), (
            started.headers["location"]
        )


@pytest.mark.parametrize("grant_type", ["client_credentials", "password", "unknown"])
async def test_an_unsupported_grant_type_is_named_as_such(grant_type):
    """RFC 6749 §5.2: a grant type the server does not support is
    `unsupported_grant_type`, not a malformed request. The reviewed head's
    parser answered `invalid_request` for all three."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id, _, _, _ = await _public_grant(client, fake)
        refused = await client.post(
            "/mcp/token", data={"grant_type": grant_type, "client_id": client_id}
        )
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"] == "unsupported_grant_type"
        assert refused.headers.get_list("cache-control") == ["no-store"]


@pytest.mark.parametrize("method", ["absent", "plain", "s256"])
async def test_pkce_must_be_declared_s256(method):
    """RFC 7636 §4.3: an omitted `code_challenge_method` means `plain`, which
    this server does not offer, so the omission is refused exactly as `plain`
    is — RFC 7636 §4.4.1's authorization error response, an `invalid_request`
    redirect to the registered callback with the state, and no consent
    transaction — where the reviewed head's model defaulted the omission to
    `S256` and opened one. `S256` stated is the control."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        registered = await client.post(
            "/mcp/register", json={**REGISTRATION, "token_endpoint_auth_method": "none"}
        )
        client_id = registered.json()["client_id"]
        _, challenge = _pkce()
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": NATIVE_CB,
            "code_challenge": challenge,
            "state": "client-state",
            "scope": "openid",
        }
        if method == "plain":
            params["code_challenge_method"] = "plain"
        elif method == "s256":
            params["code_challenge_method"] = "S256"
        response = await client.get("/mcp/authorize", params=params)
        assert response.status_code == 302, response.text
        location = response.headers["location"]
        if method == "s256":
            assert location.startswith(f"{BASE}/mcp/consent?txn_id="), location
            return
        assert location.startswith(NATIVE_CB + "?"), location
        back = _query(location)
        assert back["error"] == "invalid_request"
        assert back["state"] == "client-state"


# --- the unregistered-client guidance points at a document that exists ----------------------


async def test_an_unregistered_client_is_pointed_at_the_root_discovery_document():
    """FastMCP's authorize handler answers an unknown client with guidance: the
    registration endpoint and the authorization-server document. The document
    it named lived under the issuer path — the child alias this instance
    prunes — so the recovery instruction was a 404 exactly when a client had
    lost its registration (Codex #212 round 6, f19). The pointer is now the
    canonical root document, and it answers 200; the HTML page for a browser
    is the control."""
    async with oauth_app(FakeIdp()) as (_, client):
        _, challenge = _pkce()
        params = {
            "client_id": "nobody-registered-this",
            "response_type": "code",
            "redirect_uri": NATIVE_CB,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "client-state",
        }
        guided = await client.get(
            "/mcp/authorize", params=params, headers={"Accept": "application/json"}
        )
        assert guided.status_code == 400, guided.text
        body = guided.json()
        assert body["registration_endpoint"] == f"{BASE}/mcp/register"
        assert body["authorization_server_metadata"] == (
            f"{BASE}/.well-known/oauth-authorization-server/mcp"
        )
        document = await client.get(body["authorization_server_metadata"].removeprefix(BASE))
        assert document.status_code == 200
        assert document.json()["registration_endpoint"] == body["registration_endpoint"]
        page = await client.get("/mcp/authorize", params=params, headers={"Accept": "text/html"})
        assert page.status_code == 400
        assert page.headers["content-type"].startswith("text/html")


# --- Codex #212 round 7: admission, decoding, cardinality and the SDK hand-off together -------
#
# Round 6 owned the boundary field by field and left three of its own mistakes at
# the seam: the guard chose *whether to run* by a case-sensitive prefix of the
# media type; its multiplicity rule had one exception it did not know about
# (RFC 8707's `resource`); and the assertion admission let the SDK select an
# assertion beside a second credential, and — on a public client — ignore it.


FOREIGN_RESOURCE = "https://other.example/mcp"


async def _handle(client, fake: FakeIdp, endpoint: str) -> tuple[str, list[tuple[str, str]], dict]:
    """A public DCR client with the handle `endpoint` needs — a client id for
    the authorization request, a code for the exchange, a token for the
    revocation — and the endpoint's valid form as ordered pairs."""
    if endpoint == "authorize":
        registered = await client.post(
            "/mcp/register", json={**REGISTRATION, "token_endpoint_auth_method": "none"}
        )
        client_id = registered.json()["client_id"]
        _, challenge = _pkce()
        pairs = [
            ("client_id", client_id),
            ("response_type", "code"),
            ("redirect_uri", NATIVE_CB),
            ("code_challenge", challenge),
            ("code_challenge_method", "S256"),
            ("state", "client-state"),
            ("scope", "openid"),
        ]
        return client_id, pairs, {}
    client_id, code, verifier, _ = await _public_grant(client, fake)
    exchange = [
        ("grant_type", "authorization_code"),
        ("code", code),
        ("redirect_uri", NATIVE_CB),
        ("client_id", client_id),
        ("code_verifier", verifier),
    ]
    if endpoint == "token":
        return client_id, exchange, {}
    exchanged = await client.post("/mcp/token", data=dict(exchange))
    assert exchanged.status_code == 200, exchanged.text
    tokens = exchanged.json()
    if endpoint == "refresh":
        fake.next_refresh = _provider_refresh_for(fake)
        refresh = [
            ("grant_type", "refresh_token"),
            ("refresh_token", tokens["refresh_token"]),
            ("client_id", client_id),
        ]
        return client_id, refresh, tokens
    return client_id, [("token", tokens["access_token"]), ("client_id", client_id)], tokens


def _path(endpoint: str) -> str:
    return "/mcp/token" if endpoint == "refresh" else f"/mcp/{endpoint}"


def _succeeded(endpoint: str, response) -> bool:
    if endpoint == "authorize":
        return response.status_code == 302 and response.headers["location"].startswith(
            f"{BASE}/mcp/consent?txn_id="
        )
    return response.status_code == 200


@pytest.mark.parametrize("representation", ["mixed_case", "charset", "multipart", "json"])
@pytest.mark.parametrize("endpoint", ["authorize", "token", "revoke"])
async def test_request_decoding_applies_to_every_body_representation(endpoint, representation):
    """RFC 9110 §8.3.1: a media type's name is case-insensitive and its
    parameters are not part of it; RFC 6749 §4.1.3: the body is
    `application/x-www-form-urlencoded`. The guard's contract holds under
    `Application/X-Www-Form-Urlencoded` (a repeated `client_id` is still
    `400 invalid_request`, the handle intact) and under `; charset=UTF-8` (the
    control: processed normally); a `multipart/form-data` or JSON body is
    `400 invalid_request` before the SDK parses it, the handle intact, and
    the same request form-encoded then succeeds. The reviewed head chose
    whether to run by a case-sensitive `startswith`, so the mixed-case and
    multipart bodies — both of which the SDK parses — redirected, minted
    and revoked around the guard (Codex #212 round 7, f20)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id, pairs, tokens = await _handle(client, fake, endpoint)
        path = f"/mcp/{endpoint}"
        if representation == "mixed_case":
            body, _ = _encoded([("client_id", "someone-else")] + pairs)
            refused = await client.post(
                path, content=body, headers={"Content-Type": "Application/X-Www-Form-Urlencoded"}
            )
            expected_description = "parameter repeated: client_id"
        elif representation == "multipart":
            refused = await client.post(path, files={name: (None, value) for name, value in pairs})
            assert refused.request.headers["content-type"].startswith("multipart/form-data")
            expected_description = "the request body must be application/x-www-form-urlencoded"
        elif representation == "json":
            refused = await client.post(path, json=dict(pairs))
            expected_description = "the request body must be application/x-www-form-urlencoded"
        else:
            body, _ = _encoded(pairs)
            done = await client.post(
                path,
                content=body,
                headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
            )
            assert _succeeded(endpoint, done), done.text[:300]
            if endpoint == "revoke":
                assert not grant_records(await _state_rows())
            return
        assert refused.status_code == 400, (representation, refused.status_code, refused.text)
        assert "location" not in refused.headers
        assert refused.json()["error"] == "invalid_request"
        assert refused.json()["error_description"].startswith(expected_description)
        assert refused.headers.get_list("cache-control") == ["no-store"]
        if endpoint == "revoke":
            assert grant_records(await _state_rows())
            assert (await initialize(client, tokens["access_token"])).status_code == 200
        body, _ = _encoded(pairs)
        done = await client.post(
            path, content=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        assert _succeeded(endpoint, done), done.text[:300]
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())
    if endpoint == "token":
        assert len(await _events(audit.MCP_GRANT_ISSUED)) == 1


@pytest.mark.parametrize(
    "shape",
    ["identical", "spellings", "foreign_first", "foreign_last", "foreign_only", "unparseable"],
)
@pytest.mark.parametrize("endpoint", ["authorize", "token"])
async def test_the_resource_indicator_is_a_set(endpoint, shape):
    """RFC 8707 §2: `resource` may appear more than once, so it is the one
    parameter exempt from the repetition rule — and the set is judged as a
    set. Identical values, or several spellings of this server's own
    resource (with and without the trailing slash, with a query — FastMCP's
    comparison), are one effective target and the request proceeds; a set
    naming any other target, before or after the local one, or alone, is
    `invalid_target` — at `/authorize` the SDK's own error redirect to the
    registered callback with the state (RFC 8707 §2.1 through RFC 6749
    §4.1.2.1), no transaction created; at `/token` a direct 400, the code
    surviving to a clean exchange (§2.2: the SDK reads the field and judges
    nothing, so a foreign target at the token endpoint was accepted before
    this round); and a value that does not parse is a direct 400 on both.
    The reviewed head answered every repetition `400 invalid_request`
    "parameter repeated: resource" (Codex #212 round 7, f22)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id, pairs, _ = await _handle(client, fake, endpoint)
        local = f"{BASE}/mcp/"
        resources = {
            "identical": [local, local],
            "spellings": [local, local.rstrip("/"), local + "?kb_name=plamo"],
            "foreign_first": [FOREIGN_RESOURCE, local],
            "foreign_last": [local, FOREIGN_RESOURCE],
            "foreign_only": [FOREIGN_RESOURCE],
            "unparseable": ["http://[::1", local],
        }[shape]
        sent = pairs + [("resource", value) for value in resources]
        if endpoint == "authorize":
            from urllib.parse import urlencode

            response = await client.get("/mcp/authorize?" + urlencode(sent))
        else:
            body, headers = _encoded(sent)
            response = await client.post("/mcp/token", content=body, headers=headers)
        if shape in ("identical", "spellings"):
            assert _succeeded(endpoint, response), (shape, response.status_code, response.text)
            return
        if endpoint == "authorize" and shape != "unparseable":
            assert response.status_code == 302, response.text
            location = response.headers["location"]
            assert location.startswith(NATIVE_CB + "?"), location
            back = _query(location)
            assert back["error"] == "invalid_target", back
            assert back["state"] == "client-state"
        else:
            assert response.status_code == 400, response.text
            assert "location" not in response.headers
            assert response.json()["error"] == "invalid_target", response.text
            assert response.headers.get_list("cache-control") == ["no-store"]
        if endpoint == "authorize":
            assert "mcp-oauth-transactions" not in {c for c, _ in await _state_rows()}
            return
        body, headers = _encoded(pairs)
        exchanged = await client.post("/mcp/token", content=body, headers=headers)
        assert exchanged.status_code == 200, exchanged.text
    if endpoint == "token":
        assert len(await _events(audit.MCP_GRANT_ISSUED)) == 1


@pytest.mark.parametrize("mechanism", ["secret", "basic"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_a_second_mechanism_beside_an_assertion_is_refused_before_it_is_spent(
    monkeypatch, endpoint, mechanism
):
    """RFC 6749 §2.3 and RFC 7521 §4.2.1: one client authentication mechanism
    per request, and the error for more is `invalid_client`. A valid
    `private_key_jwt` assertion beside a `client_secret`, or beside
    `Authorization: Basic`, is `401 invalid_client` on both endpoints with
    the grant intact and no provider call — and the refusal spends nothing:
    the **same assertion** on a corrected request then succeeds. A 401 to a
    client that used the `Authorization` header carries `WWW-Authenticate`
    in the scheme it used (RFC 6749 §5.2, adopted by RFC 7009 §2.2.1); one
    that did not carries none. The reviewed head verified the assertion,
    ignored the second credential, and minted or revoked (Codex #212 round 7,
    f24)."""
    key = cimd(monkeypatch, "private_key_jwt")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        credential = {
            "client_assertion_type": ASSERTION_TYPE,
            "client_assertion": signed(key, CIMD_ID, audience),
        }
        headers: dict[str, str] = {}
        if mechanism == "secret":
            competing = {**credential, "client_secret": "stray"}
        else:
            competing = dict(credential)
            headers["Authorization"] = "Basic " + base64.b64encode(b"other:wrong").decode()
        asked_before = list(fake.token_requests)
        refused = await _endpoint_request(
            client, endpoint, tokens, fake, competing, headers=headers
        )
        assert refused.status_code == 401, (refused.status_code, refused.text[:300])
        assert refused.json()["error"] == "invalid_client"
        assert refused.headers.get_list("cache-control") == ["no-store"]
        if mechanism == "basic":
            assert refused.headers["www-authenticate"] == f'Basic realm="{BASE}/mcp"'
        else:
            assert "www-authenticate" not in refused.headers
        assert grant_records(await _state_rows())
        assert fake.token_requests == asked_before
        assert fake.revoked == []
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        accepted = await _endpoint_request(client, endpoint, tokens, fake, credential)
        assert accepted.status_code == 200, accepted.text[:300]
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())
    assert not await _events(audit.MCP_IDENTITY_REFUSED)


@pytest.mark.parametrize("kind", ["dcr", "cimd_none"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_an_assertion_from_a_client_not_registered_for_it_is_refused(
    monkeypatch, endpoint, kind
):
    """Presenting an assertion is a request to be authenticated by it, and a
    public client — a dynamically registered one, or a CIMD client whose
    document says `none` — has no key the server could verify one against:
    a well-formed assertion under a key of the client's own choosing is
    `401 invalid_client` on both endpoints, and the same handle on the
    client's registered method (the client id alone) then succeeds. The
    reviewed head's SDK selected public-client authentication and accepted
    the request with the assertion unread, which made call 14's "judged in
    full whatever its method" true of a private client only (Codex #212
    round 7, under call 14)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        if kind == "dcr":
            client_id, exchange, _ = await _handle(client, fake, "token")
            exchanged = await client.post("/mcp/token", data=dict(exchange))
            assert exchanged.status_code == 200, exchanged.text
            tokens = exchanged.json()
        else:
            cimd(monkeypatch, "none")
            client_id = CIMD_ID
            tokens = await cimd_link(client, fake, None)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        stranger = RSAKey.generate_key(2048, parameters={"kid": "the-client-s-own-idea"})
        credential = {
            "client_assertion_type": ASSERTION_TYPE,
            "client_assertion": assertion(stranger, client_id, audience),
        }
        refused = await _endpoint_request(
            client, endpoint, tokens, fake, credential, client_id=client_id
        )
        assert refused.status_code == 401, (refused.status_code, refused.text[:300])
        assert refused.json()["error"] == "invalid_client"
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        accepted = await _endpoint_request(client, endpoint, tokens, fake, {}, client_id=client_id)
        assert accepted.status_code == 200, accepted.text[:300]
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())


# --- Codex #212 round 8: admitted once — recognised fields, every credential, one snapshot --
#
# Round 7 owned the boundary's decisions and left each as a precheck in front of
# something that decided again: a resource comparison borrowed from FastMCP that
# erased what it should have compared, a repetition rule over every name where
# the protocol says to ignore the unknown ones, an authenticator that read one
# `Authorization` occurrence and delegated the rest to an SDK that read none, and
# a client looked up twice. The rows below are the invariant: a request is
# admitted once, from its recognised fields and every credential occurrence,
# against one client snapshot, with the resource decision carried through.


@pytest.mark.parametrize(
    "value",
    [
        "fragment",
        "empty_fragment",
        "relative",
        "tab_in_authority",
        "cr_in_path",
        "leading_nul",
        "bad_percent",
        "unescaped_space",
        "path_parameter",
        "host_case",
        "scheme_case",
        "encoded_query",
    ],
)
@pytest.mark.parametrize("endpoint", ["authorize", "token", "refresh"])
async def test_a_resource_is_compared_on_the_whole_uri(endpoint, value):
    """RFC 8707 §2: the value is an absolute URI without a fragment — RFC
    3986's grammar, judged on the decoded string before any parser — and it
    names this server or it does not. Malformed, a direct `400 invalid_target`
    on every endpoint: a fragment (`#other`, or the empty `#`), a value with
    no scheme, a tab in the authority, a carriage return in the path, a
    leading NUL, an invalid percent-escape and an unescaped space in the
    query (round 9, f31: `urlsplit` had accepted every one of these, some by
    stripping the character, and a query the comparison ignores was never
    checked). Another target — at `/authorize` the error redirect with the
    state and no transaction, at the code exchange and at a refresh a direct
    400, the handle surviving to a corrected request: a path carrying
    `;different-resource`, and the host spelled differently from the
    protected-resource document (the authority compares as written). This
    server: the scheme spelled in upper case (case-folded, as FastMCP's
    normaliser behind the hand-off folds it too — round 9's correction of the
    wording) and a query with a valid percent-escape. The reviewed head of
    round 8 shared FastMCP's normaliser, which dropped the fragment and the
    path's parameters before comparing, so three of Codex's values opened a
    transaction and minted (Codex #212 round 8, f27)."""
    local = f"{BASE}/mcp/"
    resources = {
        "fragment": local + "#other",
        "empty_fragment": local + "#",
        "relative": "/mcp/",
        "tab_in_authority": "http://local\thost/mcp/",
        "cr_in_path": "http://localhost/m\rcp/",
        "leading_nul": "\x00" + local,
        "bad_percent": local + "?x=%zz",
        "unescaped_space": local + "?x=a b",
        "path_parameter": local + ";different-resource",
        "host_case": local.replace("localhost", "LOCALHOST"),
        "scheme_case": local.replace("http://", "HTTP://"),
        "encoded_query": local + "?x=a%20b",
    }
    malformed = value in (
        "fragment",
        "empty_fragment",
        "relative",
        "tab_in_authority",
        "cr_in_path",
        "leading_nul",
        "bad_percent",
        "unescaped_space",
    )
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id, pairs, _ = await _handle(client, fake, endpoint)
        sent = pairs + [("resource", resources[value])]
        if endpoint == "authorize":
            from urllib.parse import urlencode

            response = await client.get("/mcp/authorize?" + urlencode(sent))
        else:
            body, headers = _encoded(sent)
            response = await client.post("/mcp/token", content=body, headers=headers)
        if value in ("scheme_case", "encoded_query"):
            assert _succeeded(endpoint, response), (value, response.status_code, response.text)
            return
        if endpoint == "authorize" and not malformed:
            assert response.status_code == 302, response.text
            location = response.headers["location"]
            assert location.startswith(NATIVE_CB + "?"), location
            back = _query(location)
            assert back["error"] == "invalid_target", back
            assert back["state"] == "client-state"
        else:
            assert response.status_code == 400, (value, response.status_code, response.text)
            assert "location" not in response.headers
            assert response.json()["error"] == "invalid_target", response.text
            assert response.headers.get_list("cache-control") == ["no-store"]
        if endpoint == "authorize":
            assert "mcp-oauth-transactions" not in {c for c, _ in await _state_rows()}
            return
        body, headers = _encoded(pairs)
        done = await client.post("/mcp/token", content=body, headers=headers)
        assert done.status_code == 200, done.text


@pytest.mark.parametrize("endpoint", ["authorize", "token", "revoke"])
async def test_an_unknown_parameter_is_ignored_however_often_it_appears(endpoint):
    """RFC 6749 §3.1 as corrected by erratum 5708: the prohibition on
    repeating a parameter covers the parameters the protocol defines;
    unrecognised extension parameters are ignored — one of them or two.
    `x_vendor_hint` and `audience` twice each, on every endpoint, and the
    request proceeds. The reviewed head's repetition rule counted every
    name and answered `400 invalid_request` (Codex #212 round 8, f28)."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        _, pairs, _ = await _handle(client, fake, endpoint)
        extensions = [
            ("x_vendor_hint", "one"),
            ("x_vendor_hint", "two"),
            ("audience", "one"),
            ("audience", "two"),
        ]
        body, headers = _encoded(pairs + extensions)
        done = await client.post(_path(endpoint), content=body, headers=headers)
        assert _succeeded(endpoint, done), (done.status_code, done.text[:300])
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())


async def test_a_repeated_recognised_credential_is_still_refused():
    """The other half of the erratum: a parameter the endpoint *does*
    recognise keeps its cardinality — `client_secret` twice at `/token` is
    `400 invalid_request` with the code surviving, exactly as `client_id`
    twice is."""
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        _, pairs, _ = await _handle(client, fake, "token")
        body, headers = _encoded(pairs + [("client_secret", "a"), ("client_secret", "b")])
        refused = await client.post("/mcp/token", content=body, headers=headers)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"] == "invalid_request"
        assert refused.json()["error_description"].startswith("parameter repeated: client_secret")
        body, headers = _encoded(pairs)
        assert (await client.post("/mcp/token", content=body, headers=headers)).status_code == 200


async def _public_handle(client, fake: FakeIdp, kind: str, endpoint: str):
    """A public client of either kind with the handle `endpoint` needs, and
    the endpoint's valid pairs: a DCR client through `_handle`; a CIMD
    client whose document says `none` through the browser leg."""
    if kind == "dcr":
        return await _handle(client, fake, endpoint)
    if endpoint == "token":
        code, verifier = await browser_leg(client, fake, CIMD_ID, CIMD_CB)
        return (
            CIMD_ID,
            [
                ("grant_type", "authorization_code"),
                ("code", code),
                ("redirect_uri", CIMD_CB),
                ("client_id", CIMD_ID),
                ("code_verifier", verifier),
            ],
            {},
        )
    tokens = await cimd_link(client, fake, None)
    if endpoint == "refresh":
        fake.next_refresh = _provider_refresh_for(fake)
        return (
            CIMD_ID,
            [
                ("grant_type", "refresh_token"),
                ("refresh_token", tokens["refresh_token"]),
                ("client_id", CIMD_ID),
            ],
            tokens,
        )
    return CIMD_ID, [("token", tokens["access_token"]), ("client_id", CIMD_ID)], tokens


@pytest.mark.parametrize("scheme", ["Basic", "Bearer", "Unknown"])
@pytest.mark.parametrize("endpoint", ["token", "refresh", "revoke"])
@pytest.mark.parametrize("kind", ["dcr", "cimd_none"])
async def test_an_http_authentication_attempt_is_refused_on_a_public_client(
    monkeypatch, kind, endpoint, scheme
):
    """RFC 6749 §2.3 and §5.2: client authentication included in a request
    is evaluated, and an unsupported method is `invalid_client`; a request
    that used the `Authorization` header gets a 401 with the matching
    challenge. No HTTP scheme is admitted by this contract, so `Basic`,
    `Bearer` or an unknown scheme beside a public client's valid code,
    refresh token or revocation token — a DCR client, or a CIMD client whose
    document says `none` — is `401 invalid_client` with `WWW-Authenticate` in
    that scheme, the handle intact and then redeemed on the client id alone.
    The reviewed head's authenticator returned to the SDK's `none` branch
    when no assertion was presented, and the SDK ignored the header: all
    eighteen cells succeeded (Codex #212 round 8, f29)."""
    if kind == "cimd_none":
        cimd(monkeypatch, "none")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        client_id, pairs, tokens = await _public_handle(client, fake, kind, endpoint)
        credential = (
            base64.b64encode(b"somebody-else:wrong-secret").decode()
            if scheme == "Basic"
            else "invalid-credential"
        )
        body, headers = _encoded(pairs)
        refused = await client.post(
            _path(endpoint),
            content=body,
            headers={**headers, "Authorization": f"{scheme} {credential}"},
        )
        assert refused.status_code == 401, (refused.status_code, refused.text[:300])
        assert refused.json()["error"] == "invalid_client"
        assert refused.headers["www-authenticate"] == f'{scheme} realm="{BASE}/mcp"'
        assert refused.headers.get_list("cache-control") == ["no-store"]
        if endpoint == "revoke":
            assert grant_records(await _state_rows())
            assert (await initialize(client, tokens["access_token"])).status_code == 200
        done = await client.post(_path(endpoint), content=body, headers=headers)
        assert _succeeded(endpoint, done), (done.status_code, done.text[:300])
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())
    assert not await _events(audit.MCP_IDENTITY_REFUSED)


@pytest.mark.parametrize("order", ["empty_first", "basic_first"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_every_authorization_occurrence_counts(monkeypatch, endpoint, order):
    """RFC 7235 lets `Authorization` appear more than once; the credential
    inventory reads every occurrence. A valid assertion beside two raw
    `Authorization` fields — an empty one and `Basic eDp5`, in either order —
    is `401 invalid_client` with the `Basic` challenge, the grant intact, and
    the same assertion then succeeds. The reviewed head read the first
    occurrence only, so an empty first field hid the second (Codex #212
    round 8, f29)."""
    key = cimd(monkeypatch, "private_key_jwt")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        credential = {
            "client_assertion_type": ASSERTION_TYPE,
            "client_assertion": signed(key, CIMD_ID, audience),
        }
        fields = [("Authorization", ""), ("Authorization", "Basic eDp5")]
        if order == "basic_first":
            fields.reverse()
        refused = await _endpoint_request(
            client, endpoint, tokens, fake, credential, headers=fields
        )
        assert refused.status_code == 401, (refused.status_code, refused.text[:300])
        assert refused.json()["error"] == "invalid_client"
        assert refused.headers["www-authenticate"] == f'Basic realm="{BASE}/mcp"'
        assert grant_records(await _state_rows())
        accepted = await _endpoint_request(client, endpoint, tokens, fake, credential)
        assert accepted.status_code == 200, accepted.text[:300]


@pytest.mark.parametrize("flip", ["none_then_private", "private_then_none"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_the_client_record_is_one_snapshot_per_request(monkeypatch, endpoint, flip):
    """A CIMD document served with `no-store` is fetched on every lookup, so a
    document that changes between two lookups within one request would be
    judged by two records: the reviewed head admitted the method from the
    first and let the SDK select from the second — `private_key_jwt` then
    `none` accepted an assertion under a key the document never published.
    The record is resolved once per request now, and the method it names,
    the keys that verify the assertion and the authenticated client are that
    snapshot: a document saying `none` first and `private_key_jwt` after
    refuses a valid assertion (presented to a `none` client); one saying
    `private_key_jwt` first and `none` after refuses an assertion under
    another key (the first snapshot's document verifies it). Neither
    complete record authorises either request, and mixing them no longer
    does; a stable document then accepts the client's own assertion
    (Codex #212 round 8, f30)."""
    key = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
    private_document = _cimd_document(
        token_endpoint_auth_method="private_key_jwt",
        jwks={"keys": [key.as_dict(private=False)]},
    )
    public_document = _cimd_document(token_endpoint_auth_method="none")
    played: dict = {"sequence": None, "fetches": 0}

    async def fetch(self, client_id_url: str):
        assert client_id_url == CIMD_ID
        if played["sequence"] is None:
            return private_document
        played["fetches"] += 1
        first, later = played["sequence"]
        return first if played["fetches"] == 1 else later

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        if flip == "none_then_private":
            played["sequence"] = (public_document, private_document)
            signer = key
        else:
            played["sequence"] = (private_document, public_document)
            signer = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
        credential = {
            "client_assertion_type": ASSERTION_TYPE,
            "client_assertion": assertion(signer, CIMD_ID, audience),
        }
        refused = await _endpoint_request(client, endpoint, tokens, fake, credential)
        assert refused.status_code == 401, (flip, refused.status_code, refused.text[:300])
        assert refused.json()["error"] == "invalid_client"
        assert played["fetches"] >= 1
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        played["sequence"] = None
        accepted = await _endpoint_request(
            client,
            endpoint,
            tokens,
            fake,
            {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": assertion(key, CIMD_ID, audience),
            },
        )
        assert accepted.status_code == 200, accepted.text[:300]


# --- Codex #212 round 9: the inline key set has a contract too --------------------------------


@pytest.mark.parametrize("shape", ["keys_object", "keys_string", "null_entry", "null_beside_key"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_a_malformed_inline_key_set_is_a_client_refusal(monkeypatch, endpoint, shape):
    """RFC 7517 §5 and §5.1: a JWK Set's `keys` is an array of JWK objects,
    and an entry that cannot be processed is ignored. A CIMD document whose
    inline set has `keys` as an object or a string, or holds only a null
    entry, is `401 invalid_client` on both endpoints — the grant intact, the
    handle and the **same assertion** then accepted once the document is
    sound again — where FastMCP's extraction called `.get` on the entry and
    answered 500; a null entry beside the client's key is skipped, as the
    remote path skips it, and the request succeeds (Codex #212 round 9,
    f32)."""
    key = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
    public = key.as_dict(private=False)
    sound = _cimd_document(token_endpoint_auth_method="private_key_jwt", jwks={"keys": [public]})
    shapes = {
        "keys_object": {"keys": {"one": public}},
        "keys_string": {"keys": "x"},
        "null_entry": {"keys": [None]},
        "null_beside_key": {"keys": [None, public]},
    }
    served = {"document": sound}

    async def fetch(self, client_id_url: str):
        assert client_id_url == CIMD_ID
        return served["document"]

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        credential = {
            "client_assertion_type": ASSERTION_TYPE,
            "client_assertion": assertion(key, CIMD_ID, audience),
        }
        served["document"] = _cimd_document(
            token_endpoint_auth_method="private_key_jwt", jwks=shapes[shape]
        )
        response = await _endpoint_request(client, endpoint, tokens, fake, credential)
        if shape == "null_beside_key":
            assert response.status_code == 200, (shape, response.status_code, response.text[:300])
            if endpoint == "revoke":
                assert not grant_records(await _state_rows())
            return
        assert response.status_code == 401, (shape, response.status_code, response.text[:300])
        assert response.json()["error"] == "invalid_client"
        assert response.headers.get_list("cache-control") == ["no-store"]
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        served["document"] = sound
        accepted = await _endpoint_request(client, endpoint, tokens, fake, credential)
        assert accepted.status_code == 200, accepted.text[:300]
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())


# --- Codex #212 round 10: the selected key keeps its authorization -----------------------------


JWKS_URI = "https://client.example/jwks.json"


def _restricted(public: dict, restriction: str) -> dict:
    """The client's public JWK with one declared restriction, or the explicit
    permissive metadata."""
    return {
        "alg_rs512": {**public, "alg": "RS512"},
        "use_enc": {**public, "use": "enc"},
        "key_ops_sign": {**public, "key_ops": ["sign"]},
        "explicit_ok": {**public, "alg": "RS256", "use": "sig", "key_ops": ["verify"]},
    }[restriction]


def _play_key_sets(monkeypatch, sound: dict, source: str):
    """A CIMD document whose key set is `sound` — inline, or fetched from
    `JWKS_URI` with the JWKS fetch played below FastMCP's verifier (its
    SSRF-safe fetch is not exercised here; its cache, selection and
    verification are) — returned as a mutable holder the test can point at
    another set, and a fetch counter."""
    served = {"jwks": sound, "fetches": 0, "source": "inline"}

    def document():
        # The link is made through the inline set whatever `source` is, so a
        # fetched set's verifier meets the set under test on its first fetch
        # (FastMCP caches a fetched set for an hour); the test switches the
        # source after linking.
        if served["source"] == "inline":
            return _cimd_document(token_endpoint_auth_method="private_key_jwt", jwks=served["jwks"])
        return _cimd_document(token_endpoint_auth_method="private_key_jwt", jwks_uri=JWKS_URI)

    async def fetch(self, client_id_url: str):
        assert client_id_url == CIMD_ID
        return document()

    async def fetch_jwks(self):
        served["fetches"] += 1
        return served["jwks"]

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)
    monkeypatch.setattr(JWTVerifier, "_fetch_jwks", fetch_jwks)
    return served


@pytest.mark.parametrize(
    "restriction", ["alg_rs512", "use_enc", "key_ops_sign", "explicit_ok", "mixed_set"]
)
@pytest.mark.parametrize("source", ["inline", "remote"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_a_published_key_s_restrictions_are_enforced(
    monkeypatch, endpoint, source, restriction
):
    """RFC 7517 §4.2–§4.4 and RFC 8725 §3.1: a JWK's `alg`, `use` and
    `key_ops` are the key's authorization, and the key that verifies an
    assertion must be authorized for that. The client's own key, published
    with `alg: RS512`, `use: enc` or `key_ops: ["sign"]`, refuses its RS256
    assertion — `401 invalid_client` on both endpoints, inline and fetched,
    with the grant intact and the **same assertion and handle** accepted
    once the published metadata is corrected; explicit permissive metadata
    is accepted, and a set holding an encryption key beside the signing key
    admits the signing key by `kid`. The reviewed head converted the
    selected JWK to a PEM before verifying, on both paths, so the metadata
    never reached the verifier and a mathematically valid signature
    authenticated under a key that excluded it (Codex #212 round 10, f33)."""
    key = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
    public = key.as_dict(private=False)
    sound = {"keys": [public]}
    served = _play_key_sets(monkeypatch, sound, source)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (live, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        credential = {
            "client_assertion_type": ASSERTION_TYPE,
            "client_assertion": assertion(key, CIMD_ID, audience),
        }
        served["source"] = source
        if restriction == "mixed_set":
            other = RSAKey.generate_key(2048, parameters={"kid": "enc-key"}).as_dict(private=False)
            served["jwks"] = {"keys": [{**other, "use": "enc"}, {**public, "use": "sig"}]}
        else:
            served["jwks"] = {"keys": [_restricted(public, restriction)]}
        response = await _endpoint_request(client, endpoint, tokens, fake, credential)
        if restriction in ("explicit_ok", "mixed_set"):
            assert response.status_code == 200, (
                restriction,
                response.status_code,
                response.text[:300],
            )
            if endpoint == "revoke":
                assert not grant_records(await _state_rows())
            return
        assert response.status_code == 401, (restriction, response.status_code, response.text[:300])
        assert response.json()["error"] == "invalid_client"
        assert response.headers.get_list("cache-control") == ["no-store"]
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        served["jwks"] = sound
        if source == "remote":
            # The refusing key is what the verifier cached, for FastMCP's hour:
            # the corrected set is met by a fresh verifier (the cache dropped),
            # not by a restriction lifted from the cached key.
            getattr(live.state, MCP_OAUTH_ATTR).proxy.assertion_validator._verifier_cache.clear()
        accepted = await _endpoint_request(client, endpoint, tokens, fake, credential)
        assert accepted.status_code == 200, accepted.text[:300]
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())


@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_a_cached_remote_key_keeps_its_restrictions(monkeypatch, endpoint):
    """The restriction lives on the key FastMCP caches, not only on the fetch:
    a fetched set whose key says `use: enc` is refused on the first request
    (the fetch) and on the second (the cache, no fetch), and a key fetched
    sound stays sound within FastMCP's cache lifetime even if the published
    set changes — the same TTL semantics as the key material's rotation,
    named as such in the PR body."""
    key = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
    public = key.as_dict(private=False)
    served = _play_key_sets(monkeypatch, {"keys": [public]}, "remote")
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL

        def credential():
            return {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": assertion(key, CIMD_ID, audience),
            }

        served["source"] = "remote"
        served["jwks"] = {"keys": [{**public, "use": "enc"}]}
        fetches_before = served["fetches"]
        first = await _endpoint_request(client, endpoint, tokens, fake, credential())
        assert first.status_code == 401, first.text[:300]
        assert served["fetches"] == fetches_before + 1
        second = await _endpoint_request(client, endpoint, tokens, fake, credential())
        assert second.status_code == 401, second.text[:300]
        assert served["fetches"] == fetches_before + 1, "the cached key, not a fetch, refused"
        assert grant_records(await _state_rows())


# --- Codex #212 round 11: the record the kid named; the remote path's usability predicate -----


def _assertion_with_kid(key: RSAKey, kid: str | None, client_id: str, audience: str) -> str:
    """An assertion signed by `key` whose header names `kid` — or names none."""
    now = int(time.time())
    body = {
        "iss": client_id,
        "sub": client_id,
        "aud": audience,
        "iat": now,
        "exp": now + 120,
        "jti": secrets.token_hex(8),
    }
    header = {"alg": "RS256"} if kid is None else {"alg": "RS256", "kid": kid}
    return jwt.encode(header, body, key)


@pytest.mark.parametrize("order", ["allowed_first", "selected_first"])
@pytest.mark.parametrize("source", ["inline", "remote"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_the_key_selected_by_kid_is_the_one_judged(monkeypatch, endpoint, source, order):
    """RFC 7517 §4.5 and §5.1: `kid` is how a specific key is selected, and a
    set's order implies nothing. One RSA material published twice —
    `allowed-copy` with `use: sig`, `selected-copy` with `use: enc` — and an
    assertion naming `selected-copy` is `401 invalid_client` on both
    endpoints, inline and fetched, whichever copy comes first, with no
    provider call and the grant intact; the same handle with an assertion
    naming `allowed-copy` then succeeds. Round 10's repair found the selected
    key by its material and so judged the *first* copy with that material:
    with the allowed copy first, all four requests were accepted (Codex #212
    round 11, f34)."""
    key = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
    public = key.as_dict(private=False)
    public.pop("kid", None)
    allowed = {**public, "kid": "allowed-copy", "use": "sig"}
    selected = {**public, "kid": "selected-copy", "use": "enc"}
    served = _play_key_sets(monkeypatch, {"keys": [allowed]}, source)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        served["source"] = source
        served["jwks"] = {
            "keys": [allowed, selected] if order == "allowed_first" else [selected, allowed]
        }
        asked_before = list(fake.token_requests)
        refused = await _endpoint_request(
            client,
            endpoint,
            tokens,
            fake,
            {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": _assertion_with_kid(key, "selected-copy", CIMD_ID, audience),
            },
        )
        assert refused.status_code == 401, (order, refused.status_code, refused.text[:300])
        assert refused.json()["error"] == "invalid_client"
        assert fake.token_requests == asked_before
        assert fake.revoked == []
        assert grant_records(await _state_rows())
        assert (await initialize(client, tokens["access_token"])).status_code == 200
        accepted = await _endpoint_request(
            client,
            endpoint,
            tokens,
            fake,
            {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": _assertion_with_kid(key, "allowed-copy", CIMD_ID, audience),
            },
        )
        assert accepted.status_code == 200, accepted.text[:300]
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())


@pytest.mark.parametrize("shape", ["unsupported_kty", "incomplete_rsa"])
@pytest.mark.parametrize("source", ["inline", "remote"])
@pytest.mark.parametrize("endpoint", ["token", "revoke"])
async def test_an_unusable_inline_key_is_ignored_before_the_fallback(
    monkeypatch, endpoint, source, shape
):
    """RFC 7517 §5: a JWK with an unsupported `kty` or a missing required
    member is ignored. One usable RSA key published without a `kid`, beside
    an `OKP` object or an RSA object missing `n`, verifies an assertion that
    names no `kid` — the single-key fallback sees one usable key — on both
    endpoints, inline as on the fetched path, which skipped the unusable
    object already. Round 9's inline filter kept every object, so the inline
    set counted two and refused what the fetched set accepted (Codex #212
    round 11, f35)."""
    key = RSAKey.generate_key(2048, parameters={"kid": "client-key"})
    public = key.as_dict(private=False)
    public.pop("kid", None)
    unusable = {
        "unsupported_kty": {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "kid": "other",
        },
        "incomplete_rsa": {"kty": "RSA", "e": "AQAB", "kid": "broken"},
    }[shape]
    served = _play_key_sets(monkeypatch, {"keys": [public]}, source)
    fake = FakeIdp()
    await _bind_owner()
    async with oauth_app(fake) as (_, client):
        tokens = await cimd_link(client, fake, key)
        audience = TOKEN_URL if endpoint == "token" else REVOKE_URL
        served["source"] = source
        served["jwks"] = {"keys": [unusable, public]}
        accepted = await _endpoint_request(
            client,
            endpoint,
            tokens,
            fake,
            {
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": _assertion_with_kid(key, None, CIMD_ID, audience),
            },
        )
        assert accepted.status_code == 200, (shape, accepted.status_code, accepted.text[:300])
        if endpoint == "revoke":
            assert not grant_records(await _state_rows())
