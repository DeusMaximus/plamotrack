"""Local credential primitives (§5.6, credential leakage and brute force; M6-3, #188).

Three kinds of secret, one rule each:

- **The owner's password** is stored as an Argon2id encoded string
  (`credential.secret_hash`; the encoding carries its own salt and parameters,
  so a parameter bump is a re-hash on the next successful login). Verification
  against a **dummy hash** when no credential row exists — an unclaimed instance
  — costs the same work and fails the same way as a wrong password, so the two
  failure kinds are indistinguishable from outside (§5.8 T11).
- **Opaque tokens** — the session id and the setup token — are
  `secrets.token_urlsafe` values shown or set once and stored only as SHA-256
  digests, compared with `hmac.compare_digest`. A database read cannot
  reconstruct a live session (§5.6, session theft).
- **The CSRF token** is HMAC-SHA256 keyed by the raw session token. It is bound
  to the session, needs no column and no server secret, and only a holder of the
  cookie value can compute it — which a cross-site page cannot, the cookie being
  `HttpOnly` and the token being handed out only by `GET /auth/session` to a
  same-origin fetch (§5.6, CSRF control 3).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: The algorithm label stored beside the verifier (`credential.algorithm`), for a
#: future rotation to recognise.
ALGORITHM = "argon2id"

#: The floor on a new password. Length is the one rule: a single owner picks one
#: passphrase for their own instance, and composition rules buy nothing Argon2id
#: and the failure budget do not already (NIST SP 800-63B). The ceiling bounds the
#: hashing work an unauthenticated request can demand.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024

#: Bytes of entropy behind a session id and a setup token (`token_urlsafe` renders
#: them as ~43 characters). 32 bytes = 256 bits: unguessable by construction.
TOKEN_BYTES = 32

_hasher = PasswordHasher()  # argon2-cffi's defaults: Argon2id, 64 MiB, t=3, p=4

#: A real Argon2id verifier for a secret nobody holds. Verifying a presented
#: password against it does the full Argon2 work and always fails — the shape an
#: unclaimed instance answers a login attempt with (T11).
DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(TOKEN_BYTES))


def hash_password(password: str) -> str:
    """The Argon2id encoded string to store for `password`."""
    return _hasher.hash(password)


def verify_password(encoded: str | None, password: str) -> bool:
    """Whether `password` matches the stored verifier. `None` — no credential row
    — verifies against `DUMMY_HASH`, so the work and the answer are the same as
    for a wrong password."""
    try:
        return _hasher.verify(encoded if encoded is not None else DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(encoded: str) -> bool:
    """True when the stored verifier was made with weaker parameters than the
    current ones — re-hash on the next successful login."""
    return _hasher.check_needs_rehash(encoded)


def new_token() -> str:
    """An opaque secret: a session id or a setup token. Shown or set once."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def digest(token: str) -> str:
    """What the database holds for an opaque token: its SHA-256, hex."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(presented: str, expected_digest: str) -> bool:
    """Constant-time comparison of a presented opaque token against its stored
    digest — the compare is on the digests, both fixed-length."""
    return hmac.compare_digest(digest(presented), expected_digest)


def csrf_token_for(raw_session_token: str) -> str:
    """The CSRF token bound to one session: HMAC-SHA256 keyed by the raw session
    token, hex. Deterministic per session, so `GET /auth/session` and the check
    on every cookie-borne unsafe request agree without a stored column."""
    return hmac.new(
        raw_session_token.encode("utf-8"), b"plamotrack csrf token", hashlib.sha256
    ).hexdigest()


def csrf_tokens_match(presented: str | None, raw_session_token: str) -> bool:
    if presented is None:
        return False
    return hmac.compare_digest(presented, csrf_token_for(raw_session_token))
