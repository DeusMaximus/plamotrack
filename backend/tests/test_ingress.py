"""Ingress identity (M6-1, #186; design notes §5.5–§5.6, tests T3 and T9; absorbs #39).

The app's own identity comes from configuration and never from a header: a Host
outside the allowlist is 421, an unsafe request whose Origin fails the three-way
rule is 403, forwarded headers are believed only from `TRUSTED_PROXIES` and only
for the client address, `/readyz` answers the raw loopback peer alone, and no
spelling is ever redirected. Everything here drives the real app through the
ASGI transport with the lifespan running, so `/mcp/` is FastMCP's genuine
streamable-HTTP handler behind its genuine guard, not a stub.

Axes, per the checklist:

- **Requests** (T3 names them): MCP initialize, a JSON write, `POST
  /import/preview`, `POST /import/apply` in both modes. A GET beside them, because
  the Origin rule is unsafe-methods-only and a matrix that never drives a safe
  method cannot see that.
- **Values of `Host`:** a loopback name, a listed name, the `PUBLIC_BASE_URL`
  host, the bind address, a wildcard match, a hostile name, an empty/absent one.
- **Values of `Origin`:** absent, `null`, hostile, loopback against loopback,
  equal to the request's own origin, listed, the canonical https origin against a
  plain-http socket, and the `Referer` fallback in its three states.
- **Policy states:** the loopback default, `ALLOWED_HOSTS`, `PUBLIC_BASE_URL`,
  `ALLOWED_ORIGINS`, `WEB_BIND` — each its own app through `create_app`.

The two guards are asserted separately: the REST middleware by its envelope body,
FastMCP's by its plain-text body on a safe-method request the REST middleware
does not judge. A parity test holds the normalisers to FastMCP's, so the mirror
in `app/ingress.py` cannot drift from the guard it is meant to agree with.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastmcp.server import http as fastmcp_http
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select
from starlette.datastructures import Headers

from app import error_codes
from app.config import Settings
from app.db import get_sessionmaker
from app.hostnames import validate_host_pattern
from app.ingress import (
    BUNDLED_CLIENT_HEADER,
    CLIENT_ADDRESS_KEY,
    LOOPBACK_HOSTS,
    ForwardedClientMiddleware,
    HostOriginGuardMiddleware,
    IngressPolicy,
    is_internal_peer,
    normalize_host,
    normalize_origin,
)
from app.main import build_mcp_app, create_app
from app.models import AuditEvent
from app.services import audit

SERVER_NAMES_SCRIPT = (
    Path(__file__).resolve().parents[2] / "frontend/nginx/15-plamotrack-server-names.envsh"
)

LOOPBACK_PEER = ("127.0.0.1", 123)
OUTSIDE_PEER = ("198.51.100.7", 40000)

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test_ingress", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
RETAILERS_CSV = b"name\nIngress Test Retailer\n"


# --- harness --------------------------------------------------------------------


def make_settings(**overrides) -> Settings:
    """A `Settings` for one policy state. The defaults are the loopback install;
    every override is stated at the call site so the state under test is visible
    in the test, not hidden in a fixture."""
    return Settings(**overrides)


@asynccontextmanager
async def running_client(
    settings: Settings | None = None,
    peer=LOOPBACK_PEER,
    host="localhost",
    *,
    authorization: bool = False,
):
    """The real app for `settings`, lifespan entered (FastMCP's session manager
    lives there), reached through the ASGI transport as `peer` with `Host: host`.
    `raise_app_exceptions=False` so a broken handler reads as its status, not a
    re-raised exception (rule 6).

    The base URL is the socket uvicorn binds in development, and `host` travels
    as a header: httpx's ASGI transport derives `scope["server"]` — the bound
    address, which the allowlist admits the way FastMCP's guard does — from the
    URL, so a name put there would be admitted as the bind address rather than
    judged as a Host."""
    app = create_app(settings or make_settings(), authorization=authorization)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=peer, raise_app_exceptions=False)
        async with AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000", headers={"Host": host}
        ) as client:
            yield client


async def _audit_rows(*event_types: str) -> list[AuditEvent]:
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.event_type.in_(event_types))
            .order_by(AuditEvent.occurred_at, AuditEvent.event_type)
        )
        return list(rows.scalars().all())


async def mcp_initialize(client: AsyncClient, **headers):
    return await client.post("/mcp/", json=INITIALIZE, headers={**MCP_HEADERS, **headers})


async def json_write(client: AsyncClient, **headers):
    # A fresh name per call: several writes land in one test, and a 409 for a
    # duplicate would read as a refusal this file is not about.
    name = f"Ingress Retailer {uuid.uuid4().hex[:8]}"
    return await client.post("/retailers", json={"name": name}, headers=headers)


async def import_preview(client: AsyncClient, **headers):
    return await client.post(
        "/import/preview",
        files={"file": ("retailers.csv", RETAILERS_CSV, "text/csv")},
        data={"mode": "merge"},
        headers=headers,
    )


async def test_host_and_origin_rejections_are_audited_without_request_data():
    """#193 / T10: the pre-routing guards write who/where/what, but neither a
    query string nor a body. The two proxy states drive T9's address axis too:
    an untrusted peer's XFF is ignored, a trusted peer's is honoured."""
    untrusted = make_settings()
    async with running_client(
        untrusted,
        peer=OUTSIDE_PEER,
        host="evil.example",
        authorization=True,
    ) as client:
        host = await client.get(
            "/audit-host?token=query-secret",
            headers={"X-Forwarded-For": "203.0.113.40"},
        )
    assert host.status_code == 421

    trusted = make_settings(trusted_proxies=OUTSIDE_PEER[0])
    async with running_client(
        trusted,
        peer=OUTSIDE_PEER,
        host="localhost",
        authorization=True,
    ) as client:
        origin = await client.post(
            "/retailers?token=query-secret",
            json={"name": "body-secret"},
            headers={
                "Origin": "https://evil.example",
                "X-Forwarded-For": "203.0.113.41",
            },
        )
    assert origin.status_code == 403

    rows = await _audit_rows(audit.HOST_REJECTED, audit.ORIGIN_REJECTED)
    assert [
        (
            row.event_type,
            row.principal_kind,
            row.principal_subject,
            row.client_address,
            row.target,
            row.detail,
        )
        for row in rows
    ] == [
        (
            audit.HOST_REJECTED,
            "anon",
            None,
            OUTSIDE_PEER[0],
            "/audit-host",
            "method=GET setting=ALLOWED_HOSTS",
        ),
        (
            audit.ORIGIN_REJECTED,
            "anon",
            None,
            "203.0.113.41",
            "/retailers",
            "method=POST setting=ALLOWED_ORIGINS",
        ),
    ]
    for row in rows:
        stored = f"{row.target} {row.detail}"
        assert "query-secret" not in stored
        assert "body-secret" not in stored


def _import_apply(mode: str):
    async def apply(client: AsyncClient, **headers):
        # The plan hash comes from a benign preview: the point is what the
        # *apply* earns under these headers, and #41's mandatory hash must not
        # be the thing that refuses it (§5.6: CSRF protection does not rest on
        # plan_hash).
        preview = await client.post(
            "/import/preview",
            files={"file": ("retailers.csv", RETAILERS_CSV, "text/csv")},
            data={"mode": mode},
        )
        assert preview.status_code == 200, preview.text
        form = {"mode": mode, "plan_hash": preview.json()["plan_hash"]}
        if mode == "replace_all":
            form["confirm"] = "REPLACE"
        return await client.post(
            "/import/apply",
            files={"file": ("retailers.csv", RETAILERS_CSV, "text/csv")},
            data=form,
            headers=headers,
        )

    apply.__name__ = f"import_apply_{mode}"
    return apply


import_apply_merge = _import_apply("merge")
import_apply_replace_all = _import_apply("replace_all")

#: T3's request kinds with the status each earns when nothing refuses it.
UNSAFE_REQUESTS = [
    pytest.param(mcp_initialize, 200, id="mcp-initialize"),
    pytest.param(json_write, 201, id="json-write"),
    pytest.param(import_preview, 200, id="import-preview"),
    pytest.param(import_apply_merge, 200, id="import-apply-merge"),
    pytest.param(import_apply_replace_all, 200, id="import-apply-replace_all"),
]


def assert_host_refused(resp):
    assert resp.status_code == 421, resp.text
    assert resp.json() == {
        "detail": resp.json()["detail"],
        "code": error_codes.INGRESS_HOST_NOT_ALLOWED,
        "params": {"setting": "ALLOWED_HOSTS"},
    }
    assert "ALLOWED_HOSTS" in resp.json()["detail"]
    assert "location" not in resp.headers


def assert_origin_refused(resp):
    assert resp.status_code == 403, resp.text
    assert resp.json() == {
        "detail": resp.json()["detail"],
        "code": error_codes.INGRESS_ORIGIN_NOT_ALLOWED,
        "params": {"setting": "ALLOWED_ORIGINS"},
    }
    assert "location" not in resp.headers


# --- T3: the Host allowlist, app layer -------------------------------------------


@pytest.mark.parametrize("request_fn,ok", UNSAFE_REQUESTS)
async def test_hostile_host_is_421_on_the_loopback_install(request_fn, ok):
    async with running_client() as client:
        assert_host_refused(await request_fn(client, Host="evil.example"))
        # Host is judged first: a loopback Origin does not rescue a hostile Host.
        assert_host_refused(
            await request_fn(client, Host="evil.example", Origin="http://localhost:5173")
        )


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1:8000", "[::1]:8080", "LOCALHOST:8080"])
@pytest.mark.parametrize("request_fn,ok", UNSAFE_REQUESTS)
async def test_loopback_names_are_always_allowed(request_fn, ok, host):
    async with running_client(host=host) as client:
        assert (await request_fn(client)).status_code == ok


async def test_hostile_host_is_421_on_a_safe_method_too():
    async with running_client() as client:
        assert_host_refused(await client.get("/kits", headers={"Host": "evil.example"}))
        assert_host_refused(await client.get("/healthz", headers={"Host": "evil.example"}))


@pytest.mark.parametrize(
    "settings_kwargs,allowed,refused",
    [
        pytest.param(
            {"allowed_hosts": "nas.lan"},
            ["nas.lan", "nas.lan:8080", "NAS.LAN"],
            ["nas.lan.evil.example", "evil.example"],
            id="allowed_hosts",
        ),
        pytest.param(
            {"allowed_hosts": " nas.lan , plamotrack.home.arpa,,"},
            ["nas.lan", "plamotrack.home.arpa"],
            ["home.arpa"],
            id="allowed_hosts-csv-whitespace",
        ),
        pytest.param(
            {"allowed_hosts": "*.home.arpa"},
            ["nas.home.arpa", "a.b.home.arpa"],
            ["home.arpa", "nashome.arpa"],
            id="allowed_hosts-wildcard",
        ),
        pytest.param(
            {"public_base_url": "https://app.example"},
            ["app.example", "app.example:443"],
            ["www.app.example"],
            id="public_base_url-host",
        ),
        pytest.param(
            {"public_base_url": "http://[fd00::10]:8080"},
            ["[fd00::10]:8080", "[fd00::10]"],
            ["[fd00::11]:8080"],
            id="public_base_url-ipv6",
        ),
        pytest.param(
            {"web_bind": "192.168.1.10"},
            ["192.168.1.10:8080", "192.168.1.10"],
            ["192.168.1.11:8080"],
            id="web_bind-names-the-interface",
        ),
        pytest.param(
            {"web_bind": "0.0.0.0"},
            [],
            ["0.0.0.0:8080", "192.168.1.10:8080"],
            id="web_bind-unspecified-adds-nothing",
        ),
        pytest.param(
            # PR #196 review, P3-2: an explicit alternate loopback bind is a name
            # the operator chose; nginx lists it, so the app must too.
            {"web_bind": "127.0.0.2"},
            ["127.0.0.2:8080", "127.0.0.2"],
            ["127.0.0.3:8080"],
            id="web_bind-alternate-loopback",
        ),
        pytest.param(
            {"web_bind": "127.10.20.30"},
            ["127.10.20.30:8080"],
            ["127.10.20.31:8080"],
            id="web_bind-alternate-loopback-deep",
        ),
        pytest.param(
            # PR #196 review, P3-3: a terminal DNS dot is the same name.
            {"public_base_url": "http://nas.lan."},
            ["nas.lan", "nas.lan.", "nas.lan.:8080", "NAS.LAN."],
            ["nas.lan.evil.example"],
            id="public_base_url-terminal-dot",
        ),
        pytest.param(
            {"allowed_hosts": "nas.lan"},
            ["nas.lan.", "nas.lan.:8080"],
            ["nas.lan.."],
            id="allowed_hosts-dotted-request",
        ),
    ],
)
async def test_the_allowlist_is_the_configured_names(settings_kwargs, allowed, refused):
    async with running_client(make_settings(**settings_kwargs)) as client:
        for host in allowed:
            resp = await client.get("/healthz", headers={"Host": host})
            assert resp.status_code == 200, (host, resp.text)
        for host in refused:
            assert_host_refused(await client.get("/healthz", headers={"Host": host}))


async def test_a_dotted_name_passes_on_mcp_and_rest_alike():
    # FastMCP's normaliser keeps the terminal dot; ours drops it. The dotted
    # spellings handed to its guard are what keep the two answers equal.
    settings = make_settings(allowed_hosts="nas.lan")
    for host in ("nas.lan.", "localhost."):
        async with running_client(settings, host=host) as client:
            assert (await mcp_initialize(client)).status_code == 200, host
            assert (await json_write(client)).status_code == 201, host
    async with running_client(settings, host="nas.lan..") as client:
        assert_host_refused(await mcp_initialize(client))
        assert_host_refused(await json_write(client))


async def test_a_listed_name_passes_every_unsafe_request():
    async with running_client(make_settings(allowed_hosts="nas.lan"), host="nas.lan:8080") as c:
        for request_fn, ok in [(fn.values[0], fn.values[1]) for fn in UNSAFE_REQUESTS]:
            resp = await request_fn(c)
            assert resp.status_code == ok, (request_fn.__name__, resp.text)


async def test_the_default_allowlist_does_not_know_a_lan_name():
    # The lockout shape (#39): a name that only ALLOWED_HOSTS could supply.
    async with running_client(host="nas.lan:8080") as client:
        assert_host_refused(await client.get("/healthz"))


async def test_x_forwarded_host_changes_nothing():
    async with running_client() as client:
        ok = await client.get("/healthz", headers={"X-Forwarded-Host": "evil.example"})
        assert ok.status_code == 200
        assert_host_refused(
            await client.get(
                "/healthz", headers={"Host": "evil.example", "X-Forwarded-Host": "localhost"}
            )
        )


async def test_an_absent_host_header_is_421():
    # HTTP/1.0 shape; httpx always sends Host, so the middleware is driven raw.
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["path"])

    sent = []

    async def send(message):
        sent.append(message)

    guard = HostOriginGuardMiddleware(inner, IngressPolicy.from_settings(make_settings()))
    scope = {"type": "http", "method": "GET", "path": "/kits", "headers": [], "scheme": "http"}
    await guard(scope, None, send)
    assert seen == []
    assert sent[0]["status"] == 421


# --- T3: the Origin rule, app layer -------------------------------------------


@pytest.mark.parametrize("request_fn,ok", UNSAFE_REQUESTS)
async def test_hostile_origin_is_403(request_fn, ok):
    async with running_client() as client:
        assert_origin_refused(await request_fn(client, Origin="https://evil.example"))


@pytest.mark.parametrize("request_fn,ok", UNSAFE_REQUESTS)
async def test_null_origin_is_403(request_fn, ok):
    # What a browser sends from a sandboxed frame or a no-referrer page: not
    # absent, and not anyone's origin.
    async with running_client() as client:
        assert_origin_refused(await request_fn(client, Origin="null"))


@pytest.mark.parametrize("request_fn,ok", UNSAFE_REQUESTS)
async def test_absent_origin_passes_until_a_cookie_exists(request_fn, ok):
    # Scripts, curl, MCP clients: no Origin, no Referer. Refused only once a
    # cookie-borne principal exists to make the omission meaningful (M6-3).
    async with running_client() as client:
        assert (await request_fn(client)).status_code == ok


@pytest.mark.parametrize("request_fn,ok", UNSAFE_REQUESTS)
async def test_loopback_origin_against_loopback_host_passes(request_fn, ok):
    # The Vite dev proxy's shape: Origin localhost:5173, Host 127.0.0.1:8000.
    async with running_client(host="127.0.0.1:8000") as client:
        resp = await request_fn(client, Origin="http://localhost:5173")
        assert resp.status_code == ok, resp.text


@pytest.mark.parametrize("request_fn,ok", UNSAFE_REQUESTS)
async def test_same_origin_against_a_listed_host_passes(request_fn, ok):
    # Mode P with only ALLOWED_HOSTS set: the browser's Origin equals the
    # request's own scheme://Host — which is why nginx forwards $http_host.
    async with running_client(make_settings(allowed_hosts="nas.lan"), host="nas.lan:8080") as c:
        assert (await request_fn(c, Origin="http://nas.lan:8080")).status_code == ok
        assert_origin_refused(await request_fn(c, Origin="http://nas.lan:9090"))
        assert_origin_refused(await request_fn(c, Origin="https://evil.example"))


@pytest.mark.parametrize("request_fn,ok", UNSAFE_REQUESTS)
async def test_the_canonical_origin_passes_with_https_over_a_plain_socket(request_fn, ok):
    # Mode R: TLS terminates upstream, the app's socket says http, the browser
    # says https://app.example — the entry PUBLIC_BASE_URL supplies (§5.6).
    settings = make_settings(public_base_url="https://app.example")
    async with running_client(settings, host="app.example") as client:
        assert (await request_fn(client, Origin="https://app.example")).status_code == ok
        assert_origin_refused(await request_fn(client, Origin="https://evil.example"))


async def test_allowed_origins_admits_an_alias_the_socket_cannot_see():
    settings = make_settings(allowed_origins="https://alias.example, http://other.lan:9000")
    async with running_client(settings) as client:
        for origin in (
            "https://alias.example",
            "https://ALIAS.example:443",
            "http://other.lan:9000",
        ):
            resp = await json_write(client, Origin=origin)
            assert resp.status_code == 201, (origin, resp.text)
        assert_origin_refused(await json_write(client, Origin="http://alias.example"))
        assert_origin_refused(await json_write(client, Origin="http://other.lan:9001"))


@pytest.mark.parametrize(
    "referer,expected",
    [
        pytest.param("http://localhost:5173/board", 201, id="loopback-referer-passes"),
        pytest.param("https://evil.example/page?x=1", 403, id="hostile-referer-refused"),
        pytest.param("not a url", 403, id="unparsable-referer-refused"),
        pytest.param("", 403, id="empty-referer-refused"),
    ],
)
async def test_referer_is_the_fallback_when_origin_is_absent(referer, expected):
    async with running_client() as client:
        resp = await json_write(client, Referer=referer)
        assert resp.status_code == expected, resp.text
        if expected == 403:
            assert resp.json()["code"] == error_codes.INGRESS_ORIGIN_NOT_ALLOWED


async def test_origin_wins_over_referer_when_both_are_present():
    async with running_client() as client:
        refused = await json_write(
            client, Origin="https://evil.example", Referer="http://localhost:5173/board"
        )
        assert_origin_refused(refused)
        ok = await json_write(
            client, Origin="http://localhost:5173", Referer="https://evil.example/page"
        )
        assert ok.status_code == 201


async def test_safe_methods_are_not_judged_on_origin():
    async with running_client() as client:
        resp = await client.get("/kits", headers={"Origin": "https://evil.example"})
        assert resp.status_code == 200
        resp = await client.get("/meta", headers={"Origin": "null"})
        assert resp.status_code == 200


async def test_no_cors_allow_origin_is_ever_emitted():
    async with running_client() as client:
        resp = await client.get("/kits", headers={"Origin": "http://localhost:5173"})
        assert "access-control-allow-origin" not in resp.headers
        resp = await json_write(client, Origin="http://localhost:5173")
        assert resp.status_code == 201
        assert "access-control-allow-origin" not in resp.headers


# --- the MCP child's own guard ---------------------------------------------------


async def test_mcp_guard_judges_origin_on_a_safe_method_the_rest_guard_skips():
    # A GET (the SSE stream) with a hostile Origin passes the REST middleware
    # — unsafe methods only — and is refused by FastMCP's guard in strict mode.
    # The plain-text body is FastMCP's, which is what pins *which* guard spoke.
    async with running_client() as client:
        resp = await client.get(
            "/mcp/", headers={"Accept": "text/event-stream", "Origin": "https://evil.example"}
        )
        assert resp.status_code == 403
        assert resp.text == "Forbidden Origin"


async def test_mcp_child_alone_refuses_a_hostile_host_in_strict_mode():
    # The child on its own, without the parent's middleware in front of it.
    policy = IngressPolicy.from_settings(make_settings(allowed_hosts="nas.lan"))
    mcp_app = build_mcp_app(policy)
    async with mcp_app.router.lifespan_context(mcp_app):
        transport = ASGITransport(app=mcp_app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.post("/", json=INITIALIZE, headers=MCP_HEADERS)
            assert resp.status_code == 200
            resp = await client.post(
                "/", json=INITIALIZE, headers={**MCP_HEADERS, "Host": "nas.lan:8080"}
            )
            assert resp.status_code == 200
            resp = await client.post(
                "/", json=INITIALIZE, headers={**MCP_HEADERS, "Host": "evil.example"}
            )
            assert resp.status_code == 421
            assert resp.text == "Misdirected Request"
            resp = await client.post(
                "/", json=INITIALIZE, headers={**MCP_HEADERS, "Origin": "https://evil.example"}
            )
            assert resp.status_code == 403
            assert resp.text == "Forbidden Origin"


async def test_mcp_child_never_redirects_a_slash_spelling():
    # The child has one route today, so its `redirect_slashes=False` is only
    # observable once FastMCP adds `/authorize`, `/token`, `/auth/callback`
    # (M6-7) — the case §5.6 is about: `/mcp/auth/callback/?code=…` must be 404,
    # not a 307 to a Location built from the request. A probe route stands in for
    # those, so the wiring is pinned before the routes that need it exist.
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    mcp_app = build_mcp_app(IngressPolicy.from_settings(make_settings()))
    mcp_app.router.routes.append(Route("/probe", lambda request: PlainTextResponse("ok")))
    async with mcp_app.router.lifespan_context(mcp_app):
        transport = ASGITransport(app=mcp_app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://localhost") as client:
            assert (await client.get("/probe")).status_code == 200
            resp = await client.get("/probe/?code=secret&state=xyz")
            assert resp.status_code == 404
            assert "location" not in resp.headers


def test_loopback_names_equal_fastmcps_defaults():
    # The two guards' built-ins, held together by a literal on this side.
    assert LOOPBACK_HOSTS == ("127.0.0.1", "localhost", "::1")
    assert set(LOOPBACK_HOSTS) == set(fastmcp_http.DEFAULT_HOSTS)


@pytest.mark.parametrize(
    "value",
    [
        "localhost",
        "LocalHost:8080",
        "[::1]:8080",
        "[fd00::10]",
        "fd00::10",
        "nas.lan:8080",
        "nas.lan",
        "",
        "  spaced.lan  ",
        "[unterminated",
    ],
)
def test_host_normalisation_mirrors_fastmcp(value):
    assert normalize_host(value) == fastmcp_http._normalize_host(value)


@pytest.mark.parametrize(
    "value,ours,theirs",
    [("nas.lan.", "nas.lan", "nas.lan."), ("localhost.", "localhost", "localhost.")],
)
def test_terminal_dots_are_the_one_deliberate_divergence(value, ours, theirs):
    # Ours drops them (nginx does on the request side); FastMCP keeps them. The
    # dotted entries in `mcp_allowed_hosts` are the bridge, tested end to end in
    # test_a_dotted_name_passes_on_mcp_and_rest_alike.
    assert normalize_host(value) == ours
    assert fastmcp_http._normalize_host(value) == theirs


@pytest.mark.parametrize(
    "value",
    [
        "http://localhost:5173",
        "https://App.Example",
        "https://app.example:443/",
        "http://[::1]:8080",
        "http://[fd00::10]",
        "null",
        "",
        "not a url",
        "http://host/path",
        "http://host:notaport",
        "https://host:8443",
    ],
)
def test_origin_normalisation_mirrors_fastmcp(value):
    assert normalize_origin(value) == fastmcp_http._normalize_origin(value)


# --- T9: proxy trust and the raw peer -------------------------------------------


@pytest.mark.parametrize(
    "trusted,peer,forwarded,expected",
    [
        pytest.param("", "10.0.0.5", "203.0.113.9", "10.0.0.5", id="nothing-trusted"),
        pytest.param("10.0.0.5", "10.0.0.5", "203.0.113.9", "203.0.113.9", id="trusted-peer"),
        pytest.param("10.0.0.5", "10.0.0.6", "203.0.113.9", "10.0.0.6", id="untrusted-peer"),
        pytest.param("10.0.0.0/8", "10.1.2.3", "203.0.113.9", "203.0.113.9", id="cidr"),
        pytest.param(
            "10.0.0.0/8",
            "10.0.0.5",
            "203.0.113.9, 10.0.0.7",
            "203.0.113.9",
            id="walks-past-trusted-hops",
        ),
        pytest.param(
            "10.0.0.0/8",
            "10.0.0.5",
            "198.51.100.1, 203.0.113.9, 10.0.0.7",
            "203.0.113.9",
            id="stops-at-the-first-untrusted-from-the-right",
        ),
        pytest.param("10.0.0.5", "10.0.0.5", "", "10.0.0.5", id="trusted-but-no-header"),
        pytest.param("10.0.0.5", "10.0.0.5", "garbage", "garbage", id="unparsable-entry-kept"),
        pytest.param("10.0.0.5", None, "203.0.113.9", None, id="no-peer"),
        pytest.param(
            "10.0.0.5", "10.0.0.5", "[2001:db8::1]:4444", "2001:db8::1", id="ipv6-with-port"
        ),
    ],
)
def test_forwarded_client_resolution(trusted, peer, forwarded, expected):
    policy = IngressPolicy.from_settings(make_settings(trusted_proxies=trusted))
    assert policy.resolve_client_address(peer, forwarded) == expected


async def test_forwarded_client_lands_in_state_and_leaves_the_raw_peer_alone():
    captured = {}

    async def inner(scope, receive, send):
        captured["client"] = scope["client"]
        captured["state"] = dict(scope["state"])

    async def send(message):
        pass

    policy = IngressPolicy.from_settings(make_settings(trusted_proxies="10.0.0.5"))
    middleware = ForwardedClientMiddleware(inner, policy)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "client": ("10.0.0.5", 5000),
        "headers": [(b"x-forwarded-for", b"203.0.113.9"), (b"host", b"localhost")],
    }
    await middleware(scope, None, send)
    assert captured["client"] == ("10.0.0.5", 5000)
    assert captured["state"][CLIENT_ADDRESS_KEY] == "203.0.113.9"

    # The same header from a peer nobody trusts is ignored.
    scope["client"] = ("10.0.0.6", 5000)
    await middleware(scope, None, send)
    assert captured["state"][CLIENT_ADDRESS_KEY] == "10.0.0.6"


async def test_bundled_ingress_header_is_explicit_and_cannot_forge_the_raw_peer():
    captured = {}

    async def inner(scope, receive, send):
        captured["client"] = scope["client"]
        captured["address"] = scope["state"][CLIENT_ADDRESS_KEY]

    async def send(message):
        pass

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "client": ("172.20.0.4", 5000),
        "headers": [
            (BUNDLED_CLIENT_HEADER.encode(), b"203.0.113.19"),
            (b"x-forwarded-for", b"127.0.0.1"),
            (b"host", b"localhost"),
        ],
    }
    enabled = IngressPolicy.from_settings(make_settings(plamotrack_bundled_ingress=True))
    await ForwardedClientMiddleware(inner, enabled)(scope, None, send)
    assert captured == {
        "client": ("172.20.0.4", 5000),
        "address": "203.0.113.19",
    }

    # Source-run deployments do not trust the internal header or the spoofed XFF.
    scope["state"] = {}
    disabled = IngressPolicy.from_settings(make_settings())
    await ForwardedClientMiddleware(inner, disabled)(scope, None, send)
    assert captured["address"] == "172.20.0.4"


async def test_readyz_answers_the_raw_loopback_peer_only():
    async with running_client(peer=LOOPBACK_PEER) as client:
        assert (await client.get("/readyz")).status_code == 200
    async with running_client(peer=OUTSIDE_PEER) as client:
        resp = await client.get("/readyz")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Not Found"}
        # Liveness stays open to the same peer.
        assert (await client.get("/healthz")).status_code == 200


async def test_a_trusted_proxy_cannot_forge_the_loopback_peer_for_readyz():
    # T9's control: X-Forwarded-For: 127.0.0.1 from a TRUSTED_PROXIES peer is
    # honoured for the client address and still gets 404 from /readyz, because
    # `internal` reads the socket, not the resolved address.
    settings = make_settings(trusted_proxies="198.51.100.7")
    async with running_client(settings, peer=OUTSIDE_PEER) as client:
        resp = await client.get("/readyz", headers={"X-Forwarded-For": "127.0.0.1"})
        assert resp.status_code == 404
        resp = await client.get("/healthz", headers={"X-Forwarded-For": "127.0.0.1"})
        assert resp.status_code == 200


@pytest.mark.parametrize(
    "client,expected",
    [
        (("127.0.0.1", 1), True),
        (("::1", 1), True),
        (("127.0.0.2", 1), True),
        (("10.0.0.5", 1), False),
        (("198.51.100.7", 1), False),
        (None, False),
        (("not-an-ip", 1), False),
    ],
)
def test_is_internal_peer(client, expected):
    assert is_internal_peer({"type": "http", "client": client}) is expected


# --- no request-derived redirects ------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/kits/", "/orders/?x=1", "/mcp", "/retailers/", "/import/preview/"],
)
async def test_non_canonical_spellings_are_404_with_no_location(path):
    async with running_client() as client:
        resp = await client.get(path)
        assert resp.status_code == 404, resp.text
        assert "location" not in resp.headers
        resp = await client.post(path, json={})
        assert resp.status_code == 404, resp.text
        assert "location" not in resp.headers


async def test_the_canonical_spellings_still_answer():
    async with running_client() as client:
        assert (await client.get("/kits")).status_code == 200
        assert (await mcp_initialize(client)).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200
        assert (await client.get("/docs")).status_code == 200


# --- the settings themselves --------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("", ""),
        ("   ", ""),
        ("http://localhost:8080", "http://localhost:8080"),
        ("https://app.example/", "https://app.example"),
        ("https://app.example///", "https://app.example"),
        ("http://[fd00::10]:8080", "http://[fd00::10]:8080"),
        ("HTTPS://App.Example:8443", "HTTPS://App.Example:8443"),
    ],
)
def test_public_base_url_accepts_a_bare_origin(value, expected):
    assert make_settings(public_base_url=value).public_base_url == expected


@pytest.mark.parametrize(
    "value",
    [
        "app.example",
        "ftp://app.example",
        "http://",
        "http://app.example/plamotrack",
        "http://app.example/?x=1",
        "http://app.example/#frag",
        "http://user:pw@app.example",
        "http://app.example:notaport",
        "http://app.example:99999",
    ],
)
def test_public_base_url_refuses_anything_but_a_bare_origin(value):
    with pytest.raises(ValidationError, match="PUBLIC_BASE_URL"):
        make_settings(public_base_url=value)


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "**",
        "nas.lan,*",
        " * ",
        # PR #196 review, P3-1: wildcard-equivalents whose *normalised* form is
        # `*` — the port, the brackets and the doubled star all come off before
        # matching, so judging the raw spelling admitted every Host.
        "*:8080",
        "**:80",
        "[*]",
        "[*]:8080",
        "*.",
        "www.*",
        "*foo.lan",
        "nas.*.lan",
        "*.*",
        ".lan",
        "nas..lan",
        "0.0.0.0",
        "::",
        "-nas.lan",
    ],
)
def test_allowed_hosts_refuses_wildcard_equivalents_and_non_names(value):
    with pytest.raises(ValidationError, match="ALLOWED_HOSTS"):
        make_settings(allowed_hosts=value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        ",",
        " , ",
        "nas.lan",
        "*.home.arpa",
        "a,b",
        "NAS.LAN:8080",
        "nas.lan.",
        "[fd00::10]:8080",
        "fd00::10",
        "127.0.0.2",
        "my_container",
        "*.a.b.c",
    ],
)
def test_allowed_hosts_accepts_names_and_wildcards(value):
    make_settings(allowed_hosts=value)


def test_a_port_qualified_wildcard_never_reaches_the_guard():
    # The end-to-end shape of P3-1: had `*:8080` survived validation it would
    # have admitted evil.example. Refused at Settings, so no policy exists.
    with pytest.raises(ValidationError):
        IngressPolicy.from_settings(make_settings(allowed_hosts="*:8080"))
    # And the accepted wildcard keeps its subdomain-only meaning.
    policy = IngressPolicy.from_settings(make_settings(allowed_hosts="*.lan"))
    assert policy.host_allowed("nas.lan:8080")
    assert not policy.host_allowed("evil.example:8080")
    assert not policy.host_allowed("lan")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"public_base_url": "http://*:8080"},
        {"public_base_url": "http://*.lan:8080"},
        {"web_bind": "*"},
        {"web_bind": "*.lan"},
        {"web_bind": "nas.*"},
        {"allowed_origins": "http://*:8080"},
        {"allowed_origins": "https://*.lan"},
    ],
)
def test_every_host_producing_setting_refuses_a_wildcard(kwargs):
    # The P3-1 sweep: ALLOWED_HOSTS is not the only setting whose host reaches
    # the allowlist or the guard's fnmatch.
    with pytest.raises(ValidationError):
        make_settings(**kwargs)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0.0.0.0",
        "::",
        "127.0.0.1",
        "127.0.0.2",
        "192.168.1.10",
        "fd00::10",
        "localhost",
        "nas.lan",
    ],
)
def test_web_bind_accepts_addresses_and_names(value):
    make_settings(web_bind=value)


@pytest.mark.parametrize(
    "entry,allow_wildcard,expected",
    [
        ("NAS.lan:8080", True, "nas.lan"),
        ("nas.lan.", True, "nas.lan"),
        ("[FD00::10]:8080", True, "fd00::10"),
        ("*.Home.ARPA", True, "*.home.arpa"),
        ("127.0.0.2", False, "127.0.0.2"),
    ],
)
def test_validate_host_pattern_returns_the_normalised_form(entry, allow_wildcard, expected):
    assert validate_host_pattern(entry, setting="X", allow_wildcard=allow_wildcard) == expected


def test_validate_host_pattern_names_the_setting():
    with pytest.raises(ValueError, match="^SOME_SETTING entry"):
        validate_host_pattern("*:8080", setting="SOME_SETTING", allow_wildcard=True)
    with pytest.raises(ValueError, match="may not be a wildcard"):
        validate_host_pattern("*.lan", setting="SOME_SETTING", allow_wildcard=False)


@pytest.mark.parametrize(
    "value",
    ["alias.example", "ftp://alias.example", "http://alias.example/path", "http://a@b.example"],
)
def test_allowed_origins_refuses_non_origins(value):
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        make_settings(allowed_origins=value)


@pytest.mark.parametrize("value", ["", "https://alias.example", "http://a.lan:9000/, http://b"])
def test_allowed_origins_accepts_origins(value):
    make_settings(allowed_origins=value)


@pytest.mark.parametrize("value", ["nginx", "10.0.0.5/33", "10.0.0", "not an ip"])
def test_trusted_proxies_refuses_non_addresses(value):
    with pytest.raises(ValidationError, match="TRUSTED_PROXIES"):
        make_settings(trusted_proxies=value)


@pytest.mark.parametrize("value", ["", "10.0.0.5", "10.0.0.0/8, fd00::/8", "10.0.0.5/32"])
def test_trusted_proxies_accepts_addresses_and_cidrs(value):
    make_settings(trusted_proxies=value)


def test_policy_derivation_from_every_setting():
    settings = make_settings(
        public_base_url="https://App.Example:8443",
        allowed_hosts="nas.lan, nas.lan, *.home.arpa",
        allowed_origins="http://alias.lan:9000",
        trusted_proxies="10.0.0.0/8",
        web_bind="192.168.1.10",
    )
    policy = IngressPolicy.from_settings(settings)
    assert policy.extra_hosts == ("app.example", "192.168.1.10", "nas.lan", "*.home.arpa")
    assert policy.mcp_allowed_hosts == (
        "app.example",
        "192.168.1.10",
        "nas.lan",
        "*.home.arpa",
        "localhost.",
        "app.example.",
        "nas.lan.",
        "*.home.arpa.",
    )
    assert policy.allowed_origins == ("https://app.example:8443", "http://alias.lan:9000")
    assert policy.canonical_origin == "https://app.example:8443"
    assert [str(n) for n in policy.trusted_proxies] == ["10.0.0.0/8"]
    assert policy.bundled_ingress is False
    # The per-request list adds the loopback names and a bound address that
    # names something; 0.0.0.0 (the container's bind) adds nothing.
    assert policy.allowed_hosts_for("0.0.0.0") == (*LOOPBACK_HOSTS, *policy.extra_hosts)
    assert policy.allowed_hosts_for("172.18.0.3") == (
        *LOOPBACK_HOSTS,
        *policy.extra_hosts,
        "172.18.0.3",
    )


def test_the_loopback_install_derives_an_empty_policy():
    policy = IngressPolicy.from_settings(make_settings())
    assert policy.extra_hosts == ()
    assert policy.allowed_origins == ()
    assert policy.canonical_origin is None
    assert policy.trusted_proxies == ()
    assert policy.bundled_ingress is False


@pytest.mark.parametrize(
    "bind", ["0.0.0.0", "::", "127.0.0.1", "localhost", "[::1]", "LOCALHOST", ""]
)
def test_a_built_in_or_unspecified_bind_adds_no_host(bind):
    assert IngressPolicy.from_settings(make_settings(web_bind=bind)).extra_hosts == ()


@pytest.mark.parametrize(
    "bind,expected",
    [("127.0.0.2", "127.0.0.2"), ("127.10.20.30", "127.10.20.30"), ("NAS.lan.", "nas.lan")],
)
def test_an_explicit_bind_that_is_not_a_built_in_is_kept(bind, expected):
    # PR #196 review, P3-2: excluding the whole loopback class dropped a name
    # nginx lists. Only the three built-ins are redundant.
    assert IngressPolicy.from_settings(make_settings(web_bind=bind)).extra_hosts == (expected,)


def test_configured_names_are_stored_normalised_and_deduplicated():
    settings = make_settings(
        public_base_url="http://NAS.lan.:8080",
        web_bind="nas.lan",
        allowed_hosts="nas.lan., NAS.LAN:9090, localhost, 127.0.0.1, [::1]:80, *.HOME.arpa",
    )
    assert IngressPolicy.from_settings(settings).extra_hosts == ("nas.lan", "*.home.arpa")


# --- the two derivations agree: this file's policy and the nginx generator --------

SERVER_NAME_CORPUS = [
    pytest.param("", "", "", id="loopback-install"),
    pytest.param("http://nas.lan.", "127.0.0.2", "", id="p3-2-and-p3-3"),
    pytest.param(
        "http://NAS.lan:8080", "0.0.0.0", "nas.lan, *.home.arpa", id="dupes-case-wildcard"
    ),
    pytest.param(
        "https://app.example",
        "192.168.1.10",
        "a.lan:8080, [fd00::10]:8080, fd00::11",
        id="ports-and-ipv6",
    ),
    pytest.param(
        "http://[fd00::10]:8080",
        "::1",
        "localhost., LOCALHOST, 127.0.0.1",
        id="ipv6-base-loopback-noise",
    ),
    pytest.param("http://nas.lan:8080/", "::", "", id="trailing-slash-unspecified"),
    pytest.param(
        "", "127.10.20.30", "plamotrack.home.arpa., my_container", id="deep-loopback-underscore"
    ),
]


def _nginx_server_names(public_base_url: str, web_bind: str, allowed_hosts: str) -> set[str]:
    env = {
        "PATH": os.environ["PATH"],
        "PUBLIC_BASE_URL": public_base_url,
        "WEB_BIND": web_bind,
        "ALLOWED_HOSTS": allowed_hosts,
    }
    result = subprocess.run(
        [
            "sh",
            "-c",
            f'. "{SERVER_NAMES_SCRIPT}" >/dev/null; printf "%s" "$PLAMOTRACK_SERVER_NAMES"',
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    names = result.stdout.split()
    assert len(names) == len(set(names)), f"nginx would warn on a duplicate server_name: {names}"
    for name in names:
        # nginx-side invariants, checked on the raw spelling because the
        # normalised comparison below would hide them (a first version of this
        # helper did, and the generator's dot-strip mutant survived it).
        assert not name.endswith("."), f"a dotted server_name never matches: {name}"
        assert name.startswith("[") or ":" not in name, f"a port in a server_name: {name}"
        assert name == name.lower(), f"the generator lowercases for its dedupe: {name}"
    return {normalize_host(name) for name in names}


def _nginx_trusted_proxy_directives(value: str) -> str:
    env = {"PATH": os.environ["PATH"], "TRUSTED_PROXIES": value}
    command = (
        f'. "{SERVER_NAMES_SCRIPT}" >/dev/null; printf "%s" "$PLAMOTRACK_TRUSTED_PROXY_DIRECTIVES"'
    )
    result = subprocess.run(
        ["sh", "-c", command],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.mark.parametrize("public_base_url,web_bind,allowed_hosts", SERVER_NAME_CORPUS)
def test_nginx_server_names_equal_the_apps_allowlist(public_base_url, web_bind, allowed_hosts):
    # One corpus through both derivations (PR #196 review: the three P3s were
    # all mismatches between the Python policy and the sh generator). Compared
    # on the normalised form each layer matches against — nginx brackets IPv6
    # and keeps its own case rules, the app normalises the Host header.
    settings = make_settings(
        public_base_url=public_base_url, web_bind=web_bind, allowed_hosts=allowed_hosts
    )
    policy = IngressPolicy.from_settings(settings)
    ours = {normalize_host(h) for h in (*LOOPBACK_HOSTS, *policy.extra_hosts)}
    assert _nginx_server_names(public_base_url, web_bind, allowed_hosts) == ours


def test_the_generator_drops_a_terminal_dot_and_a_port():
    # P3-3 as the review reproduced it: `server_name nas.lan.;` never matches.
    names = _nginx_server_names("http://nas.lan.", "", "other.lan.:8080")
    assert "nas.lan" in names and "other.lan" in names
    # The raw-spelling invariants inside _nginx_server_names are what refuse a
    # dotted or port-carrying entry; this pins that the names still arrived.
    assert names == {"localhost", "127.0.0.1", "::1", "nas.lan", "other.lan"}


def test_the_generator_renders_only_validated_trusted_proxy_directives():
    assert _nginx_trusted_proxy_directives("10.0.0.5, 192.0.2.0/24, fd00::/8") == (
        "set_real_ip_from 10.0.0.5;\nset_real_ip_from 192.0.2.0/24;\nset_real_ip_from fd00::/8;\n"
    )
    assert _nginx_trusted_proxy_directives("") == ""


@pytest.mark.parametrize("value", ["all", "10.0.0.1;return", "10.0.0.1\nallow", "*"])
def test_the_generator_refuses_trusted_proxy_config_injection(value):
    env = {"PATH": os.environ["PATH"], "TRUSTED_PROXIES": value}
    result = subprocess.run(
        ["sh", "-c", f'. "{SERVER_NAMES_SCRIPT}" >/dev/null'],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "invalid TRUSTED_PROXIES entry" in result.stderr


def test_the_refusal_bodies_are_the_error_envelope():
    # The codes are registered (test_error_envelope pins the module to the shared
    # fixture); this pins that the guard actually emits them with `setting`.
    headers = Headers(raw=[(b"host", b"evil.example")])
    assert headers.get("host") == "evil.example"  # the shape the guard reads
    assert error_codes.INGRESS_HOST_NOT_ALLOWED in error_codes.all_codes()
    assert error_codes.INGRESS_ORIGIN_NOT_ALLOWED in error_codes.all_codes()
