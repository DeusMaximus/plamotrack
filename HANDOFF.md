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

## 2026-08-21 — Claude Code (Fable 5) — #120 implemented: PR #121 open, CI green; release cadence decided (no v0.2.6 tag)

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
  MCP's `update_kit_status` shortcut stays. **Review call: recommended no
  external review** — frontend-only consolidation, no shared mechanism (#40
  criterion); the owner had not yet confirmed at hand-off time.
- **State:** PR #121 open, unmerged; CI green at `a8c4406`; no migration. Dev
  servers running on :8000/:5173 (serving this branch). Note: the previous
  session's hand-off commit `1c37dfb` was never pushed — it goes up with this
  one. Stale worktrees `/private/tmp/plamotrack-pr100` and `-pr108-main`
  remain, not this session's.
- **Next:** owner decides review-or-merge on #121 (#120 closes on merge). Then
  the 0.2.6 list, reprioritized by dogfooding — the owner plans to dogfood off
  `main` once #120 lands, and **#112 goes before any real-collection import**
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

## 2026-08-20 — Claude Code (Fable 5) — #94 + #96 closed: PR #113 merged as `93ec9cc` after one Cursor round; #112 + #114 filed

- **Done:** **#94 + #96 closed — PR #113 squash-merged as `93ec9cc`**, branch
  deleted, on the owner's call after one Cursor round (Grok 4.6) at `523deed`:
  GO, P2-1 + P3-1, both taken at `8928f3e`; CI green at every head. No second
  round: both remedies were the reviewer's own prescription, verified red-first
  and one-site-mutated (the #109/#111 precedent). P2-1: the
  #112 caveat omitted `series` from its own dropped-field list — one docs
  sentence. P3-1: blank/whitespace series stored and served by /kits/series —
  `_normalize_series` on both write paths (blank → null, values trimmed,
  matching parse_text) plus a `names.WHITESPACE` btrim guard on the distinct
  values; two tests red-first at `523deed`, three fix sites one-site-mutated.
  Also took the review's two pins (re-completion mirror; MCP naive build date)
  and filed **#114** (naive CSV dates read as midnight UTC — the class behind
  the starter sheet's date columns; M5.1-shaped). Reply posted at `8928f3e`.**
  Five separable commits: one additive hand-checked migration (three nullable
  `kits` columns, **no backfill** per #94's decision); #94 — `stamp_build_date`
  in `services/kits.py`, called by both live status writers (`update_kit`,
  `receive_order`'s advance), stamps only-when-null and never against an
  explicit value in the same request; importer and creation never derive
  (rule 10 by analogy; cell states keep absent=keep / blank=clear /
  populated=overwrite over a stored date); #96 — free-text `series`,
  `GET /kits/series` + MCP `list_kit_series` (most-frequent-first) feeding the
  kit form's datalist (`staleTime: 0`, the #49/#108 rule), `series=` filter on
  service/REST/MCP with the #49 fold; spec.py + starter sheet + docs updated.
  On owner feedback the Kits table now shows **Started/Completed** columns
  (elapsed days inline) and dropped the `status_updated_at` "Since" column;
  kit-side arrival date **considered and deferred** (recorded in design §3.1 —
  derivable only via the spawning order; lives on the order side for now).
  **#112 filed**: the starter sheet's retailer-bearing rows silently drop every
  kit-only field (`rating`, `build_notes`, now the three new ones) — proven via
  `expand()`; fix leans on the hybrid dispatch #86 is re-deciding, so sequenced
  after #86; disclosed in import-export.md meanwhile.
- **Decisions (on the PR as "Deliberate calls"):** stamp-only-when-null incl.
  re-completion; creation never derives; **no cross-field validation** (user
  owns the values; a service check would diverge from the importer); the
  browser series *filter* is client-side while the form typeahead uses the
  endpoint; `/kits/series` declared before `/{kit_id}` (route test pins it).
- **State:** backend **742** (713 + 19 `test_build_dates.py` + 10
  `test_series.py`), vitest 109, e2e 20 against a DB migrated from empty, all
  zero after; ruff/oxlint/builds clean. Negative control: **24 red / 1 green
  of 25 on unfixed `main`** (re-measured by the reviewer); round 1's four
  additions split 2 red (P3-1) / 2 green (pins) against `523deed`, stated in
  the PR body. **Worktree trap, learned:** `plamotrack_test`
  migrated to a branch head makes `main`'s conftest downgrade explode — drop the
  DB first; the Cursor brief warns about it. No mutants in the harness (#86's
  file); five hand-mutant tuples with once-matching anchors are in the brief,
  queued for the fold-in with #109's and #111's. **Cursor brief for #113 is in
  this session's scratchpad** (`cursor-brief-113.md`), handed to the owner —
  round complete — GO, answered. Live and still true: **#86 at `dfa7f29` owes its Codex
  round** and gates #44/#77/#87/#90; #104/#98/#99 → 0.2.8; #110, #112 and #114
  unmilestoned. Dev servers may be running on :8000/:5173 (this branch).
- **Next:** clear of #86, 0.2.7 has only **#97** left (MCP `update_order` /
  `get_order` — reuse `OrderUpdate` so #111's `received_at` correction and any
  later fields flow in like `_KitPatch` does for kits; the line-set-replacement
  foot-gun is the design question on the issue). **#95 needs #86** (its importer
  half mirrors the arriving-receipt question), so 0.2.7's release gate is #86
  itself unless the owner defers #95. Clear-of-#86 beyond the milestone: the
  whole 0.2.8 list (#104 keyboard picker, #98, #99, #53, #54, #61, #63, #67);
  #114 is M5.1-shaped. Waiting on #86: #95, #110, #112, and the mutant fold-ins
  (#109's 17, #111's 6, #113's 8).
