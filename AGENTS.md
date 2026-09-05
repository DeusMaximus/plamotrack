# AGENTS.md — plamotrack

Guidance for AI coding agents (Claude Code, Codex, …) and humans working in this repo.

**plamotrack** is a self-hosted, open-source Gunpla/plamo collection & build tracker:
kits move through a pipeline (pre_ordered → ordered → in_transit → backlog →
building → complete; backlog = in hand, not started) on a drag-and-drop Kanban
board with Build and Orders views, alongside quantity-tracked tools, consumables,
third-party upgrades, and display gear (stands, bases, diorama scenery). Ships as a
Docker Compose stack: FastAPI REST API + embedded MCP server (same process, shared service
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
- Exception: session bookkeeping and documentation commit on `main` when they are
  small — `HANDOFF.md` entries and their rotation into `.agents/handoff/`,
  `AGENTS.md` notes, a new `.agents/` template or lesson, a pointer. Branching a
  hand-off entry just delays the next agent from seeing it. The test is size and
  moving parts, not file type: #105 — the rewrite of `AGENTS.md` plus the creation
  of `.agents/` — went through a PR because it was a lot of moving parts, and a
  docs change of that shape should again (owner's call, 2026-08-19).
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
    models/             # SQLAlchemy 2.0 async models — 10 tables
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
  nginx/                # THE ingress: default.conf.template (rendered by envsubst at
                        #   container start — default-deny 421 server, the /api/ alias
                        #   rejections, security headers) plus the .envsh that assembles
                        #   server_name from PUBLIC_BASE_URL, WEB_BIND and ALLOWED_HOSTS.
                        #   Read the comments before touching the /mcp or resolver
                        #   lines — both encode bugs found by testing (§8)
  src/
    api/                # hand-typed API client + types mirroring backend schemas
    i18n/               # language manifest + en-AU catalogue (§6.1) — manifest.json's
                        #   enabled tags must equal SUPPORTED_INTERFACE_LANGUAGES
                        #   (backend/tests/test_settings.py holds the pair together);
                        #   extraction keeps en-AU strings byte-identical (e2e proves it)
    components/         # Layout, Modal, ui primitives, CatalogItemPicker (§3.9 select-or-create)
    pages/              # BoardPage (Kanban), KitsPage, OrdersPage, InventoryPage,
                        #   RetailersPage, and settings/ (SettingsPage + sections,
                        #   including Data management at /settings/data)
  e2e/                  # Playwright happy-path (runs against the dev stack, self-cleaning)
docs/design.md          # product intent + architectural decision record (§n targets)
docs/import-export.md   # user-facing CSV format + matching reference
docs/operations.md      # backup / restore / upgrade for the container stack
docs/translating.md     # contributor how-to for proposing/reviewing a language (#22)
HANDOFF.md              # session hand-off log — the five most recent entries only
.agents/                # process material for agents, NOT user docs (README inside)
  handoff/YYYY-MM.md    #   archived HANDOFF.md entries, verbatim; grep it, don't read it
  lessons.md            #   case histories behind the rules — append-only, stable headings
  testing-and-review.md #   procedure: suites, harness, CI, release gate, reviewer routing
  review-brief.md       #   fill-in template for briefing a reviewer; the PR-body shape it assumes
```

## Dev environment & commands

Postgres comes from Docker (OrbStack on the primary dev Mac, auto-starts). For
development, run **only** the db service and the app from source — the container
stack has no hot reload, and both want port 5432:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db --wait
```

To exercise the packaged stack instead (before touching Dockerfiles, `frontend/nginx/`,
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
explanations have already been committed and retracted
(`.agents/lessons.md` → "The `--build` mystery"). State the observation, prescribe
the flag, stop there.

Backend is uv-managed — run everything from `backend/`:

```bash
uv sync                      # install deps
uv run pytest                # tests: auto-creates plamotrack_test DB, runs alembic
                             # downgrade+upgrade, truncates tables between tests
uv run ruff check --fix . && uv run ruff format .   # lint+format — run before committing
uv run alembic upgrade head  # apply migrations to the dev DB
uv run uvicorn app.main:app --no-proxy-headers  # REST on :8000, MCP at /mcp/ (the flag: rule 12)
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
   - **There are three writers, not two.** The CSV importer reaches the same tables
     by direct `setattr`, sharing no service function with the other two, so every
     guard they hold is one it has to be given separately (#44). What the two sides
     share is the **predicates** — `kit_progressed`, `PROGRESSED_STATUSES` and
     `IMMUTABLE_LINE_COLUMNS` in `services/orders.py`, read by
     `services/portability/invariants.py` — never the mutation path, which rule 10
     forbids. A guard added to an order or order-line write owes an answer from
     `invariants.py` as well, and the shared matrix in
     `tests/test_order_invariants.py` is what makes a one-sided answer fail.
2. **Order line dispatch (§3.9, amended):** `item_type=kit` lines fan out into N
   `kits` rows (with `order_item_id` provenance) at entry. Catalog lines —
   tool/consumable/upgrade/display — increment `quantity_on_hand` **only when the
   order is received** (`received_at`); quantity means *physically on hand*, not on
   order. Receiving also advances
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
2.1. **`received_at is not None` means "stock was applied", everywhere** — it is the
   proxy four stock mutators read (`create_order`, `update_order`, `receive_order`,
   `delete_order`), so anything that can set the column owes that invariant. The CSV
   importer could set it freely and produced a state none of the four could read: the
   genuine receive 409'd as "already received", a delete became impossible, an edit
   moved stock by the wrong delta, and *clearing* the column re-armed the increment
   and double-counted a delivery (#44). The answer is to refuse the transition, not to
   represent it — `invariants.py` blocks an import moving `received_at` into or out of
   null on an order with catalog lines, and (#87) blocks a *new* catalog line joining
   an order whose stored `received_at` is already set, which is the same unaccounted
   state reached from the line's side. Do not add a `stock_applied` column instead:
   the backfill cannot be right on a live instance, and in the CSV (rule 9) it becomes
   a sheet asserting that stock was applied, which is this defect on a worse field.
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
12. **Ingress identity (M6-1, §5.5–§5.6):** the instance's own names and origin come
    from `PUBLIC_BASE_URL`, `ALLOWED_HOSTS`, `ALLOWED_ORIGINS` and `WEB_BIND` — never
    from `Host`, `Origin` or `X-Forwarded-*`. `app/ingress.py` derives one
    `IngressPolicy` that the REST guard and FastMCP's guard (strict mode, same lists)
    both read: a Host outside the list is 421, an unsafe request whose Origin fails
    the three-way rule (listed, loopback-to-loopback, or equal to the request's own
    origin) is 403, each with the envelope naming the setting. `scope["client"]` is
    the raw socket peer and stays that way — uvicorn runs with `--no-proxy-headers`,
    and the forwarded address (believed from `TRUSTED_PROXIES` only) goes to
    `request.state.client_address` instead — because the raw peer is what `/readyz`'s
    `internal` check reads. No router-generated redirects (`redirect_slashes=False`
    on both routers): a non-canonical spelling is 404, never 3xx. nginx duplicates
    the cheap denies and owns **one spelling per family**: every root namespace of
    the API process whose canonical spelling is not under `/api/` (`/mcp`,
    `/.well-known`, `/openapi.json`, `/readyz`) is 404 under `/api/` before the
    generic location, and `backend/ingress_matrix.py` proves it against the
    packaged stack (CI Integration). That list is **generated** from the route
    policy registry (`app/auth/registry.py`, `API_ALIAS_REJECTIONS`) into the
    template by `scripts/render_ingress.py` (M6-2): a new root namespace owes a
    declaration there or fails `tests/test_ingress_generation.py`. The app is
    authoritative and nginx never grants: development runs without it.
13. **Authorization is one dependency over a declared registry (M6-2, §5.5):** every
    request resolves to one `Principal` (`anon`, `owner`, `pat`, `mcp`, `internal`;
    scopes `collection:read`/`collection:write`/`instance:admin`, `write` implying
    `read`, `admin` held by the owner alone), and a single app-level default-deny
    dependency (`app/auth/dependency.py`) allows or denies from the **route policy
    registry** (`app/auth/registry.py`) — the rule-9 shape applied to routes: declared
    once, read by the dependency, the ingress rejection list and the T1/T2 matrix, and
    matched on the **resolved endpoint**, never the URL string. The enumeration test
    (`tests/test_route_policy.py`) fails on any effective route or MCP tool the registry
    does not declare, which is what makes a new router or an M8 `/public/*` handler a
    deliberate act. Auth configuration is **env-only** — there is no `AUTH_MODE=disabled`
    in the shipped image and no settings row that turns authentication off (the Settings
    page cannot grow a "disable auth" toggle); the pytest principal-injection seam
    (`app/auth/resolver.py`) is a test-only `app.state` attribute the shipped app never
    sets. Only an **absent** credential is `anon`; a credential that is *presented and
    fails* — expired, revoked, malformed, wrong audience — is **401**, never a silent
    downgrade. Auth tables are **never** portable (rule 9): they are absent from
    `services/portability/spec.py`, so an export cannot become a credential dump. An
    import's required privilege is read off its **plan's mutations** (`plan_requires_admin`)
    — an `instance_settings` UPDATE or a `replace_all` needs `instance:admin` in any mode;
    an unchanged or skipped settings sheet, or a collection-only plan, stays
    `collection:write`. **Activation landed with M6-3 (#188):** the shipped `app` is
    `create_app(authorization=True)` — default-deny — now that the browser session
    exists to claim the owner and sign in; `create_app()` (the default off) is what the
    ingress and packaged-stack harnesses build, and the test suite drives the shipped
    app with an injected owner (`tests/conftest.py`). The staged sequencing ("foundation
    M6-2, activate once a credential works", owner's call 2026-09-03) is complete for the
    browser, and **the bearer landed with M6-4 (#189):** a personal access token
    (`ptk_<id>_<secret>`, digest stored, `compare_digest` against a dummy for an unknown
    id) in `Authorization` only — never a query parameter — resolved by **one** helper,
    `services/tokens.resolve_bearer`, from both the REST resolver and the FastMCP
    `TokenVerifier` on the `/mcp` mount, so a token is valid on both surfaces or on
    neither; a presented-and-failed bearer is 401 `auth.bearer_invalid` on every route,
    the anonymous families included, and a bearer on a family-3 action is 403. Per-tool
    scope is one FastMCP middleware on `tools/call` (`app/auth/mcp_auth.py`) reading
    `MCP_TOOL_SCOPES`, refusing before arguments are parsed; the in-memory test client
    carries no header, so it reads an injected principal off the server object only
    when no HTTP request is in flight (`tests/conftest.py` sets it). Token management
    is family 6 (`/auth/tokens`): the owner's session alone, so a token cannot mint a
    token. The matrix
    **Browser OIDC landed with M6-6 (#191):** `AUTH_MODE=oidc` replaces the password
    with a sign-in at one configured OpenID Connect provider; the owner is bound to the
    provider's `(issuer, subject)` at the first login that presents the setup token,
    every other identity is refused with an audit row, and `recovery rebind-oidc` is
    the host-side way back. The modes are mutually exclusive and env-only; each
    family-3 action declares its mode in the registry and answers 404 in the other.
    The id_token is verified with joserfc for its signature and by **one explicit
    claim validator** for its contract (`validate_id_token_claims`: each claim's type
    before its value, `aud` exactly this client, `azp` when present, `iat` required,
    `nonce` a string) — a generic JWT registry read a list as containing the expected
    value and opened a session for a token naming another client (Codex #209 round
    1). The login transaction is a database row consumed before any network call
    (`services/oidc.py`). **A browser session is authority only in the mode that
    minted it:** `session.auth_mode` is stamped at mint, the resolver refuses it under
    the other mode, and the API's start in a new mode revokes the old mode's sessions
    with an `auth.mode_changed` audit row, so a switch signs everyone out durably and
    switching back resurrects nothing (same round). The matrix
    (`tests/test_authorization.py`) drives the real route graph through the dependency
    with injected principals; `tests/test_auth_local.py` drives the shipped app through
    the real session cookie; `tests/test_auth_tokens.py` drives it through real bearers
    and the MCP transport by hand.
    The registry's **response profile is enforced, not defaulted, adjacent to the
    router that selects the route**: for the app's own routes the response
    middleware — added *first*, so it is the innermost user middleware, with only
    the framework's own pass-through layers between it and FastAPI's router —
    reads the endpoint the router recorded in the very dict it holds and stamps the
    final response, replacing whatever `Cache-Control` a handler or library set
    (`no-transform` alone survives beside `no-store`); every route under the `/mcp`
    mount, whose child may stack middleware of its own, carries a `RouteBinding`
    that stamps on the route's own send and **enforces the declared verbs** in front
    of the implementation — the transport's metadata declares none, so the
    registry's set is its dispatch boundary. A scope-copying middleware, which the
    ASGI contract permits, can lose neither. And `build_route_index` refuses a
    route graph a declaration cannot describe — two routes on one dispatch entry,
    one endpoint on two routes, an undeclared route under a mount, a route type the
    walk does not know.
    **Family 13 is closed by the pre-routing gate (M6-3b, #204):** one middleware
    directly above the response-profile layer (`app/auth/prerouting.py`) resolves the
    principal **once** per request the REST app owns, before Starlette routes and
    FastAPI parses, stashes it for the dependency to reuse, and refuses `anon` wherever
    the router would have answered 404, 405 or the dependency's 401 — an unrouted path,
    a wrong verb (no `Allow`), a malformed body — reading what the request would reach
    from the registry's dispatch walk, never the URL. It never grants; the dependency
    stays the authority on every matched route. The anonymous families keep their own
    405/422, the `/mcp` mount is the child's, family 8's `/.well-known/` namespace
    (`PROTOCOL_NAMESPACES`, one declaration with the ingress rejection) is the
    router's 404 for everyone, and a new mutating middleware or a change
    to the resolver owes the once-per-request test (`tests/test_auth_unrouted.py`).
    **MCP OAuth landed with M6-7 (#192):** in OIDC mode the `/mcp` mount is built with
    `PlamotrackOAuthProxy` (`app/auth/mcp_oauth.py`) — FastMCP's `OAuthProxy` in front
    of the **same provider and client** as the browser login, every plamotrack rule on a
    documented extension point: the upstream identity must be the bound owner, checked
    **at issuance** (`exchange_authorization_code` — a stranger gets `invalid_grant`, an
    `auth.mcp_identity_refused` row and nothing minted — the id_token through the same
    `validate_id_token_claims`, with `nonce=None`) and carried as **grant state** — in
    every token the proxy issues, compared with the owner row on every request, and on
    the **grant record** itself, whose binding is what every refresh is checked
    against: the record gate (`GrantRecords`) admits a refresh's upstream set, on the
    client's exchange or the transparent refresh behind a request, only with an
    identity that binding names — the id_token already verified, or a new one verified
    in full naming the **record's** `(iss, sub)`, not merely the owner now (round 3,
    f10: the two differ for the length of a rebind) — else the grant ends
    (`ended_by=upstream_refresh`);
    one validly omitted carries the binding forward; **one transition per grant** —
    issuance, both refreshes and revocation serialize on a Postgres advisory lock per
    grant, the write gate's shape, so a second redemption is `invalid_grant` and a
    revocation and a refresh never interleave; **revocation is the grant's** — either
    half presented is **located, not authorized** (`RevocationLookup`: the proxy's own
    signature and the JTI mapping, the provider asked nothing, no owner row read — the
    SDK's handler otherwise finds a token through the bearer path, and a provider whose
    keys could not be fetched turned that into a silent 200 over a live grant; round 3,
    f9), ends the whole grant locally first, then the provider's refresh
    token best effort (`auth.mcp_grant_revoked`); what bounds a grant is the
    provider's own token, refreshed transparently while it can be (Codex #212 rounds
    1–2, f1–f3 and f6–f7); every issued token maps to a **fixed** `collection:read` +
    `collection:write` by its `kind` (the OAuth scope vocabulary is the provider's,
    `openid`), never `instance:admin`; the mount requires no OAuth scope, so a personal
    access token stays valid on `/mcp/` in that mode; the redirect-URI binding is per
    client kind — a DCR client to its registration (`BoundDCRClient`: exact, loopback
    port free, *then* the operator allowlist, which FastMCP alone would check instead),
    the synthesised upstream-id client refused, a CIMD client (Claude web, ChatGPT web)
    by its document — and the allowlist, when set, applies to every kind. **One
    downstream client contract** (round 4, f11–f13): every dynamically registered client
    is **public** (`none` + PKCE) whatever it asked for and the registration response says
    so (`register_client` makes the SDK's object truthful before it is stored *or*
    returned — the SDK returns that same object); a CIMD client authenticates as its
    document says, `none` or `private_key_jwt`, on `/token` **and** `/revoke`
    (`_revocation_authenticator`, the assertion bound to the revocation URL); the wire
    forms are the RFCs' (`GrantRevocation` over `RevocationForm`: `client_id` in the
    form, no secret from a public client, `401 invalid_client` on a failed client
    authentication on either endpoint); **discovery says the same** — the two
    authorization-server documents are built here (`discovery_metadata`,
    `CLIENT_AUTH_METHODS`, `CLIENT_ASSERTION_ALGORITHMS`) and publish exactly those two
    methods for both endpoints and `RS256`, where the SDK's metadata advertised its
    shared-secret methods and no algorithm (round 5, f14); every protocol field's value
    space is the protocol's, unrecognised values included — an unknown
    `token_type_hint` is ignored, never refused (f15); and **the boundary is owned field
    by field** (round 6, f16–f19): `ClientAssertionAuthenticator` judges an assertion's
    claims (`nbf` included, dates never booleans, `jti` a string) *before* the SDK's
    validator spends its `jti`; `register_client` canonicalises the admitted metadata and
    stores that same object (a null redirect list refused; `jwks` with `jwks_uri`
    refused, RFC 7591 §2 — round 7, f26); `ProtocolRequest`, an ASGI
    guard on `/authorize`, `/token` and `/revoke`, refuses a repeated parameter, drops
    empty ones, names `unsupported_grant_type`, and reads an omitted
    `code_challenge_method` as `plain` for the SDK to refuse; `UnregisteredClientGuidance`
    points at the root discovery document. **Admission, decoding, cardinality and the
    SDK hand-off are one decision** (round 7, f20–f24): the guard reads the media type
    as HTTP does (case-insensitive, parameters aside) and refuses any body that is not
    form-encoded before the SDK parses it — a case-sensitive prefix had let mixed-case
    and multipart bodies around it; `resource` is the one parameter RFC 8707 lets a
    client repeat, so it is a **set** — identical values collapse, the proxy's own
    `accepts_resource` judges every member, a set naming another target is
    `invalid_target` (at `/authorize` the SDK's redirect, which the proxy's `authorize`
    renders because the SDK's vocabulary lacks the code; at `/token` directly, where the
    SDK judges nothing), and the naïve exemption that hands the SDK the last value is
    the wrong repair; a NumericDate has a range, ±2^53, judged before any float
    conversion; and `ClientAssertionAuthenticator` refuses a second mechanism beside an
    assertion (RFC 7521 §4.2.1, `invalid_client`), and an assertion from a client not
    registered for `private_key_jwt` — the SDK's `none` branch had accepted it unread —
    with a 401 to a client that used the `Authorization` header carrying the
    `WWW-Authenticate` challenge RFC 6749 §5.2 requires. **And a request is admitted
    once** (round 8, f27–f30): a decision at the seam is owned, not prechecked — a
    refuse-only check in front of a parser, comparison or lookup that decides again can
    disagree with what executes. So the resource comparison is this server's own, on
    the whole URI (`resource_identity`: a fragment or a missing scheme is malformed, the
    path keeps its `;parameters`, a trailing slash and the query are the only
    equivalences, scheme and authority compare as written) and `authorize` applies it
    behind the guard's hand-off; each endpoint declares the parameters it recognises
    (`RECOGNISED_PARAMETERS`) and unknown ones are discarded before their multiplicity
    is judged (RFC 6749 §3.1, erratum 5708); and `ClientAssertionAuthenticator` owns
    client authentication end to end — every `Authorization` occurrence inventoried
    first and any one refused as a failed HTTP attempt, the client resolved **once**
    with the method, the verifying document and the authenticated client all that
    snapshot, FastMCP's cryptographic validator behind it. **Parsing is not
    validation** (round 9, f31–f32): the resource value is judged against RFC 3986's
    `absolute-URI` grammar before `urlsplit` sees it (a parser strips or admits what
    the grammar refuses, and a query the comparison ignores was never checked), and the
    inline key set has a contract in front of FastMCP's extraction (`keys` an array,
    unusable entries ignored per RFC 7517 §5.1, none usable a refusal) where a
    malformed set had been a 500. **The selected key keeps its authorization** (round
    10, f33): FastMCP verified with a PEM of the JWK it selected, so the key's `alg`, `use`
    and `key_ops` never reached joserfc; `RestrictedKeyAssertionValidator` and
    `RestrictedKeyVerifier` hand its verifier the selected JWK itself — the record the
    `kid` named, never the first record with its material (round 11, f34) — on the inline
    and the fetched path, cache included, and the same decode enforces the restrictions —
    one cryptographic validator, the SDK's *remote* selection rule on both paths; the
    inline set is filtered by the remote path's own usability predicate before the
    single-key fallback counts it (f35); and a named `kid` that matches nothing is a
    refusal on both paths, the fallback only for a header naming none — the SDK has two
    rules, and its inline extraction, which round 11 wrote out, fell back to the only key
    whenever no record matched (round 12, f36). All of it tested from raw
    requests in `tests/test_mcp_oauth_clients.py` — never through the SDK's models or
    a helper that pads the form, and with the test's own dates computed when it runs,
    not at import (f23). The upstream
    endpoints are **properties over `OidcProvider.cached_metadata`** — no reader in
    FastMCP can hold a stale copy — and every entry point that reaches the provider
    fetches first (authorize, consent, the callback, the exchanges), so a provider down
    at start never fails the start and a restart mid-flow completes on the fresh process
    (round 1, f5). A protocol route's failure is the `RouteBinding`'s stamped 500, a
    non-JSON registration body RFC 7591's 400, and nginx's `limit_req` 429 carries the
    envelope and `no-store` (round 1, f4). State lives in `mcp_oauth_state`, a
    table Alembic owns (never portable), Fernet-encrypted under a key derived from
    `MCP_OAUTH_SIGNING_KEY`, which OIDC mode requires — as it now requires an **https or
    loopback** `PUBLIC_BASE_URL`, the MCP OAuth issuer being `<PUBLIC_BASE_URL>/mcp` (RFC
    8414, enforced by the SDK). Family 8 is declared in the registry by **path**
    (`DISCOVERY_ROUTES`, `MCP_OAUTH_ROUTES`, each with a `ProtocolRole`), because the
    same nine paths exist in both modes — FastMCP's handlers in OIDC mode, a 404 of
    their own naming the mode in local mode — with the child routes' method metadata
    cleared so the `RouteBinding` is their verb boundary too; the pre-routing gate passes
    the whole `/.well-known/` namespace through unresolved, and the index build refuses
    any non-protocol route under it. A change to any of this owes
    `tests/test_mcp_oauth.py` (the fake provider is `tests/oidc_fake.py`) and, for the
    ingress half, `ingress_matrix.py --mode oidc` against a packaged stack with a provider.

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
6.5. UI redesign: move off the stock Tailwind look — direction still being
     explored, deliberately undecided; before M7/M8 so the gallery and showcase
     are built in the new look once (#122 rides here)
7. Photo upload + gallery ← decide storage backend default first (§9.2)
8. Public read-only routes + showcase page ← only after admin/MCP paths are protected
9. Open-source operations: contribution guide, release automation, support matrix,
   deployment-doc polish

The repo goes public at 4.5 as an alpha (§10, revised) rather than waiting for
milestones 1–6. Consequence for anything written from here on: **the audience is
strangers.** No internal references, no assumed context, and disclose what isn't
built rather than describing planned endpoints as if they exist. Collection and
administrative access is authenticated — the owner login for the browser, personal
access tokens for REST scripts and MCP clients (M6-3/M6-4); only liveness and the
auth bootstrap answer anonymously — but there is no tested TLS path yet, so an alpha
instance belongs on a trusted network.
