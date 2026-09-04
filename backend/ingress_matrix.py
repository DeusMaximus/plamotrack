"""T2 — the ingress matrix, run against the packaged stack (design notes §5.5,
§5.8; M6-1, #186).

    uv run python ingress_matrix.py [BASE_URL] [--allowed-host NAME]
                                    [--setup-token TOKEN] [--password PASSWORD]
                                    [--token-out PATH] [--log-secrets-out PATH]

BASE_URL defaults to http://127.0.0.1:8080. `--allowed-host` names an entry the
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
`--log-secrets-out PATH` writes the run's password, PAT and session value to a
mode-0600 JSON file for the caller's T10 log scan; none is printed.

What it proves, per row: the status; that no response carries a `Location`
except nginx's own relative `/api` → `/api/` 301; that the security headers are
present on everything nginx serves; and that the one-spelling-per-family
rejections — the `/api/mcp`, `/api/.well-known`, `/api/openapi.json` and
`/api/readyz` namespaces in their literal, doubled-slash and percent-encoded
forms — are 404 while their canonical spellings and the positives beside them
(`/api/docs`, `/api/healthz`, the collection routes, `/mcp/`, `/openapi.json`)
answer. Paths are sent verbatim over `http.client`, because an HTTP library
that normalises `%6d` back to `m` would test the wrong spelling.

Snapshots responses, never a route table (§5.5). Exit status is the number of
failing rows; every failure is printed with what was expected.
"""

from __future__ import annotations

import argparse
import http.client
import json
import pathlib
import sys
from dataclasses import dataclass, field
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
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
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
    """Create/restrict a harness secret file before putting a secret in it."""
    path = pathlib.Path(path_value)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(content)
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


def send(base: str, row: Row, host_override: str | None = None) -> Response:
    parts = urlsplit(base)
    conn = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=30)
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
    if row.json_equals is not None or row.json_code is not None:
        try:
            parsed = resp.json()
        except ValueError:
            problems.append(f"body is not JSON: {resp.body[:80]!r}")
            parsed = None
        if parsed is not None and row.json_equals is not None and parsed != row.json_equals:
            problems.append(f"body {parsed!r}, expected {row.json_equals!r}")
        if parsed is not None and row.json_code is not None and parsed.get("code") != row.json_code:
            problems.append(f"code {parsed.get('code')!r}, expected {row.json_code!r}")
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
    guard's are 403/421)."""
    return Row(
        label,
        "POST",
        path,
        401,
        body=INITIALIZE,
        www_authenticate="Bearer",
        **{"headers": MCP_HEADERS, **kw},
    )


def rows(
    allowed_host: str | None, credential: Credential | None = None, tokens: Tokens | None = None
) -> list[Row]:
    owner = credential.read() if credential is not None else {}
    mcp_auth = tokens.write.header() if tokens is not None else {}

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
        # --- the root .well-known namespace is not the SPA ---------------------------
        rejected("root .well-known unknown", "GET", "/.well-known/anything"),
        rejected(
            "root .well-known discovery (404 until M6-7)",
            "GET",
            "/.well-known/openid-configuration/mcp",
        ),
        rejected(
            "root .well-known resource (404 until M6-7)",
            "GET",
            "/.well-known/oauth-protected-resource/mcp/",
        ),
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
        mcp_challenge("mcp/ initialize anonymous → 401", "/mcp/"),
        mcp_challenge("mcp bare anonymous → 401 (ingress-only spelling)", "/mcp"),
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
        Row(
            "hostile Host → nginx 421",
            "GET",
            "/",
            421,
            headers={"Host": "evil.example"},
            json_code="ingress.host_not_allowed",
            security_headers=False,
        ),
        Row(
            "hostile Host on the API → nginx 421",
            "GET",
            "/api/healthz",
            421,
            headers={"Host": "evil.example"},
            json_code="ingress.host_not_allowed",
            security_headers=False,
        ),
        Row(
            "hostile Host on MCP → nginx 421",
            "POST",
            "/mcp/",
            421,
            headers={**MCP_HEADERS, "Host": "evil.example"},
            json_code="ingress.host_not_allowed",
            security_headers=False,
        ),
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
    passed them (its refusals are 403), the app withheld the write."""
    parts = urlsplit(base)
    port = f":{parts.port}" if parts.port else ""
    json_type = {"Content-Type": "application/json"}

    def write(label: str, name: str, *, origin: str | None, host: str | None = None) -> Row:
        headers = {**json_type}
        if host is not None:
            headers["Host"] = host
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
            "loopback Origin on a write",
            "Ingress Matrix Loopback",
            origin=f"http://localhost{port}",
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


def token_rows(base: str, tokens: Tokens) -> list[Row]:
    """The bearer through nginx (§5.5; #189): what each grant can and cannot do,
    and the one answer every failed bearer earns."""
    port = urlsplit(base).port
    port = f":{port}" if port else ""
    invalid = 'Bearer error="invalid_token"'
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
                "Origin": f"http://localhost{port}",
            },
            body=b'{"password":"irrelevant"}',
            json_code="auth.forbidden",
        ),
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


def rate_limit_checks(base: str) -> list[str]:
    """T8 at the real ingress: each bounded family eventually answers 429.

    The checks run after sign-out and use safe GETs, so they cannot change auth
    state or trip the app's separate login-failure budget. We intentionally do
    not pin the exact accepted count — elapsed time and a worker scheduling gap
    can replenish a request — only the control's observable boundary.
    """
    cases = (
        ("family 2 auth bootstrap", "/api/auth/session", {200}),
        ("family 3 auth actions", "/api/auth/login", {405}),
        ("family 8 protocol", "/.well-known/openid-configuration/mcp", {404}),
        ("family 9 liveness", "/api/healthz", {200}),
    )
    problems: list[str] = []
    for label, path, admitted in cases:
        statuses: list[int] = []
        for _ in range(80):
            response = send(base, Row(label, "GET", path, 0))
            statuses.append(response.status)
            if response.status == 429:
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
        help="write the run's PAT, session id and password to a mode-0600 JSON file for T10",
    )
    args = parser.parse_args(argv)
    if args.setup_token is not None and args.password is None:
        parser.error("--setup-token needs --password (the password the claim sets)")
    if args.token_out is not None and args.password is None:
        parser.error("--token-out needs a signed-in owner (--password) to mint the token")
    if args.log_secrets_out is not None and args.password is None:
        parser.error("--log-secrets-out needs a signed-in owner (--password)")

    credential = None
    tokens = None
    if args.password is not None:
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

    for row in rows(args.allowed_host, credential, tokens):
        run(row)
    for row, resp in write_rows(args.base, args.allowed_host, credential):
        run(row, resp)
    if credential is not None and tokens is not None:
        if args.log_secrets_out is not None:
            path = write_private(
                args.log_secrets_out,
                json.dumps(
                    {
                        "password": args.password,
                        "pat": tokens.write.raw,
                        "session": credential.cookie.split("=", 1)[1],
                    }
                )
                + "\n",
            )
            print(f"log-scan secrets written to {path}")
        for row in token_rows(args.base, tokens):
            run(row)
        revoke_token(args.base, credential, tokens.read)
        for row in revoked_rows(tokens):
            run(row)
        if args.token_out is not None:
            path = write_private(args.token_out, tokens.write.raw + "\n")
            print(f"write token left live and written to {path}")
        else:
            revoke_token(args.base, credential, tokens.write)
        sign_out(args.base, credential)
    for problem in rate_limit_checks(args.base):
        failures += 1
        print(f"FAIL {'RATE':6} {'':60} {problem}")
    print(f"\n{failures} failing check(s)")
    return failures


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
