# Testing and review — how it is done here

Procedure, current-state, edited in place. When something here changes — a harness
grows a flag, a reviewer's ceiling moves, the release gate gains a step — overwrite
the line; do not append a note below it. The reasons behind these steps are in
`lessons.md`; the binding short-form rules are in `AGENTS.md`.

**Read this** before writing a regression test for a filed defect, before opening a
PR for review, when responding to a review, and before cutting a release. It is not
needed on every turn — that is why it is not in `AGENTS.md`.

Contents: [Running the suites](#running-the-suites) ·
[Writing a regression test](#writing-a-regression-test) ·
[Concurrency tests](#concurrency-tests) · [Mutation testing](#mutation-testing) ·
[CI](#ci) · [External review](#external-review) ·
[The release gate](#the-release-gate)

---

## Running the suites

All from `backend/` unless noted. Numbers are the counts on `main` when this was
last edited, so a large jump either way is worth a look.

| What | Command | Notes |
| --- | --- | --- |
| Backend (~1088) | `uv run pytest` | Auto-creates `plamotrack_test`, runs `alembic downgrade` + `upgrade` at session start, truncates between tests. Needs the dev `db` container up. |
| Lint + format | `uv run ruff check --fix . && uv run ruff format .` | Before every commit. CI checks both. |
| Frontend unit (~165) | `npm test` (in `frontend/`) | vitest over `src/**/*.test.ts` only — the include glob is narrowed on purpose. Includes the i18n catalogue checks (`src/i18n/catalogue.test.ts`). |
| Frontend build | `npm run build` | `tsc -b` then Vite. Before every commit. Also the compile-time check on every static `t("…")` key. |
| Frontend lint | `npm run lint` | oxlint. |
| Translation coverage | `npm run i18n:report` (in `frontend/`) | Markdown table, presentation only — the catalogue tests are what gate. CI appends it to the job summary. |
| E2E (~29) | `npm run test:e2e` | Playwright; reuses a running backend on :8000 and Vite on :5173, else starts them. Creates uniquely-named data and cleans up via the API. `npx playwright install chromium` once. |
| Mutation harness | `uv run python mutation_test.py` | See below. |

**One pytest session at a time.** Two runs against `plamotrack_test` interfere —
the conftest truncates between tests and migrates at session start; the failure mode
is a deadlock on `TRUNCATE` and phantom failures. Under the write gate a hung run
parked on `wait_event='advisory'` in `pg_stat_activity` is the tell.

**Verify e2e against a database migrated from empty before trusting a green run.**
CI starts empty; the dev database does not. A test that reads "whichever order is on
the page" passes locally and has nothing to find in CI. Playwright's `webServer`
starts uvicorn itself when nothing is on :8000, and the app reads `DATABASE_URL`, so
the whole thing is one script (run from the repo root, with the dev `db` up):

```bash
eval "$(grep -E '^POSTGRES_(USER|PASSWORD|PORT)=' .env | sed 's/^/export /')"
DSN="postgresql+asyncpg://$POSTGRES_USER:$POSTGRES_PASSWORD@127.0.0.1:${POSTGRES_PORT:-5432}/plamotrack_e2e"
psqlc() { docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T db psql -U "$POSTGRES_USER" -d "$1" -tAqc "$2"; }
psqlc postgres "DROP DATABASE IF EXISTS plamotrack_e2e;"      # separate calls: DROP DATABASE
psqlc postgres "CREATE DATABASE plamotrack_e2e OWNER $POSTGRES_USER;"   # can't share a transaction
( cd backend  && DATABASE_URL="$DSN" uv run alembic upgrade head )
( cd frontend && DATABASE_URL="$DSN" npx playwright test )
psqlc plamotrack_e2e "select count(*) from kits union all select count(*) from orders union all select count(*) from retailers"   # all 0
psqlc postgres "DROP DATABASE plamotrack_e2e;"
```

Every count must be zero afterwards — a spec that leaves rows behind is a spec that
will collide with the next one.

**Do not use `--repeat-each` to measure flakiness.** It reuses one module load, so
every repeat shares the fixture name and stacks duplicates. Fresh processes only.

---

## Writing a regression test

The checklist. `AGENTS.md` carries the short form; `lessons.md` carries the case
that produced each line.

1. **Reproduce first, at the head under review.** Every finding is reproduced
   before it is fixed; a fix for a defect nobody reproduced is a guess.
2. **Enumerate the field's values before writing assertions:** null, empty,
   whitespace, the derived or default value, and something that genuinely differs.
   Drive at least the null and the default.
3. **Enumerate the row's states.** The action (create / update / error / skip), the
   mode (merge / add_only / replace_all), the status — whatever classification
   decides the shape of the structure the fix touches. Drive at least two, and
   prefer the one that makes the structure non-empty (`changes` is empty on a
   create; `matched_id` is null until something matches).
4. **When one matrix in a file varies a state axis, every matrix over the same
   field owes a reason why it doesn't.** The neighbour is the cheapest place to
   notice.
5. **If the rule is about rows diverging, seed more than one row.** If it is about
   timing, pin the timing rather than hoping. The pins that have worked in e2e:
   `page.route` to *hold* a request until both clicks have landed (double-submit
   guards); `page.clock.setFixedTime(new Date())` to freeze `Date.now()` so a
   TanStack `staleTime` can never elapse (cache-staleness defects) — timers keep
   running, so debounces still fire; `page.route` to *stall* a refetch so a stale
   window is certain (#66). In pytest: a task for the racer and `pg_stat_activity`
   for the wait, never `sleep`.
6. **Assert the layer that spoke and the error class**, not a substring both layers
   happen to contain and not merely "a refusal happened". Where the point of the
   test is which status a bad input earns, use the **`http_client`** fixture
   (`raise_app_exceptions=False`) — the default `client` re-raises a 500 into the
   test, which goes red without pinning anything.
7. **Assert the named control, not containment.** `inDialog` is satisfied by focus
   that was already inside; it cannot see a mechanism that moves focus within.
8. **Never derive the test's subject from the code under test.** A parametrize list
   built by calling the function being tested can be emptied by the mutant, and an
   empty parametrize *skips*. Read the enumeration from the schema, the fixtures, or
   a literal list.
9. **Cross-layer behaviour gets a shared fixture, not a suite per side.**
   `frontend/src/lib/__fixtures__/money-cases.json` is read by both
   `format.test.ts` and `backend/tests/test_currency.py`. Add cross-layer cases
   there.
10. **Run the suite against the unfixed code, and check *which* tests go red and
    why each one does.** Necessary, not sufficient — a red test proves it detects
    the case you thought of. Do it in a **worktree**, not with
    `git checkout <branch> -- <paths>` (which has discarded work here). Size and
    assert off literals, not the fix's new constant — a test naming a symbol the
    old tree lacks fails to import, which masks the whole file. If a param would
    hang against the old tree (two billion inserts), deselect it with `-k`.
11. **Then mutate the fix, one place at a time.** A fix that lands in several
    equivalent places (three catalog tables, four integer families, REST and MCP)
    is checked by breaking each place separately; breaking the fix as a whole
    proves the test sees *a* fix, not that it sees every place. See the harness.
12. **State the negative controls in the PR body:** which tests fail against
    unfixed `main`, and why each one does. Reviewers here check the test claim
    before the diff.

---

## Concurrency tests

Three writer types exist by design (UI, REST, MCP agents) plus the importer, so
races are in scope. What has held up:

- **Under the write gate, launch the racer as a task and await it after the
  apply.** Awaiting inline inside a patched `plan_import` while the apply holds the
  gate deadlocks the test against itself.
- **Coordinate on Postgres state, not sleep.** `_race_after_planning` in
  `tests/test_integrity.py` waits for either the racer finishing or
  `pg_stat_activity` reporting it parked on the advisory lock, and raises if
  neither happens. `asyncio.sleep` creates an opportunity, not an occurrence.
- **A pinned barrier** (a third transaction holding `FOR UPDATE` on one row so
  writers park on it) is safe only when the code under test holds a single lock and
  always releases it — it can never be half of a cycle. Where pinning would put the
  test itself inside a lock cycle (#37's shape), **repeat the race ten times and
  assert the end state** instead; check the repeat count catches the unfixed code
  reliably (6/6, not 2/8).
- **An export racer completes inline** — no gate, no row locks — and is exactly
  deterministic; that is specific to row writes.
- **The suite runs on `NullPool`.** Anything about a connection characteristic
  leaking back into a pool (isolation level, `READ ONLY`) needs its own
  `pool_size=1` engine, as `test_the_snapshot_does_not_follow_the_connection_back_into_the_pool` does.

---

## Mutation testing

`backend/mutation_test.py` — hand-rolled semantic mutation testing, tracked. Its
docstring is the contract. Each case is `(label, file, exact source, replacement,
pytest -k expression that must go red)`; the script applies one mutant, runs the
named tests, restores from a backup in a `finally`, and reports killed vs
surviving.

```bash
cd backend && uv run python mutation_test.py          # every case — ~22 min at 227 cases on
                                                      # the primary dev Mac (22m16s measured
                                                      # at the #159 fold-in, 27/08/2026;
                                                      # hardware-dependent — each case runs
                                                      # its selection twice: baseline + mutant)
uv run python mutation_test.py -k rcpt-                # cases whose label contains "rcpt-"
```

- **Refuses a dirty tree**, so an interrupted run is obvious in `git status`.
- **A burst of failures that vanish on re-probe is a concurrent pytest session,
  not a finding.** A parallel session running the suite against `plamotrack_test`
  mid-harness reads as SICK/ERROR/GREEN for exactly the window it overlaps, and
  every label re-probes RED afterwards (seen live at the #133 fold-in, caused by
  a spawned agent session). Check `git worktree list` and `pg_stat_activity` for
  the intruder, then re-run — don't chase the labels.
- **An anchor matching zero or two places is a failure**, not a skip — a mutant that
  never applied is not a mutant that was killed. Anchors are exact source strings
  and rot when the code moves; a refactor that touches an anchored line owes a
  harness run.
- **A `-k` expression that selects no test is a failure too** (`NONE`, on #86's
  harness from `fd8d195`). pytest exits 5 there, and "any non-zero exit is a kill"
  read it as RED: after a merge united two case sets under one target-file list, 13
  cases ran nothing and reported killed. The harness names its target files in a
  literal `TEST_FILES` list; a case whose tests live in a new file extends the list.
- **A surviving mutant is the finding**, and means one of two things: the condition
  is dead (something else already decides the outcome), or it is live and untested.
  Decide which before acting; do not delete a guard for being unreachable if what
  it protects is data another module's ordering happens to shield today.
- **Check a new mutant actually changes behaviour** before trusting its result. A
  renamed key that hashes the same, or a change a sibling branch compensates for,
  reads green and proves nothing.
- **Take a mutant that can never be killed *out*.** A permanent survivor trains
  people to ignore the report.
- **On `main` at the time of writing: 227 cases over twenty files** — #86's
  `cell-`/`merge-`/`inv-`/`stamp-`/`fut-` set plus the folded queues from
  #109 (`n`/`o`/`c`), #111 (`rcpt-`), #113 (`bd-`/`ser-`), #115 (`moe-`),
  #118 (`ship-`), #129 (`dsp-`), #130 (`cat-`), #133 (`ref-`), #136
  (`strt-` — queued as `st-`, relabelled because `-k st-` substring-matches
  "post-write" in older labels; pick prefixes `-k` can't find elsewhere),
  #139 (`adv-`; that branch also re-anchored ship-5/ship-12/stamp-2 in place)
  #141 (`cap-` — `fan-` was rejected because `-k fan-` matches "fan-out"
  in strt-7's label; that branch also re-anchored adv-7), #143 (`rcv-`),
  #149 (`wdr-` — withdrawal; wdr-7's kill is the end-state assert seeing two
  successes, not a `StaleDataError`, per the round-1 review correction) and
  #151 (`mig-` — the first cases that mutate **migrations** rather than app
  code; the clean-tree check covers `alembic/` since that fold-in, and the
  walk fixture suppresses a teardown restore failure only when the test body
  already failed, so these kills read as the one failure they are) and #154
  (`o67-` — silent kit lines) and #156 (`d63-` — the dangling-reversal tolerance)
  and #159 (`stg-` — the instance-settings singleton; `iset-` was rejected
  because `-k iset` matches cat-22's "multiset". stg-5's kill is the
  `pg_blocking_pids` holder→updater edge, never a count of advisory waiters —
  that round-1 finding is the standing example of an observation a decoy can
  satisfy; stg-17 mutates the settings migration's seed under the mig- set's
  clean-tree cover).
  A branch that runs mutants ahead of the harness (a scratch copy, a hand run)
  queues its tuples in the PR body for folding in after merge — anchors get
  re-checked at fold-in, since the code may have moved under them. Labels are
  prefixed because `-k` matches substrings and two sets numbered from 1 collide.
- **Frontend equivalent races Vite's recompile.** A frontend mutant reported as
  surviving needs a manual re-run before it is believed. Nothing tracked yet.
- **When briefing an external model to do this work, say "mutation testing".**
  "Neuter each guard" / "find inputs that evade the refusal" reads as an evasion
  harness and was refused ~14 times. Standard terms plus one line of domain context
  (inventory counts, not access control; no auth yet) is what worked.

---

## CI

`.github/workflows/ci.yml` — three jobs, SHA-pinned actions, `contents: read`,
no secrets to forks, stale runs cancelled.

| Job | Runs |
| --- | --- |
| Backend | ruff check + format check, pytest against Postgres 16 |
| Frontend | oxlint, vitest, translation coverage report to the step summary, `tsc -b` + Vite build |
| Integration | Playwright e2e (one worker, one retry, trace on first retry, HTML report uploaded **only on failure**), then the packaged Compose stack: UI/API/OpenAPI probes and an MCP `tools/list` through nginx |

- **A pass on retry reports as `flaky` with exit 0.** Deliberate: instability is
  surfaced without blocking a PR. The lever, if it hides a real intermittent, is the
  retry count, not the artifacts.
- **A job stuck `in_progress` with every step green:** `gh run rerun <run> --job
  <id>`. Not a project problem.
- **Integration copies `.env.example` to `.env`** — the documented fresh-install
  path, no secrets.

---

## External review

Reviews here have found what tests did not on every branch that touched a boundary,
so the loop is part of the process, not a formality.

### When to buy one

The owner's criterion, from #40: **buy a review for a shared mechanism everything
flows through**; a small, local change whose worst failure is a false refusal rides
the release gate instead. State the call and the reason in the hand-off entry.

### Which reviewer

| Reviewer | Fits | Notes |
| --- | --- | --- |
| **Cursor / Grok 4.6** | ≤ ~1,000 insertions, PR thread ≤ a few K tokens | 256K context. Two rounds on #89 (993 insertions) took 15 and 19 min and ended at 63 % and 68 %. **One round per fresh chat session** — a second review in one session runs out mid-analysis, and a truncated review that still emits a verdict is the worst outcome. Survivable because the PR thread is the session memory. |
| **Codex (GPT 5.6)** | Anything larger; multi-round | Has absorbed #86 (4,442 insertions) across four rounds. Usage budget is finite and resets on a schedule (the #86 entry recorded a Thursday reset with ~5 % left); check what remains before starting a round. |
| **Copilot auto-review** | Off | Disabled by the owner on 2026-08-11 to conserve credits until 1 September. Its useful finds have been API-state semantics readable off a diff, not value-space defects. Don't request one casually. |

Match the tool to the size of the work rather than forcing everything through one
queue. Both external tools output to chat unless told otherwise.

### Briefing a reviewer

**The brief is a template — `.agents/review-brief.md`.** Fill its `‹slots›` and
**print the finished brief in the chat, in full, in a copyable fenced block**
(four backticks — the brief contains three-backtick blocks); a path to a scratchpad
file is not a deliverable (owner's call, 2026-08-24). Don't write one from memory:
the fixed sentences are the wording that has worked, and the file's last section is
the checklist that produces the per-PR "where I'd push" bullets, which is where the
findings come from. The template also names the PR-body sections it points at
(What / Deliberate calls / Tests with the negative control and the mutant table),
so write the PR body to that shape. The bullets below are why the fixed parts say
what they say:

- **Prepare the environment first:** deps installed (`uv sync`, `npm install`),
  db up, everything offline-resolvable. Otherwise every install is an approval
  prompt inside the review.
- **Tell it where to post:** `gh pr comment N --body-file <path>` — `--body-file`,
  not `--body`, because a shell string mangles backticks and `$`.
- **Point it at the test claim, and tell it to re-measure.** The PR body lists
  which tests fail against unfixed `main` and why; that is the claim most worth
  checking, and the author's counts are the first thing to get wrong (#109's body
  said 70 red over a measured 74, and "17 mutants" over a table of 16). Name the
  two or three things in the branch that are assumptions rather than proofs and
  invite it to push there.
- **Vocabulary:** see the mutation-testing note above.
- **One reviewer per round, a different model family from the author where you
  can.** Cursor and Codex are the defaults; Claude is an option with the caveat
  written into the template's footer.

### Responding to a review

1. **Open with the attribution line, close with the sign-off** — the format is in
   `AGENTS.md` (Git conventions). Every reply, every round. Name the head:
   *"response to the Codex review, at head `9d751ca`"*.
2. **Reproduce each finding at the reviewed head** before touching anything. Then
   fix, then re-verify by mutating (not by reading).
3. **Answer per finding**, in the reviewer's numbering, and say what was done: fixed
   at `<sha>`, filed as #N, or declined with the reason. A finding that is right
   about the defect and wrong about the remedy gets both halves said.
4. **Severity is triaged by real exposure, not by the bug's shape.** A pre-adoption
   alpha on a trusted network is a legitimate input to a P-level; say so rather
   than rating a shape.
5. **Push back on the wrong ones**, on the PR, so they are not left standing for
   the next reader — with the evidence (the type, the version, the test).
6. **Expect another round.** Merging on a NO-GO discards the review it was sent
   out for. If rounds keep landing in the same function, stop patching it and look
   for the invariant one level up.
7. **File the siblings a review turns up** as their own issues; do not fold them in
   unless they share the root cause and the branch says so.
8. **After merge, `Closes #A, closes #B`** — one `closes` per reference; GitHub binds
   only the first otherwise.

`gh pr merge` works from an agent session; attempt it once when asked and hand
over the command if it is denied rather than routing around via the API.

---

## The release gate

Run before every tag. It has failed twice on the same invariant (#65, #69 →
v0.2.4.1, v0.2.4.2), so it is not a formality either.

1. **Milestone is empty** of open issues, or what remains is deliberately deferred
   and says so.
2. **Version bump — three files that move together:** `backend/app/__init__.py`
   (`__version__`), `backend/pyproject.toml`, and the `plamotrack-backend` entry in
   `backend/uv.lock` via `uv lock` (never hand-edited). Through a PR like anything
   else. Two tests hold the version, one of which pins `pyproject.toml` against `app/__init__.py` (#78).
3. **Check the two surfaces**, not the edit: `GET /meta` and the MCP handshake's
   `serverInfo.version` both report the new number.
4. **Packaged stack, from the tagged commit:**
   ```bash
   docker compose up -d --wait --build     # --build is load-bearing; see AGENTS.md
   docker compose logs migrate             # Exited (0)
   curl -s http://127.0.0.1:8080/api/meta  # right version
   ```
   Then export an archive *from the container* and check its manifest carries the
   right `app_version` and schema revision. Four healthy services.
5. **Restore the dev overlay afterwards** — the packaged stack replaced the dev
   `db` container:
   ```bash
   docker compose down
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db --wait
   ```
6. **Tag and release.** Annotated tag, subject `vX.Y.Z-alpha — <short theme>`, on
   the commit that carries the bump. `git push origin vX.Y.Z-alpha` (needs
   confirmation — outward-facing), then
   `gh release create vX.Y.Z-alpha --prerelease --verify-tag --notes-file …` so it
   attaches to the pushed tag rather than minting one. **`--prerelease` every
   time** while the project is alpha.
7. **Release notes lead with what alters data someone already has** — a fix that
   reinterprets stored amounts, a migration that has to guess, a rollback that is
   lossy — and say what to check. Headline the data fix over the bigger feature.
   Amend published notes in place, with the amendment stated at the top, if they
   turn out to have overclaimed.
8. **A migration that guesses is disclosed as one**, with the rollback consequence
   (e.g. downgrading clears rows the restored column cannot represent).
