"""#190 spike, phase A3 — a blanket no-store middleware on the mount must not
disturb the consent/binding cookies (design §5.6 credential leakage row)."""
import asyncio, json, re
from urllib.parse import parse_qs, urlparse
import httpx
import probe_a as A
from starlette.middleware.base import BaseHTTPMiddleware


class NoStore(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        if not request.url.path.startswith("/.well-known/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp


async def main():
    proxy = A.make_proxy()
    parent, child, _, _ = A.build_app(proxy)
    child.add_middleware(NoStore)
    out = {}
    async with child.router.lifespan_context(child):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=parent), base_url=A.BASE) as c:
            cid = (await A.register(c, ["http://localhost:3000/cb"])).json()["client_id"]
            r = await A.authorize(c, cid, "http://localhost:3000/cb")
            txn = parse_qs(urlparse(r.headers["location"]).query)["txn_id"][0]
            page = await c.get(f"/mcp/consent?txn_id={txn}")
            out["consent GET"] = A.profile(page)
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            r = await c.post("/mcp/consent", data={"txn_id": txn, "csrf_token": csrf, "action": "approve"})
            out["consent POST approve"] = A.profile(r)
            r = await c.get(f"/mcp/auth/callback?error=access_denied&state={txn}")
            out["callback error -> client"] = A.profile(r)
            r = await c.post("/mcp/token", data={"grant_type": "authorization_code", "code": "bad", "client_id": cid, "redirect_uri": "http://localhost:3000/cb", "code_verifier": "v" * 43})
            out["token bad code"] = A.profile(r)
            out["discovery untouched"] = A.profile(await c.get("/.well-known/oauth-authorization-server/mcp"))["cache"]
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if vv not in (None, [], "")} if isinstance(v, dict) else v for k, v in out.items()}, indent=1))

asyncio.run(main())
