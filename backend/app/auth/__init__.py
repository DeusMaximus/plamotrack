"""Authentication and authorization foundation (Milestone 6, §5.5–§5.6).

The pieces the rest of M6 attaches to, kept in one package so the principal
model, the scopes, and the route policy registry are declared once and read
everywhere:

- `principal` — the resolved caller: `anon`, `owner`, `pat`, `mcp`, `internal`,
  and the three scopes with `write` implying `read` (§5.5).
- `registry` — the route policy registry (§5.5, "declared once, enumerated by
  test"): for every effective REST route and every MCP tool, the family, the
  credential policy the dependency enforces, the declared methods, the permitted
  external spellings, and the response profile. The dependency, the ingress
  template's rejection list and the T1/T2 matrix all read it; the enumeration
  test fails on anything undeclared.

M6-2 (#187) builds the model and the registry; the credential *mechanisms*
that turn a request into a non-anonymous principal arrive with local auth
(#188), personal access tokens (#189) and OAuth (#192). The registry carries
declarations for those families now so the dependency and the tests have one
source to read as each mechanism lands.
"""

from app.auth.principal import (
    Principal,
    PrincipalKind,
    Scope,
    anonymous,
    internal,
    mcp,
    owner,
    pat,
)

__all__ = [
    "Principal",
    "PrincipalKind",
    "Scope",
    "anonymous",
    "internal",
    "mcp",
    "owner",
    "pat",
]
