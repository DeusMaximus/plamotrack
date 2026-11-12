"""#190 spike, phase B — scripted MCP client through the OIDC proxy to Keycloak.

  link   [user]  full flow: discovery, DCR, authorize, consent, Keycloak login,
                 callback, token, MCP initialize + whoami, refresh; saves state.json
  verify         with saved state: refresh -> initialize -> whoami (T13 restore)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

HERE = Path(__file__).parent
BASE = "http://127.0.0.1:8000"
STATE = HERE / "state.json"
REDIRECT = "http://localhost:6274/oauth/callback"


class FormFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and a.get("id") == "kc-form-login":
            self.action = a.get("action")
        if tag == "input" and a.get("name") and a.get("type") == "hidden":
            self.fields[a["name"]] = a.get("value", "")


def mcp(c, token, method, params=None, id_=1, session=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    if session:
        headers["Mcp-Session-Id"] = session
    body = {"jsonrpc": "2.0", "method": method}
    if not method.startswith("notifications/"):
        body["id"] = id_
    if params is not None:
        body["params"] = params
    return c.post(f"{BASE}/mcp/", json=body, headers=headers)


def link(username, password):
    out = {}
    c = httpx.Client(follow_redirects=False, timeout=20)
    prm = c.get(f"{BASE}/.well-known/oauth-protected-resource/mcp/").json()
    asm = c.get(f"{BASE}/.well-known/oauth-authorization-server/mcp").json()
    out["prm"] = prm
    out["as_issuer"] = asm["issuer"]
    reg = c.post(asm["registration_endpoint"], json={
        "client_name": "spike-script", "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    assert reg.status_code == 201, reg.text
    cid = reg.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    r = c.get(asm["authorization_endpoint"] + "?" + urlencode({
        "response_type": "code", "client_id": cid, "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "scope": "openid", "resource": f"{BASE}/mcp/",
    }))
    assert r.status_code == 302 and "/mcp/consent" in r.headers["location"], (r.status_code, r.text[:200])
    page = c.get(r.headers["location"])
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    txn = parse_qs(urlparse(r.headers["location"]).query)["txn_id"][0]
    r = c.post(f"{BASE}/mcp/consent", data={"txn_id": txn, "csrf_token": csrf, "action": "approve"})
    assert r.status_code == 302, (r.status_code, r.text[:200])
    kc_url = r.headers["location"]
    out["upstream_authorize_params"] = sorted(parse_qs(urlparse(kc_url).query))
    # Keycloak login
    kc = httpx.Client(follow_redirects=False, timeout=20)
    # Keycloak 26 marks its cookies Secure even over plain http; browsers accept
    # that on loopback (Chrome/Firefox, design §5.6) but the Python jar refuses
    # to return them, so the browser-side leg carries them by hand.
    page = kc.get(kc_url)
    jar = "; ".join(x.split(";")[0] for x in page.headers.get_list("set-cookie"))
    out["keycloak_cookie_attrs"] = sorted({a.strip() for x in page.headers.get_list("set-cookie") for a in x.split(";")[1:] if not a.strip().startswith(("Max-Age", "Path", "Version"))})
    f = FormFinder()
    f.feed(page.text)
    assert f.action, page.text[:300]
    r = kc.post(f.action, data={"username": username, "password": password, "credentialId": "", **f.fields}, headers={"Cookie": jar})
    assert r.status_code == 302, (r.status_code, r.text[:300])
    cb = r.headers["location"]
    out["idp_callback_shape"] = urlparse(cb)._replace(query="<code,state>").geturl()
    assert cb.startswith(f"{BASE}/mcp/auth/callback?")
    # callback on the proxy, carrying the consent-binding cookie from the same jar
    r = c.get(cb)
    assert r.status_code == 302, (r.status_code, r.text[:500])
    client_cb = r.headers["location"]
    assert client_cb.startswith(REDIRECT), client_cb
    q = parse_qs(urlparse(client_cb).query)
    assert q["state"][0] == state
    out["callback_cache_control"] = r.headers.get("cache-control")
    out["callback_set_cookie"] = [x.split(";")[0].split("=")[0] for x in r.headers.get_list("set-cookie")]
    tok = c.post(asm["token_endpoint"], data={
        "grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": REDIRECT,
        "client_id": cid, "code_verifier": verifier, "resource": f"{BASE}/mcp/",
    })
    assert tok.status_code == 200, tok.text
    t = tok.json()
    out["token_response_keys"] = sorted(t)
    out["expires_in"] = t.get("expires_in")
    out["token_cache_control"] = tok.headers.get("cache-control")
    at = t["access_token"]
    hdr, payload = at.split(".")[:2]
    def b64(s):
        return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
    out["fastmcp_jwt_header"] = b64(hdr)
    p = b64(payload)
    out["fastmcp_jwt_claims"] = {k: p[k] for k in p if k not in ("jti",)}
    init = mcp(c, at, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "spike", "version": "0"}})
    assert init.status_code == 200, init.text
    sess = init.headers.get("mcp-session-id")
    out["initialize_protocol"] = init.json()["result"]["protocolVersion"]
    mcp(c, at, "notifications/initialized", session=sess)
    who = mcp(c, at, "tools/call", {"name": "whoami", "arguments": {}}, id_=2, session=sess)
    assert who.status_code == 200, who.text
    res = who.json()["result"]
    claims = json.loads(res["content"][0]["text"])
    out["whoami"] = {
        "client_id": claims["client_id"], "scopes": claims["scopes"],
        "claims_subset": {k: claims["claims"].get(k) for k in ["iss", "sub", "aud", "azp", "email", "preferred_username", "scope", "typ"]},
    }
    # bad audience / REST-shaped use: present the token elsewhere
    rf = c.post(asm["token_endpoint"], data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": cid})
    assert rf.status_code == 200, rf.text
    out["refresh_rotates"] = rf.json()["refresh_token"] != t["refresh_token"]
    STATE.write_text(json.dumps({"client_id": cid, "refresh_token": rf.json()["refresh_token"], "access_token": rf.json()["access_token"], "token_endpoint": asm["token_endpoint"]}))
    print(json.dumps(out, indent=1))


def verify(label):
    s = json.loads(STATE.read_text())
    c = httpx.Client(follow_redirects=False, timeout=20)
    out = {"label": label}
    rf = c.post(s["token_endpoint"], data={"grant_type": "refresh_token", "refresh_token": s["refresh_token"], "client_id": s["client_id"]})
    out["refresh"] = {"status": rf.status_code, "body": rf.json() if rf.status_code != 200 else "ok", "cache": rf.headers.get("cache-control")}
    old = mcp(c, s["access_token"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "spike", "version": "0"}})
    out["old_access_token_initialize"] = {"status": old.status_code, "www_auth": old.headers.get("www-authenticate")}
    if rf.status_code == 200:
        t = rf.json()
        init = mcp(c, t["access_token"], "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "spike", "version": "0"}})
        out["new_access_token_initialize"] = init.status_code
        s["refresh_token"] = t["refresh_token"]
        s["access_token"] = t["access_token"]
        STATE.write_text(json.dumps(s))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "link":
        link(sys.argv[2], sys.argv[3])
    else:
        verify(sys.argv[2] if len(sys.argv) > 2 else "")
