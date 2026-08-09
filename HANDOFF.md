# Session hand-off log

Every agent session that changes this repo appends an entry **at the top** (newest
first) before finishing. Keep entries short and factual — the next session may be a
different agent/model with no shared context.

Template:

```markdown
## YYYY-MM-DD — <agent> — <short title>
- **Done:**
- **Decisions:**
- **State:** (tests? migrations? anything half-finished?)
- **Next:**
```

---

## 2026-08-10 — Claude Code — M5 installability + neutral reference currency

Branch **`feat/m5-install-and-reference-currency`**, pushed, PR open against `main`.
Two commits: `588a12f` (the work below) and `f6a69c4` (exposure docs). Working tree
clean.

This hand-off entry lives on the branch rather than on `main`, against the usual
convention — the branch already contained a `HANDOFF.md` edit, so committing another
to `main` would have guaranteed a conflict at merge. The PR was opened immediately,
so nothing is hidden from the next session in the meantime.

- **Done — reference currency (pulled forward from M5.1):**
  - `converted_price_aud_minor` → `converted_price_minor` + `converted_currency_code`.
    Migration `2b293c6fd496` **renames** (doesn't replace) and backfills `'AUD'`;
    downgrade is deliberately lossy for non-AUD rows and says so. Round trip verified.
  - New `REFERENCE_CURRENCY` setting (default AUD, validated as ISO 4217). The code is
    stamped **at write time** by `_converted_snapshot()` in `services/orders.py` —
    never read from config on the way out, or every historical amount would change
    meaning when the operator edits an env var. Paired CHECK constraint.
  - New `GET /meta` (version + reference_currency). The order form reads it; it gates
    its render on the query because react-hook-form snapshots defaults at mount and
    would otherwise stick a new order on the fallback currency.
  - **CSV alias mechanism** on `ColumnSpec`: `aliases` + `alias_fills`. The retired
    header still imports and carries `AUD` in with it, because the old *name* asserted
    the currency — an instance on JPY must not reinterpret those rows. Exports only
    emit current names. 13 new tests in `tests/test_reference_currency.py`.
- **Done — M5 packaging:** `web` (nginx) + `api` + one-shot `migrate` + `db`. Only
  `web` published, loopback, `${WEB_PORT:-8080}`. Images build from source in-repo —
  registry publishing stays in M9. `/readyz` (real `SELECT 1`) is the healthcheck;
  `/healthz` stays liveness-only.
- **Three things found by testing, not by reasoning — don't "simplify" them away:**
  1. **nginx `resolver 127.0.0.11` + variable upstream.** A literal hostname in
     `proxy_pass` resolves once at startup and caches forever, so recreating `api` on a
     new address — *what upgrading does* — 502s everything until `web` restarts too.
     Reproduced by squatting api's address: 502 before, 200 after.
  2. **`proxy_buffering off` on `/mcp`.** Verified a full MCP session (initialize →
     tools/list → tools/call) through the proxy, chunked SSE intact.
  3. **`location = /openapi.json`.** `/api/docs` rendered fine but its schema fetch hit
     the SPA fallback and got `index.html` with a 200. Swagger would show "failed to
     load API definition".
  - Also: `/mcp` without the trailing slash is now *served*, not redirected.
    `serverInfo.version` was reporting FastMCP's `3.4.5` under plamotrack's name; now
    `app.__version__`.
- **Done — exposure docs (`f6a69c4`):** `WEB_BIND` works exactly like `POSTGRES_BIND`
  (it's the host-IP field of the same publish syntax), but the *risk* isn't symmetric:
  Postgres on `0.0.0.0` still has a password, the web ingress has nothing. New
  "Reaching it from another machine" section in `docs/operations.md` gives three
  options best-first — SSH tunnel, private/VPN address, then LAN — plus the Docker
  iptables surprise (published ports are forwarded, not delivered to the host, so
  `ufw deny` does **not** block them; the bind address is the real control).
  Deliberately ships **no** reverse-proxy config: a TLS/auth reference belongs with M6
  where it can be tested against the MCP streaming path.
- **State:** 102 backend tests pass, ruff clean, `npm run build` + oxlint clean,
  Playwright e2e passes. Verified on a clean volume: `up -d --build --wait` exits 0,
  all six migrations run, UI/API/MCP/openapi all 200 on an empty instance. Failure path
  verified too — a migration that can't connect leaves `api` and `web` in `Created` and
  compose exits **1**. The documented `pg_dump`/`pg_restore` procedure was run
  end-to-end and the conversion snapshot survived it.
- **Screenshots need no action.** They were shot with Playwright, which captures the
  page viewport only — no browser chrome, so no `:5173` address bar to go stale against
  the README's new `:8080`. Checked all six. The UI in them is also unchanged by this
  work (none show the order form modal, the only screen that moved).
- **Next:** M5.1 proper is now just the three i18n workstreams — frontend string
  catalogue (~200–260 keys, `react-i18next` recommended, OrdersPage is the big one),
  locale-aware formatting (small; only 19 directional Tailwind utilities to swap), and
  structured error codes (48 raise sites; the codes become permanent API surface, so
  pin them with tests). Estimated 4–5 sessions. The reference-currency piece that used
  to sit in M5.1 is done — don't re-plan it.

## 2026-08-09 — Codex — Public roadmap reprioritisation (merged)

- **Done:** Reworked the public roadmap across `docs/design.md`, `README.md`,
  `AGENTS.md`, and milestone-bearing code/config comments.
- **Decisions:** M5 = full local Compose install; M5.1 = internationalisation
  foundation and neutral reference currency; M6 = single-owner auth, OAuth MCP,
  and tested VPS deployment; M6.1 = dual-era MCP `2026-07-28`; M7 = photos;
  M8 = public showcase after protected admin/MCP ingress; M9 = open-source ops.
- **State:** Documentation/comment-only work committed as `8f87776`, pushed, and
  merged to `main` in PR #1 (`ade9d2a`). Local `main` is fast-forwarded to that
  merge. `git diff --check` was clean; no runtime tests were needed.
- **Next:** Implement M5 packaging with one loopback-bound ingress, internal API/db,
  controlled migrations, health checks, and upgrade/backup docs.

## 2026-08-06 — Claude Code — Public alpha SHIPPED: repo public, v0.1.0-alpha

**The repo is public and v0.1.0-alpha is released.** Everything below is on
`main`: `058bca4` (docs + README + screenshots), `a88f796` (loopback binding),
`5f790e7` (pool_pre_ping), `12a6ac0` (screenshot disclaimer). Release tagged at
`12a6ac0`, marked **prerelease** so GitHub doesn't badge it "Latest" and the
alpha framing survives outside the notes body.

Repo settings now: visibility public; About description was already the §10.1
functional text; topics added (gunpla, plamo, model-kits, self-hosted, fastapi,
react, mcp, mcp-server, postgres, docker). Verified anonymously after the flip —
README, screenshots and design notes serve 200, `.env` serves 404.

**Branching changed with it:** feature work goes on a branch + PR now, direct-
to-main is retired. See the Git conventions section in AGENTS.md.

- **Done — publishing the design doc:**
  - **Now tracked at `docs/design.md`** (was the untracked
    `plamotrack-design-doc.md`; its `.git/info/exclude` line is removed, so
    that old filename is no longer ignored anywhere).
  - Sanitised for an audience of strangers: internal-project references
    replaced with the underlying rationale, personal phrasing removed, and the
    two-port MCP sketch corrected to the `/mcp` route that was actually built.
  - **Reframed from spec to decision record.** It now states outright that it
    isn't a contract and that the code wins where they disagree — development
    had already improved on it in several places. Every section carries a
    ✅ Built / 🔨 Planned (Mn) / 💭 Open marker; §4 separates built endpoints
    from planned ones, §5 (auth + `/public/*`) is labelled entirely
    unimplemented, and §9.1–§9.4 are explicitly numbered so the code comments
    referencing them resolve.
  - **§10 rewritten for the alpha**: public at 4.5 rather than after M1–6, with
    four disclosures (no auth, no bundled containers, no photos/showcase,
    schema still moving). §12.6 realigned — code going public ≠ an instance
    going on the internet, and M7 still gates the latter.
  - AGENTS.md: design-doc bullet rewritten (tracked, not a spec, not binding —
    the architecture rules are), `docs/design.md` added to Layout, roadmap notes
    the alpha ships at 4.5 and that the audience is now strangers.
- **Done — README** (stub → full front page): alpha warning up top, feature
  sections, install steps, MCP wiring, tool table, what-isn't-built table. Tone
  deliberately light per design notes §10.1.
  - **Claude Desktop is documented as config-file-only** (`mcp-remote` bridge in
    `claude_desktop_config.json`). Its *Add custom connector* dialog only
    accepts publicly reachable URLs, so it cannot reach a self-hosted instance —
    user-verified, after a first draft claimed otherwise. Claude Code takes the
    HTTP URL directly. Endpoint is `http://localhost:8000/mcp/`; **the trailing
    slash matters**, without it you get a 307 and not every client re-POSTs.
  - **`docs/screenshots/`** — six 2× retina PNGs (~1.5 MB) captured with
    Playwright against the dev stack. The capture script was throwaway; to
    re-shoot, drive chromium from inside `frontend/` so `@playwright/test`
    resolves.
- **Done — config and exposure hardening** (all three found while writing the
  install docs; none were asked for up front):
  - **One `.env`**, at the repo root. Previously root `.env` for compose plus
    `backend/.env` for the API, with the password written twice and nothing
    enforcing a match. `app/config.py` now declares
    `POSTGRES_USER/PASSWORD/DB/HOST/PORT` and **assembles** the DSN, URL-quoting
    the credentials so a password containing `@` or `/` can't produce a DSN that
    parses to the wrong host. `DATABASE_URL` still overrides wholesale —
    `tests/conftest.py` and the M8 container both depend on that. `env_file` is
    an absolute pair (`<root>/.env`, `<backend>/.env`, later wins) anchored on
    `__file__` instead of the cwd-relative `".env"`, so the repo root and
    `backend/` now resolve identically; they previously didn't. `backend/.env`
    is redundant and deleted locally, still honoured if present.
  - **Postgres publishes on loopback only** (`${POSTGRES_BIND:-127.0.0.1}`).
    Docker publishes on 0.0.0.0 when the bind address is omitted, so the dev db
    was answering on the LAN — confirmed by connecting to it on the host's
    network address, and refused after the change.
  - **`pool_pre_ping=True`** on the engine. Without it the first request after
    any Postgres restart 500s on a severed pooled connection
    (`asyncpg InterfaceError: connection is closed`) and only recovers on the
    second — A/B verified by restarting the db container both ways. Matters more
    from M8, where api and db restart independently. No-op under the tests'
    NullPool.
- **Security audit (clean):** only `.env.example` has *ever* been tracked, in
  any commit, not just at HEAD; no db/dump/key files; no hardcoded secrets. The
  only credential-shaped strings in tracked code are the localhost dev defaults
  in `app/config.py` and `tests/conftest.py` (`plamotrack`/`plamotrack`) —
  throwaway, fine to publish, worth a glance if that ever stops being true.
- **State:** 89 backend tests green, ruff clean, `npm run build` green. Working
  tree clean, `main` pushed, repo public, release out. The dev DB holds seeded
  demo data (~21 kits, 12 orders, 4 retailers) created via the REST API for the
  screenshots — the user has confirmed it's all throwaway test data, so there's
  nothing here worth preserving on the dev Mac.
- **Next:** Milestone 5 (photos) — the §9.2 storage decision comes first, and it
  now has a second input: the user's own instance will run in a dedicated LXC on
  Proxmox, so "local volume" means a bind mount inside one container rather than
  anything exotic. That also shapes M8 packaging — single-host compose, not
  orchestration.
- **Now that it's public, for whoever picks this up:** the README's alpha warning
  is the only thing between a stranger and an unauthenticated write API. Don't
  weaken it, and don't describe planned endpoints as though they exist —
  `docs/design.md` marks every section ✅/🔨/💭 for exactly that reason. M7 (auth)
  is the gate on anyone sensibly exposing an instance.

## 2026-08-06 — Claude Code — Milestone 4.5: CSV import/export

- **Done:**
  - **`services/portability/`** — `spec.py` declares every table's CSV shape once
    (columns, parsers, roles, natural key, FK order); `exporting.py`,
    `importing.py`, `starter_sheet.py` all read it, so export/import/templates
    can't drift. A test asserts template headers == export headers.
  - **Export:** `GET /export/archive` (zip of 9 CSVs + `manifest.json` carrying
    export + schema versions, schema version = live Alembic revision + README),
    `GET /export/{table}.csv`, `/export/templates` (blank pack + COLUMNS.txt),
    `/export/starter-sheet.csv`. Every uuid FK gets a readable twin column
    (`retailer_name`), every `*_minor` a major-unit twin (`unit_price`) — the
    canonical column wins on import.
  - **Import:** `POST /import/preview` → full `ImportPlan` (per-row action,
    what it matched and how, field diffs, derived effects); `POST /import/apply`
    re-plans and 409s if `plan_hash` moved. Stateless — nothing cached between
    the two calls. Modes: merge / add_only / replace_all (typed `confirm=REPLACE`).
    One transaction; any bad row imports nothing.
  - **Starter sheet:** one denormalized row per kit → expands to
    retailers + orders + order lines, then goes through the *same* planner.
  - **Frontend:** `/data` page (export, templates, drag-drop import with mode
    selector, preview accordions, REPLACE gate), `ExportCsvButton` on Kits /
    Orders / Inventory / Retailers.
  - `docs/import-export.md` (user-facing format + matching reference), README
    section, AGENTS.md rules 9–10, design doc §12.
- **Decisions (user-confirmed up front):** hybrid dispatch (kits restored when
  the upload has them, spawned via the §3.9 fan-out when it doesn't);
  three conflict modes; natural-key matching per table with **kits deliberately
  excluded** (a kit row is one physical kit — name matching would merge real
  purchases); both a template pack and a single starter sheet.
- **Two invariants worth not breaking** (see AGENTS.md 9–10, §12.5):
  stock is only ever read from the catalog CSVs — importing orders never adjusts
  it, or re-import doubles it; and a blank cell in an *included* column means
  null while an *omitted* column is left alone, which is why the starter sheet
  emits only the columns it actually knows about (it was wiping retailer ratings
  until that was fixed — regression test covers it).
- **State:** 89 backend tests green (60 existing + 29 new), ruff clean,
  `npm run build` + lint green. Browser-verified live: starter sheet →
  6 created + 3 kits spawned; archive re-import → 0 new / 0 updated /
  24 unchanged; replace_all wipe-and-restore → collection byte-identical
  before/after. **No migration** — additive only. `python-multipart` added to
  backend deps (FastAPI needs it for uploads).
  Refactor: `orders._spawn_kits` → public `spawn_kits(...)` with keyword args so
  the importer reuses the real fan-out; `_spawn_from_details` wraps it for the
  REST payload shape.
- **Next:** Milestone 5 (photos) — §9.2 storage decision first. `kit_photos` is
  already registered in the portability spec and exports empty, so the archive
  shape won't change when photos land.

## 2026-08-06 — Claude Code — Status merge (in_hand → backlog) + dual board views

- **Done:**
  - **Merged in_hand into backlog** (migration `9d78b6148c30`, hand-written —
    enum value changes are invisible to autogenerate): they were functionally
    the same pile. Final pipeline: pre_ordered → ordered → in_transit →
    **backlog** (= in hand, not started; keeps in_hand's old position and teal)
    → building → complete. in_hand kits data-migrated; CHECK constraint
    rebuilt; receive/spawn flows now advance to backlog. MCP `_parse_status`
    gained aliases (in_hand/arrived/received → backlog) for agents with stale
    vocabulary.
  - **Board views**: Build (default — Backlog/Building/Complete) and Orders
    (Pre-ordered/Ordered/In Transit + one aggregate **Received** column
    grouping the three build states, cards showing their status badge).
    Dropping on Received = backlog unless the kit is already past it. Toggle
    persists in localStorage (`plamotrack.boardView`).
- **State:** 60 backend tests + 2 E2E green (drag test now runs in the default
  Build view); design doc §1.1/§3.1 amended. Committed + pushed.
- **Next:** Milestone 5 (photos) — §9.2 storage decision first.

## 2026-08-06 — Claude Code — Milestone 4: Kanban board + deferred review items

- **Done:**
  - **Board page** (`/board`, now the index route) with @dnd-kit/core: seven
    color-accented status columns, draggable kit cards (grade/scale/kit# chips,
    rating stars), DragOverlay ghost, per-column counts. Drops call the same
    `PATCH /kits/{id}` as the table's dropdown, with an **optimistic cache
    update** (rollback on error, invalidate on settle) so cards land instantly.
  - dnd-kit subtleties handled: `pointerWithin` collision with a
    `rectIntersection` fallback (pointerWithin alone breaks keyboard drags),
    and a **custom keyboard coordinate getter** that jumps one whole column per
    arrow press (the default 25px nudges get cancelled by board auto-scroll).
    Keyboard: focus card → Enter → arrows → Enter.
  - Deferred review items: list-query failures now render error banners instead
    of fake empty states (all pages); Receive has a confirm dialog; **Playwright
    happy-path E2E** (`frontend/e2e/`, `npm run test:e2e`): order with new
    retailer + typeahead-created consumable → pending (stock 0) → receive
    (stock 3, kit In Hand) → real stepped mouse drag to Building. Runs against
    the dev stack, uniquely-named data, cleans up after itself via the API
    (including un-progressing the kit so undo-delete passes). Chromium via
    `npx playwright install chromium`.
- **Notes:** in-pane synthetic single-step drags don't satisfy the
  PointerSensor activation constraint — that's an automation artifact; human
  mouse drag (user-verified) and Playwright stepped drags both work. No
  intra-column manual ordering (nothing in the schema backs it) — columns sort
  by status_updated_at desc.
- **State:** frontend build + lint green, 2/2 E2E green, 60 backend tests
  untouched. Committed + pushed.
- **Next:** Milestone 5 — photo upload + gallery. **Decision gate first:
  §9.2 photo storage backend** (local volume default vs S3/MinIO opt-in)
  before writing the upload handler.

## 2026-08-06 — Claude Code — Integrity fixes from external review (GPT 5.6)

- **Done:** three backend integrity fixes, all with regression tests
  (`tests/test_integrity.py`, suite now 60):
  1. `_get_order_for_write` now locks the order row (`FOR UPDATE`) — concurrent
     `receive_order` calls serialize; the loser 409s instead of applying stock
     twice. Test drives two simultaneous receives via asyncio.gather and
     asserts exactly one success + single stock application.
  2. `get_or_create_retailer` no longer commits — it joins the caller's
     transaction, so a failed MCP order rolls back its implicitly-created
     retailer. Happy path (case-insensitive reuse) re-tested.
  3. Order-spawned kits are blocked from direct deletion (409 pointing at
     order editing) so line quantity and surviving kits can't drift; the edit
     diff also now computes against actual kit counts as defense in depth.
     Standalone kits still delete normally.
- **Not done (deferred, from the same review):** surface frontend query
  failures as errors (not empty states); confirmation dialog on Receive;
  Playwright happy-path test. Queue these with or before Milestone 4 frontend
  work. A proper "disposed/sold" kit state is the long-term answer for removing
  an order-spawned kit from the collection without touching purchase history.
- **State:** 60 backend tests green; committed + pushed.

## 2026-08-06 — Claude Code — Order lifecycle (pending→received) + full CRUD

- **Done:**
  - **Stock timing fix:** `orders.received_at` (migration `6cbd8315df95`,
    existing orders backfilled as received). Catalog stock now increments on
    receive, not at entry; `POST /orders/{id}/receive` + "Receive" button +
    MCP `mark_order_received` / `list_orders(pending_only)`. Receiving advances
    pipeline kits to in_hand; `received: true` at creation covers store buys.
  - **Order edit (full line diffing):** `PATCH /orders/{id}` takes header fields
    and/or a replacement `items` set (line `id` = update, no id = add, omitted =
    remove-and-undo). Kit detail edits propagate to all spawned kits; quantity
    changes spawn/delete kits; target/qty changes on received orders adjust
    stock. item_type changes rejected (frontend drops the id → remove+add).
  - **Order delete = undo:** kits removed, applied stock reversed.
  - **Guards:** progressed kits (building/complete, rated, or with photos) and
    below-zero stock block destructive edits with clear 409s.
  - **CRUD gaps closed:** PATCH/DELETE for tools/consumables/upgrades/retailers
    with history guards (referenced by order lines / applications / orders →
    409). Frontend: edit/delete on Inventory + Retailers, order edit modal
    (reconstructs lines incl. prices in major units), Pending/Received chips.
  - **Retailer report card** (parity with the old Baserow base, migration
    `e720578b82de`): `rating` 1–5, `packing_quality`
    (excellent/good/average/below_average/poor), `shipping_speed`
    (very_fast/fast/average/slow/very_slow), `would_order_again`
    (yes/maybe/no) — all optional, text-enum CHECKs, in the form + table.
  - **`orders.order_number`** (migration `04315056a82f`): the retailer's own
    reference, for support contact. Nullable text, deliberately NO uniqueness
    constraint — only unique per retailer at best, never an internal identifier
    (UUIDs remain identity). In the order form/table and MCP create_order.
- **Decisions (user-confirmed):** undo-dispatch on delete; full line editing;
  order-level received state (split shipments = separate orders, no per-line
  receiving); kits auto-advance on receive.
- **State:** 56 backend tests green; frontend build + lint green; browser-
  verified live (defer→receive stock flow, rename propagation, undo delete,
  delete guards, retailer report card, order number). Committed + pushed along
  with Milestone 3. The local design doc is amended to Draft v1.1 (§3.7, §3.8,
  §3.9 lifecycle amendment, §4, §7, §11 ticks).
- **Next:** Milestone 4 (Kanban) still queued. Possible follow-up: un-receive
  action (reverse a mistaken receive) — not built, delete/re-enter covers it.

## 2026-08-06 — Claude Code — Milestone 3: frontend (tables + forms)

- **Done:**
  - `frontend/`: Vite + React 19 + TS, Tailwind v4, TanStack Query,
    react-hook-form, react-router. Dev proxy: app calls `/api/*` → Vite strips
    the prefix → backend :8000 (prod nginx will mirror this at M8).
  - Pages: Kits (search/status filter, add/edit modals, inline status dropdown =
    Kanban precursor, delete), Inventory (tools/consumables/upgrades tabs,
    low-stock highlight, apply-upgrade-to-kit dialog), Retailers, Orders
    (expandable rows with per-line detail + multi-currency totals; new-order
    modal with retailer quick-add and per-line dispatch).
  - **CatalogItemPicker** implements §3.9 select-or-create: debounced typeahead
    against `/catalog/search`, pick-existing or create-new — no free-text path.
  - Browser-verified end to end: order (2× kit + new consumable) → fan-out to 2
    kits with derived 1/144 scale, stock at 3, totals correct, status changes.
- **Fixed (backend):** read-after-write race — FastAPI runs yield-dependency
  teardown (where the commit lived) *after* sending the response, so the UI's
  invalidate-and-refetch could read pre-commit state. Mutating service functions
  now commit explicitly before returning; `db.session_scope` keeps a no-op
  safety-net commit. All 27 backend tests still pass (atomic rollback included).
- **Decisions:**
  - Prices entered in major units, converted to minor via Intl fraction digits
    (JPY → 0). All lines share the order currency in the UI (API still supports
    per-line). `converted_price_aud_minor` auto-set only when currency is AUD —
    FX lookup remains the §6 nice-to-have, not built.
  - No frontend unit tests this milestone — verified via live browser E2E;
    Playwright is a candidate once the Kanban lands.
- **State:** backend tests green, `npm run build` + lint green, **uncommitted**.
  Dev DB holds a bit of demo data (1 order, 2 kits, 1 consumable, 1 retailer) —
  deletable via the UI. `.claude/launch.json` starts the Vite dev server.
- **Next:** Milestone 4 — Kanban board with dnd-kit (drag card between status
  columns → `PATCH /kits/{id}`), reusing the inline-status mutation pattern.

## 2026-08-06 — Claude Code — Milestones 1+2: schema, REST API, MCP server

- **Done:**
  - Repo scaffold: `.gitignore`, `.env.example`, `docker-compose.yml` (db only),
    uv-managed `backend/`.
  - All 9 tables as SQLAlchemy 2.0 async models + one hand-checked Alembic
    migration (`71ddc06de024`). Text enums with CHECK constraints; stock/rating
    guards; `ondelete` cascades; `kits.order_item_id` provenance (nullable — Backlog
    kits pre-date orders).
  - Service layer with the §3.9 fan-out/increment dispatch (single transaction,
    full rollback on any bad line), row-locked stock mutations, catalog search,
    grade→scale derivation (HG/RG/EG→1/144, MG→1/100, PG→1/60, SD→non-scale).
  - REST API per §4 (kits CRUD incl. Kanban PATCH, tools/consumables/upgrades,
    `/upgrades/{id}/apply`, retailers, orders with nested items, `/catalog/search`).
  - All 7 §7 MCP tools via FastMCP **v3**, mounted at `/mcp` on the REST port
    (deviation from §8's two-port layout — simpler, split later if needed).
    Agent niceties: status normalization ("In Transit" → `in_transit`),
    case-insensitive get-or-create retailer in `create_order`.
  - 27 tests (REST + in-memory MCP client) incl. atomicity and stock-guard cases.
  - Verified live: REST smoke + MCP-over-HTTP smoke both good.
- **Decisions:**
  - Photo endpoints deferred to M5 (`kit_photos` table exists, schema-only).
  - No auth yet — matches M1 scope; auth is M7.
  - `POST /orders` kit lines carry `kit` details (name/grade/…); catalog lines take
    `catalog_ref_id` XOR `new_item` (select-or-create at the API level).
  - Tests run real migrations both directions every run + auto-create the test DB.
- **State:** all green — `docker compose up -d db --wait` then `uv run pytest`
  → 27 passed; ruff clean. Dev DB migrated and empty. OrbStack installed by the
  user (auto-starts); earlier brew-Postgres workaround retired (leftover
  `.dev/pgdata` is inert and gitignored).
- **Next:** Milestone 3 — `frontend/` (React + Vite + TS + dnd-kit): table views
  and forms against the REST API. Open §9 decisions unchanged (taxonomy before
  config UI; photo storage backend before M5 upload handler).
