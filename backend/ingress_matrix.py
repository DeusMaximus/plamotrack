"""T2 — the ingress matrix, run against the packaged stack (design notes §5.5,
§5.8; M6-1, #186).

    uv run python ingress_matrix.py [BASE_URL] [--allowed-host NAME]
                                    [--setup-token TOKEN] [--password PASSWORD]
                                    [--credential-file PATH] [--token-out PATH]
                                    [--log-secrets-out PATH] [--mode local|oidc]
                                    [--public-base-url URL] [--behind-proxy]
                                    [--hold-stream SECONDS] [--ca-cert PATH]

BASE_URL defaults to http://127.0.0.1:8080; an https BASE_URL is reached through
the system trust store (or `--ca-cert`'s bundle). `--allowed-host` names an entry the
stack's `.env` carries in ALLOWED_HOSTS, which enables T3's "a listed name" rows
at the ingress layer; CI sets `ci.plamotrack.test`.

Since the default-deny flip (M6-3, #188) the collection routes want a signed-in
owner, so the matrix signs in first when told how: `--setup-token` with
`--password` **claims** an unclaimed stack through `/api/auth/setup` — the token
is the one the API printed to its log, which is what CI reads out of
`docker compose logs api`, so the first-run path is exercised through the
packaged ingress; `--password` alone signs into a claimed instance through
`/api/auth/login`. The claim path signs out and performs a real password login
before continuing, so CI's log-hygiene control covers the full login flow rather
than treating setup as a substitute. Either way the positives then run cookie-borne, with the
`Origin` and `X-CSRF-Token` a cookie-borne write owes (§5.6), and the session
is signed out at the end. With neither flag the same rows expect the
dependency's 401 — still a positive control for the ingress (a spelling nginx
rejects never reaches the dependency), just not for the content behind it.

Signed in, the matrix also mints two personal access tokens (M6-4, #189) — the
MCP transport is bearer-only, so the `/mcp/` positives carry one — and proves
the token rows through nginx: a read token reads and cannot write, a write
token cannot manage tokens, a token in the query string is nothing, a wrong
secret and a revoked token are the `invalid_token` 401 on REST and MCP alike,
and an anonymous MCP initialize is the bare `Bearer` challenge. `--token-out
PATH` writes the write token there (mode 0600) and leaves it live for the next
step — CI's MCP `tools/list` probe with a real client; without it both tokens
are revoked at the end. The token is never printed, and a live token travels
only in headers: the query-string row uses a fake, because request URIs are
what access logs record (T10).

After sign-out, the matrix rapidly reads one safe endpoint in each bounded
family (2, 3, 8 and 9) and requires every nginx zone to answer 429. It does not
pin the exact admitted count because elapsed time may replenish a request.
`--log-secrets-out PATH` writes the run's password, PAT and session value (when
signed in), plus synthetic OAuth code/state/Referer probes, to a mode-0600 JSON
file for T10. The probes also drive a 429 so nginx's error logging is covered;
none of their values is printed. This option also works without a browser login
in the OIDC-mode run.

What it proves, per row: the status; that no response carries a `Location`
except nginx's own relative `/api` → `/api/` 301; that the security headers are
present on everything nginx serves; and that the one-spelling-per-family
rejections — the `/api/mcp`, `/api/.well-known`, `/api/openapi.json` and
`/api/readyz` namespaces in their literal, doubled-slash and percent-encoded
forms — are 404 while their canonical spellings and the positives beside them
(`/api/docs`, `/api/healthz`, the collection routes, `/mcp/`, `/openapi.json`)
answer. Paths are sent verbatim over `http.client`, because an HTTP library
that normalises `%6d` back to `m` would test the wrong spelling.

Family 8 (M6-7, #192) is the mode axis: `--mode local` (the default, what CI's
stack runs) expects the three root discovery documents and the six protocol
routes under `/mcp/` to answer their own 404 naming the mode, the slash-less
resource path to be nginx's 404 rather than its 301, an undeclared verb to be
the app's 405 with `Allow`, and no `Location` anywhere; `--mode oidc`, against a
stack configured with a provider, expects the documents to answer 200 with
their public caching and this instance's issuer, the protocol routes to be
FastMCP's, and the anonymous MCP challenge to carry the `resource_metadata`
pointer. The OIDC run is the release gate's, by hand (`.agents/testing-and-
review.md`); `--public-base-url` names the stack's `PUBLIC_BASE_URL` when it
differs from the address the matrix connects to.

T12 (#194) runs the same matrix through a TLS proxy in front of the stack.
`--behind-proxy` skips the three hostile-Host rows — a proxy answers a foreign
`Host` itself, so nginx's 421 is proven there with the real name before
`ALLOWED_HOSTS` lists it — and every other row is expected to relay unchanged.
`--credential-file` supplies an owner session the matrix cannot obtain itself
(an OIDC login), which makes the OIDC-mode run a signed-in one; that session is
used and never signed out. `--hold-stream SECONDS` opens a standalone MCP
stream on `/mcp/` and on bare `/mcp`, holds it with the client silent, ends the
session from another connection, and reports the longest gap between bytes
(the SDK pings every 15 s, so a longer gap means something buffered). Rows
whose expectation depends on the base name — a loopback `Origin` is allowed
against a loopback name only — read the name and expect accordingly, so the
CI run on 127.0.0.1 is unchanged.

Snapshots responses, never a route table (§5.5). Exit status is the number of
failing rows; every failure is printed with what was expected.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import pathlib
import secrets
import socket
import ssl
import sys
import time
from dataclasses import dataclass, field, replace
from ipaddress import ip_address
from urllib.parse import urlsplit

INITIALIZE = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "ingress_matrix", "version": "0"},
        },
    }
).encode()
INITIALIZED = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
#: The TLS context an https BASE_URL is reached through — the system trust
#: store, or the bundle `--ca-cert` names for a private CA. Module state so
#: `send()` keeps its signature; `main` replaces it before the first request.
TLS_CONTEXT: ssl.SSLContext = ssl.create_default_context()
#: The three T3 rows nginx answers from its default-deny server. A TLS proxy in
#: front of the stack answers a foreign `Host` itself — a name that matches no
#: site block never reaches nginx — so `--behind-proxy` skips exactly these.
HOSTILE_HOST_LABELS = (
    "hostile Host → nginx 421",
    "hostile Host on the API → nginx 421",
    "hostile Host on MCP → nginx 421",
)
JSON_404 = {"detail": "Not Found"}
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self):
        return json.loads(self.body)


@dataclass
class Credential:
    """The owner session the positives run under: the cookie the API set
    (whichever name the scheme selected) and the session-bound CSRF token."""

    cookie: str
    csrf_token: str

    def read(self) -> dict[str, str]:
        return {"Cookie": self.cookie}

    def write(self, origin: str | None) -> dict[str, str]:
        """A cookie-borne write owes an Origin and the CSRF token (§5.6); the
        Origin is the row's own concern, so None sends none."""
        headers = {"Cookie": self.cookie, "X-CSRF-Token": self.csrf_token}
        if origin is not None:
            headers["Origin"] = origin
        return headers


def write_private(path_value: str, content: str) -> pathlib.Path:
    """Restrict and write one opened file, refusing a symlink at the output path."""
    path = pathlib.Path(path_value)
    flags = os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(content)
    return path


@dataclass
class Row:
    label: str
    method: str
    path: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    #: None → no Location allowed; a string → exactly that Location.
    location: str | None = None
    #: JSON the body must equal, or a key the JSON body must carry.
    json_equals: object = None
    json_code: str | None = None
    content_type: str | None = None
    #: Security headers are asserted on everything nginx serves itself or
    #: proxies; the default-deny server's 421 is the one response without them.
    security_headers: bool = True
    csp_contains: str | None = "frame-ancestors 'none'"
    #: The `WWW-Authenticate` value a 401 must carry — exact, or a prefix when
    #: `www_authenticate_exact` is False (FastMCP appends an error description).
    www_authenticate: str | None = None
    www_authenticate_exact: bool = True
    #: Response headers that must carry exactly these values (lower-case names):
    #: the family-8 profile (`cache-control`) and the verb boundary (`allow`).
    expect_headers: dict[str, str] = field(default_factory=dict)
    #: Keys the JSON body must carry with these values — a discovery document's
    #: `issuer`, a resource document's `resource` — beside whatever else it holds.
    json_has: dict[str, object] | None = None


@dataclass
class Bearer:
    """A personal access token the matrix minted (#189): the raw value for the
    header and the id for the revoke."""

    raw: str
    token_id: str

    def header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.raw}"}


@dataclass
class Tokens:
    write: Bearer
    read: Bearer


def is_loopback_base(base: str) -> bool:
    """Whether BASE_URL names loopback — `localhost` or a loopback address — the
    reading the app's Origin rule makes of a request's Host (§5.6): the
    loopback-to-loopback allowance needs both sides."""
    host = urlsplit(base).hostname or ""
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def default_port(base: str) -> int:
    parts = urlsplit(base)
    return parts.port or (443 if parts.scheme == "https" else 80)


def send(base: str, row: Row, host_override: str | None = None) -> Response:
    parts = urlsplit(base)
    if parts.scheme == "https":
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            parts.hostname, default_port(base), timeout=30, context=TLS_CONTEXT
        )
    else:
        conn = http.client.HTTPConnection(parts.hostname, default_port(base), timeout=30)
    headers = dict(row.headers)
    if host_override is not None:
        headers["Host"] = host_override
    elif "Host" not in headers:
        headers["Host"] = parts.netloc
    try:
        conn.request(row.method, row.path, body=row.body, headers=headers)
        raw = conn.getresponse()
        body = raw.read()
        return Response(raw.status, {k.lower(): v for k, v in raw.getheaders()}, body)
    finally:
        conn.close()


def check(row: Row, resp: Response) -> list[str]:
    problems: list[str] = []
    if resp.status != row.status:
        problems.append(f"status {resp.status}, expected {row.status}")
    location = resp.headers.get("location")
    if row.location is None and location is not None:
        problems.append(f"unexpected Location: {location}")
    elif row.location is not None and location != row.location:
        problems.append(f"Location {location!r}, expected {row.location!r}")
    if row.content_type and not resp.headers.get("content-type", "").startswith(row.content_type):
        problems.append(f"content-type {resp.headers.get('content-type')!r}")
    if row.json_equals is not None or row.json_code is not None or row.json_has is not None:
        try:
            parsed = resp.json()
        except ValueError:
            problems.append(f"body is not JSON: {resp.body[:80]!r}")
            parsed = None
        if parsed is not None and row.json_equals is not None and parsed != row.json_equals:
            problems.append(f"body {parsed!r}, expected {row.json_equals!r}")
        if parsed is not None and row.json_code is not None and parsed.get("code") != row.json_code:
            problems.append(f"code {parsed.get('code')!r}, expected {row.json_code!r}")
        if parsed is not None and row.json_has is not None:
            for key, value in row.json_has.items():
                if not isinstance(parsed, dict) or parsed.get(key) != value:
                    got = parsed.get(key) if isinstance(parsed, dict) else parsed
                    problems.append(f"body[{key!r}] {got!r}, expected {value!r}")
    for name, value in row.expect_headers.items():
        if resp.headers.get(name) != value:
            problems.append(f"{name}: {resp.headers.get(name)!r}, expected {value!r}")
    if row.www_authenticate is not None:
        got = resp.headers.get("www-authenticate")
        matched = (
            got == row.www_authenticate
            if row.www_authenticate_exact
            else (got or "").startswith(row.www_authenticate)
        )
        if not matched:
            problems.append(f"www-authenticate {got!r}, expected {row.www_authenticate!r}")
    if row.security_headers:
        for name, value in SECURITY_HEADERS.items():
            if resp.headers.get(name) != value:
                problems.append(f"{name}: {resp.headers.get(name)!r}, expected {value!r}")
        csp = resp.headers.get("content-security-policy", "")
        if row.csp_contains and row.csp_contains not in csp:
            problems.append(f"CSP {csp!r} lacks {row.csp_contains!r}")
    return problems


def rejected(label: str, method: str, path: str, **kw) -> Row:
    return Row(label, method, path, 404, json_equals=JSON_404, **kw)


def unauthenticated(label: str, method: str, path: str, **kw) -> Row:
    """The dependency's refusal of an anonymous request to a guarded route —
    proof the spelling reached the app (nginx's rejections are 404, the ingress
    guard's are 403/421)."""
    return Row(
        label,
        method,
        path,
        401,
        json_code="auth.unauthenticated",
        content_type="application/json",
        **kw,
    )


def sign_in(base: str, *, setup_token: str | None, password: str) -> Credential:
    """Claim (setup token given) or log in, through the ingress, and keep the
    session the API set. Exits with the response when the stack refuses."""
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    if setup_token is not None:
        path, payload = "/api/auth/setup", {"token": setup_token, "password": password}
    else:
        path, payload = "/api/auth/login", {"password": password}
    row = Row(
        "sign in",
        "POST",
        path,
        200,
        headers={"Content-Type": "application/json", "Origin": origin},
        body=json.dumps(payload).encode(),
    )
    resp = send(base, row)
    if resp.status != 200:
        raise SystemExit(f"{path} answered {resp.status}: {resp.body[:200]!r}")
    set_cookie = resp.headers.get("set-cookie", "")
    cookie = set_cookie.split(";", 1)[0]
    if "=" not in cookie:
        raise SystemExit(f"{path} set no session cookie: {set_cookie!r}")
    return Credential(cookie=cookie, csrf_token=resp.json()["csrf_token"])


def mint_tokens(base: str, credential: Credential) -> Tokens:
    """Two tokens through the owner's session — cookie-borne writes, so with
    the Origin and CSRF token — one holding write, one read-only."""
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    minted: list[Bearer] = []
    for name, scopes in (
        ("ingress matrix (write)", ["collection:read", "collection:write"]),
        ("ingress matrix (read)", ["collection:read"]),
    ):
        row = Row(
            "mint token",
            "POST",
            "/api/auth/tokens",
            201,
            headers={**credential.write(origin), "Content-Type": "application/json"},
            body=json.dumps({"name": name, "scopes": scopes}).encode(),
        )
        resp = send(base, row)
        if resp.status != 201:
            raise SystemExit(f"/api/auth/tokens answered {resp.status}: {resp.body[:200]!r}")
        payload = resp.json()
        minted.append(Bearer(raw=payload["token"], token_id=payload["id"]))
    return Tokens(write=minted[0], read=minted[1])


def revoke_token(base: str, credential: Credential, bearer: Bearer) -> None:
    parts = urlsplit(base)
    row = Row(
        "revoke token",
        "DELETE",
        f"/api/auth/tokens/{bearer.token_id}",
        204,
        headers=credential.write(f"{parts.scheme}://{parts.netloc}"),
    )
    resp = send(base, row)
    if resp.status != 204:
        raise SystemExit(f"revoking a token answered {resp.status}: {resp.body[:200]!r}")


def sign_out(base: str, credential: Credential) -> None:
    parts = urlsplit(base)
    row = Row(
        "sign out",
        "POST",
        "/api/auth/logout",
        204,
        headers=credential.write(f"{parts.scheme}://{parts.netloc}"),
    )
    resp = send(base, row)
    if resp.status != 204:
        print(f"warning: sign-out answered {resp.status}", file=sys.stderr)


def _wrong_secret(bearer: Bearer) -> dict[str, str]:
    kind, public_id, _secret = bearer.raw.split("_", 2)
    return {"Authorization": f"Bearer {kind}_{public_id}_{'A' * 43}"}


def mcp_challenge(label: str, path: str, **kw) -> Row:
    """The transport's refusal of a request with no bearer: FastMCP's 401 with
    the bare `Bearer` challenge (RFC 6750 §3.1) and an empty body — proof the
    spelling reached the MCP app (nginx's rejections are 404, the ingress
    guard's are 403/421). In OIDC mode the challenge names the resource
    document (`family_8_rows` passes the exact value)."""
    return Row(
        label,
        "POST",
        path,
        401,
        body=INITIALIZE,
        **{"headers": MCP_HEADERS, "www_authenticate": "Bearer", **kw},
    )


#: The three root discovery documents and the six protocol routes (§5.5 family
#: 8; #192), as the registry declares them — `app/auth/registry.py`'s
#: `DISCOVERY_ROUTES` and `MCP_OAUTH_ROUTES` — typed here as literals, the way
#: every other row is: the matrix is the independent snapshot of the ingress
#: surface, not a reading of the registry.
DISCOVERY_DOCUMENTS = (
    "/.well-known/oauth-authorization-server/mcp",
    "/.well-known/openid-configuration/mcp",
    "/.well-known/oauth-protected-resource/mcp/",
)
PROTOCOL_ROUTES: dict[str, tuple[str, str]] = {
    # path: (a declared verb to send, the `Allow` set an undeclared verb earns)
    "/mcp/register": ("POST", "POST, OPTIONS"),
    "/mcp/authorize": ("GET", "GET, POST"),
    "/mcp/consent": ("GET", "GET, POST"),
    "/mcp/auth/callback": ("GET", "GET"),
    "/mcp/token": ("POST", "POST, OPTIONS"),
    "/mcp/revoke": ("POST", "POST, OPTIONS"),
}
NO_STORE = {"cache-control": "no-store"}
PUBLIC = {"cache-control": "public, max-age=3600"}


def family_8_rows(mode: str, public_base_url: str) -> list[Row]:
    """The family-8 surface through nginx, on the mode axis (T2, #192). Local
    mode: every path exists and answers its own 404 naming the mode. OIDC
    mode: the documents name this instance and the protocol routes are
    FastMCP's — driven here only as far as an anonymous caller with no
    transaction can go (a bare authorize is its 400, a bare token request its
    401, a bare registration its 400), each with the `no-store` profile. Both
    modes: no `Location` anywhere, the slash-less resource path is nginx's 404
    (its 301 suppressed), the bare OpenID document and the child aliases are
    404, and an undeclared verb is the app's 405 with `Allow` and the profile."""
    issuer = f"{public_base_url}/mcp"
    rows: list[Row] = []
    for path in DISCOVERY_DOCUMENTS:
        if mode == "oidc":
            has = (
                {"resource": issuer + "/", "authorization_servers": [issuer]}
                if path.endswith("/mcp/")
                else {"issuer": issuer, "authorization_endpoint": f"{issuer}/authorize"}
            )
            rows.append(
                Row(
                    f"discovery {path} → 200, public",
                    "GET",
                    path,
                    200,
                    content_type="application/json",
                    expect_headers=PUBLIC,
                    json_has=has,
                )
            )
        else:
            rows.append(
                Row(
                    f"discovery {path} in local mode → 404 naming the mode",
                    "GET",
                    path,
                    404,
                    json_code="auth.not_in_this_mode",
                    content_type="application/json",
                )
            )
    rows += [
        # nginx's own 404, not its 301 onto the slash form (§5.6: the /api
        # redirect is the one ingress-produced redirect).
        rejected(
            "slash-less resource path → nginx 404, not 301",
            "GET",
            "/.well-known/oauth-protected-resource/mcp",
        ),
        rejected("bare openid-configuration (pruned)", "GET", "/.well-known/openid-configuration"),
        rejected(
            "bare oauth-authorization-server (pruned)",
            "GET",
            "/.well-known/oauth-authorization-server",
        ),
        rejected("root .well-known unknown", "GET", "/.well-known/anything"),
        Row(
            "mcp/.well-known child alias (pruned) → 404",
            "GET",
            "/mcp/.well-known/oauth-authorization-server",
            404,
        ),
    ]
    for path, (verb, allow) in PROTOCOL_ROUTES.items():
        query = "?code=x&state=y" if path.endswith("callback") else ""
        if mode == "oidc":
            # token and revoke authenticate the client first (401 with no
            # client_id); the callback with no transaction is its 400.
            expected = {"/mcp/token": 401, "/mcp/revoke": 401, "/mcp/auth/callback": 400}.get(
                path, 400
            )
            if path == "/mcp/consent":
                expected = 400
            rows.append(
                Row(
                    f"{path} bare {verb} in OIDC mode → {expected}, no-store, no Location",
                    verb,
                    path + query,
                    expected,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    body=b"",
                    expect_headers=NO_STORE,
                )
            )
        else:
            rows.append(
                Row(
                    f"{path} in local mode → 404 naming the mode, no Location",
                    verb,
                    path + query,
                    404,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    body=b"",
                    json_code="auth.not_in_this_mode",
                    content_type="application/json",
                    expect_headers=NO_STORE,
                )
            )
        rows.append(
            Row(
                f"{path} undeclared verb → 405 with Allow, no-store",
                "PUT" if "PUT" not in allow else "TRACE",
                path,
                405,
                expect_headers={**NO_STORE, "allow": allow},
            )
        )
    rows += [
        Row(
            "mcp/authorize/ trailing slash → 404, no Location",
            "GET",
            "/mcp/authorize/",
            404,
        ),
        Row(
            "mcp/auth/callback/ trailing slash with a code → 404, no Location",
            "GET",
            "/mcp/auth/callback/?code=x&state=y",
            404,
        ),
        Row(
            "mcp/token/ trailing slash → 404, no Location",
            "POST",
            "/mcp/token/",
            404,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=b"",
        ),
        # The transport's challenge: bare in local mode (no document to point
        # at); in OIDC mode it names the resource document, built from
        # PUBLIC_BASE_URL (§5.5 family 7; T5's pointer).
        mcp_challenge(
            f"mcp/ initialize anonymous → 401 with{'' if mode == 'oidc' else 'out'} the pointer",
            "/mcp/",
            www_authenticate=mcp_challenge_value(mode, public_base_url),
        ),
    ]
    if mode == "oidc":
        # A registration the SDK cannot read is RFC 7591's 400 with the
        # profile, never the child app's 500 without it (Codex #212 f4): an
        # empty JSON body, a body that is not JSON, and — the SDK's own
        # refusal — a JSON document that is not client metadata.
        for label, body in (
            ("empty JSON body", b""),
            ("body that is not JSON", b"not json"),
            ("empty object", b"{}"),
        ):
            rows.append(
                Row(
                    f"mcp/register {label} → 400 invalid_client_metadata, no-store",
                    "POST",
                    "/mcp/register",
                    400,
                    headers={"Content-Type": "application/json"},
                    body=body,
                    content_type="application/json",
                    json_has={"error": "invalid_client_metadata"},
                    expect_headers=NO_STORE,
                )
            )
    return rows


#: Requests fired at `/mcp/register` back to back to trip nginx's per-peer
#: limit (10 r/s, burst 20, nodelay): well over the burst, so some are refused
#: however fast the API answers the rest.
RATE_LIMIT_BURST = 60


#: The body budgets the registry declares (`AUTH_BODY_LIMIT`,
#: `PROTOCOL_BODY_LIMIT`; #221 item 1), typed here as literals the way the
#: matrix types its rows: an independent snapshot the packaged stack is held to.
AUTH_BODY_LIMIT = 32 * 1024
PROTOCOL_BODY_LIMIT = 16 * 1024


def _padded(core: bytes, size: int) -> bytes:
    return core + b" " * (size - len(core))


def body_budget_rows(mode: str, *, claimed: bool) -> list[Row]:
    """#221 item 1 at the ingress: a body one byte past a route's budget is 413
    in the envelope with `no-store` — nginx's `client_max_body_size` on the
    generated exact location answers it, and the app's gate and guards answer
    the same code behind it; a body of exactly the budget reaches the app,
    whose answer is the route's own: the mode's 404 for a route of the other
    mode, the registration handler's 400, a claimed instance's 410 at setup."""
    json_type = {"Content-Type": "application/json"}
    form_type = {"Content-Type": "application/x-www-form-urlencoded"}
    too_large = {
        "json_code": "ingress.body_too_large",
        "expect_headers": NO_STORE,
        "content_type": "application/json",
    }
    over_json = _padded(b'{"redirect_uris": []}', PROTOCOL_BODY_LIMIT + 1)
    over_form = _padded(b"a=b", PROTOCOL_BODY_LIMIT + 1)
    rows = [
        Row(
            "body budget: /api/auth/setup one byte over → 413",
            "POST",
            "/api/auth/setup",
            413,
            headers=json_type,
            body=_padded(b'{"token": "x", "password": "y"}', AUTH_BODY_LIMIT + 1),
            **too_large,
        ),
        Row(
            "body budget: /api/auth/login one byte over → 413",
            "POST",
            "/api/auth/login",
            413,
            headers=json_type,
            body=_padded(b'{"password": "y"}', AUTH_BODY_LIMIT + 1),
            **too_large,
        ),
        Row(
            "body budget: /mcp/register one byte over → 413",
            "POST",
            "/mcp/register",
            413,
            headers=json_type,
            body=over_json,
            **too_large,
        ),
        Row(
            "body budget: /mcp/token one byte over → 413",
            "POST",
            "/mcp/token",
            413,
            headers=form_type,
            body=over_form,
            **too_large,
        ),
        Row(
            "body budget: /mcp/consent one byte over → 413",
            "POST",
            "/mcp/consent",
            413,
            headers=form_type,
            body=over_form,
            **too_large,
        ),
    ]
    at_budget_json = _padded(b'{"redirect_uris": []}', PROTOCOL_BODY_LIMIT)
    at_budget_setup = _padded(b'{"token": "x", "password": "y"}', AUTH_BODY_LIMIT)
    if mode == "local":
        rows.append(
            Row(
                "body budget: /mcp/register at the budget reaches the app (the mode's 404)",
                "POST",
                "/mcp/register",
                404,
                headers=json_type,
                body=at_budget_json,
                json_code="auth.not_in_this_mode",
                expect_headers=NO_STORE,
            )
        )
        if claimed:
            rows.append(
                Row(
                    "body budget: /api/auth/setup at the budget reaches the app (410, claimed)",
                    "POST",
                    "/api/auth/setup",
                    410,
                    headers=json_type,
                    body=at_budget_setup,
                    json_code="auth.setup_claimed",
                    expect_headers=NO_STORE,
                )
            )
    else:
        rows.append(
            Row(
                "body budget: /mcp/register at the budget reaches the app (the handler's 400)",
                "POST",
                "/mcp/register",
                400,
                headers=json_type,
                body=at_budget_json,
                json_has={"error": "invalid_client_metadata"},
                expect_headers=NO_STORE,
            )
        )
        rows.append(
            Row(
                "body budget: /api/auth/setup at the budget reaches the app (the mode's 404)",
                "POST",
                "/api/auth/setup",
                404,
                headers=json_type,
                body=at_budget_setup,
                json_code="auth.not_in_this_mode",
                expect_headers=NO_STORE,
            )
        )
    return rows


#: Hostile-Origin writes fired at a collection route back to back (#210; #221
#: item 3): every one is the guard's 403, and the packaged run's audit rows for
#: them are bounded — CI counts the rows after the run.
ORIGIN_FLOOD = 30


def origin_flood_rows(base: str) -> list[tuple[Row, Response]]:
    """A flood of hostile-Origin writes is refused, every one, whether or not
    the refusal budget records it; the row count is CI's to check."""
    row = Row(
        f"hostile Origin ×{ORIGIN_FLOOD} on /api/retailers → 403 every time; rows bounded",
        "POST",
        "/api/retailers",
        403,
        headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        body=b'{"name": "flood"}',
        json_code="ingress.origin_not_allowed",
    )
    responses = [send(base, row) for _ in range(ORIGIN_FLOOD)]
    refused = [resp for resp in responses if resp.status != 403]
    if refused:
        return [(row, resp) for resp in refused]
    return [(row, responses[-1])]


def rate_limit_rows(base: str) -> list[tuple[Row, Response]]:
    """nginx's `limit_req` on the OAuth endpoints, in either mode: a burst at
    `/mcp/register` earns some 429s, and every one of them is the envelope with
    `Cache-Control: no-store` and the security headers — the ingress-generated
    family-8 failure keeps the declared profile (Codex #212 f4). Run **last**:
    the peer is rate-limited for a moment afterwards."""
    burst = Row(
        "mcp/register burst → some 429s, each no-store in the envelope",
        "POST",
        "/mcp/register",
        429,
        headers={"Content-Type": "application/json"},
        body=b"{}",
        content_type="application/json",
        json_code="ingress.rate_limited",
        expect_headers={**NO_STORE, "retry-after": "1"},
    )
    refused = [
        resp for resp in (send(base, burst) for _ in range(RATE_LIMIT_BURST)) if resp.status == 429
    ]
    if not refused:
        return [(burst, Response(0, {}, b"the limiter never engaged across the burst"))]
    return [(burst, resp) for resp in refused]


def mcp_challenge_value(mode: str, public_base_url: str) -> str:
    """The `WWW-Authenticate` an anonymous MCP request earns: bare in local
    mode (no document to point at); in OIDC mode it names the resource
    document, built from PUBLIC_BASE_URL (§5.5 family 7; T5's pointer)."""
    if mode == "oidc":
        document = f"{public_base_url}/.well-known/oauth-protected-resource/mcp/"
        return f'Bearer resource_metadata="{document}"'
    return "Bearer"


def rows(
    allowed_host: str | None,
    credential: Credential | None = None,
    tokens: Tokens | None = None,
    *,
    challenge: str = "Bearer",
    behind_proxy: bool = False,
) -> list[Row]:
    owner = credential.read() if credential is not None else {}
    mcp_auth = tokens.write.header() if tokens is not None else {}
    hostile_host_rows = [
        Row(
            HOSTILE_HOST_LABELS[0],
            "GET",
            "/",
            421,
            headers={"Host": "evil.example"},
            json_code="ingress.host_not_allowed",
            security_headers=False,
        ),
        Row(
            HOSTILE_HOST_LABELS[1],
            "GET",
            "/api/healthz",
            421,
            headers={"Host": "evil.example"},
            json_code="ingress.host_not_allowed",
            security_headers=False,
        ),
        Row(
            HOSTILE_HOST_LABELS[2],
            "POST",
            "/mcp/",
            421,
            headers={**MCP_HEADERS, "Host": "evil.example"},
            json_code="ingress.host_not_allowed",
            security_headers=False,
        ),
    ]

    def guarded(label: str, path: str, *, content_type: str) -> Row:
        """A collection-read positive: 200 for the signed-in owner, else the
        dependency's 401 — either way the spelling reached the app."""
        if credential is None:
            return unauthenticated(f"{label} (anonymous)", "GET", path)
        return Row(label, "GET", path, 200, headers=owner, content_type=content_type)

    def family_13(label: str, method: str, path: str, status: int) -> Row:
        """Everything else under `/api/` (§5.5 family 13; #204): the app's
        pre-routing gate answers an anonymous caller 401 with the bare
        `Bearer` challenge before the router's own 404/405 — proof the spelling
        reached the app, and that the route table is not enumerable without a
        credential; the signed-in owner gets the router's plain answer."""
        if credential is None:
            return unauthenticated(f"{label} (anonymous)", method, path, www_authenticate="Bearer")
        return Row(label, method, path, status, headers=owner, content_type="application/json")

    matrix: list[Row] = [
        # --- one spelling per family: the rejections ------------------------------
        rejected("api/mcp literal", "GET", "/api/mcp"),
        rejected("api/mcp/ literal", "GET", "/api/mcp/"),
        rejected("api/mcp/ initialize", "POST", "/api/mcp/", headers=MCP_HEADERS, body=INITIALIZE),
        rejected("api//mcp/ doubled slash", "GET", "/api//mcp/"),
        rejected("//api/mcp/ doubled leading slash", "GET", "//api/mcp/"),
        rejected("api/%6dcp/ percent-encoded", "GET", "/api/%6dcp/"),
        rejected("api/mcp%2f encoded slash", "GET", "/api/mcp%2f"),
        rejected(
            "api/.well-known literal", "GET", "/api/.well-known/oauth-authorization-server/mcp"
        ),
        rejected(
            "api/%2ewell-known encoded dot", "GET", "/api/%2ewell-known/openid-configuration/mcp"
        ),
        rejected(
            "api//.well-known doubled slash",
            "GET",
            "/api//.well-known/oauth-protected-resource/mcp/",
        ),
        rejected("api/openapi.json", "GET", "/api/openapi.json"),
        rejected("api/readyz", "GET", "/api/readyz"),
        rejected(
            "api/readyz with forwarded loopback",
            "GET",
            "/api/readyz",
            headers={"X-Forwarded-For": "127.0.0.1"},
        ),
        # --- no request-derived redirects -------------------------------------------
        # These reach the app through the generic `/api/` location, so the app
        # decides: family 13 (#204) — 401 with the bare challenge for an
        # anonymous caller, the plain 404 for the signed-in owner; never a
        # Location either way.
        family_13("api/kits/ trailing slash", "GET", "/api/kits/", 404),
        family_13("api/orders/?x=1 trailing slash with query", "GET", "/api/orders/?x=1", 404),
        # --- family 13: unrouted paths and wrong verbs under /api/ -----------------
        family_13("api/no-such-route", "GET", "/api/no-such-route", 404),
        family_13("api/kits wrong verb", "DELETE", "/api/kits", 405),
        rejected(
            "api/mcp/.well-known alias", "GET", "/api/mcp/.well-known/oauth-authorization-server"
        ),
        # --- the root .well-known namespace is not the SPA: family 8's rows are
        # --- `family_8_rows`, on the mode axis ----------------------------------------
        # --- nginx's one redirect ---------------------------------------------------
        Row(
            "api?x=1 relative 301",
            "GET",
            "/api?x=1",
            301,
            location="/api/?x=1",
            csp_contains="frame-ancestors 'none'",
        ),
        # --- positives ------------------------------------------------------------------
        Row(
            "SPA root", "GET", "/", 200, content_type="text/html", csp_contains="default-src 'self'"
        ),
        Row(
            "SPA deep link",
            "GET",
            "/orders",
            200,
            content_type="text/html",
            csp_contains="default-src 'self'",
        ),
        Row(
            "SPA kits/ (root namespace, not the API)",
            "GET",
            "/kits/",
            200,
            content_type="text/html",
            csp_contains="default-src 'self'",
        ),
        Row("api/healthz", "GET", "/api/healthz", 200, json_equals={"status": "ok"}),
        Row(
            "api/healthz with forwarded host",
            "GET",
            "/api/healthz",
            200,
            headers={"X-Forwarded-Host": "evil.example"},
            json_equals={"status": "ok"},
        ),
        # The SPA's bootstrap (family 2) answers anyone; everything below it wants
        # the owner (M6-3), and the anonymous row proves default-deny holds
        # through nginx whatever credential this run carries.
        Row("api/auth/session", "GET", "/api/auth/session", 200, content_type="application/json"),
        unauthenticated("api/kits anonymous → 401", "GET", "/api/kits"),
        guarded("api/docs", "/api/docs", content_type="text/html"),
        guarded("openapi.json canonical", "/openapi.json", content_type="application/json"),
        guarded("api/kits", "/api/kits", content_type="application/json"),
        guarded("api/retailers", "/api/retailers", content_type="application/json"),
        guarded("api/meta", "/api/meta", content_type="application/json"),
        # The MCP transport is bearer-only (§5.5 family 7; #189): with a token
        # the initialize opens a stream, anonymous it is the transport's own 401.
        mcp_challenge("mcp/ initialize anonymous → 401", "/mcp/", www_authenticate=challenge),
        mcp_challenge(
            "mcp bare anonymous → 401 (ingress-only spelling)", "/mcp", www_authenticate=challenge
        ),
        *(
            [
                Row(
                    "mcp/ initialize with a token",
                    "POST",
                    "/mcp/",
                    200,
                    headers={**MCP_HEADERS, **mcp_auth},
                    body=INITIALIZE,
                    content_type="text/event-stream",
                ),
                Row(
                    "mcp bare with a token (ingress-only spelling)",
                    "POST",
                    "/mcp",
                    200,
                    headers={**MCP_HEADERS, **mcp_auth},
                    body=INITIALIZE,
                    content_type="text/event-stream",
                ),
            ]
            if tokens is not None
            else []
        ),
        # --- T3 at the ingress ------------------------------------------------------------
        # The hostile-Host rows are nginx's own 421; behind a TLS proxy the
        # proxy answers a foreign Host before nginx sees it (T12 proves the 421
        # through the proxy with the real name, before ALLOWED_HOSTS lists it).
        *([] if behind_proxy else hostile_host_rows),
        Row(
            "hostile Origin on a write → app 403",
            "POST",
            "/api/retailers",
            403,
            headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
            body=b'{"name":"Ingress Matrix"}',
            json_code="ingress.origin_not_allowed",
        ),
        Row(
            "null Origin on a write → app 403",
            "POST",
            "/api/retailers",
            403,
            headers={"Content-Type": "application/json", "Origin": "null"},
            body=b'{"name":"Ingress Matrix"}',
            json_code="ingress.origin_not_allowed",
        ),
        Row(
            "hostile Origin on MCP initialize → 403",
            "POST",
            "/mcp/",
            403,
            headers={**MCP_HEADERS, "Origin": "https://evil.example"},
            json_code="ingress.origin_not_allowed",
        ),
    ]
    if allowed_host:
        matrix += [
            Row(
                f"listed name {allowed_host} → 200",
                "GET",
                "/api/healthz",
                200,
                headers={"Host": allowed_host},
                json_equals={"status": "ok"},
            ),
            (
                Row(
                    f"listed name {allowed_host} on MCP → 200",
                    "POST",
                    "/mcp/",
                    200,
                    headers={**MCP_HEADERS, **mcp_auth, "Host": allowed_host},
                    body=INITIALIZE,
                    content_type="text/event-stream",
                )
                if tokens is not None
                else mcp_challenge(
                    f"listed name {allowed_host} on MCP anonymous → 401",
                    "/mcp/",
                    www_authenticate=challenge,
                    headers={**MCP_HEADERS, "Host": allowed_host},
                )
            ),
            Row(
                f"listed name {allowed_host} on the SPA → 200",
                "GET",
                "/",
                200,
                headers={"Host": allowed_host},
                content_type="text/html",
                csp_contains="default-src 'self'",
            ),
        ]
    return matrix


def write_rows(
    base: str, allowed_host: str | None, credential: Credential | None = None
) -> list[tuple[Row, Response]]:
    """Writes through the ingress's Origin rule: a loopback Origin on the
    loopback name, no Origin at all, and (with --allowed-host) a same-origin
    write on the listed name. Signed in, the first and third must succeed and are
    undone; the absent-Origin write is now the app's own 403 — a cookie-borne
    write must say where it came from (§5.6, CSRF), and nginx adds no Origin on
    the way through. Anonymous, all three reach the dependency's 401: the ingress
    passed them (its refusals are 403), the app withheld the write.

    When BASE_URL is not a loopback name (a run through a TLS proxy, #194), the
    loopback Origin is the guard's 403 `ingress.origin_not_allowed` signed in or
    not: the loopback-to-loopback allowance needs both sides, and the guard
    speaks before the dependency does."""
    parts = urlsplit(base)
    port = f":{parts.port}" if parts.port else ""
    json_type = {"Content-Type": "application/json"}
    loopback = is_loopback_base(base)

    def write(
        label: str,
        name: str,
        *,
        origin: str | None,
        host: str | None = None,
        forbidden: bool = False,
    ) -> Row:
        headers = {**json_type}
        if host is not None:
            headers["Host"] = host
        if forbidden:
            if origin is not None:
                headers["Origin"] = origin
            if credential is not None:
                headers.update(credential.write(origin))
            return Row(
                f"{label} → 403",
                "POST",
                "/api/retailers",
                403,
                headers=headers,
                body=json.dumps({"name": name}).encode(),
                json_code="ingress.origin_not_allowed",
                content_type="application/json",
            )
        if credential is None:
            if origin is not None:
                headers["Origin"] = origin
            return unauthenticated(
                f"{label} (anonymous)", "POST", "/api/retailers", headers=headers
            )
        headers.update(credential.write(origin))
        if origin is None:
            return Row(
                f"{label} → 403",
                "POST",
                "/api/retailers",
                403,
                headers=headers,
                body=json.dumps({"name": name}).encode(),
                json_code="auth.origin_required",
                content_type="application/json",
            )
        return Row(
            f"{label} → 201",
            "POST",
            "/api/retailers",
            201,
            headers=headers,
            body=json.dumps({"name": name}).encode(),
            content_type="application/json",
        )

    cases = [
        write(
            "loopback Origin on a write"
            if loopback
            else "loopback Origin against a non-loopback name",
            "Ingress Matrix Loopback",
            origin=f"http://localhost{port}",
            forbidden=not loopback,
        ),
        write("absent Origin on a cookie-borne write", "Ingress Matrix Script", origin=None),
    ]
    if allowed_host:
        cases.append(
            write(
                f"same-origin write on {allowed_host}",
                "Ingress Matrix Listed",
                origin=f"http://{allowed_host}{port}",
                host=f"{allowed_host}{port}",
            )
        )
    results = []
    for row in cases:
        resp = send(base, row)
        results.append((row, resp))
        if resp.status == 201 and credential is not None:
            created = resp.json()["id"]
            cleanup = Row(
                "cleanup",
                "DELETE",
                f"/api/retailers/{created}",
                204,
                headers=credential.write(f"{parts.scheme}://{parts.netloc}"),
            )
            done = send(base, cleanup)
            if done.status != 204:
                results.append((cleanup, done))
    return results


def token_rows(
    base: str, tokens: Tokens, *, mode: str = "local", public_base_url: str | None = None
) -> list[Row]:
    """The bearer through nginx (§5.5; #189): what each grant can and cannot do,
    and the one answer every failed bearer earns. The two rows that carry an
    Origin send the request's own — the rule that holds on every base name,
    where a loopback Origin holds on a loopback name alone (`write_rows`).

    The two OIDC rows are on the mode axis: in local mode the routes exist and
    answer their own 404 naming the mode; in OIDC mode `oidc/start` begins a
    login (200) and the callback with a state nobody issued is the documented
    302 to the SPA's root **built from `PUBLIC_BASE_URL`** — behind TLS, the T9
    proof that a self Location names the public scheme and host, never the
    plain-http socket's."""
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    invalid = 'Bearer error="invalid_token"'
    public = (public_base_url or base).rstrip("/")
    if mode == "oidc":
        oidc_rows = [
            Row(
                "api/auth/oidc/start in oidc mode → 200 (a login begins)",
                "POST",
                "/api/auth/oidc/start",
                200,
                headers={"Content-Type": "application/json", "Origin": origin},
                body=b"{}",
                content_type="application/json",
            ),
            Row(
                "api/auth/oidc/callback with an unknown state → 302 to PUBLIC_BASE_URL",
                "GET",
                "/api/auth/oidc/callback?state=x&code=y",
                302,
                location=f"{public}/?auth_error=oidc_expired",
            ),
        ]
    else:
        oidc_rows = [
            Row(
                "api/auth/oidc/start in local mode → 404",
                "POST",
                "/api/auth/oidc/start",
                404,
                headers={"Content-Type": "application/json", "Origin": origin},
                body=b"{}",
                json_code="auth.not_in_this_mode",
            ),
            Row(
                "api/auth/oidc/callback in local mode → 404, no Location",
                "GET",
                "/api/auth/oidc/callback?state=x&code=y",
                404,
                json_code="auth.not_in_this_mode",
            ),
        ]
    return [
        Row(
            "api/kits with a read token → 200",
            "GET",
            "/api/kits",
            200,
            headers=tokens.read.header(),
            content_type="application/json",
        ),
        Row(
            "api/retailers write with a read token → 403",
            "POST",
            "/api/retailers",
            403,
            headers={**tokens.read.header(), "Content-Type": "application/json"},
            body=b'{"name":"Ingress Matrix Read Token"}',
            json_code="auth.forbidden",
        ),
        Row(
            "api/auth/tokens with a write token → 403 (a token cannot manage tokens)",
            "GET",
            "/api/auth/tokens",
            403,
            headers=tokens.write.header(),
            json_code="auth.forbidden",
        ),
        Row(
            "api/settings PATCH with a write token → 403",
            "PATCH",
            "/api/settings",
            403,
            headers={**tokens.write.header(), "Content-Type": "application/json"},
            body=b'{"time_zone":"Australia/Sydney"}',
            json_code="auth.forbidden",
        ),
        Row(
            "api/auth/login with a token → 403 (a token is not a browser)",
            "POST",
            "/api/auth/login",
            403,
            headers={
                **tokens.write.header(),
                "Content-Type": "application/json",
                "Origin": origin,
            },
            body=b'{"password":"irrelevant"}',
            json_code="auth.forbidden",
        ),
        # OIDC mode's routes exist in local mode too (#191) — registered and
        # answering 404 themselves, never the anonymous 401, so a mode is not a
        # challenge (§5.5); in local mode the callback carries no Location, so a
        # browser sent here by a hostile page lands on the envelope, nowhere
        # else. In OIDC mode they are live, and the callback's Location is the
        # public origin (the docstring).
        *oidc_rows,
        # A well-shaped *fake* token, never a live one: request URIs land in the
        # uvicorn and nginx access logs, and a real token there would put the
        # branch's own integration run in breach of T10 (Codex #202 round 1,
        # f3). The row still proves the parameter is ignored — an
        # implementation honouring it would answer `auth.bearer_invalid` for
        # this value, not the anonymous 401.
        Row(
            "api/kits?access_token= is anonymous → 401",
            "GET",
            f"/api/kits?access_token=ptk_{'0' * 12}_{'A' * 43}",
            401,
            json_code="auth.unauthenticated",
            www_authenticate="Bearer",
        ),
        Row(
            "api/kits with a wrong secret → 401 invalid_token",
            "GET",
            "/api/kits",
            401,
            headers=_wrong_secret(tokens.write),
            json_code="auth.bearer_invalid",
            www_authenticate=invalid,
        ),
        Row(
            "mcp/ initialize with a wrong secret → 401 invalid_token",
            "POST",
            "/mcp/",
            401,
            headers={**MCP_HEADERS, **_wrong_secret(tokens.write)},
            body=INITIALIZE,
            www_authenticate=invalid,
            www_authenticate_exact=False,
            content_type="application/json",
        ),
    ]


#: The SDK pings an idle SSE stream every ~15 s (sse-starlette's default). A gap
#: past two intervals is a buffering or stalled chain, not a live keepalive — the
#: held stream is failing, not holding.
MODERN_MAX_SILENCE = 30.0
_LAST_CHUNK = b"\r\n0\r\n\r\n"


def _observe_hold(
    raw, seconds: int, initial_bytes: bytes, *, max_silence: float = MODERN_MAX_SILENCE
) -> tuple[bool, int, int, float, str]:
    """Read an SSE stream for `seconds`, **asserting** — not merely reporting —
    that it keeps flowing: no silence (before the first byte, between bytes, or
    trailing) exceeds `max_silence`, and the chain neither closes the socket nor
    sends the chunked terminator within the window (the handler must still be
    holding). Returns `(ok, chunks, received, max_gap, reason)`.

    A held stream that goes silent, buffers, or completes early is a gate
    failure the caller must surface: reporting `max_gap` alone let an
    initial-ping-then-silence stream pass with `max gap 0.0 s`, and a completed
    body on a still-open socket pass as if it were holding (#244, Codex #250 F1).
    `raw.recv` and `time.monotonic` are the only ambient inputs, so the observer
    is exercised offline by `tests/test_hold_observer.py` with a scripted socket
    and clock."""
    started = time.monotonic()
    last = started
    chunks, received, max_gap = (1, len(initial_bytes), 0.0) if initial_bytes else (0, 0, 0.0)
    tail = initial_bytes[-len(_LAST_CHUNK) :]
    if tail.endswith(_LAST_CHUNK):
        return False, chunks, received, max_gap, "the stream completed before the hold began"
    raw.settimeout(2.0)
    while time.monotonic() - started < seconds:
        try:
            piece = raw.recv(4096)
        except TimeoutError:
            gap = time.monotonic() - last
            if gap > max_silence:
                return (
                    False,
                    chunks,
                    received,
                    max(max_gap, gap),
                    f"silent {gap:.1f} s (> {max_silence:g} s) after "
                    f"{time.monotonic() - started:.1f} s of {seconds} — buffered or stalled",
                )
            continue
        now = time.monotonic()
        if not piece:
            return (
                False,
                chunks,
                received,
                max_gap,
                f"the chain closed the stream after {now - started:.1f} s of {seconds}",
            )
        gap = now - last
        tail = (tail + piece)[-len(_LAST_CHUNK) :]
        max_gap, last = max(max_gap, gap), now
        chunks, received = chunks + 1, received + len(piece)
        if gap > max_silence:
            return (
                False,
                chunks,
                received,
                max_gap,
                f"a {gap:.1f} s gap (> {max_silence:g} s) between bytes — buffered or stalled",
            )
        if tail.endswith(_LAST_CHUNK):
            return (
                False,
                chunks,
                received,
                max_gap,
                f"the stream completed (terminal chunk) after {now - started:.1f} s of {seconds}",
            )
    max_gap = max(max_gap, time.monotonic() - last)
    if chunks == 0:
        return (
            False,
            chunks,
            received,
            max_gap,
            f"no bytes in {seconds} s (committed but never pinged)",
        )
    if max_gap > max_silence:
        return (
            False,
            chunks,
            received,
            max_gap,
            f"max gap {max_gap:.1f} s exceeds {max_silence:g} s",
        )
    return True, chunks, received, max_gap, f"max gap {max_gap:.1f} s (< {max_silence:g} s)"


def hold_stream(
    base: str, bearer: Bearer, path: str, seconds: int, *, close_grace: float = 10.0
) -> tuple[bool, str]:
    """T12's held stream (§5.8): a standalone MCP GET stream on `path`, kept
    open for `seconds` with this client silent, then ended by a DELETE of the
    session on another connection. Fails if anything on the chain ends the
    response before the deadline — an EOF, or the terminating chunk — or if
    nothing ends it once the session is gone (a half-open stream nobody can
    close is the other proxy failure). Reads the socket raw: the probe needs
    liveness and the end of the response, not SSE parsing, and `http.client`'s
    chunked reader does not survive a read timeout mid-frame.

    Reports the maximum gap between bytes. The SDK's streams send a ping every
    15 s (sse-starlette's default), so a proxy read timeout shorter than that
    never fires here, and a probe that only waited would be green for the
    wrong reason; the gap is the value that says which chain the bytes crossed
    and whether anything on it buffered them."""
    parts = urlsplit(base)
    with_session = {**MCP_HEADERS, **bearer.header()}
    opened = send(base, Row("initialize", "POST", path, 200, headers=with_session, body=INITIALIZE))
    if opened.status != 200:
        return False, f"initialize answered {opened.status}"
    session_id = opened.headers.get("mcp-session-id")
    if not session_id:
        return False, "initialize set no mcp-session-id (a stateless mount holds no stream)"
    with_session["Mcp-Session-Id"] = session_id
    acknowledged = send(
        base, Row("initialized", "POST", path, 202, headers=with_session, body=INITIALIZED)
    )
    if acknowledged.status != 202:
        return False, f"notifications/initialized answered {acknowledged.status}"

    raw = socket.create_connection((parts.hostname, default_port(base)), timeout=10)
    if parts.scheme == "https":
        raw = TLS_CONTEXT.wrap_socket(raw, server_hostname=parts.hostname)
    request = (
        f"GET {path} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
        f"Authorization: Bearer {bearer.raw}\r\nAccept: text/event-stream\r\n"
        f"Mcp-Session-Id: {session_id}\r\nMCP-Protocol-Version: 2025-06-18\r\n"
        "Connection: close\r\n\r\n"
    ).encode()
    try:
        raw.sendall(request)
        raw.settimeout(5)
        # A tunnel that buffers until the origin's content-type is known may not
        # flush the response headers until the stream's first ping (~15 s), so
        # tolerate the read timeout up to the hold window rather than the socket's
        # connect timeout — Caddy and a direct connection flush immediately.
        header_deadline = time.monotonic() + max(seconds, 30)
        head = b""
        while b"\r\n\r\n" not in head:
            try:
                piece = raw.recv(4096)
            except TimeoutError:
                if time.monotonic() > header_deadline:
                    return False, "no response headers within the hold window (a buffering proxy?)"
                continue
            if not piece:
                return False, "closed before any response headers"
            head += piece
        header_block, body = head.split(b"\r\n\r\n", 1)
        status_line, *header_lines = header_block.decode("latin-1").split("\r\n")
        status = int(status_line.split(" ", 2)[1])
        headers = {
            name.strip().lower(): value.strip()
            for name, value in (line.split(":", 1) for line in header_lines if ":" in line)
        }
        if status != 200 or not headers.get("content-type", "").startswith("text/event-stream"):
            return False, f"GET answered {status} {headers.get('content-type')!r}"

        # The stream must keep flowing for the whole window (the observer asserts
        # no stall and no early close/completion), then the DELETE must end it.
        held_start = time.monotonic()
        ok, chunks, received, max_gap, reason = _observe_hold(raw, seconds, body)
        held = time.monotonic() - held_start
        if not ok:
            return False, f"{reason} ({chunks} chunk(s), max gap {max_gap:.1f} s)"

        tail = b""

        def ended(piece: bytes) -> bool:
            nonlocal tail
            if not piece:
                return True
            tail = (tail + piece)[-len(_LAST_CHUNK) :]
            return tail.endswith(_LAST_CHUNK)

        deleted = send(base, Row("delete session", "DELETE", path, 200, headers=with_session))
        delete_at = time.monotonic()
        closed_after = None
        raw.settimeout(min(1.0, close_grace))
        while time.monotonic() - delete_at < close_grace:
            try:
                piece = raw.recv(4096)
            except TimeoutError:
                continue
            if ended(piece):
                closed_after = time.monotonic() - delete_at
                break
        if deleted.status != 200:
            return False, f"DELETE answered {deleted.status} after a {held:.1f} s hold"
        if closed_after is None:
            return False, (
                f"still open {close_grace:g} s after DELETE"
                f" (held {held:.1f} s, max gap {max_gap:.1f} s)"
            )
        return True, (
            f"held {held:.1f} s (asked {seconds}); {chunks} chunk(s), {received} bytes;"
            f" max gap {max_gap:.1f} s; ended {closed_after:.1f} s after DELETE"
        )
    finally:
        raw.close()


def hold_stream_modern(base: str, bearer: Bearer, path: str, seconds: int) -> tuple[bool, str]:
    """T12's modern twin (§7.1; #244): the `2026-07-28` era has no standalone GET
    channel and opens no session, so the held stream is the response to a single
    `tools/call` POST whose handler runs past the SDK's ping interval. plamotrack
    exposes no long-running tool, so this requires the stack to arm
    `PLAMOTRACK_ENABLE_TEST_HOLD` (`app.mcp_hold_probe`), which makes `get_meta`
    hold a database connection for that many seconds — an isolated test
    instance, never the shipped image. The client reads the SSE for `seconds`
    with the connection silent, then **aborts by closing the socket** (the
    modern era's cancellation: there is no DELETE); the caller verifies
    server-side cancellation and connection cleanup out of band (the deployment
    gate reads `pg_stat_activity`).

    Fails if the chain never commits `text/event-stream`, sets a session id
    (a modern response must not), buffers the keepalive (a gap at or beyond the
    ping interval), or ends the stream before the deadline (the handler must
    still be holding). Reads the socket raw for the same reason
    `hold_stream` does. Reports the longest gap between bytes."""
    parts = urlsplit(base)
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "get_meta",
                "arguments": {},
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientInfo": {
                        "name": "ingress_matrix",
                        "version": "0",
                    },
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        }
    ).encode()

    raw = socket.create_connection((parts.hostname, default_port(base)), timeout=10)
    if parts.scheme == "https":
        raw = TLS_CONTEXT.wrap_socket(raw, server_hostname=parts.hostname)
    request = (
        f"POST {path} HTTP/1.1\r\nHost: {parts.netloc}\r\n"
        f"Authorization: Bearer {bearer.raw}\r\n"
        "Accept: application/json, text/event-stream\r\nContent-Type: application/json\r\n"
        "MCP-Protocol-Version: 2026-07-28\r\nMcp-Method: tools/call\r\nMcp-Name: get_meta\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode() + body
    try:
        raw.sendall(request)
        raw.settimeout(5)
        header_deadline = time.monotonic() + max(seconds, 30)
        head = b""
        while b"\r\n\r\n" not in head:
            try:
                piece = raw.recv(4096)
            except TimeoutError:
                if time.monotonic() > header_deadline:
                    return False, "no response headers within the hold window (a buffering proxy?)"
                continue
            if not piece:
                return False, "closed before any response headers"
            head += piece
        header_block, body_bytes = head.split(b"\r\n\r\n", 1)
        status_line, *header_lines = header_block.decode("latin-1").split("\r\n")
        status = int(status_line.split(" ", 2)[1])
        headers = {
            name.strip().lower(): value.strip()
            for name, value in (line.split(":", 1) for line in header_lines if ":" in line)
        }
        if status != 200 or not headers.get("content-type", "").startswith("text/event-stream"):
            return False, f"POST answered {status} {headers.get('content-type')!r}"
        if "mcp-session-id" in headers:
            return False, "a modern response set mcp-session-id (it must not)"

        held_start = time.monotonic()
        ok, chunks, received, max_gap, reason = _observe_hold(raw, seconds, body_bytes)
        held = time.monotonic() - held_start
        if not ok:
            return (
                False,
                f"{reason} ({chunks} chunk(s), {received} bytes) — the handler stopped holding",
            )
        return True, (
            f"held {held:.1f} s (asked {seconds}); {chunks} chunk(s), {received} bytes;"
            f" {reason}; no session id; aborted by close"
        )
    finally:
        raw.close()


def revoked_rows(tokens: Tokens) -> list[Row]:
    """After the read token is revoked: refused everywhere, in the same shape."""
    invalid = 'Bearer error="invalid_token"'
    return [
        Row(
            "api/kits with a revoked token → 401",
            "GET",
            "/api/kits",
            401,
            headers=tokens.read.header(),
            json_code="auth.bearer_invalid",
            www_authenticate=invalid,
        ),
        Row(
            "mcp/ initialize with a revoked token → 401",
            "POST",
            "/mcp/",
            401,
            headers={**MCP_HEADERS, **tokens.read.header()},
            body=INITIALIZE,
            www_authenticate=invalid,
            www_authenticate_exact=False,
            content_type="application/json",
        ),
    ]


def query_log_probes(
    base: str, mode: str, markers: dict[str, str], *, throttled: bool = False
) -> list[str]:
    """Synthetic credentials exercise the real query/Referer logging paths.
    Never print the query: the caller records only the probe's outcome."""
    callback = (
        "/mcp/auth/callback?code=" + markers["oauth_code"] + "&state=" + markers["oauth_state"]
    )
    headers = {"Referer": base + "/callback?code=" + markers["referer_code"]}
    row = Row(
        "callback query log probe",
        "GET",
        callback,
        429 if throttled else (400 if mode == "oidc" else 404),
        headers=headers,
    )
    if throttled:
        row = replace(rate_limit_refusal(callback), headers=headers)
        refused = [
            response
            for response in (send(base, row) for _ in range(RATE_LIMIT_BURST))
            if response.status == 429
        ]
        if not refused:
            return ["query-bearing burst never engaged the limiter"]
        return [problem for response in refused for problem in check(row, response)]
    problems = check(row, send(base, row))
    if not throttled:
        row = Row(
            "token query log probe",
            "GET",
            "/api/healthz?access_token=" + markers["oauth_code"],
            200,
        )
        problems.extend(check(row, send(base, row)))
    return problems


def rate_limit_refusal(path: str) -> Row:
    return Row(
        "bounded family refusal profile",
        "GET",
        path,
        429,
        content_type="application/json",
        json_code="ingress.rate_limited",
        expect_headers={**NO_STORE, "retry-after": "1"},
    )


def rate_limit_checks(base: str, mode: str = "local") -> list[str]:
    """T8 at the real ingress: each bounded family eventually answers 429.

    The checks run after sign-out and use safe GETs, so they cannot change auth
    state or trip the app's separate login-failure budget. We intentionally do
    not pin the exact accepted count — elapsed time and a worker scheduling gap
    can replenish a request — only the control's observable boundary. Doubled-
    slash, dot-segment and percent-encoded spellings are sent verbatim for every
    family: each must share the canonical ingress limit key, even when the app
    refuses an unrewritten root spelling (#208 review P3-1).
    """
    discovery_status = {200} if mode == "oidc" else {404}
    cases = (
        ("family 2 auth bootstrap", "/api/auth/session", {200}),
        ("family 3 auth actions", "/api/auth/login", {405}),
        ("family 8 protocol", "/.well-known/openid-configuration/mcp", discovery_status),
        ("family 9 liveness", "/api/healthz", {200}),
    )
    # Every protocol location now inherits this same budget (#212/#193).
    protocol_cases = tuple(
        ("family 8 " + path, path, {400, 405} if mode == "oidc" else {404, 405})
        for path in PROTOCOL_ROUTES
    )
    cases += protocol_cases
    problems: list[str] = []
    for label, path, admitted in cases:
        statuses: list[int] = []
        for _ in range(80):
            response = send(base, Row(label, "GET", path, 0))
            statuses.append(response.status)
            if response.status == 429:
                problems.extend(check(rate_limit_refusal(path), response))
                break
            if response.status not in admitted:
                problems.append(
                    f"{label} answered {response.status} before throttling; "
                    f"expected one of {sorted(admitted)}"
                )
                break
        if 429 not in statuses:
            problems.append(f"{label} never answered 429 across {len(statuses)} requests")
        else:
            print(f"ok  RATE   {path:60} {label} → 429 after {len(statuses)} requests")
    normalised_cases = (
        ("family 2", "//api/auth/session", {200}),
        ("family 2", "/api/./auth/session", {200}),
        ("family 2", "/api/%61uth/session", {200}),
        ("family 3", "//api/auth/login", {405}),
        ("family 3", "/api/./auth/login", {405}),
        ("family 3", "/api/auth/%6cogin", {405}),
        # Root proxy locations can forward an unrewritten spelling to the app,
        # whose default-deny gate then answers 401. A non-canonical spelling of a
        # discovery document is 404 at nginx (one spelling per family, rule 12) —
        # `/.well-known/./…` is 404 while `//…` and `%6f…` normalise to the 200
        # canonical — but the limiter keys on the normalised path either way, so
        # 404 is an admitted pre-throttle status here and the 429 is the real
        # proof. In local mode discovery is itself 404, which is why this only
        # surfaced under the OIDC-mode gate (#194): there discovery is 200, and a
        # 404 spelling failed the check whenever the limiter had not tripped first.
        ("family 8", "//.well-known/openid-configuration/mcp", discovery_status | {401, 404}),
        ("family 8", "/.well-known/./openid-configuration/mcp", discovery_status | {401, 404}),
        ("family 8", "/.well-known/%6fpenid-configuration/mcp", discovery_status | {401, 404}),
        ("family 9", "//api/healthz", {200}),
        ("family 9", "/api/./healthz", {200}),
        ("family 9", "/api/%68ealthz", {200}),
    )
    for label, path, admitted in protocol_cases:
        prefix, name = path.rsplit("/", 1)
        encoded = prefix + "/%" + format(ord(name[0]), "02x") + name[1:]
        normalised_cases += tuple(
            (label, spelling, admitted | {401, 404})
            for spelling in ("/" + path, "/./" + path.lstrip("/"), encoded)
        )
    for family, path, admitted in normalised_cases:
        statuses = []
        for _ in range(80):
            response = send(base, Row(f"{family} normalised spelling", "GET", path, 0))
            statuses.append(response.status)
            if response.status == 429:
                problems.extend(check(rate_limit_refusal(path), response))
                break
            if response.status not in admitted:
                problems.append(
                    f"normalised {family} spelling {path!r} answered {response.status} "
                    f"before throttling; expected one of {sorted(admitted)}"
                )
                break
        if 429 not in statuses:
            problems.append(
                f"normalised {family} spelling {path!r} never answered 429 "
                f"across {len(statuses)} requests"
            )
        else:
            print(
                f"ok  RATE   {path:60} {family} normalised spelling → 429 "
                f"after {len(statuses)} requests"
            )
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8080")
    parser.add_argument("--allowed-host", default=None)
    parser.add_argument(
        "--setup-token",
        default=None,
        help="claim an unclaimed stack with this token (from the API log) and --password",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="the owner password: the one to set with --setup-token, else the one to log in with",
    )
    parser.add_argument(
        "--token-out",
        default=None,
        help="write the minted write token to this file (mode 0600) and leave it live",
    )
    parser.add_argument(
        "--log-secrets-out",
        default=None,
        help="write query probes and any run PAT/session/password to a private JSON file for T10",
    )
    parser.add_argument(
        "--mode",
        choices=("local", "oidc"),
        default="local",
        help="the stack's AUTH_MODE: decides what family 8 (MCP OAuth) is expected to answer",
    )
    parser.add_argument(
        "--public-base-url",
        default=None,
        help="the stack's PUBLIC_BASE_URL when it differs from BASE_URL (OIDC mode names it)",
    )
    parser.add_argument(
        "--credential-file",
        default=None,
        help="JSON {cookie, csrf_token} of a signed-in owner session the matrix cannot "
        "obtain itself (an OIDC login); it is used, never signed out",
    )
    parser.add_argument(
        "--ca-cert",
        default=None,
        help="a CA bundle to trust for an https BASE_URL (a private CA); else the system store",
    )
    parser.add_argument(
        "--behind-proxy",
        action="store_true",
        help="BASE_URL is a TLS proxy in front of the stack: the hostile-Host rows, which the "
        "proxy answers itself, are skipped",
    )
    parser.add_argument(
        "--hold-stream",
        type=int,
        default=0,
        metavar="SECONDS",
        help="hold a standalone MCP stream open this long on /mcp/ and on bare /mcp (T12); 0 skips",
    )
    parser.add_argument(
        "--skip-rate-limits",
        action="store_true",
        help="do not exercise nginx's per-address limiter — for a run behind a CDN whose "
        "latency and URL normalisation make the per-second, per-spelling keying unobservable "
        "(it is proven at the packaged layer instead)",
    )
    args = parser.parse_args(argv)
    if args.setup_token is not None and args.password is None:
        parser.error("--setup-token needs --password (the password the claim sets)")
    if args.credential_file is not None and args.password is not None:
        parser.error("--credential-file supplies the session; --password is not used with it")
    if args.token_out is not None and args.password is None and args.credential_file is None:
        parser.error("--token-out needs a signed-in owner (--password or --credential-file)")
    if args.hold_stream < 0:
        parser.error("--hold-stream takes a number of seconds")
    if args.ca_cert is not None:
        global TLS_CONTEXT
        TLS_CONTEXT = ssl.create_default_context(cafile=args.ca_cert)

    log_secrets = (
        {key: secrets.token_urlsafe(24) for key in ("oauth_code", "oauth_state", "referer_code")}
        if args.log_secrets_out
        else None
    )
    credential = None
    tokens = None
    supplied = args.credential_file is not None
    if supplied:
        session = json.loads(pathlib.Path(args.credential_file).read_text(encoding="utf-8"))
        credential = Credential(cookie=session["cookie"], csrf_token=session["csrf_token"])
        tokens = mint_tokens(args.base, credential)
        print("using the supplied owner session (stays signed in); minted a write and a read token")
    elif args.password is not None:
        credential = sign_in(args.base, setup_token=args.setup_token, password=args.password)
        if args.setup_token is not None:
            # A fresh-stack run proves both credential-bearing actions: claim,
            # then sign out and perform a real password login for the full T10
            # log scan. The credential below is therefore always login-issued.
            sign_out(args.base, credential)
            credential = sign_in(args.base, setup_token=None, password=args.password)
            print("claimed the instance, then logged in as the owner")
        else:
            print("logged in as the owner")
        tokens = mint_tokens(args.base, credential)
        print("minted a write token and a read token for the bearer rows")
    else:
        print("no credential: guarded positives expect the dependency's 401")

    failures = 0

    def run(row: Row, resp: Response | None = None) -> None:
        nonlocal failures
        problems = check(row, resp if resp is not None else send(args.base, row))
        status = "ok " if not problems else "FAIL"
        print(f"{status} {row.method:6} {row.path:60} {row.label}")
        for problem in problems:
            failures += 1
            print(f"       {problem}")

    public_base_url = (args.public_base_url or args.base).rstrip("/")
    if args.behind_proxy:
        for label in HOSTILE_HOST_LABELS:
            print(f"skip {'':6} {'':60} {label} (a proxy answers a foreign Host itself)")
    for row in rows(
        args.allowed_host,
        credential,
        tokens,
        challenge=mcp_challenge_value(args.mode, public_base_url),
        behind_proxy=args.behind_proxy,
    ):
        run(row)
    for row in family_8_rows(args.mode, public_base_url):
        # Family 8 now shares a budget across discovery and protocol routes.
        # These are contract checks; intentional bursts run separately below.
        time.sleep(0.12)
        run(row)
    for row in body_budget_rows(args.mode, claimed=credential is not None):
        time.sleep(0.12)
        run(row)
    for row, resp in origin_flood_rows(args.base):
        run(row, resp)
    for row, resp in write_rows(args.base, args.allowed_host, credential):
        run(row, resp)
    if credential is not None and tokens is not None:
        if log_secrets is not None:
            log_secrets.update(
                pat=tokens.write.raw,
                session=credential.cookie.split("=", 1)[1],
            )
            if args.password is not None:
                log_secrets["password"] = args.password
        for row in token_rows(args.base, tokens, mode=args.mode, public_base_url=public_base_url):
            run(row)
        if args.hold_stream:
            for path in ("/mcp/", "/mcp"):
                ok, message = hold_stream(args.base, tokens.write, path, args.hold_stream)
                if not ok:
                    failures += 1
                print(f"{'ok ' if ok else 'FAIL'} {'HOLD':6} {path:60} {message}")
        revoke_token(args.base, credential, tokens.read)
        for row in revoked_rows(tokens):
            run(row)
        if args.token_out is not None:
            path = write_private(args.token_out, tokens.write.raw + "\n")
            print(f"write token left live and written to {path}")
        else:
            revoke_token(args.base, credential, tokens.write)
        if not supplied:
            sign_out(args.base, credential)
    if log_secrets is not None:
        write_private(args.log_secrets_out, json.dumps(log_secrets) + "\n")
        for problem in query_log_probes(args.base, args.mode, log_secrets):
            failures += 1
            print(f"FAIL LOG {problem}")
        print("query/referrer log probes sent; scan their private output with the container logs")
    if args.skip_rate_limits:
        print(f"skip {'RATE':6} {'':60} limiter checks skipped (--skip-rate-limits)")
    else:
        for problem in rate_limit_checks(args.base, args.mode):
            failures += 1
            print(f"FAIL {'RATE':6} {'':60} {problem}")
        for row, resp in rate_limit_rows(args.base):
            run(row, resp)
        if log_secrets is not None:
            for problem in query_log_probes(args.base, args.mode, log_secrets, throttled=True):
                failures += 1
                print(f"FAIL LOG {problem}")
    print(f"\n{failures} failing check(s)")
    return failures


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
