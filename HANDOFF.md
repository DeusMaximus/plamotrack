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

## 2026-08-06 — Claude Code — Public alpha prep: design doc published, README

- **Done:**
  - **Design doc is now tracked at `docs/design.md`** (was the untracked
    `plamotrack-design-doc.md`; its `.git/info/exclude` line is removed).
    Sanitised for a public audience: internal-project references replaced with
    the underlying rationale, second-person/personal phrasing removed, the
    two-port MCP sketch corrected to the mounted `/mcp` route.
    **Reframed from spec to decision record** — it now says outright that it
    isn't a contract and that the code wins where they disagree. Every section
    carries a ✅ Built / 🔨 Planned (Mn) / 💭 Open marker; §4 splits into built
    vs planned endpoints, and §5 (auth + `/public/*`) is labelled as entirely
    unimplemented. §9.1–§9.4 are now explicitly numbered so code comments
    referencing them resolve.
  - **§10 rewritten for the public alpha**: repo goes public at 4.5 instead of
    waiting for M1–6, with the four disclosures (no auth, no bundled
    containers, no photos/showcase, schema still moving). §12.6 realigned —
    code going public ≠ an instance going on the internet; M7 still gates that.
  - **README** fleshed out from the stub: alpha warning up top, feature
    sections with six screenshots, install steps, MCP wiring for Claude
    Desktop (connector UI + `mcp-remote` fallback) and Claude Code, tool table,
    what-isn't-built table. Tone is deliberately light per design notes §10.1.
  - **`docs/screenshots/`** — six 2× retina PNGs (~1.5 MB total) captured via
    Playwright against the dev stack. Script is throwaway; re-shoot by driving
    chromium from `frontend/` so `@playwright/test` resolves.
  - AGENTS.md: design-doc bullet rewritten (tracked, not a spec, not binding —
    the architecture rules are), `docs/design.md` added to Layout, roadmap notes
    the alpha ships at 4.5 and that the audience is now strangers.
  - **Config consolidated to one `.env`** (was root `.env` for compose +
    `backend/.env` for the API, with the password written twice and required to
    match). `app/config.py` now declares `POSTGRES_USER/PASSWORD/DB/HOST/PORT`
    and **assembles** the DSN from them, URL-quoting the credentials so a
    password containing `@` or `/` can't produce a DSN that parses to the wrong
    host. `DATABASE_URL` still overrides wholesale — `tests/conftest.py` and the
    M8 container both depend on that. `env_file` is now an absolute pair
    (`<root>/.env`, `<backend>/.env`, later wins) anchored on `__file__` rather
    than the cwd-relative `".env"`, so launching from the repo root and from
    `backend/` resolve identically; they previously didn't. Compose publishes
    `${POSTGRES_PORT:-5432}`, so moving the port is one edit. `backend/.env` is
    now redundant — deleted locally, still honoured if present.
- **Security audit (clean):** only `.env.example` has *ever* been tracked, in
  any commit; no db/dump/key files; no hardcoded secrets. The only
  credential-shaped strings in tracked code are the localhost dev defaults in
  `app/config.py` and `tests/conftest.py` (`plamotrack`/`plamotrack`) —
  throwaway, fine to publish, worth a glance if that ever stops being true.
- **State:** 89 backend tests green. **Nothing committed** — the user is
  reviewing the README first. **The dev DB now holds seeded demo data** (~21
  kits, 12 orders, 4 retailers) created for the screenshots via the REST API;
  a pre-seed archive export was taken if it needs reverting.
- **Next:** commit after review, then Milestone 5 (photos) — §9.2 storage
  decision still first.

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
