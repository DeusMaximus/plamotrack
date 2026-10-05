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

## 2026-10-06 — Claude Code (Opus 5.5) — #323 MERGED as `b2343a4` (PR #328): every free-text table cell gives way by its value; Inventory's Tools and Display fold; #326, #327, #329 filed

- **Done:**
  - **[PR #328](https://github.com/DeusMaximus/plamotrack/pull/328)** squash-merged as **`b2343a4`**, pinned to the reviewed head `b57dc13` after all three checks. #323 is closed.
    - `frontend/src/components/Measured.tsx` (new) is Orders' `Reference`, lifted out and generalised as `Measured`/`TableRuler`.
      - A value breaks anywhere only when its widest word is past a budget: `name` 10em, `text` 8em; the references keep 6em and 8.3em.
      - It breaks down to a floor: 4em for a name, 3em for text.
      - The measuring copy takes the drawn text's font.
    - Every free-text cell that sets a column's width goes through it: Kits, Orders (including the lines box's delivery service), Retailers, and all four Inventory tables.
    - **Siblings fixed in the same PR:**
      - Inventory's category `<select>` gets `max-w-52`;
      - a phone kit card's scale may narrow, and `GradeChip` wraps below 768 px;
      - Inventory card `Facts` wrap instead of truncating.
    - **Round 1 (Codex, P2):** words under their budgets add up. Inventory's **Tools fold Condition below 44rem, and Display fold Manufacturer and Notes below 55rem**. Both lines are measured with a word just under its budget in every column at once.
    - **Round 2 (Codex, P2):** allowed values still outgrow fixed lines, Kits' #258 line included. **Owner's call:** ship as measured, state the contract (a line holds what it was measured with; past it the box scrolls), and file **#329, fold to fit**.
    - **Round 3:** GO. Codex made 1,540 paired measurements against `main`: no regressions, and 565 main overflows now fit.
  - **Tests** (`lists.spec.ts`): seeds with every free-text field unbroken; near-budget rows on all four Inventory tabs; the real widest words ("(Unidentified" 6.2em, "Workstation" 5.7em); a rule test (ordinary words stay plain, unbroken ones break, both floors, a clipped delivery service); Inventory in the sweep and the fold test. 22 mutants killed over the rounds.
  - **Filed:**
    - [#326](https://github.com/DeusMaximus/plamotrack/issues/326): Home has the same defect in its no-wrap strips. It's a design call.
    - [#327](https://github.com/DeusMaximus/plamotrack/issues/327): WebKit's Tools table is 6 px over at 768 px with a ten-digit count. A failed test's leftover rows found it.
    - [#329](https://github.com/DeusMaximus/plamotrack/issues/329): fold to fit, on every list. Codex's cautions are in its comment: no observer loop, invalidation when content changes, and tables that never fold today.
  - Lesson: `.agents/lessons.md` → "Under its budget is still a width".
- **Decisions (owner, 06/10):**
  - Fold Inventory rather than break every value in a table that doesn't fit.
  - Ship #328 scoped and sequence #329 after it.
  - Desktop Codex for every round.
- **State:**
  - **Unreleased on `main`:** #294, #289, #247, #302, #310, #313 (a migration), #314, #319, #322 and now **#328**. See `.agents/next-release.md`; #323's entry is there.
  - **Unexplained:** one full Chromium run at `a92e784` had two `tablet` tests fail because a list wasn't drawn within 5 s of loading. It didn't reproduce in 17/17 plus 3× repeats. Codex's settled-frame probe saw no observer churn from `Measured`. If it recurs, look there first.
  - **Known gaps, filed:** #329, #326, #327; #324 (local runs need `--workers=1`); #320; #315; #316.
  - **Tooling:**
    - No dev servers, worktrees or e2e databases are left, and `main` is clean.
    - Merged branches left on origin: `fix/323-unbroken-names`, `fix/321-focus-row-page`, `fix/317-narrow-list-lookups`, `feat/318-page-size`.
    - Review briefs: `.dev/323/review-brief-{1,2,3}.md`.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next:**
  1. #329 (fold to fit; it closes Codex's round-2 finding and Kits' line), or #326 (Home) by the owner's priority. Then #315 and #316. #324 when local multi-worker runs matter.
  2. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`. Its open questions: does its domain layer map onto the op names, and does its store accept caller-chosen ids?
  3. Carried:
     - #279's edge probes, then #281's packaging; #282's VPS path;
     - at the next release, work through `.agents/next-release.md`;
     - cloud candidates: #124, #125, #268, #238, #110, #116, #134 and #137;
     - posting the rehearsal on #285.

## 2026-10-05 — Claude Code (Opus 5.5) — #321 MERGED as `277cb0a` (PR #322) and #317 MERGED as `3fba4c3` (PR #325); #323, #324 filed

- **Done:**
  - **#317 was never a focus race.** Its #275 test opens `/inventory?tab=upgrades`, which can't be narrowed. With more than ten upgrades sorting ahead, the row is on page 2; 11 seeded leftovers reproduce it every time.
  - **The sweep** found 38 lookups of that shape across 13 spec files (classified on #317's thread).
  - **[PR #325](https://github.com/DeusMaximus/plamotrack/pull/325)** squash-merged as **`3fba4c3`** after `main` was merged in at `f9e8c6a`. It is test-only:
    - Kits, Orders and Retailers open with `?q=` naming the test's own record.
    - Inventory opens through `e2e/listRows.ts` → `openListAt`, which steps `?page=` and reads the pager, not the locale-formatted range (round 1, Codex and Greptile).
    - `lists.spec`'s `openList` delegates to it.
    - Local multi-worker runs: 17 failures on `main`, then 8–10. The rest are #324, #321, #323 and slow saves.
  - **[PR #322](https://github.com/DeusMaximus/plamotrack/pull/322)** squash-merged as **`277cb0a`**; #321 is closed. It fixes #319's regression: a turn from phone to rail with the keyboard past row 10 fell to `<body>`.
    - `usePaging()` (`lib/listState.ts`) now owns slicing via `paging.slice(rows)`. In the crossing render it lands on the page holding the record from `focusedRecordKeys()` (open dialogs' openers via `Modal`'s `holdOpener`, then the focused control) and writes `?page=N`.
    - The hold writes once and asks the browser's address, not only the router. Another navigation ends it (round 1, Greptile).
    - Inventory slices only the tab on screen (round 1, Codex P2).
    - Design §13.7 ("Amended — #318", last bullet), AGENTS.md (the focusKey line) and two lessons are updated.
  - **Reviews:**
    - #322 round 1: Codex P1 and P2, Greptile 4/5; all taken. Round 2, briefed Codex desktop: **GO**, no findings, with five extra probes.
    - #325: Codex P2 and Greptile 4/5, both taken; the connector's re-review was clean.
  - **Decisions (owner, 03–05/10):** C over B for #321; separate PRs; fix #317's whole class in one branch; #322 got a briefed desktop round, #325 the connector only.
- **State:**
  - **Unreleased on `main`:** #294, #289, #247, #302, #310, #313 (a migration), #314, #319 and now **#322**, folded into #318's entry. #325 is test-only. See `.agents/next-release.md`.
  - **Coverage gap on #322**, recorded in its PR body and not filed: the mutant *no turn while the URL has a page* survived 16 runs in Codex's replay. A deterministic witness needs the router's update held across a turn.
  - **Known gaps, filed:**
    - **#323 (bug, product):** an unbroken name widens all seven list tables past their box from 768 px up, measured. `lists.spec`'s fit test seeds only its own rows.
    - **#324:** Home and import e2e read collection-wide state, so the local multi-worker default fails. Keep `--workers=1` until it's fixed.
    - **#320:** Orders' render cost at hundreds of orders on a phone.
    - **#315:** leaving Data management mid-import.
    - **#316:** download errors at the section's head.
  - **Tooling:** the iOS Simulator is still booted. No dev servers, worktrees or e2e databases are left, and `main` is clean. Merged branches left on origin: `fix/321-focus-row-page`, `fix/317-narrow-list-lookups`, `feat/318-page-size`.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next:**
  1. #323 (product; a by-value rule for names, like `ReferenceRuler`), then #315 and #316 by priority. #324 when local multi-worker runs matter.
  2. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`. Its open questions: does its domain layer map onto the op names, and does its store accept caller-chosen ids?
  3. Carried:
     - #279's edge probes, then #281's packaging; #282's VPS path;
     - at the next release, work through `.agents/next-release.md`;
     - cloud candidates: #124, #125, #268, #238, #110, #116, #134 and #137;
     - posting the rehearsal on #285.

## 2026-10-03 — Claude Code (Opus 5.5) — #318 MERGED as `3f72272` (PR #319): every row on a phone, ten a page wider; #320 filed

- **Done:**
  - **[PR #319](https://github.com/DeusMaximus/plamotrack/pull/319)** squash-merged as **`3f72272`** from `f6d81c5`, after all three checks. #318 is closed.
    - The phone shell (below 768 px) shows every row on Kits, Orders, Inventory's four tabs and Retailers, with no pager. From 768 px it's ten a page, as before.
    - Decided by the shell alone. `usePaging()` in `lib/listState.ts` is the one entry; `paginate` takes `"all"`. On a phone `?page=` is dropped in place (a replace).
    - A page button's focus stand-in is now `page-action`. The phone's compact `pageWindow`, and the e2e that measured its fit, are gone.
    - The design record is design §13.7, "Amended — #318".
  - **The owner's calls (03/10):**
    - A first build had a *Rows per page* (10 / 20 / All) browser-local preference, one value per shell. The owner dropped it before review. Nothing is stored, and §13.1's "the theme is the one exception" stands.
    - `?page=` is dropped, not ignored.
    - Greptile's Orders P2 is "revisit later" → **#320**.
  - **Measured before deciding.** Chromium, 390 px, 300 rows a list (the owner has 116 kits and 82 orders):
    - 0.2–0.4 s unthrottled; 0.9–2.1 s at a 4× CPU throttle.
    - No scroll frame past 50 ms.
    - Orders is the heaviest: about 5.7 s of long tasks at 4×. That is #320.
  - **Reviews:**
    - Round 1: the Codex connector found nothing. Greptile gave 4/5 with two P2s. Coverage of the other lists was taken (`f6d81c5`: a phone test over the six other lists, with 6 mutants killed). Orders render cost was declined and filed as #320.
    - No desktop Codex round: a small PR, by the owner's routing.
  - **Final state:**
    - Full Chromium e2e from empty at `befff4b`: 185 passed / 0 failed. Targeted re-runs after the later changes.
    - WebKit: both #318 tests (`phone`) and the focus sweep (`tablet`) pass.
    - Mutants 5/6 on the design, plus 6/6 per list. The survivor was an equivalent override, which was removed.
    - 648 unit tests.
- **State:**
  - **Unreleased on `main`:** #294, #289, #247, #302 (#299, #300, #301), #310 (#305), #313 (#309, a migration), #314 (#304) and now **#319 (#318)**. See `.agents/next-release.md`. #318's entry owes the docs site's phone page a line, and retaken phone screenshots that show a pager.
  - **Not checked** for #318: iOS Safari on a device or in the Simulator; VoiceOver; a physical phone.
  - **Known gaps, filed:**
    - #315: leaving Data management while an import runs. An Add only repeat can duplicate kits.
    - #316: download errors show at the section's head.
    - #317: `lists.spec.ts`'s #275 test fails about 1 in 3 on `tablet`, on `main` too.
    - #320: Orders render cost at hundreds of orders on a phone.
  - **Tooling:** the iOS Simulator (iPhone 18 Pro) is still booted with the owner's dev session. No dev servers or throwaway databases are left, and `main` is clean. Merged branches left on origin: `feat/318-page-size`, `feat/304-phone-import`.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next:**
  1. **#317**: the flaky #275 test on `tablet`. It's next, by the owner's call. Then #315 and #316.
  2. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`. Its open questions: does its domain layer map onto the op names, and does its store accept caller-chosen ids?
  3. Carried:
     - #279's edge probes, then #281's packaging; #282's VPS path;
     - at the next release, work through `.agents/next-release.md`;
     - cloud candidates: #124, #125, #268, #238, #110, #116, #134 and #137;
     - posting the rehearsal on #285.

## 2026-10-03 — Claude Code (Opus 5.5) — #304 MERGED as `39a9661` (PR #314): a phone imports — Merge and Add only, Apply in a bar above the tab bar; review routing settled

- **Done:**
  - **[PR #314](https://github.com/DeusMaximus/plamotrack/pull/314)** squash-merged as **`39a9661`** by `--auto --match-head-commit` at `b15ba9f`, after all three checks. #304 is closed.
    - The owner's calls (02/10): Merge and Add only on a phone, `replace_all` never drawn; the same `ImportPreview` with phone folds; the starter sheet only, after the import; a mockup first. Cancel left and Apply right, as in every dialog's bar, against the mockup.
    - The mockup is a private canvas on the owner's account (the link is in the agent's memory, not in the repo).
    - Verified in the iOS Simulator (iPhone 18 Pro, Safari, the dev instance; the owner signed in): the archive downloaded and picked from Files, previewed, cancelled. Nothing was applied to the dev database.
    - What the design settled is in design §13.7, "Amended — #304": the sent import as its own phase (`submitted`), preview numbering (`previewSeq`), and where the keyboard goes at each transition.
  - **Reviews:**
    - Round 1 was the GitHub autoreviews: Greptile 4/5, the Codex connector two P2s.
    - Rounds 2–4 were briefed Codex in the desktop app (GPT 6.1 Sol): NO-GO (1 P2, 2 P3), NO-GO (1 P2, reclassified P3 by exposure on the owner's call, plus 1 P3), then **GO** with 2 P3s. Those two were taken, and a sibling from `main` was folded in (a preview's answer dropping the keyboard), with no fifth round.
    - The PR body has every round's mutant table and a coverage record. Two lessons are in `.agents/lessons.md` (#304).
  - **Final state at `b15ba9f`:** full Chromium e2e 185 passed / 0 failed; WebKit `pages.spec.ts` 12 passed; the held-request tests ×5 in each engine; 650 unit tests.
  - **Process, on `main` (owner, 03/10):**
    - Review briefs live in `.dev/<issue>/review-brief-<n>.md` and travel as a one-line paste; they are no longer printed in chat.
    - Small PRs ride Greptile (only the first review is automatic; re-runs are the owner's) and the Codex connector (`@codex review`).
    - Big PRs get briefed Codex on the Mac: the plugin's task route without a browser, the desktop app with one.
    - All of this is now in `.agents/testing-and-review.md` and `.agents/review-brief.md`.
- **State:**
  - **Unreleased on `main`:** #294, #289, #247, #302 (#299, #300, #301), #310 (#305), #313 (#309, a migration) and now **#314 (#304)**. See `.agents/next-release.md`; #304's entry owes the docs site's phone page (and retaken `phone-data` screenshots) and the import page's opening line.
  - **Not checked by anyone** for #304 (the coverage record has the full list): VoiceOver announcing the status line; native CSV selection on iOS; Android pickers; a physical device; a real plamotrack-ios archive.
  - **Known gaps, filed:**
    - #315: leaving Data management while an import runs (the same on `main`; an Add only repeat can duplicate kits).
    - #316: download errors show at the section's head, a screen away from the starter sheet on a phone.
    - #317: `lists.spec.ts`'s #275 test fails about 1 in 3 on the `tablet` project, on `main` too.
  - **New, from the owner's use on a phone:** #318, a page-size preference (10 / 20 / All), stored in the browser like the theme, with All by default in the phone shell. Its open questions are in the issue, including revising design §13.1's "the one deliberate exception" to rule 11.
  - **The iOS Simulator** (iPhone 18 Pro) is still booted, with the owner's dev session in its Safari. The dev servers are stopped. Throwaway databases dropped, no worktrees, `main` clean.
  - Merged branches left on origin: `feat/304-phone-import`, plus the ones listed below.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next:**
  1. #318 (page size on a phone) wants the owner's answers to its "To decide" list before code; then #315–#317 by priority. #317 first if CI starts flaking on it.
  2. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`. Its open questions: does its domain layer map onto the op names, and does its store accept caller-chosen ids?
  3. Carried:
     - #279's edge probes, then #281's packaging; #282's VPS path;
     - at the next release, work through `.agents/next-release.md`, including #304's docs-site page;
     - cloud candidates: #124, #125, #268, #238, #110, #116, #134 and #137;
     - posting the rehearsal on #285.

## 2026-10-02 — Claude Code (Opus 5.5) — #305 (`8ba9c6e`, PR #310), #307 (`f8d7f0d`, PR #311) and #309 (`4651ce2`, PR #313) MERGED; #306 fixed on the docs site; `main` gets a ruleset

- **Done:**
  - **#306** closed by [plamotrack-docs#8](https://github.com/DeusMaximus/plamotrack-docs/pull/8), merged as `bb30824`.
    - The backups page no longer says an archive "does not preserve ids". The import page now says a restore into a new instance keeps them.
    - Checked first against `v0.5.2-alpha`, in a worktree: the golden archive restored into an empty instance kept all 35 ids.
    - The merge sentence names only retailers, catalog items and orders. Kits match by id alone, so "matching records" would have overclaimed.
  - **[PR #310](https://github.com/DeusMaximus/plamotrack/pull/310)** squash-merged as **`8ba9c6e`**, pinned to the reviewed head `96a8ff0`; #305 is closed.
    - Reproduced on `main` first. 11 range CHECKs previewed clean and then failed the apply with a 500. `shipping_cost_minor` and `low_stock_threshold`, which have no CHECK, stored negative values.
    - The fix:
      - `ColumnSpec.minimum` / `maximum` on 12 columns;
      - `RATING_MIN` / `RATING_MAX` in `services/numeric.py`, read by `schemas.numeric.Rating` too;
      - `_check_ranges` after money scaling, quoting the cell as written (header, alias included, and text);
      - codes `import.cell_below_minimum` and `import.cell_above_maximum`.
    - `tests/test_import_ranges.py`, 63 cases:
      - CHECKs, request schemas and declarations agree, and the CHECK walk is total;
      - every bound one step out, in merge and `replace_all`;
      - the bound itself imports;
      - update rows, the alias header, the starter sheet.
    - The `305-` mutants: 10/10 killed. Full suite at `f28eb28`: 3060 passed, 1 xfailed.
    - Greptile: 4/5 with two P2s (the source cell; the audit skipping unknown CHECK forms), both taken in `96a8ff0`; round 2 5/5. CI green.
    - `.agents/next-release.md` has the entry; it owes the docs site and `docs/import-export.md` a line on ranges.
  - **[PR #311](https://github.com/DeusMaximus/plamotrack/pull/311)** squash-merged as **`f8d7f0d`** from head `9e9fc8c`; #307 is closed.
    - Behaviour scenarios shared with plamotrack-ios: `backend/tests/fixtures/scenarios/` (`scenario.schema.json` and 6 files, 31 scenarios); the runner is `tests/test_scenarios.py`. The format is in `.agents/testing-and-review.md` → "Behaviour scenarios", and `AGENTS.md` now points rules the app reimplements at it.
    - The owner's five calls: run against the services; seed `given` by direct insert; `@now` as the run's window; refusal params on the registry's declared keys; one file per rule area.
    - Reviews:
      - Round 1: Codex P2 (`@now` in a step `result`) and Greptile 4/5 (spawned-kit provenance; repeated JSON keys).
      - Round 2: Codex P2 (an unpinned seeded status clock passed as `@now`). Every seeded kit now states its clock, a meta-test enforces it, and mutants scn-13/14/15 survive on `d638cc4` and are killed on `9e9fc8c`.
      - Round 3: Codex clean (👍); Greptile 5/5.
    - The `scn-` mutants: 15/15 killed. Full suite at `f44cc3a`: 3109 passed, 1 xfailed. `jsonschema` is now a declared dev dependency.
    - **Merged before CI finished**, which the owner had not asked for ("merge once green"). `main` has no branch protection and the repo's auto-merge setting is off, so `gh pr merge --auto` merged immediately. Both CI runs then passed: the PR head and the push to `main`; the trees are identical. Since then `main` has a ruleset (below).
  - **[PR #313](https://github.com/DeusMaximus/plamotrack/pull/313)** merged as **`4651ce2`** from head `10d959b` by `--auto`, after all three checks; #309 (filed this session) is closed.
    - Migration `5cbec7813500`: negatives cleared to **null** (the owner's call), the count logged online, then `ck_orders_shipping_cost_non_negative` and `ck_consumables_low_stock_threshold_non_negative`. Offline (`--sql`) it writes the UPDATE.
    - New guards in `test_migration_data.py`: every migration renders offline, and every model CHECK matches the migrated schema by name **and definition** (the models are built into a scratch schema and compared through `pg_get_constraintdef`). No existing drift was found.
    - The `309-` mutants: 7/7.
    - Reviews: Codex clean twice. Greptile flagged offline `.rowcount` (P1) and the name-only guard (P2), both fixed; then 5/5.
    - **CI caught one failure the ruleset held back:** #303's golden restore test required no warnings, and the new migration made the fixture's `schema_version` stale (`import.schema_drift`). The test now expects exactly that warning; no regeneration is needed (testing-and-review says so).
    - Full suite 3116 passed, 1 xfailed.
  - **Ruleset "main"** (id 24351954) and repo auto-merge, set up at the owner's request:
    - required checks Backend, Frontend and Integration; force pushes and deletion blocked; the admin role bypasses "Always".
    - Tested: a direct docs push bypasses it, and `--auto` waits (#312).
    - `AGENTS.md`: never `--admin`; "merge when green" is `--auto --match-head-commit`.
- **Decisions (the owner's, 2026-10-01/02):**
  - `docs/import-export.md` was left for the release under the published-release rule; the owner did not object. Before that rule, PRs edited it directly.
  - Greptile reviews; the PRs squash-merge pinned to the reviewed head.
- **State:**
  - **Unreleased on `main`:** #294, #289, #247, #302 (#299, #300, #301), #310 (#305) and #313 (#309, a migration); see `.agents/next-release.md`. #303 (PR #308) is test-only and owes nothing. The release also owes the Pocket ID docs page. #300 remains the most exposed: v0.5.2-alpha's `migrate` stops on a punctuated `POSTGRES_PASSWORD`.
  - Merged branches left on origin: `feat/303-golden-archive`, `fix/305-import-range-checks`, `fix/archive-keeps-ids` (docs repo), plus the three older ones.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next:**
  1. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`. Its open questions: does its domain layer map onto the op names, and does its store accept caller-chosen ids?
  2. **#304**, import on a phone: the owner's decisions on modes and the 390 px preview, then mockups, before code.
  3. Carried:
     - #279's edge probes, then #281's packaging; #282's VPS path;
     - at the next release, work through `.agents/next-release.md`;
     - cloud candidates: #124, #125, #268, #238, #110, #116, #134 and #137;
     - posting the rehearsal on #285.
