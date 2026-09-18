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
| Frontend unit (~628) | `npm test` (in `frontend/`) | vitest over `src/**/*.test.ts` only — the include glob is narrowed on purpose. Includes the i18n catalogue checks (`src/i18n/catalogue.test.ts`). |
| Frontend build | `npm run build` | `tsc -b` then Vite. Before every commit. Also the compile-time check on every static `t("…")` key. |
| Frontend lint | `npm run lint` | oxlint, then `scripts/check-palette.mjs` — refuses any stock Tailwind palette utility under `src/` (design §13.1: tokens only; `@theme` already emits no CSS for one, so the guard is what makes the regression loud). |
| Translation coverage | `npm run i18n:report` (in `frontend/`) | Markdown table, presentation only — the catalogue tests are what gate. CI appends it to the job summary. |
| E2E (~124) | `npm run test:e2e` | Playwright; reuses a running backend on :8000 and Vite on :5173, else starts them. The `setup` project (`e2e/auth.setup.ts`) signs in as the owner first — an **unclaimed** instance is claimed through the recovery command with `E2E_OWNER_PASSWORD` (default `e2e-owner-password`); a **claimed** one is only signed into, so on a dev database you claimed yourself export `E2E_OWNER_PASSWORD` to its password or the run stops and says so. The session lands in `e2e/.auth/` (gitignored); specs' own API calls go through `e2e/api.ts` (`apiContext()`), which carries the cookie, an `Origin` and the CSRF token. Creates uniquely-named data and cleans up via the API. `npx playwright install chromium` once. Three browser projects since #257: `app` (the desktop default, a mouse — every spec), and `phone` (390 × 844) and `tablet` (820 × 1180), both Chromium with a touch screen (`hasTouch` + `isMobile`, which is what makes `(pointer: coarse)` match), running the specs their `testMatch` lists — `shell.spec.ts` and `lists.spec.ts` (#258; it seeds its own rows), which `app` runs too. The `settings` project runs last, after all three: `settings.spec.ts` and `lists.settings.spec.ts` flip the instance-settings singleton, which every date on every page is written with. `--project=phone` runs one (it pulls in `setup`). A phone or tablet spec sets its size and *then* loads the page: a poll after resizing a live page can be satisfied by the layout it was meant to replace (`lessons.md`). |
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
( cd frontend && DATABASE_URL="$DSN" npx playwright test --workers=1 )   # one worker, CI's shape: the multi-worker local default fails specs from cross-file contention
psqlc plamotrack_e2e "select count(*) from kits union all select count(*) from orders union all select count(*) from retailers"   # all 0
psqlc postgres "DROP DATABASE plamotrack_e2e;"
```

Every count must be zero afterwards — a spec that leaves rows behind is a spec that
will collide with the next one.

**Proving a layout did not move** (M6.6: every PR of #257–#260 owes "1280 px and
wider unchanged"; first done on #265). Compare the branch with `main` over *one*
database, capture by capture, byte for byte and then pixel for pixel:

- **One seeded database, one API.** Seed a fresh database with the screenshot spec
  (`SCREENSHOTS=1 SCREENSHOTS_OUT=<dir> DATABASE_URL=$DSN npx playwright test
  e2e/screenshots.spec.ts --workers=1`); afterwards `frontend/e2e/.auth/owner.json`
  is a storage state a plain Playwright script can load — the cookie is for
  `localhost`, any port. Start the API from the **real checkout's** `backend/`: a
  worktree's has no virtualenv and Playwright's own `webServer` times out there.
- **`main` from a worktree on :5174, the branch on :5173.** Give the worktree its
  **own copy** of `node_modules` (`cp -cR frontend/node_modules <worktree>/frontend/`).
  A symlink puts the bundled Inter outside Vite's fs root, the page renders in a
  fallback font, and *every* capture differs from the first pixel of the wordmark.
  `npx vite --port 5174 --strictPort` takes about 40 s cold; let its first
  dependency optimisation finish before capturing, or a screenshot times out.
- **Hold still what can move:** `page.clock.setFixedTime(...)`, `deviceScaleFactor: 1`,
  `animations: "disabled"`, `caret: "hide"`, `networkidle` and `document.fonts.ready`
  before each capture; every route and the dialogs, both themes, 1440 × 900 and
  1280 × 720. No image library is installed — to diff two PNGs, draw both into an
  `OffscreenCanvas` inside a Playwright page and report the count of differing
  pixels, their bounding box and the largest channel delta.
- **Measure the noise floor first: `main` against itself.** It is not zero. On #265
  about 10 of 64 captures differed between two runs of the same code, by 1–64 pixels
  — a 15-pixel patch at the search field's icon, single pixels on borders — at a
  channel delta of up to 28. A difference is a finding when a capture's **size**
  differs or its bounding box lies **outside** the patches `main` shows against
  itself, not when the bytes differ.
- **The demo data is not every state.** It draws no mixed order (so no *pre-order*
  tag), no expanded order row, no hover. Add the states your change touches, in a
  throwaway database, and measure those too.
- **Read a difference's box before its count, and crop it.** On #259 the order
  dialogs differed from the line row down at 1280 px and from the panel's very top
  at 1440 × 900 — one cause: a row 4 px shorter, and at the size where the dialog is
  taller than the screen the focus call scrolls the overlay to its nearest edge, so a
  16 px shorter panel lands 16 px elsewhere. A crop with the differing pixels drawn
  in red (thirty lines of `OffscreenCanvas`) told the two apart from a sub-pixel
  rounding on one button's edge, which the count alone (146 pixels, delta 239)
  made look like a moved control. The row's 4 px was an empty label's margin, an
  accident `main` had; it went back in for parity, because the layout from 768 px
  up was not the milestone's to change — say which it is, an accident kept or a
  fix declared, rather than let the comparison decide.

The capture and diff scripts were throwaway (about sixty lines each); the traps
above are the part worth keeping.

**Proving a list fits its box** (M6.6; first done on #258, `frontend/e2e/lists.spec.ts`).
A table scrolls inside its own `overflow-x-auto` box, so the document never moves and
a page-level check calls a clipped edit control fine. What #258 learned doing it:

- **Measure the box, on rows.** `scrollWidth` against `clientWidth` on the table's
  box, and every control's right edge against the box's — on a list with rows in it.
  The from-empty suite sees empty states; a spec that measures seeds its own.
- **Seed ordinary rows, not the demo's.** The screenshot spec's data has no order
  that was both shipped and received, and the Orders table needs 87 px more with one
  (1040 against 953). Give every field its widest ordinary value *and* its null — a
  fold is where a null leaves a dangling separator or an empty line.
- **A seed must be the same width every run.** A base-36 run tag inside a retailer's
  name and an order number moved the table's minimum by 25 px between runs — enough
  to pass or fail a fold line on the letters the clock dealt. Digits are tabular in
  a table cell; use them where the tag sits in a width-setting cell.
- **Sweep the box, don't sample the viewport.** Nine viewports are nine points; a
  fold line a few pixels short of what its table needs is a band a few pixels wide
  between them (the second Orders fold overflowed from 866 to 927 px and no sampled
  width was in it). Set the container's `style.width` to every px from the narrowest
  box to the widest — container queries answer the box, whatever set its width — and
  collect the widths that overflow. Under a touch project *and* a mouse one: the
  44 px pencil must not cost the table anything.
- **To read what a fold state needs**, disable the fold (`@max-[1rem]`) and take the
  last overflowing width plus one. Put the line over that, not on it — and say the
  devices either side of it out loud: a rounder number 16 px higher would have folded
  every 1366 px laptop. A container query reads the box's *content* width, so a 1 px
  border is 2 px of the arithmetic.
- **`getByText` sees hidden elements.** A CSS fold keeps a hidden second copy of what
  it moves, and `expect(getByText("MS-91055")).toBeVisible()` becomes a strict-mode
  violation at widths where nothing ever folds. A test that reads a list row's text
  asks for the one on screen — `locator.filter({ visible: true })` — and "on screen
  exactly once" is that with `toHaveCount(1)`, which catches dropped *and* said
  twice. The first match for a retailer's name on a table shell is a closed
  `<select>`'s `<option>`, which is never visible — wait on a shown match.
- **A loop over no sizes passes.** A test that filters its sizes down to none for a
  project (`phone` has no table shell) is green having looked at nothing: `test.skip`
  it there by name.
- **The widest *ordinary* row is one point in the value space, and the settings are an
  axis of it** (Codex #266, finding 2). The date style and the formatting locale are
  instance settings: `full` turns "27/08/2026 · 9 d" into "Thursday, 27 August 2026 ·
  9 d", and a table measured only under the defaults was 121 px past its box at
  1280 px. Seed the *wide* row beside the ordinary one — a reference with nowhere to
  break (a USPS tracking number is 22 digits, 30 with its routing prefix), a total in
  three currencies — and run the sweep again under every date style
  (`e2e/lists.settings.spec.ts`; in the `settings` project, which waits for every
  other project, because the singleton is what every date on every page is written
  with). Assert the page is *showing* the style first — format the expected string in
  the test with `Intl`, not with the app — or a PATCH that did not take passes the lot.
- **A rigid cell is a decision about a value, so make it by the value.** `nowrap` on
  every date, or `overflow-wrap: anywhere` on every reference, changes the ordinary
  rows too: a table squeezes every column that has give, so lowering one column's
  minimum re-lays-out the rest, the desktop's included. Decide per value (a date in
  digits is rigid, one in words wraps; a run longer than the measured one may break)
  and the ordinary rows stay where the fold lines were measured — then prove that with
  the pixel comparison, not by reading the CSS.
- **A count is not a width, and a canvas is not the cell** (round 2, finding 5). The
  reference rule first said "a run longer than thirteen characters may break"; thirteen
  `W`s are 183 px where thirteen digits are 115, and the table was 33 px past its box.
  Measure the thing the constraint is in — pixels, by the browser, at the cell's own
  font and figures. Four ways of doing that were wrong before one was right: a hidden
  copy in the cell is scrollable overflow unless clipped; a copy inside a fold's
  `display: none` half has no width; a copy that is DOM text is what `getByText`
  returns, because it prefers the deepest match; and `canvas.measureText` cannot be
  told `font-variant-numeric: tabular-nums`, so its digits are narrower than the
  table's. The one that holds: a pseudo-element (`content: attr(…)`) in a clipped
  zero-size ruler the table renders once, reached through a portal.
- **`overflow-wrap: anywhere` changes the text, not only where it may break.** In
  Chromium kerning stops at a break opportunity, and `anywhere` puts one after every
  character: a 105 px word became 110 px and wrapped at its cell's edge with nothing
  squeezed. So the class goes on a value that is over budget and on nothing else, and
  "ordinary rows lay out as they did" is proved by the pixel comparison, not by reading
  the rule.
- **A browser preference is an axis too** (round 2, finding 6). Sizes in rem follow the
  browser's default font size; a phone's width does not. At 32 px an 8rem reservation
  was 256 px in a 94 px column. Launch Chromium with
  `--blink-settings=defaultFontSize=32` in the test (a launch flag, so a browser of its
  own — `chromium.launch`, the same `storageState`) and assert the identifying text
  starts and ends inside its card and the screen; assert the root font size first, or
  the flag not taking passes the lot.
- **Bounds passing is not content showing** (finding 1). A card that fits the screen
  exactly can have squeezed its own title to 0 px: beside a `shrink-0` sibling of
  unbounded length (a total in three currencies) a `min-w-0 truncate` name gives up
  everything. Assert the identifying text is visible *and has room* (its box, not its
  card's), and that what a card says is not clipped (`scrollWidth` against
  `clientWidth` on the text's own element). Run the phone's tests from 320 px: wrapping
  is decided at the narrow end.
- **"Equivalent for the seeded values" is a claim about the seed** (round 3). The author
  called four of round 2's survivors equivalent; the reviewer distinguished three with
  values the seed did not have — twenty narrow digits (182 px in the table's tabular
  figures, 114 proportionally: a ruler without the figures leaves them a plain word and
  the table past its box), a reference wider than the table's box (an unclipped ruler
  hands it to the document), and a web font held until after the first paint (thirteen
  digits sit either side of the budget in the fallback font and in Inter). Each is a
  seed or a control in `lists.spec.ts` now (`NARROW_TRACKING`, `UNBOUNDED_NUMBER`,
  `CROSSING_TRACKING`; *a reference's rule follows the font that is drawn*, which holds
  the `.woff2` requests with `page.route` and releases them after the fallback has been
  measured). When a survivor's argument names the value that would kill it, that value
  is the next seed, not the closing sentence.
- **Two points on a preference's axis, because the second decides differently** (round
  3, finding 7). The stepper past its card at 32 px was the finding, and a fix for the
  stepper alone passes 32 px. At 40 px the pencil and the toggle, not the stepper, left
  the name 38 px — the same class, other instances — and only the second point showed
  it. Test a preference at two values, the second where the first fix's neighbours are
  at their floors. A floor the tested points never reach leaves its mutant alive (the
  pencil's, the toggle's and the count's px floors at 40 px: F7e, F7i, F7k): say so in
  the tuples rather than adding a third point for its own sake.

**Proving the keyboard survives a change of representation** (Codex #266, findings 3–4;
`lists.spec.ts`, "no change of representation leaves the keyboard on `<body>`"). The
rule is one sentence — every change of representation accounts for the focused
control — and its instances are found one at a time by whoever thinks of them: the
build thought of rows, a dialog's opener and one select; the review of four more
selects and a button; a sweep of **every** control then found the pager, two links,
Export CSV and the entire navigation, in code a reviewer had already passed. So:
enumerate the focusable controls from the page, focus each, change the page under it
each way it can change — a shell's line (744 ↔ 1133 px), a fold inside one shell
(1180 ↔ 820 px: no shell change, no render, only a container query), the other shell
line (1100 ↔ 1300 px) — and assert the keyboard is not on `<body>`. Re-read the list
after every change (a shell swap replaces the nodes, and a probe that tagged them once
silently skipped everything remounted — it reported 27 losses where there were 211).
A sweep derives its subjects from the page, so say by name which controls it must
have reached, and how many; and keep the named tests beside it, because "not nowhere"
says nothing about *where*. A `ResizeObserver` cannot watch an inline element — a text
link has no size — which is why the hook watches the nearest sized ancestor.

**Run the phone specs under WebKit before calling a dialog, a picker or a focus rule
done** (#259). Every iPhone and iPad is WebKit and CI installs Chromium alone. A
throwaway config that spreads `playwright.config.ts` and sets `browserName: "webkit"`
on every project but `setup` — then `npx playwright test --config <it> --project=phone
e2e/dialog-keyboard.spec.ts e2e/dialogs.spec.ts`, and `lists.spec.ts` beside them (the
filter sheet is a `Modal`) — found three defects Chromium never shows: the trap's
Shift+Tab escape (#267), a picker result no click could pick (Safari does not focus a
button on click, so the input blurred to nowhere and #104's rule unmounted the list
before the click landed), and a submit that dropped the keyboard to `<body>` (WebKit
takes focus off a just-disabled control *after* the mutation observer has looked).
"Measured in Chromium" is a measurement of Chromium: where a rule is about an engine's
focus or its timing, measure the other engine. `npx playwright install webkit` once.

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
- **On `main` after the #193 `aud-` fold-in: 570 cases over 51 target files** — counted the way the
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
  the contract suite; 113…114 from round 13 — the fallback counts records: the fetched
  records kept by cache slot again, the no-`kid` fallback taking the last of several —
  both killed in the contract suite, with moa-108/110/112 re-anchored by that round (the
  rule is one function, `select_records`, for both paths); 115 from round 14 — the raw
  fetched array handed back to the SDK, whose skip loop chokes on an unhashable record
  `kid` — killed in the contract suite;
  all 112 killed on the branch by the tracked harness on the committed tree,
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
  regression; all 34 killed at fold-in, `-k oidc-`)
  and #193 (`aud-` — audit events, request budgets and log hygiene, PR #208, folded
  after the merge: `app/services/audit.py`, `services/auth.py`, `services/oidc.py`,
  `auth/mcp_auth.py`, `auth/mcp_oauth.py`, `routers/auth.py`, `ingress.py`,
  `log_hygiene.py`, `main.py` and — the first cases against them — the nginx
  template, the Dockerfile's `CMD` and `ingress_matrix.py`'s private output, so the
  clean-tree check covers those three paths since this fold-in; aud-1…17 hand-run
  on the branch and recorded as descriptions only, their exact anchors reconstructed
  at fold-in against `bd40687` (aud-14 re-anchored to the normalised snapshot, as
  the record said it must be); 18…37 the integration record's exact recipes and
  38…58 the P3-5/P3-6 round's; aud-34 and aud-35 stay out — the raw `$request_uri`
  in the access log and nginx's request diagnostics restored have no pytest
  witness, only the packaged log scan the release gate runs — and aud-17/aud-36,
  packaged-only in the record, are killed here by the literal assertions the P3
  round added to the four-families test; four suites join `TEST_FILES`
  (`test_audit.py`, `test_audit_privacy.py`, `test_access_logging.py`,
  `test_deployment_hygiene.py`); aud-23 survived the first pass on the record's
  reconstructed selection — the id_token-rejected test asserts the row's detail,
  not its actor — and was re-pointed at the cancel-at-provider test, which asserts
  the actor on the row the same `_refuse` writes; all 56 killed at fold-in,
  `-k aud-`).
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
| Integration | Playwright e2e (one worker, one retry, trace on first retry, HTML report uploaded **only on failure**), then the packaged Compose stack **from an empty volume** (`down -v` first — the e2e claimed the owner in the same project's database, and a claimed instance prints no token): UI/liveness/`/api/auth/session` probes (a fresh stack must say `unclaimed`), the **setup token read from `docker compose logs api`** the way an operator would, **`backend/ingress_matrix.py`** (T2/T8 — claims the stack with that token, signs out and performs a real password login through nginx; checks the `/api/` alias rejections in their normalised spellings, the canonical positives, cookie-borne writes, redirects, security headers, hostile Host/Origin and the listed CI name; mints two personal access tokens and proves the REST/MCP bearer rows; then requires each independent nginx limit on families 2, 3, 8 and 9 to answer 429; since #221 also drives a body one byte over and exactly at each declared budget — 413 in the envelope from nginx's generated exact location, the route's own answer at the budget — and a thirty-request hostile-Origin flood, all refused), **the refusal-budget count** (`ingress.origin_rejected` rows after the run between 1 and 10 — the per-address bound, not the request count; #221 item 3), an MCP `tools/list` through nginx **with the live token** by a real `fastmcp` client plus the same client refused without one, and a non-vacuous T10 scan (requires access records from both containers, then proves the run's password, PAT, session value and OAuth query/Referer probes are absent from their full logs) |

- **A pass on retry reports as `flaky` with exit 0.** Deliberate: instability is
  surfaced without blocking a PR. The lever, if it hides a real intermittent, is the
  retry count, not the artifacts.
- **A job stuck `in_progress` with every step green:** `gh run rerun <run> --job
  <id>`. Not a project problem.
- **Integration copies `.env.example` to `.env`** — the documented fresh-install
  path, no secrets — and appends `ALLOWED_HOSTS=ci.plamotrack.test` so the matrix
  has a listed name to prove. Locally the matrix runs the same way against a
  packaged stack: `uv run python ingress_matrix.py http://127.0.0.1:8080
  [--allowed-host NAME] [--setup-token=TOKEN | ] --password PASSWORD` from
  `backend/`; without a name in your `.env`, omit the flag and the listed-name rows
  are skipped. `--setup-token` (from `docker compose logs api`) claims a fresh
  stack with `--password` — spell it attached, `--setup-token=TOKEN`: a token can
  begin with `-`, which argparse reads as an option when the value is a separate
  word (#215); `--password` alone signs into a claimed one; with
  neither, the guarded positives expect the dependency's 401 and no write lands.
  The claim is real — a stack claimed by the matrix is claimed with that password.
  Signed in, it mints two access tokens for the bearer rows and revokes them at
  the end; `--token-out PATH` keeps the write one live and writes it there (mode
  0600) for a following MCP-client step — never printed. An `https://` base is
  reached through the system trust store (`--ca-cert` for a private CA);
  `--behind-proxy` skips the three hostile-Host rows a TLS proxy answers itself;
  `--hold-stream SECONDS` holds a standalone MCP stream on `/mcp/` and bare `/mcp`
  and reports the longest gap between bytes (#194).

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
| **Cursor (Grok 4.6, SpaceXAI)** | **Not on the roster** — available until 2026-09-15, then gone | Retired 2026-08-28 for the 256K ceiling; the subscription runs out on the 15th. It reviewed #219 on 2026-09-07 because the owner picked it instead of GLM in T3 Chat by mistake, and the round was a good one for the record: it wrote the feature contract before reading the author's plan, found the P3 in the gap between its list and the coverage record — a collection the branch itself classified as a grant's, purged unread — named the remedy's wrong half (the record's top level vs `idp_tokens`), re-measured the control and all 16 mutants exactly, re-sampled the race kill 3/3, and listed what it left unexamined. Until the 15th a fix round it can hold whole is fine; after, it is history. |
| **Codex (GPT-6 since 2026-09-05; GPT 5.6 Sol before; from #212 round 11, 2026-09-06, ChatGPT's Daybreak Blue — GPT 5.6 Sol-based — after GPT-6 Astra's refusals)** | The highest-stakes shared mechanisms; second opinions | Its first GPT-6 round (#212 round 2) reproduced two grant-lifecycle defects round 1 had not, each with an independent control, and corrected the author's mutant count. Has absorbed #86 (4,442 insertions) across four rounds, and its NO-GO rounds have caught hidden P2s (#159's isalpha currency, #169's parser-stage envelope). Reserve it for anything touching the write gate, money/stock semantics, migrations, and the M6 security work — and as a second opinion when a GO on an unpolished branch feels too easy. Subscription upped 2026-08-28; routine rounds need no meter check. **#236 (M6.5, 2026-09-10), four rounds:** two hidden P2s in the order clock (round 1 the SQL session's zone, round 2 Postgres's zone files against the settings' `zoneinfo` — 598 names executed), the tie P3 in round 3 (PEP 495), each with a ready reproduction and both halves of the remedy; re-measured 32 mutants and corrected the author's table twice; the visual leg (contrast composed in the browser, captures against the artboards) worked — it is the reviewer for the M6.5 PRs (owner's call). |
| **Codex through the Claude Code plugin** (OpenAI's `codex` plugin, tried on #265, 2026-09-17) | **Source-and-unit legs only; second opinions mid-session** — not a review round for anything with a browser or Docker leg | Three routes. `/codex:review` and `/codex:adversarial-review` are typed by the owner (the plugin marks them user-invoked only), take no brief, and the plain one **ran no tests**: it read the diff, type-checked and reported nothing. The **task route** (`codex:codex-rescue`) is the agent's to launch and can carry the whole brief (`--prompt-file`), but runs in a hardcoded `workspace-write` sandbox with **no approval prompts**, and **Chromium will not start inside it** (`MachPortRendezvousServer … Permission denied`) — so on #265 it delivered the compiled-CSS parity check, the decoded icons, nine unit mutants and a correction to the author's negative-control count (10 green, not 11, from arithmetic alone), and a NO-GO that meant only "browser gate incomplete". The owner then resumed the same Codex session in the Codex app, where the browser leg ran and the round ended GO with two real P3s. Untested: a backend-only PR (pytest and Postgres over TCP should work in the sandbox). The plugin's shared runtime keeps the thread locked ("open in another app") until the Claude session ends; release it with the broker half of the plugin's own SessionEnd hook before `codex resume <id>`. **Channel rule (owner, 2026-09-17): a plugin round returns its result in-session and never posts on GitHub; a round started the old way talks through PR comments** — the unattended plugin run had put an environmental NO-GO on the public thread under the owner's account. |
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

- **One line, not a wall of text:** save the finished brief to a file as well as
  printing it, and give the owner the one-line paste — *"Follow the review brief at
  `<path>`"*. Free **:8000 and :5173** before a frontend round: the e2e config reuses
  whatever is listening, and the dev database's owner password is not the suite's.
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
3. **Check the surfaces**, not the edit: `GET /meta`, the legacy MCP handshake's
   `serverInfo.version` and a modern client's `server_info` (`Client(...)` in its
   default `auto` mode, which negotiates `2026-07-28`; `mode="legacy"` for the
   handshake) all report the new number — the two eras are decided per request and
   one can be right while the other is stale (#243).
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
   --public-base-url <the stack's PUBLIC_BASE_URL>
   --log-secrets-out <private JSON path>` — and expect zero
   failing rows; the three discovery documents, the anonymous `/mcp/` challenge's
   `resource_metadata` pointer, the six protocol routes' `no-store` (a registration
   body the SDK cannot read included) are what it proves there and cannot in local
   mode. In either mode the matrix ends with a burst at `/mcp/register` that trips
   nginx's limiter and checks its 429s carry the envelope and `no-store` — run it
   last, and expect the peer to be rate-limited for a moment afterwards. Scan
   the complete API/nginx logs for every value in that private JSON, requiring
   an access record from each service first, as the CI T10 step does. This run
   also probes query/Referer values on refused and throttled callbacks; it does not perform a provider login
   itself — `--credential-file PATH` (a JSON `{cookie, csrf_token}` from a login made
   another way; the deployment gate below makes one headlessly) turns it into a
   signed-in run, which the gate's `oidc` phase is.
4b. **Deployment gate — T12 and T13 (#194), on a prepared host, not this machine.**
   `.agents/deployment-gate/README.md` has the setup (a fresh Debian host, Caddy
   with the cloudflare DNS module and `deploy/caddy/Caddyfile`, the Keycloak
   fixture, a DNS token the operator writes on the host); then from `backend/`:
   ```bash
   GATE_IDP_PASSWORD=owner-password uv run python deployment_gate.py \
     --base https://NAME --ssh root@HOST --idp https://idp.NAME --phase all \
     [--tunnel-base https://TUNNEL --tunnel-proxy CONNECTOR-IP --host-ip HOST-LAN-IP]
   ```
   Every phase must end with zero failing checks: precheck, both lockouts and their
   recoveries, the local-mode matrix over https with the stream held on both `/mcp`
   spellings, the `TRUSTED_PROXIES` observation, the OIDC-mode matrix signed in, the
   three restores with the documented commands verbatim, and — once the operator
   has added the route — the tunnel. The results block it prints goes into the
   release notes **as observed**; a number in it that was not produced by the run
   is a defect in the notes. The docs may describe a deployment only when this
   has passed against it (design §5.8).
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
