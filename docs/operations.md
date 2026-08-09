# Running an instance

Backing up, restoring, and upgrading the bundled Docker Compose stack.

> **This stack has no authentication yet.** It binds to `127.0.0.1` by default and
> belongs on a machine you trust. Exposing it to a network — or the internet —
> means anyone who can reach the port owns your collection. Authentication and a
> tested remote-access path are Milestone 6.

## What's running

`docker compose up -d --wait` gives you four things:

| Service | What it is | Published? |
| --- | --- | --- |
| `web` | nginx: the UI, plus `/api` and `/mcp` proxied to the API | **yes** — `127.0.0.1:8080` |
| `api` | FastAPI + the MCP server, one process | no |
| `migrate` | runs `alembic upgrade head`, then exits | no |
| `db` | Postgres 16 | loopback only, for local tooling |

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
docker compose exec -T db pg_dump -U plamotrack -Fc plamotrack > plamotrack-$(date +%F).dump
```

**The CSV archive — portable copy.** Readable, diffable, and importable into a
future version whose schema has moved on. Slower to restore and it won't preserve
ids exactly, but it survives things a dump doesn't. Grab it from **Data → Export**
in the UI, or:

```bash
curl -o plamotrack-archive.zip http://127.0.0.1:8080/api/export/archive
```

Keep both. The dump is what you restore from on Sunday; the archive is what still
opens in three years. See [import-export.md](import-export.md) for the format.

### Restoring a dump

Into an **empty** database — `pg_restore` will not merge cleanly into a populated
one:

```bash
docker compose down -v          # destroys the current database. See the warning below.
docker compose up -d db --wait
docker compose exec -T db pg_restore -U plamotrack -d plamotrack --clean --if-exists < plamotrack-2026-08-10.dump
docker compose up -d --wait
```

> `docker compose down -v` deletes the `db-data` volume, which **is** your
> collection. Without `-v` the volume survives and `down` is safe. Take a backup
> first regardless.

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

## Configuration

Everything lives in `.env` at the repo root — one file, read by both Compose and
the API. `.env.example` documents every key. The ones worth knowing:

| Key | Default | Notes |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | — | Required. Only read when the database volume is first created. |
| `WEB_BIND` | `127.0.0.1` | The interface the stack listens on. Leave it here until M6. |
| `WEB_PORT` | `8080` | Host port for the UI, `/api`, and `/mcp`. |
| `REFERENCE_CURRENCY` | `AUD` | Your currency. Changing it affects new entries only — stored snapshots keep the currency they were recorded in. |
| `DATABASE_URL` | — | Set it to use a Postgres you manage yourself; the `POSTGRES_*` values then only configure the bundled `db`. |

Changes to `.env` need `docker compose up -d` to take effect.

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
