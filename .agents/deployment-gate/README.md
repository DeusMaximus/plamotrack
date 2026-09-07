# The deployment gate — T12/T13 (design notes §5.8; #194)

Evidence and harness for mode R, run before a release: the packaged stack behind
the reference Caddy on a fresh host, the ingress matrix and a held MCP stream
through it, the two lockouts and their recoveries, OIDC mode signed in, a real
MCP client linked and the three restores from the two-part backup set, and the
same stack behind a Cloudflare Tunnel. The driver is `backend/deployment_gate.py`
(its docstring lists the phases); this directory holds what the host needs.
Nothing here is imported by the app.

## What the operator supplies

- A fresh Debian host (an unprivileged LXC with `nesting=1` does; a VM does) with
  root SSH, and a name for it that resolves where the run happens —
  `PLAMOTRACK_TEST_NAME` below. A second name, `idp.<name>`, at the same address
  for the Keycloak fixture. Split-horizon names work: DNS-01 writes only the
  `_acme-challenge` TXT record in the public zone.
- A Cloudflare API token with **both** Zone → DNS → Edit and Zone → Zone → Read on
  that zone (the caddy-dns/cloudflare module reads the zone id before editing a
  record; Cloudflare's "Edit zone DNS" template grants exactly these two), written by hand on
  the host to `/etc/caddy/cloudflare.env` as `CLOUDFLARE_API_TOKEN=…`, mode 0600.
  `host-prepare.sh` refuses to run until it exists and never prints it.
- For the tunnel phase: a public-hostname route on an existing Cloudflare Tunnel
  whose connector runs on another host, pointing at `http://<host LAN IP>:8080`,
  the connector's address (for `--tunnel-proxy`), and this workstation's public
  address as Cloudflare forwards it (for `--tunnel-visitor` —
  `curl -s https://cloudflare.com/cdn-cgi/trace | sed -n 's/^ip=//p'`), and the UI
  steps written down for `docs/operations.md`.

## Run

From the workstation, with the branch under test checked out:

```bash
# From macOS, COPYFILE_DISABLE=1 keeps tar from adding AppleDouble `._*` files — GNU tar
# extracts those as real files, and Alembic then tries to import `._<migration>.py`.
COPYFILE_DISABLE=1 tar czf - --exclude .git --exclude node_modules --exclude .venv \
      --exclude frontend/dist --exclude .env --exclude .agents/spikes --exclude __pycache__ . \
  | ssh root@HOST 'mkdir -p /opt/plamotrack && tar xzf - -C /opt/plamotrack'
ssh root@HOST 'PLAMOTRACK_TEST_NAME=NAME PLAMOTRACK_TUNNEL_NAME=TUNNEL-NAME \
      sh /opt/plamotrack/.agents/deployment-gate/host-prepare.sh'
ssh root@HOST 'cd /opt/plamotrack && docker compose up -d --build --wait'   # --build: AGENTS.md
cd backend && GATE_IDP_PASSWORD=owner-password uv run python deployment_gate.py \
      --base https://NAME --ssh root@HOST --idp https://idp.NAME \
      --phase all --results-out ../.agents/deployment-gate/results-$(date +%F).md
```

`host-prepare.sh` installs Docker Engine and Compose from Docker's repository,
Caddy from its repository with `caddy add-package github.com/caddy-dns/cloudflare`
(a rebuilt binary from caddyserver.com), renders `Caddyfile.test` — the reference
`deploy/caddy/Caddyfile` with the name filled in, plus the `idp.` site — into
`/etc/caddy/Caddyfile`, writes a `.env` with a generated database password and
no public name yet (the lockout phase supplies it), renders the Keycloak realm and
starts it on loopback behind Caddy. Re-running it is safe.

The driver keeps every secret of the run under `~/.plamotrack-gate/<name>/`
(mode 0600) and prints none; the results block it writes is what the release
notes and the PR body carry. Run the tunnel phase last, once the route exists,
with **four** tunnel arguments — the fourth, `--tunnel-visitor`, is this
workstation's public address exactly as Cloudflare forwards it, obtained
independently so the phase proves attribution rather than mere change:
```bash
VISITOR=$(curl -s https://cloudflare.com/cdn-cgi/trace | sed -n 's/^ip=//p')
… --phase tunnel --tunnel-base https://TUNNEL-NAME --tunnel-proxy <connector IP> \
  --host-ip <host LAN IP> --tunnel-visitor "$VISITOR"
```
(or add those four to `--phase all`).

## Files

- `Caddyfile.test` — the reference site block with `PLAMOTRACK_TEST_NAME` to fill in,
  and the Keycloak site beside it; `host-prepare.sh` renders it.
- `keycloak/docker-compose.yml`, `keycloak/realm.template.json` — the #190 spike's
  Keycloak, told its https name; the realm has `owner` / `owner-password` and
  `stranger` / `stranger-password`, one confidential client, and both names'
  browser and MCP callbacks. `realm.json` is the rendered copy (ignored).
- `host-prepare.sh` — the host side, idempotent.
- `results-*.md` — a run's results block, if kept here.

Tear-down is the operator's: the driver never removes anything, and the host is
theirs to keep or destroy.
