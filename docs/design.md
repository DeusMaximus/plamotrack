# plamotrack — Design Notes

**Status:** Living document · **First written:** 05/08/2026 · **Last revised:** 09/08/2026

---

## How to read this

This is **not a specification**, and nothing here is a contract. It's the record of
why plamotrack is shaped the way it is — the decisions taken, the alternatives
rejected, and the reasoning that would otherwise evaporate the moment it left
someone's head.

Two things follow from that:

- **Where this document and the code disagree, the code is right** and this document
  is behind. Several sections already describe a design that development improved on;
  those are marked rather than quietly rewritten, because the *change* is usually the
  interesting part.
- **Sections can be revisited.** If a decision here turns out to be wrong, the fix is
  to change it and say why — not to treat the document as something to be complied
  with.

Section and feature markers used throughout:

| Marker | Meaning |
|---|---|
| ✅ **Built** | Implemented and working in the app today |
| 🔨 **Planned (Mn)** | Decided, not yet written — the milestone it belongs to |
| 💭 **Open** | Still genuinely undecided |

The roadmap and current milestone live in §11. `HANDOFF.md` in the repo root carries
the session-by-session build log.

---

## 1. Overview

A self-hosted, open-source web application for tracking a Gunpla (or general model-kit)
collection end to end: pre-order → order → arrival → build pipeline → completion,
alongside the tools, consumables, and third-party upgrades used along the way. It is
being packaged as a Docker Compose stack with a web UI, a REST API, and an embedded MCP
server so Claude and other agents can query and update the data directly.

It exists because the obvious alternatives don't fit. Spreadsheets can't model the
one-order-becomes-several-kits relationship without either duplicating everything or
giving up on it. General-purpose database/app-builder tools handle the data fine but
tend to put the features you want most — a genuinely draggable Kanban board, unlimited
rows — behind a paywall, and you're still building the app yourself, just in someone
else's UI. This is the same app, owned outright.

### 1.1 Goals

- ✅ A drag-and-drop Kanban board for build status (Pre-ordered → Ordered → In Transit
  → Backlog → Building → Complete), not a static view.
  *(Revised 06/08/2026: the original design had separate In Hand and Backlog statuses.
  They turned out to be the same pile with two names, and were merged — Backlog now
  means "in hand, not started" and occupies In Hand's old pipeline position. The board
  defaults to a Build view of Backlog/Building/Complete; an Orders view shows the
  ordering states with everything received rolled into one aggregate column.)*
- ✅ Full CRUD via the web UI, without touching a database or an app-builder tool
- ✅ MCP-native: agents can add orders, update build status, and adjust stock without a
  human touching the UI
- ✅ Data that can leave: CSV export and import, so the collection is never trapped (§12)
- 🔨 **Planned (M5)** `docker compose up` → ready-to-use local instance, no manual
  runtime or schema setup
- 🔨 **Planned (M5.1)** Internationalisation foundations: English strings behind a
  translation layer, locale-aware formatting, structured errors, and a configurable
  reference currency — no translations yet
- 🔨 **Planned (M6)** Authenticated remote access for the web UI, REST API, and MCP,
  including OAuth-compatible MCP clients and a tested VPS deployment path
- 🔨 **Planned (M6.1)** Dual-era MCP compatibility, adding `2026-07-28` without
  dropping clients on the current protocol generation
- 🔨 **Planned (M7)** Photo gallery per kit
- 🔨 **Planned (M8)** A public-facing, read-only showcase page suitable for linking
- Genuinely reusable by someone who isn't the author — this is a public repo, not a
  personal script

### 1.2 Non-goals

- Multi-tenant / multi-household support (single collection per instance)
- Build-stage photo timelines (single gallery per kit only — see §4.6)
- Built-in email parsing for order import. Handled instead by MCP plus whatever mail
  connector the operator already has, at query time — not a first-class feature
- Price/currency conversion via live FX rates (see §6)

---

## 2. Architecture

```
┌──────────────┐               ┌─────────────────────────────┐      ┌────────────┐
│  Frontend    │──── /api ────▶│  FastAPI — a single process │─────▶│  Postgres  │
│  React + Vite│               │   ├─ REST routers           │      │            │
└──────────────┘               │   ├─ FastMCP, mounted /mcp  │      └────────────┘
                               │   └─ shared service layer   │
┌──────────────┐               │        (all business logic) │
│  MCP clients │──── /mcp/ ───▶│                             │
│ (Claude, …)  │               └──────────────┬──────────────┘
└──────────────┘                              │
                                     ┌────────┴─────────┐
                                     │  Photo storage   │ 🔨 M7
                                     │  (volume or S3)  │
                                     └──────────────────┘
```

- ✅ **The API and the MCP server share one FastAPI process.** FastMCP mounts as an ASGI
  sub-application at `/mcp` on the same port the REST API serves. Business logic lives
  in exactly one place — the service layer — and both the UI and agents call it, so REST
  and MCP cannot drift apart. It also means one deployment unit instead of two.
  *(Revised 06/08/2026: the original sketch gave MCP its own port. Mounting it as a
  route is simpler, needs no extra firewall or proxy rule, and nothing has yet wanted
  them operated separately. Splitting later is a routing change, not a redesign.)*
- ✅ **Postgres, not SQLite.** SQLite under concurrent writers means WAL contention and
  `busy_timeout` tuning — a well-trodden source of pain. plamotrack has three concurrent
  writer types by design (web UI, REST clients, MCP agents), so Postgres is the boring
  correct answer. It costs one more container in the compose file; worth it.
- ✅ **Frontend: React + Vite**, to be served as a static build behind a lightweight
  nginx container (M5). Kanban via `dnd-kit` — maintained, accessible, no jQuery-era
  baggage.

---

## 3. Data Model

Serialized (unique) and fungible (quantity-tracked) items are modelled as genuinely
separate tables rather than one polymorphic "item" table. They behave too differently to
unify cleanly, and four honest tables are easier to reason about and query than one
table with half its columns null.

### 3.1 `kits`

One row per **physical** kit. Duplicate purchases of the same product create separate
rows.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "RX-79(G) Ground Type" |
| grade | text/enum | HG/RG/MG/PG/SD/etc — see §9.1 |
| scale | text | derived default from grade, overridable |
| kit_number | text | manufacturer product code |
| status | enum | Pre-ordered / Ordered / In Transit / Backlog / Building / Complete — Backlog = in hand, not started (In Hand merged into it, 06/08/2026) |
| status_updated_at | timestamp | |
| rating | int (nullable) | out of 5, set on completion |
| build_notes | text | freeform |
| order_item_id | uuid FK | provenance — which order line spawned this kit |
| created_at / updated_at | timestamp | |

### 3.2 `kit_photos`

One-to-many gallery per kit. ✅ The table exists and is registered for export; 🔨 the
upload endpoints and UI land in M7.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| kit_id | uuid FK | |
| file_path | text | storage-backend-relative path |
| caption | text (nullable) | optional now; cheap insurance if a build-stage timeline is ever wanted |
| taken_at | timestamp (nullable) | same reasoning — lets photos sort meaningfully without committing to a staged-build model |
| created_at | timestamp | |

### 3.3 `tools`

Fungible, durable. Catalog and on-hand quantity in one row — no separate catalog/stock
split is warranted at this scale.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "Godhand Ultimate Nippers" |
| category | text | cutting / filing / gluing / etc |
| quantity_on_hand | int | |
| unit_cost_reference | numeric (nullable) | last known price, informational only |
| condition_notes | text (nullable) | |

### 3.4 `consumables`

Fungible, depletable. Partial-state tracking is deliberately not attempted — decrement
on use, discard row-level detail. Nobody wants to record that a paint pot is 40% empty.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "Gundam Marker GM02" |
| category | text | paint / cement / blades / sanding / etc |
| quantity_on_hand | int | |
| low_stock_threshold | int (nullable) | optional reorder flag |

### 3.5 `upgrades`

Fungible stock **plus** a relationship to the kits they're applied to — structurally
different from consumables, so it keeps its own table rather than being merged in.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | e.g. "G-Rework Decal Sheet #4" |
| manufacturer | text | |
| quantity_on_hand | int | |

### 3.6 `upgrade_applications`

Join table: which upgrades have been used on which kits.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| upgrade_id | uuid FK | |
| kit_id | uuid FK | |
| quantity_used | int | |
| applied_at | timestamp | |

### 3.7 `retailers`

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| name | text | |
| url | text (nullable) | |
| rating | int (nullable) | overall, out of 5 |
| packing_quality | text/enum (nullable) | excellent / good / average / below_average / poor |
| shipping_speed | text/enum (nullable) | very_fast / fast / average / slow / very_slow |
| would_order_again | text/enum (nullable) | yes / maybe / no |
| notes | text (nullable) | anything else goes here |

The report-card fields (rating through would_order_again) are all optional, filled in
after actually dealing with a retailer. Ordering from overseas hobby shops is enough of
a gamble that remembering which ones pack properly has real value.

### 3.8 `orders`

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| retailer_id | uuid FK | |
| order_date | date | |
| order_number | text (nullable) | the retailer's own reference, kept for support contact ("order lost", "item missing"). **Deliberately not unique** — it's only unique per retailer at best, so it's never used as an identifier internally; ids are ids |
| delivery_service | text (nullable) | null = local pickup/purchase |
| tracking_number | text (nullable) | |
| tracking_url | text (nullable) | |
| shipping_cost_minor | int (nullable) | see §6 for currency handling |
| currency_code | text | ISO 4217 |
| received_at | timestamp (nullable) | null = pending (not yet arrived) — see §3.9 |

### 3.9 `order_items`

The dispatch point between orders and the four catalog tables.

| Field | Type | Notes |
|---|---|---|
| id | uuid | |
| order_id | uuid FK | |
| item_type | enum | kit / tool / consumable / upgrade |
| catalog_ref_id | uuid (nullable) | FK to a tools/consumables/upgrades row (null for kit-type, since kits are spawned fresh) |
| quantity | int | **semantics differ by item_type** — see below |
| unit_price_minor | int | |
| currency_code | text | ISO 4217 |
| converted_price_aud_minor | int | snapshot at entry time, see §6 |

**Quantity semantics.** These differ by item type, which is the kind of thing that has
to be explicit in code and not merely documented:

- `item_type = kit` → quantity **fans out**: creates N new rows in `kits`, each linked
  back to this order item, at entry time
- `item_type = tool/consumable/upgrade` → quantity **increments** `quantity_on_hand` on
  the referenced catalog row, **when the order is received** — not at entry

**Order lifecycle (revised 06/08/2026).** Orders are pending → received. The original
design incremented stock at entry, which meant plamotrack would cheerfully report five
Gundam markers on hand while they were still in a warehouse in Osaka. Quantity means
*physically on hand*, not *on order*. So:

- catalog stock applies when the order is marked received (`received_at`); kits fan out
  at entry regardless, since they have their own pipeline states to sit in
- receiving also advances that order's kits still in pre_ordered/ordered/in_transit to
  backlog (in hand, unbuilt)
- a received-at-entry flag covers over-the-counter purchases; split shipments are
  entered as separate orders — deliberately no per-line receiving lifecycle
- **edit** re-runs the dispatch diff: kit detail fixes propagate to the spawned kits
  (names live on the kits, the line just re-syncs them), and quantity or target changes
  spawn/remove kits and adjust applied stock
- **delete = undo the entry**: spawned kits removed, applied stock reversed
- guards throughout: kits that are building/complete, rated, or carrying photos, and
  stock that's already been consumed, block destructive edits with a 409 rather than
  silently losing history
- every order mutation loads the order row `FOR UPDATE`, so concurrent
  receive/edit/delete calls serialize instead of double-applying stock — three writer
  types (§2) makes this a real race, not a theoretical one

**Duplicate-catalog prevention.** Order entry uses search-and-select-or-create (a
typeahead against existing tools/consumables/upgrades) rather than a free-text name
field. This is a deliberate constraint rather than a UX nicety: free-text entry
fragments the catalog within weeks — "GM02 Gundam Marker" and "Gundam Marker GM02" as
two rows with split stock — and once fragmented it takes manual merging to fix. The
constraint matters more, not less, for people who haven't been maintaining the
collection long enough to have a consistent naming habit.

---

## 4. API Design (REST)

Standard CRUD plus a few purpose-built endpoints.

**Built ✅**

- `GET/POST /kits`, `GET/PATCH/DELETE /kits/{id}` — PATCH handles Kanban drag (status
  change). Order-spawned kits refuse direct deletion (409) — undo happens at the order
  line, so purchase records and the collection can't drift apart
- `GET/POST /tools|/consumables|/upgrades` + `PATCH/DELETE /{id}` on each — deletes are
  blocked (409) when the item appears in order history or upgrade applications; edit
  instead, history is fact
- `POST /upgrades/{id}/apply` — body: kit_id, quantity → creates an
  `upgrade_applications` row, decrements stock
- `GET/POST /retailers`, `PATCH/DELETE /retailers/{id}` — delete blocked when the
  retailer has orders
- `GET/POST /orders`, `GET /orders/{id}` — POST body includes nested order items; the
  server handles fan-out/increment dispatch per §3.9
- `PATCH /orders/{id}` — header fields and/or full line-set replacement (dispatch diff
  per §3.9; the `converted_*` snapshot is the one field pair an omission preserves
  rather than clears — see §6)
- `POST /orders/{id}/receive`, `DELETE /orders/{id}` — receive/undo per §3.9
- `GET /catalog/search?q=` — powers the typeahead, searches across
  tools/consumables/upgrades
- `GET /export/archive`, `GET /export/{table}.csv`, `GET /export/templates`,
  `GET /export/starter-sheet.csv`, `POST /import/preview`, `POST /import/apply` — see §12
- `GET /healthz`

**Planned 🔨**

- `GET /kits/{id}/photos`, `POST /kits/{id}/photos` (multipart upload) — **M7**, blocked
  on the §9.2 storage decision. Not implemented; the `kit_photos` table exists but
  nothing writes to it
- `GET /public/kits`, `GET /public/kits/{id}` — **M8**, read-only, no auth, powers the
  showcase page (§5). Not implemented; there is currently no `/public/*` namespace at all

### 4.6 Photo model note

Single gallery per kit, confirmed. `caption` and `taken_at` are retained on
`kit_photos` as low-cost future-proofing (§3.2) — this does **not** imply a build-stage
timeline is planned, only that the columns are cheap now and expensive to retrofit.

---

## 5. Auth, Remote Access & Public Mode 🔨 **Planned (M6 + M8) — none of this exists yet**

Nothing in this section is implemented. Today every endpoint is unauthenticated and
every endpoint can write. See §10 for what that means for running an alpha instance.

The intended shape has three genuinely separate access surfaces, not a UI toggle over
one path:

- **Browser admin path** — an authenticated, single-owner web session. The schema does
  not preclude multi-user later, but v1 has exactly one owner. **M6.**
- **REST and MCP path** — bearer-token authentication with separate read and write
  scopes. Remote MCP clients authenticate via the MCP OAuth contract; browser sessions
  do not double as MCP credentials. **M6.**
- **Public/read path** — `/public/*` routes, no auth, and no write capability reachable
  from them at all. Genuinely separate route handlers, not client-side filtering over
  the same ones. **M8.**

That separation must be enforced at both the application and ingress layers. Separate
`/public/*` handlers are necessary, but they do not make a showcase safe if the same
public reverse proxy also exposes unauthenticated `/kits`, `/orders`, or `/mcp`. M6
protects the admin surfaces before M8 makes the instance deliberately public.

MCP tools always operate through the authenticated path — no public or anonymous MCP
access. The implementation should use a maintained OAuth/OIDC provider or proxy rather
than inventing an authorization server inside plamotrack. A remote deployment also needs
token expiry and revocation, host/origin validation, rate limiting, and useful audit
logs; "a login page exists" is not the completion criterion.

---

## 6. Currency Handling

- `unit_price_minor` — integer, minor units (cents), never float. Avoids the classic
  floating-point money bug
- `currency_code` — ISO 4217 (AUD, USD, JPY, …), stored per order item
- ✅ `converted_price_minor` + `converted_currency_code` — the conversion snapshot,
  captured **at entry time** and never recalculated on view.
  What a kit cost is a historical fact; re-deriving it from a live FX API on every page
  load would make spend history drift underneath the person reading it. If a live-rate
  lookup at entry time is wanted (a nice-to-have, not built), it's a one-shot call at
  creation, result stored, done
- ✅ `REFERENCE_CURRENCY` — the instance's own currency (default `AUD`). Order forms,
  starter-sheet templates, and the MCP `create_order` default all read it. A CHECK
  constraint keeps the amount and its code null-or-present together

✅ **The AUD assumption is gone** (shipped ahead of M5.1, alongside M5). The amount
column was `converted_price_aud_minor` — a name that asserted a currency the schema
never stored. It is now a neutral amount with its code beside it, and the code is
written **at entry time**, not read from config on the way out: an amount whose meaning
can be changed by editing an env var is not a snapshot. Moving `REFERENCE_CURRENCY`
later therefore changes what *new* entries default to and nothing else.

Two compatibility notes for anyone who used the 0.1.0 alpha:

- the migration renames the column rather than replacing it, and backfills `AUD` for
  every existing snapshot — which is what those rows always meant
- CSVs exported by 0.1.0 still import. `converted_price_aud_minor` is a registered
  alias of the current column and carries `AUD` in with it, so an old archive is read
  as the AUD it was even on an instance whose reference currency is something else.
  Exports only ever emit the current name

The same instinct — recorded facts stay recorded — runs through the order guards in
§3.9 and the delete blocks in §4.

✅ **An edit only touches the snapshot when it says so.** A line in `PATCH /orders/{id}`
otherwise replaces the stored one field for field; the `converted_*` pair is the single
exception. Omit it and the stored snapshot survives; clearing takes an explicit `null`.
Restating the amount alone doesn't relabel the currency either — on an update the code
falls back to the one already recorded before it falls back to the instance default, or
a typo fix on a GBP amount would quietly reissue it as AUD.
The reason it can't follow the rule its neighbours follow: no client holds the
entry-time rate, so nobody editing a quantity is in a position to restate the
conversion — and treating "absent" as "clear" meant a foreign-currency snapshot,
imported from a spreadsheet or written by an agent, died on the first unrelated edit.

The browser follows from the same premise. It derives a snapshot only for a line it is
*creating* in the instance's own currency, where the converted amount is the price and
no rate is involved. For a line that already exists it shows what was recorded — in the
currency it was recorded in — and sends that back untouched. Notably, "the purchase
currency equals `REFERENCE_CURRENCY`" is **not** grounds to recompute: a yen purchase
carrying an AUD snapshot on an instance that later moved to `JPY` would be silently
restamped as yen, which is precisely the drift this section exists to prevent. Nor is
"the amount differs from the unit price" — an imported AUD 95 against an AUD 100 line
is a record, not a rounding error. Correcting or removing a snapshot is a thing the
operator does on purpose, in a field put there for it.

### 6.1 Internationalisation 🔨 **Planned (M5.1) — no translations yet**

The first localisation milestone is infrastructure, not a partially translated UI:

- move every user-facing frontend string into an English source catalogue with semantic
  keys, interpolation, and plural rules
- route dates, times, numbers, and currency through locale-aware formatters; browser
  locale is the initial default, with an explicit persisted override
- set the document language and direction from the active locale, and prefer logical
  layout properties where practical so a future right-to-left language is not a rewrite
- return stable error codes and parameters from REST alongside the existing English
  `detail`; the browser can translate known errors while API and MCP clients still get a
  useful message
- keep API enum values, MCP tool names, database values, and canonical CSV headers
  stable and untranslated. Translation happens at the presentation boundary; user-entered
  kit names, notes, retailers, and categories remain exactly what the owner wrote

Shipping the English catalogue before adding photos, authentication screens, or the
showcase prevents each of those features from creating another pile of embedded copy.

The configurable reference currency listed above was split out and shipped early, with
M5 — it is a schema migration and a CSV rename, unrelated to translation, and it got
cheaper the sooner it happened: every archive exported under the old column name is one
more file the compatibility alias has to keep understanding.

---

## 7. MCP Tools ✅

Exposed via FastMCP alongside the REST API, sharing the same service layer. The endpoint
is `/mcp/` on the API port (streamable HTTP).

- `list_kits(status?, grade?)`
- `get_kit(id)`
- `update_kit_status(id, status)`
- `search_catalog(query)` — the same backing search as the UI typeahead, so an agent
  adding an order hits the same de-dup logic a human would
- `create_order(retailer, date, items[], order_number?, tracking?, received?)` — the
  items array drives the same fan-out/increment dispatch as the REST endpoint; retailer
  matched by name case-insensitively, created if new
- `list_orders(pending_only?)` — find the order a shipping or arrival email belongs to
- `mark_order_received(order_id)` — applies stock, advances pipeline kits to backlog (§3.9)
- `adjust_stock(catalog_id, delta, reason?)`
- `apply_upgrade(upgrade_id, kit_id, quantity)`

Status arguments are normalised for agents ("In Transit" → `in_transit`), including
aliases for the retired `in_hand` vocabulary, because an agent's idea of the status
names will always lag the schema.

This is what makes "grab the latest order confirmation from my email and add those" work
without an email-parsing feature existing anywhere in the app. It's one agent session
with this MCP server and a mail connector both active, reading one and writing the
other. Building that as a feature would mean owning IMAP credentials, per-retailer
parsers, and a support burden — for something the agent layer already does better.

### 7.1 Protocol modernisation 🔨 **Planned (M6.1)**

The current server uses the handshake/session-era MCP implementation. The `2026-07-28`
revision changes the transport substantially: a stateless core, discovery in place of a
required initialize handshake, standard routing headers, cache hints, and hardened OAuth
behaviour. Plamotrack's tool handlers are already application-stateless — each call gets
its durable state from Postgres — so the product architecture does not need to change.

M6.1 adds the modern protocol only through an SDK/framework release that serves modern
and legacy clients from the same endpoint. Completion means conformance coverage plus a
small client matrix, not merely raising a dependency version. Tasks, multi-round-trip
requests, subscriptions, and MCP Apps are not roadmap items: the current short,
transactional tools do not need them.

---

## 8. Docker Compose Layout ✅ (Milestone 5, 10/08/2026)

```yaml
services:
  web:      # nginx: static Vite build; /api and /mcp proxied to api
  api:      # FastAPI + FastMCP, one process, one port (REST at /, MCP at /mcp)
  migrate:  # alembic upgrade head, then exits — a gate, not a service
  db:       # postgres:16
  # photo storage: local named volume by default;
  # optional S3-compatible (MinIO or external) via env var, not required for v1
```

Only `web` is published; the API and database stay on the Compose network, so an
instance has one door and it binds to `127.0.0.1` — a convenient install is not
accidentally an internet deployment. `docker compose up -d --wait` is the supported
empty-instance path, and it exits non-zero if anything fails to come up.

Images build from source in-repo. Publishing to a registry belongs with the rest of
release automation in M9; until then an install needs no registry, no tags, and no
multi-architecture story — the machine doing the installing builds for itself.

**Migrations are their own container**, gating the API through
`service_completed_successfully`. Running them from the API's entrypoint would turn a
failed migration into a crash-looping API; this way it's a stopped deploy with the
error in `docker compose logs migrate`, and the API never starts against a database it
doesn't match.

**The API's healthcheck is `/readyz`, which touches the database.** `/healthz` stays a
pure liveness check. If the healthcheck didn't hit Postgres, Compose would report a
healthy stack that cannot serve a single request.

Two nginx details are load-bearing rather than incidental, both found by testing
rather than reasoning:

- **`proxy_buffering off` on the MCP routes.** MCP is streamable HTTP; with buffering
  on, nginx holds the response and the client waits for bytes the proxy already has.
  It presents as a hang, not an error, which makes it expensive to diagnose later.
- **The upstream is resolved through a variable, with `resolver 127.0.0.11`.** A
  literal hostname in `proxy_pass` is resolved once at startup and cached for the life
  of the process, so recreating the api container onto a new address — exactly what
  upgrading does — 502s every request until `web` is restarted too. Verified by
  forcing the api container onto a different address with `web` left running: 502
  before, 200 after.

`/mcp` without the trailing slash is served rather than redirected. A 307 in answer to
a POST is a real hazard, not a cosmetic one, because not every client re-sends the body.

M5 does **not** make the stack internet-safe. M6 supplies a tested VPS deployment path
with authentication and a reference TLS/reverse-proxy configuration (for example Caddy),
while leaving operators free to use Traefik, nginx, or a tunnel. The base Compose file
does not bundle a certificate authority or a heavyweight identity platform.

---

## 9. Open Decisions 💭

1. **§9.1 — Generic "hobby build tracker" vs Gunpla-specific.** Still under consideration. The
   schema hedges reasonably well either way — `grade` and `category` are free text or
   text-enum rather than hardcoded logic, so the harder call (configurable taxonomy vs
   fixed enum) can be deferred without a schema rewrite. Needs deciding before a
   taxonomy/config UI is built, not before the core schema. This is also why enums are
   text + CHECK constraint rather than native Postgres enums: changing the taxonomy
   stays a data migration.
2. **§9.2 — Photo storage backend default.** A local volume is the safe v1 default, with
   S3/MinIO as an opt-in env var. Worth confirming before the upload handler is written,
   because it also decides the backup story — a Docker volume is covered by whatever
   already backs up the host, whereas an external object store is a second thing to
   remember to back up.
3. ~~**§9.3 — License**~~ — **Settled: MIT.**
4. **§9.4 — Multi-user / multi-collection.** Out of scope for v1, but worth a one-line decision
   on whether the schema should avoid single-owner assumptions now, since retrofitting
   multi-tenancy later is a real migration and not a toggle.

---

## 10. Repository & Release Strategy

**Revised 06/08/2026.** The original plan held the repo private until milestones 1–6
were finished. It's going public earlier than that — at Milestone 4.5, as a **public
alpha**, with the remaining milestones built in the open.

What changed the calculus: Milestone 4.5 (import/export) removed the thing that made
early exposure irresponsible. Before it, data went in through the UI and MCP and had no
way out — a one-way door, which is not something to invite anyone else through. With a
full CSV archive in and out, an early adopter can back up, migrate, or walk away, and
the remaining gaps become things to disclose rather than things to hide.

**What "alpha" honestly means here — the things to disclose:**

- **No auth on the write path** (M6). Anyone who can reach the API can write to it. Run
  it on a network you trust — LAN, VPN, localhost. Do not put it on the public internet.
- **No bundled application containers yet** (M5). Compose starts Postgres; the API and
  frontend run from source. The M5 stack will remain loopback-only by default and does
  not imply that an unauthenticated instance is safe to expose.
- **No localisation infrastructure yet** (M5.1). English is embedded in the UI and AUD
  is still the reference-currency assumption.
- **No photos** (M7) and **no public showcase page** (M8).
- **The schema will still move.** Migrations are provided and tested in both directions,
  but breaking changes are possible while it's alpha. Export an archive before upgrading
  — that is exactly what §12 is for.

Unchanged from the original plan:

- `.gitignore` and `.env.example` in place from commit #1, so the private→public flip
  carries the full commit history with no secrets to scrub out of it
- License: MIT

### 10.1 Naming & README tone

- **Repo name:** `plamotrack` — chosen over a generic "gunpla-tracker" name for
  community authenticity ("plamo" is the hobbyist term) and to hedge the still-open
  generic-vs-Gunpla-specific question (§9.1)
- **GitHub "About" description** (functional, carries search/SEO weight): *"Self-hosted
  Gunpla/plamo collection & build tracker — Docker Compose, Kanban build pipeline, and
  an MCP server so you can manage it via Claude or ChatGPT."*
- **README tagline** (self-deprecating, hobby-community tone — it lands as a joke once
  someone has already found the repo, and doesn't need to do discovery work): *"Track
  every kit, tool, and terrible financial decision from pre-order to panel-lined
  masterpiece."*
- General principle for README and docs: functional copy where it needs to be found
  (About field, package descriptions, docs headers), joke copy where it already has an
  audience (README body, contribution guide intro). Don't make the humour carry search
  weight.

---

## 11. Milestones

1. ✅ Schema + Postgres migrations + FastAPI CRUD (no auth, no UI) — prove the data model
2. ✅ MCP tools wired to the same service layer
3. ✅ Frontend: table views + basic forms *(grew into the full order lifecycle and CRUD
   along the way — §3.9)*
4. ✅ Kanban board (drag-and-drop)
5. ✅ **4.5** Import/export — CSV archive + manifest, preview, templates (§12), inserted
   ahead of the rest to make a public alpha honest (§10)
6. → **Public alpha here.** Everything below happens in the open.
7. ✅ **M5 — Installability:** full local Docker Compose stack, controlled migrations,
   safe loopback defaults, health checks, and backup/upgrade documentation (§8,
   `docs/operations.md`). This improves adoption without claiming the unauthenticated
   stack is internet-safe. The configurable reference currency was pulled forward from
   M5.1 and shipped here — it is a schema migration, not translation work, and its
   compatibility cost grows with every archive exported under the old column name
8. 🔨 **M5.1 — Internationalisation foundation:** English source catalogue,
   locale-aware formatting, and structured API errors. No translations in this
   milestone
9. 🔨 **M6 — Secure remote access:** single-owner browser authentication, scoped
   REST/MCP bearer tokens, OAuth-compatible MCP access, and a tested TLS/VPS deployment
   path. This is the gate for deliberately exposing an instance
10. 🔨 **M6.1 — MCP modernisation:** dual-era compatibility for the existing protocol
    generation and `2026-07-28`, with conformance and real-client coverage
11. 🔨 **M7 — Photos:** local-volume upload + gallery, archive integration, and the
    §9.2 storage decision closed before implementation
12. 🔨 **M8 — Public showcase:** genuinely separate anonymous read routes and a
    shareable frontend, built only after the admin and MCP surfaces are protected
13. 🔨 **M9 — Open-source operations:** contribution guide, release automation,
    compatibility/support matrix, and deployment documentation polish

---

## 12. Import & Export ✅ (Milestone 4.5, 06/08/2026)

Added ahead of milestones 5–9 because the app was a one-way door: data went in via the
UI and MCP and could not come back out. That's a hard blocker for handing it to anyone
else — nobody should trust a collection to a self-hosted tool they can't back up,
migrate, or seed from the spreadsheet they already keep.

### 12.1 Format

CSV, one file per table, zipped with a `manifest.json` carrying `format`,
`export_version`, `schema_version` (the live Alembic revision), `app_version`,
`exported_at`, and per-table row counts. An archive from a **newer** `export_version` is
refused rather than mangled; a `schema_version` mismatch is a warning.

The CSVs are deliberately human-readable as well as machine-restorable: every uuid FK
carries a readable twin column (`retailer_name`, `catalog_name`), and every integer
minor-unit money column a major-unit twin (`unit_price` beside `unit_price_minor`). The
canonical column always wins when both are present. This costs a few columns and buys a
file that opens in any spreadsheet and makes sense — which is most of what "your data is
yours" means in practice.

### 12.2 The spec registry

`services/portability/spec.py` declares each table once — columns, parsers, roles
(`DATA` / `ID` / `REF` / `ALT_REF` / `ALT_MONEY`), natural key, FK dependency order.
Export, import, and blank-template generation all read it, so they cannot drift; a test
asserts template headers are byte-identical to export headers. Adding a model column is
one `col(...)` line.

`virtual=True` marks CSV columns with no backing model attribute — the `order_items`
`kit_*` columns mirror the kits a line spawned (kit details live on the kits, not the
line). They're exported for legibility and consumed on import only when the upload
doesn't supply the kits itself.

### 12.3 Plan, then apply

`POST /import/preview` returns an `ImportPlan`: per-row action (create / update /
unchanged / skip / error), what it matched and how, field-level diffs, warnings, and
derived effects. `POST /import/apply` **re-parses and re-plans**, then compares a
`plan_hash` of the decisions against the one previewed — a mismatch is a 409.

Nothing is cached server-side. The plan can't go stale, it survives a container restart,
and the recheck closes the window between looking and committing. The frontend just
holds the `File` and posts it twice.

### 12.4 Not duplicating things

Ids are preserved on create, so restoring into an empty instance reproduces every
internal reference exactly. When a row *matches* an existing record under a different
uuid, that mapping goes into an id-remap and all later references are rewritten through
it — an archive lands in an instance that already knows a retailer without creating a
second copy of it.

Rows without an id fall back to natural keys: case-insensitive name for retailers and
the three catalog tables (the same rule `get_or_create_retailer` and the §3.9
select-or-create flow already use); `(retailer, order_number)` for orders, falling back
to `(retailer, order_date, line fingerprint)` when there's no number; line fingerprint
within the parent for order lines. Ambiguous multi-matches become an error row asking
for an explicit id rather than a guess.

**Kits are excluded from natural-key matching by design.** A kit row is one *physical*
kit (§3.1), so duplicates are legitimate; matching on name would silently merge real
purchases. The preview flags look-alikes instead and lets the human decide. In
replace-all mode the flag is suppressed — everything is being deleted first, so it would
be misleading.

### 12.5 Two invariants

- **Stock is stated, never derived.** `quantity_on_hand` comes only from the catalog
  CSVs. Importing orders — even received ones — never adjusts it. Deriving it from
  received orders would double stock on every re-import, which is precisely the bug the
  §3.9 lifecycle revision already fixed once.
- **Kits are hybrid-dispatched.** An order line spawns kits only for the shortfall
  nothing else supplies: `quantity − (kits.csv rows for this line) − (kits already on a
  matched line)`. An archive round-trips with zero spawns; a bare orders sheet builds the
  collection. Same diff arithmetic as `_update_line`.

A blank cell in an *included* column means null; a column omitted from the file entirely
is left alone. That's needed for archive fidelity, but it makes partial sheets dangerous
— so the starter sheet emits only the columns it actually knows about. Otherwise
importing a kit list would wipe the report card off a rated retailer, which it did once
before a regression test started guarding it.

### 12.6 What this milestone does and doesn't make safe

This is the milestone that makes a public alpha reasonable: the data can now leave.

It does **not** make an exposed instance safe, and the two shouldn't be conflated. The
code going public is not the same as an instance going on the internet. M6 (secure
remote access and auth on the write path) is still the gate for the latter — see §10.

### 12.7 Deliberately not done

No MCP tools for import/export. The operations are file-upload-shaped and fit tool calls
badly, and an agent that can silently replace an entire collection is not a feature.
The services stay callable if that ever changes. The REST/MCP parity rule is about logic
living in the service layer, which it does.
