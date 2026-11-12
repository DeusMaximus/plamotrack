"""Personal access tokens — the primitives (§5.5 `pat:read`/`pat:write`, §5.6
credential leakage; M6-4, #189).

The credential scripts and local MCP clients use: the owner's own, valid on REST
and on `/mcp` alike, never holding `instance:admin`. The shape on the wire is

    ptk_<public id>_<secret>

`ptk_` names the kind (a leaked string is recognisable in a log or a scanner's
output); the public id — twelve hex characters — is what the database is looked
up by (`personal_access_token.token_prefix`, unique); the secret is 32 bytes of
`token_urlsafe`. The database holds only the SHA-256 of the **whole** token
(`secret_hash`), so a read of the table reconstructs nothing, and a presented
token is compared with `hmac.compare_digest` against the stored digest — or
against `DUMMY_DIGEST` when the public id names no row, so an unknown id and a
wrong secret do the same work and answer the same way (§5.8 T11).

Where the token travels: the `Authorization: Bearer` header and nowhere else. A
query parameter lands in access logs and `Referer` (§5.6), so nothing here reads
one; `bearer_from_headers` is the single parser both REST and MCP use.

What this module does **not** do: touch the database. Minting, listing, revoking
and resolving a presented token are `services/tokens.py`, so the REST resolver,
the MCP verifier and the tests all reach one implementation (rule 1).
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping

from app.auth import credentials
from app.auth.principal import Scope

#: The kind marker every token starts with.
TOKEN_KIND = "ptk"
#: Bytes behind the public id (twelve hex characters — 48 bits: unique by
#: construction across one instance's tokens, and the unique index says so).
PUBLIC_ID_BYTES = 6
#: Bytes behind the secret: 32 = 256 bits, the same floor as a session id.
SECRET_BYTES = credentials.TOKEN_BYTES

#: `ptk_<12 hex>_<url-safe secret>`. The id is hex so the second underscore is
#: unambiguous — `token_urlsafe` output may itself contain underscores.
_TOKEN_SHAPE = re.compile(r"^ptk_([0-9a-f]{12})_([A-Za-z0-9_-]{16,})$")

#: The digest of a token nobody holds, compared against when the public id
#: names no row — the `DUMMY_HASH` shape (T11).
DUMMY_DIGEST = credentials.digest(f"ptk_{'0' * 12}_{secrets.token_urlsafe(SECRET_BYTES)}")

#: The scopes a token may hold. Never `instance:admin` (§5.5): everything admin
#: is a person acting in Settings, and a leaked bearer must not be able to erase
#: or reconfigure the instance.
GRANTABLE_SCOPES: frozenset[Scope] = frozenset({Scope.READ, Scope.WRITE})

#: The separator the `scopes` column uses (canonical identifiers, no spaces).
SCOPES_SEPARATOR = ","


def mint_raw() -> tuple[str, str]:
    """A fresh token: `(public_id, raw)`. Shown once; the caller stores
    `credentials.digest(raw)` beside the public id."""
    public_id = secrets.token_hex(PUBLIC_ID_BYTES)
    secret = secrets.token_urlsafe(SECRET_BYTES)
    return public_id, f"{TOKEN_KIND}_{public_id}_{secret}"


def public_id_of(raw: str) -> str | None:
    """The public id a presented token names, or None when the string is not
    shaped like a token at all (the malformed case — refused without a lookup)."""
    match = _TOKEN_SHAPE.match(raw)
    return match.group(1) if match else None


def encode_scopes(scopes: frozenset[Scope] | set[Scope]) -> str:
    """The column value for a granted set: canonical identifiers in `Scope`
    order. `write` implies `read`, so a write grant is stored with both — the
    column says what the token holds, not what was typed."""
    granted = set(scopes)
    if Scope.WRITE in granted:
        granted.add(Scope.READ)
    return SCOPES_SEPARATOR.join(s.value for s in Scope if s in granted)


def decode_scopes(column: str) -> frozenset[Scope]:
    """The granted set from the column. A value the enum does not know is a
    corrupt row and is refused (raises), never silently widened or narrowed."""
    return frozenset(Scope(part) for part in column.split(SCOPES_SEPARATOR) if part)


#: `bearer_from_headers` answers this for an `Authorization` header that is
#: present but is not `Bearer <token>` — a `Basic` credential, an empty bearer.
#: Presented and failed: 401, never `anon` (§5.5).
MALFORMED = object()


def bearer_from_headers(headers: Mapping[str, str]) -> str | object | None:
    """The bearer token an `Authorization` header carries: the token string; None
    when the header is absent (the only way to be `anon`); `MALFORMED` when a
    header is present that is not a non-empty `Bearer` credential. Case-
    insensitive on the scheme (RFC 7235 §2.1); nothing else is consulted — no
    query parameter, no cookie."""
    header = headers.get("authorization")
    if header is None:
        return None
    scheme, _, value = header.strip().partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value:
        return MALFORMED
    return value
