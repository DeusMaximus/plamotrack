"""The resolved caller — one `Principal` per request (§5.5).

Every request resolves to exactly one principal, and the app-level dependency
decides allow/deny from the principal's scopes against the route's declared
credential policy. The credential *mechanisms* that produce a non-anonymous
principal land later in M6 (session #188, personal token #189, OAuth #192); this
module is the shape they all resolve to, so the dependency and the scope helper
are written once against it.

The five kinds and their scopes are §5.5's principal table:

| kind       | how it arrives                            | scopes                        |
|------------|-------------------------------------------|-------------------------------|
| `anon`     | no credential                             | none                          |
| `owner`    | session cookie (+ CSRF on unsafe methods) | read, write, `instance:admin` |
| `pat`      | `Authorization: Bearer` access token      | read, or read+write           |
| `mcp`      | bearer from the MCP OAuth path (OIDC)     | read, or read+write; no admin |
| `internal` | raw TCP peer is loopback in the namespace | none — readiness only         |

Only an *absent* credential is `anon`; a credential that is presented and fails
— expired, revoked, malformed, wrong audience — is 401, never a silent
downgrade to `anon` (§5.5). That distinction lives in the resolver
(#188/#189/#192), not here; this module only names the results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Scope(StrEnum):
    """The three scopes. Canonical identifiers — they reach OAuth grants and
    token records on the wire, so renaming one is a breaking change (§5.5).

    `write` implies `read` (`Principal.has_scope`). `instance:admin` implies
    nothing automatically; the owner simply holds all three. No token tier holds
    admin in M6 — everything that needs it is a person acting in Settings (§5.5).
    """

    READ = "collection:read"
    WRITE = "collection:write"
    ADMIN = "instance:admin"


#: `Principal.via` values.
VIA_SESSION = "session"
VIA_BEARER = "bearer"


class PrincipalKind(StrEnum):
    ANON = "anon"
    OWNER = "owner"
    PAT = "pat"
    MCP = "mcp"
    INTERNAL = "internal"


@dataclass(frozen=True)
class Principal:
    """A resolved caller. Immutable: a request resolves it once and the
    dependency reads it; nothing mutates a principal in place.

    `subject` is the stable id of the credential behind the principal — the
    session id, the token id, the OAuth subject — carried for audit (#193) and
    left `None` for `anon` and `internal`, which have no credential.
    """

    kind: PrincipalKind
    scopes: frozenset[Scope] = field(default_factory=frozenset)
    subject: str | None = None
    #: How the credential arrived — `"session"` for the owner's cookie, `"bearer"`
    #: for a token in `Authorization` (#189), None for `anon`, `internal` and the
    #: pytest injection seam. The dependency reads it to decide whether the CSRF
    #: controls apply: a cookie-borne unsafe request owes the session-bound token
    #: and an Origin; a bearer-borne one owes neither (§5.6, CSRF).
    via: str | None = None

    @property
    def cookie_borne(self) -> bool:
        return self.via == VIA_SESSION

    def has_scope(self, scope: Scope) -> bool:
        """Whether this principal satisfies a required scope. The one implication
        is `write` ⇒ `read`: a write token can read. Admin is not an implication —
        the owner holds `read` and `write` explicitly, so an admin-only route is
        not silently readable by something that only happens to hold admin."""
        if scope in self.scopes:
            return True
        if scope is Scope.READ and Scope.WRITE in self.scopes:
            return True
        return False

    @property
    def label(self) -> str:
        """The name §5.5's matrix uses for this principal — `pat:read`,
        `pat:write`, `mcp`, `owner`, `anon`, `internal`. The bearer kinds split
        by whether they carry write, which is what the matrix rows vary."""
        if self.kind in (PrincipalKind.PAT, PrincipalKind.MCP):
            tier = "write" if Scope.WRITE in self.scopes else "read"
            return f"{self.kind.value}:{tier}"
        return self.kind.value


# --- factories -----------------------------------------------------------------
# Named constructors so callers (the resolver, the tests' injection seam) build a
# principal by intent rather than by assembling a scope set correctly each time.


def anonymous() -> Principal:
    """No credential. Allowed only on the anonymous families (SPA, `/auth/session`,
    the auth actions, liveness); 401 on every scoped route."""
    return Principal(kind=PrincipalKind.ANON)


def internal() -> Principal:
    """A request whose raw TCP peer is loopback in the API's own namespace: the
    container healthcheck, source-run development. Grants readiness and nothing
    else — it holds no collection scope, so it cannot read or write the
    collection (§5.5, family 10)."""
    return Principal(kind=PrincipalKind.INTERNAL)


def owner(subject: str | None = None, *, via: str | None = None) -> Principal:
    """The single owner's browser session. Holds every scope, `instance:admin`
    included — the only principal that does (§5.5). `via` is `VIA_SESSION` when
    a real cookie produced it (the resolver's call); the test seam leaves it None."""
    return Principal(
        kind=PrincipalKind.OWNER,
        scopes=frozenset({Scope.READ, Scope.WRITE, Scope.ADMIN}),
        subject=subject,
        via=via,
    )


def pat(*, write: bool, subject: str | None = None) -> Principal:
    """A personal access token — the owner's own credential for scripts and local
    MCP clients (#189). `read`, or `read`+`write`; never admin (§5.5)."""
    scopes = {Scope.READ, Scope.WRITE} if write else {Scope.READ}
    return Principal(kind=PrincipalKind.PAT, scopes=frozenset(scopes), subject=subject)


def mcp(*, write: bool, subject: str | None = None) -> Principal:
    """An MCP OAuth grant, audience-bound to `/mcp` (OIDC mode only, #192).
    `read`, or `read`+`write` if granted; never admin (§5.5)."""
    scopes = {Scope.READ, Scope.WRITE} if write else {Scope.READ}
    return Principal(kind=PrincipalKind.MCP, scopes=frozenset(scopes), subject=subject)
