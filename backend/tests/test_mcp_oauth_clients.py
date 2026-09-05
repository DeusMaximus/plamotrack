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
    return client_id, [("token", tokens["access_token"]), ("client_id", client_id)], tokens


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
