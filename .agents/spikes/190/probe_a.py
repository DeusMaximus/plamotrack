"""#190 spike, phase A — local probe of the pinned FastMCP OAuth proxy.

No network: OAuthProxy with explicit upstream endpoints, in-memory store.
Mounted the way app/main.py mounts the child (create_streamable_http_app,
streamable_http_path="/", redirect_slashes off) at /mcp on a parent whose
root carries get_well_known_routes("/") minus the bare openid document.
Records: route tables, response profile per route, redirect binding per
client kind, Location host provenance, store collections, key derivation.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.http import create_streamable_http_app
from key_value.aio.stores.memory import MemoryStore
from starlette.applications import Starlette
from starlette.routing import Mount, Route

BASE = "http://127.0.0.1:8000"
UPSTREAM_ID = "upstream-client-id"
OUT: dict = {}


class NullVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        return None


class PinnedProxy(OAuthProxy):
    """Thin constraint: refuse the synthesised upstream-id client."""

    async def get_client(self, client_id: str):
        if client_id == self._upstream_client_id:
            return None
        return await super().get_client(client_id)


def make_proxy(cls=OAuthProxy, allowlist=None, **kw):
    kw.setdefault("jwt_signing_key", os.urandom(32))
    kw.setdefault("base_url", f"{BASE}/mcp")
    return cls(
        upstream_authorization_endpoint="https://idp.example/authorize",
        upstream_token_endpoint="https://idp.example/token",
        upstream_revocation_endpoint="https://idp.example/revoke",
        upstream_client_id=UPSTREAM_ID,
        upstream_client_secret="s" * 40,
        token_verifier=NullVerifier(required_scopes=["collection:read"]),
        valid_scopes=["collection:read", "collection:write"],
        client_storage=MemoryStore(),
        allowed_client_redirect_uris=allowlist,
        **kw,
    )


def route_table(routes):
    return [
        (r.path, sorted(r.methods or []) if isinstance(r, Route) else "MOUNT")
        for r in routes
    ]


def build_app(proxy, install_bare_openid=False):
    child = create_streamable_http_app(
        server=FastMCP("probe"),
        streamable_http_path="/",
        auth=proxy,
        json_response=True,
        stateless_http=True,
    )
    child.router.redirect_slashes = False
    raw_child = route_table(child.router.routes)
    # prune the child's /.well-known/* aliases (design §5.5 family 8)
    child.router.routes[:] = [
        r
        for r in child.router.routes
        if not (isinstance(r, Route) and r.path.startswith("/.well-known/"))
    ]
    well_known = proxy.get_well_known_routes("/")
    raw_well_known = route_table(well_known)
    parent_routes = [
        r
        for r in well_known
        if install_bare_openid or r.path != "/.well-known/openid-configuration"
    ]
    parent = Starlette(routes=[*parent_routes, Mount("/mcp", app=child)])
    parent.router.redirect_slashes = False
    return parent, child, raw_child, raw_well_known


def profile(resp: httpx.Response):
    h = resp.headers
    cookies = [c.split(";")[0].split("=")[0] + " [" + ";".join(
        a.strip() for a in c.split(";")[1:]) + "]" for c in h.get_list("set-cookie")]
    return {
        "status": resp.status_code,
        "cache": h.get("cache-control"),
        "ctype": (h.get("content-type") or "").split(";")[0],
        "location": h.get("location"),
        "www_auth": h.get("www-authenticate"),
        "allow": h.get("allow"),
        "acao": h.get("access-control-allow-origin"),
        "cookies": cookies,
    }


async def register(client, redirect_uris, **extra):
    r = await client.post(
        "/mcp/register",
        json={"redirect_uris": redirect_uris, "token_endpoint_auth_method": "none", **extra},
    )
    return r


async def authorize(client, client_id, redirect_uri, **extra):
    q = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256",
        "state": "client-state-123",
        **extra,
    }
    return await client.get("/mcp/authorize?" + urlencode(q))


async def phase_routes_and_profile():
    proxy = make_proxy()
    parent, child, raw_child, raw_wk = build_app(proxy)
    OUT["child_routes_raw"] = raw_child
    OUT["child_routes_after_prune"] = route_table(child.router.routes)
    OUT["well_known_routes_raw"] = raw_wk
    OUT["parent_routes_installed"] = route_table(
        [r for r in parent.router.routes if isinstance(r, Route)]
    )
    async with child.router.lifespan_context(child):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=parent), base_url=BASE
        ) as c:
            P = OUT["profile"] = {}
            for path in [
                "/.well-known/oauth-protected-resource/mcp/",
                "/.well-known/oauth-protected-resource/mcp",
                "/.well-known/oauth-authorization-server/mcp",
                "/.well-known/oauth-authorization-server/mcp/",
                "/.well-known/oauth-authorization-server",
                "/.well-known/openid-configuration/mcp",
                "/.well-known/openid-configuration",
                "/mcp/.well-known/oauth-authorization-server",
                "/mcp/.well-known/oauth-protected-resource/mcp/",
                "/mcp/.well-known/openid-configuration",
            ]:
                r = await c.get(path)
                P[f"GET {path}"] = profile(r)
                if r.status_code == 200:
                    P[f"GET {path}"]["body"] = r.json()
            r = await c.options(
                "/.well-known/oauth-authorization-server/mcp",
                headers={"Origin": "https://inspector.example", "Access-Control-Request-Method": "GET"},
            )
            P["OPTIONS /.well-known/oauth-authorization-server/mcp (CORS preflight)"] = profile(r)

            # transport without bearer
            r = await c.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
            P["POST /mcp/ (no bearer)"] = profile(r)
            r = await c.post("/mcp", json={})
            P["POST /mcp (bare, source-run)"] = profile(r)

            # authorize: no params / unknown client
            P["GET /mcp/authorize (no params)"] = profile(await c.get("/mcp/authorize"))
            r = await authorize(c, "no-such-client", "http://localhost:3000/cb")
            P["GET /mcp/authorize (unknown client_id)"] = profile(r)
            P["GET /mcp/authorize/ (trailing slash)"] = profile(
                await c.get("/mcp/authorize/?client_id=x&redirect_uri=http://localhost/cb")
            )
            P["PUT /mcp/authorize"] = profile(await c.put("/mcp/authorize"))

            # register
            r = await register(c, ["http://localhost:3000/cb"])
            P["POST /mcp/register"] = profile(r)
            reg = r.json()
            OUT["registration_response_keys"] = sorted(reg)
            cid = reg["client_id"]
            P["OPTIONS /mcp/register (CORS)"] = profile(
                await c.options("/mcp/register", headers={"Origin": "https://inspector.example", "Access-Control-Request-Method": "POST"})
            )
            P["GET /mcp/register"] = profile(await c.get("/mcp/register"))

            # authorize happy path -> consent
            r = await authorize(c, cid, "http://localhost:3000/cb")
            P["GET /mcp/authorize (registered, -> consent)"] = profile(r)
            loc = r.headers.get("location", "")
            txn = parse_qs(urlparse(loc).query).get("txn_id", [None])[0]
            OUT["consent_location_shape"] = loc.replace(txn or "", "<txn>")
            # Host / X-Forwarded-Host provenance on the self redirect
            r2 = await authorize(c, cid, "http://localhost:3000/cb")
            r3 = await c.get(
                "/mcp/authorize?" + urlencode({
                    "response_type": "code", "client_id": cid,
                    "redirect_uri": "http://localhost:3000/cb",
                    "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                    "code_challenge_method": "S256", "state": "s"}),
                headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https"},
            )
            OUT["self_redirect_host_provenance"] = {
                "normal": urlparse(r2.headers["location"]).netloc,
                "hostile Host + XFH": urlparse(r3.headers["location"]).netloc if "location" in r3.headers else r3.status_code,
            }

            # consent GET (needs the txn cookie? try bare and with cookies from authorize)
            r = await c.get(f"/mcp/consent?txn_id={txn}")
            P["GET /mcp/consent (with cookie jar from authorize)"] = profile(r)
            OUT["consent_html_has_csp_meta"] = "Content-Security-Policy" in r.text
            OUT["consent_html_has_frame_headers"] = {
                k: r.headers.get(k) for k in ["x-frame-options", "content-security-policy", "x-content-type-options"]
            }
            fresh = httpx.AsyncClient(transport=httpx.ASGITransport(app=parent), base_url=BASE)
            P["GET /mcp/consent (no cookie)"] = profile(await fresh.get(f"/mcp/consent?txn_id={txn}"))
            P["GET /mcp/consent (no txn)"] = profile(await fresh.get("/mcp/consent"))
            await fresh.aclose()
            # consent POST: deny, with csrf from the page
            import re
            m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
            csrf = m.group(1) if m else ""
            r = await c.post("/mcp/consent", data={"txn_id": txn, "csrf_token": csrf, "action": "deny"})
            P["POST /mcp/consent (deny)"] = profile(r)
            OUT["deny_location"] = r.headers.get("location")
            r = await c.post("/mcp/consent", data={"txn_id": txn, "csrf_token": "bad", "action": "approve"})
            P["POST /mcp/consent (bad csrf)"] = profile(r)
            # approve on a fresh txn -> upstream redirect
            r = await authorize(c, cid, "http://localhost:3000/cb")
            txn2 = parse_qs(urlparse(r.headers["location"]).query)["txn_id"][0]
            page = await c.get(f"/mcp/consent?txn_id={txn2}")
            csrf2 = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            r = await c.post("/mcp/consent", data={"txn_id": txn2, "csrf_token": csrf2, "action": "approve"})
            P["POST /mcp/consent (approve -> upstream)"] = profile(r)
            up = urlparse(r.headers.get("location", ""))
            upq = parse_qs(up.query)
            OUT["upstream_redirect"] = {
                "endpoint": f"{up.scheme}://{up.netloc}{up.path}",
                "redirect_uri": upq.get("redirect_uri"),
                "params": sorted(upq),
                "resource": upq.get("resource"),
                "scope": upq.get("scope"),
            }

            # callback
            P["GET /mcp/auth/callback (no params)"] = profile(await c.get("/mcp/auth/callback"))
            r = await c.get(f"/mcp/auth/callback?error=access_denied&state={txn2}")
            P["GET /mcp/auth/callback (error, valid txn -> client)"] = profile(r)
            P["GET /mcp/auth/callback (error, unknown txn)"] = profile(
                await c.get("/mcp/auth/callback?error=access_denied&state=nope")
            )
            P["GET /mcp/auth/callback/ (trailing slash + code)"] = profile(
                await c.get("/mcp/auth/callback/?code=x&state=y")
            )
            P["GET /mcp/auth/callback (code, unknown txn)"] = profile(
                await c.get("/mcp/auth/callback?code=x&state=nope")
            )

            # token / revoke
            r = await c.post("/mcp/token", data={"grant_type": "authorization_code", "code": "bad", "client_id": cid, "redirect_uri": "http://localhost:3000/cb", "code_verifier": "v" * 43})
            P["POST /mcp/token (bad code)"] = profile(r)
            OUT["token_bad_code_body"] = r.json()
            r = await c.post("/mcp/token", data={"grant_type": "authorization_code", "code": "bad", "client_id": cid, "redirect_uri": "http://localhost:3000/cb", "code_verifier": "v" * 43}, headers={"Authorization": "Bearer stray"})
            P["POST /mcp/token (bad code, stray bearer)"] = profile(r)
            r = await c.post("/mcp/token", data={"grant_type": "refresh_token", "refresh_token": "nope", "client_id": cid})
            P["POST /mcp/token (bad refresh)"] = profile(r)
            P["POST /mcp/token/ (trailing slash)"] = profile(await c.post("/mcp/token/", data={}))
            P["GET /mcp/token"] = profile(await c.get("/mcp/token"))
            r = await c.post("/mcp/revoke", data={"token": "nope", "client_id": cid})
            P["POST /mcp/revoke (unknown token)"] = profile(r)
            P["GET /mcp/nope"] = profile(await c.get("/mcp/nope"))


async def phase_redirect_binding():
    R = OUT["redirect_binding"] = {}

    async def run(label, proxy, cases, registered):
        parent, child, _, _ = build_app(proxy)
        rows = {}
        async with child.router.lifespan_context(child):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=parent), base_url=BASE) as c:
                r = await register(c, registered)
                if r.status_code != 201:
                    rows["REGISTER " + ",".join(registered)] = {"status": r.status_code, "body": r.json()}
                    R[label] = rows
                    return
                cid = r.json()["client_id"]
                for redirect in cases:
                    rr = await authorize(c, redirect.get("client_id", cid), redirect["uri"])
                    loc = rr.headers.get("location")
                    rows[redirect["uri"] + (" [upstream id]" if "client_id" in redirect else "")] = {
                        "status": rr.status_code,
                        "location": ("<consent>" if loc and "/mcp/consent" in loc else loc),
                        "body": rr.text[:120] if rr.status_code >= 400 and "html" not in rr.headers.get("content-type", "") else None,
                    }
        R[label] = rows

    loop_cases = [
        {"uri": "http://localhost:3000/cb"},
        {"uri": "http://localhost:4000/cb"},
        {"uri": "http://127.0.0.1:3000/cb"},
        {"uri": "http://localhost:3000/other"},
        {"uri": "http://localhost:3000/cb/../x"},
        {"uri": "http://localhost@evil.example/cb"},
        {"uri": "https://evil.example/cb"},
        {"uri": "https://evil.example/cb", "client_id": UPSTREAM_ID},
    ]
    await run("DCR, no allowlist, registered http://localhost:3000/cb", make_proxy(), loop_cases, ["http://localhost:3000/cb"])
    await run(
        "DCR, no allowlist, registered https://claude.ai/api/mcp/auth_callback",
        make_proxy(),
        [
            {"uri": "https://claude.ai/api/mcp/auth_callback"},
            {"uri": "https://claude.ai/api/mcp/auth_callback2"},
            {"uri": "https://claude.ai:8443/api/mcp/auth_callback"},
            {"uri": "https://evil.example/api/mcp/auth_callback"},
        ],
        ["https://claude.ai/api/mcp/auth_callback"],
    )
    await run(
        "DCR, allowlist [http://localhost:*], registered http://localhost:3000/cb",
        make_proxy(allowlist=["http://localhost:*"]),
        [
            {"uri": "http://localhost:3000/cb"},
            {"uri": "http://localhost:5000/anything-at-all"},
            {"uri": "http://127.0.0.1:3000/cb"},
            {"uri": "https://evil.example/cb"},
            {"uri": "https://evil.example/cb", "client_id": UPSTREAM_ID},
            {"uri": "http://localhost:9999/x", "client_id": UPSTREAM_ID},
        ],
        ["http://localhost:3000/cb"],
    )
    await run(
        "DCR, allowlist [http://localhost:*], registering https://client.example/cb",
        make_proxy(allowlist=["http://localhost:*"]),
        [],
        ["https://client.example/cb"],
    )
    await run(
        "PinnedProxy (get_client refuses upstream id), no allowlist",
        make_proxy(PinnedProxy),
        [
            {"uri": "http://localhost:3000/cb"},
            {"uri": "https://evil.example/cb", "client_id": UPSTREAM_ID},
        ],
        ["http://localhost:3000/cb"],
    )
    await run(
        "DCR, no allowlist, registering javascript: scheme",
        make_proxy(),
        [],
        ["javascript:alert(1)"],
    )


def phase_persistence_and_keys():
    from fastmcp import settings as fm_settings
    OUT["fastmcp_home_default"] = str(fm_settings.home)
    proxy = make_proxy()
    OUT["store_collections"] = sorted(
        getattr(proxy, a).default_collection
        for a in dir(proxy)
        if a.endswith("_store") and hasattr(getattr(proxy, a), "default_collection")
    )
    # str key derivation cost
    t = time.perf_counter()
    make_proxy(jwt_signing_key="a-string-secret-of-reasonable-length-1234")
    OUT["jwt_key_str_derivation_seconds"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    make_proxy(jwt_signing_key=os.urandom(32))
    OUT["jwt_key_bytes_seconds"] = round(time.perf_counter() - t, 3)
    try:
        import key_value.aio.stores.postgresql as pg  # noqa
        OUT["kv_postgresql_importable"] = True
    except Exception as e:  # pragma: no cover
        OUT["kv_postgresql_importable"] = repr(e)
    # default file store: where would it land, given a fixed key?
    proxy_default = OAuthProxy(
        upstream_authorization_endpoint="https://idp.example/authorize",
        upstream_token_endpoint="https://idp.example/token",
        upstream_client_id=UPSTREAM_ID,
        upstream_client_secret="s" * 40,
        token_verifier=NullVerifier(),
        base_url=f"{BASE}/mcp",
        jwt_signing_key=b"\x01" * 32,
    )
    store = proxy_default._client_storage
    inner = getattr(store, "key_value", None)
    OUT["default_store"] = {
        "wrapper": type(store).__name__,
        "inner": type(inner).__name__,
        "data_directory": str(getattr(inner, "_data_directory", getattr(inner, "data_directory", "?"))),
    }


async def main():
    make_proxy  # noqa
    phase_persistence_and_keys()
    await phase_routes_and_profile()
    await phase_redirect_binding()
    out = os.path.join(os.path.dirname(__file__), "probe_a.json")
    with open(out, "w") as f:
        json.dump(OUT, f, indent=2, default=str)
    print(json.dumps(OUT, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
