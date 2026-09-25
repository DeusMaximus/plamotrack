# #280 findings — Pocket ID for the owner login and MCP OAuth

The #280 report; the owner's decision is §8. Run 2026-09-23 with `probe.py`
(README.md), end to end from a clean start by `sequence.sh`, exit 0; the refresh legs
re-run once more with exact upstream counting (§3). Browser legs used a CDP virtual
authenticator, not a real device; the owner's real-device and Claude.ai legs are §7,
and its last subsection is the Claude.ai link on the #294 build without the
workaround (2026-09-25).

## What ran

| | |
|---|---|
| Pocket ID | v2.16.0 (2026-09-20), `ghcr.io/pocket-id/pocket-id@sha256:9366436f…111ea` — the same index on Docker Hub; image revision `bb05e69` = the tag; SQLite, the image's defaults otherwise |
| plamotrack | v0.5.2-alpha release files, unmodified: api `sha256:20ad5a0a…b8c4`, web `sha256:ed5d0a2c…d4d8`, db `postgres@sha256:a3b7f434…30d6`; revision `4586081` |
| Front | the deployment gate's host: Caddy 2.11.4 with DNS-01, the reference Caddyfile, `NAME` and `idp.NAME` on Let's Encrypt certificates |
| Client registration at Pocket ID | one confidential client `plamotrack`, PKCE required, not group-restricted, callbacks `<base>/api/auth/oidc/callback` and `<base>/mcp/auth/callback` |
| Authenticator | headless Chromium 151, virtual CTAP2 platform authenticator (resident key, user verification) |
| MCP client | the gate's scripted DCR client (`deployment_gate.mcp_link`): discovery, DCR, authorize with `resource=<base>/mcp/`, consent, provider, token, `initialize`, `tools/call get_meta`, refresh |

## Results

| Leg | Result |
|---|---|
| Discovery | issuer `https://idp.NAME` (no path, no trailing slash); `RS256` only; **no `revocation_endpoint`** |
| First claim (setup token) | owner session through a Pocket ID passkey |
| Later login | owner session |
| Another Pocket ID user | refused: `?auth_error=oidc_identity_refused`, audit `auth.oidc_identity_refused` |
| MCP link, as shipped | **fails**: Pocket ID answers `/authorize` with `303 … error=invalid_request` ("The 'resource' or 'scope' parameter is invalid") before any sign-in; the client gets no code |
| MCP link, `/mcp` registered as an API in Pocket ID | works end to end, first refresh included |
| Refresh + `initialize` with the saved link | 200 / 200 |
| Provider token expired (lifetime set to 1 min), then a tool call | 200; exactly **1** upstream token call (the transparent refresh) |
| Two refreshes of one refresh token at once | `[200, 401 invalid_grant]`; exactly **1** upstream token call; the winner's next refresh 200, `initialize` 200 |
| Pocket ID itself: a rotated refresh token presented again | 400 `invalid_grant` — and the rotated one is then **also** 400 `invalid_grant` |
| Restart Pocket ID, then a tool call + refresh | 200; 200 / 200 |
| Restart plamotrack's api, then a tool call + refresh | 200; 200 / 200 |
| Client revokes at `/mcp/revoke` | 200; refresh 401 `invalid_grant`; old access token 401; audit `auth.mcp_grant_revoked` |
| Pocket ID `export` → `down -v` → `import` | the owner signs in (same `sub`); the live MCP link refreshes 200 / 200 |
| Restored data under another `ENCRYPTION_KEY` | Pocket ID does not start: restart loop, "failed to decrypt key"; the right key restores it |
| Owner's passkey deleted at Pocket ID | "We couldn't verify your passkey"; a login code and a new passkey; plamotrack owner again, no rebind |

## 1. The browser login works unchanged

Nothing in plamotrack needed changing. Pocket ID's id_token is `RS256`, `aud` is a
one-element array (`validate_id_token_claims` already accepts that), `azp` is absent
(optional there), `iat` and `nonce` are present. The login asks `openid email
profile`, so Pocket ID's consent screen lists Email and Profile the first time a user
signs in to the client, then remembers it.

## 2. The MCP link is blocked by one parameter, and it is ours to stop sending

FastMCP's `OAuthProxy` forwards the downstream client's RFC 8707 `resource` on the
upstream authorize request by default (`forward_resource=True`, FastMCP 4.0.3
`oauth_proxy/proxy.py:904`), and `PlamotrackOAuthProxy` does not change it. The
`resource` names plamotrack's own `/mcp/`, whose authorization server is the proxy;
the provider issues tokens for plamotrack's OIDC client and has no business with
that URI. Google and Keycloak ignore it; Pocket ID implements RFC 8707 and refuses a
resource it does not know. `probe.py matrix`, one parameter varied at a time against
Pocket ID's `/authorize`:

| Upstream authorize request | Pocket ID |
|---|---|
| as the proxy sends it (`scope=openid`, `resource`, `access_type=offline`, `prompt=consent`) | refused, `invalid_request` |
| the same without `resource` | accepted |
| `resource` alone; without its trailing slash; naming the provider itself | refused, `invalid_request` |
| `scope=openid`; `scope=openid offline_access` | accepted |
| `access_type=offline` alone; `prompt=consent` alone | accepted |

So the Google-specific parameters (`UPSTREAM_AUTHORIZE_PARAMS`, `mcp_oauth.py:400`)
are harmless here, and `resource` is the whole problem.

**Two ways past it.** (a) Configuration only: register `<PUBLIC_BASE_URL>/mcp` as an
API in Pocket ID (Admin → APIs) and grant the plamotrack client user-delegated
access. Measured: everything in §3 ran this way. Pocket ID then audiences the
*access* token to that URI; plamotrack never reads it (`GrantVerifier` treats the
upstream token as opaque), and the id_token keeps `aud` = the client. (b) The app
change: `forward_resource=False` in `PlamotrackOAuthProxy`, which makes the extra
registration unnecessary and is the semantically right request for every provider.
Not measured here — no test build ran — so it is its own issue with its own
evidence, per #280's acceptance: #294.

## 3. With the resource accepted, the rest of the MCP contract holds — and Pocket ID tests it harder than Google

Pocket ID issues a refresh token on the code exchange without `offline_access`,
rotates it on every refresh, and treats a rotated token presented again as theft:
the replay *and* the token that replaced it are both refused afterwards (measured,
`probe.py reuse`). Google does not rotate. Against Pocket ID, two refreshes of one
grant reaching the provider at once would end the grant; the proxy's per-grant
advisory lock (rule 13, "one transition per grant") is what prevents it, and the
race above shows it working — the loser is refused at the proxy with the SDK's
`401 invalid_grant` (the status `tests/test_mcp_oauth.py` asserts) and never reaches
Pocket ID.

The transparent refresh behind a request, restarts of either service and
revocation behaved as the deployment gate expects of Keycloak. Every refresh passed
the grant record's identity check, which admits an upstream refresh only with a
verified id_token naming the grant's `(iss, sub)` or with none; which of the two
Pocket ID returns on refresh was not recorded.

**Revocation is local only.** Pocket ID publishes no `revocation_endpoint`, so
`/mcp/revoke` ends the grant in plamotrack and the best-effort upstream revoke has
nothing to call. Pocket ID's refresh token then lives until its own lifetime (30 days
by default, per client) or until the user removes plamotrack from Pocket ID's
authorized apps from their own settings (the route is
`DELETE /api/oidc/users/me/authorized-clients/:clientId`; the page was not driven).
Nothing in plamotrack accepts it once the grant has ended, so this is a note for the
docs, not a defect.

## 4. Backup, restore and recovery

- **Backup set.** Pocket ID's documented `pocket-id export` (marked experimental
  upstream) produces a zip of `database.json`, `francis.bin` and uploads. Imported
  into a destroyed-and-recreated volume it restored passkeys, the user's `sub`, the
  signing key (it lives encrypted in the database — the wrong-key leg below is
  Pocket ID failing to load it from there) and live upstream refresh tokens — an MCP
  link made before the export refreshed afterwards. **`ENCRYPTION_KEY` is part of the
  set:** the signing keys are encrypted with it in the database, and under another
  key Pocket ID does not start at all. The conservative alternative is a cold copy of
  the data volume, not measured here.
- **Lost passkey, identity kept.** An admin login code (Admin → Users, or
  `docker compose exec pocket-id /app/pocket-id one-time-access-token <user>`) signs
  the user in to add a new passkey; the `sub` does not change, so plamotrack's
  binding holds with no host-side step. Rebinding is for a *different* identity:
  `recovery rebind-oidc` (unchanged, gated elsewhere). The login-code route needs a
  Pocket ID admin, which in a single-owner install is the owner — so losing the only
  passkey with no other admin and no shell on the host is the unrecoverable case
  (email login codes, off by default, are Pocket ID's other route; not measured).

## 5. Operator notes the recipe has to carry

- Pocket ID needs its own hostname (`APP_URL` takes no path), HTTPS (passkeys need a
  secure context, and the passkey's RP ID is that hostname — changing it later
  orphans every passkey), a persistent volume, and `ENCRYPTION_KEY` kept with the
  backups.
- A client created in Pocket ID's admin UI is **group-restricted by default**
  (`oidc-client-form.svelte`: `isGroupRestricted ?? true`). Either put the owner in an
  allowed group or clear the restriction. (The probe created its client through the
  API with the restriction off; the UI path is not measured.)
- Both callbacks go on one client: `<PUBLIC_BASE_URL>/api/auth/oidc/callback` and
  `<PUBLIC_BASE_URL>/mcp/auth/callback`.
- Pocket ID's access log records a login code in the request path when it is
  exchanged (`/api/one-time-access-token/<code>`). Single-use and short-lived, but a
  credential in a log; worth a line wherever the docs discuss Pocket ID's logs.
- Pocket ID's lack of dynamic client registration does not matter: MCP clients
  register with plamotrack's proxy, which is one fixed client at Pocket ID.

## 6. Setup and maintenance burden against the existing route

Measured only for Pocket ID; the Google route is the one the owner's own instance
runs and is not re-measured here.

| | Pocket ID | Google (the existing route) |
|---|---|---|
| Extra service | one container + volume | none |
| Names and TLS | a second hostname with a certificate | none beyond plamotrack's |
| Provider registration | one client in Pocket ID's admin UI (+ the API registration until §2's change lands) | a Google Cloud project, an OAuth client and a consent screen |
| Secrets to keep | `ENCRYPTION_KEY`, the client secret | the client secret |
| Backups | Pocket ID's export or volume, with `ENCRYPTION_KEY` | nothing of the provider's |
| Owner's sign-in | a passkey; nothing depends on a third party | a Google account |
| Losing access | a login code from a Pocket ID admin or the host's shell keeps the identity | Google's own recovery; `rebind-oidc` otherwise |

## 7. The owner's legs — real devices and Claude.ai, through a Cloudflare Tunnel

Run 2026-09-23 by the owner, the evidence read back from plamotrack's audit rows,
nginx's access log and Pocket ID's. The spike's plamotrack moved behind the gate's
Cloudflare Tunnel with the gate's tunnel settings (`probe.py tunnel`: `WEB_BIND` on
the host's LAN address, `PUBLIC_BASE_URL` the tunnel's name, `TRUSTED_PROXIES` the
connector — nginx saw the connector before it was trusted and exactly the
workstation's public address after). Pocket ID stayed on its own name behind Caddy,
**resolvable only inside the owner's network**; the client gained the tunnel's two
callbacks, and the tunnel's `/mcp` was registered as a second Pocket ID API (§2a is
per URI).

| Leg | Evidence |
|---|---|
| A real passkey, desktop | Chrome on macOS; saved to **Proton Pass** (Pocket ID records AAGUID `50726f74-6f6e-5061-7373-50726f746f6e`, "Proton Pass Passkey", backup-eligible and backed up, transports `internal` + `hybrid`) |
| The same passkey, phone | Chrome on Android, the passkey synced by Proton Pass: Pocket ID's `webauthn/login` start → finish, then plamotrack's `auth.login_succeeded` |
| Claude.ai as a custom connector | a CIMD client (no `/mcp/register` request): discovery → `/mcp/authorize` → consent → Pocket ID (the desktop passkey) → callback → `/mcp/token` → `auth.mcp_grant_issued`; tool calls `POST /mcp` 200 |
| Claude.ai after the provider's token expired | a call 6½ minutes after the link, Pocket ID's lifetime still 1 minute: the proxy's refresh at Pocket ID's token endpoint (200) in the same second, the call 200, no diagnostics in the api log; Claude.ai itself never refreshed (its token from the proxy lasts an hour) |
| Browser write through the tunnel | `POST /api/kits` 201 with the owner's session; the same request with a foreign `Origin` 403 `ingress.origin_not_allowed` |

**The provider only has to be reachable by the owner's browser.** Claude.ai's
servers talk to plamotrack alone — discovery, the token endpoint, `/mcp` — and the
proxy reaches Pocket ID's token endpoint from the api container. So a cloud MCP
client linked through an identity provider the internet cannot reach. On a hosted
platform the owner's browser is on the internet too, so in practice the provider is
public there; the finding matters for #282's private-network and VPS cases.

Not run: a platform authenticator (iCloud Keychain, Google Password Manager); the
cross-device QR sign-in (the phone signed in directly with the synced passkey); a
device off the owner's network; the client created in Pocket ID's UI (§5); Pocket
ID on a hosting platform (#279).

### Without the workaround, on the #294 build (2026-09-25)

The same tunnel, Pocket ID client and callbacks, with plamotrack's api the #294
branch's image (`plamotrack-api:294-spike`; web and db the v0.5.2 release) and **no
API registered in Pocket ID** (`GET /api/apis` → 0). The owner removed the Claude.ai
connector from the earlier run and added it again; the evidence is read back as
before.

| Leg | Evidence |
|---|---|
| The old link | Claude.ai still presented the refresh token from the earlier link, made under §2a, although the connector had been removed. The proxy's upstream refresh was refused by Pocket ID (`400 invalid_request`, fosite's `ExactAudienceMatchingStrategy`: the grant's audience names an API no longer registered), `/mcp/token` answered 401, and Claude.ai asked the owner to reconnect |
| The reconnect | discovery → `/mcp/authorize` → consent → Pocket ID `/authorize` with `response_type`, `client_id`, `redirect_uri`, `state`, `scope=openid`, `code_challenge`, `code_challenge_method`, `access_type`, `prompt` — **no `resource`** — accepted (302) → the Proton Pass passkey (`webauthn/login` start → finish) → callback → upstream token 200 → `/mcp/token` 200 → `auth.mcp_grant_issued` (a CIMD client: no `/mcp/register`) |
| Tool calls | `POST /mcp` 200, six requests |
| Past the provider's 1-minute token | the next request, a minute after the link: the proxy's refresh at Pocket ID's token endpoint (200) in the same second, the call 200 |

**A link made under §2a needs one reconnect once the API registration is removed.**
Pocket ID will not refresh a grant whose audience names an API it no longer has, so
the grant ends at the proxy and the client authorizes again; Claude.ai prompts for
it, and the reconnect is the ordinary link. Not measured: the #294 build with the
registration left in place — nothing in the request names it any more, so it should
be inert, but the measured path is remove it and reconnect once.

## 8. Decision (the owner's, 2026-09-25)

Pocket ID is an **optional supported provider**. The owner's reason: it makes
setting up OAuth for an assistant much easier. Both conditions the draft
recommendation set held: the `resource` change (§2) landed as #294 (`ee458f4`) with
its own tests, and a real passkey and a real client linked without §2a (§7, last
subsection).

- **Documented from the release that ships #294.** The docs describe the published
  release, and v0.5.2 still forwards `resource`; the page is owed in
  `.agents/next-release.md`. It carries §5's operator notes, §4's backup set
  (`ENCRYPTION_KEY` with it) and lost-passkey route, revocation being local only
  (§3), and the one reconnect above for anyone who used §2a.
- **Not bundled by this decision.** Whether the hosting templates include it is
  #281's call with #279's platform, because it is a second public service with its
  own name, volume and backup item — on Render roughly a third more cost, on Railway
  about a dollar. #282's VPS path can document it beside the reference Caddy; §7's
  reachability finding (the provider need not be public) applies there.
- **§2a is not advertised.** Anyone already running v0.5.2 that way keeps working
  until they upgrade.
