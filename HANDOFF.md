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
  to the top of `.agents/handoff/2026-08.md` — plus `50f7c41` (#105). The only
  other branch is `fix/44-import-order-invariants` (PR #86, untouched, still the
  0.2.6 blocker). Live from the previous entry and
  still true: #86 gates #44/#77/#87/#90; **#104** is filed into 0.2.8; #97 → 0.2.7,
  #98/#99 → 0.2.8; a stray local `pr-102-review-ref` branch was already gone.
- **Next:** the previous entry's Next stands: **#49**
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

## 2026-08-18 — Claude Code (Opus 5) — #92 + #55 as one rule-1 sweep; PR #100 open

- **Done:** closed the write-surface divergence in both directions on
  `feat/92-55-write-surface-parity` (`9f4a269`, pushed). **PR #100 is open against
  `main`, CI green on all three jobs.** MCP gains `update_kit`, `list_retailers`,
  `create_retailer`, `update_retailer` and one catalog editor per table; REST gains
  `POST /catalog/{id}/adjust` plus a −/+ stepper on the inventory rows. 521 backend
  tests, 11 e2e, no migration. Filed the rest of the class as **#97** (`update_order`,
  `get_order`), **#98** (`create_kit`, the three catalog creates, `list_catalog`) and
  **#99** (`create_order`'s docstring names a `meta` resource that was never built).
  All three are **unmilestoned on purpose** — placing them is the owner's call.
- **Decisions:**
  - **Three catalog-edit tools, not one dispatching on `item_type`** — a deviation
    from what #92 proposed. `adjust_stock`, the analogy the issue reached for, takes
    no `item_type` at all, and REST's own shape here is three PATCH routes. One tool
    needs a patch model spanning all three tables' columns: a hand-maintained union
    #94 and #96 would each have to be added to twice. It also removes an edge —
    `ItemType.KIT` is a valid enum value naming no catalog table, so a dispatcher
    would `KeyError` into a 500. Named `update_catalog_*`, since "tool" is already
    taken inside an MCP client.
  - **`update_kit_status` kept, not renamed.** Removing a tool a client may have
    wired is a visible break; it is the documented status-only shortcut now, pinned
    by a test to the same service call so the two cannot drift into two
    implementations.
  - **Edit tools take a patch object, not one optional argument per field.** An MCP
    tool is a function signature, so the flat spelling cannot tell "leave the notes
    alone" from "erase the notes" — both arrive as `None`. Taking the REST route's
    own `*Update` schema keeps `model_fields_set`, so absent and null mean the same
    on both surfaces. `_KitPatch` subclasses `KitUpdate` and overrides only `status`,
    so #94's and #96's columns reach the tool with no second edit.
  - **The adjust route lives on `/catalog`,** not `/inventory/{type}/{id}` — the
    service resolves the id across the three tables itself, as the search does.
  - **First `data-testid` in the repo** (`stock-count`). The stepper made the "on
    hand" cell read `"0−+"`, breaking `happy-path.spec.ts`. `toContainText` on the
    cell is not a substitute: `"10"` contains `"0"`. Flagged in the PR for review.
- **State:** `main` untouched by the feature work — everything is on the branch and
  in PR #100. Seven mutants (naive-kwargs on each of the three patch paths,
  always-restamp, wrong `ItemType`, negated delta, dropped reason) were run **by
  hand** and all killed; they are deliberately **not** in `mutation_test.py`, which
  PR #86 rewrites. Worth adding there once #86 lands. `test_int4_bounds.py` no longer
  claims `adjust_stock` has no REST route and drives both doors.
- **Next:** #86 is still the blocker for 0.2.6 — all four of its remaining issues
  (#44, #77, #87, #90) live inside the files that PR rewrites, so nothing there is
  startable first. This branch was picked for touching **none** of #86's files, so
  the two should merge in either order. Remaining 0.2.7 work with no #86 overlap:
  #50 (board move ordering — worth landing before #94, which makes a lost update
  worse), #51 (dialog focus trap), #49 (retailer LIKE wildcards, but read #86's
  importer name-matching first — #49's point is making all three normalisations
  agree).

## 2026-08-18 — Claude Code (Opus 5) — #91 split into #92–#95; docs-only, no code touched

- **Done:** assessed #91 (dogfooding gaps in the MCP/UI write surface) and split it
  into four issues; **#91 is closed as split**, with a scoping comment answering its
  four open questions and a closing note mapping every finding to its issue.
  Two commits on `main`, both pushed: `5f249b3` widens the attribution rule to issue
  bodies and exempts the docs; `5f973b7` documents `--build` everywhere the packaged
  stack is started.
- **State:** **no application code changed, no migrations, no tests run** — there was
  nothing to run. `main` is at `5f973b7`. Working tree clean apart from this entry.
- **Next:** #92 is the cheap one and is not blocked by anything. #94 is now decided
  (see below) and unblocked too — nothing in this batch is waiting on a call.

### #96 (series) filed, #95 rewritten — from a read of the owner's other tracker

The owner's existing 73-kit collection lives in another tool; its schema was read
directly and compared against `kits`. Two real gaps, one non-gap, one dead end.

- **#96 — kits record no series.** `series` existed nowhere in this repo. Filed into
  0.2.7. **Single value, free text, like `grade` and `scale`** — the owner's tracker
  models it as a multi-select, but the single two-valued row there is a data-entry
  mistake, not a case to support, and a kit spanning two series gets a name covering
  both. Flexibility is the *requirement*: in the other tool an option must be
  predefined and its API can't add one, so an agent cannot record an unlisted series.
  Free text plus a distinct-values typeahead (the `CatalogItemPicker` select-or-create
  idiom) is the shape: writable by anyone, hard to near-miss by accident, no lookup
  table. Free text also **keeps §9.1 open** — an enum would settle the
  generic-vs-Gunpla taxonomy question by accident, since "series" is Gunpla-specific
  in a way "grade" is not.
- **#96 and #94 share a migration slot**, noted on both. Same table, same `spec.py`,
  same hand-curated `STARTER_SHEET_COLUMNS`, same kit form.
- **`grade` and `scale` already have the fragmentation exposure** `series` would
  introduce: `default_scale_for_grade` normalises with `.strip().upper()` only for its
  lookup and stores what was typed, and `list_kits(grade=…)` matches with `ilike`, so
  `HG` and `High Grade` are two grades today. Recorded inside #96 rather than filed
  separately because the same endpoint fixes all three — split it out if that stops
  being true.
- **#95 rewritten** as the order timeline. `shipped_at` is a nullable column **and a
  transition**: `KitStatus.IN_TRANSIT` exists and `ARRIVAL_ELIGIBLE` reads out of it,
  but **nothing in the codebase ever writes it** — a board drag is the only way in.
  Marking an order shipped should advance its kits, which makes the pipeline
  machine-driven end to end. Shipping applies **no stock**; `received_at` stays the
  sole "stock was applied" proxy (rule 2.1).
- **The pre-order distinction needs no schema at all.** It only matters while an order
  is pending, so there is nothing to persist, and `OrderItemRead.kits` already carries
  `KitRead.status` — the Orders page can tell a pending pre-order from a late order
  from the payload it already renders. Presentation-only. Accepted limit: a
  catalog-only order spawns no kits and so has no pre-order signal.
- **`Wishlist` status: declined, not deferred.** The other tracker has the stage and
  has never used it (0 of 73 rows), and the owner dropped it. Not filed, deliberately.

### Milestones reorganised — 0.2.7 is now the workflow release

Decided by the owner, 2026-08-18. **0.2.6 is "the importer is stable and usable",
not "the importer is finished"** — the test is whether a bug corrupts data silently,
not whether the feature is complete.

- **0.2.6** — #44 (PR #86), #77, **+#87**, **+#90**. The last two were unmilestoned;
  both are silent importer corruption (#90 writes an unresolved `catalog_ref_id` when
  a partial sheet omits `item_type`; #87 leaves stock unaccounted when a merge-import
  adds a catalog line to a received order), so both fail the usable test.
- **0.2.7** — the workflow release: #92–#95, plus **#55** (same rule-1 divergence as
  #92, opposite direction), **#49** (lives in `get_or_create_retailer`, next door to
  #92's retailer tools), **#50** (see below) and **#51** (same dialogs #93/#94 add
  fields to).
- **0.2.8** — new milestone, everything else: #53, #61, #63, #67, #54.

**#50 moved on severity, not theme.** It is filed low because a mis-ordered board
move is visible and correctable. #94 makes a transition stamp a build date, the
refetch corrects the column but does **not** un-stamp the date, and the stamp is
write-once-when-null. Land #50 with #94.

### #94's three implementation decisions, all recorded on the issue

1. **No backfill.** `build_completed_at` is not derived from `status_updated_at` for
   already-`complete` kits. A backfilled date is indistinguishable from an asserted
   one, and for a kit that went `complete` → `building` → `complete` the guess is
   wrong — the same shape as a fabricated conversion snapshot (rule 4). Nothing is
   lost: `status_updated_at` still holds what it held, so the owner has the same
   evidence and can decide what it means. **Consequence: the migration is purely
   additive, so #94 does not depend on #54**, which is why #54 sits in 0.2.8.
2. **Build dates stay out of `OrderKitDetails`.** A line edit echoes kit details back
   and `_update_line` reads a difference as an intentional restatement (#67). Putting
   build dates there would let a price typo correction revert a completion date set
   from MCP. Excluding them keeps #67 exactly as wide as it is today — which is why
   #67 is in 0.2.8 rather than travelling with #94.
3. Editability through UI, REST **and** MCP is a first-class requirement, not a
   backfill convenience. Stamp only when null, never clobber a user-set value.

### The split, and what each one actually costs

- **#92 — MCP write parity.** Retailers, catalog items, kit `rating`/`build_notes`.
  No schema change, no frontend, no new logic: `create_retailer`/`update_retailer`,
  `update_catalog_item` and `update_kit` all already exist with full field sets and
  are already on REST. This is a **rule-1 divergence**, not a missing feature —
  the MCP wrappers were simply never written. ~half a day.
- **#93 — backdatable `received_at`.** No migration; the column is already nullable
  `timestamptz` and the CSV archive already round-trips it. Two lines in
  `services/orders.py` stamp `now`. Note `receive_order` also stamps the kits it
  advances, so a backdated receipt has to backdate those or the problem just moves
  one table over.
- **#94 — kit build start/completion dates.** The only one needing a migration.
- **#95 — order shipped/dispatched milestone.** Filed so the split didn't drop it.

### #94 is DECIDED — two columns, dates owned by the user

**Settled by the owner, 2026-08-18. Do not reopen this without new information.**
Two nullable columns (`build_started_at`, `build_completed_at`) on `kits`, **not** a
`kit_status_events` history table. A history table drags the whole rule-9 surface
with it — natural key, re-import dedupe, `TABLE_SPECS` position, blank templates,
backfill migration — to answer stage-duration questions nobody has asked, and it
makes the two wanted dates something you reconstruct rather than something you set.

**The dates belong to the user, not to the state machine.** A transition stamps a
default; the stored value stays editable afterwards through the UI, REST *and* MCP.
That editability is a first-class requirement, not a backfill convenience — it is how
a collection migrated from another tool gets its real dates. A user-set date must
never be clobbered by a later status change, which falls out of "stamp only when
null".

**Two consequences accepted going in, both recorded on #94:**

1. Two columns measure **elapsed**, not **active**, time. A kit started in January,
   shelved three months and finished in June reads as a five-month build. Per-interval
   "hours at the bench" is the event table returning, and is out of scope. Do not
   treat the five-month build as a bug.
2. The shelved-build case has **no representation at all**. A paused/postponed status
   was proposed and **declined** — a stalled build sitting in `building` indefinitely
   is acceptable for a single-owner collection, and it ranks below the other gaps.
   Deliberately **not filed**, so its absence from the issue list is a decision rather
   than an oversight.

Whoever builds it: the cost is the sweep, not the migration. Kit status is written
from **three** places — `services/kits.py` `update_kit`, `services/orders.py`
`receive_order`, `services/portability/importing.py` — and they need one shared
derivation helper, with the importer explicitly **not** inventing timestamps (rule 10
by analogy). Also `STARTER_SHEET_COLUMNS` is hand-curated, not generated from the
table spec, so build dates have to be added there too or the one-file migration path
silently drops them — which is exactly the path someone moving off a spreadsheet uses.

### A doc defect that this log caused

`docker compose up -d --wait` without `--build` fails on a **first run**: `api` and
`migrate` name an `image:` tag alongside their build context, so `up` tries to
resolve `plamotrack-api:local` and no registry has it.

**This was already known — it is recorded at HANDOFF.md:616, from the #75/#76 release
gate.** That finding stayed in this file and never reached the docs a stranger reads,
so the broken command sat in README, AGENTS.md, the compose header, design notes §8
and twice in operations.md until it failed again on a real first install. AGENTS.md
was worse than silent: it asserted the command "builds on first run".

**The sweep rule applies to prose.** Recording a workaround here is not the same as
fixing the document that told someone to do the wrong thing. `5f973b7` fixed the four
sites the owner's README commit (`2b93747`) left behind.

**Tested afterwards, and the first explanation was too strong — then the second
one was too.** An isolated probe (a throwaway `image:` + `build:` service whose tag
exists in no registry) **built fine without `--build`** on this Mac. So the failure
is not a property of the compose file, and the docs no longer say it is.

It was then written up as *version*-dependent, which the evidence does not support
either: this Mac runs **OrbStack**, and its `docker compose` is OrbStack's own binary
(`~/.docker/cli-plugins/docker-compose` → `OrbStack.app/.../xbin/docker-compose`,
reporting v5.1.2, server `OperatingSystem: OrbStack`). The LXC runs the official
Docker packages. Engine, Compose build and Compose version all differ at once, so the
probe isolates **nothing** about which one matters. Recorded as "depends on the host".

The two hosts, now measured:

| Host | Compose | Engine | Bare `up -d --wait` |
| --- | --- | --- | --- |
| LXC, official Docker packages | **v5.4.0** | 29.7.2, Debian 13 (trixie) | **fails** |
| Mac, OrbStack | v5.1.2 | 29.4.0, OrbStack | builds |

**This kills the "newer Compose builds it" reading — the failing host is on the newer
Compose.** So the live explanations are that OrbStack's compose binary diverges from
upstream, or that upstream tightened this between v5.1.2 and v5.4.0. Do not tell
anyone to upgrade Compose; that is the direction that fails.

**The probe ran on the LXC and refuted the mechanism, not just the attribution.**
Both cases succeeded there, exit 0. Case A — one service, `image:` + `build:`, image
removed first, no `pull_policy` — printed `Image plamoprobe-nosuchimage:local Pulling`
for 2.2s, failed the pull, and **fell back to building**. So on the very host where
plamotrack fails, a named-but-missing image is *not* a hard failure, and
`pull_policy: build` is not needed to make it build. Both of the fixes under
discussion were aimed at a mechanism that host does not exhibit.

**What is left standing:** a fresh LXC did fail `docker compose up -d --wait` on
*this repo* with a can't-find-the-images error, and `--build` fixed it. That
observation is solid. Every explanation offered for it so far is not.

**Leading suspect, untested:** the probe had **one** build service. This file has
three, and `api` and `migrate` **share the tag `plamotrack-api:local`** while `web`
has its own. Two services claiming one image tag is the structural feature the probe
had no equivalent of. `--wait` and the `service_completed_successfully` dependency are
the other untested differences.

**The definitive test needs no probe at all**: on the LXC, `docker compose down`, then
`docker image rm -f plamotrack-api:local plamotrack-web:local`, then
`docker compose up -d --wait` with no `--build`. That is the real stack in the real
failing state, with zero fidelity questions. `down` without `-v` keeps the volume, and
the images rebuild, so the only cost is a couple of minutes of downtime on a live
instance — the owner's call, not something to run unasked.

**Sweep lesson:** the first pass missed a sixth site because the grep required the
word `compose`, and the Layout block writes `` `up -d --wait` `` bare. Grep the
distinctive fragment, not the comfortable full phrase.

### Operational note: `gh issue create` was unusable, `gh api` worked

GitHub was half-down. The git protocol and REST v3 were fine; **GraphQL was 503**, and
`gh issue create` / `gh issue view` go through GraphQL. Filing worked via
`gh api repos/OWNER/REPO/issues -X POST -F body=@file -f 'labels[]=…'`. Worth knowing
next time GitHub is flaky. A 503 on a POST can still have created the record — check
before retrying; one of the four 503'd and had *not* been created.

