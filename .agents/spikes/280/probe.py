"""#280 spike driver — plamotrack's browser login and MCP OAuth against Pocket ID.

Evidence, not code: nothing here is imported by the app. It reuses the deployment
gate's flows (`backend/deployment_gate.py`: the host over ssh, `oidc_login`,
`mcp_link`, `mcp_verify`) and replaces only the provider's sign-in — the gate fills
Keycloak's password form over HTTP, and Pocket ID has no password: its sign-in is a
passkey, driven here in Chromium with a CDP virtual authenticator whose credentials
persist in the state directory between runs.

Run from `backend/` (the gate's imports) with Playwright alongside, never added to
the lock:

    uv run --with 'playwright==1.62.*' python ../.agents/spikes/280/probe.py <step> \\
        --base https://NAME --ssh root@HOST

Steps, in order (README.md has the host layout):

    prepare        stop the gate's stack and Keycloak, start Pocket ID, create the
                   `plamotrack` client, start a fresh plamotrack stack in OIDC mode
    enrol USER     create a Pocket ID user and register a passkey for it
    claim          the first browser login, presenting the setup token (owner)
    login          a later browser login (owner)
    stranger       a login by another Pocket ID user, which must be refused
    mcp            a DCR client linked through the whole chain (gate.mcp_link)
    verify         refresh and initialize with the saved link (gate.mcp_verify)
    lifetime MIN   set the provider's access-token lifetime for the client
    transparent    a tool call after the provider's token expired (refresh behind it)
    race           two refreshes of one refresh token at once
    reuse          Pocket ID itself: a rotated refresh token presented again
    revoke         the client revokes its grant at /mcp/revoke
    restart WHICH  restart `idp` or `api`, then a tool call and a refresh
    matrix         the upstream authorize request, one parameter varied at a time
    api-resource add|remove   register plamotrack's /mcp as an API in Pocket ID
    backup-restore Pocket ID export, `down -v`, import; then login and refresh
    wrong-key      the restored data under another ENCRYPTION_KEY, then the right one
    lost-passkey   the owner's passkey deleted; a login code and a new one; login
    tunnel         plamotrack behind a Cloudflare Tunnel (--base is the tunnel's name;
                   --idp, --host-ip, --tunnel-proxy, --tunnel-visitor)
    teardown       remove the spike's stacks; start the gate's stack and Keycloak

Secrets (the Pocket ID keys, the client secret, the passkeys' private keys, the
session cookie, the MCP link) live in `--state-dir` as mode-0600 files and are
never printed.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import html
import json
import pathlib
import secrets
import sys
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

import httpx  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

import deployment_gate as gate  # noqa: E402

RESULTS_DIR = HERE.parents[2] / ".dev" / "280"
SPIKE_DIR = "/opt/plamotrack-280"
GATE_DIR = "/opt/plamotrack"
CLIENT_ID = "plamotrack"
#: The provider's redirects during the most recent sign-in, with any `error*`
#: parameters they carried back — what a failed link is reported with.
LAST_HOPS: list[str] = []


# --- state ---------------------------------------------------------------------------


def secret(ctx: gate.Context, filename: str, make) -> str:
    path = ctx.state(filename)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = make()
    ctx.save(filename, value + "\n")
    return value


def idp_api(ctx: gate.Context) -> httpx.Client:
    return httpx.Client(
        base_url=f"{ctx.idp}/api",
        headers={"X-API-KEY": ctx.load("pocket-id-api-key")},
        timeout=30,
    )


# --- the browser -------------------------------------------------------------------


@contextlib.contextmanager
def browser(ctx: gate.Context, user: str | None):
    """Chromium with one virtual platform authenticator (resident keys, user
    verification, presence simulated) holding USER's saved passkeys."""
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch(headless=True)
        context = chromium.new_context()
        page = context.new_page()
        cdp = context.new_cdp_session(page)
        cdp.send("WebAuthn.enable", {"enableUI": False})
        authenticator = cdp.send(
            "WebAuthn.addVirtualAuthenticator",
            {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,
                    "hasUserVerification": True,
                    "isUserVerified": True,
                    "automaticPresenceSimulation": True,
                }
            },
        )["authenticatorId"]
        if user is not None and ctx.state(f"passkeys-{user}.json").exists():
            for credential in json.loads(ctx.load(f"passkeys-{user}.json")):
                cdp.send(
                    "WebAuthn.addCredential",
                    {"authenticatorId": authenticator, "credential": credential},
                )
        try:
            yield page, cdp, authenticator
        finally:
            chromium.close()


def shot(page, label: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(RESULTS_DIR / f"{time.strftime('%H%M%S')}-{label}.png"))


def pocket_sign_in(ctx: gate.Context, authorization_url: str) -> str:
    """The provider leg of a login, as a person with a passkey: open the authorize
    URL, press Pocket ID's Sign in (passkey, then consent), and return the redirect
    back to plamotrack without following it — the gate's HTTP client holds the
    login-binding cookie and follows it itself."""
    captured: list[str] = []
    hops = LAST_HOPS
    hops.clear()
    with browser(ctx, ctx.idp_user) as (page, _cdp, _authenticator):

        def catch(route):
            # A navigation to plamotrack started by Pocket ID's script (not a redirect).
            if route.request.is_navigation_request():
                captured.append(route.request.url)
                route.fulfill(status=200, body="captured by the #280 probe")
            else:
                route.abort()

        def provider(route):
            # A redirect is invisible to a route on its target, so the provider's
            # navigations are fetched here without following them: a 3xx back to
            # plamotrack is captured instead of reaching the callback without the
            # login-binding cookie the gate's own client holds.
            if not route.request.is_navigation_request():
                route.continue_()
                return
            answer = route.fetch(max_redirects=0)
            if not 300 <= answer.status < 400:
                route.fulfill(response=answer)
                return
            location = urljoin(route.request.url, answer.headers.get("location", ""))
            returned = parse_qs(urlsplit(location).query)
            errors = {k: v[0] for k, v in returned.items() if k.startswith("error")}
            hops.append(
                f"{answer.status} {route.request.url.split('?')[0]} -> {location.split('?')[0]}"
                + (f" {errors}" if errors else f" (params {sorted(returned)})")
            )
            if location.startswith(ctx.base):
                captured.append(location)
                route.fulfill(status=200, body="captured by the #280 probe")
                return
            # A hop within the provider becomes a client-side navigation (a meta
            # refresh; Pocket ID's CSP is dropped from the hop), so the next
            # request is a fresh one this handler sees (cookies set on the hop kept).
            headers = {
                k: v
                for k, v in answer.headers.items()
                if k.lower()
                not in ("location", "content-length", "content-type", "content-security-policy")
            }
            route.fulfill(
                status=200,
                headers={**headers, "content-type": "text/html"},
                body=f'<meta http-equiv="refresh" content="0;url={html.escape(location)}">',
            )

        page.context.route(f"{ctx.base}/**", catch)
        page.context.route(f"{ctx.idp}/**", provider)
        page.goto(authorization_url)
        page.wait_for_load_state("networkidle")
        shot(page, f"{ctx.idp_user}-authorize")
        # The interaction page is one button through its steps: the first press
        # signs in with the passkey, the next confirms consent. Press it until
        # Pocket ID redirects back, and record how many presses that took.
        presses = 0
        while not captured and presses < 4:
            button = page.get_by_role("button", name="Sign in")
            for _ in range(80):
                if captured or button.count():
                    break
                page.wait_for_timeout(250)
            if captured:
                break
            if button.count() == 0:
                raise gate.GateError(
                    f"no Sign in button at {page.url.split('?')[0]}: "
                    f"{page.locator('body').inner_text()[:300]!r}"
                )
            button.first.click()
            presses += 1
            for _ in range(40):
                if captured:
                    break
                page.wait_for_timeout(250)
            shot(page, f"{ctx.idp_user}-after-press-{presses}")
        print(f"     (redirected back after {presses} press(es) of Sign in; provider hops: {hops})")
        if not captured:
            raise gate.GateError(
                f"Pocket ID never redirected back (at {page.url.split('?')[0]}): "
                f"{page.locator('body').inner_text()[:300]!r}"
            )
    return captured[0]


gate.idp_sign_in = pocket_sign_in


# --- steps ---------------------------------------------------------------------------


def step_prepare(ctx: gate.Context) -> None:
    host = ctx.host
    name = ctx.name
    encryption_key = secret(ctx, "pocket-id-encryption-key", lambda: secrets.token_urlsafe(32))
    api_key = secret(ctx, "pocket-id-api-key", lambda: secrets.token_urlsafe(32))
    client_secret = secret(ctx, "oidc-client-secret", lambda: secrets.token_urlsafe(32))
    signing_key = secret(ctx, "signing-key", lambda: secrets.token_hex(32))
    db_password = secret(ctx, "postgres-password", lambda: secrets.token_urlsafe(24))

    root = gate.Host(ssh=host.ssh, remote_dir="/")
    root.run(
        f"mkdir -p {SPIKE_DIR}/pocket-id && cp -n {GATE_DIR}/docker-compose.yml "
        f"{GATE_DIR}/env.example {SPIKE_DIR}/ && cd {SPIKE_DIR} && "
        "{ [ -f .env ] || { cp env.example .env && chmod 600 .env; }; }"
    )
    root.run(
        f"cat > {SPIKE_DIR}/pocket-id/docker-compose.yml",
        input_text=(HERE / "pocket-id" / "docker-compose.yml").read_text(encoding="utf-8"),
    )
    idp_env = gate.Host(ssh=host.ssh, remote_dir=f"{SPIKE_DIR}/pocket-id")
    idp_env.run("touch .env && chmod 600 .env")
    idp_env.env_set(
        PLAMOTRACK_TEST_NAME=name,
        POCKET_ID_ENCRYPTION_KEY=encryption_key,
        POCKET_ID_STATIC_API_KEY=api_key,
    )
    ctx.results.record("pocket-id env", "written on the host (values on stdin)")

    # The gate's collection stays in its own volume; only the containers stop.
    root.run(f"cd {GATE_DIR} && docker compose stop")
    root.run("docker stop plamotrack-gate-keycloak >/dev/null 2>&1 || true")
    ctx.results.record("gate stack + Keycloak", "stopped (volumes kept)")

    idp_env.run("docker compose up -d --wait")
    discovery = httpx.get(f"{ctx.idp}/.well-known/openid-configuration", timeout=30).json()
    ctx.save("discovery.json", json.dumps(discovery, indent=2) + "\n")
    algorithms = discovery.get("id_token_signing_alg_values_supported")
    ctx.results.record(
        "discovery",
        f"issuer {discovery['issuer']}; algs {algorithms}; "
        f"revocation {'revocation_endpoint' in discovery}",
    )

    with idp_api(ctx) as api:
        callbacks = [f"{ctx.base}/api/auth/oidc/callback", f"{ctx.base}/mcp/auth/callback"]
        body = {
            "id": CLIENT_ID,
            "name": "plamotrack",
            "callbackURLs": callbacks,
            "isPublic": False,
            "pkceEnabled": True,
            "isGroupRestricted": False,
        }
        existing = api.get(f"/oidc/clients/{CLIENT_ID}")
        if existing.status_code == 200:
            answer = api.put(f"/oidc/clients/{CLIENT_ID}", json=body)
        else:
            answer = api.post("/oidc/clients", json=body)
        if answer.status_code not in (200, 201):
            raise gate.GateError(f"client write answered {answer.status_code}: {answer.text[:300]}")
        listed = api.get(f"/oidc/clients/{CLIENT_ID}/secrets").json()
        if not listed:
            made = api.post(f"/oidc/clients/{CLIENT_ID}/secrets", json={"secret": client_secret})
            if made.status_code not in (200, 201):
                raise gate.GateError(f"secret answered {made.status_code}: {made.text[:300]}")
    ctx.results.record(
        "pocket-id client", f"{CLIENT_ID}: confidential, PKCE on, callbacks {callbacks}"
    )

    host.env_set(
        COMPOSE_PROJECT_NAME="plamotrack-280",
        POSTGRES_PASSWORD=db_password,
        AUTH_MODE="oidc",
        OIDC_ISSUER=discovery["issuer"],
        OIDC_CLIENT_ID=CLIENT_ID,
        OIDC_CLIENT_SECRET=client_secret,
        MCP_OAUTH_SIGNING_KEY=signing_key,
        PUBLIC_BASE_URL=ctx.base,
    )
    host.up()
    session = httpx.get(f"{ctx.base}/api/auth/session", timeout=30).json()
    ctx.results.record("plamotrack-280", f"up; /api/auth/session state {session.get('state')!r}")


def step_enrol(ctx: gate.Context, user: str) -> None:
    with idp_api(ctx) as api:
        found = [
            u
            for u in api.get("/users", params={"search": user}).json()["data"]
            if u["username"] == user
        ]
        if found:
            user_id = found[0]["id"]
        else:
            made = api.post(
                "/users",
                json={
                    "username": user,
                    "email": f"{user}@spike.invalid",
                    "emailVerified": True,
                    "firstName": user.title(),
                    "lastName": "Spike",
                    "displayName": f"{user.title()} Spike",
                },
            )
            if made.status_code != 201:
                raise gate.GateError(f"user create answered {made.status_code}: {made.text[:300]}")
            user_id = made.json()["id"]
        # An hour's code is the 12-character form, which /lc/ submits by itself; the
        # 15-minute default is 6 characters, and with email codes off (the default)
        # the code page waits for 12.
        code = api.post(f"/users/{user_id}/one-time-access-token", json={"ttl": 3600}).json()[
            "token"
        ]
    ctx.save(f"user-id-{user}", user_id + "\n")
    with browser(ctx, None) as (page, cdp, authenticator):
        page.goto(f"{ctx.idp}/lc/{code}")
        page.wait_for_url(f"{ctx.idp}/settings**", timeout=30000)
        page.goto(f"{ctx.idp}/settings/account")
        page.wait_for_load_state("networkidle")
        page.get_by_role("button", name="Add Passkey").first.click()
        for _ in range(40):
            credentials = cdp.send("WebAuthn.getCredentials", {"authenticatorId": authenticator})[
                "credentials"
            ]
            if credentials:
                break
            page.wait_for_timeout(250)
        page.wait_for_timeout(1000)
        shot(page, f"{user}-enrolled")
    if not credentials:
        raise gate.GateError(f"no passkey was created for {user}")
    ctx.save(f"passkeys-{user}.json", json.dumps(credentials) + "\n")
    ctx.results.record(f"enrol {user}", f"Pocket ID user {user_id}; {len(credentials)} passkey(s)")


def step_claim(ctx: gate.Context) -> None:
    token = ctx.host.setup_token()
    credential = gate.oidc_login(ctx, token)
    gate.save_credential(ctx, "owner-session.json", credential)
    ctx.results.record("claim (first login)", "owner session via Pocket ID passkey")


def step_login(ctx: gate.Context) -> None:
    credential = gate.oidc_login(ctx, None)
    gate.save_credential(ctx, "owner-session.json", credential)
    ctx.results.record("later login", "owner session via Pocket ID passkey")


def step_stranger(ctx: gate.Context) -> None:
    try:
        gate.oidc_login(ctx, None)
    except gate.GateError as refused:
        rows = ctx.host.psql("SELECT event_type FROM audit_event ORDER BY occurred_at DESC LIMIT 1")
        ctx.results.record("stranger refused", f"{refused}; newest audit row {rows}")
        return
    ctx.results.record("stranger refused", "the stranger got an owner session", ok=False)


def step_mcp(ctx: gate.Context) -> None:
    try:
        link = gate.mcp_link(ctx)
    except KeyError as missing:
        # The gate reads `code` off the client's redirect; an upstream refusal
        # arrives there without one. Report what the provider said instead.
        raise gate.GateError(
            f"no {missing} came back to the client; provider hops: {LAST_HOPS}"
        ) from None
    ctx.save("mcp-link.json", json.dumps(link) + "\n")
    ctx.results.record(
        "mcp link", "DCR → consent → Pocket ID → token → initialize → get_meta → refresh"
    )


def step_verify(ctx: gate.Context) -> None:
    link = json.loads(ctx.load("mcp-link.json"))
    out = gate.mcp_verify(ctx, link)
    ctx.save("mcp-link.json", json.dumps(link) + "\n")
    ctx.results.record("mcp verify", json.dumps(out))


def mcp_tool_call(ctx: gate.Context, link: dict) -> int:
    """initialize + notifications/initialized + tools/call get_meta with the saved
    access token; the status of the tool call (raises on a JSON-RPC failure)."""
    with ctx.http() as client:
        opened = gate.mcp_initialize(client, ctx.base, link["access_token"])
        if opened.status_code != 200:
            return opened.status_code
        session = opened.headers.get("mcp-session-id")
        gate.mcp_post(
            client, ctx.base, link["access_token"], "notifications/initialized", session=session
        )
        called = gate.mcp_post(
            client,
            ctx.base,
            link["access_token"],
            "tools/call",
            {"name": "get_meta", "arguments": {}},
            id_=2,
            session=session,
        )
        gate.mcp_result(called, 2, "tools/call get_meta")
        return called.status_code


def upstream_token_calls(ctx: gate.Context) -> set[str]:
    """The request ids of every answer Pocket ID's token endpoint has logged since
    its container started — a step diffs two readings, so nothing outside the
    step is counted. The route and the id only, never a query or a body."""
    out = gate.Host(ssh=ctx.host.ssh, remote_dir="/").run(
        "docker logs plamotrack-spike-pocket-id 2>&1 | grep 'route=/api/oidc/token ' "
        "| grep -o 'request_id=[0-9a-f-]*' || true"
    )
    return set(out.split())


def step_lifetime(ctx: gate.Context, minutes: str) -> None:
    with idp_api(ctx) as api:
        current = api.get(f"/oidc/clients/{CLIENT_ID}").json()
        body = {
            k: current.get(k)
            for k in (
                "name",
                "description",
                "callbackURLs",
                "logoutCallbackURLs",
                "isPublic",
                "pkceEnabled",
                "requiresReauthentication",
                "requiresPushedAuthorizationRequests",
                "skipConsent",
                "isGroupRestricted",
                "refreshTokenDurationMinutes",
            )
        }
        body = {k: v for k, v in body.items() if v is not None}
        body["accessTokenDurationMinutes"] = int(minutes)
        answer = api.put(f"/oidc/clients/{CLIENT_ID}", json=body)
        if answer.status_code != 200:
            raise gate.GateError(
                f"client update answered {answer.status_code}: {answer.text[:300]}"
            )
        got = api.get(f"/oidc/clients/{CLIENT_ID}").json()
    ctx.results.record(
        "provider access-token lifetime",
        f"{got.get('accessTokenDurationMinutes')} min "
        f"(refresh {got.get('refreshTokenDurationMinutes')} min)",
    )


def step_transparent(ctx: gate.Context) -> None:
    """A request after the provider's access token has expired: FastMCP must
    refresh it behind the request (Pocket ID rotates the refresh token)."""
    link = json.loads(ctx.load("mcp-link.json"))
    before = upstream_token_calls(ctx)
    status = mcp_tool_call(ctx, link)
    calls = len(upstream_token_calls(ctx) - before)
    ctx.results.record(
        "transparent refresh",
        f"tools/call {status}; upstream token calls {calls}",
        ok=status == 200 and calls == 1,
    )


def step_race(ctx: gate.Context) -> None:
    """Two refreshes of one refresh token at once. Pocket ID revokes a whole grant
    when a rotated refresh token is presented again, so the proxy must let exactly
    one reach it; the winner's tokens must then keep working."""
    import concurrent.futures

    link = json.loads(ctx.load("mcp-link.json"))
    before = upstream_token_calls(ctx)

    def refresh(_):
        with ctx.http() as client:
            return client.post(
                link["token_endpoint"],
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": link["refresh_token"],
                    "client_id": link["client_id"],
                },
            )

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        answers = list(pool.map(refresh, range(2)))
    statuses = sorted(a.status_code for a in answers)
    winners = [a for a in answers if a.status_code == 200]
    errors = [a.json().get("error") for a in answers if a.status_code != 200]
    calls = len(upstream_token_calls(ctx) - before)
    ok = len(winners) == 1 and calls == 1
    if winners:
        fresh = winners[0].json()
        link.update(refresh_token=fresh["refresh_token"], access_token=fresh["access_token"])
        ctx.save("mcp-link.json", json.dumps(link) + "\n")
        after = gate.mcp_verify(ctx, link)
        ctx.save("mcp-link.json", json.dumps(link) + "\n")
        ok = ok and after.get("refresh_status") == 200
    else:
        after = {}
    ctx.results.record(
        "concurrent refresh",
        f"statuses {statuses} {errors}; upstream token calls {calls}; "
        f"then refresh {after.get('refresh_status')} / initialize "
        f"{after.get('new_access_initialize')}",
        ok=ok,
    )


def step_reuse(ctx: gate.Context) -> None:
    """Pocket ID's own rule, measured directly rather than read from its source: a
    refresh token presented a second time after rotation. This is why the proxy's
    per-grant lock matters here — Google does not rotate, Pocket ID does. The
    probe is the client (the `plamotrack` client's secret, the MCP callback), so
    no plamotrack grant is touched."""
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    redirect = f"{ctx.base}/mcp/auth/callback"
    url = f"{ctx.idp}/authorize?" + urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect,
            "scope": "openid",
            "state": secrets.token_urlsafe(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    code = parse_qs(urlsplit(pocket_sign_in(ctx, url)).query)["code"][0]
    auth = (CLIENT_ID, ctx.load("oidc-client-secret"))
    token_url = f"{ctx.idp}/api/oidc/token"
    with httpx.Client(timeout=30) as client:

        def refresh(token: str) -> httpx.Response:
            return client.post(
                token_url, auth=auth, data={"grant_type": "refresh_token", "refresh_token": token}
            )

        first = client.post(
            token_url,
            auth=auth,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "code_verifier": verifier,
            },
        ).json()
        second = refresh(first["refresh_token"])
        rotated = second.json().get("refresh_token")
        replay = refresh(first["refresh_token"])
        after = refresh(rotated) if rotated else None
    ctx.results.record(
        "provider refresh-token reuse",
        f"first refresh {second.status_code} (rotated: {rotated != first['refresh_token']}); "
        f"old token again {replay.status_code} {replay.json().get('error')}; "
        f"the rotated one then {after.status_code if after else None} "
        f"{after.json().get('error') if after is not None and after.status_code != 200 else ''}",
    )


def step_revoke(ctx: gate.Context) -> None:
    link = json.loads(ctx.load("mcp-link.json"))
    with ctx.http() as client:
        revoked = client.post(
            f"{ctx.base}/mcp/revoke",
            data={
                "token": link["refresh_token"],
                "token_type_hint": "refresh_token",
                "client_id": link["client_id"],
            },
        )
    after = gate.mcp_verify(ctx, dict(link))
    rows = ctx.host.psql("SELECT event_type FROM audit_event ORDER BY occurred_at DESC LIMIT 3")
    ctx.results.record(
        "revocation",
        f"/mcp/revoke {revoked.status_code}; then refresh "
        f"{after.get('refresh_status')} {after.get('refresh_error')}, old access "
        f"initialize {after.get('old_access_initialize')}; audit {rows}",
        ok=revoked.status_code == 200 and after.get("refresh_status") != 200,
    )


def step_restart(ctx: gate.Context, which: str) -> None:
    root = gate.Host(ssh=ctx.host.ssh, remote_dir="/")
    if which == "idp":
        root.run(
            f"cd {SPIKE_DIR}/pocket-id && docker compose restart && docker compose up -d --wait"
        )
    else:
        ctx.host.compose("restart api")
        ctx.host.compose("up -d --wait --no-build")
    link = json.loads(ctx.load("mcp-link.json"))
    status = mcp_tool_call(ctx, link)
    out = gate.mcp_verify(ctx, link)
    ctx.save("mcp-link.json", json.dumps(link) + "\n")
    ctx.results.record(
        f"restart {which}",
        f"tools/call {status}; then {json.dumps(out)}",
        ok=status == 200 and out.get("refresh_status") == 200,
    )


def step_matrix(ctx: gate.Context) -> None:
    """The MCP proxy's upstream authorize request, one parameter varied at a time,
    sent to Pocket ID directly: accepted is its 302 to `/interaction`; refused is
    its 303 back to the callback with `error` (never followed)."""
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    core = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": f"{ctx.base}/mcp/auth/callback",
        "state": secrets.token_urlsafe(16),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    resource = f"{ctx.base}/mcp/"
    cases = {
        "as the proxy sends it": {
            "scope": "openid",
            "resource": resource,
            "access_type": "offline",
            "prompt": "consent",
        },
        "without resource": {"scope": "openid", "access_type": "offline", "prompt": "consent"},
        "resource alone": {"scope": "openid", "resource": resource},
        "resource, no trailing slash": {"scope": "openid", "resource": resource.rstrip("/")},
        "resource = the provider": {"scope": "openid", "resource": ctx.idp},
        "scope openid": {"scope": "openid"},
        "scope openid offline_access": {"scope": "openid offline_access"},
        "access_type=offline": {"scope": "openid", "access_type": "offline"},
        "prompt=consent": {"scope": "openid", "prompt": "consent"},
    }
    with httpx.Client(follow_redirects=False, timeout=30) as client:
        for name, extra in cases.items():
            answer = client.get(f"{ctx.idp}/authorize?" + urlencode({**core, **extra}))
            location = answer.headers.get("location", "")
            if location.startswith("/interaction"):
                verdict = "accepted"
            else:
                error = parse_qs(urlsplit(location).query).get("error", ["?"])[0]
                verdict = f"refused: {answer.status_code} {error}"
            ctx.results.record(f"authorize: {name}", verdict)


def step_api_resource(ctx: gate.Context, action: str) -> None:
    """The configuration-only answer to the `resource` refusal: register
    plamotrack's MCP URL as an API in Pocket ID and grant the client delegated
    access to it (`add`), or remove every API (`remove`)."""
    with idp_api(ctx) as api:
        listed = api.get("/apis").json()
        existing = listed["data"] if isinstance(listed, dict) else listed
        if action == "remove":
            for item in existing:
                api.delete(f"/apis/{item['id']}")
            ctx.results.record("api resource", f"removed {len(existing)}")
            return
        made = api.post("/apis", json={"name": "plamotrack MCP", "resource": f"{ctx.base}/mcp"})
        if made.status_code != 201:
            raise gate.GateError(f"api create answered {made.status_code}: {made.text[:300]}")
        grant = api.put(
            f"/apis/{made.json()['id']}/clients/{CLIENT_ID}",
            json={
                "userDelegatedAccess": True,
                "clientAccess": False,
                "userDelegatedPermissionIds": [],
                "clientPermissionIds": [],
            },
        )
        if grant.status_code != 200:
            raise gate.GateError(f"api grant answered {grant.status_code}: {grant.text[:300]}")
    ctx.results.record("api resource", f"{made.json()['resource']} registered, client granted")


def step_backup_restore(ctx: gate.Context) -> None:
    """Pocket ID's documented export/import (experimental upstream) across a
    destroyed volume, then the owner's login and the MCP link's refresh."""
    idp = gate.Host(ssh=ctx.host.ssh, remote_dir=f"{SPIKE_DIR}/pocket-id")
    archive = "/root/spike-280-pocket-id-export.zip"
    idp.run(
        f"docker compose exec -T pocket-id ./pocket-id export --path - > {archive} "
        f"&& chmod 600 {archive}"
    )
    entries = idp.run(f"unzip -Z1 {archive}").split()
    idp.run("docker compose down -v")
    idp.run(f"docker compose run --rm -T pocket-id ./pocket-id import --yes --path - < {archive}")
    idp.run("docker compose up -d --wait")
    ctx.results.record(
        "pocket-id export → down -v → import",
        f"archive holds {sorted(e for e in entries if '/' not in e)} + uploads",
    )
    step_login(ctx)
    step_verify(ctx)


def step_wrong_key(ctx: gate.Context) -> None:
    """The restored data started with another ENCRYPTION_KEY, then the right one."""
    idp = gate.Host(ssh=ctx.host.ssh, remote_dir=f"{SPIKE_DIR}/pocket-id")
    idp.env_set(POCKET_ID_ENCRYPTION_KEY=secrets.token_urlsafe(32))
    idp.run("docker compose up -d --wait", check=False)
    time.sleep(3)
    state = idp.run(
        "docker inspect -f '{{.State.Status}} restarts={{.RestartCount}}' "
        "plamotrack-spike-pocket-id"
    ).strip()
    reason = idp.run(
        "docker logs --since 30s plamotrack-spike-pocket-id 2>&1 "
        "| grep -o 'failed to decrypt key' | head -1",
        check=False,
    ).strip()
    idp.env_set(POCKET_ID_ENCRYPTION_KEY=ctx.load("pocket-id-encryption-key"))
    idp.run("docker compose up -d --wait")
    ctx.results.record(
        "wrong ENCRYPTION_KEY",
        f"{state}; {reason or 'no decrypt error logged'}; right key restored",
        ok=bool(reason),
    )
    step_login(ctx)


def step_lost_passkey(ctx: gate.Context) -> None:
    """The owner's passkey deleted at Pocket ID; the old one refused; a one-time
    code and a new passkey; plamotrack's owner unchanged (same `sub`, no rebind)."""
    user_id = ctx.load("user-id-owner")
    with idp_api(ctx) as api:
        for credential in api.get(f"/users/{user_id}/webauthn-credentials").json():
            api.delete(f"/users/{user_id}/webauthn-credentials/{credential['id']}")
    try:
        gate.oidc_login(ctx, None)
    except gate.GateError as refused:
        ctx.results.record("deleted passkey", f"refused: {str(refused)[:160]}")
    else:
        ctx.results.record("deleted passkey", "still signed in", ok=False)
    step_enrol(ctx, "owner")
    step_login(ctx)


def step_tunnel(ctx: gate.Context) -> None:
    """The spike's plamotrack behind a Cloudflare Tunnel whose connector runs on
    another host, the gate's tunnel phase applied to it: `--base` is the tunnel's
    name; Pocket ID keeps its own. The client gains the tunnel's two callbacks; then
    WEB_BIND on the LAN address and PUBLIC_BASE_URL on the tunnel, and
    TRUSTED_PROXIES set only once nginx has been seen to receive the connector's
    address — after which it must resolve this workstation's, exactly."""
    if not (ctx.host_ip and ctx.tunnel_proxy and ctx.tunnel_visitor):
        raise gate.GateError("tunnel needs --host-ip, --tunnel-proxy and --tunnel-visitor")
    host = ctx.host
    with idp_api(ctx) as api:
        current = api.get(f"/oidc/clients/{CLIENT_ID}").json()
        callbacks = list(current["callbackURLs"])
        for callback in (f"{ctx.base}/api/auth/oidc/callback", f"{ctx.base}/mcp/auth/callback"):
            if callback not in callbacks:
                callbacks.append(callback)
        body = {
            k: current.get(k)
            for k in (
                "name",
                "description",
                "logoutCallbackURLs",
                "isPublic",
                "pkceEnabled",
                "requiresReauthentication",
                "requiresPushedAuthorizationRequests",
                "skipConsent",
                "isGroupRestricted",
                "accessTokenDurationMinutes",
                "refreshTokenDurationMinutes",
            )
        }
        body = {k: v for k, v in body.items() if v is not None}
        answer = api.put(f"/oidc/clients/{CLIENT_ID}", json={**body, "callbackURLs": callbacks})
        if answer.status_code != 200:
            raise gate.GateError(
                f"client update answered {answer.status_code}: {answer.text[:300]}"
            )
    ctx.results.record("pocket-id client callbacks", f"{len(callbacks)}: + the tunnel's two")

    host.env_set(
        WEB_BIND=ctx.host_ip, PUBLIC_BASE_URL=ctx.base, ALLOWED_HOSTS=None, TRUSTED_PROXIES=None
    )
    host.up()
    gate.expect(ctx, "tunnel: reachable", gate.get(ctx, "/api/healthz"), 200)
    before = host.web_last_address()
    if before != ctx.tunnel_proxy:
        raise gate.GateError(
            f"nginx saw {before}, not the connector {ctx.tunnel_proxy}; TRUSTED_PROXIES not set"
        )
    host.env_set(TRUSTED_PROXIES=ctx.tunnel_proxy)
    host.up()
    gate.get(ctx, "/api/healthz")
    after = host.web_last_address()
    ctx.results.record(
        f"tunnel: TRUSTED_PROXIES={ctx.tunnel_proxy}",
        f"nginx $remote_addr before: {before}; after: {after}; expected {ctx.tunnel_visitor}",
        after == ctx.tunnel_visitor,
    )


def step_teardown(ctx: gate.Context) -> None:
    """The spike's two stacks, their volumes, its directory and the export
    archive removed; the gate's stack and Keycloak started again, as they were."""
    root = gate.Host(ssh=ctx.host.ssh, remote_dir="/")
    root.run(f"cd {SPIKE_DIR} && docker compose down -v")
    root.run(f"cd {SPIKE_DIR}/pocket-id && docker compose down -v")
    root.run(f"rm -rf {SPIKE_DIR} /root/spike-280-pocket-id-export.zip")
    root.run("docker start plamotrack-gate-keycloak")
    root.run(f"cd {GATE_DIR} && docker compose up -d --wait --no-build")
    ctx.results.record("teardown", "spike stacks removed; gate stack and Keycloak started")


STEPS = {
    "prepare": step_prepare,
    "claim": step_claim,
    "login": step_login,
    "stranger": step_stranger,
    "mcp": step_mcp,
    "verify": step_verify,
    "transparent": step_transparent,
    "race": step_race,
    "revoke": step_revoke,
    "reuse": step_reuse,
    "matrix": step_matrix,
    "backup-restore": step_backup_restore,
    "wrong-key": step_wrong_key,
    "lost-passkey": step_lost_passkey,
    "tunnel": step_tunnel,
    "teardown": step_teardown,
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", choices=[*STEPS, "enrol", "lifetime", "restart", "api-resource"])
    parser.add_argument("user", nargs="?", default="owner")
    parser.add_argument("--base", required=True, help="https://NAME, the gate host's name")
    parser.add_argument("--ssh", required=True, help="root@HOST")
    parser.add_argument("--idp", help="Pocket ID's origin (default: https://idp.<base's host>)")
    parser.add_argument("--host-ip", help="tunnel: the host's LAN address, for WEB_BIND")
    parser.add_argument("--tunnel-proxy", help="tunnel: the connector's address")
    parser.add_argument("--tunnel-visitor", help="tunnel: this workstation's public address")
    parser.add_argument(
        "--state-dir", default=str(pathlib.Path.home() / ".plamotrack-gate" / "spike-280")
    )
    args = parser.parse_args(argv)
    base = args.base.rstrip("/")
    state_dir = pathlib.Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    ctx = gate.Context(
        base=base,
        host=gate.Host(ssh=args.ssh, remote_dir=SPIKE_DIR),
        results=gate.Results(),
        state_dir=state_dir,
        idp=(args.idp or f"https://idp.{urlsplit(base).hostname}").rstrip("/"),
        idp_user=args.user if args.step in ("enrol", "stranger") else "owner",
        idp_password=None,
        hold=0,
        ca_cert=None,
        host_ip=args.host_ip,
        tunnel_base=base,
        tunnel_proxy=args.tunnel_proxy,
        tunnel_visitor=args.tunnel_visitor,
    )
    if args.step == "stranger" and args.user == "owner":
        ctx.idp_user = "stranger"
    try:
        if args.step == "enrol":
            step_enrol(ctx, args.user)
        elif args.step == "lifetime":
            step_lifetime(ctx, args.user)
        elif args.step == "restart":
            step_restart(ctx, args.user)
        elif args.step == "api-resource":
            step_api_resource(ctx, args.user)
        else:
            STEPS[args.step](ctx)
    except gate.GateError as failure:
        ctx.results.record(args.step, str(failure), ok=False)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with (RESULTS_DIR / "log.md").open("a", encoding="utf-8") as log:
        for step, result, ok in ctx.results.rows:
            log.write(
                f"| {time.strftime('%F %T')} | {step} | {'ok' if ok else 'FAIL'} | {result} |\n"
            )
    return 1 if ctx.results.failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
