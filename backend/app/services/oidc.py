"""Browser OpenID Connect login — the service layer (§5.4 OIDC mode; §5.5 family 3;
§5.6 open redirect and code interception, safe failure; M6-6, #191).

The owner signs in at a configured provider and is **bound** to the stable
`(issuer, subject)` that provider asserts in a signed id_token. Nothing else
about the identity is an authorization input: `email` and `name` are display
only, and an identity whose `(issuer, subject)` is not the bound pair is refused
with an audit row and no session, however plausible its email (T6).

The round trip:

1. `begin_login` — a transaction row (`oidc_login`) holding digests of two
   fresh secrets: `state`, which goes through the provider and comes back in the
   callback URL, and a **binding** value that lives only in an `HttpOnly` cookie
   on this host. Both must return together, so a callback URL replayed in
   another browser, or forced onto the owner's by a hostile page, names no
   transaction. The row also carries the `nonce` the id_token must echo and the
   PKCE verifier for the code exchange. While the owner is **unbound** — a fresh
   instance, a switch from local mode, or after `recovery rebind-oidc` — the
   setup token from the API log must be presented here, and the row records
   that (`claiming`): it is what lets the identity that completes the login
   become the owner, the same single-use token the local claim uses.
2. The browser goes to the provider's authorization endpoint — the URL is built
   from the discovery document, never from a request — and comes back to
   `<PUBLIC_BASE_URL>/api/auth/oidc/callback`, the one redirect URI registered
   with the provider.
3. `complete_login` — the transaction is consumed **before** any network call
   (a replay in flight finds it used), the code is exchanged server-side with
   the client secret, the id_token's signature is checked against the provider's
   JWKS and its claims against the contract in `validate_id_token_claims` —
   `iss`, `sub`, exactly this client in `aud` and `azp`, `exp`/`iat`/`nbf` as
   numbers against the clock, the transaction's `nonce` as a string — and only
   then is the owner row read: bind it if it is unbound and the setup token
   matched at start, refuse anything that is not the bound pair, mint a session.

The provider's metadata and keys are fetched lazily and cached in the process,
so an unreachable provider fails **new logins** with a 503 and nothing else:
existing sessions, personal tokens and (later) MCP links are untouched (§5.6,
safe failure), and the mode never falls back to local on its own.

What this module does not know: cookies, headers, redirects — the router's
(`routers/auth.py`). It takes and returns raw values so the recovery command
can drive the rebind from a shell.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import math
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app import error_codes
from app.auth import credentials
from app.auth.budget import FailureBudget
from app.auth.principal import anonymous, internal
from app.auth.setup_token import SetupToken
from app.config import Settings
from app.exceptions import UnavailableError
from app.models import OidcLogin
from app.models.enums import AuthMode
from app.services import audit
from app.services import auth as auth_service
from app.services.write_gate import acquire_write_gate

log = logging.getLogger("plamotrack.auth")

#: A login must complete within this long of starting; the row is then dead.
LOGIN_TTL = timedelta(minutes=10)
#: What the provider is asked for: identity, plus the email/name shown in the UI.
SCOPES = "openid email profile"
#: The callback as the browser reaches it — under `/api/`, which the ingress
#: strips, so the app serves it as `/auth/oidc/callback`.
CALLBACK_PATH = "/api/auth/oidc/callback"
#: One timeout for discovery, the JWKS fetch and the code exchange.
HTTP_TIMEOUT = 10.0
#: Clock skew tolerated on the id_token's `exp`, `iat` and `nbf`, in seconds.
CLOCK_LEEWAY = 60
#: The signature algorithms accepted on an id_token — asymmetric only, so the
#: client secret can never sign one.
ID_TOKEN_ALGORITHMS = ("RS256", "ES256", "PS256")

_DISCOVERY = "/.well-known/openid-configuration"
_PROVIDER_UNAVAILABLE = (
    "The identity provider could not be reached. Existing sessions still work; try again shortly."
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ProviderMetadata:
    """The four things the flow needs from the discovery document."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


class CallbackError(StrEnum):
    """What the callback hands back to the SPA in `?auth_error=` when it opens
    no session — a word, never the provider's description, never a token. Not
    envelope codes: a browser navigation reads no JSON."""

    #: The owner cancelled at the provider.
    DENIED = "oidc_denied"
    #: No live transaction for that state — expired, reused, or another browser.
    EXPIRED = "oidc_expired"
    #: The exchange or the id_token validation failed, or the provider was down.
    FAILED = "oidc_failed"
    #: The owner is unbound and the setup token was not presented at start.
    SETUP_REQUIRED = "oidc_setup_required"
    #: A signed-in identity that is not the bound owner — audited, no session.
    IDENTITY_REFUSED = "oidc_identity_refused"


class OidcLoginRefused(Exception):
    """A callback that must not open a session. `code` is the `CallbackError`
    the browser is sent back to the SPA with."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _numeric_date(value: object) -> bool:
    """A JWT NumericDate as its value domain, not its Python type: a JSON number
    naming an instant (RFC 7519 §2), which JSON cannot spell as NaN or Infinity
    (RFC 8259 §6) though Python's parser admits both — and every clock
    comparison against NaN is false, so a NaN `exp` never "passes" (Codex #209
    round 2, f3). Integers on their own branch: an arbitrarily large one is a
    valid instant, and `math.isfinite` on it raises rather than answers. Not
    the bool that is also an `int`."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def validate_id_token_claims(
    claims: dict,
    *,
    issuer: str,
    client_id: str,
    nonce: str,
    now: int | None = None,
    leeway: int = CLOCK_LEEWAY,
) -> None:
    """The id_token claim contract, in one place, applied after the signature
    has verified (OpenID Connect Core 1.0 §2 and §3.1.3.7; Codex #209 round 1,
    f2). Each claim is checked for its **type** before its value, so a shape a
    generic JWT validator reads loosely — a list where a string belongs, a
    null, a bool where a number belongs, an audience list that merely
    *contains* this client — is refused rather than matched:

    - `iss` is the configured issuer, as a string (step 2);
    - `sub` is a non-empty string — nothing else can bind an owner, and there
      is no fall-back to `email` (Keycloak 25+ keeps `sub` in a client scope;
      without it there is nothing to bind to);
    - `aud` names exactly this client: the string, or an array whose only
      member is it. An additional audience is one this client does not trust,
      whatever `azp` says, so it is refused (step 3);
    - `azp`, when present, is this client's id (step 5);
    - `exp` is a NumericDate — a finite number, `_numeric_date` — no more than
      `leeway` in the past (step 9); `iat` a NumericDate — §2 requires the claim
      — no more than `leeway` in the future (step 10); `nbf`, when present,
      likewise;
    - `nonce` is the string this login sent, not a list holding it (step 11).

    Raises `OidcLoginRefused(FAILED)`; the log line names the claim, never the
    value (T10)."""
    clock = int(time.time()) if now is None else now

    def refused(claim: str, why: str) -> OidcLoginRefused:
        log.warning("OIDC id_token rejected: %s %s", claim, why)
        return OidcLoginRefused(CallbackError.FAILED)

    iss = claims.get("iss")
    if not isinstance(iss, str) or iss != issuer:
        raise refused("iss", "is not the configured issuer")
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise refused("sub", "is missing or not a string")
    aud = claims.get("aud")
    audiences = [aud] if isinstance(aud, str) else aud
    if (
        not isinstance(audiences, list)
        or not all(isinstance(member, str) for member in audiences)
        or set(audiences) != {client_id}
    ):
        raise refused("aud", "is not exactly this client")
    if "azp" in claims and claims["azp"] != client_id:
        raise refused("azp", "is not this client")
    exp = claims.get("exp")
    if not _numeric_date(exp):
        raise refused("exp", "is missing or not a NumericDate")
    if exp < clock - leeway:
        raise refused("exp", "has passed")
    iat = claims.get("iat")
    if not _numeric_date(iat):
        raise refused("iat", "is missing or not a NumericDate")
    if iat > clock + leeway:
        raise refused("iat", "is in the future")
    if "nbf" in claims:
        nbf = claims["nbf"]
        if not _numeric_date(nbf):
            raise refused("nbf", "is not a NumericDate")
        if nbf > clock + leeway:
            raise refused("nbf", "is in the future")
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or token_nonce != nonce:
        raise refused("nonce", "is not this login's")


class OidcProvider:
    """The configured provider: discovery, keys, the code exchange and id_token
    validation. One per app (`app.state`), built from settings; its HTTP
    client is injectable so the suite can play the provider."""

    def __init__(
        self,
        *,
        issuer: str,
        client_id: str,
        client_secret: str,
        public_base_url: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.issuer = issuer
        self.client_id = client_id
        self._client_secret = client_secret
        self.public_base_url = public_base_url.rstrip("/")
        self._http = http_client
        self._metadata: ProviderMetadata | None = None
        self._keys: KeySet | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def from_settings(
        cls, settings: Settings, *, http_client: httpx.AsyncClient | None = None
    ) -> OidcProvider | None:
        """The provider for OIDC mode, or None in local mode. The settings
        validator has already required the four values."""
        if settings.auth_mode != "oidc":
            return None
        return cls(
            issuer=settings.oidc_issuer,
            client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret,
            public_base_url=settings.public_base_url,
            http_client=http_client,
        )

    @property
    def redirect_uri(self) -> str:
        """The one redirect URI registered with the provider: built from
        `PUBLIC_BASE_URL`, never from `Host` (§5.6, proxy trust)."""
        return self.public_base_url + CALLBACK_PATH

    @property
    def home_url(self) -> str:
        """Where the browser lands after the callback: the SPA's root."""
        return self.public_base_url + "/"

    # --- HTTP --------------------------------------------------------------------

    async def _get_json(self, url: str) -> dict:
        try:
            if self._http is not None:
                response = await self._http.get(url)
            else:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    response = await client.get(url)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("OIDC provider request failed: %s %s", type(exc).__name__, url)
            raise UnavailableError(
                _PROVIDER_UNAVAILABLE, code=error_codes.AUTH_OIDC_PROVIDER_UNAVAILABLE
            ) from exc
        if not isinstance(body, dict):
            raise UnavailableError(
                _PROVIDER_UNAVAILABLE, code=error_codes.AUTH_OIDC_PROVIDER_UNAVAILABLE
            )
        return body

    async def metadata(self) -> ProviderMetadata:
        """The discovery document, fetched once and cached. Its `issuer` must
        equal the configured one (OpenID Discovery §4.3) — a document that says
        otherwise is a misconfiguration, refused rather than followed."""
        if self._metadata is not None:
            return self._metadata
        async with self._lock:
            if self._metadata is not None:
                return self._metadata
            document = await self._get_json(self.issuer.rstrip("/") + _DISCOVERY)
            issuer = document.get("issuer")
            if issuer != self.issuer:
                log.error(
                    "OIDC discovery document names issuer %r, OIDC_ISSUER is %r — refusing",
                    issuer,
                    self.issuer,
                )
                raise UnavailableError(
                    "The identity provider's discovery document does not name OIDC_ISSUER "
                    "as its issuer; check the setting.",
                    code=error_codes.AUTH_OIDC_PROVIDER_UNAVAILABLE,
                )
            try:
                metadata = ProviderMetadata(
                    issuer=issuer,
                    authorization_endpoint=str(document["authorization_endpoint"]),
                    token_endpoint=str(document["token_endpoint"]),
                    jwks_uri=str(document["jwks_uri"]),
                )
            except KeyError as exc:
                raise UnavailableError(
                    "The identity provider's discovery document is missing "
                    f"{exc.args[0]}; the provider is not usable for login.",
                    code=error_codes.AUTH_OIDC_PROVIDER_UNAVAILABLE,
                ) from exc
            self._metadata = metadata
            return metadata

    async def keys(self, *, refresh: bool = False) -> KeySet:
        """The provider's signing keys, cached; `refresh` re-fetches (an
        id_token signed with a key id not yet seen — rotation)."""
        if self._keys is not None and not refresh:
            return self._keys
        metadata = await self.metadata()
        async with self._lock:
            document = await self._get_json(metadata.jwks_uri)
            try:
                self._keys = KeySet.import_key_set(document)
            except (ValueError, KeyError, TypeError) as exc:
                raise UnavailableError(
                    _PROVIDER_UNAVAILABLE, code=error_codes.AUTH_OIDC_PROVIDER_UNAVAILABLE
                ) from exc
            return self._keys

    async def warm_up(self) -> bool:
        """Fetch discovery and keys at startup so the first login is not the
        first network call. Never raises — an unreachable provider fails new
        logins, not the process (§5.6, safe failure)."""
        try:
            await self.metadata()
            await self.keys()
        except UnavailableError as exc:
            log.warning("OIDC provider %s not reachable at startup: %s", self.issuer, exc)
            return False
        log.info("Auth mode: oidc — issuer %s, callback %s", self.issuer, self.redirect_uri)
        return True

    async def exchange_code(self, code: str, code_verifier: str) -> dict:
        """The authorization code for the provider's tokens, server to server,
        with the client secret as HTTP Basic (`client_secret_basic`, the method
        every provider must support) and the PKCE verifier. A provider error is
        a refused login; a network failure is a 503."""
        metadata = await self.metadata()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
        }
        try:
            if self._http is not None:
                response = await self._http.post(
                    metadata.token_endpoint, data=form, auth=(self.client_id, self._client_secret)
                )
            else:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                    response = await client.post(
                        metadata.token_endpoint,
                        data=form,
                        auth=(self.client_id, self._client_secret),
                    )
        except httpx.HTTPError as exc:
            log.warning("OIDC code exchange failed: %s", type(exc).__name__)
            raise UnavailableError(
                _PROVIDER_UNAVAILABLE, code=error_codes.AUTH_OIDC_PROVIDER_UNAVAILABLE
            ) from exc
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code != 200 or not isinstance(body, dict):
            # The provider's `error` code is a word worth logging; its
            # description and the rest of the body are not (they can quote
            # what was sent).
            provider_error = body.get("error") if isinstance(body, dict) else None
            log.warning(
                "OIDC code exchange refused: status=%s error=%s",
                response.status_code,
                provider_error,
            )
            raise OidcLoginRefused(CallbackError.FAILED)
        return body

    async def verify_id_token(self, id_token: object, *, nonce: str) -> dict:
        """The id_token's claims, once its signature verifies against the
        provider's keys on an asymmetric algorithm and the claims meet the
        contract in `validate_id_token_claims` for this issuer, this client and
        this login's nonce. Anything else is a refused login, never a session."""
        if not isinstance(id_token, str) or not id_token:
            raise OidcLoginRefused(CallbackError.FAILED)
        keys = await self.keys()
        try:
            token = jwt.decode(id_token, keys, algorithms=list(ID_TOKEN_ALGORITHMS))
        except (JoseError, ValueError):
            # A key id the cached set does not hold: the provider may have
            # rotated. One refresh, then the answer stands.
            try:
                keys = await self.keys(refresh=True)
                token = jwt.decode(id_token, keys, algorithms=list(ID_TOKEN_ALGORITHMS))
            except (JoseError, ValueError):
                log.warning("OIDC id_token rejected: signature or format")
                raise OidcLoginRefused(CallbackError.FAILED) from None
        validate_id_token_claims(
            token.claims, issuer=self.issuer, client_id=self.client_id, nonce=nonce
        )
        return dict(token.claims)


# --- the owner's state --------------------------------------------------------------


async def owner_is_unbound(session: AsyncSession) -> bool:
    """OIDC mode's setup condition: no owner claimed yet, or a claimed owner with
    no `(issuer, subject)` — a switch from local mode, or after a rebind. Either
    way the next login needs the setup token and binds."""
    owner = await auth_service.owner_row(session)
    return owner.claimed_at is None or owner.oidc_subject is None


# --- the flows ----------------------------------------------------------------------


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def begin_login(
    session: AsyncSession,
    provider: OidcProvider,
    *,
    request: Request | None,
    setup_token: str | None,
    setup_state: SetupToken,
    budget: FailureBudget,
) -> tuple[str, str]:
    """`POST /auth/oidc/start`. Returns the provider authorization URL the
    browser goes to and the raw binding value for the cookie. While the owner is
    unbound the setup token is required and counts against the failure budget
    exactly as `POST /auth/setup` does (T8); a match is remembered on the row,
    the token itself is consumed only when the callback binds."""
    # Discovery first, outside the gate: network I/O holds no lock, and an
    # unreachable provider is a 503 before anything is written.
    metadata = await provider.metadata()
    await acquire_write_gate(session)
    claiming = False
    if await owner_is_unbound(session):
        await auth_service.refuse_throttled(
            session, budget, request=request, target="/auth/oidc/start"
        )
        if setup_token is None or not setup_state.matches(setup_token):
            await auth_service.record_setup_failure(
                session, budget, request=request, target="/auth/oidc/start"
            )
        claiming = True
    now = _now()
    # Housekeeping: rows that can no longer complete.
    await session.execute(
        delete(OidcLogin).where(or_(OidcLogin.expires_at < now, OidcLogin.used_at.is_not(None)))
    )
    state = credentials.new_token()
    binding = credentials.new_token()
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)  # 64 chars: within RFC 7636's 43–128
    session.add(
        OidcLogin(
            state_hash=credentials.digest(state),
            binding_hash=credentials.digest(binding),
            nonce=nonce,
            code_verifier=verifier,
            claiming=claiming,
            expires_at=now + LOGIN_TTL,
        )
    )
    await session.commit()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": provider.redirect_uri,
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "code_challenge": _pkce_challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    joiner = "&" if "?" in metadata.authorization_endpoint else "?"
    return metadata.authorization_endpoint + joiner + query, binding


async def _refuse(
    session: AsyncSession, request: Request | None, *, code: str, detail: str
) -> OidcLoginRefused:
    """Audit a failed round trip (committed — the caller is about to raise) and
    hand back the refusal to raise."""
    await audit.record_event(
        session,
        audit.OIDC_LOGIN_FAILED,
        principal=anonymous(),
        request=request,
        target="/auth/oidc/callback",
        detail=detail,
    )
    await session.commit()
    return OidcLoginRefused(code)


async def complete_login(
    session: AsyncSession,
    provider: OidcProvider,
    *,
    request: Request | None,
    state: str | None,
    code: str | None,
    error: str | None,
    binding: str | None,
    setup_state: SetupToken,
) -> str:
    """`GET /auth/oidc/callback`. Returns the raw session token for the cookie,
    or raises `OidcLoginRefused` with the code the browser is sent back with.

    Two transactions, deliberately: the first consumes the `oidc_login` row
    (state, binding, expiry, single use) and commits before the network calls,
    so the write gate is never held across the provider round trip and a
    concurrent replay of the same callback finds the row used; the second
    reads the owner row `FOR UPDATE` and either binds it or checks it."""
    await acquire_write_gate(session)
    row = None
    if state:
        row = (
            await session.execute(
                select(OidcLogin).where(OidcLogin.state_hash == credentials.digest(state))
            )
        ).scalar_one_or_none()
    now = _now()
    if (
        row is None
        or row.used_at is not None
        or now >= row.expires_at
        or binding is None
        or not credentials.tokens_match(binding, row.binding_hash)
    ):
        raise await _refuse(
            session, request, code=CallbackError.EXPIRED, detail="no live transaction"
        )
    row.used_at = now
    claiming, nonce, verifier = row.claiming, row.nonce, row.code_verifier
    await session.commit()

    if error is not None or not code:
        code_out = CallbackError.DENIED if error == "access_denied" else CallbackError.FAILED
        raise await _refuse(
            session, request, code=code_out, detail=f"provider_error={error or 'missing_code'}"
        )

    try:
        tokens = await provider.exchange_code(code, verifier)
        claims = await provider.verify_id_token(tokens.get("id_token"), nonce=nonce)
    except UnavailableError:
        raise await _refuse(
            session, request, code=CallbackError.FAILED, detail="provider_unavailable"
        ) from None
    except OidcLoginRefused as exc:
        raise await _refuse(session, request, code=exc.code, detail="id_token_rejected") from None
    # A non-empty string, or `verify_id_token` would have refused: the claim
    # contract lives in one validator, and `email` is never a fall-back.
    subject: str = claims["sub"]
    display_name = _display_name(claims)

    await acquire_write_gate(session)
    owner = await auth_service.owner_row(session, for_update=True)
    now = _now()
    if owner.claimed_at is None or owner.oidc_subject is None:
        if not claiming:
            raise await _refuse(
                session,
                request,
                code=CallbackError.SETUP_REQUIRED,
                detail="unbound owner, no setup token at start",
            )
        owner.oidc_issuer = provider.issuer
        owner.oidc_subject = subject
        owner.display_name = display_name
        if owner.claimed_at is None:
            owner.claimed_at = now
        setup_state.consume()
        raw, session_row = auth_service.new_session_row(now, auth_mode=AuthMode.OIDC)
        session.add(session_row)
        await session.flush()
        await audit.record_event(
            session,
            audit.SETUP_CLAIMED,
            principal=auth_service.owner_principal(session_row),
            request=request,
            target="/auth/oidc/callback",
            detail="via=oidc",
        )
        await session.commit()
        return raw

    if (owner.oidc_issuer, owner.oidc_subject) != (provider.issuer, subject):
        await audit.record_event(
            session,
            audit.OIDC_IDENTITY_REFUSED,
            principal=anonymous(),
            request=request,
            target="/auth/oidc/callback",
            detail=f"subject={subject}",
        )
        await session.commit()
        raise OidcLoginRefused(CallbackError.IDENTITY_REFUSED)
    if display_name and owner.display_name != display_name:
        owner.display_name = display_name
    raw, session_row = auth_service.new_session_row(now, auth_mode=AuthMode.OIDC)
    session.add(session_row)
    await session.flush()
    await audit.record_event(
        session,
        audit.LOGIN_SUCCEEDED,
        principal=auth_service.owner_principal(session_row),
        request=request,
        target="/auth/oidc/callback",
        detail="via=oidc",
    )
    await session.commit()
    return raw


def _display_name(claims: dict) -> str | None:
    for key in ("email", "name", "preferred_username"):
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return None


# --- recovery -------------------------------------------------------------------------


async def recovery_rebind_oidc(session: AsyncSession) -> int:
    """The host-side rebind (§5.6, credentials lost): clear the owner's
    `(issuer, subject)` and revoke every session. The instance then reports
    `unclaimed` in OIDC mode, prints a setup token at the next start, and the
    next provider login that presents it binds afresh — the operator never
    types a subject. Never an HTTP endpoint. Returns the sessions revoked."""
    await acquire_write_gate(session)
    owner = await auth_service.owner_row(session, for_update=True)
    owner.oidc_issuer = None
    owner.oidc_subject = None
    revoked = await auth_service.revoke_all_sessions(
        session, target="recovery rebind-oidc", principal=internal(), client_address="host"
    )
    await audit.record_event(
        session,
        audit.OIDC_REBIND,
        principal=internal(),
        target="recovery rebind-oidc",
        client_address="host",
    )
    await audit.record_event(
        session,
        audit.RECOVERY_RUN,
        principal=internal(),
        target="recovery rebind-oidc",
        detail=f"sessions_revoked={revoked}",
        client_address="host",
    )
    await session.commit()
    return revoked
