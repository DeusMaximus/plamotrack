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
