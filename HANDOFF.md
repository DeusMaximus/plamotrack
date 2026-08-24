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
  reviewed in its source PR) — stated in the PR body, owner may overrule.
  **Awaiting the owner's merge call.**
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

## 2026-08-21 — Claude Code (Fable 5) — #120 closed: PR #121 merged as `f3c5d1a`, review skipped; #122 filed; release cadence decided (no v0.2.6 tag)

- **Done:** **#120 items 1+2 — PR #121** (branch `feat/120-status-editing`, head
  `a8c4406`, CI green all three jobs). Browser-only; no service, schema, REST,
  MCP or CSV change. Kits: inline status select + its mutation removed, badge
  display-only (the board's `lib/kitStatusMutation.ts` is separate and
  untouched). Orders: Ship/Receive modals and row buttons removed; Edit's
  "Shipped on"/"Received on" fields show regardless of state — correction PATCH
  when the instant is set (unchanged), ship/receive dispatch on save when it
  isn't (ship before receive; one-way `useRef` latches so a retry after partial
  failure can't replay a transition the server already took); SHIPPED/RECEIVED
  table columns mirror Kits' Started/Completed, counting transit live
  ("in transit · N d"); per-line Ordered/Pre-ordered picker replaced by one
  create-time Pre-order toggle applied to every kit line at submit — the API
  keeps per-line status (edits round-trip the first spawned kit's; a line added
  mid-edit inherits the order's derived pre-order state). Design §3.9 gained a
  sentence. e2e 20 → **21**: happy-path ships+receives through Edit and pins
  both column renderings; receive-backdate does both backdates in one save
  (the #93 tz pin now covers `shipped_at` too); new `preorder-toggle.spec.ts`
  pins the every-line fan-out with two kit lines. Negative control in a `main`
  worktree: 3 red, each on the exact control the branch adds (reasons in the PR
  body); worktree + e2e DB removed after. vitest 109, build/oxlint clean; e2e
  verified against a DB migrated from empty, all tables zero after.
- **Decisions:** **Release cadence (owner's call, this session): no v0.2.6 tag
  ever.** One release — v0.2.7-alpha — cut only when BOTH the 0.2.6 milestone
  (#77, #87, #90, #112, #119 open) and 0.2.7 (#120) are done; both milestones
  close at that tag. **Do not run the release gate when 0.2.7 alone empties.**
  Deliberate calls on the PR: ship-backfill on a received order is now
  browser-reachable (#118 kept it REST/MCP-only over button real estate, the
  service is explicitly legal); in-hand clears + disables pre-order at create;
  MCP's `update_kit_status` shortcut stays. **Review skipped, owner's call** —
  frontend-only consolidation, no shared mechanism (#40 criterion); Copilot
  auto-review stays disabled until 1 September, Cursor offered and declined.
  **M6.5 — UI redesign created (owner's call, same session):** standalone
  milestone, after M6/6.1 and before M7/M8, so the gallery and showcase are
  built in the new look once; direction still under exploration, deliberately
  undecided. Roadmaps updated in AGENTS.md + design §11 (which also got its
  stale hardening paragraph refreshed: #97/#120 shipped, the no-v0.2.6-tag
  cadence written in). #122 milestoned to M6.5.
- **State (amended in place after the merge):** **PR #121 squash-merged as
  `f3c5d1a`, branch deleted, #120 closed** on the owner's call, CI green at
  `a8c4406` (the merged head). No migration. **#122 filed** — #120's deferred
  item 3 (board cards → Edit dialog) spun out so it isn't lost in the closed
  issue; milestoned to **M6.5 — UI redesign** on the owner's call. **The
  0.2.7 milestone is now empty — do NOT run the release gate** (cadence above:
  one v0.2.7-alpha release only when 0.2.6 is also done). Dev servers running
  on :8000/:5173, now serving merged `main`. Stale worktrees
  `/private/tmp/plamotrack-pr100` and `-pr108-main` remain, not this session's.
- **Next:** the 0.2.6 list (#77, #87, #90, #112, #119), reprioritized by
  dogfooding — the owner intends to start dogfooding off `main` (real instance
  is the Proxmox LXC), and **#112 goes before any real-collection import**
  (the starter sheet drops kit-only fields on retailer-bearing rows). Gate +
  v0.2.7-alpha tag only when both milestones are empty.

## 2026-08-21 — Claude Code (Sonnet 5) — #120 filed: the 0.2.7 "one more item" is named

- **Done:** UI walkthrough with the owner over the Kits and Orders pages (no
  code changed this session). Three gaps surfaced and filed as **#120**,
  milestoned to v0.2.7-alpha: (1) Kits table shows status as both a badge and a
  redundant inline `<select>` — the dropdown bypasses Edit and should go,
  status changes only through Edit going forward; (2) Orders — Ship/Receive
  already backdate correctly (#95/#111) but live in separate modals from
  Edit's date-correction fields, should fold into one Edit-order dialog; the
  row space Ship/Receive buttons free up becomes `SHIPPED`/`RECEIVED` columns
  mirroring Kits' Started/Completed elapsed-day pattern; the per-line
  `kit_status` (ordered/pre_ordered) picker on order line items is a confusing
  per-line rendering of what's really an order-wide flag (a retailer splitting
  a shipment becomes two plamotrack orders, per the owner's stated workflow) —
  promote to one flag set at order creation, applied to every line, drop the
  per-line picker. (3) Board cards (Build and Orders kanban) don't open the
  same Edit dialog their list-page rows do — filed but **explicitly deferred
  by the owner** to a future UI redesign, not 0.2.7 scope.
- **Decisions:** #120 items 1+2 are 0.2.7 scope; item 3 is deferred and
  deliberately *not* milestoned to 0.2.7 (the issue body says so — don't pull
  it into this milestone without asking).
- **State:** no code changes, no migration, no tests touched. Dev servers were
  already running on :8000/:5173 from the prior session; left as-is.
- **Next:** implement #120 (items 1+2) — this is the "one more item" the prior
  entry said the owner was adding to 0.2.7. Once it lands, run the release gate
  (`.agents/testing-and-review.md`) and 0.2.7 is ready to cut.

## 2026-08-21 — Claude Code (Fable 5) — #117 merged as `7396e5d`, #118 merged as `53009c0` (#95 closed) after two Codex rounds; 0.2.7 held open for one more item

- **Done:** (1) **The fold-in queue, folded — PR #117** (branch
  `test/fold-queued-mutants`, `985e6d7`; no app or test code — only
  `mutation_test.py` and the procedure doc). The true queue was **29, not the 33
  earlier entries said** (two count slips: #111 carries 5 tuples, and #113's
  five live in its round-1 Cursor review while its body names only 3
  candidates) — harness 68 → **97 over eight files**, TEST_FILES +6 suites,
  `rcpt-1` re-anchored across #86's `receipt_is_future` refactor, every anchor
  verified once against `386ebda`, full run **97/97 killed**. (2) **#95
  implemented on the five agreed leans — PR #118** (branch `feat/95-shipped-at`,
  `c8d4c75`): `shipped_at` + the ship transition on every writer, one additive
  migration; the advance stamps the ship instant (the #93 rule one stage
  earlier, `stamp_build_date` wired per #94); the importer ships **freely on
  every order** (no stock basis to refuse, unlike the receipt), un-shipping
  refused everywhere, **no cross-field validation** (#113's rule, the issue's
  open constraint settled that way), the spawn's ship instant resolved at plan
  time and hash-bound (round five's P3 lesson applied before a reviewer had
  to); browser Ship dialog, Shipped badge, and the **derived** pre-order badge
  (nothing persisted). 32 tests (**31 red / 1 explained green** against `main`
  in a worktree, test DB dropped first), `ship-1..7` mutants one per fix site,
  branch harness **75/75**, backend **896**, e2e **20**, and the browser loop
  driven by hand — a backdated ship stored local-midnight in the browser's own
  offset, both kits advanced on the same instant.
- **Decisions (all in #118's "Deliberate calls"):** the five leans as agreed,
  plus the browser Ship button on pending-unshipped rows only (backfill on a
  received order stays REST/MCP), asserted-in_transit kits borrowing the ship
  stamp (the asserted-backlog parallel), and ship-after-receive legal while
  receive never backfills.
- **State: Codex round one is answered on both PRs.** **#117: GO, two P3s,
  both taken at `34f9e52`**, reply posted — the harness now runs each selection
  unmutated first and requires a pass (`SICK` otherwise; it caught the
  stale-test-DB scenario live), a kill is exit 1 + "failed" + no "error"
  (`ERROR` otherwise), `cell-4` re-anchored as a compiling mutant (its old
  replacement never compiled — an IndentationError stood in for the assertion
  for its whole life), and the runtime claim remeasured: **665s ≈ 11 min at 97
  cases** (was a 30-40 min extrapolation slip, owned). **#118: NO-GO, P2 +
  three P3s, answered at `5b98142`**, reply posted — P2 fixed red-first
  (`_restamp_receipt_kits` gains `only_status`; ship correction passes
  IN_TRANSIT because a ship and a receive can share a local-midnight instant
  and the receipt owns the backlog kit; receipt contract untouched per the
  review's "do not"); P3-3's six unmutated sites + the fix site now have
  tuples (branch harness **82/82**, suite **897**); P3-4 docs fixed; **P3-2
  filed as #119** (derived advances not plan-bound — BOTH ship and receipt
  siblings, the receipt one pre-existing since #86). **Round two: both GO,
  clean** — Codex independently replayed the stale-DB and cell-4 controls on
  #117 and the P2 regression + status-precedence corners on #118, declined the
  JUnit alternative as unnecessary, and re-affirmed #119's scoping. **Merged in
  the declared order, on the owner's call: #117 squash-merged as `7396e5d`;
  `main` merged forward into #118 (the CASES-tail conflict resolved as
  declared — both blocks, one `ORD`, TEST_FILES union), combined harness
  **111/111 under the new kill contract** + suite **897** + CI green at
  `4f98b69`; #118 squash-merged as `53009c0`, #95 closed, both branches
  deleted.** Dev servers running on :8000/:5173; dev DB disposable. Live:
  **0.2.7 is deliberately NOT closed — the owner is adding one more item to
  the milestone** (unnamed at hand-off time; do not read "last item merged" as
  "cut the release"). #110/#112 and #77/#87/#90 unblocked; #114 M5.1-shaped;
  #116 + #119 unmilestoned; 0.2.8 open (#104/#98/#99/#53/#54/#61/#63/#67).
- **Next:** wait for the owner's new 0.2.7 item; implement it; only then the
  release gate (`.agents/testing-and-review.md`) for 0.2.7. The harness on
  `main` is now 111 cases / ~13 min, baseline-inclusive — the runtime line in
  testing-and-review.md says 97 cases / ~11 min and can be refreshed in
  passing next time that file is edited.
