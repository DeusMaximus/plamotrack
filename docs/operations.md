# Running an instance

Backing up, restoring, and upgrading the bundled Docker Compose stack.

> **This instance has a single owner login.** Since M6-3 every collection route
> requires the owner's browser session: a fresh install comes up *unclaimed* and
> prints a one-time setup token to the API log — see [First run](#first-run-claim-the-instance).
> Scripts and MCP clients authenticate with a [personal access token](#access-tokens)
> instead. There is still **no TLS** here — a tested HTTPS reverse-proxy path is the
> rest of Milestone 6 — so keep an instance on a network you trust. It also answers
> only to names you list; reach it by any other name and it says
> `421 Misdirected Request`; see [Names it answers to](#names-it-answers-to).

## First run: claim the instance

A fresh install (and an existing instance upgraded onto M6-3) starts **unclaimed**:
every collection route answers `401` and the UI shows a setup screen. Claim it once:

```bash
docker compose logs api | grep -A6 "no owner yet"
```

The API prints a one-time **setup token** at every start while the instance is
unclaimed. Copy it, open the instance in a browser, and enter the token with the
owner password you want. That's it — the token is single-use, and the instance
stops printing one once claimed. Lost the token? Restart the container
(`docker compose restart api`) and read the fresh one from the log.

After that, one owner password signs you in from any browser on the trusted
network. Sign out from the sidebar. Forgot the password? See
[Recovery](#recovery-locked-out).

### Recovery: locked out

If you forget the password, reset it from **inside the API container** — never over
the network:

```bash
docker compose exec api python -m app.auth.recovery reset-password
```

It prompts for a new password, sets it, and signs every browser out. To sign
everyone out without changing the password, use `revoke-sessions` instead. Both
run only where you already have shell access to the host, which is the point.
Neither touches access tokens — revoke those from Settings once you are back in.

## Access tokens

The browser session is for people. A script, a cron job or an MCP client (Claude
Desktop, Claude Code, anything else that speaks MCP over HTTP) authenticates with a
**personal access token** instead: **Settings → Access tokens** in the app, owner
login required. A token looks like `ptk_<id>_<secret>`, is shown once when it is
created, and is stored only as a digest — if you lose it, revoke it and make
another. Send it as an `Authorization: Bearer ptk_…` header on the REST API
(`/api/…`) and on the MCP endpoint (`/mcp/`). **Never put a token in a URL:** a
query parameter is ignored as a credential, but request URIs are what access
logs record — nginx's and the API's both go to `docker compose logs` — so a token
there is a token in your logs. The README's *Wiring up the MCP server* section has
the Claude Desktop and Claude Code configuration.

What a token can do is chosen when it is minted and never widens:

- **Read-only** — list and look up: kits, orders, the catalog, retailers, settings,
  the CSV exports.
- **Read and write** — the above plus adding kits and catalog items, recording and
  editing orders, adjusting stock, applying upgrades, and CSV import in `merge` or
  `add_only` mode.

No token can change the instance settings, run a `replace_all` import, or manage
tokens — those stay with the owner login, so a leaked token cannot lock you out or
erase the collection. An optional expiry (30, 90 or 365 days) is offered at
creation. The list shows when each token was last used; **Revoke** stops it
immediately and keeps the row as a record. The MCP endpoint takes *only* a token —
the browser's session cookie never authenticates it, by design, so a page in your
browser cannot drive an agent's tools. Minting, revoking, and any use of a revoked
token are recorded in the audit table.

## Security audit retention

Security-relevant authentication and ingress events are kept in Postgres's
`audit_event` table: owner claim, login success/failure/throttling, logout and
session revocation, token mint/revocation/use-after-revocation, host-side recovery,
and app-layer Host/Origin refusals. Rows carry the credential's kind and id when
one exists, the resolved client address, and the route or tool — never a request
body, query string, or secret. The bundled nginx rejects an unknown Host before
it can reach the API, so that outer refusal is in nginx's access log; the app's
defence-in-depth Host refusal is the database event. Collection edits are not
audited in Milestone 6.

The table is append-only during normal operation. Retention is the operator's
choice; this host-side command deletes rows older than 180 days and appends a row
recording the prune itself:

```bash
docker compose exec api python -m app.auth.recovery prune-audit --older-than-days 180
```

Use a different positive day count if your policy requires it. Take a database
backup first if those events must remain available elsewhere.

## What's running

`docker compose up -d --build --wait` gives you four things:

| Service | What it is | Published? |
| --- | --- | --- |
| `web` | nginx: the UI, plus `/api` and `/mcp` proxied to the API | **yes** — `127.0.0.1:8080` |
| `api` | FastAPI + the MCP server, one process | no |
| `migrate` | runs `alembic upgrade head`, then exits | no |
| `db` | Postgres 16 | no — Compose network only |

Only `web` is reachable, so an instance has one door. `migrate` showing as
`Exited (0)` is what success looks like — it's a startup step, not a service.

The API is deliberately not published. Anything you'd have pointed at
`localhost:8000` now goes through the ingress: `http://localhost:8080/api/…`, and
MCP at `http://localhost:8080/mcp/`.

## Backups

Two kinds, and they answer different questions.

**`pg_dump` — exact restore.** Everything, byte for byte, including ids and
timestamps. This is your disaster-recovery copy.

```bash
docker compose exec -T db sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' \
  > plamotrack-$(date +%F).dump
```

**The CSV archive — portable copy.** Readable, diffable, and importable into a
future version whose schema has moved on. Slower to restore and it won't preserve
ids exactly, but it survives things a dump doesn't. Grab it from
**Settings → Data management → Export** in the UI, or:

```bash
curl -o plamotrack-archive.zip http://127.0.0.1:8080/api/export/archive
```

Both are point-in-time: the archive is read from a single database snapshot, so
taking one while the app is in use — an agent adding an order mid-download — gives
you the collection as it stood when the export began reading, never a mix of
before and after.

Keep both. The dump is what you restore from on Sunday; the archive is what still
opens in three years. See [import-export.md](import-export.md) for the format.

### Restoring a dump

Into an **empty** database — `pg_restore` will not merge cleanly into a populated
one:

```bash
docker compose down -v          # destroys the current database. See the warning below.
docker compose up -d db --wait
docker compose exec -T db sh -c \
  'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
  < plamotrack-2026-08-10.dump
docker compose up -d --build --wait
```

> `docker compose down -v` deletes the `db-data` volume, which **is** your
> collection. Without `-v` the volume survives and `down` is safe. Take a backup
> first regardless.

The quoted variables are expanded inside the database container, so these commands
follow the active `POSTGRES_USER` and `POSTGRES_DB` values from `.env` rather than
assuming the defaults.

## Upgrading

```bash
git pull
docker compose up -d --build --wait
```

The `migrate` service applies any new migrations before the API starts, so
there's no separate step. If a migration fails, `up` exits non-zero and the API
is not started at all — you get a stopped deploy with a readable error rather
than a half-migrated database serving traffic. Check it with:

```bash
docker compose logs migrate
```

**Back up before upgrading.** Migrations run forward automatically; rolling one
back is a manual `alembic downgrade` and some are deliberately lossy about it.

### Upgrading to 0.2.10: set `ALLOWED_HOSTS` first

0.2.10 makes the instance refuse names it doesn't know
([Names it answers to](#names-it-answers-to)). If you reach it by anything other
than `localhost` or `127.0.0.1` — a LAN hostname, a container name, a mesh DNS
name, a reverse proxy — add that name to `ALLOWED_HOSTS` in `.env` **before** the
`docker compose up`, or the first thing you'll see afterwards is
`421 Misdirected Request`. It is recoverable (edit `.env`, `up -d` again, nothing
lost), but there is no reason to meet it by surprise. No migration in this release.

### If you imported CSVs before 0.2.7

Importers before 0.2.7 could leave a kit order line holding a different number of
kits than its quantity said. Nothing in the app minds, but an archive exported from
such a collection is refused when you try to restore it with *replace everything*
("this line says quantity N, but this upload supplies M kit(s)"). Check once, before
your next export:

```bash
docker compose exec -T db sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT oi.id, oi.quantity, count(k.id) AS kits
FROM order_items oi LEFT JOIN kits k ON k.order_item_id = oi.id
WHERE oi.item_type = 'kit'
GROUP BY oi.id, oi.quantity
HAVING count(k.id) <> oi.quantity;
SQL
```

No rows means nothing to do. For each row it lists, open that order in the app and
save the line — the order editor reconciles the count against the kits actually
there (it spawns the missing one, or leaves an extra one where it is once you set
the quantity to match). Then export again.

### If your database predates 2026-08-06 (the first public schema)

The migration that introduced pending/received orders marked every order that
existed before it as received — those orders had their stock applied at entry, so
they were received by definition. It did **not** touch the kits those orders had
spawned. A database that crossed that revision can therefore hold a received order
whose kit still says *Ordered* or *In transit*, which the app would never produce
on its own.

This is cosmetic, and it is deliberately not repaired by a later migration: a
repair running today would overwrite kit statuses set by hand since, which is
worse than the blemish. If you see such a kit, drag it to the right column (or
edit its status) — that is the whole fix. Fresh installations are unaffected; the
window was a single day of pre-public history.

## Configuration

Everything lives in `.env` at the repo root — one file, read by both Compose and
the API. `.env.example` documents every key. The ones worth knowing:

| Key | Default | Notes |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | — | Required. Only read when the database volume is first created. |
| `WEB_BIND` | `127.0.0.1` | The interface the stack listens on. Leave it on loopback unless you have read [Reaching it from another machine](#reaching-it-from-another-machine). A non-loopback address here is also a name the instance answers to. |
| `WEB_PORT` | `8080` | Host port for the UI, `/api`, and `/mcp`. |
| `ALLOWED_HOSTS` | — | Names you reach the instance by, beyond `localhost`, `127.0.0.1`, `[::1]`, `WEB_BIND` and the host of `PUBLIC_BASE_URL`: a LAN hostname, a container name, what a proxy forwards. Comma-separated, no ports; `*.home.arpa` wildcards work. Any other name gets **421** — [details below](#names-it-answers-to). |
| `PUBLIC_BASE_URL` | — | The address a browser uses, when it isn't `http://localhost:<WEB_PORT>`: scheme, host and port, nothing after. Its host is allowed automatically; behind an HTTPS proxy it is what makes the browser's `https://` origin the instance's own, and its scheme decides whether the session cookie is `Secure`. The MCP OAuth path (later in M6) will bind to it too, so choose the name you mean to keep. |
| `ALLOWED_ORIGINS` | — | Extra browser origins allowed to write, beyond the instance's own and loopback ones. Rarely needed. |
| `TRUSTED_PROXIES` | — | IPs or CIDRs of a reverse proxy whose `X-Forwarded-For` is believed for the client's address. nginx keys its per-client limits on that resolved address and the API records it in security audit events. Leave it empty without an extra proxy. |
| `REFERENCE_CURRENCY` | `AUD` | Your currency — **first-run bootstrap only**. The migration seeds it into the instance settings; after that the database row is the setting (`PATCH /settings`), and editing the env var does nothing. Changing the setting affects new entries only — stored snapshots keep the currency they were recorded in. |
| `DATABASE_URL` | — | Set it to use a Postgres you manage yourself; the `POSTGRES_*` values then only configure the bundled `db`. |

Changes to `.env` need `docker compose up -d` to take effect.

### Names it answers to

Since 0.2.10 the instance refuses a request whose `Host` header is not a name it
knows, with `421 Misdirected Request` and a JSON body naming the setting to fix. It
is the Host-allowlist half of the M6 threat model (design notes §5.6): a page in your
browser that points its own hostname at your instance (DNS rebinding) can no longer
talk to it. It is also the one setting here that can lock you out of your own
install, which is why it shipped as a release of its own.

Always known: `localhost`, `127.0.0.1`, `[::1]`, a `WEB_BIND` address that names an
interface, and the host of `PUBLIC_BASE_URL`. Everything else — `nas.lan`,
`plamotrack.home.arpa`, a container name, whatever a reverse proxy forwards — goes
in `ALLOWED_HOSTS`. Ports don't matter (`nas.lan:8080` is `nas.lan`), nor does a
trailing DNS dot or letter case; wildcards like `*.home.arpa` work (that leading
`*.` is the only wildcard form); a bare `*`, a `*:8080`, or a `*` anywhere else
is refused at startup, because an allowlist of everything is the hole the
setting closes. `WEB_BIND=0.0.0.0` names *nothing*, so the LAN
address or hostname you actually type still has to be listed.

**Locked out?** You typed a name into a browser or an MCP client and got 421. Nothing
was written and nothing is lost. Add the name:

```bash
# in .env
ALLOWED_HOSTS=nas.lan
```

then `docker compose up -d`. The API and the ingress read the same line, so that is
the whole fix. The SSH-tunnel path — `localhost:8080` on your laptop — never needs
it.

The Origin half: a write (`POST`, `PATCH`, `DELETE`) that arrives with an `Origin`
header — every browser sends one — must come from the instance's own origin, from a
loopback origin against a loopback name, or from a listed one; anything else is
`403` with the code `ingress.origin_not_allowed`. Scripts, `curl` and MCP clients
send no `Origin` and are not affected. Reaching the instance over plain HTTP by
one name and through an HTTPS proxy by another is the case for `PUBLIC_BASE_URL`
(the canonical one) plus `ALLOWED_ORIGINS` (the rest).

### Bootstrap vs runtime settings

Interface language, formatting locale, time zone, date style, hour cycle, and the
reference currency are **runtime settings**: they live in the database (the
one-row `instance_settings` table), so every browser and agent sees the same
values. Read them with `GET /api/settings`, change them with `PATCH /api/settings`. The
Settings page shows them all: General changes the reference currency, while
Language & region changes the interface language, formatting locale, time zone,
date style, and hour cycle. A fresh install bootstraps them once:
`en-AU` interface language and formatting locale, `UTC` time zone, locale-default
date style and hour cycle, and the reference currency from `REFERENCE_CURRENCY`
in `.env`. After that first migration the env var is inert. The full-archive
export includes the settings row and a restore updates it in place — details in
`docs/import-export.md`.

Existing instances upgrade to the same `en-AU`/UTC defaults. The configured time
zone applies prospectively when an import reads a naive CSV timestamp; existing
stored instants, dates, currency snapshots, and CSV identifiers are never
reinterpreted. Downgrading past the settings migration removes the settings row,
so record any changed values before a rollback and set them again after upgrading.

## Reaching it from another machine

Running it on a NAS, a home server, or a VM and wanting to use it from your laptop
is the normal case. The default `WEB_BIND=127.0.0.1` means only the machine
*running* it can connect, so this needs a decision from you rather than a flag.

Start from what's actually true. Collection and administrative access is
authenticated: the browser needs the owner login, and `/api` scripts and `/mcp`
clients need a [personal access token](#access-tokens) — only liveness and the
login/setup entry points answer without one. What plamotrack does **not** have yet is a
tested TLS path, so it speaks plain HTTP — and on a network you don't control, a
device on the path can read the session cookie or a token off the wire and use it.
So the question isn't only "who can reach the port", it's "who can see the
traffic". Three answers, best first.

### 1. Don't open it — tunnel to it

Nothing to configure, nothing exposed, and it works from anywhere you can SSH:

```bash
ssh -N -L 8080:127.0.0.1:8080 you@your-server
```

`http://localhost:8080` on your laptop is now the instance. `WEB_BIND` stays on
loopback. plamotrack still asks for the login and the token; SSH keeps them, and
everything else, off the network. Best option for occasional use from one or two
machines.

### 2. Put it on a private network

A WireGuard-based mesh (Tailscale, Netbird, headscale, plain WireGuard) gives the
server an address only your own devices can route to. Bind to *that* interface
rather than to everything:

```bash
WEB_BIND=100.x.y.z    # the server's address on the private network, not 0.0.0.0
ALLOWED_HOSTS=nas.tail1234.ts.net   # only if you'll use the mesh's DNS name rather than the address
```

Now the app is reachable from your phone and laptop, and from nothing else, and
the tunnel supplies the confidentiality plain HTTP lacks — the session cookie and
any token cross the wire encrypted. The bind address is a name the instance
answers to on its own; a mesh hostname is not, hence the second line. This is the
best fit if you want it always-available on your own devices.

### 3. Bind to the LAN

```bash
WEB_BIND=0.0.0.0
ALLOWED_HOSTS=nas.lan,192.168.1.10   # whatever you'll type into the address bar
```

`0.0.0.0` names nothing, so the second line is not optional: without it every
request from another machine is `421`. Every device on the network can now reach
the login — a guest phone, a smart TV, anything that joins your Wi-Fi — and, because
this is plain HTTP, any of them positioned on the path can read your session cookie
or a token in transit and use it. Reasonable on a network where you trust every
device and every person; a bad idea on a shared, office, or student-house network.
**Never route this in from the internet or put it on a public-facing interface.**
Use option 1 or 2 instead until the tested TLS path lands.

> ### ⚠️ On Linux, a published port ignores your firewall
>
> Docker inserts its own iptables rules to forward published ports into
> containers. That traffic is *forwarded*, not delivered to the host, so it never
> passes the `INPUT` rules `ufw` and `firewalld` mostly work with — `ufw deny 8080`
> typically will **not** block a published container port. Plenty of self-hosted
> services have ended up on the open internet exactly this way.
>
> The reliable control is the bind address, not the firewall: keep `WEB_BIND` on
> `127.0.0.1` or a private-network address, and let it decide who can connect.
> If you do need host-firewall rules to apply to Docker traffic, they belong in
> the `DOCKER-USER` chain.

### What about HTTPS?

The login landed in M6-3 and access tokens in M6-4 — see
[First run](#first-run-claim-the-instance) and [Access tokens](#access-tokens).
What is still to come in Milestone 6 is a *tested* TLS reverse-proxy
configuration. Putting a proxy in front of this today can give you HTTPS, and
some people will want that — but a config here that hasn't been tested against the
MCP streaming path would be a liability rather than a help, so this document won't
pretend to supply one yet.
On plain HTTP the session cookie cannot be marked `Secure` (a browser limitation),
so its confidentiality rests on the network being yours; set `PUBLIC_BASE_URL=https://…`
behind a TLS proxy and the cookie becomes `Secure` and `__Host-`-prefixed.
If you do build your own: `frontend/nginx/default.conf.template` documents the two
settings a proxy in front of MCP has to get right; the name it forwards goes in
`ALLOWED_HOSTS`; `PUBLIC_BASE_URL=https://…` is what lets the browser's `https://`
origin write; and `TRUSTED_PROXIES` names the proxy so rate limits and audit use
the client address rather than treating the proxy as one client.

## When something's wrong

**`up --wait` hangs or fails.** Find the unhealthy service:

```bash
docker compose ps
```

**The UI loads but everything is empty and the console shows failed requests.**
The API isn't ready. `docker compose logs api`, and `docker compose ps` for the
api healthcheck — it probes `/readyz` from *inside* the container, which is the
only place that answers (from outside, `/api/readyz` is deliberately 404 so a
stranger can't learn whether the database is up); `/api/healthz` only says the
process is alive.

**`421 Misdirected Request`, from a browser or an MCP client.** You reached the
instance by a name it doesn't know. [Names it answers to](#names-it-answers-to) —
add it to `ALLOWED_HOSTS`, `docker compose up -d`, nothing lost.

**`403` with `ingress.origin_not_allowed` on a save.** The page you saved from is
on an origin the instance doesn't recognise as its own — usually an HTTPS proxy in
front of a plain-HTTP instance. Set `PUBLIC_BASE_URL` to the address in your
browser's bar.

**`password authentication failed`.** `POSTGRES_PASSWORD` changed after the
database volume was created. Postgres only reads it when initialising an empty
data directory. Either put the old value back, or `docker compose down -v` and
restore from a backup — that flag deletes the database.

**Port already in use.** Something else has 8080. Set `WEB_PORT` in `.env`.

**MCP client connects but hangs.** Check you're on `http://…/mcp/`. Both spellings
work through the bundled ingress, but a client pointed at a *different* proxy you
put in front of this one needs `proxy_buffering off` — MCP is a streaming
protocol, and a buffering proxy holds the response instead of passing it on. It
fails as a hang, not an error. `frontend/nginx/default.conf.template` is a working
reference.
