# #280 spike harness — Pocket ID for the owner login and MCP OAuth

Evidence, not code: nothing here is imported by the app. `findings.md` is the
report (the draft of the #280 comment); `probe.py` is the driver; `sequence.sh` runs
every step in order; `pocket-id/docker-compose.yml` is the provider, pinned by digest.

The driver reuses the deployment gate (`backend/deployment_gate.py`): its host over
ssh, `oidc_login`, `mcp_link` and `mcp_verify`. It replaces only the provider's
sign-in. The gate fills Keycloak's password form over HTTP; Pocket ID has no
password, so the probe signs in with a passkey in headless Chromium through a CDP
virtual authenticator, whose private keys it keeps in the state directory between
steps. Real authenticators (a phone, a computer) are the owner's legs, below.

## The host

The deployment gate's host as `host-prepare.sh` leaves it — Caddy with DNS-01 in
front of `NAME` → `127.0.0.1:8080` and `idp.NAME` → `127.0.0.1:8081` — with the gate's
stack in `/opt/plamotrack` (a release install) and its Keycloak on 8081.

`prepare` stops both (volumes kept), starts Pocket ID on 8081 so Caddy fronts it
unchanged, creates the `plamotrack` client through Pocket ID's admin API
(`STATIC_API_KEY`), and starts a second plamotrack from the same release files in
`/opt/plamotrack-280` under its own Compose project, so its database is new and the
first claim is real. `teardown` removes the spike's stacks, volumes and directory
and starts the gate's stack and Keycloak again.

The Keycloak container's `realm.json` bind mount is the path it was created with; if
the gate's tree has moved since, `docker start` fails until the file is back at that
path. Recreating the container instead re-imports the realm with new user ids, which
changes the owner's `sub` and needs `recovery rebind-oidc` on the gate's collection.

## Run

From `backend/`, with Playwright alongside (never added to the lock):

```bash
sh ../.agents/spikes/280/sequence.sh https://NAME root@HOST      # every step, in order
uv run --with 'playwright==1.62.*' python ../.agents/spikes/280/probe.py <step> \
    --base https://NAME --ssh root@HOST                           # one step
uv run --with 'playwright==1.62.*' python ../.agents/spikes/280/probe.py teardown \
    --base https://NAME --ssh root@HOST
```

The first `uv run --with playwright` downloads the package; Chromium comes from
`frontend/`'s Playwright install (`npx playwright install chromium`) when the
versions match. Rows append to `.dev/280/log.md` and screenshots land beside it (both
gitignored). Secrets — Pocket ID's `ENCRYPTION_KEY` and API key, the client secret,
the passkeys, the session cookie, the MCP link — live in
`~/.plamotrack-gate/spike-280/` (mode 0600) and are never printed; the enrol rows
print Pocket ID's user ids, which are not secrets. Pocket ID's own access log is
another matter: it records a one-time login code in the request path when the code
is exchanged (`/api/one-time-access-token/<code>`) — single-use and short-lived, but
a credential in a log all the same.

## The owner's legs

Real devices and a real MCP client (findings §7). A cloud client needs plamotrack
reachable from the internet, so `probe.py tunnel` first moves the spike's plamotrack
behind a Cloudflare Tunnel the way the gate's tunnel phase does — `--base` becomes the
tunnel's name, and `--idp` keeps Pocket ID on its own:

```bash
VISITOR=$(curl -s https://cloudflare.com/cdn-cgi/trace | sed -n 's/^ip=//p')
uv run --with 'playwright==1.62.*' python ../.agents/spikes/280/probe.py tunnel \
    --base https://TUNNEL-NAME --ssh root@HOST --idp https://idp.NAME \
    --host-ip <host LAN IP> --tunnel-proxy <connector IP> --tunnel-visitor "$VISITOR"
uv run --with 'playwright==1.62.*' python ../.agents/spikes/280/probe.py api-resource add \
    --base https://TUNNEL-NAME --ssh root@HOST --idp https://idp.NAME
```

Then a login code for the Pocket ID user the instance is bound to (the documented
recovery command, run on the host), a real passkey added from it, and the sign-ins and
the MCP client driven by hand:

```bash
ssh root@HOST 'cd /opt/plamotrack-280/pocket-id && docker compose exec pocket-id /app/pocket-id one-time-access-token owner'
```

The evidence is read back afterwards from plamotrack's `audit_event` rows, nginx's
access log and Pocket ID's (devices by user agent, upstream refreshes by the token
route), never from the clients.

Tear-down: `probe.py teardown`, then `rm -rf ~/.plamotrack-gate/spike-280` when the
evidence is no longer wanted.
