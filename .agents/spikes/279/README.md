# #279 — quick-deploy platform: the paper comparison

Research, not a proof deployment. The owner chose **paper only for now** on
2026-09-23: record what the providers' documentation says, measure nothing that
needs an account, and come back to a proof deployment after #280. Nothing here is
a compatibility claim — #279's acceptance needs one candidate actually running the
stack, and neither has.

Collected 2026-09-23 from the providers' public documentation and pricing pages.
**Prices are estimates from list prices, not measured usage.** Where a fact rests on
a staff forum post or third-party evidence rather than documentation, it says so.

## The stack each candidate has to run

Four services from the release's `docker-compose.yml`: `web` (nginx, the only
public ingress), `api` (FastAPI, one uvicorn worker, MCP streamable HTTP on
`/mcp`), `migrate` (one-shot Alembic), `db` (Postgres 16 with a volume). Optionally
an identity provider (#280): Pocket ID is one small service with SQLite on a volume.

## Measured load — the owner's instance, 2026-09-23

A single-host release install of v0.5.2 in normal use, holding 116 kits, 80 orders,
73 inventory items and 27 retailers (the owner's `docker stats` and Postgres
queries, and the host's own graphs over a day):

| | |
|---|---|
| RAM | web (nginx) 3.7 MiB, api 119 MiB, db 30 MiB — **~152 MiB for the stack**; ~330 MiB for the whole host with its OS and Docker; never above 512 MiB over the day |
| CPU | ~1.5 % of 2 cores at idle for the whole host (health checks, Postgres housekeeping); ~11 % briefly during the upgrade (image pulls, migrations, starts) |
| Database | `pg_database_size` **9.3 MB**; the data directory **64 MB** (write-ahead log and catalogs included) |
| Traffic | ~375 kB sent by nginx in the few hours after the upgrade's restart |

What it settles: **load decides neither platform.** At Railway's list prices
(RAM ≈ $10/GB-month, CPU ≈ $20/vCPU-month, volume $0.15/GB-month, egress
$0.05/GB) this is roughly $2–3.50 of usage, under the Hobby plan's included $5, with
room for a small identity provider; Railway's Postgres image may idle higher than
this one, which is an estimate to check on the trial. On Render every service's
smallest tier is many times what it uses, so its price is set by how many services
there are, not by load. What remains open is backups and restore, the MCP request
limits, and photo storage (#28), which will outgrow a 64 MB database quickly.

## Side by side

| | Railway | Render |
|---|---|---|
| Cheapest continuous plan, stack only | Hobby: $5/month, includes $5 usage; ≈ $5 total estimated | ≈ $20.30/month (web $7 + api private service $7 + Postgres basic $6 + 1 GB $0.30) |
| With Pocket ID | ≈ $6 (usage-billed) | ≈ $27.55 (a $7 web service + a disk) |
| Trial | $5 once, 30 days, no card; GitHub link lifts the "limited trial" egress restriction | Free tier sleeps after 15 min idle; paid services need a card |
| Prebuilt images | GHCR public images deploy; digest pinning undocumented (third-party evidence only) | Any public image; a digest is accepted in place of a tag; linux/amd64 required |
| One-click | Template + "Deploy on Railway" button; `${{secret()}}` generates secrets; templates do not track image updates | `render.yaml` Blueprint in the repo + "Deploy to Render" button; `generateValue` secrets; `preDeployCommand` |
| Private network | `<service>.railway.internal`; IPv4 + IPv6 for environments created after 2025-10-16, IPv6-only before; resolver address undocumented (staff post: `fd12::10`) | Single-label internal hostnames (`api-xxxx`); system resolver per the docs |
| Edge request limit | **15 min per request, 5 min idle** (websockets exempt) | 100 min |
| Client address | `X-Real-IP` documented; `X-Forwarded-For` behaviour contradicted between staff posts (2024 vs 2026); edge source range undocumented | Traffic passes through Cloudflare; `X-Forwarded-For`, first entry the client (staff, 2021); source range undocumented |
| Migrations / ordering | Pre-deploy command: separate container, service variables, private network, no volume; timeout settable | Pre-deploy command on paid services: separate instance, 30 min, no disk; private network access unstated |
| Health checks | Deploy-time only; sent with `Host: healthcheck.railway.app` | Continuous; sent with the service's own host; 60 s of failure restarts |
| Postgres | A container on a volume ("unmanaged"); volume backups (daily 6 d, weekly 27 d, monthly 89 d) — **pricing page ticks backups for Pro and Enterprise only** (read from the page's HTML; confirm) | Managed; paid tiers have PITR (3 days Hobby, 7 Pro) and 7-day logical backups; free Postgres expires after 30 days |
| Volumes | One per service; Hobby ≤ 5 GB; brief downtime on every redeploy of a service with a volume | Disks paid only, one per service, grow not shrink, daily snapshots ≥ 7 days; a disk disables zero-downtime deploys |
| Object storage (M7) | S3-compatible buckets, $0.015/GB-month, presigned URLs only, not on the private network (billed egress) | A disk, or external S3; Render object storage "alpha" since 2026-03 |

## What any platform needs from the packaging (#281)

These are the release images as they stand, read against both columns above — the
proof deployment would have to work around them, and #281 would own the fix:

1. **nginx's resolver is Docker's.** `resolver 127.0.0.11 valid=10s ipv6=off`
   (`frontend/nginx/default.conf.template`) exists so a recreated `api` container is
   re-resolved (§8). Neither platform documents a fixed resolver address, and
   Railway's private network is IPv6 in older environments. Reading the resolver
   from `/etc/resolv.conf` at container start, without `ipv6=off`, is the portable
   form.
2. **The upstream and the port are literals.** `http://api:8000` and `listen 80` are
   written into the template; both platforms name services their own way and inject
   `PORT`.
3. **Default-deny Host vs platform health checks.** Railway's health check sends
   `Host: healthcheck.railway.app`, which the 421 default server refuses.
4. **`TRUSTED_PROXIES` needs the edge's source addresses, which neither documents.**
   Without them every visitor keys the rate limits and the audit address on the edge
   — the #194 gateway problem again. This has to be measured on the platform, not
   configured from documentation.
5. **The one-shot `migrate` service** maps to a pre-deploy command on both; whether
   Render's can reach the private database is unstated.
6. **Service count is Render's price.** nginx uses 3.7 MiB of a $7 instance; an image
   serving the SPA and the API from one service (nginx and uvicorn together, or the
   API serving the built frontend) would take Render from ≈ $20 to ≈ $13 a month. It
   costs Railway nothing either way, and it changes the ingress §8 and rule 12 are
   written around, so it is #281's decision, not a default.

## Open questions only a deployment answers

- Railway's 15-minute / 5-minute-idle cap against the MCP transport: does the
  streamable-HTTP GET stream reconnect cleanly, and do FastMCP's pings keep an idle
  stream under 5 minutes? (Cloudflare's 125 s cliff was survivable in the #194 gate
  with the 15 s ping.)
- Render's SSE buffering (community reports only).
- The edge source ranges on both, for `TRUSTED_PROXIES`.
- Whether Railway's Hobby plan really lacks volume backups, which decides whether
  the cheap column needs the $20 Pro plan to meet §11.1's "recover it without an
  operations manual".

## Where this leaves the decision

On paper Render is the lower-risk proof candidate (managed Postgres with restore on
the cheapest paid tier, a 100-minute edge limit, a Blueprint from this repository)
and Railway the cheaper one (≈ a quarter of the cost, but platform backups and an
MCP-friendly request limit are the open questions). A Railway trial costs nothing
and could measure its two open questions before a card is involved. The #280 result
decides whether Pocket ID is part of the template, which moves Render's estimate by
about a third and Railway's by a dollar.

## Sources

Railway: [pricing](https://railway.com/pricing), [plans](https://docs.railway.com/pricing/plans),
[free trial](https://docs.railway.com/pricing/free-trial),
[private registries](https://docs.railway.com/builds/private-registries),
[templates: create](https://docs.railway.com/templates/create),
[publish](https://docs.railway.com/templates/publish-and-share),
[deploy](https://docs.railway.com/templates/deploy),
[private networking](https://docs.railway.com/networking/private-networking/how-it-works),
[domains](https://docs.railway.com/networking/domains/working-with-domains),
[public networking limits](https://docs.railway.com/networking/public-networking/specs-and-limits),
[CDN](https://docs.railway.com/networking/cdn),
[pre-deploy command](https://docs.railway.com/deployments/pre-deploy-command),
[healthchecks](https://docs.railway.com/deployments/healthchecks),
[restart policy](https://docs.railway.com/deployments/restart-policy),
[PostgreSQL](https://docs.railway.com/databases/postgresql),
[volume backups](https://docs.railway.com/volumes/backups),
[volumes](https://docs.railway.com/volumes/reference),
[buckets billing](https://docs.railway.com/storage-buckets/billing);
staff posts on [nginx DNS](https://station.railway.com/questions/nginx-stale-dns-entries-for-redeployed-s-ecd64513),
[X-Forwarded-For (2024)](https://station.railway.com/questions/edge-proxy-x-forwarded-for-and-x-real-ip-c5a50049) and
[(2026)](https://station.railway.com/questions/security-critical-questions-on-edge-prox-8fddd775).

Render: [pricing](https://render.com/pricing), [free tier](https://render.com/docs/free),
[deploy an image](https://render.com/docs/deploy-an-image),
[Blueprint spec](https://render.com/docs/blueprint-spec),
[Deploy to Render](https://render.com/docs/deploy-to-render),
[private network](https://render.com/docs/private-network),
[web services](https://render.com/docs/web-services),
[deploys](https://render.com/docs/deploys),
[health checks](https://render.com/docs/health-checks),
[websockets](https://render.com/docs/websocket),
[Postgres backups](https://render.com/docs/postgresql-backups),
[disks](https://render.com/docs/disks),
[DDoS / Cloudflare](https://render.com/articles/how-render-handles-ddos-attacks),
[feedback: object storage](https://feedback.render.com/features/p/cloud-object-storage),
[feedback: X-Forwarded-For](https://feedback.render.com/features/p/send-the-correct-xforwardedfor).
