"""The MCP OAuth proxy's state table — what both of its writers agree on (#214).

`mcp_oauth_state` (Alembic-owned; never portable, rule 9) is one key-value
table holding FastMCP's six collections. Two writers reach it: the proxy in
`app/auth/mcp_oauth.py`, on every OAuth transition, and the host-side
`recovery rebind-oidc` (`app/services/oidc.py`), which purges the grants of an
owner the instance no longer trusts. The proxy imports the service module, so
the service cannot import the proxy; what both need lives here — the collection
names and which of them are *a grant's*, the grant lock's key, the storage key
and the store itself — so neither side carries a private copy that can drift.
"""

from __future__ import annotations

import base64
import hashlib

import asyncpg
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from key_value.aio.stores.postgresql import PostgreSQLStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from sqlalchemy.engine import make_url

from app.config import Settings
from app.models import MCP_OAUTH_STATE_TABLE

# --- the collections ----------------------------------------------------------------------

#: The grant record — the provider's token set for one link, keyed by the grant
#: id. FastMCP's own name for the collection; the record gate's adapter reads and
#: writes this same one.
GRANT_COLLECTION = "mcp-upstream-tokens"
#: Issued token id (JTI) → the grant record it was minted on.
JTI_COLLECTION = "mcp-jti-mappings"
#: Refresh-token metadata, keyed by the token's hash.
REFRESH_COLLECTION = "mcp-refresh-tokens"
#: An authorization code the client has not yet exchanged — it already carries
#: the provider's token response (`idp_tokens`) for whoever signed in, so the
#: rebind reads it for what to revoke at the provider, as it does a grant.
CODE_COLLECTION = "mcp-authorization-codes"
#: Dynamically registered clients (RFC 7591).
CLIENT_COLLECTION = "mcp-oauth-proxy-clients"
#: Consent transactions in flight.
TRANSACTION_COLLECTION = "mcp-oauth-transactions"

#: The collections that are *a grant's* — every row of them names, maps to or
#: holds an upstream credential — and so what a rebind purges. A registered
#: client and a consent transaction belong to no grant and stay: the client can
#: link again, and a consent the new owner completes is checked at issuance.
GRANT_COLLECTIONS: frozenset[str] = frozenset(
    {GRANT_COLLECTION, JTI_COLLECTION, REFRESH_COLLECTION, CODE_COLLECTION}
)

#: What an `auth.mcp_grant_revoked` row's `ended_by` says when the rebind, not a
#: client at `/mcp/revoke` or the provider's refresh response, ended the grant.
ENDED_BY_REBIND = "rebind"

# --- the grant lock -----------------------------------------------------------------------

#: Postgres advisory-lock namespace for the grant lock — the two-int4 form,
#: which cannot collide with the write gate's single int8 key; spells "moa",
#: so it is recognisable in `pg_locks`.
GRANT_LOCK_NAMESPACE = 0x6D6F61


def lock_key(handle: str) -> int:
    """A grant handle as the int4 half of an advisory-lock key. Derived here, not
    by `hashtext` in SQL: the handle can be a secret (an authorization code),
    and the engine's DEBUG log would otherwise print it as a bound parameter."""
    return int.from_bytes(hashlib.sha256(handle.encode()).digest()[:4], "big", signed=True)


# --- the store ----------------------------------------------------------------------------

#: Connections the state store may hold: the proxy touches it a handful of
#: times per request, on one owner's traffic.
STATE_STORE_POOL_SIZE = 2
#: HKDF salt for the storage key — distinct from anything FastMCP derives from
#: the same material, so the signing key and the encryption key differ.
STORAGE_KEY_SALT = b"plamotrack-mcp-oauth-state"


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
    """The store and its encrypting wrapper for `settings`: the proxy's, and the
    rebind's when it reads the grant records it is about to purge."""
    store = OAuthStateStore(
        url=asyncpg_dsn(settings.database_url), table_name=MCP_OAUTH_STATE_TABLE
    )
    wrapped = FernetEncryptionWrapper(
        key_value=store,
        fernet=Fernet(storage_key(settings.mcp_oauth_signing_key_bytes)),
        raise_on_decryption_error=False,
    )
    return store, wrapped
