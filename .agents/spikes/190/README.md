# #190 spike harness — FastMCP OAuth proxy against real providers and clients

Evidence, not code: nothing here is imported by the app. `findings.md` is the
draft of the comment for #190 (the legs that ran locally); `access.log` is the
per-client request record those findings quote; `probe_a.json` / `probe_a2.json`
are the raw phase-A outputs. Runs from `backend/`'s venv against the locked tree.

## Phase A — no network (route table, response profile, redirect binding, keys)

```bash
cd .agents/spikes/190 && ../../../backend/.venv/bin/python probe_a.py    # → probe_a.json
../../../backend/.venv/bin/python probe_a2.py                              # BoundProxy, consent deny, https cookies, bytes key
../../../backend/.venv/bin/python probe_a3.py                              # a no-store middleware leaves the cookies alone
```

## Phase B — Keycloak + a probe server behind `OIDCProxy`

```bash
(cd keycloak && docker compose up -d --wait)       # http://localhost:8081, realm "plamotrack": owner / owner-password, stranger / stranger-password
python3 -c 'import os;print(os.urandom(32).hex())' > jwt_key.hex
./restart.sh "$PWD/store" "$(cat jwt_key.hex)"     # probe server on :8000; env knobs at the top of probe_b_server.py
../../../backend/.venv/bin/python probe_b_flow.py link owner owner-password   # scripted MCP client: DCR → consent → Keycloak → token → initialize → whoami → refresh
../../../backend/.venv/bin/python probe_b_flow.py verify <label>              # refresh + initialize with the saved state (T13)
```

`restart.sh` reads `SPIKE_VERIFY_ID_TOKEN=1`, `SPIKE_OWNER_SUB=<sub>`,
`SPIKE_OWNER_AT_ISSUANCE=1`, `SPIKE_PG_URL=postgresql://…` and `SPIKE_BARE_OPENID=1`
from the environment. Every request lands in `access.log` (method, path, status,
Origin, User-Agent, `Bearer`-or-not, `Location`, `Cache-Control` — never a token).

MCP Inspector: `npm install @modelcontextprotocol/inspector@2.5.0` somewhere
scratch, `MCP_AUTO_OPEN_ENABLED=false node_modules/.bin/mcp-inspector`, add a
Streamable HTTP server at `http://127.0.0.1:8000/mcp/`, connect.

## Phase C — the packaged nginx in front of the probe

```bash
docker build -t plamotrack-web-spike ../../../frontend
(cd nginx && docker compose up -d)                 # http://127.0.0.1:8082 → socat "api" → host :8000
../../../backend/.venv/bin/python probe_c_ingress.py
```

## The remaining legs (owner-supplied)

- Google: an OAuth client (Web application) with redirect `<base>/mcp/auth/callback`;
  `SPIKE_OIDC_CONFIG_URL=https://accounts.google.com/.well-known/openid-configuration
  SPIKE_CLIENT_ID=… SPIKE_CLIENT_SECRET=… SPIKE_VERIFY_ID_TOKEN=1`.
- Claude web / ChatGPT web: a public `https://` tunnel to :8000, `SPIKE_BASE_URL=https://<host>`,
  the upstream client's redirect updated to match; read `access.log` per client.

Tear-down: `pkill -f probe_b_server.py`; `(cd nginx && docker compose down)`;
`(cd keycloak && docker compose down -v)`.
