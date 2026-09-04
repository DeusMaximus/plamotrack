"""#190 spike, phase A2 — the thin binding constraint, consent deny, https cookies.

Proves a subclass can make an operator allowlist NARROW registration rather
than replace it (design §5.6 proxy trust), without touching the flow.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from urllib.parse import parse_qs, urlparse

import httpx
from mcp.shared.auth import InvalidRedirectUriError
from pydantic import AnyUrl

import probe_a as A
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.oauth_proxy.models import (
    ProxyDCRClient,
    _matches_registered_redirect_uri,
)

OUT: dict = {}


class BoundDCRClient(ProxyDCRClient):
    """Registration binding first (exact, loopback port may vary), then the
    operator allowlist if one is configured. Both must pass."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is not None and self.cimd_document is None:
            if not _matches_registered_redirect_uri(redirect_uri, self.redirect_uris):
                raise InvalidRedirectUriError(
                    f"Redirect URI '{redirect_uri}' not registered for client"
                )
        return super().validate_redirect_uri(redirect_uri)


class BoundProxy(OAuthProxy):
    async def get_client(self, client_id: str):
        if client_id == self._upstream_client_id:
            return None  # the synthesised client is refused outright
        client = await super().get_client(client_id)
        if client is None or client.cimd_document is not None:
            return client
        return BoundDCRClient(**client.model_dump(), allow_unregistered_redirect_uris=False)


async def run(label, proxy, cases, registered):
    parent, child, _, _ = A.build_app(proxy)
    rows = {}
    async with child.router.lifespan_context(child):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=parent), base_url=A.BASE) as c:
            r = await A.register(c, registered)
            if r.status_code != 201:
                rows["REGISTER"] = {"status": r.status_code, "body": r.json()}
                OUT[label] = rows
                return
            cid = r.json()["client_id"]
            for case in cases:
                rr = await A.authorize(c, case.get("client_id", cid), case["uri"])
                loc = rr.headers.get("location")
                rows[case["uri"] + (" [upstream id]" if "client_id" in case else "")] = {
                    "status": rr.status_code,
                    "location": "<consent>" if loc and "/mcp/consent" in loc else loc,
                }
    OUT[label] = rows


async def consent_and_cookies():
    # deny on a clean transaction
    proxy = A.make_proxy()
    parent, child, _, _ = A.build_app(proxy)
    async with child.router.lifespan_context(child):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=parent), base_url=A.BASE) as c:
            cid = (await A.register(c, ["http://localhost:3000/cb"])).json()["client_id"]
            r = await A.authorize(c, cid, "http://localhost:3000/cb")
            txn = parse_qs(urlparse(r.headers["location"]).query)["txn_id"][0]
            page = await c.get(f"/mcp/consent?txn_id={txn}")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            r = await c.post("/mcp/consent", data={"txn_id": txn, "csrf_token": csrf, "action": "deny"})
            OUT["consent deny"] = A.profile(r)
            r = await c.head("/.well-known/oauth-authorization-server/mcp")
            OUT["HEAD discovery"] = A.profile(r)
            r = await c.post("/mcp/revoke", data={"token": "x"})
            OUT["POST /mcp/revoke (no client_id)"] = A.profile(r) | {"body": r.text[:100]}
    # https base: Secure attribute on the consent cookies?
    proxy = A.make_proxy(base_url="https://plamo.example/mcp")
    parent, child, _, _ = A.build_app(proxy)
    async with child.router.lifespan_context(child):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=parent), base_url="https://plamo.example") as c:
            cid = (await A.register(c, ["http://localhost:3000/cb"])).json()["client_id"]
            r = await A.authorize(c, cid, "http://localhost:3000/cb")
            txn = parse_qs(urlparse(r.headers["location"]).query)["txn_id"][0]
            page = await c.get(f"/mcp/consent?txn_id={txn}")
            OUT["consent GET cookies (https base)"] = A.profile(page)["cookies"]
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            r = await c.post("/mcp/consent", data={"txn_id": txn, "csrf_token": csrf, "action": "approve"})
            OUT["consent approve cookies (https base)"] = A.profile(r)["cookies"]
            OUT["upstream redirect_uri (https base)"] = parse_qs(urlparse(r.headers["location"]).query)["redirect_uri"]


async def main():
    await run(
        "BoundProxy, allowlist [http://localhost:*], registered http://localhost:3000/cb",
        A.make_proxy(BoundProxy, allowlist=["http://localhost:*"]),
        [
            {"uri": "http://localhost:3000/cb"},
            {"uri": "http://localhost:4000/cb"},
            {"uri": "http://localhost:5000/anything-at-all"},
            {"uri": "http://127.0.0.1:3000/cb"},
            {"uri": "https://evil.example/cb"},
            {"uri": "https://evil.example/cb", "client_id": A.UPSTREAM_ID},
            {"uri": "http://localhost:9999/x", "client_id": A.UPSTREAM_ID},
        ],
        ["http://localhost:3000/cb"],
    )
    await run(
        "BoundProxy, no allowlist, registered http://localhost:3000/cb",
        A.make_proxy(BoundProxy),
        [
            {"uri": "http://localhost:3000/cb"},
            {"uri": "http://localhost:4000/cb"},
            {"uri": "http://localhost:5000/anything-at-all"},
        ],
        ["http://localhost:3000/cb"],
    )
    await consent_and_cookies()
    out = os.path.join(os.path.dirname(__file__), "probe_a2.json")
    json.dump(OUT, open(out, "w"), indent=2, default=str)
    print(json.dumps(OUT, indent=2, default=str))


def random_bytes_key_with_default_store():
    """Does an explicit random-bytes key survive the default store's key derivation?"""
    from fastmcp.server.auth.oauth_proxy import OAuthProxy
    try:
        OAuthProxy(
            upstream_authorization_endpoint="https://idp.example/authorize",
            upstream_token_endpoint="https://idp.example/token",
            upstream_client_id="x", upstream_client_secret="s" * 40,
            token_verifier=A.NullVerifier(), base_url="http://127.0.0.1:8000/mcp",
            jwt_signing_key=bytes(range(128, 160)),
        )
        return "ok"
    except Exception as e:
        return repr(e)[:160]


if __name__ == "__main__":
    print("random_bytes_key_with_default_store:", random_bytes_key_with_default_store())
    asyncio.run(main())
