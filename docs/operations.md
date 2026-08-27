# Running an instance

Backing up, restoring, and upgrading the bundled Docker Compose stack.

> **This stack has no authentication yet.** It binds to `127.0.0.1` by default and
> belongs on a machine you trust. Exposing it to a network — or the internet —
> means anyone who can reach the port owns your collection. Authentication and a
> tested remote-access path are Milestone 6.

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
| `WEB_BIND` | `127.0.0.1` | The interface the stack listens on. Leave it here until M6. |
| `WEB_PORT` | `8080` | Host port for the UI, `/api`, and `/mcp`. |
| `REFERENCE_CURRENCY` | `AUD` | Your currency — **first-run bootstrap only**. The migration seeds it into the instance settings; after that the database row is the setting (`PATCH /settings`), and editing the env var does nothing. Changing the setting affects new entries only — stored snapshots keep the currency they were recorded in. |
| `DATABASE_URL` | — | Set it to use a Postgres you manage yourself; the `POSTGRES_*` values then only configure the bundled `db`. |

Changes to `.env` need `docker compose up -d` to take effect.

### Bootstrap vs runtime settings

Interface language, formatting locale, time zone, date style, hour cycle, and the
reference currency are **runtime settings**: they live in the database (the
one-row `instance_settings` table), so every browser and agent sees the same
values. Read them with `GET /api/settings`, change them with `PATCH /api/settings`. The
Settings page shows them all; its General section changes the reference
currency, and browser controls for the language and regional settings are still
to come (they're API-only for now). A fresh install bootstraps them once:
`en-AU` interface language and formatting locale, `UTC` time zone, locale-default
date style and hour cycle, and the reference currency from `REFERENCE_CURRENCY`
in `.env`. After that first migration the env var is inert. The full-archive
export includes the settings row and a restore updates it in place — details in
`docs/import-export.md`.

## Reaching it from another machine

Running it on a NAS, a home server, or a VM and wanting to use it from your laptop
is the normal case. The default `WEB_BIND=127.0.0.1` means only the machine
*running* it can connect, so this needs a decision from you rather than a flag.

Start from what's actually true: **nothing in plamotrack is authenticated yet.**
There is no login, and `/api` and `/mcp` accept writes and deletes from anyone who
can reach the port. So the question isn't "how do I open the port", it's "who
should be able to reach this, and what's doing the deciding". Three answers, best
first.

### 1. Don't open it — tunnel to it

Nothing to configure, nothing exposed, and it works from anywhere you can SSH:

```bash
ssh -N -L 8080:127.0.0.1:8080 you@your-server
```

`http://localhost:8080` on your laptop is now the instance. `WEB_BIND` stays on
loopback. SSH is doing the authentication, which is the part plamotrack can't do
yet. Best option for occasional use from one or two machines.

### 2. Put it on a private network

A WireGuard-based mesh (Tailscale, Netbird, headscale, plain WireGuard) gives the
server an address only your own devices can route to. Bind to *that* interface
rather than to everything:

```bash
WEB_BIND=100.x.y.z    # the server's address on the private network, not 0.0.0.0
```

Now the app is reachable from your phone and laptop, and from nothing else, with
the VPN deciding who's in. This is the best fit if you want it always-available on
your own devices. It's also the shape M6's authentication will slot into rather
than replace.

### 3. Bind to the LAN

```bash
WEB_BIND=0.0.0.0
```

Every device on the network can now reach it, and there is nothing to stop any of
them writing to it — a guest phone, a smart TV, anything that joins your Wi-Fi.
Reasonable on a network where you trust every device and every person; a bad idea
on a shared, office, or student-house network. **Never route this in from the
internet or put it on a public-facing interface.** Use option 1 or 2 instead until
M6 lands.

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

### What about HTTPS and a login?

That's Milestone 6: single-owner browser authentication, scoped API/MCP tokens,
and a *tested* TLS reverse-proxy configuration. Putting a proxy in front of this
today can give you HTTPS and a password prompt, and some people will want that —
but a config here that hasn't been tested against the MCP streaming path would be
a liability rather than a help, so this document won't pretend to supply one yet.
If you do build your own, `frontend/nginx.conf` documents the two settings a proxy
in front of MCP has to get right.

## When something's wrong

**`up --wait` hangs or fails.** Find the unhealthy service:

```bash
docker compose ps
```

**The UI loads but everything is empty and the console shows failed requests.**
The API isn't ready. `docker compose logs api` — and note that `/api/readyz`
reports whether it can actually reach Postgres, while `/api/healthz` only says the
process is alive.

**`password authentication failed`.** `POSTGRES_PASSWORD` changed after the
database volume was created. Postgres only reads it when initialising an empty
data directory. Either put the old value back, or `docker compose down -v` and
restore from a backup — that flag deletes the database.

**Port already in use.** Something else has 8080. Set `WEB_PORT` in `.env`.

**MCP client connects but hangs.** Check you're on `http://…/mcp/`. Both spellings
work through the bundled ingress, but a client pointed at a *different* proxy you
put in front of this one needs `proxy_buffering off` — MCP is a streaming
protocol, and a buffering proxy holds the response instead of passing it on. It
fails as a hang, not an error. `frontend/nginx.conf` is a working reference.
