# Session hand-off log

Every agent session that changes this repo appends an entry **at the top** (newest
first) before finishing. The next session may be a different agent/model with no
shared context — and possibly a small context window — so this file stays short:

- **It holds the five most recent entries.** After appending yours, if there are
  more than five, move the oldest to the top of `.agents/handoff/YYYY-MM.md` (the
  month in the entry's date), verbatim, in the same commit. Never edit or
  summarise an entry on the way out.
- **Entries are ≤ ~60 lines and carry state:** what was done, what was decided,
  what is half-finished or broken, what comes next. A *lesson* — the trap a test
  fell into, what a review round found and why it was missed — goes under its own
  heading in `.agents/lessons.md`; the entry links it in one line. *Procedure*
  that changed — how to run a check, which reviewer for what — is edited into
  `.agents/testing-and-review.md`, not narrated here.
- **The newest entry is self-sufficient about live state.** If something from an
  older entry is still true and still matters — an in-flight decision, known
  breakage, a sequencing constraint — restate it or link it. Older entries in this
  file are history and rotation will drop them; nothing live may depend on one.

Older entries live in `.agents/handoff/YYYY-MM.md`, verbatim, newest first. Do not
read an archive file whole. To find something:

```bash
grep -n '^## ' .agents/handoff/*.md      # every archived title, with its date
grep -rn '#123' .agents/handoff/         # every mention of an issue or PR number
```

then read the entry that matched.

Template:

```markdown
## YYYY-MM-DD — <agent> — <short title>
- **Done:**
- **Decisions:**
- **State:** (tests? migrations? anything half-finished?)
- **Next:**
```

---

## 2026-08-28 — Claude Code (Fable 5) — #24 CLOSED: the Settings page (PR #168, one Codex round)

- **Done:** **#24 closed — PR #168 squash-merged as `db48440`** on the
  owner's call, branch deleted (final head `7eb6567`,
  539 insertions, frontend-only, **no migrations**): `/settings` with nested
  section routes. General = the reference-currency form (hydration gated on
  `settingsQuery`; on save `setQueryData` for settings + **invalidate
  `metaQuery`** — /meta carries the same reference_currency at staleTime
  Infinity and the order/inventory forms default from that copy). Language &
  region = read-only display; **#27 owns the controls**, the page says so.
  Data management = DataPage git-renamed to `pages/settings/DataSection.tsx`
  (90 % similar; plan_hash/confirm/global invalidateQueries byte-identical).
  About = version from `metaQuery`. `/data` → `/settings/data`. `Card` lifted
  into ui.tsx (h2→h3, reason at the definition), `ErrorBanner` now
  `role="alert"`, sidebar swaps 💾 Data → ⚙️ Settings, catalogue gains a
  `settings` group (`nav.data`/`data.title` removed as unused). All six README
  screenshots re-shot (the sidebar changed in every one); docs swept
  (README, operations, import-export, design §6 + §6.1).
- **Decisions:** sections are **routes**, not InventoryPage-style tab state —
  the redirect criterion needs an addressable Data-management section. The new
  settings e2e is its own Playwright **project** with `dependencies: ["app"]`:
  it flips the singleton that order-snapshot/order-lossless beforeAll-read, and
  local parallel workers would flake *them*; cost disclosed (a red in app skips
  settings). Language & region deliberately not editable here (#27's first
  acceptance criterion). This entry was rebuilt once: the parallel #166
  session's hand-off (bundle warning, merged) landed on `main` mid-session and
  had already rotated the entry my first draft rotated — the #144 shape, live.
- **State:** `main` at `db48440` (+ this entry), CI green at every head
  including the post-review `7eb6567`. **Codex round 1 (GPT 5.6 Sol): GO + 2 P3s**, both
  reproduced and answered at `7eb6567` — P3-1 dead Data-page directions
  (fixed, plus one sibling the re-sweep found: the #126 downgrade-guard
  message; `mutation_test.py -k mig-5` re-measured killed, anchor untouched);
  P3-2 evidence-record overcounts (PR body amended in place: 6 tests / five
  green / :138 — this entry carried the same two numbers and is corrected in
  this commit). Codex's subscription was upped this session — capacity no
  longer the constraint; its model is GPT 5.6 Sol (procedure + brief template
  refreshed on main, `639238a`). Suites at the head: backend **1187**, vitest **212**, e2e
  from-empty **36 passed + 1 skipped** (6 new settings tests), tables zero
  after, currency restored. Two measured e2e negative controls in the PR body
  (meta-invalidation removed → red at settings.spec.ts:138; role="status"
  removed → red at the status assert). No mutant queues (frontend-only). No
  dev servers left running; stale worktrees `/private/tmp/plamotrack-pr100`
  and `-pr108-main` persist (pre-date this).
- **Notable:** **#167 filed** — display-items spec's `getByLabel('Category')`
  collides with Inventory's category filter on any database holding a
  categorised display item (the dev DB did); invisible from empty, so CI and
  the from-empty run can never see it. preorder-toggle flaked once locally
  (#17 contention class), clean on re-run and in the counted run.
- **Next:** the M5.1 rest, all unblocked:
  #25/#26 (structured diagnostics), #27 (language/region controls — the
  read-only section and `/meta`'s missing language advertising are its), #114
  (naive CSV dates). #162 (e2e keyboard-select race) remains
  reproduced-on-`main`, unfixed. LXC: **back up before pulling** (real
  collection, several releases behind; 0.2.8's settings migration still
  pending there).


## 2026-08-28 — Claude Code (Fable 5) — bundle-size warning assessed: no splitting; PR #166 merged

- **Done:** the 503 kB chunk warning (flagged informational in the previous
  entry) assessed and dispositioned. Measured at `abb9d7c`: one 506.76 kB
  chunk, 154.90 kB gzip. Sourcemap attribution: react-dom 175 kB (35%), app
  code ~102 kB (14 kB of it the en-AU catalogue), the #22 i18n stack ~57 kB,
  dnd-kit 41 kB, react-router 36 kB, react-hook-form 35 kB, TanStack Query
  35 kB — nothing accidental; the deliberate #22 addition is what crossed
  Vite's 500 kB default. **PR #166 squash-merged as `58c174f`** on the
  owner's call: `build.chunkSizeWarningLimit: 600` with the reasoning and the
  revisit path as a config comment. Built chunk byte-identical; build + lint
  green, CI green (all three checks). Review skipped per the #40 criterion
  (small, local; worst failure is a suppressed warning); owner concurred by
  merging.
- **Decisions:** severity by real exposure — a single-owner LAN instance
  fetches 155 kB gzip once per release, cached thereafter; no user-observable
  cost. React.lazy declined (index redirects to /board, the dnd-kit consumer,
  so the heaviest split-able dep loads on first paint anyway; Suspense adds
  e2e async surface of the #162 class). manualChunks declined (cross-release
  caching for one repeat visitor; a Vite 8/Rolldown config dialect to carry).
  600 keeps the tripwire: ~90 kB headroom ≈ six statically imported
  catalogues (~14 kB each, `src/i18n/registry.ts`) — if shipped languages
  re-trip it, per-language dynamic import (natural home #27), not another
  raise. No issue filed — not a defect, no numbered rule violated.
- **State:** `main` at `58c174f` (+ this entry), CI green; no in-flight
  branches. Config-only merge — no migrations, no mutant queues. Backend
  1187, vitest 212, e2e 30 (+1 skipped) — untouched. Stale worktrees
  `/private/tmp/plamotrack-pr100` and `-pr108-main` persist (pre-date this).
- **Next:** M5.1 as before, all unblocked:
  #24 (Settings page), #25/#26 (structured diagnostics), #27 (language/region
  UI; `/meta` still doesn't advertise supported languages), #114 (naive CSV
  dates). #162 (e2e keyboard-select race) remains reproduced-on-`main`,
  unfixed. Cursor carried three rounds and Codex two on #22 — check both
  meters before the next buy. LXC: **back up before pulling** (real
  collection; 0.2.8's settings migration still pending there).

## 2026-08-28 — Claude Code (Fable 5) — #22 CLOSED: the i18n foundation, four PRs (#161/#163/#164/#165)

- **Done:** **#22 closed** — the en-AU catalogue foundation, four sequential
  PRs, each squash-merged on the owner's call after review. **#161**
  (`cc91045`, Codex NO-GO→GO; P2: the runtime and the tests kept separate
  catalogue lists, so an enabled language passed every gate while the browser
  never loaded it — `src/i18n/registry.ts` is now the single import map both
  derive from, with a loaded-bundle test; P3: blank values refused): i18next +
  react-i18next, sync init pinned `en-AU` (#27 wires it to settings),
  manifest (tag/nativeName/direction/enabled), `catalogue.test.ts` (validators
  proven on inline bad fixtures first; plural shapes per language's own CLDR
  categories; 100% coverage bar for enabled languages), backend parity test
  pinning `SUPPORTED_INTERFACE_LANGUAGES` == enabled manifest tags,
  `npm run i18n:report` + CI summary step, `docs/translating.md`. **#163**
  (`fb569f9`, Cursor GO + 2 P3s: CountPills borrowed the totals plural group
  and reworded the one divergent action — own `importPill.*` group + a
  divergence pin; the unified `importTable.*` headings disclosed):
  Retailers/Data/ImportPreview/CatalogItemPicker — first plurals + `<Trans>`,
  the TABLE_LABELS/TABLE_EXPORTS by-value duplication ended. **#164**
  (`4f18a04`, Cursor clean GO): Kits/Inventory — `dateWithElapsed` over
  `common.elapsed.*`; the U+00A0 find (below). **#165** (`a85325f`, Cursor
  clean GO + two corrections to my brief, owned on the thread): Orders —
  `itemType.*.title` select nouns, receivedCell's one-byte NBSP normalization
  (disclosed at #164, endorsed), catalogue machine-formatted (json indent=2).
- **Decisions:** byte-identical extraction, proven by a from-empty e2e run per
  PR — wording fixes deliberately out of scope (`data.result` `_one` forms
  still read "1 kits …", stated in #163). Dynamic keys are the vitest
  matrix's; flat static keys are `tsc -b`'s (measured on #165: deleted key →
  vitest green, tsc red naming the call site). No jsdom — i18next core only.
  Review bought on every PR including the "mechanical" ones, which paid: real
  P3s in two of three.
- **Notable:** the NBSP transcription trap and the unverified spec-coverage
  claims are in `.agents/lessons.md` (→ "The value axis", "Review").
  **#162 filed**: dialog-keyboard's keyboard-select spec races the catalog
  search under load (its readiness wait is satisfied by the Create-new
  button) — reproduced on `main`, remedy sketched, deliberately not fixed on
  the series. This file repaired: the 27-08 entry had been amended into the
  template fence; moved out verbatim, skeleton restored.
- **State:** `main` at `a85325f` (+ this entry), CI green at every merged
  head. Backend **1187**, vitest **212**, e2e 30 (+1 skipped screenshots),
  from-empty verified repeatedly, tables zero after. Catalogue **350 keys @
  100%**. Bundle 503 kB — past Vite's 500 kB chunk warning, informational,
  unfiled. **No migrations in the series.** No mutant queues; `stg-`
  re-measured 23/23 at #161. No dev servers running; stale worktrees
  `/private/tmp/plamotrack-pr100` and `-pr108-main` persist (pre-date this).
- **Next:** the rest of **M5.1**, all unblocked: **#24** (Settings page —
  its copy now has a catalogue to land in), #25/#26 (structured diagnostics —
  the runtime was chosen for `t(code, {defaultValue})`), #27 (language/region
  UI; `/meta` still doesn't advertise supported languages — that gap is
  #27's), #114 (naive CSV dates). Cursor carried three rounds this session
  and Codex two — check both meters. LXC: **back up before pulling** (real
  collection, several releases behind; no migrations to run this time, but
  0.2.8's settings migration is still pending there).

## 2026-08-27 — Claude Code (Fable 5) — M5.1 opened: #23 CLOSED (PR #159, two Codex rounds; fold-in PR #160)

- **Done:** **#23 — PR #159 open** (`feat/23-instance-settings`, head `18cfc45`,
  ~1,555 insertions — Codex-sized). The `instance_settings` singleton: model
  (int PK, CHECK id=1; DateStyle/HourCycle text enums on the Intl vocabularies),
  migration `f9979ec7b9cb` seeding en-AU/en-AU/UTC/locale/locale plus the
  env-configured REFERENCE_CURRENCY (bootstrap-only from here on),
  `services/instance_settings.py` (gate → FOR UPDATE → per-field validation;
  validators are ValueError-raising module functions the CSV spec parsers
  share), `GET/PATCH /settings`, DB-backed `/meta` (both wrappers async now).
  Every `get_settings().reference_currency` read site rewired: orders snapshots
  (reference threaded per mutation), MCP create_order, the importer's
  `_default_money_currency` (read ONCE in `plan_import` before parsing,
  hash-bound), the starter sheet (examples + expansion take the value).
  Portability: `TableSpec.singleton` — exported, update-only on import, outside
  `_PORTABLE_TABLES`, excluded from replace_all's rows_deleted, absent sheet =
  untouched, a second row dies on the target claim. conftest RESETS (never
  truncates) the row between tests. `tzdata` dependency added. Frontend: client
  types + getSettings/updateSettings, DataPage export row, `matched_id` widened
  (the singleton matches by the int 1). Docs: design §3.10 + §6.1,
  import-export.md ("the one exception"), operations.md ("Bootstrap vs
  runtime"), .env.example, README's M5.1 row.
- **Decisions (deliberate calls, the full numbered list is in the PR body):**
  UTC constant tz bootstrap; interface language membership-tested vs formatting
  locale shape-only; BCP 47 extension subtags refused; no id column in
  settings.csv; replace_all updates rather than resets; **no new MCP tools**
  (get_meta stays the MCP read surface — revisit at #24/#27); enum membership
  left to pydantic/enum_parser rather than a third list.
- **Round 1 (Codex): NO-GO — P2 + 2×P3, all accepted, all reproduced at
  `18cfc45` first, fixed at `fb72dbd`; reply posted.** P2: `parse_currency`
  judged letters with Unicode `isalpha` while PATCH used ASCII — 'ÅUD' imported
  and got stamped into snapshots; now ONE shape test, `require_currency_code`
  in `services/currency.py`, both writers delegate, swept across all five CSV
  currency columns (literal matrix in test_reference_currency.py). P3:
  `canonical_locale` narrowed to the UTS 35 shape Intl consumes (language
  {2,3}|{5,8}, variants unique + stored SORTED — Intl sorts them; the shared
  `frontend/src/lib/__fixtures__/locale-cases.json` + new frontend Intl suite
  found that fourth defect on its first run). P3: the gate test now asserts
  `holder = ANY(pg_blocking_pids(updater))` — Codex proved a decoy advisory
  waiter false-passed the old count-based check (stg-5 GREEN 5/5); post-fix
  the same decoy scenario reads RED 5/5. The two-field test renamed to the
  final-state control it is. Round negative control: 14 red / 130 green in a
  worktree of `18cfc45`.
- **Round 2 (Codex): clean GO** — it replayed all three remedies against
  persisted final state (its own decoy scenario included: stg-5 RED 5/5 with
  an unrelated advisory waiter parked) and re-measured the queue 23/23.
  **PR #159 squash-merged as `7118f96` on the owner's call; #23 closed;
  branch deleted; CI green at every head.**
- **Fold-in PR #160 squash-merged as `ad2da8d`** (owner's call,
  merge-on-green; review skipped per the #40/#132 precedent, stated in the
  body): 23 `stg-` tuples + SET/META constants; TEST_FILES + test_settings.py,
  test_settings_portability.py, test_reference_currency.py; scratch runner
  deleted, superseded. **Full harness 227/227 @ 22m16s measured**; the
  procedure doc's runtime + case-count lines refreshed. No queues outstanding —
  the tracked harness again holds every tuple ever filed.
- **State:** `main` at `ad2da8d` (+ this entry), CI green at every merged
  head. Backend **1186**, vitest **132** (the shared
  `frontend/src/lib/__fixtures__/locale-cases.json` + Intl suite), e2e 30
  (+1 skipped screenshots) verified from-empty this session. One migration
  (`f9979ec7b9cb`, additive + seed) — **live instances must run migrations on
  next pull**; REFERENCE_CURRENCY in .env is bootstrap-only from here on.
  test_reference_currency's env fixture split in two: `bootstrap_currency`
  (monkeypatch, the two config tests) vs the row-writing, awaited
  `reference_currency`. No dev servers running; stale worktrees
  `/private/tmp/plamotrack-pr100` and `-pr108-main` persist (pre-date this).
- **Next:** the rest of **M5.1** — #24 (Settings page + Data absorption; the
  frontend client methods and types already exist), #22 (catalogue manifest —
  unlocks languages beyond en-AU in SUPPORTED_INTERFACE_LANGUAGES),
  #25/#26 (structured diagnostics), #27 (settings UI for language/region),
  #114 (naive CSV dates — the settings row now HOLDS the instance time zone
  it needs). Codex carried both #159 rounds — check its meter before the next
  buy. LXC is still pre-0.2.8: **back up the LXC database before pulling**
  (real collection), and this pull adds the settings migration.

## 2026-08-26 — Claude Code (Fable 5) — #104 + #67 + #63 closed; v0.2.8-alpha RELEASED (“the dead ends open”)

- **Done:** **#104 — PR #153** (`e295e7e`, review skipped per the #121 precedent,
  owner concurred): the catalog picker closes only when focus genuinely leaves
  it (container `onBlur` + `relatedTarget`; the 150ms timer and its race are
  gone) and both result buttons select on `onClick`, which keyboard activation
  shares. The focus-containment test's pre-fix block rewritten (it pinned the
  timer close); a new e2e drives Tab → Enter through to the stored order's
  `catalog_ref_id`. Negative control: red on main on exactly that assertion.
  **#67 — PR #154** (`4d547ef`, Codex round 1 GO + 1 P3, fixed `7ffa587`):
  an id-bearing kit line may omit `kit` — `OrderItemUpsert` overrides the
  create-shape check, `_update_line` restates/propagates nothing it wasn't
  given, a silent quantity increase clones the live first kit (status
  normalised ordered/pre_ordered). Browser: editor hydrates from a fresh
  `GET /orders/{id}` (**`isFetchedAfterMount` is the load-bearing gate** —
  `data` alone serves the stale cache while refetching) and sends kit details
  only when their fields are dirty. Stated details still restate (REST/MCP
  posture, in the MCP docstring + design §3.9/§7 with the #36 pricing note).
  The P3 (Codex measured my own where-I'd-push bullet): a 404'd fresh read sat
  on Loading… forever — now renders words, skips the retry backoff, and
  invalidates the list so the stale row goes too; red-first e2e. Negative
  control 4 red / 1 green (the green: new lines still require details —
  unchanged rule). **Fold-in PR #155** (`fd606a3`): 5 `o67-` tuples, first
  schema-file path constant; harness **199/199 @ 19m06s**. No queues out.
- **Decisions:** quantity growth on a silent line clones rather than refuses —
  refusing would force details onto every quantity change, re-opening the
  stale-echo window for #67's own example. Codex endorsed all five deliberate
  calls, incl. the no-stall e2e pin (it replayed the spec with the omission
  branch disabled and watched it fail on the persisted value).
- **Notable:** Cursor was rate-limited all day — Codex took every round this
  session (#151 ×2, #154 ×1); check its meter before the next buy.
  `_line_kits` and `OrderRead`'s nested kits both order `(created_at, id)` —
  Codex probed it; that agreement is what makes "the first kit" one kit.
- **State:** `main` at `fd606a3` (+ this entry), CI green at every head.
  Backend **1085**, vitest 109, e2e **29** (+1 skipped screenshots) — both new
  suites verified from-empty, tables zero after. Harness 199/199 @ 19m06s.
  No dev servers running; stale worktrees `/private/tmp/plamotrack-pr100` and
  `-pr108-main` persist (pre-date these sessions).
- **Released: v0.2.8-alpha** at tag `ee2355d` ("the dead ends open"),
  `--prerelease`, notes owner-approved; milestone closed at the tag. Gate ran
  clean: both surfaces 0.2.8, packaged stack four-healthy, migrate Exited (0),
  container-exported manifest carries app_version 0.2.8 + schema
  `2c97a5ced66a`; dev overlay restored. **No migrations in this release.**
  **Also this session: #63 — PR #156** (`ec311c1`, Codex GO + 2 P3s, both
  evidence gaps, fixed `2a3e2a5`): `_adjust_ref` gains keyword-only
  `missing_ok`, set ONLY by `delete_order` — a dangling reversal is skipped
  and logged where the entry is being undone wholesale; receive/retarget/line
  removal stay strict, their 409 naming the delete-and-re-enter escape. P3-1:
  my negative control died on main at the logger monkeypatch, not the
  behavioural assert — patch the logger OBJECT with raising=False; P3-2: the
  line-removal boundary was unpinned — test + d63-5 added. **Fold-in PR #157**
  (`a6a0e16`): 5 `d63-` tuples, TEST_FILES + test_integrity.py, harness
  **204/204 @ 21m21s**. Bump **PR #158** (`ee2355d`). Suite-count note: the
  session conftest's alembic fileConfig DISABLES pre-imported app loggers —
  caplog cannot see app-module records anywhere in this suite (measured;
  production unaffected; recorded in PR #156 deliberate call 3).
- **Next:** 0.2.8 done — the backlog ahead is **M5.1** (settings +
  i18n foundation; the #54 harness now exists for its settings migration) or
  owner's pick. #137/#144 await product calls; #122 rides M6.5. Codex carried
  every round this session (Cursor rate-limited) — check its meter. LXC:
  **back up the LXC database before pulling the release** (real collection).

