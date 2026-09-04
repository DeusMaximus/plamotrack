"""MCP OAuth — FastMCP's OAuth proxy in front of the configured OpenID Connect
provider, on the `/mcp` mount (§5.5 family 8; §5.6 proxy trust, open redirect,
credential leakage, safe failure; §5.9 items 5 and 7; M6-7, #192).

An MCP client that speaks OAuth — Claude web, ChatGPT web, MCP Inspector, any
DCR-capable native client — discovers this instance as an authorization server
(the three root documents `main.py` installs), registers or presents its
metadata document, and is sent through a consent page to the **same provider
and client** the browser login uses (#191). The provider's tokens never leave
the process: FastMCP issues its own access/refresh pair to the client, keeps
the upstream set encrypted in the state table, and re-verifies the upstream
identity on every request. What this module adds to FastMCP's `OAuthProxy` is
the plamotrack policy, each piece on a documented extension point (#30's
failure rule — the #190 spike measured that nothing needs protocol code):

- **Owner binding, at issuance and per request** (§5.6 open redirect; T6).
  `OwnerBoundIdTokenVerifier` verifies the provider's **id_token** — signature
  against the provider's JWKS, claims through the one validator the browser
  login uses (`validate_id_token_claims`, with no nonce: the proxy sends none)
  — and then requires `(iss, sub)` to equal the bound owner. It is the proxy's
  token verifier, so every MCP request re-checks; and
  `exchange_authorization_code` runs it **before** any token is minted, so a
  stranger who signs in at the provider gets `invalid_grant` at `/token`, an
  audit row, and nothing stored — the verifier alone would have handed them a
  token pair and refused the first tool call (the spike's finding 7a). A
  token without `sub` is refused, never mapped by email (7b).
- **Fixed scope mapping** (7c). The scope vocabulary the proxy advertises and
  forwards is the provider's (`openid`); `collection:read`/`collection:write`
  cannot be per-grant OAuth scopes on FastMCP 3.4.5 without translating in both
  directions through a private method. So every proxy-issued token is the
  owner's delegated grant with **both** collection scopes and never
  `instance:admin` — `mcp_auth.principal_from_access_token` maps `kind=mcp`
  to that, whatever the token's `scope` claim says. The mount itself requires
  no scope (the verifier declares none), so a personal access token — whose
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
- **Lazy upstream endpoints** (§5.6 safe failure). `OIDCProxy` fetches the
  provider's discovery document synchronously at construction — a provider
  that is down at start would fail the start. This subclass is an
  `OAuthProxy` built with placeholder endpoints and resolves the real ones
  from `OidcProvider.metadata()` — the browser login's cached, issuer-checked
  document — at each entry point: `authorize` (a down provider is
  `temporarily_unavailable` to the client, per RFC 6749), the upstream
  callback, the refresh exchange and revocation. The lifespan's warm-up fills
  the cache; nothing here blocks the start.
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
`RouteBinding` on each mounted route (M6-2's design); `declare_child_verbs`
clears the SDK routes' own method metadata so that binding is the one boundary,
as `build_mcp_app` does for the transport. In local mode the same paths are
registered and answer 404 themselves (`NotInThisMode`), so a mode is never a
challenge (§5.5).
"""

from __future__ import annotations

import base64
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

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
    _matches_registered_redirect_uri,
)
from fastmcp.server.dependencies import get_http_request
from fastmcp.utilities.ui import create_secure_html_response
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizeError,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import (
    InvalidRedirectUriError,
    OAuthClientInformationFull,
    OAuthToken,
)
from pydantic import AnyUrl
from sqlalchemy.engine import make_url
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from app import error_codes
from app.auth import tokens as token_format
from app.auth.mcp_auth import PersonalAccessTokenVerifier
from app.auth.mode import OIDC_PROVIDER_ATTR
from app.auth.principal import mcp as mcp_principal
from app.auth.registry import DISCOVERY_ROUTES, MCP_MOUNT, MCP_OAUTH_ROUTES
from app.config import Settings
from app.db import session_scope
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
#: clients cannot refresh gracefully). The upstream token is re-validated on
#: every request and refreshed transparently, so this extends nothing upstream.
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
#: What the proxy holds for an upstream endpoint until `_resolve_upstream` has
#: read the provider's document: a name that resolves nowhere (`.invalid`, RFC
#: 2606). Never reached — every entry point resolves first — but a bug that
#: did reach it would fail loudly rather than reach a wrong server.
UNRESOLVED_ENDPOINT = "https://oidc-provider-unresolved.invalid/"

_NOT_IN_THIS_MODE = "This instance does not sign in that way; see AUTH_MODE."
_NOT_OWNER = "The signed-in identity is not this instance's owner."
_PROVIDER_UNAVAILABLE = "The identity provider could not be reached; try again shortly."
_PROVIDER_UNAVAILABLE_HTML = (
    "<h1>Identity provider unavailable</h1>"
    "<p>The identity provider could not be reached. Try again shortly.</p>"
)


def _reference(token: str) -> str:
    """A non-secret stand-in for a token in an `AccessToken.token` field: the SDK
    keeps the object on the request scope for the connection's life, and an
    accidental repr should leak nothing (the `PersonalAccessTokenVerifier`
    precedent)."""
    return "sha256:" + hashlib.sha256(token.encode()).hexdigest()[:16]


def _current_request() -> Request | None:
    try:
        return get_http_request()
    except RuntimeError:
        return None


# --- the owner binding ------------------------------------------------------------


@dataclass(frozen=True)
class OwnerVerdict:
    """What the verifier decided about one id_token: the access token for the
    owner, or why not — `invalid` (signature, shape, expiry: the browser login's
    contract), `unavailable` (the provider's keys could not be fetched),
    `identity` (verified, but not the bound owner — `subject` names who)."""

    token: AccessToken | None
    reason: str
    subject: str | None = None


class OwnerBoundIdTokenVerifier(TokenVerifier):
    """The proxy's token verifier: the provider's id_token, verified through
    `OidcProvider` and bound to the owner row. Declares no required scope — the
    mount then requires none, which is what keeps personal access tokens valid
    on `/mcp/` in OIDC mode; the advertised scopes are the proxy's
    `valid_scopes`."""

    def __init__(self, provider: Callable[[], OidcProvider]) -> None:
        super().__init__(required_scopes=[])
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
        return OwnerVerdict(
            AccessToken(
                token=_reference(id_token),
                client_id=provider.client_id,
                scopes=[],
                expires_at=int(claims["exp"]),
                claims={"kind": "mcp", "iss": claims["iss"], "sub": subject},
            ),
            "ok",
            subject,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        return (await self.check(token)).token


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
        self._owner_verifier = OwnerBoundIdTokenVerifier(provider)
        self._pat_verifier = pat_verifier
        #: Test seam: an httpx transport the upstream code exchange and refresh
        #: go through instead of the network, so the suite can play the
        #: provider. None on the shipped app — nothing sets it.
        self.upstream_transport: httpx.AsyncBaseTransport | None = None
        super().__init__(
            upstream_authorization_endpoint=UNRESOLVED_ENDPOINT,
            upstream_token_endpoint=UNRESOLVED_ENDPOINT,
            # Registers `/revoke` unconditionally; resolved to the provider's
            # endpoint, or to None (nothing upstream to revoke), on first use.
            upstream_revocation_endpoint=UNRESOLVED_ENDPOINT,
            upstream_client_id=settings.oidc_client_id,
            upstream_client_secret=settings.oidc_client_secret,
            token_verifier=self._owner_verifier,
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

    # -- the upstream, resolved lazily ------------------------------------------

    async def _resolve_upstream(self) -> None:
        """Read the provider's endpoints off the (cached, issuer-checked)
        discovery document. Raises `UnavailableError` when the provider cannot
        be reached and nothing is cached yet."""
        metadata = await self._provider().metadata()
        self._upstream_authorization_endpoint = metadata.authorization_endpoint
        self._upstream_token_endpoint = metadata.token_endpoint
        self._upstream_revocation_endpoint = metadata.revocation_endpoint

    async def _resolve_upstream_softly(self) -> None:
        """For paths that only *may* need the upstream (a refresh behind a
        request, a revocation): a down provider leaves the endpoints as they
        are and the upstream call fails on its own."""
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

    async def _handle_idp_callback(self, request: Request):
        try:
            await self._resolve_upstream()
        except UnavailableError:
            return create_secure_html_response(_PROVIDER_UNAVAILABLE_HTML, status_code=503)
        return await super()._handle_idp_callback(request)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        code_model = await self._code_store.get(key=authorization_code.code)
        if code_model is None:
            # The SDK's own `invalid_grant` for a code it does not hold.
            return await super().exchange_authorization_code(client, authorization_code)
        verdict = await self._owner_verifier.check(code_model.idp_tokens.get("id_token"))
        if verdict.token is None:
            # Consume the code first: a retry must not find it.
            await self._code_store.delete(key=authorization_code.code)
            if verdict.reason == "identity":
                await self._record(
                    audit.MCP_IDENTITY_REFUSED,
                    detail=f"subject={verdict.subject} client={client.client_id}",
                )
                raise TokenError("invalid_grant", _NOT_OWNER)
            await self._record(
                audit.OIDC_LOGIN_FAILED,
                detail=f"id_token_{verdict.reason} client={client.client_id}",
            )
            raise TokenError(
                "invalid_grant",
                _PROVIDER_UNAVAILABLE if verdict.reason == "unavailable" else _NOT_OWNER,
            )
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
            await self._resolve_upstream()
        except UnavailableError as exc:
            raise TokenError("invalid_request", _PROVIDER_UNAVAILABLE) from exc
        return await super().exchange_refresh_token(client, refresh_token, scopes)

    async def revoke_token(self, token) -> None:
        await self._resolve_upstream_softly()
        await super().revoke_token(token)

    # -- the bearer, per request ---------------------------------------------------------

    def _get_verification_token(self, upstream_token_set) -> str | None:
        """What the verifier sees on every request: the provider's **id_token**,
        never its access token — Google's are opaque and Keycloak's carry no
        claim this instance can bind an owner to (the spike's one verifier
        shape). `OIDCProxy`'s hook, reproduced here because this proxy is built
        on `OAuthProxy` for the lazy upstream (see the module docstring)."""
        return upstream_token_set.raw_token_data.get("id_token")

    def _uses_alternate_verification(self) -> bool:
        """Tells FastMCP the verified token is not the upstream access token, so
        the returned `AccessToken` carries the upstream set's expiry rather than
        the id_token's (the other `OIDCProxy` hook)."""
        return True

    async def load_access_token(self, token: str) -> AccessToken | None:
        token = token.strip()
        if token.startswith(f"{token_format.TOKEN_KIND}_"):
            # The owner's own credential, valid in every mode (§5.5).
            return await self._pat_verifier.verify_token(token)
        await self._resolve_upstream_softly()
        validated = await super().load_access_token(token)
        if validated is None:
            return None
        try:
            payload = self.jwt_issuer.verify_token(token)
        except Exception:
            return None
        client_id = str(payload.get("client_id") or validated.client_id)
        # FastMCP hands back the *upstream* access token in `token`; a reference
        # stands in for it here, and the MCP client's id rides along for audit.
        return validated.model_copy(
            update={
                "token": _reference(token),
                "client_id": client_id,
                "claims": {**(validated.claims or {}), "client_id": client_id},
            }
        )

    # -- audit ---------------------------------------------------------------------------

    async def _record(self, event: str, *, detail: str, principal=None) -> None:
        request = _current_request()
        async with session_scope() as session:
            await audit.record_event(
                session,
                event,
                principal=principal,
                request=request,
                target=f"{MCP_MOUNT}/token",
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


def declare_child_verbs(mcp_app: Starlette) -> None:
    """Clear the SDK's own method metadata on every protocol route, so the
    registry's `RouteBinding` is the one verb boundary for the mount — an
    undeclared verb is its 405 with `Allow` and the profile, not Starlette's
    without either (the transport's precedent, `build_mcp_app`)."""
    for route in mcp_app.router.routes:
        if isinstance(route, Route) and MCP_MOUNT + route.path in MCP_OAUTH_ROUTES:
            route.methods = None  # type: ignore[assignment]
