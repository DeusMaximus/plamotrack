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

## YYYY-MM-DD — <agent> — <short title>
- **Done:**
- **Decisions:**
- **State:** (tests? migrations? anything half-finished?)
- **Next:**
```

---

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

## 2026-08-25 — Claude Code (Fable 5) — 0.2.8 underway: #53 + #61 + #54 closed (PRs #148–#152), #63 decided

- **Done:** **#53 — PR #148** (`64ac350`, docs-only, review skipped per #40,
  owner concurred). Decision: **export unescaped, document it** — caveat in the
  archive's bundled README.txt (the `_README` string in `exporting.py`),
  import-export.md "Limits and safety", reasoning + both declined alternatives
  in design §12.8. **#61 — PR #149** (`914fcac`):
  `withdraw_upgrade_application` — write-gated, upgrade row locked in
  `apply_upgrade`'s order on BOTH flavours, **`restore_stock` required with no
  default on any surface**; REST `DELETE
  /upgrades/{id}/applications/{aid}?restore_stock=` + `GET
  /kits/{id}/applications`; MCP tool (docstring: ask, don't guess) + `get_kit`
  embeds applications; kit editor "Applied upgrades" section (two equal-weight
  buttons, no default); the two dead-end guard messages (#37 kit delete,
  upgrade delete) now point at withdrawal and release after it. Design §3.6
  block in the same commit. Cursor round 1 **GO + 1 P3** (order-line release
  untested) — fixed `def519b`, red-proofed under the wdr-6 mutant.
  **Fold-in PR #150** (`8d7bde2`, review skipped per the #132 precedent, owner
  concurred): 11 `wdr-` tuples; TEST_FILES + `test_mcp.py` +
  `test_order_lifecycle.py`. **#54 — PR #151** (`204e957`, TWO Codex rounds —
  Cursor was down on high load): `tests/test_migration_data.py`, 7 tests that
  walk `plamotrack_test` to each data-bearing revision's parent, seed the old
  shape by textual SQL, and assert both directions — the four #54 revisions
  plus the #126 display downgrade guard across its four states;
  operations.md documents the 6cbd legacy state (received order, `ordered`
  kit — never repaired, by design). Round 1 NO-GO, both findings real and
  reproduced first: P2 (my walk-teardown fallback swallowed a later
  migration failing against seeded rows — recovery and verdict now separate
  in `_restore_head`, re-raise when the body passed) and P3 (the
  date→timestamptz→date identity is FALSE for a civil date the zone skipped
  — Pacific/Apia never had 2011-12-30; the contract is exact-instant
  equality, and the skipped-date policy is pinned under an ALTER DATABASE'd
  Apia default). Round 2 clean GO, everything replayed. **Fold-in PR #152**
  (`6ef0d1b`): 7 `mig-` tuples — the first cases that mutate MIGRATIONS;
  `tree_is_clean` now covers `alembic/`; harness **194/194 @ 19m48s**. No
  queues outstanding.
- **Decisions:** **#63 (owner, this session): option 2** — `delete_order`
  treats a dangling old `catalog_ref_id` as nothing-to-reverse (logged);
  receive/edit/retarget stay strict 409s. Recorded on the issue; implementation
  stays open on 0.2.8; reasoning lands in design.md with it.
- **Notable:** my brief's wdr-7 kill mechanism was wrong (claimed
  `StaleDataError`; measured: both racers succeed, the empty DELETE is a
  `SAWarning`, the end-state assert kills) — Cursor corrected it; owned in the
  PR #149 reply and recorded beside the tuples in `mutation_test.py`. Cursor
  also reproduced both #44-shaped import interactions under deliberate call 5
  and endorsed no `invariants.py` change — its paragraph on the PR is the
  reference if that ever resurfaces.
- **State:** `main` at `6ef0d1b` (+ this entry), CI green at every head.
  Backend **1080**, vitest 109, e2e 26 (+1 skipped screenshots spec) verified
  from-empty, harness 194/194; the procedure doc's drifted suite-count table
  refreshed (~534 → ~1080). No dev servers running; stale worktrees
  `/private/tmp/plamotrack-pr100` and `-pr108-main` persist (not this
  session's). Codex budget untouched — both rounds this session were Cursor.
- **Next:** the 0.2.8 remainder — **#104**, **#67**, and the **#63
  implementation** (decision recorded, small strict-scope branch). The
  migration harness (#54) now exists for M5.1's settings migration to lean
  on. Codex took both #151 rounds (Cursor down); its budget is dented but was
  ~full. #137/#144 still await product calls; #122 rides M6.5. LXC: if
  v0.2.7 hasn't been pulled yet, **back up the LXC database first** (real
  collection).

## 2026-08-25 — Claude Code (Fable 5) — v0.2.7-alpha RELEASED; #119, #77, #87 closed (one Cursor round each); docs + screenshots refreshed; both milestones closed

- **Released: v0.2.7-alpha** at tag `921c4f1` ("the importer keeps its promises"),
  `--prerelease`, notes owner-approved; gate ran clean (both surfaces 0.2.7,
  packaged stack healthy, migrate Exited (0), container-exported manifest carries
  app_version 0.2.7 + schema `2c97a5ced66a`; dev overlay restored). Milestones
  0.2.6 and 0.2.7 both closed at the tag. **No v0.2.6 tag exists, by design.**
- **Done this session:** **#119 — PR #139** (`b6c083d`): derived ship/receive
  advances as hash-bound `_Advance` plan descriptors; Cursor GO + 1 P3 (docs),
  fixed `7de77bb`. **#77 — PR #141** (`0302c36`): `require_total_fanout` /
  MAX_TOTAL_FANOUT=10,000 shared by entry, edit (stated totals, pre-lock) and the
  import planner (actual spawns → blocking error; restore-safe); Cursor GO + 2 P3s
  fixed `0f16ef8`. **#87 — PR #143** (`d41d7c5`), owner chose option 1: a new
  catalog line may not join a stored already-received order
  (`_check_lines_joining_received_orders`; the replace_all return is load-bearing);
  Cursor clean GO, zero findings. Fold-ins #140/#142/#145 merged — tracked
  harness **176/176** (`adv-`/`cap-`/`rcv-`), no queues outstanding.
  **Docs PR #146**: all six screenshots re-shot post-#120/#126 via the new
  repeatable `frontend/e2e/screenshots.spec.ts` (skipped unless SCREENSHOTS=1;
  seeds a throwaway `plamotrack_demo` DB, refuses a non-empty one); README gained
  the order-timeline paragraph + the M6.5 redesign row; operations.md's
  "before 0.2.6" → 0.2.7. Version bump PR #147 (`921c4f1`).
- **Notable finds:** the pre-existing currency-fingerprint test seeded the exact
  #87 defect and asserted it as good — adapted to a pending parent (its subject
  preserved; disclosed in PR #143, verified by the round). `-k fan-` collides
  with "fan-out" in strt-7's label (prefix rule matters); cap-/rcv- chosen by
  grep-first.
- **Filed:** **#144** — parallel agent sessions collide on `plamotrack_test`,
  the dev ports and the harness's in-place mutation; sketch: `PLAMOTRACK_TEST_DB`
  override + per-session ports. **Owner's call: backburner** until parallel
  sessions ramp up. #137 stays unmilestoned (product call).
- **State:** `main` at `921c4f1` == the tag (+ this entry), backend **1056**,
  vitest 109, e2e 24 (+1 skipped screenshot spec), harness 176/176 @ 18m08s,
  CI green at every head. Dev db container back on the dev overlay; no dev
  servers running. Codex budget still ~full (unused; all four rounds were
  Cursor).
- **Next:** the owner will likely pull the release onto the LXC — **back up the
  LXC database first** (real collection). Then the 0.2.8 backlog
  (#104/#53/#54/#61/#63/#67) or M5.1; #122 rides M6.5; #137 and #144 await
  product calls. The AI-native-SDLC review (owner asked, this session) filed no
  issues but shortlisted: deterministic hooks for `down -v` / migration edits,
  a scheduled CI harness run, plan-first for M6, per-worktree test DBs (#144).

## 2026-08-24 — Claude Code (Fable 5) — #90 + #112 closed (PRs #133, #136, one Cursor round each); both mutant queues folded (#135, #138); #137 filed

- **Done:** **#90 — PR #133** squash-merged as `545f341`, Cursor round 1 GO clean.
  `_resolve_ref` now dispatches catalog refs through `invariants.effective_item_type`,
  which gained a `stored` parameter for the one caller that runs before matching
  binds `row.target` (a typeless row can only match by id, so the lookup equals the
  future target). Post-#86 the live damage was: dead uuid **written through on
  stored kit lines**, `catalog_name` mirror silently ignored, upload-remapped id
  falsely refused — all three red-first; 6 tests in `test_order_invariants.py`
  (3 red / 3 green worktree control). **#112 — PR #136** squash-merged as
  `ce59b2b`, Cursor GO + 2 P3s, both answered at `cf19d17`. The starter sheet's
  retailer branch synthesizes stable line ids and emits full `kits` rows with
  `order_item_id`, so the §3.9 hybrid dispatch spawns nothing and rating/notes/
  build dates/series all travel; status + arrival stamp resolved through
  `initial_kit_status` (made public — rule-1 shared predicate; the receive-advance
  is UPDATE-only, so this resolution is load-bearing, proven by a mutant).
  import-export.md's #112 caveat removed. P3-1 (cross-file same-order-key
  restatement) remedied by documentation, its optional preview banner **declined**
  (the update diff already shows the price/qty movement); P3-2 pinned as tests
  (stated in_transit, replace_all). A st-2 count slip Cursor caught was owned and
  corrected in the PR body.
- **Decisions:** **line ids are keyed on order key + kit identity + occurrence,
  overruling #112's "position" sketch** — position ids silently rewrite lines when
  one order key (shop+date, numberless) spans two separately-imported files;
  quantity/price deliberately outside the id so fix-and-re-import updates in
  place. Review-endorsed (PR #136 deliberate calls 1–2). Cursor for both reviews
  (~200 and ~340 insertions — size table).
- **Fold-ins:** #133's queue merged as **PR #135** (`25f5b20`), #136's as
  **PR #138** (`85468c9`); #136's tuples relabelled `st-` → `strt-` (`-k st-`
  substring-matches "post-write" in old labels; prefix rule sharpened in the
  procedure doc). Harness **156/156, 16m12s**; runtime + case-count lines
  refreshed. **No mutant queues outstanding.**
- **Also:** **#137 filed** — standalone (retailer-free) starter rows duplicate on
  re-import (verified: one row, two applies, two kits); no synthesized standalone
  id is safe (any scheme merges distinct physical kits across split files —
  corruption beats duplication), so the remedy is a product call; unmilestoned.
  A full-harness run mid-session read as ~15 mass failures: a spawned agent
  session ran pytest against `plamotrack_test` concurrently — signature now in
  testing-and-review.md ("a burst of failures that vanish on re-probe").
- **State:** clean. `main` at `85468c9`, CI green at every merged head, backend
  **1031**, harness 156/156. Dev servers on :8000/:5173 still run **pre-#133
  code** — stale, restart before any browser verification. Codex budget ~99%
  remaining (unused this session; both rounds were Cursor).
- **Next:** **#119, in a fresh session** (owner's call, context budget) — derived
  ship/receive kit advances hash-bound as plan descriptors, BOTH siblings in one
  structural change extending the `_Spawn` precedent. Then #77 (aggregate fan-out
  cap). **#87 stays blocked on the owner's product call** (refuse vs leave —
  owner deferred to "discuss when we get there"). Live: **no v0.2.6 tag ever**;
  one v0.2.7-alpha only when BOTH 0.2.6 (#119, #77, #87) and 0.2.7 are done, and
  0.2.7 is empty, so **do not run the release gate**. #112 merged means the
  real-collection starter import is unblocked — **back up the LXC before pulling
  `main`**. #122 rides M6.5.
