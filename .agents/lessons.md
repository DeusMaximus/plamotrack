# Lessons — the case histories behind the rules

What a defect cost, what a test missed and why, what a review round found that a
green suite did not. Each entry is the short form with the issue and PR numbers; the
full account is in the hand-off entry it points at (`.agents/handoff/YYYY-MM.md`,
found with `grep -n '^## YYYY-MM-DD'`). `AGENTS.md` states the rules these produced;
`testing-and-review.md` states the procedure. This file is why.

**Append-only.** Add under the heading it belongs to, keep headings stable so links
from `AGENTS.md` and PR threads keep resolving, and do not rewrite an entry when a
later one supersedes it — add the later one and say so.

Contents: [Sweeping the class](#sweeping-the-class) ·
[The value axis](#the-value-axis) · [The state axis](#the-state-axis) ·
[Green for the wrong reason](#green-for-the-wrong-reason) ·
[Concurrency tests](#concurrency-tests) · [Mutation testing](#mutation-testing) ·
[Review](#review) · [Architecture](#architecture) · [Tooling and process](#tooling-and-process)

---

## Sweeping the class

### The money chain: four branches for one rule
#3 (an order-line edit discarding its conversion snapshot) was one rule-4 defect.
Fixing it exposed #12 (a CSV import relabelling that same snapshot), which exposed
#6 (minor units read off the runtime instead of ISO 4217), which exposed #19
(`tools.unit_cost_reference` — a scaled decimal with no currency column at all).
Four branches, four reviews and two releases for four instances of one rule applied
unevenly, all of which one pass over the paths touching money would have found at
the start. This is why `AGENTS.md` says to name the rule and enumerate its paths
before fixing the instance. → 2026-08-10 (#3, #12, #6), 2026-08-11 (#19)

### The sweep rule's first outing narrowed review; it did not replace it
On #19 the sweep found three instances the issue never mentioned (a select-or-create
path building a `Tool` with no currency; `_apply_money_alternates` scaling by a
column tools don't have; pair handling hardcoded to `order_items`). It did not find
the two Copilot then found — one pre-existing, one introduced by the fix. Keep both
gates. → 2026-08-11 (#19, PR #32)

### A sweep that claims to be systematic owes an answer for every writer
#74's JSON-schema contract test walked `app.schemas`, so an MCP tool — a function
signature, not a request model — was invisible to it, and `apply_upgrade` answered
422 on REST and 409 on MCP for the same value. This repo has three writers (UI, REST,
MCP) and an importer; a sweep over one of them is not a sweep. The same shape on
#74's arithmetic: schemas, MCP, and *derived* values (a legal input scaled or summed
out of int4) are three routes, and a fix that stops at the schemas passes locally and
gets a round-two review. → 2026-08-16 (#74), 2026-08-15 (triage)

### The axis that keeps going unvaried is which of several equivalent places the fix reached
#101's rollback comment was self-contradictory (`scope` pauses `mutationFn`, not
`onMutate`) and its own test asserted the behaviour that disproved it. #102 fixed
three of four integer families and missed `rating`, which had its own bounds and so
never appeared in the contract test. Both suites were green over the defect. When a
fix lands in several places, mutate the places one at a time, not the fix as a
whole. → 2026-08-18 (#100–#102)

### The sweep rule applies to prose
The `--build` requirement was recorded in the hand-off log from the v0.2.5 release
gate and never reached the documents a stranger reads, so the broken command sat in
README, AGENTS.md, the compose header, design notes §8 and twice in operations.md
until it failed again on a real first install. Recording a workaround in the log is
not fixing the document that told someone to do the wrong thing. The first sweep
then missed a sixth site because the grep required the word `compose` and one site
wrote `` `up -d --wait` `` bare — grep the distinctive fragment, not the comfortable
full phrase. → 2026-08-18 (#91 entry, "A doc defect that this log caused")

---

## The value axis

Four regression suites were written for a known defect, reviewed, run against the
unfixed code, and still missed something. Each failed differently, and together they
are why `AGENTS.md` says to enumerate what a field can hold before writing assertions.

### #65 seeded a quantity-one kit
The defect was one line's kits being flattened onto each other, which a single kit
cannot express. The test drove the exact code path and proved nothing. Also: the
interesting case for a "form doesn't lose data" test is not the empty cache, it is
the confidently wrong one. → 2026-08-11 (#65, PR #66)

### #66's warm-cache detector was timing-dependent
It passed against the broken code because on localhost the refetch beat the
assertion; only stalling the request with `page.route` made the stale window
certain. Same trap as #37's flaky detector, second time that month. If anyone
"simplifies" the hold out of `order-lossless.spec.ts`, the test goes green and stops
meaning anything. → 2026-08-11 (#66)

### #69 compared a field where both sides already agreed
Both sides held the same non-null value, so the derivation that caused the defect
was a no-op. `_update_line` resolved a null scale to the grade default *before*
comparing, so `"1/144" != None` read as an edit and a price-only change rewrote
every kit on the line. The comparison was exercised only where it could not be
wrong. → 2026-08-11 (#69, PR #70)

### #46 held both rows in the same resolution state
`_claim_identity` claimed the *resolved target*; the duplicate-id matrix drove "id
absent from the DB" and "id present" but never two rows resolving *differently* —
one natural-matching, one creating. That state wrote an order against the wrong
retailer, silently, at 200. The original matrix passes untouched with
`_claim_source_id` deleted; that is the measurement of its gap. Found by external
review. → 2026-08-16 (#46)

### #43's neighbour matrix
The starter sheet reads `quantity` down two branches, chosen by whether the row
names a retailer. The ceiling matrix varied that cell; the invalid-value matrix
immediately above it in the same file drove `0`, `-2`, `1.5`, `many` with the cell
blank only. Values and state were both in the suite, on adjacent tests, and neither
crossed — so `quantity: 0` on a retailer-backed row planned as a clean create and
500'd at flush. When one matrix in a file varies a state axis, every matrix over the
same field owes a reason why it doesn't. → 2026-08-15 (#43, PR #76)

### A shared invariant covering one end of a range is two invariants
`require_line_quantity` checked `> MAX` only; the retailer-free branch refused zero
through its own hand-written `< 1`. REST and MCP got the floor from `Field(gt=0)`,
but the importer builds models directly and never constructs `OrderItemCreate`. The
half that isn't shared is the half that drifts. → 2026-08-15 (#76 round 2)

---

### An invisible codepoint is a value too

KitsPage's elapsed cell spelled "3 d" with U+00A0 before the *d* — the only
NBSP in the frontend — and the first catalogue transcription of it flattened
the byte to a plain space. Every suite was green over the difference; it
surfaced only because an exact-match edit refused to find the line it was
aimed at. When extracting strings, byte-compare the value against its source
(`od -c`), sweep for the class rather than the instance (`grep -rP '\xa0'`),
and pin the result with explicit `\u00a0` escapes — a literal NBSP typed into
a test file proved unreliable in authoring, arriving sometimes as a space and
sometimes not. → PRs #164, #165.

## The state axis

The row's state decides whether the field is even present to be wrong. Twenty
values inside one action say nothing about the actions never entered.

### #41: every stability test drove a create, and `changes` is empty on a create
The leak put a minted uuid in a row's `changes` list. The id field's value space was
swept properly — absent column, blank cell, sheet-supplied, conjured stub — and every
case ran through a create, so the field could not appear in any test in the suite.
It was latent in the previous fingerprint too and the rewrite inherited it unseen.
No additional *value* would have helped; the axis never varied was the row's action.
Found by external review. → 2026-08-13 (#41, PR #72)

### #42: seven cases over the thing inside the container, none over the container
Every manifest case wrote its `tables` block inside a JSON object, so a manifest of
`[]` was an `AttributeError` 500 no case could reach. Its sibling drove one
member-decompression failure (a bad CRC) and missed the other two the same `except`
was meant to cover. Both found by external review. → 2026-08-15 (#42, PR #75)

### #76: an over-ceiling row matched to an existing line is an update, not an error
The ceiling check had to sit after `_parse_row` in the main pass rather than inside
`_plan_spawns` — a check on the fan-out alone would never see a catalog line or an
update that supplies its own kits. The test asserts `['update'] == ['error']` on
unfixed code. → 2026-08-15 (#76)

### #89: the mode axis pinned separately
`_classify` never runs under `replace_all` and returns SKIP before keep-stored under
`add_only`, so "correct in merge" said nothing about the other two modes. Each got
its own case. → 2026-08-17 (#89)

---

## Green for the wrong reason

### A red test proves *something* refused the input, not that the rule under test did
Three separate guards on #86 turned out to be covered by a neighbouring one, and in
each case the test that "covered" the rule stayed green when the rule was deleted.
Mutate the specific rule; if it survives, find the input where only that rule can
decide. → 2026-08-17 (#86, "Six things worth carrying")

### An edit that never applied, asserted as landed
Round 1 of #129's review added a fourth catalog type to every per-type parametrize
list. One of those edits — the two matrices in `test_write_surface_parity.py` — was
a scripted `.replace()` whose anchor did not match, so it silently changed nothing.
The suite was run afterwards and was green, which is exactly what a *missing*
stricter test also looks like, and the PR body then claimed the file had a fourth
case. Codex found it in round 2 the only way it could be found: `ItemType.DISPLAY`
→ `ItemType.TOOL` in the display MCP tool survived both suites at 31/31.

Two rules out of it. **A green run never confirms an edit whose purpose is to make
a suite stricter** — the new case has to be seen failing, or seen collected
(`pytest --collect-only -k <id>`), before it is claimed. **A scripted edit reports
whether it matched**: `assert s.count(old) == 1` before replacing, which the
mutation harness has always done with its anchors and ad-hoc edit scripts had not.
→ 2026-08-21 (#129 round 2)

### A field name found in a SQL dump
An MCP test asserted `"unit_price_minor" in str(error)`. Without the bound the call
still raised `ToolError` — the value reached Postgres, and SQLAlchemy stringified the
whole `INSERT` into the message, column names included. Assert the layer that spoke
(Pydantic's phrasing, and no `sqlalchemy` in the message), not a substring both
layers happen to contain. → 2026-08-16 (#74)

### A guard whose outcome another guard already covered
The `adjust_stock` delta bound never changed *whether* the call failed — any delta
past int4 makes the sum past int4 too. What the bound buys is the error *class*, so
the test asserts `InvalidInputError` against the ceiling's `ConflictError`, at the
service, where the two are distinguishable. → 2026-08-16 (#74)

### An empty parametrize is a skip, not a failure
`test_cell_semantics.py` enumerated its own subject — every NOT NULL column a sheet
may leave blank — by calling `_column_is_nullable`, the function under test. Mutating
it to `return True` emptied the list, `parametrize` over an empty list *skips*, and
the whole matrix silently stopped existing while the run stayed green with the rule
deleted. Worse than a test that asserts the wrong thing: this one stopped running and
reported nothing, and a skipped test looks like a pass in a `-q` summary. A test that
derives its subject from the code it tests can be disarmed rather than broken; read
the enumeration from the schema, the fixtures, or a literal list. → 2026-08-17 (#89)

### An assertion about containment cannot see a mechanism that moves things within the container
#103's suite passed against a focus observer with no guard — one that steals focus
on every mutation and makes the forms untypeable — because every assertion was
`inDialog`, and focus already inside the dialog satisfies that. Assert the named
control. → 2026-08-19 (#51, PR #103)

### A green run that came from the environment rather than the code
The disclosure test read whichever order was on the page — fine against a dev
database with twenty, nothing to find in CI, which starts empty. Verify e2e against a
database migrated from empty; it has now caught two of these. → 2026-08-19 (#103)

### A test that names the fix's new symbol cannot be run against the code without it
#75's budget tests first went red only on `AttributeError: no MAX_EXPANDED_BYTES`;
#76's referenced `MAX_LINE_QUANTITY`, so the module failed to *import* and every test
in the file errored — strictly worse, since it masks the file. Size and assert off
literals, or shim the name alone into the old tree. → 2026-08-15 (#75, #76)

### Check *which* tests go red, and why each one does
Three tests in #73 were false detectors: two errored for unrelated reasons (a
required `category` left blank; a kit line short of `kit_name`), and the third was
a matrix written as a unit test of `require_int4` that never entered the importer.
Every detector now asserts the error names the column under test. → 2026-08-14 (#40, PR #73)

The same check on #49 found a case that was green on both sides for a reason worth
knowing: `_` in ILIKE matches exactly one character, so `_` against a sixteen-character
decoy retailer creates a new row on the unfixed code too. The value was right and the
seeded *state* made it inert; a one-character decoy is what turned it into a detector.
→ 2026-08-19 (#49, PR #108)

### Sentinel collision
`None` meant both "parse failed" and "the document was JSON null", so the one
non-object manifest shape that needed the warning was the one that skipped it — a
defect *in the fix for round 1*. Don't reuse a value that is also a legitimate parse
result as an error sentinel. → 2026-08-15 (#75 round 2)

### Restructuring for a new check silently dropped an old one
Pulling `json.loads` out of `_read_manifest(json.loads(...))` so the result could be
`isinstance`-checked moved `_read_manifest` out from under its `except`, and
`ValidationError` (a `ValueError`) stopped being caught for free. It shipped through
a whole review round unnoticed; nothing asserted the *old* behaviour. → 2026-08-15 (#75 round 3)

### The fix itself broke a case, in a file with no tests
The #6 rewrite scaled by moving the decimal point, which fixed the float-rounding
mismatch — and its regex accepted only plain decimals, so `"1e2"` (which
`<input type="number">` passes through verbatim, and which `Decimal` and the
replaced `parseFloat` both read as 100) fell through to the zero returned for
unparseable input. Non-empty field, `required` satisfied, unit price saved as 0,
silently. Caught by review; `format.ts` had no tests. The shared money fixture is
also the check on the fix. → 2026-08-10 (#6, PR #16, PR #18)

### A locale-dependent assertion is green only where the runner happens to live
`toContain("1.234")` against `Intl.NumberFormat(undefined, …)` is `1,234 IQD` in
de-DE. Green on CI because the runner is en_US. Compare against a formatter handed
the same digit count, and verify under more than one locale. → 2026-08-10 (PR #18)

---

## Concurrency tests

### Repeat the race and assert the end state where pinning is impossible
The first race test for #37 caught the unlocked code 2 runs in 8 — a detector that
would read green forever after. Forcing the interleaving there means pausing the
delete while holding `FOR UPDATE`, at which point the concurrent apply blocks on
that lock and the test deadlocks instead of asserting. Ten repeats: 6/6 against
broken, stable against fixed, under two seconds. → 2026-08-11 (#37)

### A pinned barrier is safe only when the thing under test holds one lock and always releases it
#36's tests use a third transaction holding `FOR UPDATE` on one row as the barrier;
writers park on it, so the test controls what has committed before they wake. That
cannot be half of a cycle *because* the gate is a single lock. The #37 warning
stands for barriers held inside the code under test. → 2026-08-11 (#36)

### Forced-interleaving tests deadlock under the write gate
All five race tests written before the gate awaited their racing request *inline*
inside a patched `plan_import`, while the apply held the lock — the test waited on
itself, confirmed via `pg_stat_activity` (`wait_event='advisory'`). Any race test
here launches the racer as a task and awaits it after the apply. → 2026-08-15 (#80)

### Sleeping to coordinate a race proves nothing, and the obvious fix was worse
`asyncio.sleep(0.05)` creates an opportunity, not an occurrence. Signalling from a
wrapper around the racer's `acquire_write_gate` released the apply before the racer
had *done* anything — measured: `2 passed` against an `apply_import` with the gate
commented out. `_race_after_planning` now waits for the racer finishing or Postgres
reporting it parked on the advisory lock, and raises if neither happens. → 2026-08-15 (#80)

### Inline-awaiting a racer is right for an export and wrong for a write
An export holds no gate and no row locks, so its racer completes immediately and an
inline `await` is exactly deterministic. That is specific to row writes — a
`TRUNCATE` racer wants ACCESS EXCLUSIVE and queues behind the export's ACCESS SHARE.
→ 2026-08-16 (#48)

### `NullPool` hides a whole configuration from the suite
conftest disables pooling, so nothing else in-tree can observe a connection
characteristic leaking back into the pool — which is what every real deployment
runs. `test_the_snapshot_does_not_follow_the_connection_back_into_the_pool` builds
its own `pool_size=1` engine. Any future per-connection setting owes the same test.
→ 2026-08-16 (#48)

---

## Mutation testing

### A mutant that does not change behaviour is a green that means nothing
Two were inert — a renamed dict key that still hashed the same data, and a change
another branch of the same function compensated for. Check what the mutated source
actually does before trusting the result. → 2026-08-17 (#86)

### Removing an unreachable guard is not the same risk as relying on unreachability for correctness
Four conditions deleted on #86 for being dead each left an equivalent test in the
same function. `inv-11`'s guard became unreachable only because *another module's*
rule (#89's create-refusal) now happens to run first, and what it protects is #45's
class — reading rows `TRUNCATE` is about to delete. Kept, with its mutant taken out
of the harness because a case that can never be killed trains people to ignore the
report. → 2026-08-17 (#86)

### An empty `-k` selection is exit 5, and exit 5 is not a failure
The harness ran each mutant with `-k <expr>` and read any non-zero exit as a kill.
When #86 merged `main`, the two case sets were united but the target-file list was
not: every `cell-` case's tests lived in a file the branch's list did not name, so
`-k` selected nothing, pytest exited 5, and 13 mutants were reported killed having
run no test at all — `cell-5. -> 292 deselected in 0.04s`, RED. Same trap as the
empty parametrize, one layer out: whatever runs the tests has to know the difference
between "red" and "nothing ran". → 2026-08-19 (#86 pre-round)

### A guard can be shadowed by a change in another module
Not the same as a guard that was always dead. The merged harness is what surfaced
it; neither branch could see it alone. → 2026-08-17 (#86, "a sixth lesson")

### Say "mutation testing", not "neuter"
Codex refused the work on content grounds ~14 times across two sessions. The trigger
was vocabulary — "neuter each guard", "find inputs that evade the refusal", a tool
that "strips guard conditions and confirms nothing detects it" reads as an evasion
harness. The standard terms (mutants killed and surviving) plus one line of domain
context fixed it. → 2026-08-17 (#86)

### Frontend mutation scripting races Vite's recompile
A mutant reported as surviving on a frontend file needs a manual re-run before it is
believed. The backend has no such race. → 2026-08-19 (#103)

---

## Review

### Every round found a defect in the previous round's fix, with a green suite each time
Six rounds across #75 and #76; four for #75 to reach GO, three for #76. Seven on
#79. Nothing was found by writing more tests for the thing already understood; every
finding came from someone else varying an axis the author had not. A branch that
touches a boundary is not one review away from done — budget for the rounds.
→ 2026-08-15 (#75, #76), 2026-08-15 (#79)

### When rounds keep landing in one function, the fix is an invariant one level up
Rounds 2–6 on #79 were the same gap seen from different angles: apply-time locking
scoped to whatever path the last review reported, each fix leaving the next open.
Round 7 said stop; the owner's call was to make the general guard (the write gate,
rule 7.1) a prerequisite PR and rebase onto it, which deleted ~220 lines of
`importing.py` and ~580 of its tests. → 2026-08-15 (#79, #80)

### The reviews are finding things the tests do not — five for five
Three rounds on #103, every finding real, two of them changing code rather than
tests and neither reachable by anything in-tree (a focus trap letting focus reach
`<body>`, an observer with no guard). → 2026-08-19 (#103)

### Copilot left zero comments on the PR that shipped #69
Its one useful find (#62's dangling reference) was API state semantics, a class it
can read off a diff. For value-space defects, do the adversarial pass yourself.
→ 2026-08-11 (#69)

### The review was right about the defects and wrong about several remedies
The v0.2.3 external review correctly said `session.get(..., with_for_update=)`
serves stale attributes, but only one call path actually preloaded, not the five it
listed; its `formatDate` remedy would have broken `received_at`; it treated the
always-empty `kit_photos` export as a fidelity bug. Verify the remedy as hard as the
defect. → 2026-08-11 (triage entry)

### The one about attribution
Codex's review of #75 opened with a line naming the model; the reply to it did not,
and had to be corrected after the fact. Every agent here posts through the owner's
account, so unsigned prose reads as the owner speaking — including first-person
verification claims and severity calls. Hence the rule in `AGENTS.md`.
→ 2026-08-15 (#75)

### The author's counts were wrong twice in one PR body
#109's body claimed 70 red on unfixed `main` (measured: 74 — four cases the author
had filed as controls failed on the strip) and "17 mutants" over a table of 16; a
regenerated mutant tuple in the same body was corrupted by a careless text replace.
None of it changed the verdict, all of it was caught only because the reviewer
re-ran rather than read. The brief now says "re-measure", and the PR-body numbers
are written from the run's output, not from memory of it. → 2026-08-19 (#109)

---

### A claim about what a spec asserts is a measurement, not a memory

PR #165's body and brief said `order-lossless` pinned the expand-row aria
sentences and that e2e asserted "1 across 1 line". Neither was true: the
belief came from failure snapshots whose row text *contained* the phrases and
from an exploration report, repeated without a grep — the only real coupling
was a `/line items/` regex matching both verbs. The reviewer corrected both
and established the transcription by rendering the values against `main`'s
deleted literals instead, which is the stronger control anyway. Write "spec X
pins string Y" only in the same breath as the grep that proves it.
→ PR #165 reply.

## Architecture

### Why the write gate exists
Rule 7.1. See "When rounds keep landing in one function" above. Row locks serialise
writers touching the same row; they cannot protect a read-decide-write span whose
decision depends on rows the plan never names, which is the shape `apply_import`
has. A mutating service that skips the gate reopens the class: a plan read outside
it is stale by the time it is written, and the failures are 500s and silent data
loss, not conflicts. → 2026-08-15 (#79, #80)

### Why export reads one snapshot
Rule 7.2 — and where the snapshot must never go. One statement per table under `READ
COMMITTED` is one snapshot per table, and a write landing between two of them wrote
an archive whose files contradicted each other — a kit whose order line no CSV in
the same zip contained (#48). The database was never damaged; the artifact was, and
the artifact is what gets kept as a backup. `plan_import` is shared by preview and
apply, so a snapshot there would make every apply fail with
`ReadOnlySQLTransactionError` — it is the obvious next place someone would put it.
The snapshot is fixed by the transaction's *first SQL statement*, not request entry.
→ 2026-08-16 (#48)

### Building on the parent of the class the spike measured
The #190 spike measured FastMCP's `OIDCProxy`; #192 built on its parent `OAuthProxy`,
because `OIDCProxy` fetches the provider's discovery document synchronously at
construction and a provider down at start would have failed the start (§5.6 safe
failure). The parent verifies the *upstream access token*; the child's two small
hooks (`_get_verification_token`, `_uses_alternate_verification`) are what make the
**id_token** the verified token — the whole basis of the owner binding — and the
first head silently lost both: every token the proxy issued was refused at the first
MCP request. The full-link test caught it (`401 == 200` on initialize) before any
review did. When you subclass one level up from the class the evidence was taken on,
enumerate the overrides the measured class carried and re-provide each one
deliberately, or the measured behaviour is gone without a line of the diff saying so.
→ 2026-09-05 (#192)

### Deterministic lock ordering, not delta aggregation, fixes the deadlock
#36 proposed aggregating per-target deltas in `update_order`; the fix was
`_lock_catalog_targets`, draining an order write's catalog locks up front in uuid
order — which also covered create/receive/delete, where aggregation would not have.
Global rule: catalog rows (by uuid), then kits. `session.get(..., with_for_update=)`
without `populate_existing` genuinely serves stale attributes, but no code path
today reaches it; its test is an honest contract test with a reference held alive,
not a race, and should not be "fixed" into one. → 2026-08-11 (#36)

### The importer never invents timestamps or stock, and does not route through the order service
Calling `receive_order` from an import would apply stock — rule 10 head-on. The
invariant pass in `services/portability/` *rejects* what the service would refuse;
what is shared is the predicates, not the mutation path. → 2026-08-11 (triage, #44)

### Read-after-write: commit before returning
FastAPI runs yield-dependency teardown (where the commit lived) *after* sending the
response, so the UI's invalidate-and-refetch could read pre-commit state. Mutating
services commit explicitly before returning. → 2026-08-06 (Milestone 3)

### The `--build` mystery
Three explanations committed and retracted. A fresh LXC on the official Docker
packages failed `docker compose up -d --wait` outright; `--build` fixed it. A
minimal probe on that same host — one service, same `image:` + `build:` pairing, no
local image — does *not* reproduce it: Compose attempts the pull, fails, and builds
anyway. Committed and retracted so far: that the compose file always fails without
the flag; that old Compose fails and new builds (the failing host has the *newer*
Compose, v5.4.0 vs OrbStack's v5.1.2); that a named-but-missing image is a hard
failure anywhere. Leading untested suspect: `api` and `migrate` sharing one image
tag. The definitive test is on the LXC with the real stack (`down`, remove both
images, `up` without `--build`) and costs a few minutes of downtime — the owner's
call. State the observation, prescribe the flag, stop there. → 2026-08-18 (#91
entry), 2026-08-15 (v0.2.5 release gate)

---

## Tooling and process

### `git checkout <branch> -- <paths>` discarded uncommitted work
And a later `git stash pop` collided with it. Both recovered, but the stash/checkout
dance used to run tests against old code is what caused it. Commit first, then swap
files — or use a worktree, which is what every session since has done. → 2026-08-14

Done again on #49's review round: the round's *test-file* edits were uncommitted while
single-site mutants were applied to the service files and restored with
`git checkout -- <path>` — a fallback branch of the restore step named the test file
too, and it reverted to the committed version. Recovered from the edit script.
The rule is not "don't use checkout"; it is **commit the round before mutating
anything**, so every restore has a known-good target. → 2026-08-19 (#49, PR #108)

### Two pytest sessions at once deadlock on `TRUNCATE`
A background run overlapping a foreground one reported 19 phantom failures; under
the write gate a hung run parked on `advisory` is the tell. One at a time.
→ 2026-08-15 (#75), 2026-08-15 (#80)

### `--repeat-each` is not a way to measure flakiness
It reuses one module load, so every repeat shares the fixture name and stacks
duplicates. It cost a round of wrong numbers on #50 before the real one (1 pass in 5
in fresh processes). → 2026-08-18 (#50)

### `Closes #82 and #88` binds the first reference only
GitHub auto-closed #82; #88 was closed by hand afterwards. Write
`Closes #82, closes #88`. → 2026-08-17 (#89)

### `gh issue create` goes through GraphQL; `gh api` does not
With GraphQL 503 and REST fine, filing worked via
`gh api repos/OWNER/REPO/issues -X POST -F body=@file -f 'labels[]=…'`. A 503 on a
POST can still have created the record — check before retrying; one of four had not
been. → 2026-08-18

### GitHub Actions jobs stuck `in_progress` with every step green
`gh run rerun <run> --job <id>` clears it. Not a project problem. → 2026-08-11

### vitest's default include glob matches `e2e/*.spec.ts`
Which only Playwright can run. `test.include` in `vite.config.ts` is narrowed to
`src/**/*.test.ts` for that reason; widening it breaks `npm test`. The shared money
fixture is *imported*, not read with `readFileSync`, so `tsconfig.app.json` does not
need Node's globals. → 2026-08-10 (PR #18)

### Merge notes that git will not show you
#86 and #89 both added a call immediately after `_defer_filled_money_currency`, both
acting on a blank `status_updated_at`; the wrong order made the preview lie. Found by
a review that read both trees; neither branch could test it until one landed. When
two open branches touch one function, `git merge-tree --write-tree` first, and write
the resolution down before either merges. → 2026-08-17 (#89 "MERGE NOTE")

## The 401 contract (#202, rounds 1–2)

The PR body for #189 said "`WWW-Authenticate` on every 401". Codex found two 401s
without one — a wrong password, a wrong setup token — and the author narrowed the
*claim* ("every 401 at the bearer boundary") rather than the *code*: those routes
refuse a bearer, so a `Bearer` challenge there would name a credential the route
cannot take, and the 401 was left challenge-less. Round 2 overruled it: RFC 9110
§15.5.2 makes every 401 owe an applicable challenge, and "at the boundary" is not
an exception the status code grants. The fix was the status — a rejected form
credential is **403** (`CredentialRejectedError`), codes unchanged — after which
the original claim is simply true. The lesson is the reviewer's own line: when a
round lands twice in the same contract, the invariant is wrong, not the wording,
and a claim that needs a qualifier to stay true is a claim the code should be
made to satisfy instead. Same round, same shape: the T10 "no token in any log"
proof had one harness still sending a live token in a URI, and a packaged log
scan that would pass on empty output — a leakage invariant is only as wide as its
*narrowest* harness, and a scan without a vacuity guard is a scan that can be
deleted by a logging change nobody reviews.
