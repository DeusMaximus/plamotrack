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
  in-flight work, and known breakage. It holds only the five most recent entries;
  the rest are archived under `.agents/handoff/` — grep that, don't read it (the
  recipe is in `HANDOFF.md`'s header).
- **Session end:** append an entry to `HANDOFF.md` using its template — ≤ ~60
  lines, state not lessons — then **rotate**: if the file now holds more than five
  entries, move the oldest to the top of `.agents/handoff/YYYY-MM.md`, verbatim,
  in the same commit. The header there spells out the rules; the next agent may be
  a different model with zero shared context and a small context window.
- **`.agents/testing-and-review.md`** is the procedure — suites, harnesses, the
  release gate, which reviewer for what, how to answer a review. Read it before
  writing a regression test for a filed defect, before opening a PR for review,
  when responding to a review, and before cutting a release. Not on every turn.
- **`.agents/lessons.md`** is why the rules below say what they say — the case
  histories, append-only, stable headings. Read a section when a rule looks like
  over-engineering, or before arguing one down in a review.
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
  sessions — `HANDOFF.md` entries and their rotation into `.agents/handoff/`,
  `AGENTS.md` notes — commit on `main`. Branching a hand-off entry just delays the
  next agent from seeing it.
- **Commit or push only when the user asks.** Don't take a green test run as
  permission.
- Anything outward-facing — pushing a tag, cutting a release, changing repo
  settings or visibility — needs explicit confirmation each time. Approval for one
  doesn't carry to the next.
- **Say which model wrote it.** Every agent here posts through the owner's GitHub
  account, so unsigned prose on a public repo reads as the owner speaking —
  including its first-person claims about what was verified and its severity
  calls. Any issue body, PR body, or comment on either that an agent writes opens
  with a line naming the model and what it is, and closes with a sign-off:

  ```markdown
  **Claude (Anthropic) — response to the Codex review, at head `9d751ca`.**
  …
  — **Claude Opus 5 (Anthropic)**, via Claude Code
  ```

  It matters most where it is easiest to forget — a review exchange, where two
  models may be arguing and a reader is weighing whose reasoning to trust — and it
  applies to an issue drafted for the owner to file. **Not** the docs: `README.md`,
  `docs/*`, `AGENTS.md`, `.agents/*` and their kin carry no attribution line;
  they are reference material, not utterances in a conversation.
  (`.agents/lessons.md` → "The one about attribution".)

## Layout

```
docker-compose.yml      # the full stack: web (nginx) + api + migrate + db.
                        #   `up -d --build --wait` installs without publishing Postgres
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
HANDOFF.md              # session hand-off log — the five most recent entries only
.agents/                # process material for agents, NOT user docs (README inside)
  handoff/YYYY-MM.md    #   archived HANDOFF.md entries, verbatim; grep it, don't read it
  lessons.md            #   case histories behind the rules — append-only, stable headings
  testing-and-review.md #   procedure: suites, harness, CI, release gate, reviewer routing
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
docker compose up -d --build --wait   # http://127.0.0.1:8080 — see below re --build
docker compose logs migrate   # migrations; Exited (0) is success
docker compose down           # add -v ONLY to destroy the database
```

**`--build` is not optional, including on a first run.** `api` and `migrate` share
an `image:` tag so they build once and run identical bits, which also means a plain
`up` reuses a **stale** local image after you change the code — that is how a
container once ran migrations it predated. Separately, a fresh LXC on the official
Docker packages failed `up -d --wait` outright with no `--build`, and a minimal probe
on that same host does *not* reproduce it; the cause is not isolated. **Do not write
a mechanism for it into the docs until someone has reproduced it** — three plausible
explanations have been committed and retracted (`.agents/lessons.md` → "The
`--build` mystery"). State the observation, prescribe the flag, stop there.

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
7.1. **Every mutating service takes the write gate first** —
   `await acquire_write_gate(session)` from `services/write_gate.py`, before it
   *reads the state it will decide from*, not merely before it writes. Row locks
   only serialize writers touching the same row; they cannot protect a
   read-decide-write span whose decision depends on rows the plan never names,
   which is the shape `apply_import` has (and why it gates before `plan_import`,
   not after). The gate is collection-wide and transaction-scoped: it releases on
   commit or rollback, so there is nothing to release by hand. Reads never take
   it — import preview and every list/detail path stay unlocked and concurrent.
   A new mutating service that skips it reopens a class this repo paid seven
   review rounds for on #79; the failure modes are 500s and silent data loss, not
   conflicts (`.agents/lessons.md` → "Why the write gate exists").
7.2. **Export reads one snapshot** — `await begin_read_snapshot(session)` from
   `services/read_snapshot.py`, taken by `_load_all` before its first statement.
   `REPEATABLE READ READ ONLY`, fixed by the transaction's *first SQL statement*,
   so every table comes from one instant; under the default `READ COMMITTED` a
   write landing between two table reads produced an archive whose files
   contradicted each other (#48). A snapshot is not a lock, so row-level writers
   and exports never delay each other and reads still don't take the write gate;
   only a `replace_all` import's `TRUNCATE` (ACCESS EXCLUSIVE) queues behind an
   export, and the reverse. Because it covers the whole transaction and Postgres
   then refuses every write in it, put it only where the read *is* the unit of
   work. **Never on a helper a write path also calls** — `plan_import` is shared
   by preview and apply, and a snapshot there would break every import
   (`.agents/lessons.md` → "Why export reads one snapshot").
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
the instance in hand, enumerate the rest of the class. The cost of not doing this is
on the record: #3 → #12 → #6 → #19 was four branches, four reviews and two releases
for four instances of one money rule applied unevenly (`.agents/lessons.md` →
"Sweeping the class").

- **Name the rule** the defect violates — a numbered rule above, or a `§n`. If it
  violates none, it's a one-off: fix it and move on.
- **Enumerate the paths that rule governs** before writing the fix: service layer,
  REST, MCP, CSV import, CSV export, the browser, and the schema itself. They diverge
  independently — a corrected service function does not mean the importer agrees.
  `services/portability/spec.py`, `frontend/src/lib/format.ts` and the models are
  where the last four hid. This repo has three writers plus an importer; a sweep
  that answers for one of them is not a sweep. It applies to prose too — grep the
  docs for the distinctive fragment, not the comfortable full phrase.
- **File the siblings even if you won't fix them now.** An unfiled sibling is
  indistinguishable from a bug nobody has noticed. Milestone or don't, but file.
- **Fix the class in one branch** where the instances share a root cause, and say so
  in the PR. Where they genuinely don't — a schema migration, an open design question
  — separate branches are right, but the issues should already exist.
- **Cross-layer behaviour gets a shared fixture, not one test suite per side.**
  `frontend/src/lib/__fixtures__/money-cases.json` is read by both `format.test.ts`
  and `backend/tests/test_currency.py`. Two hand-maintained lists drift, and a
  drifted pair reads green on both sides with a wrong number in the database.

## Writing the test: sweep the values, not just the paths

The sweep above finds code paths that drifted apart. It does nothing about a test
that walks the right path carrying the wrong values — and that is the more
expensive mistake on this repo's record: several regression suites were written for
a known defect, reviewed, **run against the unfixed code, and still missed
something**, each in a different way. The cases are in `.agents/lessons.md` ("The
value axis", "The state axis", "Green for the wrong reason"); the procedure and
checklist are in `.agents/testing-and-review.md`. The rules they produced:

- **Enumerate what the field can hold** before writing assertions: null, empty,
  whitespace, the derived or default value, and something that genuinely differs.
  Drive at least the null and the default.
- **Values are one axis; the state the row is in is another**, and it decides
  whether the field is even present to be wrong (`changes` is empty on a create;
  `matched_id` is null until something matches; a `replace_all` has a deletion set
  and a merge has none). Where a fix touches a structure whose shape is decided by
  a classification — an action, a mode, a status — drive at least two of them, and
  prefer the one that makes the structure non-empty.
- **When one matrix in a file varies a state axis, every matrix over the same field
  owes you a reason why it doesn't.** The neighbour is the cheapest place to notice.
- **If the rule is about rows diverging, seed more than one row.** If it is about
  timing, pin the timing rather than hoping.
- **A red test proves *something* refused the input, not that the rule under test
  did.** Assert the layer that spoke and the error class; assert the named control,
  not containment; never derive the test's subject from the code under test (an
  empty parametrize is a skip, not a failure).
- **Running the test against the unfixed code is necessary and not sufficient.** It
  proves the test detects the case you thought of, nothing about the case you
  didn't. Then mutate the fix **one place at a time** — the axis that keeps going
  unvaried is *which of several equivalent places the fix actually reached*.
- **A test that asserts a status has to be able to see one.** The default `client`
  fixture re-raises unhandled exceptions into the test; use `http_client`, which
  returns the 500 as a response, wherever the point is which status a bad input
  earns (rule 6).

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
