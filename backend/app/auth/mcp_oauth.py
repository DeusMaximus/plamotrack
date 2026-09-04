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
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import asyncpg
import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.oauth_proxy.models import (
    ProxyDCRClient,
    UpstreamTokenSet,
    _hash_token,
    _matches_registered_redirect_uri,
)
from fastmcp.server.dependencies import get_http_request
from fastmcp.utilities.ui import create_secure_html_response
from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizeError,
    RefreshToken,
    TokenError,
)
from mcp.server.auth.routes import REVOCATION_PATH, cors_middleware
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyUrl
from sqlalchemy import text
from sqlalchemy.engine import make_url
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
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

    # -- the routes ------------------------------------------------------------------

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """FastMCP's protocol routes, with `/revoke` handled over
        `RevocationLookup` — the SDK's own handler and client authenticator,
        given a provider whose token lookup locates rather than authorizes.
        The same seam FastMCP uses to replace `/authorize` and `/token`."""
        routes = super().get_routes(mcp_path)
        handler = RevocationHandler(RevocationLookup(self), ClientAuthenticator(self))  # type: ignore[arg-type]
        return [
            Route(
                path=route.path,
                endpoint=cors_middleware(handler.handle, ["POST", "OPTIONS"]),
                methods=["POST", "OPTIONS"],
            )
            if isinstance(route, Route) and route.path == REVOCATION_PATH
            else route
            for route in routes
        ]

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
        try:
            await self._resolve_upstream()
        except UnavailableError as exc:
            raise AuthorizeError(
                error="temporarily_unavailable", error_description=_PROVIDER_UNAVAILABLE
            ) from exc
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


def declare_child_verbs(mcp_app: Starlette) -> None:
    """Clear the SDK's own method metadata on every protocol route, so the
    registry's `RouteBinding` is the one verb boundary for the mount — an
    undeclared verb is its 405 with `Allow` and the profile, not Starlette's
    without either (the transport's precedent, `build_mcp_app`)."""
    for route in mcp_app.router.routes:
        if isinstance(route, Route) and MCP_MOUNT + route.path in MCP_OAUTH_ROUTES:
            route.methods = None  # type: ignore[assignment]
