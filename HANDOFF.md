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
