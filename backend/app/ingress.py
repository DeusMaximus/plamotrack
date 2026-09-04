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
  origin (403 otherwise). A request with neither header passes this outer guard
  because scripts and MCP clients legitimately omit both; the authorization
  dependency separately refuses the missing-Origin case when a session cookie
  makes an unsafe request browser-borne (§5.6's CSRF row).
- `ForwardedClientMiddleware`: resolves the client address from
  `X-Forwarded-For` only when the raw TCP peer is in `TRUSTED_PROXIES`, into
  `scope["state"]["client_address"]`, and leaves `scope["client"]` alone. That
  is why uvicorn runs with `--no-proxy-headers`: its own middleware would
  overwrite the raw peer, and the raw peer is what `is_internal_peer` — the
  `/readyz` gate — reads. In the bundled stack nginx performs that trust walk,
  overwrites a private address header on every proxied path, and the unpublished
  API accepts that header only under its compose-only flag.

The helpers mirror FastMCP 3.4.5's `server/http.py` normalisation on purpose
rather than importing its private functions: the parity that matters is
observable (one matrix in `tests/test_ingress.py` drives both guards), and a
library refactor must not silently change what REST accepts.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from fnmatch import fnmatchcase
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import error_codes
from app.config import Settings, split_csv
from app.hostnames import (  # noqa: F401 — re-exported; the tests and main read them here
    LOOPBACK_HOSTS,
    is_ip_literal,
    is_loopback_host,
    is_unspecified_host,
    normalize_host,
)

_LOOPBACK_NORMALIZED = frozenset(normalize_host(h) for h in LOOPBACK_HOSTS)

#: Methods the Origin rule does not apply to. A cross-site GET without CORS
#: headers is unreadable by the page that sent it, so there is nothing to deny.
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

HOST_SETTING = "ALLOWED_HOSTS"
ORIGIN_SETTING = "ALLOWED_ORIGINS"

#: Where the resolved client address lands. `request.state.client_address` is
#: what audit reads; `request.client` stays
#: the socket's peer.
CLIENT_ADDRESS_KEY = "client_address"
BUNDLED_CLIENT_HEADER = "x-plamotrack-client-address"
_CURRENT_CLIENT_ADDRESS: ContextVar[str | None] = ContextVar(
    "plamotrack_current_client_address", default=None
)

IngressRejectionRecorder = Callable[[str, Scope, str], Awaitable[None]]

log = logging.getLogger("plamotrack.audit")


# --- normalisation (the host helpers live in app/hostnames.py) --------------------


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

    #: Host names on top of the loopback names, normalised: PUBLIC_BASE_URL's
    #: host, every explicit WEB_BIND that names something and is not already a
    #: built-in (`127.0.0.2` counts — PR #196 review, P3-2), and ALLOWED_HOSTS.
    #: `mcp_allowed_hosts` is what FastMCP's guard receives (it adds the loopback
    #: names and the socket's local address itself, as `allowed_hosts_for` does).
    extra_hosts: tuple[str, ...]
    #: PUBLIC_BASE_URL's origin plus ALLOWED_ORIGINS — FastMCP's `allowed_origins`.
    allowed_origins: tuple[str, ...]
    trusted_proxies: tuple[IPv4Network | IPv6Network, ...]
    #: Compose-only trust in the internal header the bundled nginx overwrites.
    bundled_ingress: bool
    #: The instance's own origin, normalised, or None for the loopback install.
    canonical_origin: str | None

    @classmethod
    def from_settings(cls, settings: Settings) -> IngressPolicy:
        extra_hosts: list[str] = []
        canonical_origin: str | None = None
        if settings.public_base_url:
            parsed = urlsplit(settings.public_base_url)
            extra_hosts.append(normalize_host(parsed.hostname or ""))
            canonical_origin = normalize_origin(settings.public_base_url)
        bind = normalize_host(settings.web_bind)
        if not is_unspecified_host(bind) and bind not in _LOOPBACK_NORMALIZED:
            extra_hosts.append(bind)
        extra_hosts.extend(normalize_host(entry) for entry in split_csv(settings.allowed_hosts))
        extra_hosts = [host for host in extra_hosts if host and host not in _LOOPBACK_NORMALIZED]

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
            bundled_ingress=settings.plamotrack_bundled_ingress,
            canonical_origin=canonical_origin,
        )

    @property
    def mcp_allowed_hosts(self) -> tuple[str, ...]:
        """What FastMCP's guard is handed. Its normaliser keeps a terminal DNS
        dot where ours drops it, so each DNS name is listed dotted as well —
        `localhost` included — and the two guards agree on `Host: nas.lan.`
        (PR #196 review, P3-3). IP literals take no dot."""
        names = [*self.extra_hosts]
        for host in ("localhost", *self.extra_hosts):
            if not is_ip_literal(host):
                names.append(f"{host}.")
        return tuple(dict.fromkeys(names))

    def allowed_hosts_for(self, server_host: str | None) -> tuple[str, ...]:
        """The complete Host allowlist for one request: the loopback names, the
        configured extras, and the socket's local address when it names something
        — the same rule FastMCP's guard applies. uvicorn reports the accepted
        connection's concrete local address there, not the bind literal: source-run
        that is `127.0.0.1`; in the container it is the api container's compose-
        network address, reachable only from that network (PR #196 review)."""
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


def client_address_from_scope(scope: Scope, policy: IngressPolicy) -> str | None:
    """The audit/rate-limit address for a scope, including pre-routing refusals.

    ``ForwardedClientMiddleware`` normally writes the resolved value into state,
    but the Host/Origin guard is intentionally outside it. Re-applying the same
    pure policy here lets those early refusals carry the same address without
    changing middleware order or trusting a new header.
    """
    client = scope.get("client")
    peer = client[0] if client else None
    headers = Headers(scope=scope)
    if policy.bundled_ingress:
        bundled = headers.get(BUNDLED_CLIENT_HEADER)
        if bundled:
            candidate = _parse_address(bundled)
            try:
                return str(ip_address(candidate))
            except ValueError:
                # The bundled proxy always emits an address. A malformed value
                # from a direct compose-network peer is not trusted as data.
                return peer
    forwarded = ", ".join(
        value.decode("latin1")
        for name, value in scope.get("headers", [])
        if name == b"x-forwarded-for"
    )
    return policy.resolve_client_address(peer, forwarded)


def current_client_address() -> str | None:
    """The resolved address for code reached without a Starlette ``Request``.

    FastMCP's token verifier is invoked by Starlette's authentication backend,
    before FastMCP installs its request context. The outer forwarded-client
    middleware therefore carries only this non-secret address through the
    current async context so MCP audit rows have the same source identity as
    REST rows.
    """
    return _CURRENT_CLIENT_ADDRESS.get()


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

    def __init__(
        self,
        app: ASGIApp,
        policy: IngressPolicy,
        rejection_recorder: IngressRejectionRecorder | None = None,
    ) -> None:
        self.app = app
        self.policy = policy
        self.rejection_recorder = rejection_recorder

    async def _record_rejection(self, event_type: str, scope: Scope, setting: str) -> None:
        if self.rejection_recorder is None:
            return
        try:
            await self.rejection_recorder(event_type, scope, setting)
        except Exception:
            # Audit storage must not turn a security refusal into an allow or a
            # different response. Keep the operational line free of request data.
            log.error("Could not persist %s", event_type)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        host = headers.get("host", "")
        server = scope.get("server")
        if not self.policy.host_allowed(host, server[0] if server else None):
            await self._record_rejection("ingress.host_rejected", scope, HOST_SETTING)
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
                await self._record_rejection("ingress.origin_rejected", scope, ORIGIN_SETTING)
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
        context_token: Token[str | None] | None = None
        if scope["type"] in ("http", "websocket"):
            address = client_address_from_scope(scope, self.policy)
            scope.setdefault("state", {})[CLIENT_ADDRESS_KEY] = address
            context_token = _CURRENT_CLIENT_ADDRESS.set(address)
        try:
            await self.app(scope, receive, send)
        finally:
            if context_token is not None:
                _CURRENT_CLIENT_ADDRESS.reset(context_token)
