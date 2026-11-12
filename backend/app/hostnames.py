"""Host-name normalisation and the allowlist-entry grammar, shared by the
settings validators (`app/config.py`) and the ingress policy (`app/ingress.py`).

One module because the PR #196 review found the two disagreeing: the validator
judged the *raw* entry while the guard matched the *normalised* one, so
`ALLOWED_HOSTS=*:8080` passed validation, lost its port on the way to matching
and became `*`. Everything that produces a host for the allowlist —
`ALLOWED_HOSTS`, `PUBLIC_BASE_URL`, `WEB_BIND`, `ALLOWED_ORIGINS` — is validated
here on the same normalised form the guard compares.

`normalize_host` mirrors FastMCP 3.4.5's `_normalize_host` (lowercase, brackets
and port removed) with one deliberate addition: terminal DNS dots are dropped,
because nginx drops them from the request Host before matching and a name
configured as `nas.lan.` must mean `nas.lan` at both layers. FastMCP's guard is
handed the dotted spellings as well (`IngressPolicy.mcp_allowed_hosts`), so the
two guards still agree on every request.
"""

from __future__ import annotations

import re
from ipaddress import ip_address

#: The names every install answers to. A literal, equal by test to FastMCP's
#: `DEFAULT_HOSTS`, so the two guards' built-ins cannot drift apart unnoticed.
LOOPBACK_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")

# A DNS name: labels of letters, digits, hyphens (underscores tolerated —
# container names carry them), optionally led by the one wildcard form `*.`.
_LABEL = r"[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?"
_HOSTNAME_RE = re.compile(rf"^(?:\*\.)?{_LABEL}(?:\.{_LABEL})*$")


def normalize_host(host: str) -> str:
    """A Host header, or an allowlist entry, reduced to its comparable form:
    lowercase, brackets and port removed, terminal dots removed. `[::1]:8080` →
    `::1`; `NAS.lan:80` → `nas.lan`; `nas.lan.` → `nas.lan`; a bare IPv6 literal
    with several colons is left whole."""
    host = host.strip().lower()
    if not host:
        return ""
    if host.startswith("["):
        end = host.find("]")
        host = host if end == -1 else host[1:end]
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    # One terminal dot is the DNS root and names the same host; two is not a name.
    return host.removesuffix(".")


def is_ip_literal(host: str) -> bool:
    try:
        ip_address(normalize_host(host))
    except ValueError:
        return False
    return True


def is_loopback_host(host: str) -> bool:
    host = normalize_host(host)
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def is_unspecified_host(host: str) -> bool:
    """`0.0.0.0`, `::` and the empty string — a bind address that names nothing."""
    host = normalize_host(host)
    if not host:
        return True
    try:
        return ip_address(host).is_unspecified
    except ValueError:
        return False


def validate_host_pattern(entry: str, *, setting: str, allow_wildcard: bool) -> str:
    """The normalised form of one configured host, or a `ValueError` naming the
    setting. Accepted: an IP address that names something, or a DNS name;
    with `allow_wildcard`, also the one wildcard form `*.domain`. Refused: a
    bare or port-qualified `*`, `**`, `[*]`, a wildcard anywhere but the leading
    label, a leading dot, empty labels — anything whose normalised form would
    admit more than the operator wrote."""
    normalized = normalize_host(entry)
    if not normalized:
        raise ValueError(f"{setting} entry {entry!r} names no host")
    if is_ip_literal(normalized):
        if ip_address(normalized).is_unspecified:
            raise ValueError(f"{setting} entry {entry!r} is an unspecified address, not a name")
        return normalized
    if not _HOSTNAME_RE.fullmatch(normalized):
        raise ValueError(
            f"{setting} entry {entry!r} is not a host name, an IP address or a "
            "*.domain wildcard (a bare '*', a port-qualified '*', or a wildcard "
            "anywhere but the leading label would admit every host)"
        )
    if normalized.startswith("*.") and not allow_wildcard:
        raise ValueError(f"{setting} entry {entry!r} may not be a wildcard")
    return normalized
