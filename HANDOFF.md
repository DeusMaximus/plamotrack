# Session hand-off log

Every agent session that changes this repo appends an entry **at the top** (newest
first) before finishing. Keep entries short and factual — the next session may be a
different agent/model with no shared context.

Template:

```markdown
## YYYY-MM-DD — <agent> — <short title>
- **Done:**
- **Decisions:**
- **State:** (tests? migrations? anything half-finished?)
- **Next:**
```

---

## 2026-08-11 — Claude Code — Triaged an external review into five hardening milestones

**Planning only. No code changed, working tree clean on `main`.** An external review of
v0.2.3-alpha (run outside this repo, and *not* checked in — the issues below are written
to stand alone) was verified against the code and filed as **23 issues across five new
milestones**, `M5 hardening — v0.2.4-alpha` through `v0.2.8-alpha`. Continuing that title
pattern rather than inventing `M5.0.x` numbers means the `AGENTS.md` roadmap needs no
renumbering — these are hardening passes inside M5, before 5.1 starts.

- **v0.2.4 (#34–#38) is the one that matters first.** Its theme is *a write changes only
  what it was asked to change*: an order edit restating line currency, kit scale and zero
  shipping; an inventory edit restating stock; a lock that computes from a pre-lock value;
  a kit delete cascading upgrade history away; an export rendering an amount in a currency
  it isn't denominated in. Clearing it is also what makes **manual UI use safe for real
  collection data** — that fell out of the theme rather than being scoped to it.
  v0.2.5 is ingress (#39), v0.2.6–v0.2.7 are the importer (#40–#48), v0.2.8 is loose ends.

- **Five decisions that are already made — don't re-litigate them from the issue text.**
  (1) **Do not reroute import through the order service** (#44). Calling `receive_order`
  would apply stock, which is rule 10 head-on. The fix is a declarative invariant pass in
  `services/portability/` that *rejects* what the service would refuse; what's shared with
  `orders.py` is the predicates, not the mutation path. (2) **No repair migration** for the
  `6cbd8315df95` legacy state (#54) — it would run today and overwrite kit statuses the
  owner has since set by hand; document it. (3) **No optimistic version columns** yet (#36)
  — locking plus dirty-field PATCH closes the same hole without three mapper changes.
  (4) **No dialog dependency** for #51; `Modal` is fifty lines. (5) The #41 plan hash
  **must exclude synthesized ids and clock defaults** (`uuid4()` at `importing.py:582`,
  `_create_stub`, the two `lambda: datetime.now(UTC)` column defaults) or preview and apply
  can never agree — that trap is what makes "just hash the whole plan" wrong.

- **Five things the review missed, found while verifying it.** `parse_int("inf")` raises
  `OverflowError`, which `_parse_row` doesn't catch — an unhandled 500, not a row error.
  `parse_int` accepts Python underscore literals (`1_000` → 1000). Comma-stripping lives in
  three places, not one (`spec.parse_decimal`, `currency.major_to_minor`,
  `format.ts:majorToMinor`). `POST /api/import/apply` is multipart and therefore
  preflight-exempt, so any page the owner visits can drive a `replace_all` cross-origin —
  that's the sharpest edge in #39, sharper than the DNS-rebinding case. And `adjust_stock`
  is MCP-only with no REST route (#55), which is *why* the browser has to PATCH absolutes.

- **The review was right about the defects and wrong about several remedies.** Worth
  knowing if anyone reads it later: it was correct that `session.get(..., with_for_update=)`
  serves stale attributes, but only one call path actually preloads (`orders.py:389`), not
  the five it listed; its `formatDate` remedy would break `received_at`, which is a real
  timestamp and *should* convert; and it treated the always-empty `kit_photos` export as a
  fidelity bug when it's deliberate until M7.

- **#41 carries the test churn.** Roughly 25 tests call the `apply()` helper without a plan
  hash (`tests/test_portability.py:70`) and become preview-then-apply. Do it there, before
  #44/#45/#46 change what a plan contains, or it gets done repeatedly. The browser already
  sends the hash, so no UI change.

- **#39 needs care on this machine specifically.** It's the only change that can lock the
  operator out of their own instance — the Proxmox LXC's hostname has to be in the new
  allowlist. Setting, default and `docs/operations.md` ship in one commit, and it gets its
  own release so nobody upgrading urgently for a data fix inherits the lockout risk. It's
  explicitly a stopgap #29 will absorb.

- **State:** no tests run this session (nothing was changed). Milestone descriptions carry
  the theme and the reasoning, so `gh api repos/:owner/:repo/milestones` is worth reading
  before picking work.

- **Next:** #34 and #35 are the cheapest and cover the paths a human can't avoid. #36 and
  #37 finish the milestone; #38 is a one-line exporter fix that belongs in the same money
  pass. Dependencies are recorded on the issues: #44/#46 need #40 and #41, #45 needs #41,
  #47 needs only #40 and can jump the queue if starter-sheet onboarding is wanted early.

## 2026-08-11 — Claude Code — Released v0.2.3-alpha

**Shipped.** Tag `v0.2.3-alpha` on `fe4e1af`, published as a pre-release. The version
bump went through PR #33 (`1a442a6`), green before merge. Milestone
`M5 hardening — v0.2.3-alpha` closed holding the one issue that shipped: #19. No
branches outstanding, working tree clean.

- **The known-issues list is empty for the first time.** v0.2.1 and v0.2.2 both carried
  items forward; this one carries nothing. Every open issue is now forward planning
  (M5.1 #22–#27, M6 #29–#30, M7 #28) and none is labelled `bug`.

- **The release notes disclose a migration that guesses**, and anyone answering a
  question about it needs to know why. Existing tool prices recorded an amount and no
  currency — that was the bug — so there is nothing to convert *from*, and the
  instance's `REFERENCE_CURRENCY` is the only candidate. The notes say to check tool
  prices entered in any other currency rather than offering a migration that would have
  to invent an exchange rate. They also state the **rollback** consequence, which the
  issue never mentioned: downgrading to v0.2.2 clears any tool price not in the
  reference currency, because the restored column cannot say what currency it holds.

- **Notes led with the import bug, not the headline feature.** A CSV naming a currency
  column with no amount column could relabel an existing order line — £42 becoming
  A$42 — which is the only thing in the release that alters data someone already had.
  The tool-cost work is bigger but affects a field nothing calculates with.

- **Version bump mechanics, confirmed again:** `backend/app/__init__.py`,
  `backend/pyproject.toml`, and the `plamotrack-backend` entry in `backend/uv.lock`
  (`uv lock`, never hand-edited). Check the two surfaces rather than trusting the
  edit — `GET /meta` and the MCP handshake's `serverInfo` both reported `0.2.3` before
  the tag was pushed. No test pins the version string, so nothing else would catch a
  missed file. Published with `gh release create --prerelease --verify-tag` so it
  attaches to an already-pushed tag instead of creating one of its own. Tags are
  annotated, subject line `vX.Y.Z-alpha — <short theme>`.

- **Why now:** the owner is about to start using this instance for a real collection.
  Cutting immediately before that matters because the #19 migration has nothing to
  guess at on a fresh database — the disclosure above is a non-event for a new install,
  and only bites instances that already hold tool prices.

- **Next:** M5.1. #23 (singleton settings) then #22 (en-AU catalogue), per the entries
  below. #23 moves `reference_currency` out of env config into the database, and
  `_default_money_currency` (importing.py) plus `_build_catalog_row` (services/orders.py)
  both read `get_settings().reference_currency` at write time — they need updating with
  it. Expect real-usage feedback to arrive alongside, and to be worth more than the
  issue text where the two disagree.

## 2026-08-11 — Claude Code — Tool cost carries its currency; a sweep rule to find the next one

**Merged to `main` in PR #32 (`a48eef9`), closing #19.** Verified green on `main` after
the merge: 220 backend tests, ruff check + format, 80 frontend tests, oxlint,
`npm run build`, 4 Playwright e2e, and `alembic upgrade head`. Branch deleted, local and
remote. `M5 hardening — v0.2.3-alpha` now holds nothing open.

Also on `main`, committed directly per the AGENTS.md exception: **`264a0d4`, a new
`AGENTS.md` section — "Fixing a defect: sweep the class first."** The numbered
architecture rules describe *classes*, so a violation found in one path is evidence
about every other path under the same rule. Enumerate them before fixing, file the
siblings, keep cross-layer cases in the shared fixture. It carries the #3 → #12 → #6 →
#19 chain as evidence, because the rule reads as generic advice without it.

- **What #19 actually was.** `tools.unit_cost_reference` was a `Numeric(10, 2)` with no
  currency column anywhere on the table — the only amount in the schema outside §6. Now
  `unit_cost_reference_minor` + `unit_cost_reference_currency`, paired null-or-present
  by a CHECK. It was the **only** `Numeric` in the schema; that claim was re-verified
  independently rather than taken from the issue.

- **The issue's plan covered three paths. The class had five.** Sweeping first found:
  the order-line select-or-create path built a `Tool` with no currency at all;
  `_apply_money_alternates` scaled every major-unit column by a column literally named
  `currency_code`, which tools don't have (¥1200 would have stored as ¥120000); and the
  importer's pair handling was hardcoded to `order_items`.

- **Two mechanisms worth knowing before you add another money column.**
  `ColumnSpec.currency_column` names the code an ALT_MONEY column is denominated in
  (defaults to `currency_code`, so order lines are unchanged). `TableSpec.money_pairs`
  lists `(amount, currency)` pairs whose currency is *optional* in the sheet — a pair
  whose currency column is `required` does not belong there. Declaring both is what
  makes a new money column work across export, import and the templates without
  touching the importer (rule 9). Confirmed: the template pack picked up all three new
  tool columns with correct help text, unprompted.

- **Ordering in the importer is load-bearing, and it bit.** `_default_money_currency`
  runs at parse time and must settle the code **before** `_apply_money_alternates`
  scales anything, because the exponent comes from the code — and it counts a
  major-unit twin as an amount, or a pre-0.2.3 `tools.csv` carrying only
  `unit_cost_reference` gets scaled before its currency exists.
  `_clear_orphan_money_currency` runs **after**, because the twin is the last chance
  for the amount to appear. Getting this backwards produced ¥120000 *and* an unpaired
  NULL that 500s. Self-review found it; reasoning about the order had not.

- **Copilot found two more, and one predates the PR.** A sheet naming a currency column
  with **no amount column at all** was written straight through: on an existing row
  that relabelled `1200 JPY` to `1200 GBP` with the number untouched — #12's exact bug,
  reachable through the importer, and present on `order_items` before this PR under the
  hardcoded guard. Generalising to `money_pairs` is what exposed it on two tables at
  once. It is now dropped with a preview message, matching `OrderItemCreate`, which
  refuses the same shape. The other: `ItemFormModal` read the reference currency into
  `useForm` defaults before the meta query resolved, so a JPY instance could file a new
  tool's cost as AUD — **the same bug `OrderFormModal` already carries a comment about**,
  reintroduced one page over while copying `currencyOptions` out of that very file.
  Gate on meta before the form exists; a fallback in `defaultValues` is not a fallback,
  it is a default.

- **The migration guesses, and the release must say so.** Existing rows had an amount
  and no currency, so there was nothing to convert *from* — the instance's
  `REFERENCE_CURRENCY` is the only candidate, and its **exponent** drives the conversion
  (a JPY instance's `45.00` is 45 minor units, not 4500). Run up and down against
  seeded rows: AUD round-trips exactly, GBP and JPY are dropped on downgrade rather than
  relabelled, both CHECKs confirmed firing. **v0.2.3-alpha needs a note telling anyone
  who recorded tool prices in a non-default currency to check those rows.**

- **The field had zero test coverage**, which is why a schema change to it passed 202
  tests silently. It has 18 now, in `test_reference_currency.py` beside the same
  invariant one table over. All the sweep fixes have negative controls — each was
  confirmed to fail with its fix reverted, including in the browser, where the useForm
  gate was checked with the API *stopped* (the modal must mount no form at all; a warm
  cache would have hidden a broken gate).

- **Honest read on the sweep rule's first outing.** It caught three instances the issue
  never mentioned. It did not catch the two Copilot found, one of which was pre-existing
  and one of which the fix introduced. So it narrows what review has to find; it does
  not replace review, and the entry above is the argument for keeping both gates.

- **Next:** cut **v0.2.3-alpha** — nothing is open in its milestone, and the version is
  still `0.2.2` in `backend/app/__init__.py`, `backend/pyproject.toml`, and
  `backend/uv.lock` (`uv lock`, never hand-edited). After that, M5.1: #23 (singleton
  settings) then #22 (en-AU catalogue), per the entry below. **#23 moves
  `reference_currency` out of env config into the database** — `_default_money_currency`
  and `_build_catalog_row` both read `get_settings().reference_currency` at write time
  and will need updating with it.

## 2026-08-11 — Codex — Published the M5.1 settings roadmap

- **Done:** GitHub planning now tracks #19 in `M5 hardening — v0.2.3-alpha`,
  M5.1 implementation issues #22–#27, M7's storage decision in #28, and M6's
  threat-model and owner-auth decisions in #29–#30. PR #31 merged the matching
  `AGENTS.md` and `docs/design.md` updates at `0ec250f` (`fbee2bd` plus Copilot's
  one-word grammar fix `ed6c0a3`).
- **Decisions:** plamotrack remains single-owner. Interface language, formatting
  locale, timezone, date style, hour cycle, and reference currency are
  instance-wide settings; `en-AU` is the canonical fallback; language and region
  stay independently selectable; additional languages arrive through reviewed
  PRs; Settings absorbs Data. M5.1 does not require a non-English translation.
- **State:** `main` is aligned with `origin/main`. PR #31's Backend, Frontend, and
  Integration checks are green. This was documentation/planning work, so no local
  application tests were run. The merged feature branch still exists locally and
  on `origin`.
- **Next:** implement #19 first, then the #22 catalogue foundation and #23 settings
  service. Sequence #24–#27 from those dependencies, and do not describe the
  planned settings endpoints as implemented before they exist.

## 2026-08-10 — Claude Code — Released v0.2.2-alpha

**Shipped.** Tag `v0.2.2-alpha` on `b911dae`, published as a pre-release. Version bump
went through PR #21 (`61a6d89`), green before merge. Milestone
`M5 hardening — v0.2.2-alpha` closed holding the four issues that shipped: #12, #6, #9,
#17. No branches outstanding.

- **The first release in this run whose known-issues list carries nothing forward.**
  v0.2.1-alpha named #12 and #6; both are fixed here. The only known issue now is #19,
  which is new and disclosed as needing a schema migration.
- **The release notes disclose a behaviour change**, and the next person answering a
  question about it needs to know why: amounts recorded in **HUF, COP, IQD or MGA** may
  now read smaller than they were entered. Those four are where the browser (following
  CLDR, which gives them no decimals) and the CSV importer (assuming two) disagreed, so
  what was stored depended on which path was used. There was no single correct prior
  reading — that *was* the bug — so the notes say to check and re-enter rather than
  offering a migration that would have to guess. Every other currency was consistent.
- **Version bump mechanics, confirmed again this time:** `backend/app/__init__.py`,
  `backend/pyproject.toml`, and the `plamotrack-backend` entry in `backend/uv.lock`
  (`uv lock`, never hand-edited). Worth actually checking the two surfaces rather than
  trusting the edit — `GET /meta` and the MCP handshake's `serverInfo` both reported
  `0.2.2` before the tag was pushed. Published with
  `gh release create --prerelease --verify-tag` so it attaches to an already-pushed tag
  instead of creating one of its own. No test pins the version string.
- **Why the release went out before #19:** raised as a question, decided deliberately.
  Since everyone runs from `main`, a schema migration landing there is immediately
  everyone's migration — so a tag *immediately before* one is what makes
  `docs/operations.md`'s "export an archive before upgrading" actionable. The newest tag
  had been v0.2.1-alpha, which still contained both bugs since fixed, so the only
  rollback point on offer was a worse one.
- **Next:** #19 is the only open issue and has no milestone. Estimated 1.5–2.5 hours;
  see the notes on it below and in the issue. It wants a `M5 hardening — v0.2.3-alpha`
  milestone if someone picks it up.

## 2026-08-10 — Claude Code — CI keeps its evidence; #19 filed

**Merged to `main` in PR #20 (`7d7a36f`), closing #17.** Verified green on `main` after
the merge: 202 backend tests, ruff check + format, 80 frontend tests, oxlint,
`npm run build`, 4 Playwright e2e. Branch deleted, local and remote. Config only — no
application code touched.

- **Why it existed:** a red Integration job left a console excerpt and nothing else,
  though Playwright had already written `test-results/…/error-context.md`. Telling a
  flake from a regression on PR #16 meant re-running the job and hoping it disagreed
  with itself. It did, but that isn't a method.
- **What CI does now** (`frontend/playwright.config.ts` + the Integration job):
  `retries: 1` on CI and 0 locally; `trace: "on-first-retry"`; the HTML reporter on CI;
  an `if: failure()` upload of `playwright-report/` + `test-results/`, pinned by commit
  SHA like every other action in the workflow. Plus `workers: 1` on CI — `fullyParallel:
  false` only serialises *within* a file, so both specs had been running at once against
  one database and one API process, which is the likeliest source of the original
  contention.
- **A flaky test no longer fails the build.** Passing on retry reports as `flaky` with
  exit code 0. That is deliberate: it surfaces instability without blocking a PR, and
  the trade is that a genuinely intermittent bug can sit inside a green build. If that
  becomes a problem, the lever is the retry count, not the artifacts.
- **How it was verified — worth copying.** The `if: failure()` path was exercised on
  real CI, not just locally: one commit failed an e2e on purpose, the next removed it,
  so the PR's own run history holds a red run and a green one. The red run attached a
  712 KB artifact containing the browsable report, `error-context.md` from both attempts,
  and a 42 KB `trace.zip` (verified to hold the network log and per-step screenshots,
  not an empty shell). The green run produced **0 artifacts**, which is what proves the
  gate works rather than uploading on every build. An artifact step nobody has watched
  run is a guess.
- **Also filed: #19** — `tools.unit_cost_reference` is `Numeric(10, 2)` with **no
  currency column on the table at all**, confirmed against the live schema. Two §6
  violations in one field: money as a scaled decimal, and an amount whose currency is
  unrecorded. `scale 2` means a KWD tool cost cannot even be represented — Postgres
  rounds `1.234` to `1.23` going in. Unmilestoned so it doesn't hold up v0.2.2-alpha.
  The issue records that `InventoryPage.tsx:131`'s `step="0.01"` is **correct** and
  should not be "fixed", and that the design question — per-row currency, or declare the
  field to be in the instance's reference currency — wants deciding before any migration.
- **Next:** cut **v0.2.2-alpha**. Nothing is open in its milestone.

## 2026-08-10 — Claude Code — format.ts gets tests, sharing its cases with Python

**Merged to `main` in PR #18 (`e164f0d`).** Verified green on `main` after the merge:
202 backend tests, ruff check + format, 80 frontend tests, oxlint, `npm run build`,
4 Playwright e2e. Branch deleted, local and remote. No behaviour change — tests and
tooling only. Follow-up to #6 in the same session; read that entry first.

- **Why:** `frontend/src/lib/format.ts` had no tests at all, and both defects found in
  it while fixing #6 were cases where the browser and Python disagreed about what an
  amount was worth. One was caught by reading, the other by review. Nothing in the repo
  would have caught a third.
- **The shared fixture is the point.** `frontend/src/lib/__fixtures__/money-cases.json`
  is read by **both** `format.test.ts` and `backend/tests/test_currency.py`. Two
  hand-maintained lists drift, and a drifted pair shows up as a green test on each side
  and a wrong number in the database. **Add a cross-layer case there, not to one suite.**
  Confirmed with a negative control: editing one value fails both suites.
  Suite-specific behaviour stays local — unparseable input and `stepFor` in the browser,
  `Decimal` arguments and the unknown-code warning in Python.
- **Two things that will bite anyone touching the frontend test setup:**
  - vitest's default include glob matches `e2e/*.spec.ts`, which only Playwright can
    run. `test.include` in `vite.config.ts` is narrowed to `src/**/*.test.ts` for that
    reason — widening it breaks `npm test`.
  - The fixture is **imported**, not read with `readFileSync`. Reading it would need
    `"node"` in `tsconfig.app.json`'s `types`, which would hand application code Node's
    globals; `resolveJsonModule` is the cheaper trade. Bundle size is unchanged.
- **Review:** two comments, one of each kind, both answered on the PR.
  - **Legitimate:** the `formatMoney` test asserted `toContain("1.234")` against
    `Intl.NumberFormat(undefined, …)` output. In de-DE that string is `1,234 IQD`, and
    the companion `not.toContain(".")` on 1200 JPY fails there too — German groups with
    a full stop, so the test would have reported correct behaviour as a bug. Green on CI
    only because the runner is en_US. Fixed in `4891f43`: expectations now compare
    against a formatter handed the same digit count, which is locale-independent by
    construction, plus one assertion that `formatMoney` does *not* match unaided `Intl`
    (without it the rest would still pass if the exponent went back to CLDR). Verified
    under en_AU, de_DE, fr_FR, ja_JP and C.
  - **Wrong:** "vitest doesn't expose `test.for`". It has since 2.1 — it's in
    `@vitest/runner`'s types, `typeof test.for === "function"`, `tsc -b` type-checks the
    file, and all 80 cases run by name. Pushed back on the PR rather than changing code,
    so it isn't left standing for the next reader.
- **Next:** cut **v0.2.2-alpha** — see the entry below for what it clears and the
  version-bump mechanics. `M5 hardening — v0.2.2-alpha` has nothing open.

## 2026-08-10 — Claude Code — Issue #6: ISO 4217 minor units, both halves

**Merged to `main` in PR #16 (`cc8cc19`), closing #6.** Verified green on `main` after the
merge: 180 backend tests, ruff check + format, `npm run build`, oxlint, 4 Playwright e2e.
Branch deleted, local and remote.
**#6 moved out of M5.1 into `M5 hardening — v0.2.2-alpha`** (agreed with the human) —
M5.1 now has nothing open, and that milestone is releasable.

- **Done:** new `backend/app/services/currency.py` holds the exponent table and the
  three conversions, moved out of `portability/spec.py`; `frontend/src/lib/currency.ts`
  mirrors it and supplies `stepFor()`; the three money inputs in `OrdersPage.tsx` derive
  `step` from the relevant currency (unit price and shipping from the order's, converted
  price from the *snapshot's* — §6 lets them differ).
- **The finding that changed the fix.** The issue and the previous hand-off both had the
  frontend down as the correct half, deriving the exponent from `Intl`. It isn't. `Intl`
  reports CLDR *presentation* digits, which follow everyday practice and move between ICU
  releases: Chromium 151 gives **IQD 0, HUF 0, COP 0, MGA 0** where ISO 4217 gives 3, 2,
  2, 2. So the two layers already disagreed for HUF and COP — ordinary currencies, not
  just the exotic ones the issue named — and worse, an exponent read from the runtime
  means a *browser update* can change what a stored integer is worth. That's the §6
  failure mode, so `Intl` no longer decides the exponent anywhere; it still picks symbol,
  grouping and placement, with our digits passed in explicitly.
- **Decisions** (the two the last session reserved, both put to the human):
  - **ISO 4217 wins over CLDR** for the stored exponent. Consequence to know about:
    HUF/COP/IQD/MGA amounts now display with ISO decimals, and any row already entered
    in those four codes is reinterpreted. Those rows were already ambiguous — the two
    layers disagreed about them — so there was no consistent prior meaning to keep.
    Per-locale *display* digits stay open for M5.1 and are noted in §10.
  - **Unknown codes: accept everywhere, warn on CSV import.** Rejecting would strand an
    instance already holding an obscure code; silence is what #6 objected to. The warning
    lands in the preview, where a typo'd `AUS` is still free to fix.
- **Also fixed, same criterion:** `majorToMinor` scaled through a float, so `1.005` AUD
  was 100 minor units in the browser and 101 in Python. It now shifts the decimal point
  through the string and rounds half away from zero, like `Decimal` does.
- **`InventoryPage.tsx:129` is not part of this** — the last hand-off called it the
  fourth money input. `Tool.unit_cost_reference` is `Numeric(10, 2)` with **no currency
  column** and plain `parse_decimal` in the spec, so it never touches the exponent at
  all; `step="0.01"` matches the column's real scale. Money stored as a scaled decimal
  with its currency unstated is a separate §6 inconsistency and wants its own issue.
- **State:** `tests/test_currency.py` is new (65 cases): exponents, both conversions,
  round-trip, unknown codes, and `test_frontend_mirrors_the_same_table`, which parses the
  TS table and fails if the two copies drift — the frontend has no unit-test runner, so
  that guard lives on the backend side. Three import/export tests added to
  `test_portability.py`. Negative controls run: reverting the exponent table fails 12 of
  them, removing the warning call fails the warning test, and the rest hold either way.
  Verified live too — an order stored at `unit_price_minor: 1234` KWD opens with
  `step="0.001"`, validates, and re-saves byte-identical (the thing the issue said was
  impossible); switching that form to JPY flips `step` to `1` and correctly rejects
  `1.234`. All probe data deleted from the dev database.
- **Review caught a regression, fixed in `061bb4c`.** Scaling by moving the decimal point
  fixed the rounding mismatch but the regex accepted only plain decimals, so `"1e2"` fell
  through to the zero returned for unparseable input. Not hypothetical:
  `<input type="number">` treats `1e2` as valid and passes it through verbatim, `Decimal`
  reads it as 100, and the `parseFloat` being replaced did too — so the commit meant to
  make the layers agree introduced a case where they didn't, and it failed **silently**
  (non-empty field, `required` satisfied, unit price saved as 0). The exponent now folds
  into the same decimal-point shift as the currency's digits. Checked against the backend
  across 23 inputs with no disagreement.
- **Known gap, deliberately not closed here:** `frontend/src/lib/format.ts` has **no
  automated tests**. Both defects in it this session — the float rounding and the exponent
  regression — were found by reading and by review, not by a test. The backend drift test
  pins the exponent *table* only, not the conversion logic.
- **Next:** two things, in this order.
  1. ~~**Frontend test runner.**~~ Done in PR #18 — see the entry above.
  2. **Cut v0.2.2-alpha.** It clears *both* known issues the v0.2.1-alpha notes shipped
     with (#12 and #6). Version lives in three places that move together; see the
     2026-08-10 entry on #3 for the mechanics. Release notes must mention that amounts
     already recorded in HUF, COP, IQD or MGA are reinterpreted by the ISO exponent.
- **Also opened:** #17 (CI keeps no Playwright artifacts and has no retries, so a flaky
  e2e is indistinguishable from a regression — cost a re-run to establish during this PR;
  filed under M9).

## 2026-08-10 — Claude Code — Issue #9 docs, and the #6 hand-off

**Merged to `main` in PR #15 (`b1b5879`), closing #9.** Docs only. Branch deleted, local
and remote. `M5 hardening — v0.2.2-alpha` now has **nothing open** — #12 and #9 are both
in, so the milestone is releasable whenever you want it.

- **Done:** `docs/import-export.md` said a blank starter-sheet currency means AUD; it
  means the instance's `REFERENCE_CURRENCY`, and the downloaded template's example rows
  already arrive filled in with it. Checking nearby prose (the issue's third criterion)
  turned up the design notes' known-limitations list still calling AUD "the
  reference-currency assumption", two releases stale.
- **Review:** Copilot caught that the replacement understated #6 — "can't be typed" is
  true of the web form only. Corrected in `73a5045` and worth keeping straight, because
  the two layers fail in opposite directions:
  - **Web form:** `step="0.01"` on every money input, so `1.234` fails constraint
    validation and the form (not `noValidate`) blocks submission. An order that already
    holds a three-decimal amount can't be re-saved *unchanged* — the field is invalid on
    arrival. Obstructive, visible, destroys nothing.
  - **CSV layer:** `minor_fraction_digits()` in `portability/spec.py` returns 2 for
    anything outside `ZERO_DECIMAL_CURRENCIES`, so KWD `1.234` is accepted and stored as
    `123` minor units, then exported as `12.34`. Silent, and off by a factor of ten.

### Next session: #6, then release v0.2.2-alpha

**Recommendation: do #6 first, and don't wait for M5.1.** It's arguably misfiled there.
A currency's minor-unit exponent is a property of the currency, not of the reader — KWD
has 1000 fils whether the UI is English or Japanese — so M5.1's string catalogue and
locale-aware *formatting* neither help it nor get duplicated by it. `formatMoney` on the
frontend already derives the exponent from `Intl` and is already correct; M5.1 would not
revisit either half of #6. And the CSV half isn't an i18n nicety at all: it's the third
member of the #3 / #12 family, where the stored number means something other than what
it says.

Scope is small — the exponent table wants seven three-decimal codes (BHD, IQD, JOD, KWD,
LYD, OMR, TND) and two four-decimal (CLF, UYW) beside the existing zero-decimal set, plus
`step` derived from the same rule in the four money inputs (`OrdersPage.tsx` ×3 after the
#3 field landed, `InventoryPage.tsx` ×1).

**One decision is open and belongs to the human, not the next agent.** What should an
*unrecognised* currency code do? Today both layers silently assume two decimals, which is
how a typo'd code quietly becomes a wrong amount — and #6's own acceptance criteria
object to exactly that silence. The options are keep silent-2, accept but warn on import,
or reject outright. My recommendation was **warn on import, accept in the API**: rejecting
breaks anyone already storing an obscure code, and silence is the thing being complained
about. Not agreed yet — ask before implementing.

Release after that: v0.2.2-alpha headlines #12 (the import relabelling fix), with #9 and
#6 alongside. Doing #6 first is what lets its notes drop **both** known-issue bullets that
v0.2.1-alpha shipped with, rather than repeating one. See the previous entry for the
version-bump mechanics.

## 2026-08-10 — Claude Code — Issue #12: CSV import stops relabelling a snapshot

**Merged to `main` in PR #14 (`daaed3c`), closing #12.** Verified green on `main` after
the merge: 113 backend tests, ruff, `npm run build`, oxlint. Branch deleted, local and
remote. Not released — `v0.2.1-alpha` ships with this bug and names it as known, so this
is the headline of the next one.

- **Done:** `_pair_converted_snapshot()` stamped the instance reference currency onto
  any `order_items` row carrying an amount and no currency, *including rows that already
  had one* — a merge import correcting an amount turned a stored `4200 GBP` into
  `4400 AUD`. Rows now record what the importer invented rather than read, in
  `_Row.filled`, and `_defer_filled_snapshot_currency()` resolves an invented currency
  against the row's target during classification.
- **Decisions:**
  - **Where it runs is the whole fix.** Classification is after matching (so
    `row.target` exists) and before the diff (so the change list compares the value that
    will really be written). The preview therefore stops reporting a currency change it
    won't make — no new `plan_hash` contract, no `spec.py` change. **#12's own claim that
    this had to happen at parse time was wrong**; reading the planner rather than
    planning around the assumption is what caught it.
  - Two behaviours deliberately unchanged, now pinned by tests so they don't get
    "fixed": a blank **cell** in a column the sheet includes still means the instance
    default (the column help promises it, and including a column is an instruction, not
    silence), and a row with nothing recorded still gets the default filled in, which the
    paired CHECK constraint requires.
- **State:** 4 new tests in `test_reference_currency.py`. Negative control run: the two
  aimed at the bug (apply *and* preview) fail without the fix; the two guarding
  unchanged behaviour pass either way. Verified live through `/import/preview` and
  `/import/apply` as well, and all probe data was deleted from the dev database.
  Copilot's review generated no comments.
- **Next:** #9 is the only thing left in `M5 hardening — v0.2.2-alpha` — a docs issue,
  labelled good first issue. After that the milestone is releasable; #6 (minor units,
  both halves) is the other known issue named in the v0.2.1-alpha notes and sits in M5.1.

## 2026-08-10 — Claude Code — Issue #3: order edits stop erasing the §6 snapshot

**Merged to `main` in PR #11 (`6d6b12e`), closing #3, and shipped as `v0.2.1-alpha`
(PR #13 → `3e19d4f`).** Verified green on `main` after the merge: 109 backend tests,
ruff, `npm run build`, oxlint. Both branches deleted, local and remote; local `main`
matches `origin/main`.

**Release note for whoever cuts the next one:** the version lives in three places that
must move together — `backend/app/__init__.py`, `backend/pyproject.toml`, and the
`plamotrack-backend` entry in `backend/uv.lock` (regenerate with `uv lock`, don't hand-
edit). `__init__.py` is what `GET /meta` and the MCP `serverInfo.version` report, so it
has to be on `main` before the tag. No test pins the string. Published with
`gh release create --prerelease --verify-tag` so it attaches to a tag already pushed
rather than creating one of its own.

**Milestones:** `M5 hardening — v0.2.1-alpha` is closed, holding the three issues that
shipped (#3, #7, #8). The two that didn't — #12 (CSV import relabels a snapshot's
currency) and #9 (starter-sheet currency docs) — moved to a new
`M5 hardening — v0.2.2-alpha`, and both went out documented as known issues in the
release notes. #12 is the natural headline for that release: it's the same §6 invariant
as #3, through the import path instead of the API.

- **Done:** Two commits, `6ba87ac` + `be80b31`.
  Reproduced #3 first against the live dev API — a `PATCH` carrying only a quantity
  turned `7350 AUD` into `None None` — then fixed both halves:
  - `_apply_converted_snapshot()` in `services/orders.py` reads `model_fields_set`, so
    an **omitted** `converted_price_minor` leaves the stored pair alone; an explicit
    `null` clears it. `_add_line`'s create path is untouched.
  - `OrdersPage.tsx` no longer recomputes the snapshot. `snapshotIsDerivable()` allows
    derivation **only for a line being created** in the instance's own currency;
    anything already stored round-trips in the currency it was recorded in, through a
    new optional `≈ [amount] CODE` input (blank = none, and blanking a populated one
    clears it). The field is the only way the browser can change a snapshot now.
  - Schema descriptions on both `converted_*` fields (so the rule is in the generated
    OpenAPI, not just comments), `OrderItemUpsert`'s docstring, and design notes §6.
  - `be80b31` closes a hole Copilot's review found in the first commit and I'd missed:
    resolving the code through `_converted_snapshot()` meant an amount-only `PATCH`
    restamped a stored `GBP` snapshot as the instance default — £42.00 reissued as
    A$43.00 from a request that never mentioned currency, which is the same
    config-overwrites-a-record failure the commit was written to stop. The code now
    falls back **explicit payload → already recorded on the line → instance default**.
    Explicit code changes and the create path both behave exactly as before.
- **Decisions:** Issue options **1 + 2**, not the 409 guard (option 3). The rejected
  shortcut is worth knowing about: "purchase currency == `REFERENCE_CURRENCY` → just
  recompute" silently restamps a JPY purchase's AUD snapshot as JPY once the operator
  moves the setting, and "amount != unit price → recompute" discards an imported
  AUD 95 against an AUD 100 line. Both are recorded facts; neither is derivable. The
  cost is that single-currency instances now see an `≈` row on existing lines that
  mostly restates the price — deliberate, and cheap to hide later if it grates.
- **State:** 109 backend tests pass (104 + 5 new in `test_reference_currency.py`),
  ruff check/format clean, `npm run build` + oxlint clean, 4 Playwright tests pass
  (new `e2e/order-snapshot.spec.ts` + the happy path). Negative controls run: the new
  backend test fails without the service fix, and the new e2e `L == R` case fails
  against the old frontend rule (GBP 4200 overwritten by AUD 10000). Also checked by
  hand in the browser with `REFERENCE_CURRENCY` moved to `JPY` — a JPY order's AUD
  snapshot survived a quantity edit. `.env` was restored byte-for-byte afterwards and
  all test data was deleted from the dev database.
- **Review:** Copilot's first pass found the `be80b31` bug above; its re-review of the
  fix generated no new comments. Four suppressed nits are left undone and are all
  cosmetic: three grammar tweaks (`OrdersPage.tsx:157`, `api/types.ts:191`,
  `design.md:411`) and the non-null assertion in `findOrder()` in
  `e2e/order-snapshot.spec.ts:51`, which would make a missing order fail as a cryptic
  `TypeError` rather than a readable assertion. Worth a sweep if someone's passing.
- **Next:** Two bugs found while checking this work were written up rather than fixed
  in it, both deliberately:
  - **#12 (new)** — the CSV importer relabels a stored snapshot's currency exactly as
    `be80b31` stopped the service doing: a merge import carrying `converted_price_minor`
    with no currency column turned `4200 GBP` into `4400 AUD`. Reproduced. Not a copy of
    the service fix: `_pair_converted_snapshot()` runs at parse time, before a row knows
    its update target, and the resolution has to land before the preview is computed or
    `plan_hash` stops meaning anything.
  - **#6 (commented)** — the **frontend** half of the minor-units bug: the money inputs
    hardcode `step="0.01"`, so a 3-decimal currency (KWD, BHD, CLF…) can't be typed, and
    an existing 3-decimal order can't be re-saved from the UI at all, since the form
    loads a value its own input calls invalid. The fix is `step` derived from
    `minorFractionDigits()` across all three inputs plus a decision on unknown codes —
    #6's job, and it touches InventoryPage, which #11 otherwise doesn't.

  Issue #9 untouched.

## 2026-08-10 — Codex — PR #10 Postgres review follow-up

- **Done:** Opened PR #10 for issues #7 and #8, reviewed all three Copilot threads,
  and pushed follow-up `3d74317`. The README now labels 5432 as the default dev
  host port, tests derive their default connection from the same `.env`/`POSTGRES_*`
  settings, and the feature branch no longer carries session bookkeeping.
- **Decisions:** Tests keep a separate sibling `<database>_test` database and retain
  `TEST_DATABASE_URL` as the explicit full-connection override. `HANDOFF.md` remains
  a direct-to-`main` exception rather than part of feature PRs.
- **State:** 104 backend tests passed against an isolated Postgres using custom
  credentials, database name, and port 55433 without `TEST_DATABASE_URL`; Ruff
  check/format and `git diff --check` pass. The disposable database was removed.
  PR #10 Backend, Frontend, and Integration checks all pass.
- **Next:** Review/merge PR #10. Issues #7 and #8 remain open until merge.

## 2026-08-10 — Codex — Add GitHub Actions CI

- **Done:** Added `.github/workflows/ci.yml` on `codex/add-github-ci`: read-only,
  SHA-pinned Backend, Frontend, and Integration jobs for PRs and pushes to `main`.
  Backend runs Ruff check/format plus 104 Postgres-backed tests; Frontend runs
  oxlint plus the production build; Integration runs Playwright, builds the full
  Compose stack, probes UI/API/OpenAPI, and performs an MCP `tools/list` through nginx.
- **Decisions:** Python 3.12, Node 22, Postgres 16; no version matrix, coverage gate,
  release automation, or required-check repository setting yet. Concurrent stale
  runs cancel. Public-fork code receives no secrets and only `contents: read`.
- **State:** CI is merged on `main` in PR #4 (`05ed745`). Its first run caught that
  Integration had no gitignored `.env`; the fix copies `.env.example`, exercising the
  documented fresh-install path without repository secrets. PR #5 (`78efd31`) fixed
  both uv cache globs after the post-merge run showed they resolved to
  `backend/backend/uv.lock`. PR checks and both push-to-`main` runs are green; the
  latest runs Backend, Frontend, Playwright, the packaged Compose stack, ingress
  probes, and a live MCP handshake. Both remote feature branches were deleted, their
  local branches and stale refs are cleaned up, and local `main` matches `origin/main`.
- **Next:** After several stable runs, consider making Backend and Frontend required;
  promote Integration only once its runner behaviour is proven non-flaky.

## 2026-08-10 — Claude Code — M5 installability + neutral reference currency

**Merged to `main` in PR #2 (`c9988c8`), released as `v0.2.0-alpha`.** Branch deleted.
Verified green on `main` after the merge: 104 backend tests, ruff, `npm run build`,
oxlint, and `docker compose up -d --build --wait` exiting 0.

**Open follow-up: issue #3** — editing an order line silently discards its conversion
snapshot. Pre-existing (the old AUD column did the same), found during review of #2,
reproduced and written up rather than fixed there. Worth settling before M7 adds more
edit surfaces to order lines. Don't rediscover it from scratch.

- **Done — reference currency (pulled forward from M5.1):**
  - `converted_price_aud_minor` → `converted_price_minor` + `converted_currency_code`.
    Migration `2b293c6fd496` **renames** (doesn't replace) and backfills `'AUD'`;
    downgrade is deliberately lossy for non-AUD rows and says so. Round trip verified.
  - New `REFERENCE_CURRENCY` setting (default AUD, validated as ISO 4217). The code is
    stamped **at write time** by `_converted_snapshot()` in `services/orders.py` —
    never read from config on the way out, or every historical amount would change
    meaning when the operator edits an env var. Paired CHECK constraint.
  - New `GET /meta` (version + reference_currency). The order form reads it; it gates
    its render on the query because react-hook-form snapshots defaults at mount and
    would otherwise stick a new order on the fallback currency.
  - **CSV alias mechanism** on `ColumnSpec`: `aliases` + `alias_fills`. The retired
    header still imports and carries `AUD` in with it, because the old *name* asserted
    the currency — an instance on JPY must not reinterpret those rows. Exports only
    emit current names. 13 new tests in `tests/test_reference_currency.py`.
- **Done — M5 packaging:** `web` (nginx) + `api` + one-shot `migrate` + `db`. Only
  `web` published, loopback, `${WEB_PORT:-8080}`. Images build from source in-repo —
  registry publishing stays in M9. `/readyz` (real `SELECT 1`) is the healthcheck;
  `/healthz` stays liveness-only.
- **Three things found by testing, not by reasoning — don't "simplify" them away:**
  1. **nginx `resolver 127.0.0.11` + variable upstream.** A literal hostname in
     `proxy_pass` resolves once at startup and caches forever, so recreating `api` on a
     new address — *what upgrading does* — 502s everything until `web` restarts too.
     Reproduced by squatting api's address: 502 before, 200 after.
  2. **`proxy_buffering off` on `/mcp`.** Verified a full MCP session (initialize →
     tools/list → tools/call) through the proxy, chunked SSE intact.
  3. **`location = /openapi.json`.** `/api/docs` rendered fine but its schema fetch hit
     the SPA fallback and got `index.html` with a 200. Swagger would show "failed to
     load API definition".
  - Also: `/mcp` without the trailing slash is now *served*, not redirected.
    `serverInfo.version` was reporting FastMCP's `3.4.5` under plamotrack's name; now
    `app.__version__`.
- **Done — exposure docs (`f6a69c4`):** `WEB_BIND` works exactly like `POSTGRES_BIND`
  (it's the host-IP field of the same publish syntax), but the *risk* isn't symmetric:
  Postgres on `0.0.0.0` still has a password, the web ingress has nothing. New
  "Reaching it from another machine" section in `docs/operations.md` gives three
  options best-first — SSH tunnel, private/VPN address, then LAN — plus the Docker
  iptables surprise (published ports are forwarded, not delivered to the host, so
  `ufw deny` does **not** block them; the bind address is the real control).
  Deliberately ships **no** reverse-proxy config: a TLS/auth reference belongs with M6
  where it can be tested against the MCP streaming path.
- **State:** 102 backend tests pass, ruff clean, `npm run build` + oxlint clean,
  Playwright e2e passes. Verified on a clean volume: `up -d --build --wait` exits 0,
  all six migrations run, UI/API/MCP/openapi all 200 on an empty instance. Failure path
  verified too — a migration that can't connect leaves `api` and `web` in `Created` and
  compose exits **1**. The documented `pg_dump`/`pg_restore` procedure was run
  end-to-end and the conversion snapshot survived it.
- **Screenshots need no action.** They were shot with Playwright, which captures the
  page viewport only — no browser chrome, so no `:5173` address bar to go stale against
  the README's new `:8080`. Checked all six. The UI in them is also unchanged by this
  work (none show the order form modal, the only screen that moved).
- **Next:** M5.1 proper is now just the three i18n workstreams — frontend string
  catalogue (~200–260 keys, `react-i18next` recommended, OrdersPage is the big one),
  locale-aware formatting (small; only 19 directional Tailwind utilities to swap), and
  structured error codes (48 raise sites; the codes become permanent API surface, so
  pin them with tests). Estimated 4–5 sessions. The reference-currency piece that used
  to sit in M5.1 is done — don't re-plan it.

## 2026-08-09 — Codex — Public roadmap reprioritisation (merged)

- **Done:** Reworked the public roadmap across `docs/design.md`, `README.md`,
  `AGENTS.md`, and milestone-bearing code/config comments.
- **Decisions:** M5 = full local Compose install; M5.1 = internationalisation
  foundation and neutral reference currency; M6 = single-owner auth, OAuth MCP,
  and tested VPS deployment; M6.1 = dual-era MCP `2026-07-28`; M7 = photos;
  M8 = public showcase after protected admin/MCP ingress; M9 = open-source ops.
- **State:** Documentation/comment-only work committed as `8f87776`, pushed, and
  merged to `main` in PR #1 (`ade9d2a`). Local `main` is fast-forwarded to that
  merge. `git diff --check` was clean; no runtime tests were needed.
- **Next:** Implement M5 packaging with one loopback-bound ingress, internal API/db,
  controlled migrations, health checks, and upgrade/backup docs.

## 2026-08-06 — Claude Code — Public alpha SHIPPED: repo public, v0.1.0-alpha

**The repo is public and v0.1.0-alpha is released.** Everything below is on
`main`: `058bca4` (docs + README + screenshots), `a88f796` (loopback binding),
`5f790e7` (pool_pre_ping), `12a6ac0` (screenshot disclaimer). Release tagged at
`12a6ac0`, marked **prerelease** so GitHub doesn't badge it "Latest" and the
alpha framing survives outside the notes body.

Repo settings now: visibility public; About description was already the §10.1
functional text; topics added (gunpla, plamo, model-kits, self-hosted, fastapi,
react, mcp, mcp-server, postgres, docker). Verified anonymously after the flip —
README, screenshots and design notes serve 200, `.env` serves 404.

**Branching changed with it:** feature work goes on a branch + PR now, direct-
to-main is retired. See the Git conventions section in AGENTS.md.

- **Done — publishing the design doc:**
  - **Now tracked at `docs/design.md`** (was the untracked
    `plamotrack-design-doc.md`; its `.git/info/exclude` line is removed, so
    that old filename is no longer ignored anywhere).
  - Sanitised for an audience of strangers: internal-project references
    replaced with the underlying rationale, personal phrasing removed, and the
    two-port MCP sketch corrected to the `/mcp` route that was actually built.
  - **Reframed from spec to decision record.** It now states outright that it
    isn't a contract and that the code wins where they disagree — development
    had already improved on it in several places. Every section carries a
    ✅ Built / 🔨 Planned (Mn) / 💭 Open marker; §4 separates built endpoints
    from planned ones, §5 (auth + `/public/*`) is labelled entirely
    unimplemented, and §9.1–§9.4 are explicitly numbered so the code comments
    referencing them resolve.
  - **§10 rewritten for the alpha**: public at 4.5 rather than after M1–6, with
    four disclosures (no auth, no bundled containers, no photos/showcase,
    schema still moving). §12.6 realigned — code going public ≠ an instance
    going on the internet, and M7 still gates the latter.
  - AGENTS.md: design-doc bullet rewritten (tracked, not a spec, not binding —
    the architecture rules are), `docs/design.md` added to Layout, roadmap notes
    the alpha ships at 4.5 and that the audience is now strangers.
- **Done — README** (stub → full front page): alpha warning up top, feature
  sections, install steps, MCP wiring, tool table, what-isn't-built table. Tone
  deliberately light per design notes §10.1.
  - **Claude Desktop is documented as config-file-only** (`mcp-remote` bridge in
    `claude_desktop_config.json`). Its *Add custom connector* dialog only
    accepts publicly reachable URLs, so it cannot reach a self-hosted instance —
    user-verified, after a first draft claimed otherwise. Claude Code takes the
    HTTP URL directly. Endpoint is `http://localhost:8000/mcp/`; **the trailing
    slash matters**, without it you get a 307 and not every client re-POSTs.
  - **`docs/screenshots/`** — six 2× retina PNGs (~1.5 MB) captured with
    Playwright against the dev stack. The capture script was throwaway; to
    re-shoot, drive chromium from inside `frontend/` so `@playwright/test`
    resolves.
- **Done — config and exposure hardening** (all three found while writing the
  install docs; none were asked for up front):
  - **One `.env`**, at the repo root. Previously root `.env` for compose plus
    `backend/.env` for the API, with the password written twice and nothing
    enforcing a match. `app/config.py` now declares
    `POSTGRES_USER/PASSWORD/DB/HOST/PORT` and **assembles** the DSN, URL-quoting
    the credentials so a password containing `@` or `/` can't produce a DSN that
    parses to the wrong host. `DATABASE_URL` still overrides wholesale —
    `tests/conftest.py` and the M8 container both depend on that. `env_file` is
    an absolute pair (`<root>/.env`, `<backend>/.env`, later wins) anchored on
    `__file__` instead of the cwd-relative `".env"`, so the repo root and
    `backend/` now resolve identically; they previously didn't. `backend/.env`
    is redundant and deleted locally, still honoured if present.
  - **Postgres publishes on loopback only** (`${POSTGRES_BIND:-127.0.0.1}`).
    Docker publishes on 0.0.0.0 when the bind address is omitted, so the dev db
    was answering on the LAN — confirmed by connecting to it on the host's
    network address, and refused after the change.
  - **`pool_pre_ping=True`** on the engine. Without it the first request after
    any Postgres restart 500s on a severed pooled connection
    (`asyncpg InterfaceError: connection is closed`) and only recovers on the
    second — A/B verified by restarting the db container both ways. Matters more
    from M8, where api and db restart independently. No-op under the tests'
    NullPool.
- **Security audit (clean):** only `.env.example` has *ever* been tracked, in
  any commit, not just at HEAD; no db/dump/key files; no hardcoded secrets. The
  only credential-shaped strings in tracked code are the localhost dev defaults
  in `app/config.py` and `tests/conftest.py` (`plamotrack`/`plamotrack`) —
  throwaway, fine to publish, worth a glance if that ever stops being true.
- **State:** 89 backend tests green, ruff clean, `npm run build` green. Working
  tree clean, `main` pushed, repo public, release out. The dev DB holds seeded
  demo data (~21 kits, 12 orders, 4 retailers) created via the REST API for the
  screenshots — the user has confirmed it's all throwaway test data, so there's
  nothing here worth preserving on the dev Mac.
- **Next:** Milestone 5 (photos) — the §9.2 storage decision comes first, and it
  now has a second input: the user's own instance will run in a dedicated LXC on
  Proxmox, so "local volume" means a bind mount inside one container rather than
  anything exotic. That also shapes M8 packaging — single-host compose, not
  orchestration.
- **Now that it's public, for whoever picks this up:** the README's alpha warning
  is the only thing between a stranger and an unauthenticated write API. Don't
  weaken it, and don't describe planned endpoints as though they exist —
  `docs/design.md` marks every section ✅/🔨/💭 for exactly that reason. M7 (auth)
  is the gate on anyone sensibly exposing an instance.

## 2026-08-06 — Claude Code — Milestone 4.5: CSV import/export

- **Done:**
  - **`services/portability/`** — `spec.py` declares every table's CSV shape once
    (columns, parsers, roles, natural key, FK order); `exporting.py`,
    `importing.py`, `starter_sheet.py` all read it, so export/import/templates
    can't drift. A test asserts template headers == export headers.
  - **Export:** `GET /export/archive` (zip of 9 CSVs + `manifest.json` carrying
    export + schema versions, schema version = live Alembic revision + README),
    `GET /export/{table}.csv`, `/export/templates` (blank pack + COLUMNS.txt),
    `/export/starter-sheet.csv`. Every uuid FK gets a readable twin column
    (`retailer_name`), every `*_minor` a major-unit twin (`unit_price`) — the
    canonical column wins on import.
  - **Import:** `POST /import/preview` → full `ImportPlan` (per-row action,
    what it matched and how, field diffs, derived effects); `POST /import/apply`
    re-plans and 409s if `plan_hash` moved. Stateless — nothing cached between
    the two calls. Modes: merge / add_only / replace_all (typed `confirm=REPLACE`).
    One transaction; any bad row imports nothing.
  - **Starter sheet:** one denormalized row per kit → expands to
    retailers + orders + order lines, then goes through the *same* planner.
  - **Frontend:** `/data` page (export, templates, drag-drop import with mode
    selector, preview accordions, REPLACE gate), `ExportCsvButton` on Kits /
    Orders / Inventory / Retailers.
  - `docs/import-export.md` (user-facing format + matching reference), README
    section, AGENTS.md rules 9–10, design doc §12.
- **Decisions (user-confirmed up front):** hybrid dispatch (kits restored when
  the upload has them, spawned via the §3.9 fan-out when it doesn't);
  three conflict modes; natural-key matching per table with **kits deliberately
  excluded** (a kit row is one physical kit — name matching would merge real
  purchases); both a template pack and a single starter sheet.
- **Two invariants worth not breaking** (see AGENTS.md 9–10, §12.5):
  stock is only ever read from the catalog CSVs — importing orders never adjusts
  it, or re-import doubles it; and a blank cell in an *included* column means
  null while an *omitted* column is left alone, which is why the starter sheet
  emits only the columns it actually knows about (it was wiping retailer ratings
  until that was fixed — regression test covers it).
- **State:** 89 backend tests green (60 existing + 29 new), ruff clean,
  `npm run build` + lint green. Browser-verified live: starter sheet →
  6 created + 3 kits spawned; archive re-import → 0 new / 0 updated /
  24 unchanged; replace_all wipe-and-restore → collection byte-identical
  before/after. **No migration** — additive only. `python-multipart` added to
  backend deps (FastAPI needs it for uploads).
  Refactor: `orders._spawn_kits` → public `spawn_kits(...)` with keyword args so
  the importer reuses the real fan-out; `_spawn_from_details` wraps it for the
  REST payload shape.
- **Next:** Milestone 5 (photos) — §9.2 storage decision first. `kit_photos` is
  already registered in the portability spec and exports empty, so the archive
  shape won't change when photos land.

## 2026-08-06 — Claude Code — Status merge (in_hand → backlog) + dual board views

- **Done:**
  - **Merged in_hand into backlog** (migration `9d78b6148c30`, hand-written —
    enum value changes are invisible to autogenerate): they were functionally
    the same pile. Final pipeline: pre_ordered → ordered → in_transit →
    **backlog** (= in hand, not started; keeps in_hand's old position and teal)
    → building → complete. in_hand kits data-migrated; CHECK constraint
    rebuilt; receive/spawn flows now advance to backlog. MCP `_parse_status`
    gained aliases (in_hand/arrived/received → backlog) for agents with stale
    vocabulary.
  - **Board views**: Build (default — Backlog/Building/Complete) and Orders
    (Pre-ordered/Ordered/In Transit + one aggregate **Received** column
    grouping the three build states, cards showing their status badge).
    Dropping on Received = backlog unless the kit is already past it. Toggle
    persists in localStorage (`plamotrack.boardView`).
- **State:** 60 backend tests + 2 E2E green (drag test now runs in the default
  Build view); design doc §1.1/§3.1 amended. Committed + pushed.
- **Next:** Milestone 5 (photos) — §9.2 storage decision first.

## 2026-08-06 — Claude Code — Milestone 4: Kanban board + deferred review items

- **Done:**
  - **Board page** (`/board`, now the index route) with @dnd-kit/core: seven
    color-accented status columns, draggable kit cards (grade/scale/kit# chips,
    rating stars), DragOverlay ghost, per-column counts. Drops call the same
    `PATCH /kits/{id}` as the table's dropdown, with an **optimistic cache
    update** (rollback on error, invalidate on settle) so cards land instantly.
  - dnd-kit subtleties handled: `pointerWithin` collision with a
    `rectIntersection` fallback (pointerWithin alone breaks keyboard drags),
    and a **custom keyboard coordinate getter** that jumps one whole column per
    arrow press (the default 25px nudges get cancelled by board auto-scroll).
    Keyboard: focus card → Enter → arrows → Enter.
  - Deferred review items: list-query failures now render error banners instead
    of fake empty states (all pages); Receive has a confirm dialog; **Playwright
    happy-path E2E** (`frontend/e2e/`, `npm run test:e2e`): order with new
    retailer + typeahead-created consumable → pending (stock 0) → receive
    (stock 3, kit In Hand) → real stepped mouse drag to Building. Runs against
    the dev stack, uniquely-named data, cleans up after itself via the API
    (including un-progressing the kit so undo-delete passes). Chromium via
    `npx playwright install chromium`.
- **Notes:** in-pane synthetic single-step drags don't satisfy the
  PointerSensor activation constraint — that's an automation artifact; human
  mouse drag (user-verified) and Playwright stepped drags both work. No
  intra-column manual ordering (nothing in the schema backs it) — columns sort
  by status_updated_at desc.
- **State:** frontend build + lint green, 2/2 E2E green, 60 backend tests
  untouched. Committed + pushed.
- **Next:** Milestone 5 — photo upload + gallery. **Decision gate first:
  §9.2 photo storage backend** (local volume default vs S3/MinIO opt-in)
  before writing the upload handler.

## 2026-08-06 — Claude Code — Integrity fixes from external review (GPT 5.6)

- **Done:** three backend integrity fixes, all with regression tests
  (`tests/test_integrity.py`, suite now 60):
  1. `_get_order_for_write` now locks the order row (`FOR UPDATE`) — concurrent
     `receive_order` calls serialize; the loser 409s instead of applying stock
     twice. Test drives two simultaneous receives via asyncio.gather and
     asserts exactly one success + single stock application.
  2. `get_or_create_retailer` no longer commits — it joins the caller's
     transaction, so a failed MCP order rolls back its implicitly-created
     retailer. Happy path (case-insensitive reuse) re-tested.
  3. Order-spawned kits are blocked from direct deletion (409 pointing at
     order editing) so line quantity and surviving kits can't drift; the edit
     diff also now computes against actual kit counts as defense in depth.
     Standalone kits still delete normally.
- **Not done (deferred, from the same review):** surface frontend query
  failures as errors (not empty states); confirmation dialog on Receive;
  Playwright happy-path test. Queue these with or before Milestone 4 frontend
  work. A proper "disposed/sold" kit state is the long-term answer for removing
  an order-spawned kit from the collection without touching purchase history.
- **State:** 60 backend tests green; committed + pushed.

## 2026-08-06 — Claude Code — Order lifecycle (pending→received) + full CRUD

- **Done:**
  - **Stock timing fix:** `orders.received_at` (migration `6cbd8315df95`,
    existing orders backfilled as received). Catalog stock now increments on
    receive, not at entry; `POST /orders/{id}/receive` + "Receive" button +
    MCP `mark_order_received` / `list_orders(pending_only)`. Receiving advances
    pipeline kits to in_hand; `received: true` at creation covers store buys.
  - **Order edit (full line diffing):** `PATCH /orders/{id}` takes header fields
    and/or a replacement `items` set (line `id` = update, no id = add, omitted =
    remove-and-undo). Kit detail edits propagate to all spawned kits; quantity
    changes spawn/delete kits; target/qty changes on received orders adjust
    stock. item_type changes rejected (frontend drops the id → remove+add).
  - **Order delete = undo:** kits removed, applied stock reversed.
  - **Guards:** progressed kits (building/complete, rated, or with photos) and
    below-zero stock block destructive edits with clear 409s.
  - **CRUD gaps closed:** PATCH/DELETE for tools/consumables/upgrades/retailers
    with history guards (referenced by order lines / applications / orders →
    409). Frontend: edit/delete on Inventory + Retailers, order edit modal
    (reconstructs lines incl. prices in major units), Pending/Received chips.
  - **Retailer report card** (parity with the old Baserow base, migration
    `e720578b82de`): `rating` 1–5, `packing_quality`
    (excellent/good/average/below_average/poor), `shipping_speed`
    (very_fast/fast/average/slow/very_slow), `would_order_again`
    (yes/maybe/no) — all optional, text-enum CHECKs, in the form + table.
  - **`orders.order_number`** (migration `04315056a82f`): the retailer's own
    reference, for support contact. Nullable text, deliberately NO uniqueness
    constraint — only unique per retailer at best, never an internal identifier
    (UUIDs remain identity). In the order form/table and MCP create_order.
- **Decisions (user-confirmed):** undo-dispatch on delete; full line editing;
  order-level received state (split shipments = separate orders, no per-line
  receiving); kits auto-advance on receive.
- **State:** 56 backend tests green; frontend build + lint green; browser-
  verified live (defer→receive stock flow, rename propagation, undo delete,
  delete guards, retailer report card, order number). Committed + pushed along
  with Milestone 3. The local design doc is amended to Draft v1.1 (§3.7, §3.8,
  §3.9 lifecycle amendment, §4, §7, §11 ticks).
- **Next:** Milestone 4 (Kanban) still queued. Possible follow-up: un-receive
  action (reverse a mistaken receive) — not built, delete/re-enter covers it.

## 2026-08-06 — Claude Code — Milestone 3: frontend (tables + forms)

- **Done:**
  - `frontend/`: Vite + React 19 + TS, Tailwind v4, TanStack Query,
    react-hook-form, react-router. Dev proxy: app calls `/api/*` → Vite strips
    the prefix → backend :8000 (prod nginx will mirror this at M8).
  - Pages: Kits (search/status filter, add/edit modals, inline status dropdown =
    Kanban precursor, delete), Inventory (tools/consumables/upgrades tabs,
    low-stock highlight, apply-upgrade-to-kit dialog), Retailers, Orders
    (expandable rows with per-line detail + multi-currency totals; new-order
    modal with retailer quick-add and per-line dispatch).
  - **CatalogItemPicker** implements §3.9 select-or-create: debounced typeahead
    against `/catalog/search`, pick-existing or create-new — no free-text path.
  - Browser-verified end to end: order (2× kit + new consumable) → fan-out to 2
    kits with derived 1/144 scale, stock at 3, totals correct, status changes.
- **Fixed (backend):** read-after-write race — FastAPI runs yield-dependency
  teardown (where the commit lived) *after* sending the response, so the UI's
  invalidate-and-refetch could read pre-commit state. Mutating service functions
  now commit explicitly before returning; `db.session_scope` keeps a no-op
  safety-net commit. All 27 backend tests still pass (atomic rollback included).
- **Decisions:**
  - Prices entered in major units, converted to minor via Intl fraction digits
    (JPY → 0). All lines share the order currency in the UI (API still supports
    per-line). `converted_price_aud_minor` auto-set only when currency is AUD —
    FX lookup remains the §6 nice-to-have, not built.
  - No frontend unit tests this milestone — verified via live browser E2E;
    Playwright is a candidate once the Kanban lands.
- **State:** backend tests green, `npm run build` + lint green, **uncommitted**.
  Dev DB holds a bit of demo data (1 order, 2 kits, 1 consumable, 1 retailer) —
  deletable via the UI. `.claude/launch.json` starts the Vite dev server.
- **Next:** Milestone 4 — Kanban board with dnd-kit (drag card between status
  columns → `PATCH /kits/{id}`), reusing the inline-status mutation pattern.

## 2026-08-06 — Claude Code — Milestones 1+2: schema, REST API, MCP server

- **Done:**
  - Repo scaffold: `.gitignore`, `.env.example`, `docker-compose.yml` (db only),
    uv-managed `backend/`.
  - All 9 tables as SQLAlchemy 2.0 async models + one hand-checked Alembic
    migration (`71ddc06de024`). Text enums with CHECK constraints; stock/rating
    guards; `ondelete` cascades; `kits.order_item_id` provenance (nullable — Backlog
    kits pre-date orders).
  - Service layer with the §3.9 fan-out/increment dispatch (single transaction,
    full rollback on any bad line), row-locked stock mutations, catalog search,
    grade→scale derivation (HG/RG/EG→1/144, MG→1/100, PG→1/60, SD→non-scale).
  - REST API per §4 (kits CRUD incl. Kanban PATCH, tools/consumables/upgrades,
    `/upgrades/{id}/apply`, retailers, orders with nested items, `/catalog/search`).
  - All 7 §7 MCP tools via FastMCP **v3**, mounted at `/mcp` on the REST port
    (deviation from §8's two-port layout — simpler, split later if needed).
    Agent niceties: status normalization ("In Transit" → `in_transit`),
    case-insensitive get-or-create retailer in `create_order`.
  - 27 tests (REST + in-memory MCP client) incl. atomicity and stock-guard cases.
  - Verified live: REST smoke + MCP-over-HTTP smoke both good.
- **Decisions:**
  - Photo endpoints deferred to M5 (`kit_photos` table exists, schema-only).
  - No auth yet — matches M1 scope; auth is M7.
  - `POST /orders` kit lines carry `kit` details (name/grade/…); catalog lines take
    `catalog_ref_id` XOR `new_item` (select-or-create at the API level).
  - Tests run real migrations both directions every run + auto-create the test DB.
- **State:** all green — `docker compose up -d db --wait` then `uv run pytest`
  → 27 passed; ruff clean. Dev DB migrated and empty. OrbStack installed by the
  user (auto-starts); earlier brew-Postgres workaround retired (leftover
  `.dev/pgdata` is inert and gitignored).
- **Next:** Milestone 3 — `frontend/` (React + Vite + TS + dnd-kit): table views
  and forms against the REST API. Open §9 decisions unchanged (taxonomy before
  config UI; photo storage backend before M5 upload handler).
