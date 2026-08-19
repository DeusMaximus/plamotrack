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

## 2026-08-19 — Claude Code (Fable 5) — #86 pre-round: `main` merged in, harness false-kill fixed, one defect closed

- **Done:** owner asked for a same-family pre-round on **#86** to make the next
  Codex round cheaper (not to replace it). Branch head is now **`e8cd2b3`**, pushed,
  comment posted at that head. (1) `main` merged forward (`aefaecc`, 31 commits,
  clean). (2) **The mutation harness reported 13 mutants killed that never ran**
  (`fd8d195`): pytest exits 5 when `-k` deselects everything, the harness read any
  non-zero as RED, and the merge of `main` at `5c0963b` had unioned the case sets
  while keeping this branch's two target files — every `cell-` case selected zero
  tests. `TEST_FILES` is now all three files; exit 5 reports `NONE` and counts as a
  survivor. Re-run 56/56, then 59/59 with the new cases. (3) **One product defect**
  (`43b947c`, `e8cd2b3`): a mistyped `order_item_id` on one kit in a pristine full
  archive → 200, kit detached (#82's dangling-optional-ref rule nulls it) and a
  replacement spawned (the line's restated quantity authorised it). Same cell in
  `kits.csv` alone was already 409. `_refuse_unresolved_overwrite` in `_classify`:
  an unresolvable optional REF may not clear a stored non-null link; #82's test had
  driven only the create. Also speaks first for a mistyped `catalog_ref_id` on a
  stored catalog line. (4) The arriving-receipt message offered "state the on-hand
  quantity in consumables.csv" as a remedy; the check never reads catalog files, so
  it isn't one (`7c0dc55`: message, doc bullets, test). (5) Docs note on why an
  operator's own archive can hit the over-supply refusal (`0e21381`).
- **Decisions:** mine, flagged as such on the PR — **not** changed: an *unchanged*
  line row (every full archive has one) authorises the fan-out to delete an
  incumbent / spawn a replacement on a kit move, while the same move with the row
  absent is refused. Documented and tested as intended; raised as design question A
  with the one-condition alternative (authority = the upload *writes* the quantity).
  Design question B: a pre-#44 drifted instance's archive is refused on restore in
  both modes; SQL to find drift is in the comment — worth a 0.2.6 release-note line
  and a run on the LXC before upgrading. Structural read: the rules share one
  post-write view; the CREATE-count sum is written twice (P3).
- **State:** 641 backend, ruff clean, 59/59 mutants, frontend build/lint/vitest
  clean; e2e not run locally (CI). No migration. `main` is `2772cb1` plus this
  entry. `_refuse_unresolved_overwrite` is **new code with no independent eye** —
  named as the place to push in the comment. Codex budget resets Thursday evening
  (owner); the round is still owed at `e8cd2b3`. Two stale worktrees exist on this
  Mac (`/private/tmp/plamotrack-pr100`, `/private/tmp/plamotrack-pr108-main`), not
  this session's, left alone. Live and still true: #86 gates #44/#77/#87/#90; #107
  → 0.2.7; #104/#98/#99 → 0.2.8.
- **Next:** Codex round on #86 at `e8cd2b3` — brief it with the comment's "where to
  push next" and question A. Then the previous entry's 0.2.7 list stands: #107,
  #93, #95, #94 + #96.

## 2026-08-19 — Claude Code (Fable 5) — #106 and #108 merged (#49 closed); #107 filed → 0.2.7

- **Done:** **#106 merged** (`eb3a430`) — design notes caught up on the write gate,
  export snapshot, #94/#96 decisions and the hardening milestones. **#49 closed —
  PR #108 squash-merged as `7a6e1e1`** after one Cursor review round (GO with two
  P3s, both taken before merge) — fold *both* sides of
  the predicate in Postgres (`func.lower(col) == func.lower(input)`; the Python
  fold differs on Turkish `İ`, so the reviewed head missed an exact stored
  spelling — a regression against ILIKE), and §12.4 tightened so the typeahead
  is not read as the natural-key check. Reply posted at that head.
  `get_or_create_retailer` and `list_kits(grade=)` compare `lower()` for equality
  instead of ILIKE — the importer's `_norm_name` rule, so all three surfaces
  agree. Found on the way: ILIKE read `\` as its escape, so a shop with a
  backslash in its name could never be reused. Browser: ref-guard + pending state
  on the inline "+ retailer" (double-click posted twice); `CatalogItemPicker`
  search query `staleTime: 0` (a de-dup gate must never answer from cache).
  `docs/design.md` §12.4 now states the natural key precisely. **#107 filed and
  milestoned 0.2.7** (owner's call, on Cursor's suggestion): the create/rename
  paths that apply *no* name predicate —
  `create_retailer`, `update_retailer`, `new_item`, REST catalog creates —
  can make the importer's natural key ambiguous; verified against the API first.
- **Decisions:** equality, not an escaped pattern (the backslash case is why the
  shape matters). `staleTime: 0` over per-page invalidation — closes the class,
  including rows an MCP agent adds out of band; noted in the PR for the owner to
  disagree with. #107 not folded in: different root cause, changes status codes.
- **State:** backend 556 (534 + 22 new in `tests/test_name_matching.py`), ruff
  clean; e2e 19 (17 + 2 in `e2e/catalog-dedup.spec.ts`), vitest green, build +
  oxlint clean. **e2e verified against a database migrated from empty; every
  table empty afterwards** — recipe now in `.agents/testing-and-review.md`. No
  migration. Negative controls: 11/19 backend red on unfixed `main`; five
  single-site mutants each killed by the tests aimed at that site; both e2e red
  on the unfixed UI, both timing-pinned (`page.route` hold; `page.clock`
  frozen). `main` is `7a6e1e1` plus this entry. The only branch is
  `fix/44-import-order-invariants` (PR #86, untouched, still the 0.2.6 blocker).
  A stale worktree `/private/tmp/plamotrack-pr100` exists on this Mac from an
  earlier session — not this one's, left alone. Live from before and still true:
  #86 gates #44/#77/#87/#90; #104 in 0.2.8; #97 → 0.2.7; #98/#99 → 0.2.8.
- **Next:** 0.2.7's remaining items clear of #86 are **#107** (the rest of rule 3
  on the names #49 just defined — option 1 on the issue, service-layer 409, is the
  recommendation), **#93** (backdatable `received_at` — note
  `receive_order` also stamps the kits it advances, so a backdated receipt has to
  backdate those), **#95**, and **#94 + #96** (share a migration; decisions are
  in §3.1). #86 still wants a fresh review round before anything in 0.2.6 moves.

## 2026-08-19 — Claude Code (Fable 5) — HANDOFF.md capped at five; `.agents/` created; #105 merged

- **Done:** the hand-off log and `AGENTS.md` were costing ~45k tokens per session
  start (181 KB / 43 entries + 25 KB), a fifth of a 256K context before any code.
  **Step 1 on `main` (`07f99e1`):** `HANDOFF.md` keeps the five most recent
  entries; the other 38 moved verbatim to `.agents/handoff/2026-08.md` (verified
  byte-identical on both sides of the split). The header carries the rotation
  rule, a ~60-line entry cap, "the newest entry is self-sufficient about live
  state", and the grep recipe. `AGENTS.md` protocol/layout and `docs/design.md`'s
  pointer updated. **Step 2 is PR #105, merged as `50f7c41`** after one Copilot
  round (one pointer-text nit, fixed as a class of three): `AGENTS.md` trimmed to rules with pointers (25.2 → 22.4 KB);
  `.agents/lessons.md` (case histories harvested from `AGENTS.md` and all 43
  entries, append-only, stable headings); `.agents/testing-and-review.md`
  (procedure, edited in place: suites, regression checklist, concurrency
  patterns, mutation harness, CI, reviewer routing, answering a review, release
  gate). `.agents/README.md` describes the directory.
- **Decisions (owner's, 2026-08-19):** `.agents/` not `docs/` — `docs/` is
  user-facing; five entries; lessons live beside the archive; a *separate*
  procedure doc because procedure is overwritten and lessons are appended, and
  one file would refill the way `HANDOFF.md` did. Mine: no harness-specific
  rule-loading (`.cursor/rules`, Claude `@import`, nested `AGENTS.md`) — plain
  links plus "read X before Y" work identically in all three harnesses and one
  copy can't drift. `AGENTS.md` still holds ~86 lines of architecture rules;
  cutting those further is the owner's call, not done.
- **State:** no application code changed, no tests run. `main` is `07f99e1` plus
  this entry — the **first rotation**, which moved the 2026-08-17 #82/#88 entry
  to the top of `.agents/handoff/2026-08.md` — plus `50f7c41` (#105). **PR #106
  open** (`docs/design-catch-up`, docs only): `docs/design.md` catches up on the
  write gate (§3.9), the export snapshot (§12.1/12.3), the #94/#96 decisions
  (§3.1) and the hardening milestones (§11) — none of it touched by #49, but two
  of them were owner decisions living only on issues and in the archive. The only
  other branch is `fix/44-import-order-invariants` (PR #86, untouched, still the
  0.2.6 blocker). Live from the previous entry and
  still true: #86 gates #44/#77/#87/#90; **#104** is filed into 0.2.8; #97 → 0.2.7,
  #98/#99 → 0.2.8; a stray local `pr-102-review-ref` branch was already gone.
- **Next:** merge **#106**, then the previous entry's Next stands: **#49**
  (retailer LIKE wildcards) is the remaining 0.2.7 item clear of #86 — read #86's
  importer name-matching first, since #49's point is making all three
  normalisations agree. From now on, an entry ends by rotating if it made six.

## 2026-08-19 — Claude Code (Opus 5) — #51 merged; backlog triaged; #104 filed

- **Done:** **#51 merged** (PR #103, squashed as `278f395`) — dialogs and the
  order disclosure are keyboard-operable. `main` carries 534 backend tests, 100
  frontend unit tests and 17 e2e. All three untriaged issues from the previous
  session were milestoned: **#97 → 0.2.7** (after #93/#95, which add fields its
  tool would otherwise be widened for), **#98 and #99 → 0.2.8**, with a note on
  #98 that #99 folds into it. **#104 filed** into 0.2.8, found while fixing #51.
- **Decisions:**
  - **The focus trap is hand-written in `Modal.tsx`,** not Radix or Headless UI.
    That was #51's own argument and it held: the whole thing is a selector list
    and about thirty lines. Revisit only as a deliberate dependency decision.
  - **The dialog is portalled to `<body>`.** `inert` goes on `#root`, and a
    dialog rendered inside the subtree it inerts would disable itself. All seven
    `Modal` call sites put the form *inside* the modal, so nothing moved out of a
    form.
  - **Initial focus lands on the dialog, not its first control** — the close
    button is first in DOM order, and focusing it announces "Close" as the first
    thing a screen-reader user hears about a form they just opened.
  - **A `MutationObserver` recaptures focus**, guarded on
    `activeElement === document.body`, watching `childList` plus
    `attributeFilter: ["disabled", "hidden"]`. Every entry there is measured, not
    reasoned: removing *or disabling* the focused node drops focus to `<body>`
    and fires no `blur` and no `focusout`, so nothing event-driven sees it;
    `inert` and `display: none` leave `activeElement` on the node and so can
    never satisfy the guard. `hidden` is in the filter and is **not** covered by
    a test — nothing in the app sets it on a focused node. Declared, not implied.
  - **Milestone triage used the milestones own criteria**, not feel: 0.2.8 is
    defined as items neither corruption paths nor coupled to the workflow work,
    which is what put #97 in 0.2.7 and the rest in 0.2.8.
- **State:** no migrations in any of this. `fix/44-import-order-invariants`
  (PR #86) remains the only other branch and is untouched — every branch this
  session was picked for not overlapping it.
- **Next:** #86 still gates all of 0.2.6 (#44, #77, #87, #90 all live in the
  files it rewrites). The remaining 0.2.7 item clear of it is **#49** (retailer
  LIKE wildcards) — read #86's importer name-matching first, since the point of
  #49 is making all three normalisations agree.

### The reviews are finding things the tests do not — five for five

Three review rounds on #103 alone, and every finding was real. Two changed the
code rather than the tests, and neither would have been caught by anything here:

- **A focus trap that lets focus reach `<body>` is not trapping.** Tabbing off
  the picker input lands on a result button that then unmounts underneath — an
  ordinary keyboard path, not a contrivance. Filed as **#104**, because the
  picker's own defect is that a keyboard cannot select a result at all.
- **The suite passed against an observer with no guard**, i.e. one that steals
  focus on every mutation and makes the forms untypeable. Every assertion was
  `inDialog`, and focus already inside the dialog satisfies that. The lesson
  generalises past this file: **an assertion about containment cannot see a
  mechanism that moves things within the container.** Assert the named control.

Two of the three test-writing mistakes this session were mine and were the same
mistake — a green run that came from the environment rather than the code:

- The disclosure test read whichever order was on the page. Fine against a dev
  database with twenty; nothing to find in CI, which starts empty. **Verify e2e
  against a database migrated from empty** — stand one up, point the API at it,
  and check the tables are empty again afterwards. It has now caught two of these.
- `--repeat-each` is not a way to measure flakiness: it reuses one module load,
  so every repeat shares the fixture name and stacks duplicates.

And one about the harness: `mutation_test.py`-style scripting **races Vite's
recompile** on frontend files. A mutant reported as surviving needs a manual
re-run before it is believed. The backend equivalent has no such race.

## 2026-08-18 — Claude Code (Opus 5) — #50 and the #100 review follow-ups merged

- **Done:** three PRs merged to `main`, all squashed, all reviewed by Cursor Grok
  4.6 before merge. **#100** (#92 + #55, the rule-1 write-surface sweep), **#101**
  (#50, board move ordering), **#102** (the three P3s from #100's review). `main`
  is at `2dba040`: 534 backend tests, 100 frontend unit tests, 11 e2e. Issues #92,
  #55 and #50 are closed. **#97, #98, #99** were filed from the #100 sweep and are
  **unmilestoned on purpose** — placing them is the owner's call.
- **Decisions:**
  - **Board move serialisation** is a TanStack `scope`, board-wide, in a new
    `frontend/src/lib/kitStatusMutation.ts`. The policy left `BoardPage` so it
    could be tested at all — see below. First options-factory module in this repo.
  - **Boolean refusal lives on the `Annotated` aliases** in
    `backend/app/schemas/numeric.py`, not on any route. A `BeforeValidator`
    rejecting only `bool`, deliberately not `strict=True`, which would also refuse
    `"5"`. **It must be ordered after `Field(...)`**: first, it wraps a bare `int`
    and the constraints serialize as raw `ge`/`le`, so the bound silently
    disappears from the published OpenAPI while still being enforced at runtime.
    The int4 contract test caught that; the ordering now carries a comment.
  - **`Rating` is an alias too**, in the same file, even though 1–5 is a product
    rule rather than an int4 bound. Being declared anywhere else is exactly how it
    became the one write integer that still took a boolean.
  - **`data-testid="stock-count"`** is the first test id in the repo (#100).
- **State:** no migrations anywhere in this batch. `fix/44-import-order-invariants`
  (PR #86) is untouched — all three branches were chosen for not overlapping it.
  A stray local branch `pr-102-review-ref` exists from Cursor's review; its content
  is in `main` and it can be deleted.
- **Next:** #86 is still the blocker for 0.2.6 — #44, #77, #87 and #90 all live
  inside the files it rewrites. Remaining 0.2.7 work clear of it: **#51** (dialog
  focus trap) and **#49** (retailer LIKE wildcards — read #86's importer
  name-matching first, since #49's point is making all three normalisations agree).

### Two things worth carrying forward, both learned the expensive way

- **An e2e test could not tell the #50 fix from the #50 defect.** dnd-kit's
  `DragOverlay` swallows a `pointerdown` that arrives before the previous drop
  animation finishes, so the second drag never started — one request, in order,
  which is exactly what correct serialisation looks like. It was also
  observer-sensitive: a `console.log` in the drag handlers flipped it from failing
  to passing, and it measured 1 pass in 5 in fresh processes. Deleted rather than
  shipped, and the policy was extracted so the mutation could be driven directly.
  **`--repeat-each` is not a way to measure flakiness here** — it reuses one module
  load, so every repeat shares the fixture name and stacks duplicates. That cost a
  round of wrong numbers before the real one.
- **Both reviews found a partial sweep, in branches whose whole point was
  sweeping.** #101's rollback justification was self-contradictory — `scope` pauses
  `mutationFn`, not `onMutate`, so a failed move overwrote a later queued move's
  optimistic state, and the branch's own test asserted the behaviour that
  disproved the comment. #102 fixed three of the four integer families and missed
  `rating`, which has its own bounds and so never appeared in the contract test.
  Both suites were green over the defect. The axis that keeps going unvaried is not
  values — it is *which of several equivalent places the fix actually reached*, so
  mutate the places one at a time, not the fix as a whole.
