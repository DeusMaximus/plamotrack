# AGENTS.md — plamotrack

Guidance for AI coding agents (Claude Code, Codex, …) and humans working in this repo.

**plamotrack** is a self-hosted, open-source Gunpla/plamo collection & build tracker:
kits move through a pipeline (pre_ordered → ordered → in_transit → backlog →
building → complete; backlog = in hand, not started) on a drag-and-drop Kanban
board with Build and Orders views, alongside
quantity-tracked tools, consumables, and third-party upgrades. Ships as a Docker
Compose stack: FastAPI REST API + embedded MCP server (same process, shared service
layer), Postgres, React frontend. Single-collection per instance, MIT licensed.

## Session protocol (multi-agent hand-off)

- **Session start:** read `HANDOFF.md` (newest entry first) for current state,
  in-flight work, and known breakage.
- **Session end:** append an entry to `HANDOFF.md` using its template. Keep it short
  and factual — the next agent may be a different model with zero shared context.
- **Design notes:** `docs/design.md` — tracked, public, and **not** a spec. It records
  product intent and the reasoning behind architectural decisions; `§n` references in
  code comments and docs point at its sections. Where it and the code disagree, the
  code is right and the doc is behind — update the doc in the same commit rather than
  bending the code to match it. The binding rules for agents are the architecture
  rules below, not the design notes.

## Git conventions

- **Feature work goes on a branch**, then a PR — not straight to `main`. The repo
  went public at Milestone 4.5 (2026-08-06); `main` is now what strangers clone,
  and outside contributors can open PRs against it. Direct-to-main was a
  private-and-solo convenience and is retired.
- Exception: session bookkeeping and process docs that exist to be read *between*
  sessions — `HANDOFF.md` entries, `AGENTS.md` notes — commit on `main`. Branching
  a hand-off entry just delays the next agent from seeing it.
- **Commit or push only when the user asks.** Don't take a green test run as
  permission.
- Anything outward-facing — pushing a tag, cutting a release, changing repo
  settings or visibility — needs explicit confirmation each time. Approval for one
  doesn't carry to the next.

## Layout

```
docker-compose.yml      # dev: db only; api/frontend services land at Milestone 8
.env                    # the only config file (gitignored); .env.example is the template
                        #   compose + API both read it; app/config.py assembles the DSN
                        #   from POSTGRES_* unless DATABASE_URL is set explicitly
backend/
  app/
    models/             # SQLAlchemy 2.0 async models — 9 tables
    schemas/            # Pydantic v2 request/response models
    services/           # ALL business logic lives here (see rules below)
      portability/      # CSV import/export — spec.py registry drives all of it
    routers/            # REST endpoints — thin, delegate to services
    mcp.py              # MCP tools — thin, delegate to the same services
    main.py             # app factory; MCP mounted at /mcp on the REST port
  alembic/              # async migrations; text enums + CHECK constraints
  tests/                # pytest against real Postgres, in-memory MCP client tests
frontend/               # React + Vite + TS, Tailwind v4, TanStack Query, react-hook-form
  src/
    api/                # hand-typed API client + types mirroring backend schemas
    components/         # Layout, Modal, ui primitives, CatalogItemPicker (§3.9 select-or-create)
    pages/              # BoardPage (Kanban), KitsPage, OrdersPage, InventoryPage,
                        #   RetailersPage, DataPage (import/export)
  e2e/                  # Playwright happy-path (runs against the dev stack, self-cleaning)
docs/design.md          # product intent + architectural decision record (§n targets)
docs/import-export.md   # user-facing CSV format + matching reference
```

## Dev environment & commands

Postgres comes from Docker (OrbStack on the primary dev Mac, auto-starts):

```bash
docker compose up -d db --wait
```

Backend is uv-managed — run everything from `backend/`:

```bash
uv sync                      # install deps
uv run pytest                # tests: auto-creates plamotrack_test DB, runs alembic
                             # downgrade+upgrade, truncates tables between tests
uv run ruff check --fix . && uv run ruff format .   # lint+format — run before committing
uv run alembic upgrade head  # apply migrations to the dev DB
uv run uvicorn app.main:app  # REST on :8000, MCP endpoint at /mcp/
```

Frontend is npm-managed — run from `frontend/` (needs the backend on :8000; the
dev server proxies `/api/*` there, stripping the prefix):

```bash
npm install
npm run dev                  # Vite on :5173
npm run build                # tsc type-check + production build — run before committing
npm run lint                 # oxlint
npm run test:e2e             # Playwright happy-path (needs chromium: npx playwright install chromium);
                             # reuses running dev servers, creates + cleans its own data
```

Schema changes: edit models → `uv run alembic revision --autogenerate -m "..."` →
**hand-check the generated migration** (constraint names, ondelete, enum CHECKs) →
`upgrade head` → make sure tests still pass both migration directions.

## Architecture rules (do not violate)

1. **Business logic lives in `app/services/` only.** Routers and MCP tools are thin
   wrappers over the same service functions — REST and MCP must never diverge. If
   you add an endpoint or tool, its logic goes in a service both can call.
2. **Order line dispatch (§3.9, amended):** `item_type=kit` lines fan out into N
   `kits` rows (with `order_item_id` provenance) at entry. Catalog lines increment
   `quantity_on_hand` **only when the order is received** (`received_at`) —
   quantity means *physically on hand*, not on order. Receiving also advances
   pipeline kits (pre_ordered/ordered/in_transit → backlog). One transaction per
   order — any bad line rolls back all of it.
   - Order **edit** re-runs the dispatch diff (kit details propagate to spawned
     kits; quantity/target changes spawn/remove kits and adjust applied stock).
   - Order **delete = undo the entry**: kits removed, applied stock reversed.
   - Guards everywhere: progressed kits (building/complete, rated, or with
     photos) and already-consumed stock block destructive edits with a 409.
   - Order-spawned kits cannot be deleted directly (409) — undo happens at the
     order line, so purchase records and the collection never drift.
   - All order mutations load the order row `FOR UPDATE` — concurrent
     receive/edit/delete serialize instead of double-applying stock.
3. **Catalog de-dup (§3.9):** catalog items are select-or-create — order lines take
   `catalog_ref_id` (from `/catalog/search` / `search_catalog`) or `new_item`, never
   free-text names. Don't add code paths that bypass this.
   Catalog items and retailers referenced by order history (or upgrade
   applications) cannot be deleted — edit them instead; history is fact (§6 ethos).
4. **Money:** integer minor units + ISO 4217 `currency_code`, never floats.
   `converted_price_aud_minor` is an entry-time snapshot — never recompute it (§6).
5. **Enums are text + CHECK constraint,** not native Postgres enums — the
   generic-vs-Gunpla taxonomy question (§9.1) is still open, keep it a data migration.
6. **Errors:** services raise `app.exceptions` domain errors (`NotFoundError`,
   `ConflictError`, `InvalidInputError`); the REST handler and MCP ToolError
   conversion are already wired — don't raise HTTP exceptions from services.
7. **Stock mutations** use row locks (`with_for_update`) — three concurrent writer
   types exist by design (UI, REST, MCP agents).
8. **Public read paths (Milestone 6)** must be genuinely separate route handlers
   under `/public/*` with no write capability reachable — not filtered views (§5).
9. **CSV shape is declared once**, in `services/portability/spec.py`. Export,
   import, and the blank templates all read that registry — never hand-write a
   header or a parser anywhere else, or the three drift and a template starts
   describing columns the importer won't accept (there's a test guarding this).
   Adding a model column = adding one `col(...)` line.
10. **Import never invents stock.** `quantity_on_hand` comes only from the
    catalog CSVs; importing orders never adjusts it. Re-importing an archive
    must be a no-op, and deriving stock from received orders would double it.
    Kits are the mirror image: they're spawned from an order line *only* when
    nothing else in the upload supplies them (§3.9 hybrid dispatch).

## Roadmap (design notes §11)

1. ~~Schema + migrations + REST CRUD~~ ✅
2. ~~MCP tools on the shared service layer~~ ✅
3. ~~Frontend: table views + basic forms~~ ✅
4. ~~Kanban board (drag-and-drop, dnd-kit)~~ ✅
4.5. ~~Import/export: CSV archive + manifest, preview, templates~~ ✅ (§12)
→ **Public alpha ships here.** Everything below is built in the open.
5. Photo upload + gallery ← decide storage backend default first (§9.2)
6. Public read-only routes + showcase page
7. Auth on the write path (single-user)
8. Docker Compose packaging + setup docs
9. Open-source polish: README, screenshots, contribution guide

The repo goes public at 4.5 as an alpha (§10, revised) rather than waiting for
milestones 1–6. Consequence for anything written from here on: **the audience is
strangers.** No internal references, no assumed context, and disclose what isn't
built rather than describing planned endpoints as if they exist. Nothing is
authenticated yet (M7) — an alpha instance belongs on a trusted network.
