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
| Backend (~1750) | `uv run pytest` | Auto-creates `plamotrack_test`, runs `alembic downgrade` + `upgrade` at session start, truncates between tests. Needs the dev `db` container up. |
| Lint + format | `uv run ruff check --fix . && uv run ruff format .` | Before every commit. CI checks both. |
| Frontend unit (~471) | `npm test` (in `frontend/`) | vitest over `src/**/*.test.ts` only — the include glob is narrowed on purpose. Includes the i18n catalogue checks (`src/i18n/catalogue.test.ts`). |
| Frontend build | `npm run build` | `tsc -b` then Vite. Before every commit. Also the compile-time check on every static `t("…")` key. |
| Frontend lint | `npm run lint` | oxlint. |
| Translation coverage | `npm run i18n:report` (in `frontend/`) | Markdown table, presentation only — the catalogue tests are what gate. CI appends it to the job summary. |
| E2E (~43) | `npm run test:e2e` | Playwright; reuses a running backend on :8000 and Vite on :5173, else starts them. The `setup` project (`e2e/auth.setup.ts`) signs in as the owner first — an **unclaimed** instance is claimed through the recovery command with `E2E_OWNER_PASSWORD` (default `e2e-owner-password`); a **claimed** one is only signed into, so on a dev database you claimed yourself export `E2E_OWNER_PASSWORD` to its password or the run stops and says so. The session lands in `e2e/.auth/` (gitignored); specs' own API calls go through `e2e/api.ts` (`apiContext()`), which carries the cookie, an `Origin` and the CSRF token. Creates uniquely-named data and cleans up via the API. `npx playwright install chromium` once. |
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
   Drive at least the null and the default. For a field a **protocol** defines, the
   value space is the protocol's, *unrecognised values included* — RFC 7009's
   `token_type_hint` is ignored when the server does not know it, never refused, and a
   two-value enum on that field turned a valid revocation into a 400 through four
   review rounds (#212 round 5).
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
cd backend && uv run python mutation_test.py          # every case — ~27 min at 244 cases on
                                                      # the primary dev Mac (25m19s measured
                                                      # on the #26 branch, 28/08/2026;
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
- **On `main` after #212: 511 cases over 46 target files** — counted the way the
  harness itself counts, `len(CASES)` and the distinct paths those cases mutate
  (migrations, the one test file and the two `frontend/` files included; the
  one-liner is `uv run python -c "import mutation_test as m, pathlib; print(len(m.CASES), len({pathlib.Path(c[1]).resolve() for c in m.CASES}))"`
  — the number in this sentence has been wrong twice in one PR body, so re-derive
  it rather than edit it by hand; Codex #212 round 2) — #86's
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
  clean-tree cover) and #169 (`env-` — the error envelope, folded by PR #170) and #26 (`nd-` — the
  import-preview diagnostics) and #114 (`tz-` — naive datetimes in the
  instance zone) and #178 (`oma-` — the order-ambiguity code split and the
  exact-params diagnostic audit; the first cases whose targets sit outside
  `app/`: oma-2 mutates the shared registry fixture in `frontend/` and
  oma-4/5 mutate `tests/test_error_envelope.py`'s audit comparator, so the
  clean-tree check covers the fixture path since that fold-in — a dirtied
  fixture refuses the run, measured at fold-in time) and #186 (`ingr-` — queued as
  `ing-`, relabelled because `-k ing-` substring-matches wdr-8's "missing-application";
  the M6-1 Host/Origin guard, `app/ingress.py`, `app/hostnames.py`, `app/config.py` and
  `app/main.py`; queued on PR #196 as 19 + 7 tuples, all killed there by hand, the
  seven round-1 ones against the Codex findings. **The first cases against a shell
  file:** ingr-25 and ingr-26 mutate `frontend/nginx/15-plamotrack-server-names.envsh`
  and are killed by the corpus test that runs it under `sh` against the Python
  policy, so the clean-tree check covers that path since this fold-in. ingr-5
  survived the branch's first pass — the MCP child has one route today, so its
  `redirect_slashes` was unobservable — and is killed by a probe-route test; ingr-25
  survived once because the parity helper normalised the terminal dot away before
  comparing, fixed by asserting the raw `server_name` first. The one set here that
  is about the request boundary rather than inventory: see the harness docstring)
  and #187 (`auth-` — the M6-2 auth foundation, PR #198: `app/auth/principal.py`,
  `dependency.py`, `registry.py`, `app/main.py`, `plan_requires_admin` in the importer and,
  under the mig- set's clean-tree cover, the auth migration's owner seed. auth-1…23 were
  queued on the PR (auth-5 retired at round 3, its site removed — the gap is kept);
  auth-24…42 are the round-1 set the PR queued by name only, written at fold-in. Every
  behavioural kill runs against `create_app(authorization=True)` — the shipped app is
  unenforced until #188. Two fold-in findings: the queued auth-22 tuple *appended* a
  second copy of the profile middleware outermost where the round-3 hand run had moved
  it, and survived (the inner copy still stamps) — re-anchored as one block replacement
  that moves the call; and auth-37 (the predicate counting every table's UPDATEs)
  survived because the collection-only import test planned a CREATE, never an UPDATE
  — the test now seeds the retailer so the row is an UPDATE, the state-axis rule).
  and #189 (`pat-` — personal access tokens, PR #202: `app/auth/tokens.py`,
  `app/services/tokens.py`, `app/auth/resolver.py`, `app/auth/mcp_auth.py`, plus
  `dependency.py`, `registry.py` and `main.py`; pat-1…23 hand-run on the branch, pat-24
  and pat-25 added by the Codex rounds — the value normalised in the shared helper and
  rejected form credentials mapped to 403; all 25 killed at fold-in, `-k pat-`)
  and #204 (`f13-` — the pre-routing gate, PR #205: `app/auth/prerouting.py`, plus
  `dependency.py` and `main.py`; f13-1…13 hand-run on the branch, f13-14/15 added when
  CI Integration caught the family-8 namespace miss the sweep had skipped — the
  standing example that a sweep enumerates the *families the ingress forwards*, not
  the families with routes; f13-6's sole witness is the resolution-count test, the
  audit-row test being a control that cannot see it (Codex round 1); all 15 killed
  at fold-in, `-k f13-`)
  and #192 (`moa-` — MCP OAuth, the M6-7 branch: `app/auth/mcp_oauth.py`,
  `auth/mcp_auth.py`, `auth/registry.py`, `auth/prerouting.py`, `auth/dependency.py`,
  `main.py`, `config.py` and `services/oidc.py`; every kill runs against an OIDC-mode
  app built in-process with the fake provider in `tests/oidc_fake.py`, and the suite is
  `tests/test_mcp_oauth.py`; moa-1…33 hand-run on the branch (moa-16 withdrawn),
  34…48 from Codex round 1 — the grant as one state machine: revocation, one
  redemption per handle, the binding as grant state, the consent path's resolution,
  the profile on a handler's failure on both sides of the mount; moa-4/6/10/11/23
  re-anchored in place by that round, moa-6 now the upstream token bounding a grant,
  moa-12/14/15 re-pointed at the cold-start tests because the endpoints as a view of
  the cache made the lifespan's warm-up every warm test's resolver; moa-39's kill is
  the log-grep test seeing the lock's key when it is the authorization code itself;
  49…56 from round 2 — the grant record as the unit of authority: the record gate,
  one lock per grant that revocation takes too, the binding on the record, the
  ending on a refused refresh response, the transparent path's outcome carried to
  the request — with 34/36/37/38/39/42 re-anchored by that round (37/38 are now the
  transition's lock, 42 the gate's digest check pointed at the f7 matrix, the retry
  test it named withdrawn with the retry it asserted); 57…60 from round 3 —
  revocation's own credential lookup (the `/revoke` route built over
  `RevocationLookup`, the shell's client binding, no owner-row read) and the gate's
  continuity check (a candidate must name the record's `(iss, sub)`, not merely the
  owner now), with moa-56 re-anchored by that round — the continuity check now sits
  inside its old anchor, so it replaces the verifier's call with the record's own
  verdict instead; 61…66 from round 4 — one downstream client contract, killed by the
  **wire-level contract suite** `tests/test_mcp_oauth_clients.py` (the first cases whose
  kills live in a file that builds every request by hand rather than through a helper:
  the registration response left as the SDK built it, the revocation form requiring a
  secret, the plain authenticator at `/revoke`, the assertion audience, the ownership
  check, a 200 on a failed client authentication — five of the six kill in the contract
  suite, moa-65 in the lifecycle suite's cross-client test), with moa-57 re-anchored on
  the handler class that replaced the SDK's; 67…70 from round 5 — discovery says the
  contract (the AS document not rebuilt, the revocation methods advertised as the SDK's
  pair, no algorithm beside a JWT method) and the hint as advice (an unknown value a 400
  again), all four killed in the contract suite, and moa-57 re-anchored a second time on
  the rewritten `get_routes`; 71…80 from round 6 — the protocol boundary field by field:
  the assertion claim contract (not applied, `nbf`, a non-string `jti`, a boolean date),
  registration canonicalisation (a null redirect list, the stored record), request
  decoding (a repeated parameter, an empty value, the PKCE default) and the recovery
  URL, all ten killed in the contract suite, with moa-64 re-anchored on the
  per-endpoint authenticator factory; 81…91 from round 7 — admission, decoding,
  cardinality and the SDK hand-off as one decision: the media type read by a
  case-sensitive prefix, the NumericDate range, `resource` under the repetition rule,
  a foreign set handed to the SDK as its first value, a foreign target at `/token`
  passed to an SDK that judges nothing, a second mechanism beside an assertion, an
  assertion from a public client, the missing challenge, `jwks` with `jwks_uri`,
  `invalid_target` left to the SDK's vocabulary, an unparseable resource — all
  eleven killed in the contract suite; and moa-76 **repaired** by that round (Codex
  f25: its replacement had left an unmatched `)`, a SyntaxError at import that the
  harness reported as ERROR and the PR body had counted as killed — a tuple is a
  program, so compile the mutant before counting it), and moa-12 and moa-74 re-anchored in
  place by that round (the `authorize` docstring and the f21 range line moved their
  anchors); 92…99 from round 8 — admitted once: a fragment not refused, the path
  compared without its parameters, the owned resource decision not applied at
  `/authorize`, unknown parameters counted, an `Authorization` header ignored without
  an assertion, only the first occurrence inventoried, the client looked up a second
  time before dispatch, the challenge read from the first occurrence only — all eight
  killed in the contract suite, with moa-71/86/87/90 re-anchored by that round (the
  authenticator owns admission end to end, so "the SDK's alone" became the claim
  contract skipped; the header inventory moved in front of the secret rule; dispatch
  is by the snapshot's method; the refusal is the proxy's own, so the vocabulary
  mutant is its code); 100…103 from round 9 — parsing is not validation: the URI
  grammar not applied, the inline key set handed to the SDK's extraction unchecked,
  unusable entries not dropped, the filtered copy not handed to the validator — all
  four killed in the contract suite, and moa-92 **redesigned** by that round: the grammar
  refuses a fragment on its own, so "the explicit check removed" had become an
  equivalent mutant (GREEN on the full pass — the procedure's take-it-out-or-make-it-
  killable rule); it is now the fragment *stripped* before comparing, FastMCP's original
  erasure, killed by the fragment rows; 104…106 from round 10 — the selected key's
  authorization: the inline selection converted to a PEM again, the remote verifier
  left as FastMCP's, the remote selection handed on as its PEM — all three killed in
  the contract suite; 107…109 from round 11 — the record the `kid` named: the inline
  and the remote record re-identified by material (the first copy judged), an
  object-shaped unusable inline key counted before the fallback — all three killed in
  the contract suite, with moa-102/104/106 re-anchored by that round (the usability
  predicate, the inline selection written out, the record checked against the PEM)
  and **moa-101 and moa-103 retired** by it: once the inline selection was the
  validator's own, round 9's copy-based filter was a second owner of the same decision
  and its three mutants went equivalent (GREEN on the full pass — the procedure's
  take-it-out rule); the filter retired into the selection and moa-102 followed it;
  110…112 from round 12 — a named `kid` must match: the inline fallback restored for a
  named `kid` (the SDK's inline rule, which round 11 had written out), an empty `kid`
  read as a name, the inline `kid` compared case-insensitively — all three killed in
  the contract suite;
  all 109 killed on the branch by the tracked harness on the committed tree,
  `-k moa-` — three first-pass survivors in
  round 2, each fixed outside the tuple: moa-47 a redundant second delete, moa-56 a
  fallback re-check masking the gate, moa-49 the fake's re-issued id_token identical
  to the original within one second)
  and #191 (`oidc-` — browser OIDC, PR #209: `app/services/oidc.py`, `services/auth.py`,
  `routers/auth.py`, `auth/registry.py`, `auth/mode.py` and `main.py`; oidc-4…20
  hand-run on the branch, 21…38 from Codex round 1 — a session is authority only in the
  mode that minted it, and one explicit id_token claim validator — and 39 from round 2,
  the NumericDate's finite domain; oidc-1/2/3/11 anchored on the joserfc claims
  registry that round 1 replaced and are superseded by 23/22/27/26; oidc-13, HS256 on
  the allowlist, is **equivalent** — the JWKS holds no symmetric key, and
  `test_an_id_token_signed_with_the_client_secret_is_refused` pins the behaviour either
  way — so it stays out rather than train anyone to ignore a permanent survivor; oidc-30's
  kill is a 500 at the callback's required 302, accepted by round 2 as a semantic
  regression; all 34 killed at fold-in, `-k oidc-`).
  **A message-restructuring change rots anchors silently**: #25 rewrote 81
  raise sites and six anchors (n5, n6a, n6b, cat-13, cat-14, wdr-8) sat
  SKIP-broken until #26's full run — a fold-in that runs only its own `-k`
  prefix cannot see that, so a branch that touches emission sites owes the
  *full* harness, not its own labels.
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
| Integration | Playwright e2e (one worker, one retry, trace on first retry, HTML report uploaded **only on failure**), then the packaged Compose stack **from an empty volume** (`down -v` first — the e2e claimed the owner in the same project's database, and a claimed instance prints no token): UI/liveness/`/api/auth/session` probes (a fresh stack must say `unclaimed`), the **setup token read from `docker compose logs api`** the way an operator would, **`backend/ingress_matrix.py`** (T2 — claims the stack with that token through nginx, then the `/api/` alias rejections in their normalised spellings, the canonical positives signed in beside an anonymous `401`, the cookie-borne writes with the absent-Origin `403`, no `Location` but nginx's relative 301, security headers, hostile Host/Origin and the listed name `ci.plamotrack.test` from the CI `.env`; since #189 it also mints two personal access tokens and proves the bearer rows — the MCP positives carry one, an anonymous MCP initialize is the bare `Bearer` challenge, a read token cannot write, a write token cannot manage tokens, a wrong secret and a revoked token are `invalid_token` on REST and MCP — and writes the write token to `$RUNNER_TEMP` with `--token-out`), and an MCP `tools/list` through nginx **with that token** by a real `fastmcp` client, plus the same client refused without one |

- **A pass on retry reports as `flaky` with exit 0.** Deliberate: instability is
  surfaced without blocking a PR. The lever, if it hides a real intermittent, is the
  retry count, not the artifacts.
- **A job stuck `in_progress` with every step green:** `gh run rerun <run> --job
  <id>`. Not a project problem.
- **Integration copies `.env.example` to `.env`** — the documented fresh-install
  path, no secrets — and appends `ALLOWED_HOSTS=ci.plamotrack.test` so the matrix
  has a listed name to prove. Locally the matrix runs the same way against a
  packaged stack: `uv run python ingress_matrix.py http://127.0.0.1:8080
  [--allowed-host NAME] [--setup-token TOKEN | ] --password PASSWORD` from
  `backend/`; without a name in your `.env`, omit the flag and the listed-name rows
  are skipped. `--setup-token` (from `docker compose logs api`) claims a fresh
  stack with `--password`; `--password` alone signs into a claimed one; with
  neither, the guarded positives expect the dependency's 401 and no write lands.
  The claim is real — a stack claimed by the matrix is claimed with that password.
  Signed in, it mints two access tokens for the bearer rows and revokes them at
  the end; `--token-out PATH` keeps the write one live and writes it there (mode
  0600) for a following MCP-client step — never printed.

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
| **GLM 5.3 Flash (Zhipu AI, via T3 Code on OpenRouter)** | **The default** for feature and fix rounds, any size | 1M context — holds a 2,000-insertion PR, its body and the process docs at once. Three rounds on 2026-08-28 (#171 GO+3P3, #173 GO+1P3, #174 GO+4P3): re-measures claims rather than reading them (its negative-control breakdowns have been exact), sweeps systematically (an AST prose-diff caught an author overclaim), probes empirically (injected a mutant to test an audit's pin), and discloses scope honestly. ~20 min and ~$0.07 a round (11.1M tokens ≈ $0.22 across all three, 96 % cache hit, OpenRouter billing). **Calibration: its findings have been reliable; its *remedies* are not pre-verified — measure a suggested fix like any claim** (#174 P3-1's suggested remedy failed measurement; the finding itself was right and subtle). It has not yet caught a hidden P2 on a branch that wasn't already exhaustively self-verified — widen its lane when it does. Replaced Cursor / Grok 4.6 (retired 2026-08-28, owner's call: the 256K context ceiling made large PRs a truncation risk; GLM holds them whole). |
| **Codex (GPT-6 since 2026-09-05; GPT 5.6 Sol before; from #212 round 11, 2026-09-06, ChatGPT's Daybreak Blue — GPT 5.6 Sol-based — after GPT-6 Astra's refusals)** | The highest-stakes shared mechanisms; second opinions | Its first GPT-6 round (#212 round 2) reproduced two grant-lifecycle defects round 1 had not, each with an independent control, and corrected the author's mutant count. Has absorbed #86 (4,442 insertions) across four rounds, and its NO-GO rounds have caught hidden P2s (#159's isalpha currency, #169's parser-stage envelope). Reserve it for anything touching the write gate, money/stock semantics, migrations, and the M6 security work — and as a second opinion when a GO on an unpolished branch feels too easy. Subscription upped 2026-08-28; routine rounds need no meter check. |
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
- **Give the reviewer two jobs, in order: the whole contract first, the fixes
  second.** The template says it in fixed words. A brief that specifies exactly how
  to verify the reported fixes — heads, failing assertions, mutants, the author's
  assumptions — is very good at getting those verified and steers the reviewer past
  everything outside the author's test plan; on #212, discovery metadata and the
  value space of an optional revocation field sat unchecked through four rounds of
  such briefs, and the reviewer said so (round 5). Killing every listed mutant proves
  those tests detect those defects, not completeness. So the reviewer first writes its
  own list of the feature's surfaces and each field's protocol-defined value space,
  compares it with the PR body's **coverage record**, and probes the gap before it
  verifies anything the author claimed.
- **Carry a coverage record in the PR body**, updated every round: surface by surface,
  what was checked, by what, at which head; what is unresolved; what is explicitly
  untested. Findings survive in the thread; tentative concerns, unexplored paths and
  the reasons particular checks were chosen do not — and a fresh reviewer session
  otherwise rebuilds its understanding from the newest brief alone. Where practical,
  keep one reviewer session through a PR's corrective rounds and open a fresh one
  deliberately, for an independent pass, with the record in front of it.
- **Point it at the test claim, and tell it to re-measure.** The PR body lists
  which tests fail against unfixed `main` and why; that is the claim most worth
  checking, and the author's counts are the first thing to get wrong (#109's body
  said 70 red over a measured 74, and "17 mutants" over a table of 16). Name the
  two or three things in the branch that are assumptions rather than proofs and
  invite it to push there.
- **Vocabulary:** see the mutation-testing note above.
- **One reviewer per round, a different model family from the author where you
  can.** GLM and Codex are the defaults; Claude is an option with the caveat
  written into the template's footer. Keep the working tree parked (on `main`,
  or anywhere that will not switch) for the whole review window — a branch
  changing under the reviewer cost half a round on #173 before it recovered
  via worktree.

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
7.1. **Update the coverage record** in the PR body: what this round checked and at
   which head, what it opened, what stays explicitly untested. The next reviewer reads
   it before the reply.
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
   **Family 8 in OIDC mode is the hand-run half of T2** (#192): the CI stack is local
   mode, so once per release run the matrix against a stack configured with a
   provider — `uv run python ingress_matrix.py http://127.0.0.1:8080 --mode oidc
   --public-base-url <the stack's PUBLIC_BASE_URL> --password …` — and expect zero
   failing rows; the three discovery documents, the anonymous `/mcp/` challenge's
   `resource_metadata` pointer, the six protocol routes' `no-store` (a registration
   body the SDK cannot read included) are what it proves there and cannot in local
   mode. In either mode the matrix ends with a burst at `/mcp/register` that trips
   nginx's limiter and checks its 429s carry the envelope and `no-store` — run it
   last, and expect the peer to be rate-limited for a moment afterwards.
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
