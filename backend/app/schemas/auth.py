"""Request and response shapes for the auth routes (§5.5 families 2–3; M6-3, #188)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.principal import Scope


class SessionRead(BaseModel):
    """`GET /auth/session` — what a browser needs before it can show anything:
    whether the instance is claimed, whether this browser is the owner, and the
    instance's language and formatting locale so the setup and login screens
    render in the right language. No version, no collection data (§5.5, family
    2). `csrf_token` is present only for the owner and travels back in
    `X-CSRF-Token` on every unsafe request."""

    state: Literal["unclaimed", "anonymous", "owner"]
    interface_language: str
    formatting_locale: str
    csrf_token: str | None = None
    #: Which way in this instance offers (§5.4; #191): a password, or a sign-in
    #: at the configured provider. In OIDC mode `unclaimed` also covers a claimed
    #: owner with no binding yet (a switch from local mode, or after
    #: `recovery rebind-oidc`) — the setup screen with the provider button.
    auth_mode: Literal["local", "oidc"] = "local"
    #: The provider's issuer URL, so the login screen can name it. OIDC mode only.
    oidc_issuer: str | None = None


class SetupRequest(BaseModel):
    """`POST /auth/setup`: the token from the API log and the owner's first password."""

    token: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=4096)


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=4096)


class OidcStartRequest(BaseModel):
    """`POST /auth/oidc/start`: begin a login at the provider. `setup_token` is
    required only while the owner is unbound (the instance reports `unclaimed`):
    it is what lets the identity that completes this login become the owner."""

    model_config = ConfigDict(extra="forbid")

    setup_token: str | None = Field(default=None, min_length=1, max_length=256)


class OidcStartRead(BaseModel):
    """Where the browser goes next: the provider's authorization endpoint with
    this login's `state`, `nonce` and PKCE challenge. The transaction is bound to
    the browser by the cookie the same response sets."""

    authorization_url: str


# --- personal access tokens (§5.5 family 6; M6-4, #189) ------------------------


class TokenCreate(BaseModel):
    """`POST /auth/tokens`: a name for the owner's own reference, the scopes —
    `collection:read`, or `collection:read` and `collection:write`; never
    `instance:admin` — and an optional expiry (offset-bearing ISO 8601)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    scopes: list[Scope] = Field(min_length=1, max_length=3)
    expires_at: datetime | None = None


class TokenRead(BaseModel):
    """One token as the list and the mint response show it: everything but the
    secret. `token_prefix` is the public id (`ptk_<prefix>_…`) so the owner can
    match a token in a client's configuration to a row here; `scopes` is the
    granted set as canonical identifiers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None

    @field_validator("scopes", mode="before")
    @classmethod
    def _split_scopes(cls, value: object) -> object:
        if isinstance(value, str):
            return [part for part in value.split(",") if part]
        return value


class TokenMinted(TokenRead):
    """The mint response: the row plus the raw token — shown once, stored as a
    digest, never returned again (`no-store` on the route)."""

    token: str
