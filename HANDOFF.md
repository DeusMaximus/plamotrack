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

## 2026-08-21 — Claude Code (Opus 5) — #126 implemented: `display_items`, the fourth catalog type; #127 filed (narrowed against #98); both milestoned 0.2.8

- **Done:** **#126 — PR #129** (branch `feat/126-display-items`, head `5a29cb2`),
  pushed, **awaiting its review round**. New `display_items` table (name, category
  required, scale?, manufacturer?, quantity_on_hand, notes) + `ItemType.DISPLAY`:
  full REST CRUD, `update_catalog_display` MCP tool, order dispatch, CSV spec
  entry, a fourth Inventory tab, docs (§3.5a new, §3.9/§4/§7/§9.1 updated,
  README, import-export). 34 files, ~1,300 insertions.
  Also **filed #127**, then **narrowed it**: as first written it duplicated
  **#98**'s "MCP cannot list the catalog" half. #127 is now only the part #98
  doesn't cover — a server-side folded `category` filter, a frequency-ordered
  distinct-categories surface (#96's `series` pattern), and canonicalising
  category spelling on write. #98 is its prerequisite. **#126 and #127 both
  milestoned v0.2.8-alpha.**
- **Decisions (owner, this session):**
  - **No join table to kits and no build status**, and the reason is one thing:
    `upgrade_applications.quantity_used` decrements because an applied upgrade is
    *spent*, whereas a stand moves between kits freely. That also rules out
    extending `upgrades` (the cheap option considered and rejected) — it would
    leave one table where some rows consume when linked and others don't, i.e.
    `quantity_on_hand` meaning two things by row. Reasoning is in §3.5a and the
    model docstring so it isn't re-litigated.
  - **`category` required**, because it is what makes "how many stands do I have"
    a filter rather than an agent guessing from product names. The surface that
    makes it *queryable* is deliberately **not** in this branch — building it for
    one table would leave the other three behind (#98 + #127 sweep all four).
  - **§9.1 unchanged as an open decision**, but display items recorded there as
    *evidence* for staying generic: free-text category + nullable scale fits model
    railway and 1/35 armour unmodified.
- **State:** 936 backend (+16), 23 e2e (+2, against a database migrated from
  empty; all tables 0 afterwards), 109 vitest, ruff + oxlint + `tsc -b` clean.
  Migration is **hand-written** — autogenerate got the table right and then
  proposed dropping `ck_kits_kit_status`, `ck_order_items_item_type` and all three
  retailer enum constraints without recreating any; only item_type genuinely
  changes. Downgrade **refuses** rather than deletes when display order lines
  exist. Two defects found by the new coverage, both fixed: `names._NOUN` is a
  per-model dict whose missing entry raised `KeyError` *inside* the conflict path
  (a 500 where a 409 was owed), and `_NON_NULLABLE` was a bare name set that would
  have refused clearing the nullable `manufacturer` here. **Three hand-run mutants,
  no harness cases yet** — tuples are queued in the PR body for fold-in.
  Dev servers may be running on :8000/:5173.
- **Next:** **PR #129 goes to Codex** — 1,300 insertions is past Cursor's ~1,000
  ceiling and this wants multi-round. Check Codex's remaining usage budget before
  starting; the filled brief is in this session's scratchpad as
  `codex-brief-129.md`. After merge: **#98 + #127 together** are the
  natural next piece (same area, shared code through `CATALOG_MODELS`, and #127's
  filters hang off #98's list tools). Live and still true: **release cadence — no
  v0.2.6 tag ever**; one v0.2.7-alpha cut only when BOTH the 0.2.6 milestone
  (#77, #87, #90, #112, #119 open) and 0.2.7 are done, so **do not run the release
  gate when 0.2.7 alone empties**. #122 rides M6.5 (UI redesign, direction open,
  before M7/M8). Mutant fold-ins still owed from #109 (17), #111 (6), #113 (8),
  plus this branch's 5.

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

## 2026-08-20 — Claude Code (Fable 5) — #86 MERGED as `386ebda` after Codex rounds 5+6; #44 closed; #116 filed; the 0.2.7 gate is released

- **Done:** owner asked to continue #86. (1) **`main` merged into the branch**
  (`cb6e952` — merge, not rebase, so the thread's SHA anchors survive): #109 +
  #111 + #113 + #115, zero textual conflicts; verified after the merge — 850
  backend, ruff clean, frontend build/oxlint/vitest clean, 63/63 mutants with
  every anchor still matching once despite #111/#115 rewriting `orders.py` under
  the branch's shared predicates. (2) **Stamping decision taken (owner's call):
  both importer arrival sites borrow the order's `received_at`** (`5cbc31d`) —
  `_advance_kits_for_newly_received_orders` stamps the applied receipt instead of
  `now`, and the apply loop's `spawn_kits` call passes the post-write order row's
  receipt (`spawn_kits`' own gate keeps it off kits asserted past backlog).
  Sweeping the class found a third site: import corrections of a receipt date
  don't restamp kits the way REST's `_restamp_receipt_kits` does — **declined and
  filed as #116**, pinned by `test_a_correction_by_import_leaves_kit_stamps_alone`.
  Docs in the same commit: design §3.9 + §12.5, import-export.md. Eight new tests
  in `test_order_invariants.py` over the value, state and **mode** axes
  (replace_all included, plus a receive-and-spawn-in-one-upload case that pins the
  write-loop-before-fan-out ordering); negative control **5 red / 3 green at
  `cb6e952`** (greens = the two asserted-past-backlog gate cases and the
  no-cascade pin); mutants `stamp-1`/`stamp-2` added to the tracked harness, one
  per fix site, each killed by a distinct test. Decision comment posted on the PR
  at `5cbc31d`.
- **Decisions:** merge-forward, never rebase, on a reviewed public PR (anchors +
  squash-merge); borrow at both arrival sites but decline the correction cascade
  (#116 — the importer writes only rows the upload names plus the two arrival
  derivations); the fan-out reads the receipt **post-write** via
  `session.get(Order, ...)` — a plan-time value would miss a receipt the same
  upload sets.
- **State:** branch head **`5846c44`, pushed**; backend **864**, ruff clean,
  **68/68 mutants**; frontend untouched since `cb6e952` (verified clean there);
  no migration beyond `main`'s. **Codex round 5 (the gating round, brief from
  `.agents/review-brief.md`) ran at `5cbc31d`: NO-GO, one P2 + one P3, both
  fixed at `5846c44`, reply posted; it took no issue with any deliberate call.**
  P2: a future `received_at` was refused by REST/MCP but accepted by import —
  `receipt_is_future` is now a shared predicate in `services/orders.py`, and
  `invariants._check_future_receipts` refuses it at preview wherever an upload
  *writes* the column (change-not-cell: legacy future values restate as no-ops;
  **create-is-a-restore is the stated policy**, both modes pinned — flipping it
  is one condition and two tests). P3: the spawn's stamp was read post-hash-
  check; `_order_receipt` resolves the post-write instant at plan time, `_Spawn`
  carries it, the fingerprint hashes it, apply writes the planned value — a
  correction between preview and apply now stales the hash (409). Six tests
  (3 red-first at `5cbc31d` on the review's own assertions / 3 controls);
  mutants `stamp-3`/`fut-1`/`fut-2` new, `stamp-1` re-anchored. The queued
  `rcpt-` fold-in tuples anchor lines the predicate refactor moved — re-check at
  fold-in. **Round 6: GO, clean** — Codex replayed both failure modes
  independently at `5846c44`, accepted create-as-restore as a stated product
  decision, and declared clear-to-merge; **#86 squash-merged as `386ebda`,
  branch deleted, #44 closed**, on the owner's call. Six review rounds total on
  this PR; all thread SHAs survive because the branch was always merged forward,
  never rebased. Trap re-confirmed the hard way: two
  concurrent pytest sessions against `plamotrack_test` truncate each other into
  phantom failures — one session at a time is already the written rule. Stale
  worktrees `/private/tmp/plamotrack-pr100` and `-pr108-main` remain, not this
  session's, left alone. Live and still true: **the #86 gate is released** —
  #95, #110, #112, #77, #87 and #90 are unblocked; **0.2.7 is now #95-or-defer,
  owner's call**; 0.2.8 is open ground (#104/#98/#99/#53/#54/#61/#63/#67); #114
  is M5.1-shaped; #116 unmilestoned.
- **Next:** the mutant fold-in queue is actionable now that #86's harness is on
  `main`: 33 tuples from the PR bodies of #109 (17), #111 (6), #113 (8) and
  #115 (2) fold into `mutation_test.py` — anchors verified once at their source,
  but the `rcpt-` set anchors lines the `receipt_is_future` refactor moved, so
  expect the harness to report those and re-anchor them. Then #95-or-defer
  decides 0.2.7; #110/#112 are ready when milestoned.
