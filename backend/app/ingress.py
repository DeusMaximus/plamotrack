"""Ingress identity: the Host/Origin guard, the forwarded-client resolver and the
`internal` peer test (design notes §5.5–§5.6; M6-1, #186, absorbing #39).

The app's own identity — which names it answers to, which browser origins may
write to it — comes from configuration (`PUBLIC_BASE_URL`, `ALLOWED_HOSTS`,
`ALLOWED_ORIGINS`) and never from a request header. Three things live here:

- `IngressPolicy`: the lists, derived once from `Settings`. The same lists are
  handed to FastMCP's own guard (`host_origin_protection=True`) on the `/mcp`
  mount, so REST and MCP apply one rule from one source.
- `HostOriginGuardMiddleware`: every request's `Host` must be on the allowlist
  (421 otherwise, the body naming the setting); every *unsafe* request's
  `Origin` — `Referer` as the fallback — must satisfy the three-way rule FastMCP's
  guard applies: listed, loopback-to-loopback, or equal to the request's own
  origin (403 otherwise). A request with neither header passes in this release:
  no cookie exists yet, so a missing `Origin` cannot be a cookie-borne
  cross-site request, and refusing it would refuse every script and MCP client
  for no gain (a browser cannot omit `Origin` on a cross-origin unsafe request
  — the worst it sends is `null`, which matches nothing). The session cookie
  (M6-3) is what tightens that case, per §5.6's CSRF row.
- `ForwardedClientMiddleware`: resolves the client address from
  `X-Forwarded-For` only when the raw TCP peer is in `TRUSTED_PROXIES`, into
  `scope["state"]["client_address"]`, and leaves `scope["client"]` alone. That
  is why uvicorn runs with `--no-proxy-headers`: its own middleware would
  overwrite the raw peer, and the raw peer is what `is_internal_peer` — the
  `/readyz` gate — reads.

The helpers mirror FastMCP 3.4.5's `server/http.py` normalisation on purpose
rather than importing its private functions: the parity that matters is
observable (one matrix in `tests/test_ingress.py` drives both guards), and a
library refactor must not silently change what REST accepts.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import error_codes
from app.config import Settings, split_csv

#: The names every install answers to. A literal, equal by test to FastMCP's
#: `DEFAULT_HOSTS`, so the two guards' built-ins cannot drift apart unnoticed.
LOOPBACK_HOSTS: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")

#: Methods the Origin rule does not apply to. A cross-site GET without CORS
#: headers is unreadable by the page that sent it, so there is nothing to deny.
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

HOST_SETTING = "ALLOWED_HOSTS"
ORIGIN_SETTING = "ALLOWED_ORIGINS"

#: Where the resolved client address lands. `request.state.client_address` is
#: what rate limiting and audit (later M6 items) read; `request.client` stays
#: the socket's peer.
CLIENT_ADDRESS_KEY = "client_address"


# --- normalisation ---------------------------------------------------------------


def normalize_host(host: str) -> str:
    """A Host header, or an allowlist entry, reduced to its comparable form:
    lowercase, brackets and port removed. `[::1]:8080` → `::1`; `NAS.lan:80` →
    `nas.lan`; a bare IPv6 literal with several colons is left whole."""
    host = host.strip().lower()
    if not host:
        return ""
    if host.startswith("["):
        end = host.find("]")
        return host if end == -1 else host[1:end]
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


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


def host_matches(host: str, patterns: tuple[str, ...]) -> bool:
    host = normalize_host(host)
    if not host:
        return False
    return any(fnmatchcase(host, normalize_host(pattern)) for pattern in patterns)


def _format_origin_host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def normalize_origin(origin: str) -> str:
    """An origin in comparable form: lowercase scheme and host, the port made
    explicit (`http://Localhost` → `http://localhost:80`). Anything that is not
    a bare origin — a path, a query, `null`, garbage — comes back lowercased and
    unchanged, so it can only ever equal itself."""
    origin = origin.strip().rstrip("/")
    try:
        parsed = urlsplit(origin)
        port = parsed.port
    except ValueError:
        return origin.lower()
    if not parsed.scheme or not parsed.hostname:
        return origin.lower()
    if parsed.path or parsed.query or parsed.fragment:
        return origin.lower()
    scheme = parsed.scheme.lower()
    host = _format_origin_host(normalize_host(parsed.hostname))
    if port is None:
        port = {"http": 80, "https": 443}.get(scheme)
    return f"{scheme}://{host}" if port is None else f"{scheme}://{host}:{port}"


def origin_host(origin: str) -> str:
    try:
        return urlsplit(origin).hostname or ""
    except ValueError:
        return ""


def origin_of_referer(referer: str) -> str:
    """The origin a Referer URL names, or "" when it names none — a Referer
    that is not a URL is treated as an origin that matches nothing."""
    try:
        parsed = urlsplit(referer.strip())
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _parse_address(value: str) -> str:
    """One X-Forwarded-For entry or a socket peer, with any port removed."""
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


# --- the policy ------------------------------------------------------------------


@dataclass(frozen=True)
class IngressPolicy:
    """The allowlists, derived once from settings and shared by both guards."""

    #: Host names on top of the loopback names: PUBLIC_BASE_URL's host, a
    #: non-unspecified WEB_BIND, and ALLOWED_HOSTS. This is exactly what
    #: FastMCP's guard receives as `allowed_hosts` (it adds the loopback names
    #: and the socket's bound address itself, as `allowed_hosts_for` does here).
    extra_hosts: tuple[str, ...]
    #: PUBLIC_BASE_URL's origin plus ALLOWED_ORIGINS — FastMCP's `allowed_origins`.
    allowed_origins: tuple[str, ...]
    trusted_proxies: tuple[IPv4Network | IPv6Network, ...]
    #: The instance's own origin, normalised, or None for the loopback install.
    canonical_origin: str | None

    @classmethod
    def from_settings(cls, settings: Settings) -> IngressPolicy:
        extra_hosts: list[str] = []
        canonical_origin: str | None = None
        if settings.public_base_url:
            parsed = urlsplit(settings.public_base_url)
            extra_hosts.append(parsed.hostname or "")
            canonical_origin = normalize_origin(settings.public_base_url)
        if not is_unspecified_host(settings.web_bind) and not is_loopback_host(settings.web_bind):
            extra_hosts.append(settings.web_bind)
        extra_hosts.extend(split_csv(settings.allowed_hosts))

        allowed_origins: list[str] = []
        if canonical_origin is not None:
            allowed_origins.append(canonical_origin)
        allowed_origins.extend(split_csv(settings.allowed_origins))

        trusted = tuple(
            ip_network(entry, strict=False) for entry in split_csv(settings.trusted_proxies)
        )
        return cls(
            extra_hosts=tuple(dict.fromkeys(extra_hosts)),
            allowed_origins=tuple(dict.fromkeys(allowed_origins)),
            trusted_proxies=trusted,
            canonical_origin=canonical_origin,
        )

    def allowed_hosts_for(self, server_host: str | None) -> tuple[str, ...]:
        """The complete Host allowlist for one request: the loopback names, the
        configured extras, and the address the socket is bound to when it names
        something (`0.0.0.0` inside the container names nothing)."""
        hosts = [*LOOPBACK_HOSTS, *self.extra_hosts]
        if server_host and not is_unspecified_host(server_host):
            hosts.append(server_host)
        return tuple(hosts)

    def host_allowed(self, host: str, server_host: str | None = None) -> bool:
        return host_matches(host, self.allowed_hosts_for(server_host))

    def origin_allowed(self, origin: str, scheme: str, host: str) -> bool:
        """The three-way rule: listed; loopback origin against a loopback host;
        or equal to the request's own origin (the socket's scheme and the Host).
        `null` and anything unparsable fail all three."""
        normalized = normalize_origin(origin)
        if any(fnmatchcase(normalized, normalize_origin(p)) for p in self.allowed_origins):
            return True
        if is_loopback_host(origin_host(origin)) and is_loopback_host(host):
            return True
        return normalized == normalize_origin(f"{scheme}://{host}")

    def is_trusted_proxy(self, address: str | None) -> bool:
        if not address:
            return False
        try:
            ip = ip_address(_parse_address(address))
        except ValueError:
            return False
        return any(ip in network for network in self.trusted_proxies)

    def resolve_client_address(self, peer: str | None, forwarded_for: str) -> str | None:
        """The client behind a chain of trusted proxies: walk X-Forwarded-For
        from the right, past every trusted hop, and stop at the first address
        that is not one. An untrusted peer's header is not consulted at all."""
        if not self.is_trusted_proxy(peer):
            return peer
        chain = [entry.strip() for entry in forwarded_for.split(",") if entry.strip()]
        resolved = peer
        for hop in reversed(chain):
            resolved = _parse_address(hop)
            if not self.is_trusted_proxy(hop):
                break
        return resolved


# --- the peer ----------------------------------------------------------------------


def is_internal_peer(scope: Scope) -> bool:
    """§5.5's `internal` principal: the socket's own peer is loopback. Read from
    `scope["client"]`, which nothing rewrites — uvicorn's proxy-header
    middleware is off and `ForwardedClientMiddleware` writes elsewhere."""
    client = scope.get("client")
    if not client:
        return False
    try:
        return ip_address(client[0]).is_loopback
    except ValueError:
        return False


# --- the middlewares ----------------------------------------------------------------


def _refusal(status: int, detail: str, code: str, setting: str) -> JSONResponse:
    # The #25 envelope, built here because the guard answers before routing and
    # so before any exception handler.
    return JSONResponse(
        status_code=status,
        content={"detail": detail, "code": code, "params": {"setting": setting}},
    )


class HostOriginGuardMiddleware:
    """421 for a Host outside the allowlist; 403 for an unsafe request whose
    Origin (or Referer) fails the three-way rule. Pure ASGI, outermost."""

    def __init__(self, app: ASGIApp, policy: IngressPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = headers.get("host", "")
        server = scope.get("server")
        if not self.policy.host_allowed(host, server[0] if server else None):
            response = _refusal(
                421,
                "This instance does not answer to that host name. Add the name you use "
                f"to {HOST_SETTING} in .env, then run `docker compose up -d`.",
                error_codes.INGRESS_HOST_NOT_ALLOWED,
                HOST_SETTING,
            )
            await response(scope, receive, send)
            return

        if scope["type"] == "http" and scope.get("method", "GET") not in SAFE_METHODS:
            origin = headers.get("origin")
            if origin is None:
                referer = headers.get("referer")
                if referer is not None:
                    origin = origin_of_referer(referer)
            if origin is not None and not self.policy.origin_allowed(
                origin, scope.get("scheme", "http"), host
            ):
                response = _refusal(
                    403,
                    "This instance does not accept writes from that origin. An origin of "
                    f"your own goes in {ORIGIN_SETTING} in .env.",
                    error_codes.INGRESS_ORIGIN_NOT_ALLOWED,
                    ORIGIN_SETTING,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


class ForwardedClientMiddleware:
    """Records the client address behind `TRUSTED_PROXIES` in
    `scope["state"]["client_address"]` and touches nothing else."""

    def __init__(self, app: ASGIApp, policy: IngressPolicy) -> None:
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            client = scope.get("client")
            peer = client[0] if client else None
            forwarded = ", ".join(
                value.decode("latin1")
                for name, value in scope.get("headers", [])
                if name == b"x-forwarded-for"
            )
            scope.setdefault("state", {})[CLIENT_ADDRESS_KEY] = self.policy.resolve_client_address(
                peer, forwarded
            )
        await self.app(scope, receive, send)
