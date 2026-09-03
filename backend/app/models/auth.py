"""Authentication and audit tables (Milestone 6, §5.5–§5.6).

The foundation M6-2 (#187) lays: the tables the credential mechanisms fill in.
Nothing writes them yet — local authentication (#188) claims the owner and
manages `credential`/`session`, personal access tokens (#189) manage
`personal_access_token`, and every M6 item appends to `audit_event` (#193). They
are declared here now so those items add rows, not tables.

These tables are **never** portable (rule 9, §5.6 leakage): they are not in
`services/portability/spec.py`, so an export cannot become a credential dump and
an import cannot forge a session or token. `tests/test_auth_tables.py` holds that.

Secrets are stored as digests, never in the clear: `credential.secret_hash` is
an Argon2id verifier (#188), `session.token_hash` and
`personal_access_token.secret_hash` are digests of opaque values shown once
(#188/#189). No column here holds a recoverable secret.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

#: The one primary-key value the owner singleton allows — the instance has
#: exactly one owner (§5.5), the same shape as `instance_settings`.
OWNER_ROW_ID = 1


class Owner(TimestampMixin, Base):
    """The single owner identity and the instance's claim state (§5.5, §5.6).

    Exactly one row, seeded **unclaimed** by the migration: `claimed_at` is null
    until `POST /auth/setup` claims the instance (#188). While it is null every
    collection route fails closed (§5.6 safe failure) and `GET /auth/session`
    reports `unclaimed`. The OIDC binding is the stable `(issuer, subject)` the
    upstream identity must equal in OIDC mode (#191); `display_name` is the email
    or name shown in the UI and is never used for authorization.
    """

    __tablename__ = "owner"

    id: Mapped[int] = mapped_column(primary_key=True, default=OWNER_ROW_ID)
    #: Null = unclaimed. Set once, when the setup token is used (#188).
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: The bound OIDC identity (OIDC mode, #191). Null in local mode.
    oidc_issuer: Mapped[str | None]
    oidc_subject: Mapped[str | None]
    #: Display only — the owner's email or name. Never an authorization input.
    display_name: Mapped[str | None]

    __table_args__ = (CheckConstraint(f"id = {OWNER_ROW_ID}", name="singleton"),)


class Credential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The local password verifier (§5.6, session fixation; local mode, #188).

    `secret_hash` is an Argon2id encoded string — it carries its own salt and
    parameters, so verification needs no other column and a parameter bump is a
    re-hash on next login. `algorithm` records the scheme for a future rotation.
    Absent in OIDC mode; a credential change replaces the row and revokes every
    session (§5.6). Never populated by M6-2.
    """

    __tablename__ = "credential"

    secret_hash: Mapped[str]
    algorithm: Mapped[str] = mapped_column(default="argon2id")


class Session(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An owner browser session (§5.6, session fixation; #188).

    The opaque session id lives only in the cookie; `token_hash` is its digest,
    so a database read cannot reconstruct a live session. Rotated on login,
    bounded by idle (`last_used_at`) and absolute (`expires_at`) expiry, and
    revoked — `revoked_at` set — on logout, credential change and OIDC rebind
    (§5.6). Never populated by M6-2.
    """

    __tablename__ = "session"

    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PersonalAccessToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A personal access token — `ptk_<id>_<secret>` (§5.6, credential leakage;
    #189).

    Shown once. `token_prefix` is the public id looked up on presentation;
    `secret_hash` is the digest the presented secret is compared against with
    `hmac.compare_digest`. `scopes` is the granted set as canonical identifiers
    (`collection:read`, or `collection:read,collection:write`); never
    `instance:admin` — no admin tokens in M6 (§5.5). `expires_at` optional,
    `revoked_at` set on revocation, `last_used_at` updated on use. Never
    populated by M6-2.
    """

    __tablename__ = "personal_access_token"

    token_prefix: Mapped[str] = mapped_column(unique=True, index=True)
    secret_hash: Mapped[str]
    name: Mapped[str]
    #: Canonical scope identifiers, comma-separated, validated by the service.
    scopes: Mapped[str]
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    """One security-relevant event (§5.6, log and audit hygiene; #193).

    Each row carries the principal id, credential kind, client address and the
    route or tool — **never a secret, never a request body** (§5.6). `event_type`
    is a free-text vocabulary that grows with the features that emit it (setup
    claimed, login success/failure, logout, session revoked, PAT
    minted/revoked/used-after-revoke, OIDC rebind, recovery run, Host/Origin
    rejection). Retention is a documented prune (#193). No `updated_at`: audit
    rows are append-only.
    """

    __tablename__ = "audit_event"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(index=True)
    #: The principal kind label (`owner`, `pat:write`, `anon`, …) and its
    #: credential subject (session id, token id) — an id, never the secret.
    principal_kind: Mapped[str | None]
    principal_subject: Mapped[str | None]
    #: The client address as resolved for audit (behind TRUSTED_PROXIES) — the
    #: raw peer otherwise (§5.6, proxy trust).
    client_address: Mapped[str | None]
    #: The route path or MCP tool name the event concerns.
    target: Mapped[str | None]
    #: A short structured note the event carries — never a body or a secret.
    detail: Mapped[str | None] = mapped_column(String(500))
