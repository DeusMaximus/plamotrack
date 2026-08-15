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
- **Say which model wrote it.** Every agent here posts through the owner's GitHub
  account, so an unsigned comment on a public repo reads as the owner speaking —
  including its first-person claims about what was verified and its judgement calls
  about severity. Any PR or issue comment an agent writes opens with a line naming
  the model and what the comment is, and closes with a sign-off:

  ```markdown
  **Claude (Anthropic) — response to the Codex review, at head `9d751ca`.**
  …
  — **Claude Opus 5 (Anthropic)**, via Claude Code
  ```

  Codex's review of #75 did this; the reply to it did not, and had to be corrected
  after the fact. Commits are already covered by their `Co-Authored-By` trailer —
  this is the gap that leaves. It matters most on exactly the threads where it is
  easiest to forget: a review exchange, where a reader is weighing whose reasoning
  to trust, and where two different models may be arguing with each other.

## Layout

```
docker-compose.yml      # the full stack: web (nginx) + api + migrate + db.
                        #   `up -d --wait` installs without publishing Postgres
docker-compose.dev.yml  # explicit dev overlay: publishes Postgres on loopback only
.env                    # the only config file (gitignored); .env.example is the template
                        #   compose + API both read it; app/config.py assembles the DSN
                        #   from POSTGRES_* unless DATABASE_URL is set explicitly
backend/
  Dockerfile            # multi-stage uv build; also the migrate service's image
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
  Dockerfile            # node build -> nginx:alpine
  nginx.conf            # THE ingress. Read the comments before touching the /mcp or
                        #   resolver lines — both encode bugs found by testing (§8)
  src/
    api/                # hand-typed API client + types mirroring backend schemas
    components/         # Layout, Modal, ui primitives, CatalogItemPicker (§3.9 select-or-create)
    pages/              # BoardPage (Kanban), KitsPage, OrdersPage, InventoryPage,
                        #   RetailersPage, DataPage (import/export)
  e2e/                  # Playwright happy-path (runs against the dev stack, self-cleaning)
docs/design.md          # product intent + architectural decision record (§n targets)
docs/import-export.md   # user-facing CSV format + matching reference
docs/operations.md      # backup / restore / upgrade for the container stack
```

## Dev environment & commands

Postgres comes from Docker (OrbStack on the primary dev Mac, auto-starts). For
development, run **only** the db service and the app from source — the container
stack has no hot reload, and both want port 5432:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db --wait
```

To exercise the packaged stack instead (before touching Dockerfiles, `nginx.conf`,
or anything about startup ordering):

```bash
docker compose up -d --wait   # http://127.0.0.1:8080 — builds on first run
docker compose logs migrate   # migrations; Exited (0) is success
docker compose down           # add -v ONLY to destroy the database
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
   `converted_price_minor` + `converted_currency_code` are an entry-time snapshot —
   never recompute them, and never render the amount using the *current*
   `REFERENCE_CURRENCY` instead of the code stored on the row (§6). The pair is
   null-or-present together, enforced by a CHECK constraint. The instance default
   lives in `settings.reference_currency` and is stamped in by the service layer at
   write time; `converted_price_aud_minor` survives only as a CSV import alias.
5. **Enums are text + CHECK constraint,** not native Postgres enums — the
   generic-vs-Gunpla taxonomy question (§9.1) is still open, keep it a data migration.
6. **Errors:** services raise `app.exceptions` domain errors (`NotFoundError`,
   `ConflictError`, `InvalidInputError`); the REST handler and MCP ToolError
   conversion are already wired — don't raise HTTP exceptions from services.
7. **Stock mutations** use row locks (`with_for_update`) — three concurrent writer
   types exist by design (UI, REST, MCP agents).
8. **Public read paths (Milestone 8)** must be genuinely separate route handlers
   under `/public/*` — not filtered views (§5). Public ingress must not expose an
   unauthenticated admin or MCP route; route separation is enforced at both the app
   and proxy layers.
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
11. **Instance settings and localisation (Milestone 5.1):** plamotrack remains a
    single-owner application, so interface language, formatting locale, time zone,
    date style, hour cycle, and reference currency are instance-wide settings — not
    browser-only preferences. `en-AU` is the canonical source catalogue and fallback;
    additional languages ship from the repository through reviewed PRs. Keep language
    separate from regional formatting, keep canonical API/MCP/database/CSV identifiers
    untranslated, and never let a settings change reinterpret historical money.

## Fixing a defect: sweep the class first

The rules above define defect *classes*, not just defects. A violation found in one
code path is evidence about every other path under the same rule — so before fixing
the instance in hand, enumerate the rest of the class.

The cost of not doing this is on the record. #3 (an order-line edit discarding its
conversion snapshot) was one rule-4 money defect. Fixing it exposed #12 (a CSV import
relabelling that same snapshot), which exposed #6 (minor units read off the runtime
instead of ISO 4217), which exposed #19 (`tools.unit_cost_reference` — a scaled
decimal with no currency column at all). Four branches, four reviews and two releases,
for four instances of one rule applied unevenly, all of which one pass over the paths
touching money would have found at the start.

- **Name the rule** the defect violates — a numbered rule above, or a `§n`. If it
  violates none, it's a one-off: fix it and move on.
- **Enumerate the paths that rule governs** before writing the fix: service layer,
  REST, MCP, CSV import, CSV export, the browser, and the schema itself. They diverge
  independently — a corrected service function does not mean the importer agrees.
  `services/portability/spec.py`, `frontend/src/lib/format.ts` and the models are
  where the last four hid.
- **File the siblings even if you won't fix them now.** An unfiled sibling is
  indistinguishable from a bug nobody has noticed. Milestone or don't, but file.
- **Fix the class in one branch** where the instances share a root cause, and say so
  in the PR. Where they genuinely don't — a schema migration, an open design question
  — separate branches are right, but the issues should already exist.
- **Cross-layer behaviour gets a shared fixture, not one test suite per side.**
  `frontend/src/lib/__fixtures__/money-cases.json` is read by both `format.test.ts`
  and `backend/tests/test_currency.py`. Two hand-maintained lists drift, and a drifted
  pair reads green on both sides with a wrong number in the database. Add cross-layer
  cases there. This is also the check on the fix itself: the #6 rewrite silently broke
  exponent input (`1e2` stored as `0`) in a file that then had no tests.

## Writing the test: sweep the values, not just the paths

The sweep above finds code paths that drifted apart. It does nothing about a test that
walks the right path carrying the wrong values — and that is now the more expensive
mistake on this repo's record.

Four regression suites have now been written for a known defect, reviewed, run against
the unfixed code, and still missed something. Each failed differently:

- **#65** seeded a **quantity-one** kit line. The defect was one line's kits being
  flattened onto each other, which a single kit cannot express. The test drove the
  exact code path and proved nothing.
- **#66**'s warm-cache detector was **timing-dependent**. It passed against the broken
  code because on localhost the refetch beat the assertion; only stalling the request
  with `page.route` made the stale window certain.
- **#69** compared a field where both sides already held the same non-null value, so the
  derivation that caused the defect was a no-op. The comparison was exercised only where
  it could not be wrong.
- **#41** swept its field's values properly — absent column, blank cell, sheet-supplied
  id, conjured stub — and ran every one of them through a **create**. The leak it existed
  to prevent puts a minted uuid in a row's `changes` list, and `changes` is empty on a
  create, so it could not appear in any test in the suite. It was latent in the *previous*
  fingerprint too and the rewrite inherited it unseen; an external review found it. No
  additional *value* would have helped — the axis never varied was the row's **action**.
- **#42** had a seven-case matrix over `manifest.json`'s `tables` block — absent, a string,
  a non-object entry, a missing count, a non-numeric count, a null name, a boolean count —
  and every case wrote it inside a JSON **object**. The importer's first act is
  `data.get("tables")`, so a manifest of `[]` was an `AttributeError` 500 no case in the
  matrix could reach. The axis was the container, not the thing inside it. Its sibling test
  drove one member-decompression failure (a bad CRC) and so missed the other two the same
  `except` clause was meant to cover. Both found by external review.

So when a fix turns on **comparing or branching on a field**, enumerate what that field
can legitimately hold before writing the assertions: null, empty, whitespace, the derived
or default value, and something that genuinely differs. Drive at least the null and the
default. If the rule is about rows diverging, seed more than one row. If the rule is
about timing, pin the timing rather than hoping.

**Values are one axis. The state the row is in is another, and it decides whether the
field is even present to be wrong.** `changes` is empty on a create; `matched_id` is null
until something matches; a spawn descriptor exists only for a kit line short of kits; a
`replace_all` has a deletion set and a merge has none. Twenty values inside one action
say nothing about the actions never entered. So where a fix touches a structure whose
*shape* is decided by a classification — an action, a mode, a status — drive at least two
of them, and prefer the one that makes the structure non-empty.

**Running the test against the unfixed code is necessary and not sufficient.** All four
above were, and passed. A red test proves it detects the case you thought of; it says
nothing about the case you didn't, and nothing at all about the states you never put the
row into. #41's suite was red exactly where it looked and blind everywhere else.

**A test that asserts a status has to be able to see one.** The default `client` fixture
re-raises unhandled application exceptions into the test, so a route that 500s fails the
assertion as an *error* naming some internal exception — red, but silent on what the status
should have been. Use the `http_client` fixture, which returns the 500 as a response,
wherever the point of the test is which status a bad input earns (rule 6).

## Roadmap (design notes §11)

1. ~~Schema + migrations + REST CRUD~~ ✅
2. ~~MCP tools on the shared service layer~~ ✅
3. ~~Frontend: table views + basic forms~~ ✅
4. ~~Kanban board (drag-and-drop, dnd-kit)~~ ✅
4.5. ~~Import/export: CSV archive + manifest, preview, templates~~ ✅ (§12)
→ **Public alpha ships here.** Everything below is built in the open.
5. ~~Installability: full local Docker Compose stack, safe loopback defaults,
   migrations, health checks, backup/upgrade docs~~ ✅ (§8, `docs/operations.md`)
   — also shipped the configurable reference currency, pulled forward from 5.1
5.1. Instance settings + internationalisation foundation: singleton settings,
     `en-AU` source catalogue and fallback, reviewed language contributions,
     locale-aware presentation, Settings page (absorbing Data), and structured
     REST/import diagnostics; no non-English translation required
6. Secure remote access: single-owner browser auth, scoped REST/MCP tokens,
   OAuth-compatible MCP, tested TLS/VPS deployment path
6.1. MCP modernisation: dual-era current + `2026-07-28` compatibility with
     conformance and client coverage
7. Photo upload + gallery ← decide storage backend default first (§9.2)
8. Public read-only routes + showcase page ← only after admin/MCP paths are protected
9. Open-source operations: contribution guide, release automation, support matrix,
   deployment-doc polish

The repo goes public at 4.5 as an alpha (§10, revised) rather than waiting for
milestones 1–6. Consequence for anything written from here on: **the audience is
strangers.** No internal references, no assumed context, and disclose what isn't
built rather than describing planned endpoints as if they exist. Nothing is
authenticated yet (M6) — an alpha instance belongs on a trusted network.
