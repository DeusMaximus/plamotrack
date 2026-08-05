# AGENTS.md — plamotrack

Guidance for AI coding agents (Claude Code, Codex, …) and humans working in this repo.

**plamotrack** is a self-hosted, open-source Gunpla/plamo collection & build tracker:
kits move through a build pipeline (backlog → pre_ordered → ordered → in_transit →
in_hand → building → complete) on a drag-and-drop Kanban board, alongside
quantity-tracked tools, consumables, and third-party upgrades. Ships as a Docker
Compose stack: FastAPI REST API + embedded MCP server (same process, shared service
layer), Postgres, React frontend. Single-collection per instance, MIT licensed.

## Session protocol (multi-agent hand-off)

- **Session start:** read `HANDOFF.md` (newest entry first) for current state,
  in-flight work, and known breakage.
- **Session end:** append an entry to `HANDOFF.md` using its template. Keep it short
  and factual — the next agent may be a different model with zero shared context.
- **Design doc:** the authoritative spec lives locally at `plamotrack-design-doc.md`,
  deliberately untracked via `.git/info/exclude` — **never commit it**. `§n`
  references in code comments and docs point at its sections. If the file is absent
  in your checkout, this file plus `HANDOFF.md` are your context.

## Layout

```
docker-compose.yml      # dev: db only; api/frontend services land at Milestone 8
.env / backend/.env     # local values (gitignored); .env.example is the template
backend/
  app/
    models/             # SQLAlchemy 2.0 async models — 9 tables
    schemas/            # Pydantic v2 request/response models
    services/           # ALL business logic lives here (see rules below)
    routers/            # REST endpoints — thin, delegate to services
    mcp.py              # MCP tools — thin, delegate to the same services
    main.py             # app factory; MCP mounted at /mcp on the REST port
  alembic/              # async migrations; text enums + CHECK constraints
  tests/                # pytest against real Postgres, in-memory MCP client tests
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

Schema changes: edit models → `uv run alembic revision --autogenerate -m "..."` →
**hand-check the generated migration** (constraint names, ondelete, enum CHECKs) →
`upgrade head` → make sure tests still pass both migration directions.

## Architecture rules (do not violate)

1. **Business logic lives in `app/services/` only.** Routers and MCP tools are thin
   wrappers over the same service functions — REST and MCP must never diverge. If
   you add an endpoint or tool, its logic goes in a service both can call.
2. **Order line dispatch (§3.9):** `item_type=kit` lines fan out into N `kits` rows
   (with `order_item_id` provenance); tool/consumable/upgrade lines increment
   `quantity_on_hand`. One transaction per order — any bad line rolls back all of it.
3. **Catalog de-dup (§3.9):** catalog items are select-or-create — order lines take
   `catalog_ref_id` (from `/catalog/search` / `search_catalog`) or `new_item`, never
   free-text names. Don't add code paths that bypass this.
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

## Roadmap (design doc §11)

1. ~~Schema + migrations + REST CRUD~~ ✅
2. ~~MCP tools on the shared service layer~~ ✅
3. Frontend: table views + basic forms (React + Vite + dnd-kit, `frontend/`)
4. Kanban board (drag-and-drop)
5. Photo upload + gallery ← decide storage backend default first (§9.2)
6. Public read-only routes + showcase page
7. Auth on the write path (single-user)
8. Docker Compose packaging + setup docs
9. Open-source polish: README, screenshots, contribution guide

Repo stays private until milestones 1–6 are done (§10).
