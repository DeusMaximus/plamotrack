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

## 2026-08-25 — Claude Code (Fable 5) — 0.2.8 underway: #53 + #61 closed (PRs #148/#149/#150), #63 decided

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
  `test_order_lifecycle.py`; harness **187/187 @ 19m48s**. No queues
  outstanding.
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
- **State:** `main` at `8d7bde2` (+ this entry), CI green at every head.
  Backend **1073**, vitest 109, e2e 26 (+1 skipped screenshots spec) verified
  from-empty, harness 187/187. No dev servers running; stale worktrees
  `/private/tmp/plamotrack-pr100` and `-pr108-main` persist (not this
  session's). Codex budget untouched — both rounds this session were Cursor.
- **Next:** the 0.2.8 remainder — **#54** (migration harness; wants to exist
  before M5.1's settings migration), **#104**, **#67**, and the **#63
  implementation** (decision recorded, small strict-scope branch). #137/#144
  still await product calls; #122 rides M6.5. LXC: if v0.2.7 hasn't been
  pulled yet, **back up the LXC database first** (real collection).

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

## 2026-08-24 — Claude Code (Fable 5) — #98 + #127 + #99 closed: PR #130 merged as `dfa87f3` after three Codex rounds; upgrades `category` decided-no

- **Done:** **#98 + #127 in one branch — PR #130** (`feat/98-127-catalog-create-list`,
  head `019f8dd`, **CI green all three jobs**; no migration) — the piece the previous
  entry named. MCP gains `create_kit`, `create_catalog_{tool,consumable,upgrade,display}`,
  `list_catalog_items(item_type, category?)` and `list_catalog_categories(item_type)`,
  all thin over existing services (`test_mcp.py`'s `EXPECTED_TOOLS` pin extended — it
  caught them, as designed). `services/catalog.py` gains `canonical_category` (a
  category matching an existing one case-insensitively is stored under that spelling;
  most-frequent wins, ties `COLLATE "C"`, own row excluded on update), wired into the
  create, the PATCH, and orders' `_build_catalog_row` (rule 1: three live writers);
  `list_catalog` grew a folded-equality category filter; `list_catalog_categories` is
  the #96 shape. REST: `?category=` + `GET .../categories` on the three categorised
  tables. Frontend: datalist typeaheads (Inventory forms + CatalogItemPicker new-mode),
  client-side per-tab filter. Docs: design §3.5/§3.5a/§4/§7, import-export (imports
  keep category spellings verbatim), README's MCP table — which was also missing
  `update_kit` and the three retailer tools from #92/#97, backfilled in passing.
- **Decisions:** **`upgrades` gets NO `category` column** (owner's call, this
  session; recorded in design §3.5) — the machinery is generic over
  `"category" in model.__table__.columns`, so the column is the whole cost if
  revisited. **The importer does not canonicalise categories** (re-import must stay
  a no-op; pinned by two tests) — the narrower fold-on-create-only variant is
  flagged to the reviewer as a judged call, not implemented. **Codex for the
  review** (1,063 insertions is past Cursor's ~1,000 ceiling); brief filled from
  `.agents/review-brief.md`, saved to the session scratchpad as
  `codex-brief-pr130.md` for the owner to paste.
- **State (amended in place after round 1):** **Codex round 1 at `019f8dd`: NO-GO,
  3×P2 + P3 — all four accepted, reproduced red-first, fixed** (`14406ef`, docs +
  #99 at `0660980`); reply posted at head `0660980`, CI pending there. P2-1: the
  `new_item` fold is gated on `CATEGORISED_MODELS` (an upgrade line carrying a
  category is ignored again, not 500'd). P2-2: one trimmed `btrim` expression across
  the canonical pick, filter and vocabulary — legacy padding matched, never
  propagated. P2-3 (Codex overruled the importer exclusion, accepted as prescribed):
  id-less CREATEs (stubs incl., via `synthetic_id`) fold at **plan time** —
  hash-bound, announced as a preview message; UPDATEs and id-bearing restores stay
  verbatim; replace_all folds against the upload's own rows only, verbatim rows
  seed first so sheet order can't matter. P3-4: `useId` per picker; new
  `e2e/category-typeahead.spec.ts` asserts each line's *resolved* datalist options
  (polled — an empty datalist is loading, not the defect). **#99 folded in per the
  #98 triage note**: `get_meta` serves the same function as `GET /meta`; PR closes
  line now carries it. Counts: backend **1014**, vitest 109, e2e **24/24 from
  empty** (Playwright booting its own servers — a run that *reuses* dev servers
  is NOT from-empty), ruff/build/oxlint clean. Scratch harness **23/23 killed**
  (14 re-anchored after P2-2 moved code + cat-15..23, one per round-1 fix site);
  tuples live in untracked `backend/mutation_scratch_127.py`, fold in after merge.
  Round-1 tests at the reviewed head: 8 red / 2 green (the greens: UPDATE and
  id-bearing-restore verbatim controls). Dev servers on :8000/:5173, branch code.
- **Round 2 (amended in place): NO-GO at `0660980` — P2-5 + P3-6, both accepted,
  fixed at `f2215ff`, reply posted; CI pending there.** P2-5 (second round in
  `_fold_new_categories` — taken as the invariant signal it is): the fold now
  builds one **effective post-write multiset** per key — stored rows overlaid by
  the UPDATEs rewriting them, id-bearing restores voting, winner most-frequent
  with the byte-order tie-break, `setdefault` gone; sheet order cannot pick a
  spelling; both Codex reproducers in red-first; mutants cat-24 (overlay off) and
  cat-25 (first-seen winner) die, cat-21/22 re-anchored — harness **25/25**.
  P3-6: `get_meta` no longer imports the REST layer — `services/meta.instance_meta`
  + `schemas/meta.MetaRead`, both wrappers delegate. Backend **1016**.
- **Round 3 (amended in place): GO, clean, at `f2215ff`** — Codex replayed both
  round-2 reproducers, shuffled restore row order, probed the omitted-column
  overlay and stub-fold cells itself, verified `import app.mcp` loads no
  `app.routers*`, and declared the invariant answered ("constructs the effective
  post-write multiset before selecting any winner"). **PR #130 squash-merged as
  `dfa87f3` on the owner's call; #98, #127 and #99 all closed; branch deleted;
  CI green at every head.** Dev servers on :8000/:5173 serve code identical to
  the merge.
- **Also this session (amended in place): agent skills — PR #131 open**
  (`feat/skills-gunpla`, head `e7e6452`, docs-only). The owner's Gunpla-conventions
  draft, revised (decals reclassified as Upgrades per repo canon; the nonexistent
  retailer-currency field replaced with per-order `currency_code` + `get_meta`; a
  Categories section for the #127 vocabulary; grade advice tied to scale
  derivation) and packaged as `skills/plamotrack-gunpla/SKILL.md` in the open
  Agent Skills format, with `skills/README.md` (Claude Desktop install only,
  others "coming soon" — owner's instruction), a README pointer, and design
  §7/§9.1 notes (the skill layer recorded as more staying-generic evidence).
  Review skipped (docs-only, #40 criterion). **Squash-merged as `2b94a41` on the
  owner's call, branch deleted, CI green.**
- **Fold-in done (amended in place): PR #132 open** (`test/fold-cat-dsp-mutants`,
  head `1365ddd`; only `mutation_test.py` + the procedure doc, the #117 shape).
  #129's 10 `dsp-` + #130's 25 `cat-` tuples folded; TEST_FILES +5
  (inventory, orders, write_surface_parity, catalog_categories,
  mcp_catalog_create); dsp anchors pre-checked at `2b94a41` (none moved);
  **full harness 146/146 killed, 15m38s measured** — the testing-and-review.md
  runtime line refreshed (was 97/~11min, stale since #118) and the case-count
  paragraph now names all seven queues. Scratch harness deleted, superseded.
  Review: rides without a round per #40 (contract untouched, every tuple
  reviewed in its source PR) — stated in the PR body, owner concurred.
  **Squash-merged as `41868d9` on the owner's call (merge-on-green), branch
  deleted, CI green.** No queues remain outstanding — the tracked harness now
  holds every tuple ever filed.
- **Reviewer budget (live, 24/08/2026, corrected): Codex has ~99% of its usage
  budget REMAINING** — a full tank, despite three rounds on #130. No reviewer
  constraint on the next 0.2.6 fixes; route by size per the procedure table as
  usual. (An earlier revision of this entry read the number backwards.)
- **Next:** **the mutant fold-in is now the queued mechanical piece** — 25 `cat-`
  tuples (in the PR #130 body and the untracked `backend/mutation_scratch_127.py`,
  which also holds the runner-ready form) plus #129's 10 `dsp-` tuples fold into
  `mutation_test.py` with TEST_FILES + anchors re-checked (the #117 shape: its own
  branch + PR). Then the 0.2.6 list (#77, #87, #90, #112, #119) toward the
  release, or the rest of 0.2.8 (#104/#53/#54/#61/#63/#67 remain).
  Procedure changed this session (owner's call): review briefs
  are **printed in the chat in a copyable four-backtick block**, never handed over
  as a scratchpad path — written into `.agents/review-brief.md` +
  `testing-and-review.md`. Live and still true: **no v0.2.6 tag ever** — one
  v0.2.7-alpha only when BOTH 0.2.6 (#77, #87, #90, #112, #119) and 0.2.7 are
  done; 0.2.7 is empty, so **do not run the release gate**. **#112 before any
  real-collection starter-sheet import.** #122 rides M6.5.

## 2026-08-21 — Claude Code (Opus 5) — #126 closed: PR #129 merged as `20996e1` after two Codex rounds; #127 filed (narrowed against #98); both #127 and #98 sit on 0.2.8

- **Done:** **#126 closed — PR #129 squash-merged as `20996e1`**, branch deleted,
  CI green at every head. `display_items` is the fourth catalog type: name,
  category (required), scale?, manufacturer?, quantity_on_hand, notes, plus
  `ItemType.DISPLAY` — REST CRUD, `update_catalog_display`, order dispatch, CSV
  spec entry, a fourth Inventory tab, Data-page export, docs (§3.5a new; §3.9,
  §4, §7, §9.1, README, import-export, AGENTS rule 2 swept). **Also filed #127**
  and narrowed it after finding it duplicated **#98**'s "MCP cannot list the
  catalog" half; #127 is now only the queryable-`category` part (server-side
  folded filter, frequency-ordered distinct values, canonicalised spelling on
  write) and #98 is its prerequisite. Both on **v0.2.8-alpha**.
- **Decisions:** **No join table to kits, no build status** —
  `upgrade_applications.quantity_used` decrements because an applied upgrade is
  *spent*, whereas a stand moves between kits freely. That also ruled out
  extending `upgrades` (considered, rejected): it would leave one table where
  some rows consume when linked and others don't. Reasoning is in §3.5a and the
  model docstring so it is not re-litigated. **`category` required** because it
  is what makes "how many stands do I have" a filter rather than a guess; the
  surface that makes it *queryable* was deliberately left to #98 + #127 rather
  than built for one table. **§9.1 stays open**, with display items recorded
  there as evidence for staying generic.
- **State:** 965 backend (base 897), 23 e2e, 109 vitest; one additive migration,
  hand-written (autogenerate wanted to drop five text-enum CHECKs and recreate
  none). Its downgrade **refuses** on one invariant — no display data in any
  form — with a state-aware message; **it has no pytest**, deliberately, because
  migrations here are only exercised against an empty schema (**#54**) and that
  harness is #54's job. Verified by shell across four states. **Two Codex rounds:**
  round 1 NO-GO (3×P2 + 2×P3), round 2 GO (2×P3); all seven accepted and fixed,
  none declined. **Eleven mutants, all killed — 10 backend tuples queued in the
  PR body for `mutation_test.py` fold-in**, joining #109's 17, #111's 6 and
  #113's 8; anchors want re-checking, the code moved under them. dsp-11 is
  Codex's own and is worth folding in because it *survived* a green suite.
  New lesson in `.agents/lessons.md` → "Green for the wrong reason" → **"An edit
  that never applied, asserted as landed"**: a scripted `.replace()` silently
  matched nothing, the suite stayed green (which is what a missing stricter test
  also looks like), and the PR body claimed the file had been changed. Assert the
  anchor matched; confirm a new case is collected before claiming it.
- **Next:** **#98 + #127 together** are the natural next piece — same area, shared
  code through `CATALOG_MODELS`, and #127's filters hang off #98's list tools;
  doing #127 alone would leave three tables behind. Live and still true:
  **release cadence — no v0.2.6 tag ever**; one v0.2.7-alpha cut only when BOTH
  the 0.2.6 milestone (#77, #87, #90, #112, #119 open) and 0.2.7 are done, so
  **do not run the release gate when 0.2.7 alone empties**. #122 rides M6.5 (UI
  redesign, direction open, before M7/M8).
