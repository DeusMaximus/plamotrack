"""MCP OAuth — FastMCP's OAuth proxy in front of the configured OpenID Connect
provider, on the `/mcp` mount (§5.5 family 8; §5.6 proxy trust, open redirect,
credential leakage, safe failure; §5.9 items 5 and 7; M6-7, #192).

An MCP client that speaks OAuth — Claude web, ChatGPT web, MCP Inspector, any
DCR-capable native client — discovers this instance as an authorization server
(the three root documents `main.py` installs), registers or presents its
metadata document, and is sent through a consent page to the **same provider
and client** the browser login uses (#191). The provider's tokens never leave
the process: FastMCP issues its own access/refresh pair to the client and keeps
the upstream set encrypted in the state table. What this module adds to
FastMCP's `OAuthProxy` is the plamotrack policy, each piece on a documented
extension point (#30's failure rule — the #190 spike measured that nothing
needs protocol code) — and, since the Codex review of PR #212, the policy is
applied to the **grant as one state machine** (issuance, refresh, verification,
revocation) rather than to the entry points one at a time:

- **The owner binding is grant state** (§5.6 open redirect; T6). At issuance
  `IdTokenOwnerCheck` verifies the provider's **id_token** — signature against
  the provider's JWKS, claims through the one validator the browser login uses
  (`validate_id_token_claims`, with no nonce: the proxy sends none) — and
  requires `(iss, sub)` to equal the bound owner **before** any token is minted
  (`exchange_authorization_code`): a stranger who signs in at the provider gets
  `invalid_grant` at `/token`, an audit row, and nothing stored (the spike's
  finding 7a); a token without `sub` is refused, never mapped by email (7b).
  The verified `(iss, sub)` — an `OwnerBinding` — is then carried in every
  token the proxy issues (FastMCP's `upstream_claims`, under its own
  signature) and compared with the owner row on **every request**
  (`load_access_token`), so a rebind refuses an issued token at the next
  request. The id_token is never re-expired: the binding lives on the **grant
  record** too (`GrantRecord.owner`, with the digest of the id_token last
  verified), and the record gate (`GrantRecords`) admits a refresh's upstream
  set — the client's exchange or the transparent refresh behind a request —
  only with an identity that binding names: the id_token already verified, or
  a new one that passes the same check in full and names **the same `(iss,
  sub)` the record holds** — continuity with the identity that authorized
  this grant, not merely the owner now (round 3, f10: the two differ for
  the length of a rebind) — else the grant **ends** with nothing of the
  response stored (round 2, f7); a refresh that validly omits one (OpenID
  Connect Core §12.2) carries the binding forward. What bounds a grant is
  the provider's own access token,
  re-read per request and refreshed transparently; when the provider cannot
  refresh it, the grant ends with it (Codex #212 round 1, f3).
- **One transition per grant** (RFC 6749 §4.1.2, RFC 9700 §4.14.2, RFC 7009
  §2.1). FastMCP's get→mint→delete of an authorization code, its
  get→refresh→rotate of a refresh token, the transparent refresh behind a
  request and a revocation are not atomic across requests or processes;
  `_one_transition` runs each under a transaction-scoped Postgres advisory
  lock on the grant — the record's id, or the code before a record exists —
  the write gate's shape (rule 7.1: taken *before* the read the decision is
  made from), so the second redeemer of a handle reads the first's deletion
  and gets `invalid_grant`, whichever process it landed on (f2), and a
  revocation and a refresh never interleave: whichever lands first, the record
  is gone afterwards (round 2, f6 — the reviewed head's revocation deleted the
  record while a refresh writer recreated it through the store's upsert).
- **Revocation is the grant's** (RFC 7009 §2.1). Whichever half a client
  presents at `/revoke`, the grant record goes — locally, first, so the answer
  does not depend on the provider — and the provider is then asked, best
  effort, to revoke *its* refresh token through the injectable upstream
  client; `auth.mcp_grant_revoked` names the client, or names the upstream
  (`ended_by=upstream_refresh`) when a refresh response that was not the
  owner's is what ended the grant. FastMCP alone deleted a refresh token's
  hash entry, left every access mapping to its hour-long TTL, and posted the
  `AccessToken.token` field upstream (f1). And the presented token is
  **located, not authorized** (round 3, f9): the SDK's revocation handler
  finds a token through the provider's `load_access_token`, which here is the
  bearer path — the upstream set refreshed, the id_token re-verified — so a
  provider whose keys could not be fetched made the lookup answer "not mine"
  and the handler's silent 200 left the grant standing. The `/revoke` route
  is built over `RevocationLookup`: the proxy's own signature and the JTI
  mapping locate the grant, the provider is asked nothing, no owner row is
  read, and the locked ending runs whatever the provider is doing.
- **Fixed scope mapping** (7c). The scope vocabulary the proxy advertises and
  forwards is the provider's (`openid`); `collection:read`/`collection:write`
  cannot be per-grant OAuth scopes on FastMCP 3.4.5 without translating in both
  directions through a private method. So every proxy-issued token is the
  owner's delegated grant with **both** collection scopes and never
  `instance:admin` — `mcp_auth.principal_from_access_token` maps `kind=mcp`
  to that, whatever the token's `scope` claim says. The mount itself requires
  no scope (`GrantVerifier` declares none), so a personal access token — whose
  scopes are its own — stays valid on `/mcp/` in OIDC mode: `load_access_token`
  routes a `ptk_` bearer to `PersonalAccessTokenVerifier` unchanged.
- **One downstream client contract** (RFC 7591 §3.2.1, RFC 6749 §2.3 and
  §3.2.1, RFC 7523 §3; round 4, f11–f13), the same in the registration
  response, the stored client, the code exchange, the refresh and the
  revocation. Every dynamically registered client is a **public** client —
  `token_endpoint_auth_method=none`, PKCE — whatever it asked for, and the
  registration response says so with no secret and no secret expiry
  (`register_client`). The choice is scope, not a claim that a secret would
  protect nothing — a confidential registration's secret would guard that
  registration's stolen refresh token — but the measured clients (#190) are
  a public DCR client and two CIMD clients, and confidential DCR would mean
  storing and comparing shared secrets, repairing the SDK authenticator's
  Basic branch and a second lifecycle matrix, for clients nobody has brought;
  the authority remains the owner's upstream login and the grant machinery.
  The SDK's handler minted a secret for any method
  but `none` and returned that object while FastMCP stored a public client,
  so a client held a `client_secret_post` credential the server never read
  (f11). A CIMD client authenticates as its document says — `none`, or
  `private_key_jwt` with the document's keys — on `/token` (FastMCP's
  authenticator) **and on `/revoke`** (`_revocation_authenticator`, the same
  class bound to the revocation endpoint's URL as the assertion's audience),
  where the plain SDK authenticator had refused the method the client linked
  with (f13). The wire forms are the RFCs': `client_id` in the form on both
  endpoints for every kind, no secret from a public client (one sent anyway
  is ignored, as the SDK does), the assertion fields for `private_key_jwt`;
  the SDK's revocation form model made `client_secret` a required field and
  refused the public form outright (f12) — `GrantRevocation` is the SDK's
  handler with `RevocationForm`, and a failed client authentication is `401
  invalid_client` on either endpoint (RFC 6749 §5.2, which RFC 7009 §2.2.1
  adopts; the SDK's two handlers disagreed). There are no `client_secret_*`
  clients under this contract, so the SDK authenticator's Basic branch — which
  wants the client id in the form beside the header — is unreachable. Two
  restrictions of this server, named as such: `client_id` is required in the
  form beside a `private_key_jwt` assertion (RFC 7521 §4.2 makes it optional;
  FastMCP's token endpoint requires it and the revocation endpoint matches),
  and an assertion is usable once **per process** — the SDK validator's
  replay cache is in memory, so a restart, or a second API process, would
  accept it again (RFC 7523 §3 makes replay tracking optional; the grant
  itself is still redeemed once, under its lock, whatever the process).
  **Discovery says the same** (round 5, f14): the two authorization-server
  documents are built here (`discovery_metadata`) and publish exactly
  `CLIENT_AUTH_METHODS` for the token endpoint and for the revocation
  endpoint and `CLIENT_ASSERTION_ALGORITHMS` as the signing algorithms,
  where the SDK's metadata advertised both shared-secret methods at the
  token endpoint, *only* the shared-secret methods at the revocation
  endpoint, and no algorithm — a client choosing from discovery had no
  usable way to revoke. And the value space of every field is the protocol's,
  unrecognised values included (round 5, f15): a `token_type_hint` the
  server does not know is ignored (RFC 7009 §2.2), never refused — the
  form's two-value enum had turned a valid revocation into `400`.
- **The protocol boundary, field by field** (round 6, f16–f19): registration
  normalisation, request decoding, assertion claims and a generated URL each
  have an owner here, because fixing the one field a review names leaves its
  siblings inherited. *Assertion claims* — `ClientAssertionAuthenticator`, on
  `/token` and `/revoke` alike, runs `validate_client_assertion_claims` on the
  assertion **before** the SDK verifies it (RFC 7523 §3, RFC 7519 §4.1: a
  JWS with an advertised `alg`, an object payload, string `iss`/`sub`/`jti`,
  `aud` a string or a list of strings, `exp` required, every NumericDate
  finite and never a boolean, `nbf` honoured with the SDK's 30 s skew), so a
  refusal is `401 invalid_client` and spends nothing — the SDK's validator
  never checked `nbf`, took booleans for dates, and used the raw `jti` as a
  dictionary key (a 500 for a list). *Registration* — `register_client`
  canonicalises the admitted metadata once and stores that same object: a
  `null` redirect list is refused (FastMCP invented `http://localhost/`),
  `response_types` and `grant_types` are what the server offers, a blank
  `scope` is the default, the display and software fields are kept. *Request
  decoding* — `ProtocolRequest`, an ASGI guard on the three endpoints a
  client drives (RFC 6749 §3.1–§3.2): a parameter repeated is
  `invalid_request` before anything is redeemed, redirected or spent (the
  SDK's `dict(form)` kept the last value); an empty value is an omitted one; a
  `grant_type` the server does not offer is `unsupported_grant_type`; an
  omitted `code_challenge_method` is `plain` (RFC 7636 §4.3), which this
  S256-only server then refuses the way it refuses `plain` — the SDK's model
  had defaulted the omission to `S256`. *The generated URL* —
  `UnregisteredClientGuidance` points an unknown client at the **root**
  authorization-server document; FastMCP's handler named the child alias this
  instance prunes. *And admission, decoding, cardinality and the SDK hand-off
  are one decision* (round 7, f20–f24, f26 — round 6's guard chose whether to
  run by a case-sensitive prefix of the media type, applied one multiplicity
  rule to a field the protocol lets a client repeat, and let the SDK select
  an assertion beside a second credential or, on a public client, ignore it):
  the media type is read as HTTP defines it and a body that is not
  form-encoded is refused before the SDK parses it; `resource` is a set —
  collapsed, every member judged by `accepts_resource` (FastMCP's own
  comparison as a predicate), a foreign set `invalid_target` in each
  endpoint's form, the `/authorize` redirect rendered by `authorize` itself
  because the SDK's vocabulary lacks the code, the `/token` refusal the
  guard's own because the SDK judges nothing there; a NumericDate has a
  range, ±2^53, judged before any float conversion; a second mechanism
  beside an assertion, and an assertion from a client not registered for
  `private_key_jwt`, are `invalid_client` before the SDK selects anything,
  and a 401 to a client that used the `Authorization` header carries its
  `WWW-Authenticate` challenge (`_challenge_on_refusal`); `jwks` with
  `jwks_uri` is `invalid_client_metadata`. *And a request is admitted once*
  (round 8, f27–f30 — each of round 7's decisions was a precheck in front of
  something that decided again): the resource comparison is this server's
  own, on the whole URI (`resource_identity`: a fragment or a missing scheme
  malformed, the path with its `;parameters`, a trailing slash and the query
  the only equivalences, scheme and authority as written), and `authorize`
  applies it behind the guard's hand-off because FastMCP's normaliser erased
  what it should have compared; each endpoint declares the parameters it
  recognises (`RECOGNISED_PARAMETERS`) and an unknown one is discarded
  before its multiplicity could refuse a request (RFC 6749 §3.1, erratum
  5708); and `ClientAssertionAuthenticator` owns client authentication end
  to end — every `Authorization` occurrence inventoried first and any one
  refused as a failed HTTP attempt, the client resolved **once** and the
  method, the verifying document and the authenticated client all that one
  snapshot (a `no-store` document that said `private_key_jwt` to the precheck
  and `none` to the SDK had authorised an assertion under a key it never
  published), FastMCP's cryptographic validator behind it. *And parsing is
  not validation* (round 9, f31–f32): the resource value is judged against
  RFC 3986's `absolute-URI` grammar (`ABSOLUTE_URI`) before `urlsplit` — a
  parser that accepted a tab in the authority, a carriage return in the
  path and a leading NUL, and never looked at the query the comparison
  ignores — and the inline key set has a contract where FastMCP's
  extraction read it (`keys` an array, entries that cannot be processed
  ignored as RFC 7517 §5.1 says, none usable a refusal — in the validator's
  own inline selection since round 11), where a `keys` object or a null
  entry had been a 500. *And the selected key keeps
  its authorization* (round 10, f33): FastMCP converted the JWK it selected
  to a PEM before verifying, on the inline and the fetched path alike, so
  the key's `alg`, `use` and `key_ops` (RFC 7517 §4.2–§4.4, RFC 8725 §3.1)
  never reached the verifier and a valid signature authenticated under a
  key that excluded it; `RestrictedKeyAssertionValidator` and
  `RestrictedKeyVerifier` hand FastMCP's own verifier the selected JWK
  itself — the record the selection *named* by the assertion's `kid`, or
  the only usable key when it names none, never the first record with that
  material (round 11, f34: two `kid`s publishing one material collapsed
  onto the first), cache and fallback included — and joserfc enforces the
  restrictions in the same decode, one cryptographic validator still; the
  inline set is filtered by the remote path's own usability predicate
  before that fallback counts it (f35); and the rule is the SDK's *remote*
  one on both paths — a named `kid` that matches nothing is a refusal
  (round 12, f36: the SDK has two rules, and its inline one fell back to
  the only key whenever no record matched, so an assertion naming an
  unpublished `kid` authenticated inline and was refused fetched).
- **Client-redirect binding per client kind** (§5.6 proxy trust; T9).
  `get_client` refuses the client FastMCP synthesises for the upstream client
  id (anyone who knows the public id could be sent anywhere — the spike's
  reproduced probe); wraps a dynamically registered client in `BoundDCRClient`,
  which checks the **registration** (exact, RFC 8252 §7.3 loopback port free)
  *and then* the operator allowlist, where FastMCP checks the allowlist
  *instead of* the registration once patterns are set; and leaves a CIMD
  client bound by its metadata document — plus the allowlist when one is
  configured, which is FastMCP's rule for every kind and is documented as
  such (`MCP_OAUTH_ALLOWED_REDIRECT_URIS`). Registration is narrowed by the
  allowlist in `register_client` already.
- **The upstream endpoints are a view of the provider's document** (§5.6 safe
  failure). `OIDCProxy` fetches discovery synchronously at construction — a
  provider that is down at start would fail the start. This subclass is an
  `OAuthProxy` whose three upstream-endpoint attributes are **properties**
  over `OidcProvider.cached_metadata` — the browser login's cached,
  issuer-checked document — so no reader in FastMCP, enumerated here or not,
  can hold a stale copy; until the document has been fetched they read as a
  name that resolves nowhere. Each entry point that reaches the provider
  resolves (fetches, if this process has not yet) before it acts and maps a
  provider it cannot reach to the protocol's own failure: `authorize` is
  `temporarily_unavailable` to the client (RFC 6749), the consent page and
  its approval and the upstream callback are a 503, a refresh exchange is
  `invalid_request`, a revocation and a transparent refresh carry on without
  the upstream half. The lifespan's warm-up fills the cache; nothing here
  blocks the start (f5: the consent approval was the reader the first head
  had not enumerated).
- **Persistence and keys** (§5.9 item 5, decided by the spike). State lives in
  `mcp_oauth_state`, a Postgres table Alembic owns with the store's own DDL,
  through `py-key-value-aio`'s adapter — so the backup set is the database plus
  `.env`, an export cannot carry it (rule 9) and `replace_all` cannot truncate
  it. Every value is Fernet-encrypted with a key HKDF-derived from
  `MCP_OAUTH_SIGNING_KEY` under a storage-specific salt; the signing key itself
  is 32 explicit random bytes, never derived from the provider's client secret
  (rotating that would otherwise empty the store). Both are installation
  identity beside `PUBLIC_BASE_URL`: a changed key or base URL means every MCP
  client relinks, and nothing else is lost (T13).

The response profile — `no-store` on every transaction and credential
response, `public, max-age=3600` on discovery — and the accepted verbs are the
registry's (`MCP_OAUTH_ROUTES`, `DISCOVERY_ROUTES`), enforced by the
`RouteBinding` on each mounted route (M6-2's design), a handler's own failure
included; `declare_child_verbs` clears the SDK routes' own method metadata so
that binding is the one boundary, as `build_mcp_app` does for the transport,
and `guard_registration_body` answers RFC 7591's `invalid_client_metadata` for
a registration body that is not JSON, which the SDK's handler would otherwise
raise on (f4). In local mode the same paths are registered and answer 404
themselves (`NotInThisMode`), so a mode is never a challenge (§5.5).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from binascii import Error as binascii_error
from collections import Counter
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit

import asyncpg
import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.auth import JWT_BEARER_ASSERTION_TYPE, TokenHandler
from fastmcp.server.auth.cimd import CIMDAssertionValidator
from fastmcp.server.auth.handlers.authorize import AuthorizationHandler
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.oauth_proxy.models import (
    ProxyDCRClient,
    UpstreamTokenSet,
    _hash_token,
    _matches_registered_redirect_uri,
)
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_http_request
from fastmcp.utilities.auth import decode_jwt_header
from fastmcp.utilities.ui import create_secure_html_response
from joserfc import jwk as jose_jwk
from joserfc.errors import JoseError
from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.errors import stringify_pydantic_error
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.json_response import PydanticJSONResponse
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import (
    AUTHORIZATION_PATH,
    REVOCATION_PATH,
    TOKEN_PATH,
    build_metadata,
    cors_middleware,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
)
from pydantic import AnyUrl, BaseModel, ConfigDict, ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from app import error_codes
from app.auth import tokens as token_format
from app.auth.mcp_auth import PersonalAccessTokenVerifier
from app.auth.mode import OIDC_PROVIDER_ATTR
from app.auth.principal import mcp as mcp_principal
from app.auth.registry import DISCOVERY_ROUTES, MCP_MOUNT, MCP_OAUTH_ROUTES
from app.config import Settings
from app.db import get_sessionmaker, session_scope
from app.exceptions import UnavailableError
from app.models import MCP_OAUTH_STATE_TABLE
from app.services import audit
from app.services import auth as auth_service
from app.services.oidc import OidcLoginRefused, OidcProvider

log = logging.getLogger("plamotrack.auth")

#: The `app.state` attribute holding the built `McpOAuth` in OIDC mode; absent
#: in local mode. The test suite reaches the proxy through it.
MCP_OAUTH_ATTR = "mcp_oauth"

#: The one scope advertised to and requested by MCP clients — the provider's
#: identity scope. Google returns URI-form scopes for `email`/`profile` and
#: FastMCP would then refuse a fresh token as `insufficient_scope`, so it is
#: `openid` alone (the spike's finding 7d); the collection scopes are the fixed
#: mapping in `mcp_auth`, not OAuth scopes.
ADVERTISED_SCOPES: tuple[str, ...] = ("openid",)
#: Forwarded to the provider's authorization endpoint. Google issues no refresh
#: token without both, so a link would die with the hour-long access token
#: (7d); every other provider ignores `access_type` (an unknown parameter,
#: RFC 6749 §3.1) and reads `prompt=consent` as "ask again", which a rare
#: MCP-link is the right moment for.
UPSTREAM_AUTHORIZE_PARAMS: dict[str, str] = {"access_type": "offline", "prompt": "consent"}
#: Lifetime of the access token the proxy issues to a client — pinned rather
#: than inherited from the provider's (Keycloak's default is 300 s, which some
#: clients cannot refresh gracefully). The upstream token is re-read on every
#: request and refreshed transparently, so this extends nothing upstream.
ACCESS_TOKEN_LIFETIME = 3600
#: Refresh the upstream token this many seconds before it expires, so a request
#: that passes the expiry check does not meet an expired token a moment later.
REFRESH_THRESHOLD = 30
#: Connections the state store may hold: the proxy touches it a handful of
#: times per request, on one owner's traffic.
STATE_STORE_POOL_SIZE = 2
#: HKDF salt for the storage key — distinct from anything FastMCP derives from
#: the same material, so the signing key and the encryption key differ.
STORAGE_KEY_SALT = b"plamotrack-mcp-oauth-state"
#: What an upstream-endpoint property reads as until the provider's document
#: has been fetched: a name that resolves nowhere (`.invalid`, RFC 2606). Never
#: reached — every entry point resolves first — but a bug that did reach it
#: would fail loudly rather than reach a wrong server.
UNRESOLVED_ENDPOINT = "https://oidc-provider-unresolved.invalid/"
#: The client-authentication methods this authorization server accepts, at the
#: token endpoint and at the revocation endpoint alike — the downstream client
#: contract (§5.9 item 7 (k)), published by discovery (RFC 8414 §2) as
#: `token_endpoint_auth_methods_supported` and
#: `revocation_endpoint_auth_methods_supported`: every dynamically registered
#: client is `none`; a CIMD client may bring `private_key_jwt`.
CLIENT_AUTH_METHODS: tuple[str, ...] = ("none", "private_key_jwt")
#: The assertion algorithms the pinned verifier accepts for `private_key_jwt`
#: (FastMCP's CIMD validator builds its `JWTVerifier` with the default, RS256,
#: for an inline JWKS and a `jwks_uri` alike) — published as both
#: `*_endpoint_auth_signing_alg_values_supported`, which RFC 8414 requires once
#: a JWT method is advertised. Measured by the contract suite: an ES256
#: assertion under the document's own EC key is refused.
CLIENT_ASSERTION_ALGORITHMS: tuple[str, ...] = ("RS256",)
#: The grant types this authorization server offers (RFC 6749 §4.1, §6) — what
#: `grant_types_supported` says, what a registration is substituted to, and what
#: any other `grant_type` at the token endpoint is `unsupported_grant_type`
#: against (RFC 6749 §5.2; the SDK's parser said `invalid_request`).
SUPPORTED_GRANT_TYPES: tuple[str, ...] = ("authorization_code", "refresh_token")
#: Clock tolerance for a client assertion's `nbf` — the SDK's own for `exp` and
#: `iat` (RFC 7523 §3 asks for "a small allowance").
CLIENT_ASSERTION_SKEW = 30
#: The one body representation the three client-driven endpoints admit (RFC
#: 6749 §4.1.3); the guard reads the media type case-insensitively, its
#: parameters aside (RFC 9110 §8.3.1).
FORM_MEDIA_TYPE = "application/x-www-form-urlencoded"
#: The one parameter RFC 8707 §2 lets a client repeat.
RESOURCE_PARAMETER = "resource"
#: The parameters each client-driven endpoint recognises — RFC 6749 §4.1.1, §4.1.3
#: and §6, RFC 7636 §4.3 and §4.5, RFC 8707 §2, RFC 7523 §2.2, RFC 7009 §2.1 — the
#: fields whose cardinality the request-decoding guard judges. Anything else is an
#: extension parameter the protocol says to ignore, however often it appears
#: (RFC 6749 §3.1 as corrected by erratum 5708; Codex #212 round 8, f28), so the
#: guard discards it before counting.
RECOGNISED_PARAMETERS: dict[str, frozenset[str]] = {
    AUTHORIZATION_PATH: frozenset(
        {
            "response_type",
            "client_id",
            "redirect_uri",
            "scope",
            "state",
            "code_challenge",
            "code_challenge_method",
            RESOURCE_PARAMETER,
        }
    ),
    TOKEN_PATH: frozenset(
        {
            "grant_type",
            "code",
            "redirect_uri",
            "client_id",
            "client_secret",
            "code_verifier",
            "refresh_token",
            "scope",
            RESOURCE_PARAMETER,
            "client_assertion_type",
            "client_assertion",
        }
    ),
    REVOCATION_PATH: frozenset(
        {
            "token",
            "token_type_hint",
            "client_id",
            "client_secret",
            "client_assertion_type",
            "client_assertion",
        }
    ),
}
#: The key under `upstream_claims` in every token the proxy issues that holds
#: the owner binding the grant was issued to.
BINDING_CLAIM = "plamotrack_owner"
#: The collection FastMCP keeps the grant records in — the SDK's own name for
#: it; the record gate's adapter reads and writes that same collection.
GRANT_COLLECTION = "mcp-upstream-tokens"
#: What an `auth.mcp_grant_revoked` row's `ended_by` says when the provider's
#: refresh response, not a client at `/revoke`, ended the grant.
ENDED_BY_UPSTREAM = "upstream_refresh"
#: Postgres advisory-lock namespace for the grant lock — the two-int4 form,
#: which cannot collide with the write gate's single int8 key; spells "moa",
#: so it is recognisable in `pg_locks`.
GRANT_LOCK_NAMESPACE = 0x6D6F61

_NOT_IN_THIS_MODE = "This instance does not sign in that way; see AUTH_MODE."
_NOT_OWNER = "The signed-in identity is not this instance's owner."
_GRANT_ENDED = "The grant has ended; link the client again."
_PROVIDER_UNAVAILABLE = "The identity provider could not be reached; try again shortly."
_PROVIDER_UNAVAILABLE_HTML = (
    "<h1>Identity provider unavailable</h1>"
    "<p>The identity provider could not be reached. Try again shortly.</p>"
)
_NOT_JSON = "The registration request body is not a JSON document."


def _reference(token: str) -> str:
    """A non-secret stand-in for a token in an `AccessToken.token` field: the SDK
    keeps the object on the request scope for the connection's life, and an
    accidental repr should leak nothing (the `PersonalAccessTokenVerifier`
    precedent)."""
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()[:16]


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _lock_key(handle: str) -> int:
    """A grant handle as the int4 half of an advisory-lock key."""
    return int.from_bytes(hashlib.sha256(handle.encode()).digest()[:4], "big", signed=True)


def _current_request() -> Request | None:
    try:
        return get_http_request()
    except RuntimeError:
        return None


# --- the owner binding ------------------------------------------------------------


@dataclass(frozen=True)
class OwnerBinding:
    """The identity a grant was issued to: the provider's `(iss, sub)` as the
    verified id_token asserted it, and a digest of that id_token so a refresh
    can tell the token it already verified from a new one. Carried under
    `BINDING_CLAIM` in the `upstream_claims` of every token the proxy issues —
    the proxy's own signature covers it — and compared with the owner row on
    every request."""

    issuer: str
    subject: str
    id_token_digest: str

    @classmethod
    def from_claims(cls, upstream_claims: object) -> OwnerBinding | None:
        if not isinstance(upstream_claims, dict):
            return None
        binding = upstream_claims.get(BINDING_CLAIM)
        if not isinstance(binding, dict):
            return None
        values = (binding.get("iss"), binding.get("sub"), binding.get("id_token_sha256"))
        if not all(isinstance(value, str) and value for value in values):
            return None
        return cls(*values)  # type: ignore[arg-type]

    def as_claims(self) -> dict[str, Any]:
        return {
            BINDING_CLAIM: {
                "iss": self.issuer,
                "sub": self.subject,
                "id_token_sha256": self.id_token_digest,
            }
        }


@dataclass(frozen=True)
class OwnerVerdict:
    """What the id_token check decided about one token: the binding it
    establishes for the owner, or why not — `invalid` (signature, shape,
    expiry: the browser login's contract), `unavailable` (the provider's keys
    could not be fetched), `identity` (verified, but not the bound owner —
    `subject` names who)."""

    binding: OwnerBinding | None
    reason: str
    subject: str | None = None


class IdTokenOwnerCheck:
    """The provider's id_token, verified through `OidcProvider` and bound to
    the owner row: run at issuance, and again whenever a refresh brings a new
    id_token. `still_bound` is the per-request half — a binding a grant
    carries, against the owner row as it is now."""

    def __init__(self, provider: Callable[[], OidcProvider]) -> None:
        self._provider = provider

    async def check(self, id_token: object) -> OwnerVerdict:
        provider = self._provider()
        try:
            claims = await provider.verify_id_token(id_token, nonce=None)
        except OidcLoginRefused:
            return OwnerVerdict(None, "invalid")
        except UnavailableError:
            return OwnerVerdict(None, "unavailable")
        subject: str = claims["sub"]
        async with session_scope() as session:
            owner = await auth_service.owner_row(session)
            bound = (owner.oidc_issuer, owner.oidc_subject)
        if bound != (provider.issuer, subject):
            return OwnerVerdict(None, "identity", subject)
        assert isinstance(id_token, str)
        return OwnerVerdict(OwnerBinding(claims["iss"], subject, _digest(id_token)), "ok", subject)

    async def still_bound(self, binding: OwnerBinding) -> bool:
        async with session_scope() as session:
            owner = await auth_service.owner_row(session)
        return (owner.oidc_issuer, owner.oidc_subject) == (binding.issuer, binding.subject)


class GrantVerifier(TokenVerifier):
    """FastMCP's verifier hook on this proxy. FastMCP calls it, per request,
    with the upstream access token of a grant record it has already loaded
    and, when the provider's token was near expiry, refreshed; it answers with
    the grant's `AccessToken` shell, into which FastMCP patches the upstream
    token's expiry (`_uses_alternate_verification`) — which is what bounds the
    grant by the provider. Whose grant it is — the proxy's signature on its own
    token, the carried binding against the owner row — is decided around it,
    in `load_access_token`. Declares no required scope: the mount then
    requires none, which is what keeps personal access tokens valid on `/mcp/`
    in OIDC mode; the advertised scopes are the proxy's `valid_scopes`."""

    def __init__(self) -> None:
        super().__init__(required_scopes=[])

    async def verify_token(self, token: str) -> AccessToken | None:
        return AccessToken(token=token, client_id="", scopes=[], claims={"kind": "mcp"})


class _GrantEnded(Exception):
    """Raised by the record gate when a transition finds its grant gone —
    revoked, or ended by another transition — since it read the record it
    set out to update. Nothing of the transition's is stored."""


class _GrantRefused(Exception):
    """Raised by the record gate when the identity a refresh response carries
    is not the grant's owner. The transition that meets it ends the grant."""

    def __init__(self, verdict: OwnerVerdict) -> None:
        super().__init__(verdict.reason)
        self.verdict = verdict


ISSUANCE, REFRESH, TRANSPARENT = "issuance", "refresh", "transparent"


@dataclass
class _Transition:
    """One transition of a grant, declared on the task that runs it and read by
    the record gate inside the SDK's code: which kind, for which client and
    route, the binding it holds — the one established a moment ago at
    issuance, or the one the presented token carries, replaced by the record's
    own once the gate has read it — the handles it knows (the record's id, the
    presented token's JTI, the refresh token's hash), and what it learned on
    the way (`outcome`: `ended`, or `refused`)."""

    kind: str
    client_id: str
    target: str
    binding: OwnerBinding | None = None
    grant_id: str | None = None
    jti: str | None = None
    refresh_hash: str | None = None
    outcome: str | None = None


_transition_in_flight: ContextVar[_Transition | None] = ContextVar(
    "mcp_oauth_transition", default=None
)


class _GrantLock:
    """`_one_redemption`'s lock: one transaction holding the advisory lock for
    the handle, committed or rolled back — either releases it — when the
    exchange leaves. A class, not `@asynccontextmanager` over `session_scope`:
    the SDK's `TokenError` is a frozen dataclass, and a generator-based
    context manager re-raising it assigns `__traceback__` and dies with
    `FrozenInstanceError` — a 500 where `invalid_grant` was meant."""

    def __init__(self, handle: str) -> None:
        self._handle = handle
        self._session = None

    async def __aenter__(self) -> None:
        self._session = get_sessionmaker()()
        # The key is derived here, not by `hashtext` in SQL: the handle is a
        # secret (an authorization code), and the engine's DEBUG log would
        # otherwise print it as a bound parameter (T10).
        await self._session.execute(
            text(
                "SELECT pg_advisory_xact_lock(CAST(:namespace AS integer), CAST(:key AS integer))"
            ),
            {"namespace": GRANT_LOCK_NAMESPACE, "key": _lock_key(self._handle)},
        )

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        assert self._session is not None
        try:
            if exc_type is None:
                await self._session.commit()
            else:
                await self._session.rollback()
        finally:
            await self._session.close()
        return False


class _GrantTransition:
    """`_one_transition`'s context: the advisory lock on the handle — the grant
    record's id, or the authorization code before a record exists — held for
    the whole transition, the declaration the record gate reads, and the
    ending. A transition the gate refused ends its grant here, under the lock,
    before the SDK's `invalid_grant` goes out; one that found the grant gone
    reports the same error and touches nothing."""

    def __init__(self, proxy: PlamotrackOAuthProxy, transition: _Transition, handle: str) -> None:
        self._proxy = proxy
        self._transition = transition
        self._lock = _GrantLock(handle)
        self._declared = None

    async def __aenter__(self) -> _Transition:
        await self._lock.__aenter__()
        self._declared = _transition_in_flight.set(self._transition)
        return self._transition

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        try:
            if isinstance(exc, _GrantRefused):
                raise await self._proxy._refuse_transition(self._transition, exc.verdict) from None
            if isinstance(exc, _GrantEnded):
                self._transition.outcome = "ended"
                raise TokenError("invalid_grant", _GRANT_ENDED) from None
            return False
        finally:
            assert self._declared is not None
            _transition_in_flight.reset(self._declared)
            await self._lock.__aexit__(exc_type, exc, tb)


class GrantRecord(UpstreamTokenSet):
    """The grant record: FastMCP's upstream token set — the provider's access
    and refresh tokens, their expiry, the raw response — plus the identity the
    set was verified for. `owner` is the durable binding: the `(iss, sub)` and
    the digest of the id_token that established or last renewed it. A record
    without one predates the gate and ends at its next refresh."""

    owner: OwnerBinding | None = None


class GrantRecords:
    """The one gate every write to a grant record passes. FastMCP writes the
    record at issuance, on the client's refresh exchange and on the transparent
    refresh behind a request, through the adapter it built in `__init__`; this
    stands in its place, so a writer this module has not enumerated — a future
    SDK path included — meets the same rule. A write is admitted only from a
    declared transition on this task (anything else is a programming error and
    raises); after issuance the record is read back here, under the
    transition's lock, because the record's own binding is the authority —
    the digest it holds is the id_token last verified, whichever transition
    verified it, not the one the client's tokens were minted with — and a
    record that is gone or unbound ends the transition (`_GrantEnded`); and
    the set is written only with an identity that binding names: its id_token
    is the one already verified, or it is new and passes the owner check in
    full, else `_GrantRefused` and the transition ends the grant. What keeps a
    revocation and a refresh from interleaving is the lock every transition
    holds (`_one_transition`), revocation included. The SDK's own order —
    persist, then extract claims — let a refused set become the active one,
    its transparent refresh never asked (Codex #212 round 2, f7), and its
    revocation and refresh writers shared nothing, so a stale refresh
    recreated a revoked grant through the store's upsert (f6). A new id_token
    that verifies and names the owner *now* is still not enough: it must name
    the `(iss, sub)` the record holds — the owner check answers who the owner
    is, the record answers who authorized this grant, and between a
    transition's owner check and its write the two can differ (a rebind and
    the next owner's login in that window: round 3, f10, the reviewed head's
    gate adopting the new owner's identity onto the old owner's grant)."""

    def __init__(self, proxy: PlamotrackOAuthProxy, inner: PydanticAdapter[GrantRecord]) -> None:
        self._proxy = proxy
        self._inner = inner

    async def get(
        self, key: str, *, collection: str | None = None, default: GrantRecord | None = None
    ) -> GrantRecord | None:
        return await self._inner.get(key=key, collection=collection, default=default)

    async def delete(self, key: str, *, collection: str | None = None) -> bool:
        return await self._inner.delete(key=key, collection=collection)

    async def put(
        self,
        key: str,
        value: UpstreamTokenSet,
        *,
        collection: str | None = None,
        ttl: float | None = None,
    ) -> None:
        transition = _transition_in_flight.get()
        if transition is None or transition.binding is None:
            raise RuntimeError("MCP OAuth: a grant record written outside a declared transition")
        if transition.grant_id is None:
            if transition.kind != ISSUANCE:
                raise RuntimeError("MCP OAuth: a refresh wrote a record it had not read")
            transition.grant_id = key
            established = transition.binding
        else:
            if key != transition.grant_id:
                raise RuntimeError("MCP OAuth: a transition wrote another grant's record")
            current = await self._inner.get(key=key)
            if current is None or current.owner is None:
                raise _GrantEnded()
            established = current.owner
            if (established.issuer, established.subject) != (
                transition.binding.issuer,
                transition.binding.subject,
            ):
                raise _GrantEnded()
        id_token = value.raw_token_data.get("id_token")
        if isinstance(id_token, str) and _digest(id_token) == established.id_token_digest:
            binding = established
        else:
            verdict = await self._proxy._owner_check.check(id_token)
            if verdict.binding is None:
                raise _GrantRefused(verdict)
            if (verdict.binding.issuer, verdict.binding.subject) != (
                established.issuer,
                established.subject,
            ):
                # Verified, and the owner now — but not the identity that
                # authorized this grant (OpenID Connect Core §12.2): the
                # grant is the previous owner's and ends here.
                raise _GrantRefused(OwnerVerdict(None, "identity", verdict.subject))
            binding = verdict.binding
        transition.binding = binding
        record = value if isinstance(value, GrantRecord) else GrantRecord(**value.model_dump())
        record.owner = binding
        await self._inner.put(key=key, value=record, collection=collection, ttl=ttl)


class RevocationLookup:
    """The provider as the SDK's revocation handler sees it (RFC 7009 §2.1).
    The handler locates the presented token through `load_access_token` and
    `load_refresh_token`, then checks it is the authenticated client's and
    calls `revoke_token`; on this proxy `load_access_token` is the **bearer
    path** — the grant's upstream set read and refreshed, a new id_token
    verified against the provider's keys, the owner row consulted — and a
    lookup that answers `None` there is, to the handler, a token it does not
    hold: RFC 7009's silent 200 with nothing revoked. A provider whose keys
    could not be fetched left a live grant behind a 200 that way (Codex #212
    round 3, f9). Here the access token is **located, not authorized**
    (`locate_access_token`); the refresh-token lookup was always local and
    stays the proxy's; revocation itself is the proxy's."""

    def __init__(self, proxy: PlamotrackOAuthProxy) -> None:
        self._proxy = proxy

    async def load_access_token(self, token: str) -> AccessToken | None:
        return await self._proxy.locate_access_token(token)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return await self._proxy.load_refresh_token(client, refresh_token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await self._proxy.revoke_token(token)


class RevocationForm(BaseModel):
    """RFC 7009 §2.1's form: the token and an optional hint. The client's
    credentials — `client_id`, an assertion — are the authenticator's to read,
    per the client's method, and are not fields of this model; the SDK's own
    model declared `client_secret` without a default, so Pydantic required a
    field no public client has and the contract's form was `400
    invalid_request` (Codex #212 round 4, f12). The hint is **any string**:
    a recognised value chooses the lookup order and "if the server is unable
    to locate the token using the given hint, it MUST extend its search"; an
    unrecognised one "MUST be ignored" (RFC 7009 §2.2) — a two-value enum
    here had made an empty or unknown hint a `400` (round 5, f15)."""

    model_config = ConfigDict(extra="ignore")

    token: str
    token_type_hint: str | None = None


class RevocationRefused(BaseModel):
    """RFC 7009 §2.2.1's error response, with RFC 6749 §5.2's codes: a failed
    client authentication is `invalid_client`, as the token endpoint says it
    (the SDK's revocation handler said `unauthorized_client`; the contract
    answers one code on both endpoints)."""

    error: Literal["invalid_request", "invalid_client"]
    error_description: str | None = None


class GrantRevocation(RevocationHandler):
    """The SDK's revocation handler, its steps in the SDK's order — authenticate
    the client, read the form, locate the token (the hint first, the other
    lookup second), check it is this client's, revoke, 200 — over the wire
    form the contract accepts (`RevocationForm`) and the SDK's `no-store` on
    every answer (the `RouteBinding` stamps it too). The provider is
    `RevocationLookup`; the authenticator is the proxy's
    `_revocation_authenticator`."""

    async def handle(self, request: Request) -> Response:
        try:
            client = await self.client_authenticator.authenticate_request(request)
        except AuthenticationError as exc:
            return PydanticJSONResponse(
                status_code=401,
                content=RevocationRefused(error="invalid_client", error_description=exc.message),
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        try:
            form = RevocationForm.model_validate(dict(await request.form()))
        except ValidationError as exc:
            return PydanticJSONResponse(
                status_code=400,
                content=RevocationRefused(
                    error="invalid_request", error_description=stringify_pydantic_error(exc)
                ),
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        loaders = [
            self.provider.load_access_token,
            partial(self.provider.load_refresh_token, client),
        ]
        if form.token_type_hint == "refresh_token":
            loaders.reverse()
        token: AccessToken | RefreshToken | None = None
        for loader in loaders:
            token = await loader(form.token)
            if token is not None:
                break
        # An unknown token is the RFC's 200; another client's token is too
        # (RFC 7009 §2.1: a client may revoke only its own), and nothing moves.
        if token is not None and token.client_id == client.client_id:
            await self.provider.revoke_token(token)
        return Response(
            status_code=200, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
        )


# --- the client assertion's claims --------------------------------------------------


def _b64url_json(segment: str) -> Any:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))


#: The supported range of a NumericDate — this server's policy, an inclusive
#: ±2^53: RFC 7493 §2.2 discusses the integer precision a JSON number carries
#: interoperably, through ±(2^53−1), and does not itself impose a NumericDate
#: contract (round 8's correction). Judged on the parsed value before any float
#: conversion — `math.isfinite` on a 401-digit integer raised `OverflowError`,
#: which the authenticator did not catch, and a correctly signed assertion was
#: a 500 on both endpoints (Codex #212 round 7, f21). Fractional dates inside
#: the range stay legal.
NUMERIC_DATE_BOUND = 2**53


def _numeric_date(claims: dict[str, Any], name: str) -> float | None:
    value = claims.get(name)
    if value is None:
        if name in claims:
            raise ValueError(f"{name} must be a NumericDate, not null")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite NumericDate")
    # int and float compare exactly in Python, so an integer beyond the bound is
    # refused without being converted; NaN fails both comparisons, ±inf one.
    if not (-NUMERIC_DATE_BOUND <= value <= NUMERIC_DATE_BOUND):
        raise ValueError(f"{name} must be a NumericDate within ±2^53 (this server's range)")
    return float(value)


def validate_client_assertion_claims(assertion: str, *, now: float) -> None:
    """RFC 7523 §3 and RFC 7519 §4.1 on the *unverified* assertion, refuse-only:
    it grants nothing — the SDK's validator then verifies the signature, the
    issuer, the audience, the lifetime and the replay — but it runs first, so
    a claim outside the contract is refused before the `jti` is spent, and
    the same assertion can be presented once it is valid (an `nbf` that has
    arrived). Raises `ValueError` naming the claim."""
    try:
        header_segment, payload_segment, _signature = assertion.split(".")
        header, claims = _b64url_json(header_segment), _b64url_json(payload_segment)
    except (ValueError, UnicodeDecodeError, binascii_error):
        raise ValueError("the assertion is not a compact JWS") from None
    if not isinstance(header, dict) or header.get("alg") not in CLIENT_ASSERTION_ALGORITHMS:
        raise ValueError(f"alg must be one of {', '.join(CLIENT_ASSERTION_ALGORITHMS)}")
    if not isinstance(claims, dict):
        raise ValueError("the claims must be a JSON object")
    for name in ("iss", "sub", "jti"):
        if not isinstance(claims.get(name), str) or not claims[name]:
            raise ValueError(f"{name} must be a non-empty string")
    audience = claims.get("aud")
    if isinstance(audience, list):
        if not audience or not all(isinstance(item, str) and item for item in audience):
            raise ValueError("aud must be a non-empty string or a list of them")
    elif not isinstance(audience, str) or not audience:
        raise ValueError("aud must be a non-empty string or a list of them")
    if _numeric_date(claims, "exp") is None:
        raise ValueError("exp is required")
    _numeric_date(claims, "iat")
    not_before = _numeric_date(claims, "nbf")
    if not_before is not None and not_before > now + CLIENT_ASSERTION_SKEW:
        raise ValueError("the assertion is not yet valid (nbf)")


class ClientAssertionAuthenticator(ClientAuthenticator):
    """Client authentication at `/token` and `/revoke` — `none`, and
    `private_key_jwt` verified by FastMCP's CIMD validator against the
    client's document and bound to one endpoint's URL as the assertion's
    audience — **admitted once, as one decision** (Codex #212 rounds 6–8:
    f16, f24, f29, f30). A refuse-only precheck in front of the SDK's
    authenticator could disagree with what the SDK then executed: the SDK
    read only the first `Authorization` occurrence and ignored the header
    entirely on a public client, and it looked the client up a second time,
    so a document served with `no-store` could say `private_key_jwt` to the
    precheck and `none` to the SDK, which then accepted an assertion under
    a key the document never published. So the request is judged here, in
    order, and nothing behind it decides again:

    1. **The credential inventory.** Every raw `Authorization` occurrence
       counts (RFC 7235 permits the field more than once): no HTTP scheme is
       admitted by this contract, so any occurrence is a failed HTTP
       authentication attempt — `invalid_client`, with the challenge in the
       scheme the client used (`_challenge_on_refusal`) — whether or not an
       assertion is beside it. A request carrying either assertion field is
       a request to be authenticated by the assertion: a `client_secret`
       beside it is a second mechanism (RFC 6749 §2.3, RFC 7521 §4.2.1 —
       `invalid_client`), and the assertion's claims are judged by
       `validate_client_assertion_claims` before its `jti` could be spent.
    2. **One client snapshot.** The client record is resolved once, and the
       method it names, the document whose keys verify the assertion, and
       the authenticated client the handler receives are all that record.
    3. **Dispatch by the snapshot's method.** `private_key_jwt`: the
       assertion type, the assertion, then FastMCP's own validator with the
       inline set's usability and selection owned and the selected key's
       authorization kept (`RestrictedKeyAssertionValidator` — signature,
       issuer, audience, lifetime, replay, and the key's `alg`/`use`/`key_ops`;
       rounds 9–11). `none`: the client id alone; an assertion presented to it is
       refused, since there is no key it could be verified against; a stray
       `client_secret` with no assertion is ignored, as the SDK ignores it
       (no mechanism is in use). Any other method is refused.

    A refusal is the endpoint's `401 invalid_client`, spending nothing: the
    same assertion is usable on a corrected request. One class for both
    endpoints; `PlamotrackOAuthProxy._client_authenticator` builds one per
    endpoint."""

    def __init__(
        self, *, provider, validator: RestrictedKeyAssertionValidator, token_endpoint_url: str
    ) -> None:
        super().__init__(provider)
        self.validator = validator
        self.endpoint_url = token_endpoint_url

    async def authenticate_request(self, request: Request) -> OAuthClientInformationFull:
        form = await request.form()
        assertion = form.get("client_assertion")
        presented = assertion is not None or form.get("client_assertion_type") is not None
        header_attempts = request.headers.getlist("authorization")
        if header_attempts:
            raise AuthenticationError(
                "HTTP client authentication is not admitted at this endpoint "
                "(the methods are none and private_key_jwt; RFC 6749 §2.3)"
            )
        if presented and form.get("client_secret"):
            raise AuthenticationError(
                "more than one client authentication mechanism in the request (RFC 7521 §4.2.1)"
            )
        if isinstance(assertion, str) and assertion:
            try:
                validate_client_assertion_claims(assertion, now=time.time())
            except ValueError as exc:
                raise AuthenticationError(f"Invalid client assertion: {exc}") from None
        client_id = form.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise AuthenticationError("Missing client_id")
        client = await self.provider.get_client(client_id)
        if client is None:
            raise AuthenticationError("Invalid client_id")
        method = client.token_endpoint_auth_method
        if method == "private_key_jwt":
            if form.get("client_assertion_type") != JWT_BEARER_ASSERTION_TYPE:
                raise AuthenticationError(
                    f"Invalid client_assertion_type: expected {JWT_BEARER_ASSERTION_TYPE}"
                )
            if not isinstance(assertion, str) or not assertion:
                raise AuthenticationError("Missing client_assertion")
            document = getattr(client, "cimd_document", None)
            if document is None or document.token_endpoint_auth_method != "private_key_jwt":
                raise AuthenticationError("Client must have a CIMD document for private_key_jwt")
            try:
                await self.validator.validate_assertion(
                    assertion, client.client_id, self.endpoint_url, document
                )
            except ValueError as exc:
                raise AuthenticationError(f"Invalid client assertion: {exc}") from exc
            return client
        if method == "none":
            if presented:
                raise AuthenticationError(
                    "the client is not registered for private_key_jwt; "
                    "an assertion cannot authenticate it"
                )
            return client
        raise AuthenticationError(f"Unsupported auth method: {method}")


# --- the selected key keeps its authorization --------------------------------------------


def _pem_of(key: dict[str, Any]) -> str | None:
    """The PEM FastMCP converts a JWK to, or `None` for a key it would skip as
    unusable — an unsupported `kty`, a missing member, material joserfc
    refuses — the same joserfc import and the same skip set as the SDK's
    remote path (RFC 7517 §5: ignore what cannot be processed), so this is
    also the usability predicate the inline set is filtered by (round 11,
    f35). Byte-identical to the SDK's conversion whatever metadata the JWK
    carries: the metadata is exactly what a PEM cannot represent, which is
    why identity is never re-derived from it (round 11, f34)."""
    kind = key.get("kty")
    if kind not in ("RSA", "EC"):
        return None
    try:
        return jose_jwk.import_key(key, kind).as_pem().decode("utf-8")
    except (JoseError, TypeError, ValueError, KeyError):
        return None


def _header_kid(token: str) -> str | None:
    """The assertion's `kid`, read once for both key paths: a non-empty
    string names a record; absent or empty names none, the reading the SDK's
    remote selection gives both (round 12, f36). A value that is not a string
    reads as naming none here and is refused by the JOSE decode downstream —
    joserfc refuses the header (`'kid' in header must be a str`, RFC 7515
    §4.1.4) in the very call that verifies the signature, whichever record
    the selection handed it — so no type guard stands in front of that
    decision as a second owner; a header that cannot be decoded likewise."""
    try:
        kid = decode_jwt_header(token).get("kid")
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return kid if isinstance(kid, str) and kid else None


class RestrictedKeyVerifier(JWTVerifier):
    """FastMCP's JWKS verifier with the selected key's authorization kept
    (Codex #212 round 10, f33): the SDK caches the PEM of every fetched key
    by `kid` and verifies with the PEM, so the JWK's `alg`, `use` and
    `key_ops` (RFC 7517 §4.2–§4.4; RFC 8725 §3.1) never reached joserfc and a
    valid signature authenticated under a key that excluded it. This keeps
    the JWKs of the last fetch beside the SDK's own cache — rebuilt only when
    the SDK refetches, so within its cache lifetime like the material — and
    hands `load_access_token` the JWK the SDK's selection named — by the
    assertion's `kid`, or the only key when it names none (its cache, its
    fallback, its selection all untouched) — in place of the PEM;
    the SDK's `_import_key_for_algorithm` imports a JWK as readily as a PEM,
    and the same `jwt.decode` that verifies the signature then enforces the
    restrictions. One cryptographic validator, no refetch."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._jwks_by_kid: dict[str, dict[str, Any]] = {}

    async def _fetch_jwks(self) -> dict[str, Any]:
        """The SDK's fetch, with the JWKs kept **by `kid`** exactly as the SDK
        caches their PEMs — a key without one under its `_default` slot, an
        unusable key skipped — so the record the selection names is the
        record kept (round 11, f34: found by material, two `kid`s publishing
        one material collapsed onto the first)."""
        data = await super()._fetch_jwks()
        keys = data.get("keys", []) if isinstance(data, dict) else []
        self._jwks_by_kid = {}
        for key in keys:
            if not isinstance(key, dict) or _pem_of(key) is None:
                continue
            self._jwks_by_kid[key.get("kid") or "_default"] = key
        return data

    async def _get_verification_key(self, token: str) -> Any:
        """The SDK's selection — its cache, lifetime, fetch and fallback —
        answered with the record it named: the JWK under the assertion's
        `kid`, or the only cached key when the assertion names none, as the
        SDK's rule reads. A record whose material is not the PEM the SDK
        selected is a disagreement between the two and is refused, never
        degraded to the PEM (the metadata would be lost again)."""
        pem = await super()._get_verification_key(token)
        kid = _header_kid(token)
        if kid is not None:
            chosen = self._jwks_by_kid.get(kid)
        elif len(self._jwks_by_kid) == 1:
            chosen = next(iter(self._jwks_by_kid.values()))
        else:
            chosen = None
        if chosen is None or _pem_of(chosen) != pem:
            raise ValueError("the selected key and its published record disagree")
        return chosen


class RestrictedKeyAssertionValidator(CIMDAssertionValidator):
    """FastMCP's client-assertion validator — issuer, audience, lifetime, the
    `jti` replay cache, and the key selected by `kid` or the single-key
    fallback — with the selected key's authorization kept on both key paths
    (round 10, f33; round 11, f34): the inline extraction returns the
    record the SDK's rule selects, itself, in place of the PEM the SDK
    converted it to, and a fetched set is
    verified through `RestrictedKeyVerifier`, installed in the SDK's own
    per-client verifier cache under the SDK's own key so its `validate_assertion`
    picks it up unchanged. One instance serves both endpoints
    (`PlamotrackOAuthProxy.assertion_validator`), so the replay cache is one."""

    def _extract_public_key_from_jwks(self, token: str, jwks: dict) -> Any:
        """The inline set's usability and selection in one place, as the SDK's
        remote path has them (RFC 7517 §5 and §5.1; round 9, f32; round 11,
        f34–f35): `keys` must be an array; an entry that is not an object, or
        whose material FastMCP cannot import — the remote path's own skip set
        (`_pem_of`) — is ignored; none usable is a refusal; then the SDK's
        **remote** rule (round 12, f36) — the record whose `kid` the
        assertion names, a named `kid` that matches nothing a refusal, or the
        only usable key when it names none — returning the **record
        selected**, not a PEM and not the first record with its material. The
        SDK has two rules: its inline extraction fell back to the only key
        whenever no record matched, named or not, where its remote selection
        falls back only when no `kid` is named (RFC 7517 §4.5: `kid` is how a
        key is selected), and round 11 wrote out the inline one — so an
        assertion naming an unpublished `kid` authenticated inline and was
        refused fetched. The SDK's extraction also called `.get` on whatever
        each entry was (a 500), counted an unusable object against the
        single-key fallback, and converted the selection to a PEM (its `alg`,
        `use` and `key_ops` lost). Round 9 filtered a copy of the record in
        front of the SDK's extraction instead; once the selection was written
        out here (round 11) that copy was a second owner of the same decision,
        and its mutants went equivalent, so it retired into this."""
        keys = jwks.get("keys") if isinstance(jwks, dict) else None
        if not isinstance(keys, list):
            raise ValueError(
                "the client's key set is malformed: keys is not an array (RFC 7517 §5)"
            )
        usable = [key for key in keys if isinstance(key, dict) and _pem_of(key) is not None]
        if not usable:
            raise ValueError("the client's key set holds no usable key (RFC 7517 §5.1)")
        kid = _header_kid(token)
        if kid is not None:
            selected = next((key for key in usable if key.get("kid") == kid), None)
            if selected is None:
                raise ValueError(f"Key ID '{kid}' not found in JWKS")
        elif len(usable) == 1:
            selected = usable[0]
        else:
            raise ValueError("Multiple keys in JWKS but no key ID (kid) in token")
        return selected

    async def validate_assertion(
        self, assertion: str, client_id: str, token_endpoint: str, cimd_doc: Any
    ) -> bool:
        if cimd_doc.jwks_uri:
            cache_key = f"{cimd_doc.jwks_uri}|{client_id}|{token_endpoint}"
            if not isinstance(self._verifier_cache.get(cache_key), RestrictedKeyVerifier):
                if len(self._verifier_cache) >= self._verifier_cache_max_size:
                    del self._verifier_cache[next(iter(self._verifier_cache))]
                self._verifier_cache[cache_key] = RestrictedKeyVerifier(
                    jwks_uri=str(cimd_doc.jwks_uri),
                    issuer=client_id,
                    audience=token_endpoint,
                    ssrf_safe=True,
                )
        return await super().validate_assertion(assertion, client_id, token_endpoint, cimd_doc)


#: RFC 9110 §11.1: an authentication scheme is a token. Echoed into the
#: challenge only when it is one.
_SCHEME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")


def presented_scheme(request: Request) -> str | None:
    """The HTTP authentication scheme a request used — the first occurrence
    of `Authorization` that names one (round 8, f29: the field may repeat,
    and an empty first occurrence hid the second) — or `None`."""
    for header in request.headers.getlist("authorization"):
        scheme = header.split(None, 1)[0] if header.split() else ""
        if _SCHEME.fullmatch(scheme):
            return scheme
    return None


# --- the resource indicator ----------------------------------------------------------

_UNRESERVED = r"A-Za-z0-9\-._~"
_SUB_DELIMS = r"!$&'()*+,;="
_PCT = r"%[0-9A-Fa-f]{2}"
_PCHAR = rf"(?:[{_UNRESERVED}{_SUB_DELIMS}:@]|{_PCT})"
_SEGMENT = rf"{_PCHAR}*"
_AUTHORITY = (
    rf"(?:(?:[{_UNRESERVED}{_SUB_DELIMS}:]|{_PCT})*@)?"
    rf"(?:\[(?:[0-9A-Fa-f:.]+|v[0-9A-Fa-f]+\.[{_UNRESERVED}{_SUB_DELIMS}:]+)\]"
    rf"|(?:[{_UNRESERVED}{_SUB_DELIMS}]|{_PCT})*)"
    r"(?::[0-9]*)?"
)
_HIER_PART = (
    rf"(?://{_AUTHORITY}(?:/{_SEGMENT})*"  # "//" authority path-abempty
    rf"|/(?:{_PCHAR}+(?:/{_SEGMENT})*)?"  # path-absolute
    rf"|{_PCHAR}+(?:/{_SEGMENT})*"  # path-rootless
    r"|)"  # path-empty
)
#: RFC 3986 §4.3 `absolute-URI` — scheme ":" hier-part [ "?" query ], no
#: fragment — as Appendix A's grammar, applied to the decoded value **before**
#: a parser sees it: `urlsplit` accepts what the grammar does not (a tab in
#: the authority, a carriage return in the path, a leading NUL — some of which
#: it silently strips), and a query this comparison ignores was never checked
#: at all (an invalid percent-escape, an unescaped space). RFC 8707 §2 requires
#: the value to be such a URI (Codex #212 round 9, f31: parsing is not
#: validation). A valid percent-escape in the query is admitted.
ABSOLUTE_URI = re.compile(rf"[A-Za-z][A-Za-z0-9+\-.]*:{_HIER_PART}(?:\?(?:{_PCHAR}|[/?])*)?")


def resource_identity(value: str) -> tuple[str, str, str]:
    """RFC 8707 §2's value reduced to what this server compares — the owned
    decision (Codex #212 round 8, f27: FastMCP's normaliser, shared in round
    7, dropped the fragment and the path's `;parameters` before comparing,
    so `…/mcp/#other` and `…/mcp/;different-resource` were this server).
    Malformed, raising `ValueError`: a fragment — any `#`, the empty fragment
    included — which the RFC forbids; anything outside RFC 3986's
    `absolute-URI` grammar (`ABSOLUTE_URI`, judged on the string before
    `urlsplit`, which is a parser and not a validator — round 9, f31).
    Otherwise the scheme, the authority and the **whole** path, `;parameters`
    kept (`urlsplit`, which does not separate them, where `urlparse` did),
    with these equivalences and no other: a trailing slash on the path is
    ignored; the query is not compared (RFC 8707 says a client SHOULD NOT
    send one; FastMCP allows the clients that append one); the **scheme** is
    case-folded (RFC 3986 §6.2.2.1; `urlsplit` folds it, and so does the
    `urlparse` in FastMCP's normaliser — round 9's correction of the "as
    written" wording); the **authority** is compared as written — the
    spelling the protected-resource document gave the client — so the
    normaliser behind this decision, which compares it as written too, never
    refuses what this accepted."""
    if "#" in value:
        raise ValueError("a resource indicator must not include a fragment (RFC 8707 §2)")
    if not ABSOLUTE_URI.fullmatch(value):
        raise ValueError(
            "a resource indicator must be an absolute URI (RFC 8707 §2, RFC 3986 §4.3)"
        )
    parsed = urlsplit(value)
    return parsed.scheme, parsed.netloc, parsed.path.rstrip("/")


# --- request decoding ------------------------------------------------------------------


class ProtocolRequest:
    """RFC 6749 §3.1–§3.2 in front of the SDK's handlers on the three endpoints
    a client drives — `/authorize`, `/token`, `/revoke` — applied to the raw
    query or form before the SDK's `dict(form)` loses it (Codex #212 round 6,
    f18): a parameter "MUST NOT be included more than once", so a repetition
    is `400 invalid_request` before anything is redeemed, redirected or spent
    (the SDK kept the last value and minted, revoked, or opened a consent
    transaction); a parameter "sent without a value MUST be treated as if it
    were omitted", so empties are dropped before the handler reads the form
    (an empty `token` is a missing one; an empty `scope` is no scope); a
    `grant_type` the server does not offer is `unsupported_grant_type` (RFC
    6749 §5.2), where the SDK's discriminated parser said `invalid_request`;
    and an omitted `code_challenge_method` is `plain` (RFC 7636 §4.3), which
    the SDK's S256-only model then refuses exactly as it refuses `plain` — an
    error redirect for a registered client with a valid redirect URI (RFC
    7636 §4.4.1), a direct 400 otherwise — where its default had read the
    omission as `S256`. **Every body representation** (round 7, f20): the
    media type is read as HTTP defines it — case-insensitively, its
    parameters aside (RFC 9110 §8.3.1) — and a POST whose body is anything
    but `application/x-www-form-urlencoded` is `400 invalid_request` before
    the SDK parses it (RFC 6749 §4.1.3): a case-sensitive `startswith` had
    let `Application/X-Www-Form-Urlencoded` and `multipart/form-data`
    bodies, which the SDK parses, reach the handlers unguarded. **`resource`
    is a set** (round 7, f22): RFC 8707 §2 lets it appear more than once, so
    it is exempt from the repetition rule; identical values collapse to one;
    the whole set is judged by the proxy's own acceptability predicate
    (`accepts_resource`, FastMCP's comparison at `/authorize`) — a set that
    names only this server is one effective target, handed to the SDK as
    such; a set naming any other target is `invalid_target`, at
    `/authorize` by handing the handler the first such value alone so the
    proxy's `authorize` refuses it in the endpoint's form (an error redirect
    for a registered client — the decision is the proxy's own, `accepts_resource`
    over `resource_identity`, applied again there because FastMCP's normaliser
    behind the hand-off is looser; round 8, f27), at `/token` directly, where
    the SDK reads the field and judges nothing (RFC 8707 §2.2's "MUST
    reject"); a malformed value — a fragment, no scheme, unparseable — is
    refused directly on both. **Only recognised fields are judged** (round 8,
    f28): each endpoint declares the parameters it understands
    (`RECOGNISED_PARAMETERS`) and anything else is an extension parameter the
    protocol says to ignore, however often it appears (RFC 6749 §3.1, erratum
    5708), so it is discarded before its multiplicity could refuse a request —
    a recognised credential repeated is still refused. Verbs the endpoint
    does not take pass through to the SDK (and the binding)."""

    def __init__(
        self, app: ASGIApp, *, endpoint: str, accepts_resource: Callable[[str], bool]
    ) -> None:
        self.app = app
        self.endpoint = endpoint
        self.accepts_resource = accepts_resource
        self.recognised = RECOGNISED_PARAMETERS[endpoint]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("GET", "POST"):
            await self.app(scope, receive, send)
            return
        if scope["method"] == "GET":
            if self.endpoint != AUTHORIZATION_PATH:
                await self.app(scope, receive, send)
                return
            raw = scope["query_string"].decode("utf-8", "replace")
            pairs = parse_qsl(raw, keep_blank_values=True)
            body: bytes | None = None
        else:
            request = Request(scope, receive)
            body = await request.body()
            media_type = request.headers.get("content-type", "").split(";", 1)[0]
            if media_type.strip().lower() != FORM_MEDIA_TYPE:
                await self._refuse(
                    scope,
                    receive,
                    send,
                    "invalid_request",
                    f"the request body must be {FORM_MEDIA_TYPE} (RFC 6749 §4.1.3)",
                )
                return
            pairs = parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True)
        pairs = [(name, value) for name, value in pairs if name in self.recognised]
        refusal = self._refusal(pairs)
        if refusal is not None:
            await self._refuse(scope, receive, send, *refusal)
            return
        pairs = [(name, value) for name, value in pairs if value != ""]
        pairs, refusal = self._one_resource(pairs)
        if refusal is not None:
            await self._refuse(scope, receive, send, *refusal)
            return
        if self.endpoint == AUTHORIZATION_PATH and all(
            name != "code_challenge_method" for name, _ in pairs
        ):
            pairs.append(("code_challenge_method", "plain"))
        encoded = urlencode(pairs).encode()
        if body is None:
            await self.app({**scope, "query_string": encoded}, receive, send)
            return
        headers = [(k, v) for k, v in scope["headers"] if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(encoded)).encode()))
        await self.app({**scope, "headers": headers}, self._replay(encoded), send)

    @staticmethod
    async def _refuse(
        scope: Scope, receive: Receive, send: Send, error: str, description: str
    ) -> None:
        response = JSONResponse(
            {"error": error, "error_description": description},
            status_code=400,
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
        await response(scope, receive, send)

    def _refusal(self, pairs: list[tuple[str, str]]) -> tuple[str, str] | None:
        counts = Counter(name for name, _ in pairs)
        repeated = sorted(
            name for name, count in counts.items() if count > 1 and name != RESOURCE_PARAMETER
        )
        if repeated:
            return (
                "invalid_request",
                f"parameter repeated: {', '.join(repeated)} (RFC 6749 §3.1)",
            )
        if self.endpoint == TOKEN_PATH:
            grant_types = [value for name, value in pairs if name == "grant_type" and value]
            if grant_types and grant_types[0] not in SUPPORTED_GRANT_TYPES:
                return (
                    "unsupported_grant_type",
                    f"grant_type must be one of: {', '.join(SUPPORTED_GRANT_TYPES)}",
                )
        return None

    def _one_resource(
        self, pairs: list[tuple[str, str]]
    ) -> tuple[list[tuple[str, str]], tuple[str, str] | None]:
        """The `resource` set reduced to the one target this server issues
        tokens for, or the refusal (RFC 8707 §2): identical values collapse;
        every distinct value is judged; the pairs come back with one
        `resource` at most — the first this server accepts when all are
        acceptable, the first it does not when any is not (for the proxy's
        `authorize` to refuse in the endpoint's form); a malformed value, or
        a foreign one at `/token`, is refused here. `/revoke` has no such
        field (RFC 7009): it is not recognised there and never reaches this."""
        resources = list(
            dict.fromkeys(value for name, value in pairs if name == RESOURCE_PARAMETER)
        )
        if not resources:
            return pairs, None
        others = [(name, value) for name, value in pairs if name != RESOURCE_PARAMETER]
        verdicts: dict[str, bool | None] = {}
        for value in resources:
            try:
                verdicts[value] = self.accepts_resource(value)
            except ValueError:
                verdicts[value] = None
        if any(verdict is None for verdict in verdicts.values()):
            return pairs, ("invalid_target", "a resource indicator is malformed (RFC 8707 §2)")
        foreign = [value for value, accepted in verdicts.items() if not accepted]
        if foreign and self.endpoint == TOKEN_PATH:
            return pairs, (
                "invalid_target",
                "this server issues tokens for its own resource only (RFC 8707 §2.2)",
            )
        chosen = foreign[0] if foreign else resources[0]
        return others + [(RESOURCE_PARAMETER, chosen)], None

    @staticmethod
    def _replay(body: bytes):
        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        return receive


class UnregisteredClientGuidance(AuthorizationHandler):
    """FastMCP's authorize handler — its enhanced answer to an unregistered
    client names the registration endpoint and the authorization-server
    document — with the document's URL the **root** one this instance serves:
    the handler built it under the issuer path, the child alias that is
    pruned here, so the recovery instruction was a 404 exactly when a client
    had lost its registration (Codex #212 round 6, f19). The HTML page and
    the `Link` header are the handler's own."""

    def __init__(self, provider: PlamotrackOAuthProxy, *, discovery_url: str) -> None:
        super().__init__(provider=provider, base_url=provider.base_url)  # type: ignore[arg-type]
        self._discovery_url = discovery_url

    async def _create_enhanced_error_response(
        self, request: Request, client_id: str, state: str | None
    ) -> Response:
        response = await super()._create_enhanced_error_response(request, client_id, state)
        if not response.headers.get("content-type", "").startswith("application/json"):
            return response
        body = json.loads(bytes(response.body))  # type: ignore[attr-defined]
        if "authorization_server_metadata" in body:
            body["authorization_server_metadata"] = self._discovery_url
        return JSONResponse(
            body,
            status_code=response.status_code,
            headers={
                name: value
                for name, value in response.headers.items()
                if name.lower() in ("link", "cache-control")
            },
        )


# --- the redirect binding -----------------------------------------------------------


class BoundDCRClient(ProxyDCRClient):
    """A dynamically registered client whose redirect URI must match its
    **registration** — exact, with RFC 8252 §7.3's loopback-port exception —
    and *then* the operator allowlist when one is set. FastMCP's own client
    validates the allowlist instead of the registration once patterns exist,
    so `http://localhost:*` would let a registered `localhost:3000/cb` client
    be sent to `localhost:5000/anything` (§5.6 proxy trust; the spike's
    matrix)."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None and self.cimd_document is None:
            if not _matches_registered_redirect_uri(redirect_uri, self.redirect_uris):
                raise InvalidRedirectUriError(
                    f"Redirect URI '{redirect_uri}' not registered for client"
                )
        return super().validate_redirect_uri(redirect_uri)


# --- the proxy ----------------------------------------------------------------------


class PlamotrackOAuthProxy(OAuthProxy):
    """FastMCP's `OAuthProxy` with the plamotrack policy — see the module
    docstring for each piece. Built by `build_mcp_oauth`; one per app."""

    def __init__(
        self,
        *,
        settings: Settings,
        provider: Callable[[], OidcProvider],
        pat_verifier: PersonalAccessTokenVerifier,
        storage: FernetEncryptionWrapper,
    ) -> None:
        self._provider = provider
        self._owner_check = IdTokenOwnerCheck(provider)
        self._pat_verifier = pat_verifier
        self.assertion_validator = RestrictedKeyAssertionValidator()
        #: Test seam: an httpx transport the upstream code exchange, refresh
        #: and revocation go through instead of the network, so the suite can
        #: play the provider. None on the shipped app — nothing sets it.
        self.upstream_transport: httpx.AsyncBaseTransport | None = None
        super().__init__(
            # The SDK keeps these as attributes; on this class they are the
            # properties below, and the constructor's values are not kept.
            upstream_authorization_endpoint=UNRESOLVED_ENDPOINT,
            upstream_token_endpoint=UNRESOLVED_ENDPOINT,
            # Registers `/revoke` unconditionally; the provider's endpoint, or
            # none, is what the property reads once the document is cached.
            upstream_revocation_endpoint=UNRESOLVED_ENDPOINT,
            upstream_client_id=settings.oidc_client_id,
            upstream_client_secret=settings.oidc_client_secret,
            token_verifier=GrantVerifier(),
            base_url=f"{settings.public_base_url}{MCP_MOUNT}",
            valid_scopes=list(ADVERTISED_SCOPES),
            allowed_client_redirect_uris=settings.mcp_oauth_allowed_redirect_uri_patterns,
            client_storage=storage,
            jwt_signing_key=settings.mcp_oauth_signing_key_bytes,
            require_authorization_consent=True,
            extra_authorize_params=dict(UPSTREAM_AUTHORIZE_PARAMS),
            fastmcp_access_token_expiry_seconds=ACCESS_TOKEN_LIFETIME,
            token_expiry_threshold_seconds=REFRESH_THRESHOLD,
            enable_cimd=True,
        )
        # The grant records behind the gate: the same storage and collection
        # as the adapter the SDK just built, read back as `GrantRecord`.
        sdk_records = self._upstream_token_store
        if getattr(sdk_records, "_default_collection", GRANT_COLLECTION) != GRANT_COLLECTION:
            raise RuntimeError("MCP OAuth: FastMCP moved its grant records; the gate must follow")
        self._upstream_token_store = GrantRecords(  # type: ignore[assignment]
            self,
            PydanticAdapter[GrantRecord](
                key_value=self._client_storage,
                pydantic_model=GrantRecord,
                default_collection=GRANT_COLLECTION,
                raise_on_validation_error=True,
            ),
        )

    # -- the upstream: a view of the provider's document ---------------------------

    @property
    def _upstream_authorization_endpoint(self) -> str:
        metadata = self._provider().cached_metadata
        return metadata.authorization_endpoint if metadata is not None else UNRESOLVED_ENDPOINT

    @_upstream_authorization_endpoint.setter
    def _upstream_authorization_endpoint(self, value: str) -> None:
        pass  # the SDK's constructor assigns its argument; the document decides

    @property
    def _upstream_token_endpoint(self) -> str:
        metadata = self._provider().cached_metadata
        return metadata.token_endpoint if metadata is not None else UNRESOLVED_ENDPOINT

    @_upstream_token_endpoint.setter
    def _upstream_token_endpoint(self, value: str) -> None:
        pass

    @property
    def _upstream_revocation_endpoint(self) -> str | None:
        metadata = self._provider().cached_metadata
        return metadata.revocation_endpoint if metadata is not None else UNRESOLVED_ENDPOINT

    @_upstream_revocation_endpoint.setter
    def _upstream_revocation_endpoint(self, value: str | None) -> None:
        pass

    async def _resolve_upstream(self) -> None:
        """Make sure this process holds the provider's discovery document (the
        cached, issuer-checked one the browser login reads) before an entry
        point that needs an upstream endpoint acts. Raises `UnavailableError`
        when the provider cannot be reached and nothing is cached yet."""
        await self._provider().metadata()

    async def _resolve_upstream_softly(self) -> None:
        """For paths that only *may* need the upstream (a refresh behind a
        request, a revocation): a down provider leaves the endpoints unresolved
        and the upstream half fails, or is skipped, on its own."""
        try:
            await self._resolve_upstream()
        except UnavailableError:
            pass

    def _create_upstream_oauth_client(self) -> AsyncOAuth2Client:
        if self.upstream_transport is None:
            return super()._create_upstream_oauth_client()
        return AsyncOAuth2Client(
            client_id=self._upstream_client_id,
            client_secret=(
                self._upstream_client_secret.get_secret_value()
                if self._upstream_client_secret is not None
                else None
            ),
            token_endpoint_auth_method=self._token_endpoint_auth_method,
            transport=self.upstream_transport,
        )

    # -- the client contract: registration -------------------------------------------

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Every dynamically registered client is a public client — `none`,
        PKCE — whatever method it asked for, and the registration response
        says so (RFC 7591 §3.2.1: the server may substitute requested
        metadata; the response describes what was registered). The SDK's
        handler mints a secret for any method but `none` (its default when
        the field is absent or null is `client_secret_post`), passes the
        object here and returns **that object**, while FastMCP stores a
        public `ProxyDCRClient` — so a client was told `client_secret_post`
        and handed a secret the server never read (Codex #212 round 4, f11).
        The object is made truthful before it is stored or returned: the
        same value on the wire and in the store, and nothing minted that
        nothing checks. Both MCP SDK clients adapt to it — they send a secret
        only when the response carries one, by its method. And the rest of
        the metadata describes the stored client too (round 6, f17): the
        admitted contract is canonicalised once here — a `null` redirect list
        refused (FastMCP invented `http://localhost/` for it; this server
        issues authorization codes only), `response_types` and `grant_types`
        what the server offers, a blank or padded `scope` the default — and
        the record stored is built from that same object, display and
        software fields included, where FastMCP's registration constructed a
        record of its own from a few of the fields. And the admitted metadata
        obeys the metadata's own cross-field rule (round 7, f26): `jwks` and
        `jwks_uri` "MUST NOT both be present in the same request or response"
        (RFC 7591 §2) — the combination is refused, where the SDK's model
        admitted it and the record echoed and stored both."""
        if not client_info.redirect_uris:
            raise RegistrationError(
                "invalid_client_metadata",
                "redirect_uris is required: this server issues authorization codes only",
            )
        if client_info.jwks is not None and client_info.jwks_uri is not None:
            raise RegistrationError(
                "invalid_client_metadata",
                "jwks and jwks_uri must not both be present (RFC 7591 §2)",
            )
        client_info.token_endpoint_auth_method = "none"
        client_info.client_secret = None
        client_info.client_secret_expires_at = None
        client_info.response_types = ["code"]
        client_info.grant_types = list(SUPPORTED_GRANT_TYPES)
        requested_scope = " ".join((client_info.scope or "").split())
        client_info.scope = requested_scope or " ".join(ADVERTISED_SCOPES)
        # FastMCP's registration: the allowlist check, and a record of its own.
        await super().register_client(client_info)
        # The record is the admitted contract, field for field.
        await self._client_store.put(
            key=client_info.client_id,
            value=ProxyDCRClient(
                **client_info.model_dump(),
                allowed_redirect_uri_patterns=self._allowed_client_redirect_uris,
            ),
        )

    # -- the routes ------------------------------------------------------------------

    def _client_authenticator(self, endpoint: str) -> ClientAuthenticator:
        """Client authentication at `/token` and at `/revoke`, one policy built
        per endpoint: FastMCP's CIMD-capable authenticator — `none` and
        `private_key_jwt`, the latter's assertion verified against the
        client's document and bound to **this** endpoint's URL as its
        audience (RFC 7523 §3), used once per process — under the claim
        contract (`ClientAssertionAuthenticator`, round 6). FastMCP installs
        its authenticator on `/token` alone and the plain SDK authenticator
        refused the method a CIMD client had linked with at `/revoke` (round
        4, f13). An assertion for the token endpoint is not one for
        revocation, and the reverse."""
        if self._cimd_manager is None:  # pragma: no cover — CIMD is always on here
            return ClientAuthenticator(self)
        return ClientAssertionAuthenticator(
            provider=self,
            validator=self.assertion_validator,
            token_endpoint_url=f"{self.base_url}{endpoint}",
        )

    def _challenge_on_refusal(self, handle: Callable[[Request], Any]) -> Callable[[Request], Any]:
        """RFC 6749 §5.2 (adopted by RFC 7009 §2.2.1): a 401 to a client that
        "attempted to authenticate via the Authorization request header field"
        carries `WWW-Authenticate` matching the scheme it used. No scheme is
        admitted here, so the attempt is always a failed one (round 7, f24);
        the handlers answered without the challenge."""

        async def handled(request: Request) -> Response:
            response = await handle(request)
            scheme = presented_scheme(request)
            if response.status_code == 401 and scheme is not None:
                response.headers["WWW-Authenticate"] = f'{scheme} realm="{self.base_url}"'
            return response

        return handled

    def accepts_resource(self, value: str) -> bool:
        """RFC 8707 §2: whether a resource indicator names the one target a
        token minted here is for — `resource_identity` of the value against
        that of this server's resource URL, the decision this proxy owns
        (round 7, f22; round 8, f27 — FastMCP's comparison, shared before,
        erased the fragment and the path's parameters first). The guard
        applies it to every value of a `resource` set on `/authorize` and
        `/token`, and `authorize` applies it again behind the hand-off; the
        installation URL cannot carry a query (`config.py` refuses one), so
        FastMCP's exact-match branch for such a server has no case here.
        Raises `ValueError` for a malformed value."""
        if self._resource_url is None:  # pragma: no cover — set before any route answers
            return True
        return resource_identity(value) == resource_identity(str(self._resource_url))

    def _root_discovery_url(self) -> str:
        """The RFC 8414 path-aware document at the root — the one this instance
        serves — for the unregistered-client guidance."""
        parsed = urlparse(str(self.base_url))
        path = parsed.path.rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{path}"

    def discovery_metadata(self) -> OAuthMetadata:
        """The authorization-server document (RFC 8414 §2), owned here rather
        than inherited: the SDK's `build_metadata` for the endpoints under the
        issuer, PKCE, the scopes and the grant types, FastMCP's CIMD flag, and
        then the client contract as this server actually enforces it — the
        two methods for the token endpoint and for the revocation endpoint,
        and the one assertion algorithm. The SDK's metadata advertised the
        shared-secret methods it supports in general and none of what this
        proxy admits at `/revoke` (Codex #212 round 5, f14). The contract
        suite pins the document to these literals and drives every advertised
        method end to end; `test_the_three_root_documents_…` pins the rest."""
        metadata = build_metadata(
            self.base_url,  # type: ignore[arg-type]
            self.service_documentation_url,
            self.client_registration_options or ClientRegistrationOptions(),
            self.revocation_options or RevocationOptions(),
        )
        metadata.client_id_metadata_document_supported = self._cimd_manager is not None
        metadata.token_endpoint_auth_methods_supported = list(CLIENT_AUTH_METHODS)
        metadata.token_endpoint_auth_signing_alg_values_supported = list(
            CLIENT_ASSERTION_ALGORITHMS
        )
        metadata.revocation_endpoint_auth_methods_supported = list(CLIENT_AUTH_METHODS)
        metadata.revocation_endpoint_auth_signing_alg_values_supported = list(
            CLIENT_ASSERTION_ALGORITHMS
        )
        return metadata

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """FastMCP's protocol routes, with the contract on four of them: `/revoke`
        handled by `GrantRevocation` over `RevocationLookup` — the SDK's own
        handler steps, given a provider whose token lookup locates rather than
        authorizes, the contract's wire form, and the client authenticator the
        contract needs; `/token` FastMCP's handler (its OAuth 2.1 error codes)
        over the same authenticator class bound to its own URL; `/authorize`
        FastMCP's handler with the unregistered-client guidance pointing at the
        root document; and the authorization-server document served from
        `discovery_metadata` (the root documents are this list filtered to
        `/.well-known/`, so they carry it too). The same seam FastMCP uses to
        replace `/authorize` and `/token`; the request-decoding guard goes in
        front of three of these when the mount is built (`guard_protocol_requests`)."""
        routes = super().get_routes(mcp_path)
        revocation = GrantRevocation(
            RevocationLookup(self),  # type: ignore[arg-type]
            self._client_authenticator(REVOCATION_PATH),
        )
        token = TokenHandler(
            provider=self, client_authenticator=self._client_authenticator(TOKEN_PATH)
        )
        authorize = UnregisteredClientGuidance(self, discovery_url=self._root_discovery_url())
        discovery = MetadataHandler(self.discovery_metadata())
        rebuilt: list[Route] = []
        for route in routes:
            if isinstance(route, Route) and route.path == REVOCATION_PATH:
                route = Route(
                    path=route.path,
                    endpoint=cors_middleware(
                        self._challenge_on_refusal(revocation.handle), ["POST", "OPTIONS"]
                    ),
                    methods=["POST", "OPTIONS"],
                )
            elif isinstance(route, Route) and route.path == TOKEN_PATH:
                route = Route(
                    path=route.path,
                    endpoint=cors_middleware(
                        self._challenge_on_refusal(token.handle), ["POST", "OPTIONS"]
                    ),
                    methods=["POST", "OPTIONS"],
                )
            elif isinstance(route, Route) and route.path == AUTHORIZATION_PATH:
                route = Route(path=route.path, endpoint=authorize.handle, methods=["GET", "POST"])
            elif isinstance(route, Route) and route.path.startswith(
                "/.well-known/oauth-authorization-server"
            ):
                route = Route(
                    path=route.path,
                    endpoint=cors_middleware(discovery.handle, ["GET", "OPTIONS"]),
                    methods=route.methods,
                    name=route.name,
                    include_in_schema=route.include_in_schema,
                )
            rebuilt.append(route)
        return rebuilt

    # -- the client kinds ------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if client_id == self._upstream_client_id:
            # The synthesised upstream-id client accepts any redirect URI;
            # nobody uses it (the spike named every client's kind), so it is
            # refused as an unknown client.
            return None
        client = await super().get_client(client_id)
        if client is None or client.cimd_document is not None:
            return client
        return BoundDCRClient(**client.model_dump(), allow_unregistered_redirect_uris=False)

    # -- the flow ----------------------------------------------------------------------

    async def authorize(self, client, params) -> str:
        """FastMCP's authorize — the transaction, the upstream URL — after the
        provider is resolved, and after **this server's** resource decision:
        a `resource` that `accepts_resource` refuses, malformed included, is
        RFC 8707 §2.1's `invalid_target`, rendered here as the error redirect
        the handler already validated (`params.redirect_uri`, `params.state`)
        because the SDK's response model lacks the code and its catch-all
        rendered FastMCP's refusal as `server_error` (Codex #212 round 7,
        f22), and applied here, behind the guard's hand-off, because FastMCP's
        own check is looser and accepted what the guard had judged foreign
        (round 8, f27). FastMCP's check still runs behind this one and can
        refuse nothing this accepted (`resource_identity`)."""
        try:
            await self._resolve_upstream()
        except UnavailableError as exc:
            raise AuthorizeError(
                error="temporarily_unavailable", error_description=_PROVIDER_UNAVAILABLE
            ) from exc
        resource = getattr(params, "resource", None)
        if resource is not None:
            try:
                accepted = self.accepts_resource(str(resource))
            except ValueError:
                accepted = False
            if not accepted:
                return construct_redirect_uri(
                    str(params.redirect_uri),
                    error="invalid_target",
                    error_description="this server issues tokens for its own resource only",
                    state=params.state,
                )
        return await super().authorize(client, params)

    async def _handle_consent(self, request: Request):
        """The consent page and its submission (FastMCP's `ConsentMixin`, the
        registered endpoint): an approval builds the provider's authorization
        URL, so on a fresh process — a restart between the page and the
        approval — this can be the first request that needs the endpoints
        (Codex #212 round 1, f5). A provider that cannot be reached is a 503,
        never a redirect to the placeholder."""
        try:
            await self._resolve_upstream()
        except UnavailableError:
            return create_secure_html_response(_PROVIDER_UNAVAILABLE_HTML, status_code=503)
        return await super()._handle_consent(request)

    async def _handle_idp_callback(self, request: Request):
        try:
            await self._resolve_upstream()
        except UnavailableError:
            return create_secure_html_response(_PROVIDER_UNAVAILABLE_HTML, status_code=503)
        return await super()._handle_idp_callback(request)

    def _one_transition(self, transition: _Transition, handle: str) -> _GrantTransition:
        """Run one transition of a grant under the advisory lock on `handle` —
        the grant record's id once a record exists, the authorization code
        before it — a transaction-scoped Postgres advisory lock
        (`pg_advisory_xact_lock`, the write gate's shape: rule 7.1, taken
        *before* the read the decision is made from) held through the SDK's
        get→mint→delete or get→refresh→rotate, with the declaration the record
        gate reads. Every transition of one grant across requests and
        processes serializes on it: a second redemption of a code or a refresh
        token reads the first's deletion and gets `invalid_grant`; a
        revocation and a refresh never interleave, so whichever lands first the
        record is gone afterwards. Released at commit or rollback, so nothing
        survives the transition; a refresh holds it across one upstream call,
        bounded by the SDK's HTTP timeout."""
        return _GrantTransition(self, transition, handle)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        transition = _Transition(ISSUANCE, client.client_id or "", f"{MCP_MOUNT}/token")
        async with self._one_transition(transition, authorization_code.code):
            code_model = await self._code_store.get(key=authorization_code.code)
            if code_model is None:
                # The SDK's own `invalid_grant` for a code it does not hold —
                # including the second redemption of a code the first consumed.
                return await super().exchange_authorization_code(client, authorization_code)
            verdict = await self._owner_check.check(code_model.idp_tokens.get("id_token"))
            if verdict.binding is None:
                # Consume the code first: a retry must not find it.
                await self._code_store.delete(key=authorization_code.code)
                await self._record_refusal(verdict, transition)
                raise self._refusal_error(verdict)
            transition.binding = verdict.binding
            tokens = await super().exchange_authorization_code(client, authorization_code)
            await self._record(
                audit.MCP_GRANT_ISSUED,
                principal=mcp_principal(write=True, subject=verdict.subject),
                detail=f"client={client.client_id}",
            )
            return tokens

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        try:
            payload = self.jwt_issuer.verify_token(
                refresh_token.token, expected_token_use="refresh"
            )
        except Exception as exc:
            raise TokenError("invalid_grant", "Invalid refresh token") from exc
        carried = OwnerBinding.from_claims(payload.get("upstream_claims"))
        if carried is None:
            raise TokenError("invalid_grant", "The refresh token carries no owner binding.")
        if not await self._owner_check.still_bound(carried):
            # The owner was rebound since this grant was issued: the grant is
            # the previous owner's and ends here, as its access token does at
            # the next request.
            raise TokenError("invalid_grant", _NOT_OWNER)
        try:
            await self._resolve_upstream()
        except UnavailableError as exc:
            raise TokenError("invalid_request", _PROVIDER_UNAVAILABLE) from exc
        mapping = await self._jti_mapping_store.get(key=payload["jti"])
        if mapping is None:
            # The SDK's own `invalid_grant` for a refresh token it no longer
            # holds — rotated, revoked, or a second redemption's read of the
            # first's rotation.
            return await super().exchange_refresh_token(client, refresh_token, scopes)
        transition = _Transition(
            REFRESH,
            client.client_id or "",
            f"{MCP_MOUNT}/token",
            binding=carried,
            grant_id=mapping.upstream_token_id,
            jti=payload["jti"],
            refresh_hash=_hash_token(refresh_token.token),
        )
        async with self._one_transition(transition, mapping.upstream_token_id):
            return await super().exchange_refresh_token(client, refresh_token, scopes)

    async def _extract_upstream_claims(self, idp_tokens: dict[str, Any]) -> dict[str, Any] | None:
        """FastMCP's hook for what its issued tokens carry — here the owner
        binding. Called inside the SDK's minting code after the record was
        written, at issuance with the code's provider tokens and at a refresh
        with the stored set merged with the provider's response; by then the
        record gate has verified that set and left the record's binding on the
        transition, so the claims are that binding and nothing is verified
        here a second time. A set the gate did not verify cannot reach this
        point; one that did is a programming error and fails loudly rather
        than minting."""
        transition = _transition_in_flight.get()
        id_token = idp_tokens.get("id_token")
        if (
            transition is None
            or transition.binding is None
            or not isinstance(id_token, str)
            or _digest(id_token) != transition.binding.id_token_digest
        ):
            raise RuntimeError("MCP OAuth: a token minted for a set the record gate did not verify")
        return transition.binding.as_claims()

    async def _refuse_transition(
        self, transition: _Transition, verdict: OwnerVerdict
    ) -> TokenError:
        """The record gate refused what a refresh brought back from the
        provider — another subject, or an id_token that fails the contract:
        the refusal is audited as at issuance and, unless the provider's keys
        were merely unreachable, the grant **ends** under the lock the
        transition holds — the record, the presented token's mapping and the
        refresh token's hash entry go, and `auth.mcp_grant_revoked` names the
        upstream as what ended it. Nothing of the response was stored; a
        relink is the way back (a provider that answers a refresh with another
        identity is not one to retry against). Returns the error to raise."""
        await self._record_refusal(verdict, transition)
        if verdict.reason != "unavailable":
            assert transition.grant_id is not None and transition.binding is not None
            await self._upstream_token_store.delete(key=transition.grant_id)
            if transition.jti is not None:
                await self._jti_mapping_store.delete(key=transition.jti)
            if transition.refresh_hash is not None:
                await self._refresh_token_store.delete(key=transition.refresh_hash)
            await self._record(
                audit.MCP_GRANT_REVOKED,
                principal=mcp_principal(write=True, subject=transition.binding.subject),
                detail=f"client={transition.client_id} ended_by={ENDED_BY_UPSTREAM}",
                target=transition.target,
            )
        transition.outcome = "refused"
        return self._refusal_error(verdict)

    async def _record_refusal(self, verdict: OwnerVerdict, transition: _Transition) -> None:
        """A verdict other than the owner's, at issuance or on a refresh: the
        audit row — the identity refusal names the subject, a token that fails
        the contract is a failed round trip — on the route the transition
        answers."""
        if verdict.reason == "identity":
            await self._record(
                audit.MCP_IDENTITY_REFUSED,
                detail=f"subject={verdict.subject} client={transition.client_id}",
                target=transition.target,
            )
            return
        await self._record(
            audit.OIDC_LOGIN_FAILED,
            detail=f"id_token_{verdict.reason} client={transition.client_id}",
            target=transition.target,
        )

    @staticmethod
    def _refusal_error(verdict: OwnerVerdict) -> TokenError:
        return TokenError(
            "invalid_grant",
            _PROVIDER_UNAVAILABLE if verdict.reason == "unavailable" else _NOT_OWNER,
        )

    # -- the bearer, per request ---------------------------------------------------------

    def _uses_alternate_verification(self) -> bool:
        """Tells FastMCP the verifier's answer is a shell for the grant, so the
        returned `AccessToken` carries the upstream set's expiry — the
        provider's token, refreshed transparently while it can be, is what
        bounds a grant."""
        return True

    async def load_access_token(self, token: str) -> AccessToken | None:
        token = token.strip()
        if token.startswith(f"{token_format.TOKEN_KIND}_"):
            # The owner's own credential, valid in every mode (§5.5).
            return await self._pat_verifier.verify_token(token)
        try:
            payload = self.jwt_issuer.verify_token(token)
        except Exception:
            return None
        binding = OwnerBinding.from_claims(payload.get("upstream_claims"))
        if binding is None:
            log.warning("MCP OAuth: an issued token carries no owner binding; refused")
            return None
        if not await self._owner_check.still_bound(binding):
            log.warning("MCP OAuth: an issued token's owner binding no longer holds; refused")
            return None
        # The transparent refresh behind this may need the token endpoint.
        await self._resolve_upstream_softly()
        transition = _Transition(
            TRANSPARENT,
            str(payload.get("client_id") or ""),
            f"{MCP_MOUNT}/",
            binding=binding,
            jti=payload["jti"],
        )
        declared = _transition_in_flight.set(transition)
        try:
            validated = await super().load_access_token(token)
        finally:
            _transition_in_flight.reset(declared)
        if validated is None or transition.outcome is not None:
            # The refresh behind this request found the grant gone, or refused
            # what the provider sent: the SDK then falls back to the set it had
            # loaded, and that is not an answer.
            return None
        client_id = str(payload.get("client_id") or validated.client_id)
        # FastMCP hands back the *upstream* access token in `token`; a reference
        # stands in for it here. The MCP client's id and the grant's JTI ride
        # along — the audit row and a revocation read them.
        return validated.model_copy(
            update={
                "token": _reference(token),
                "client_id": client_id,
                "claims": {
                    "kind": "mcp",
                    "iss": binding.issuer,
                    "sub": binding.subject,
                    "client_id": client_id,
                    "jti": payload["jti"],
                },
            }
        )

    async def _try_transparent_refresh(
        self, upstream_token_set: UpstreamTokenSet
    ) -> UpstreamTokenSet:
        """The refresh behind a request, as one transition of the grant: under
        the grant's lock the record is read again — gone, and the request is
        refused without the provider being asked — and the SDK's refresh runs
        on that fresh read. Its write goes through the record gate like every
        other, so a refused identity ends the grant on this path too; what
        the transition learned is left on it for `load_access_token`, since
        the SDK answers a failed refresh with the set it had loaded."""
        transition = _transition_in_flight.get()
        if transition is None or transition.kind != TRANSPARENT:
            raise RuntimeError("MCP OAuth: a transparent refresh outside a request")
        transition.grant_id = upstream_token_set.upstream_token_id
        async with self._one_transition(transition, transition.grant_id):
            current = await self._upstream_token_store.get(key=transition.grant_id)
            if current is None:
                raise _GrantEnded()
            return await super()._try_transparent_refresh(current)

    # -- revocation ------------------------------------------------------------------------

    async def locate_access_token(self, token: str) -> AccessToken | None:
        """The revocation handler's lookup of a presented access token
        (`RevocationLookup`): the proxy's own signature proves the token is
        ours, its claims name the client and the grant's binding, and the JTI
        mapping says a grant is behind it — and that is all. The provider is
        not asked, the upstream set is neither read nor refreshed, and the
        owner row is not consulted: a revocation reduces authority and needs
        none of what a request needs, and it must reach the grant whatever
        the provider is doing (RFC 7009 §2.1) — a grant the owner row no
        longer names included, which its client may still end. The shell
        carries what `revoke_token` reads (`_grant_handle`) and the client id
        the handler compares; a token behind which nothing of ours remains
        is `None`, the RFC's silent 200."""
        try:
            payload = self.jwt_issuer.verify_token(token.strip())
        except Exception:
            return None
        binding = OwnerBinding.from_claims(payload.get("upstream_claims"))
        if binding is None:
            return None
        jti = payload["jti"]
        if await self._jti_mapping_store.get(key=jti) is None:
            return None
        client_id = str(payload.get("client_id") or "")
        return AccessToken(
            token=_reference(token),
            client_id=client_id,
            scopes=[],
            claims={
                "kind": "mcp",
                "iss": binding.issuer,
                "sub": binding.subject,
                "client_id": client_id,
                "jti": jti,
            },
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """RFC 7009 §2.1 for the grant: whichever half is presented — located
        by `RevocationLookup`, checked by the SDK's handler to be this
        client's — the grant record goes, locally and first, so the presented
        token, its sibling and every token minted on the same grant are
        refused from here on whatever the provider is doing; then the provider
        is asked, best effort, to revoke *its* refresh token. A token behind
        which nothing of ours remains is the RFC's silent 200 and no audit
        row."""
        presented = "refresh_token" if isinstance(token, RefreshToken) else "access_token"
        handle = self._grant_handle(token)
        grant: UpstreamTokenSet | None = None
        if handle is not None:
            jti, binding = handle
            mapping = await self._jti_mapping_store.get(key=jti)
            if mapping is not None:
                # Under the grant's lock, so a refresh at the provider with
                # this record in hand writes after this — into a record that
                # is gone, which the gate refuses — never over it.
                async with _GrantLock(mapping.upstream_token_id):
                    grant = await self._upstream_token_store.get(key=mapping.upstream_token_id)
                    await self._upstream_token_store.delete(key=mapping.upstream_token_id)
                    await self._jti_mapping_store.delete(key=jti)
            else:
                await self._jti_mapping_store.delete(key=jti)
        if isinstance(token, RefreshToken):
            # Its own hash entry; not what serializes a concurrent refresh — the
            # mapping and the record, under the lock, are — so outside it.
            await self._refresh_token_store.delete(key=_hash_token(token.token))
        if grant is None or handle is None:
            return
        await self._record(
            audit.MCP_GRANT_REVOKED,
            principal=mcp_principal(write=True, subject=handle[1].subject),
            detail=f"client={token.client_id} presented={presented}",
            target=f"{MCP_MOUNT}/revoke",
        )
        await self._revoke_upstream(grant)

    def _grant_handle(self, token: AccessToken | RefreshToken) -> tuple[str, OwnerBinding] | None:
        """The JTI and binding behind a presented token: an access token's are
        the claims `load_access_token` stamped; a refresh token's are read off
        the proxy's own signed JWT."""
        if isinstance(token, RefreshToken):
            try:
                payload = self.jwt_issuer.verify_token(token.token, expected_token_use="refresh")
            except Exception:
                return None
            binding = OwnerBinding.from_claims(payload.get("upstream_claims"))
            return (payload["jti"], binding) if binding is not None else None
        claims = token.claims or {}
        jti, issuer, subject = claims.get("jti"), claims.get("iss"), claims.get("sub")
        if not (isinstance(jti, str) and isinstance(issuer, str) and isinstance(subject, str)):
            return None
        return jti, OwnerBinding(issuer, subject, "")

    async def _revoke_upstream(self, grant: UpstreamTokenSet) -> None:
        """Best effort, after the local record is gone: the provider's own
        refresh token (RFC 7009 says a server revoking one should revoke the
        access tokens of the grant) — or its access token when there is none —
        through the injectable upstream client, at the endpoint the document
        names. No endpoint, or a provider that cannot be reached, leaves the
        local revocation standing."""
        await self._resolve_upstream_softly()
        endpoint = self._upstream_revocation_endpoint
        if endpoint is None or endpoint == UNRESOLVED_ENDPOINT:
            log.info("MCP OAuth: no revocation endpoint at the provider; local revocation stands")
            return
        credential, hint = (
            (grant.refresh_token, "refresh_token")
            if grant.refresh_token
            else (grant.access_token, "access_token")
        )
        try:
            async with self._upstream_oauth_client() as oauth_client:
                await oauth_client.revoke_token(endpoint, token=credential, token_type_hint=hint)
        except Exception as exc:  # the provider's problem, not the client's
            log.warning("MCP OAuth: upstream revocation failed: %s", type(exc).__name__)

    # -- audit ---------------------------------------------------------------------------

    async def _record(
        self, event: str, *, detail: str, principal=None, target: str = f"{MCP_MOUNT}/token"
    ) -> None:
        request = _current_request()
        async with session_scope() as session:
            await audit.record_event(
                session,
                event,
                principal=principal,
                request=request,
                target=target,
                detail=detail,
            )


# --- the state store ------------------------------------------------------------------


class OAuthStateStore(PostgreSQLStore):
    """The `py-key-value-aio` PostgreSQL adapter over the app's own database,
    with a pool sized for the proxy's traffic (the library's default opens
    ten connections). The table exists before first use — Alembic owns it — so
    the adapter's `CREATE TABLE IF NOT EXISTS` never runs."""

    async def _create_pool(self) -> asyncpg.Pool:
        assert self._url is not None
        return await asyncpg.create_pool(self._url, min_size=1, max_size=STATE_STORE_POOL_SIZE)


def storage_key(signing_key: bytes) -> bytes:
    """The Fernet key for the state store's values, HKDF-derived from the
    signing key under a storage-specific salt."""
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=STORAGE_KEY_SALT, info=b"Fernet"
    ).derive(signing_key)
    return base64.urlsafe_b64encode(derived)


def asyncpg_dsn(database_url: str) -> str:
    """The SQLAlchemy URL (`postgresql+asyncpg://…`) as the DSN asyncpg takes."""
    return make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)


def build_state_store(settings: Settings) -> tuple[OAuthStateStore, FernetEncryptionWrapper]:
    store = OAuthStateStore(
        url=asyncpg_dsn(settings.database_url), table_name=MCP_OAUTH_STATE_TABLE
    )
    wrapped = FernetEncryptionWrapper(
        key_value=store,
        fernet=Fernet(storage_key(settings.mcp_oauth_signing_key_bytes)),
        raise_on_decryption_error=False,
    )
    return store, wrapped


# --- building it ------------------------------------------------------------------------


@dataclass
class McpOAuth:
    """What `create_app` builds in OIDC mode and keeps on `app.state`: the
    proxy the mount is built with, and the store to close at shutdown."""

    proxy: PlamotrackOAuthProxy
    store: OAuthStateStore

    async def close(self) -> None:
        await self.store.close()


def build_mcp_oauth(
    app: Starlette, settings: Settings, *, pat_verifier: PersonalAccessTokenVerifier
) -> McpOAuth:
    """The proxy for an OIDC-mode app. The provider is read off `app.state` at
    each use, not captured — the lifespan and the suite replace it there
    (`app.auth.mode`), and the proxy must follow."""

    def provider() -> OidcProvider:
        found = getattr(app.state, OIDC_PROVIDER_ATTR, None)
        if found is None:
            raise RuntimeError("the MCP OAuth proxy needs an OIDC provider on app.state")
        return found

    store, storage = build_state_store(settings)
    proxy = PlamotrackOAuthProxy(
        settings=settings, provider=provider, pat_verifier=pat_verifier, storage=storage
    )
    return McpOAuth(proxy=proxy, store=store)


# --- the routes -------------------------------------------------------------------------


class NotInThisMode:
    """A family-8 route in local mode: registered, answering its own 404 with
    the envelope that names the setting (§5.5 — the anonymous fallback must not
    turn a mode into a challenge). One instance per path: the registry keys a
    policy by endpoint."""

    def __init__(self, path: str) -> None:
        self.path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": _NOT_IN_THIS_MODE, "code": error_codes.AUTH_NOT_IN_THIS_MODE, "params": {}},
            status_code=404,
        )
        await response(scope, receive, send)


class DiscoveryDocument:
    """One root discovery route's endpoint, distinct per path: the SDK serves
    the authorization-server and OpenID documents from one handler object, and
    the registry refuses one endpoint on two routes."""

    def __init__(self, inner) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.inner(scope, receive, send)


class ClientMetadataBody:
    """In front of the SDK's registration handler: a body that is not a JSON
    document is RFC 7591 §3.2.2's `invalid_client_metadata` (400), where the
    handler's unconditional `request.json()` would raise and the child app
    would answer 500 without the profile (Codex #212 round 1, f4). The body is
    read once here and replayed to the handler; a JSON document that is not
    client metadata is the handler's own 400."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        body = await Request(scope, receive).body()
        try:
            json.loads(body)
        except ValueError:
            response = JSONResponse(
                {"error": "invalid_client_metadata", "error_description": _NOT_JSON},
                status_code=400,
            )
            await response(scope, receive, send)
            return

        async def replay() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)


def root_discovery_routes(oauth: McpOAuth | None) -> list[Route]:
    """The three root documents for the parent app (§5.5 family 8): FastMCP's
    for `base_url=…/mcp` with the bare `/.well-known/openid-configuration`
    pruned — its document names `…/mcp` as the issuer, which a bare-root lookup
    cannot match, and no client asked for it (the spike) — or, in local mode,
    the same three paths answering 404."""
    if oauth is None:
        return [
            Route(path, endpoint=NotInThisMode(path), methods=["GET", "OPTIONS"])
            for path in DISCOVERY_ROUTES
        ]
    routes = []
    for route in oauth.proxy.get_well_known_routes("/"):
        if route.path not in DISCOVERY_ROUTES:
            continue
        routes.append(
            Route(route.path, endpoint=DiscoveryDocument(route.endpoint), methods=route.methods)
        )
    return routes


def _child_path(path: str) -> str:
    return path.removeprefix(MCP_MOUNT)


def local_mode_child_routes() -> list[Route]:
    """The six protocol routes under the mount, in local mode: 404 themselves."""
    return [Route(_child_path(path), endpoint=NotInThisMode(path)) for path in MCP_OAUTH_ROUTES]


def prune_child_well_known(mcp_app: Starlette) -> None:
    """Drop the child's `/mcp/.well-known/*` aliases before mounting: the root
    documents are the parent's, and fewer spellings means fewer aliases for the
    ingress to reject (§5.5)."""
    mcp_app.router.routes[:] = [
        route
        for route in mcp_app.router.routes
        if not (isinstance(route, Route) and route.path.startswith("/.well-known/"))
    ]


def guard_registration_body(mcp_app: Starlette) -> None:
    """Put `ClientMetadataBody` in front of the SDK's registration route, under
    the `RouteBinding` the registry adds later (the route's endpoint, which the
    registry keys on, is untouched)."""
    for route in mcp_app.router.routes:
        if isinstance(route, Route) and route.path == _child_path(f"{MCP_MOUNT}/register"):
            route.app = ClientMetadataBody(route.app)


def guard_protocol_requests(mcp_app: Starlette, proxy: PlamotrackOAuthProxy) -> None:
    """Put `ProtocolRequest` in front of the three routes a client drives,
    under the `RouteBinding` the registry adds later (the route's endpoint,
    which the registry keys on, is untouched — the same shape as
    `guard_registration_body`), judging `resource` sets by the proxy's own
    predicate."""
    for route in mcp_app.router.routes:
        if isinstance(route, Route) and route.path in (
            AUTHORIZATION_PATH,
            TOKEN_PATH,
            REVOCATION_PATH,
        ):
            route.app = ProtocolRequest(
                route.app, endpoint=route.path, accepts_resource=proxy.accepts_resource
            )


def declare_child_verbs(mcp_app: Starlette) -> None:
    """Clear the SDK's own method metadata on every protocol route, so the
    registry's `RouteBinding` is the one verb boundary for the mount — an
    undeclared verb is its 405 with `Allow` and the profile, not Starlette's
    without either (the transport's precedent, `build_mcp_app`)."""
    for route in mcp_app.router.routes:
        if isinstance(route, Route) and MCP_MOUNT + route.path in MCP_OAUTH_ROUTES:
            route.methods = None  # type: ignore[assignment]
