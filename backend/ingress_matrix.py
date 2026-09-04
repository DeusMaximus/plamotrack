"""T2 — the ingress matrix, run against the packaged stack (design notes §5.5,
§5.8; M6-1, #186).

    uv run python ingress_matrix.py [BASE_URL] [--allowed-host NAME]
                                    [--setup-token TOKEN] [--password PASSWORD]

BASE_URL defaults to http://127.0.0.1:8080. `--allowed-host` names an entry the
stack's `.env` carries in ALLOWED_HOSTS, which enables T3's "a listed name" rows
at the ingress layer; CI sets `ci.plamotrack.test`.

Since the default-deny flip (M6-3, #188) the collection routes want a signed-in
owner, so the matrix signs in first when told how: `--setup-token` with
`--password` **claims** an unclaimed stack through `/api/auth/setup` — the token
is the one the API printed to its log, which is what CI reads out of
`docker compose logs api`, so the first-run path is exercised through the
packaged ingress; `--password` alone signs into a claimed instance through
`/api/auth/login`. Either way the positives then run cookie-borne, with the
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
            expected = {"/mcp/token": 401, "/mcp/auth/callback": 400}.get(path, 400)
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
            www_authenticate=(
                f'Bearer resource_metadata="{public_base_url}'
                '/.well-known/oauth-protected-resource/mcp/"'
                if mode == "oidc"
                else "Bearer"
            ),
        ),
    ]
    return rows


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
        # OIDC mode's routes exist in local mode too (#191) — registered and
        # answering 404 themselves, never the anonymous 401, so a mode is not a
        # challenge (§5.5). The callback carries no Location: a browser sent
        # here by a hostile page lands on the envelope, nowhere else.
        Row(
            "api/auth/oidc/start in local mode → 404",
            "POST",
            "/api/auth/oidc/start",
            404,
            headers={"Content-Type": "application/json", "Origin": f"http://localhost{port}"},
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
    args = parser.parse_args(argv)
    if args.setup_token is not None and args.password is None:
        parser.error("--setup-token needs --password (the password the claim sets)")
    if args.token_out is not None and args.password is None:
        parser.error("--token-out needs a signed-in owner (--password) to mint the token")

    credential = None
    tokens = None
    if args.password is not None:
        credential = sign_in(args.base, setup_token=args.setup_token, password=args.password)
        print(f"signed in as the owner ({'claimed' if args.setup_token else 'logged in'})")
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
    for row in family_8_rows(args.mode, (args.public_base_url or args.base).rstrip("/")):
        run(row)
    for row, resp in write_rows(args.base, args.allowed_host, credential):
        run(row, resp)
    if credential is not None and tokens is not None:
        for row in token_rows(args.base, tokens):
            run(row)
        revoke_token(args.base, credential, tokens.read)
        for row in revoked_rows(tokens):
            run(row)
        if args.token_out is not None:
            path = pathlib.Path(args.token_out)
            path.write_text(tokens.write.raw + "\n")
            path.chmod(0o600)
            print(f"write token left live and written to {path}")
        else:
            revoke_token(args.base, credential, tokens.write)
        sign_out(args.base, credential)
    print(f"\n{failures} failing check(s)")
    return failures


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
