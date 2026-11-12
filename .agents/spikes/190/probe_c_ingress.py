"""#190 spike, phase C — the family-8 surface as nginx exposes it (packaged web
image, PUBLIC_BASE_URL unset, defaults), in front of the phase-B probe server."""
import json, httpx
B = "http://127.0.0.1:8082"
c = httpx.Client(follow_redirects=False, timeout=10)
rows = []
def row(method, path, **kw):
    r = c.request(method, B + path, **kw)
    rows.append((f"{method} {path}" + (" [" + ",".join(f"{k}={v}" for k, v in kw.get("headers", {}).items()) + "]" if kw.get("headers") else ""),
                 r.status_code, r.headers.get("location"), r.headers.get("cache-control"), r.headers.get("www-authenticate", "")[:40],
                 (r.headers.get("content-type") or "").split(";")[0]))
for p in [
    "/.well-known/oauth-protected-resource/mcp/", "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-authorization-server/mcp", "/.well-known/oauth-authorization-server/mcp/",
    "/.well-known/oauth-authorization-server", "/.well-known/openid-configuration/mcp", "/.well-known/openid-configuration",
    "/.well-known/oauth-protected-resource", "/.well-known/anything",
    "/mcp/.well-known/oauth-authorization-server", "/mcp/.well-known/oauth-protected-resource/mcp/", "/mcp/.well-known/openid-configuration",
    "/api/.well-known/oauth-authorization-server/mcp", "/api/.well-known/oauth-protected-resource/mcp/", "/api/%2ewell-known/oauth-authorization-server/mcp",
    "/api//.well-known/oauth-authorization-server/mcp", "/api/mcp/authorize", "/api/mcp/.well-known/oauth-authorization-server",
    "/mcp/authorize", "/mcp/authorize/", "/mcp/authorize/?client_id=x&redirect_uri=http://localhost/cb", "/mcp/token/", "/mcp/auth/callback",
    "/mcp/auth/callback/?code=x&state=y", "/mcp/consent", "/mcp/consent/", "/mcp/register", "/mcp/revoke", "/mcp/nope", "/mcp", "/mcp/",
]:
    row("GET", p)
row("POST", "/mcp/", json={})
row("POST", "/mcp", json={})
row("POST", "/mcp/register", json={"redirect_uris": ["http://localhost:3000/cb"], "token_endpoint_auth_method": "none"})
row("POST", "/mcp/token", data={"grant_type": "authorization_code", "code": "x", "client_id": "x", "redirect_uri": "http://localhost/cb", "code_verifier": "v" * 43})
row("POST", "/mcp/token/", data={})
row("OPTIONS", "/mcp/token", headers={"Origin": "http://127.0.0.1:6274", "Access-Control-Request-Method": "POST"})
row("OPTIONS", "/.well-known/oauth-authorization-server/mcp", headers={"Origin": "http://127.0.0.1:6274", "Access-Control-Request-Method": "GET"})
row("PUT", "/mcp/authorize")
row("GET", "/.well-known/oauth-authorization-server/mcp", headers={"Host": "evil.example"})
row("GET", "/mcp/authorize", headers={"Host": "evil.example"})
w = max(len(r[0]) for r in rows)
for r in rows:
    print(f"{r[0]:{w}}  {r[1]}  loc={r[2]!r:<48} cc={r[3]!r:<22} www={r[4]!r:<42} {r[5]}")
r = c.get(B + "/.well-known/oauth-authorization-server/mcp")
print("\nheaders on discovery via nginx:", {k: v for k, v in r.headers.items() if k.lower() in ("x-frame-options", "content-security-policy", "x-content-type-options", "referrer-policy", "access-control-allow-origin", "cache-control")})
print("issuer via nginx:", r.json()["issuer"], "| registration_endpoint:", r.json()["registration_endpoint"])
