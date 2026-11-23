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
- **Waiting on the owner:**
- **Next:**
```

---

## 2026-11-23 — Claude Code (Opus 5.5) — #238 worker, lane 2: PR #387 open, CI and reviews pending
- **Done:** branch `238-dialog-load-failure`, [PR #387](https://github.com/DeusMaximus/plamotrack/pull/387) against `main`, head `7211548` (code at `f740989`). The order dialog and the inventory dialogs now show a failure state with Retry and Cancel when a catalog list or `/meta` fails on both attempts. Retry asks only for what failed and keeps the keyboard while it waits. The form still never mounts on a missing input or a stale `/meta`. Release note added at the end of `.agents/next-release.md`.
  - **Merged:** squash-merged as **`5d597d1`** at `abb436f`, with the owner's sign-off; #238 is closed. `abb436f` is the orchestrator's merge of `main` (#386) into the branch: the conflict was only in `.agents/next-release.md` (the `#238` section placed after `#380`'s, unchanged), and outside that file the merge's change has the same patch id as the reviewed `e256f8e..7211548`, so no second round. Reviews: Codex connector at `f740989`, no findings; Greptile did not post; briefed round 1 (Codex GPT-6.1 Sol, `7211548`) **GO** with one P3 (the PR body's counts: 9 feature tests plus setup, 8 red / 1 green on `main`), answered and corrected in the body without a push. Re-run by the orchestrator on `e256f8e` from empty, each test alone: 8 red at the missing banner, 1 green (the new-order control). Follow-ups filed: #391 (Settings → General has no Retry), #392 (the order read's generic error says "close and reopen").
- **Decisions:** the failure state is held through a Retry, because a list with nothing cached drops its error the moment its refetch starts. An answer that arrives wins over that hold. A new order doesn't wait on the lists. Each failed input gets its own banner. `useFormMeta` now returns `{ meta, error, retry }`. `GeneralSection.tsx` is not a `useFormMeta` caller (it reads the settings query and already shows an error banner).
- **State:**
  - **Tests:** new `e2e/dialog-load-failure.spec.ts` (9 tests), added to the `phone` and `tablet` projects. Full Chromium from an empty database: 384 passed, 99 skipped, 0 failed, counts 0. WebKit `phone` (the new spec, dialogs, dialog-keyboard, lists): 37 passed, 22 skipped. Unit: 709 passed. Seven hand-applied mutants, all killed (re-run by the reviewer).
  - No backend change, no migration. Lane 2's Postgres container and the worker's worktree removed by the orchestrator; branch left. Sol's T3 worktree is T3's to remove.
- **Waiting on the owner:** nothing for this PR.
- **Next:** #376 (the next `InventoryPage.tsx` issue) in lane 2, then #394. The `OrderFormModal.tsx` queue (#369, #382, #383, #384, #392) waits until after the release.

## 2026-11-23 — Claude Code (Opus 5.5) — #380: PR #386 at `6160067`, automatic reviews clean; ready for the briefed round
- **Done:**
  - [PR #386](https://github.com/DeusMaximus/plamotrack/pull/386) (closes #380), branch `380-blank-kit-text`, head `6160067`, against `main` at `e256f8e`. A kit `name`/`grade` that is only whitespace is refused with `field.blank` naming the field, in the service layer: `names.refuse_blank_text` (`clean_required_text` now calls it), `kits.refuse_blank_kit_text`, called by `create_kit`, `update_kit`, `spawn_kits` and `_update_line` before the restatement. REST, MCP and the order kit line (entry; edit restated, grown, added) all covered. The importer already refused; pinned.
  - `backend/tests/test_kit_blank_text.py`, 107 tests. Negative control on `e256f8e`: 98 red / 7 green (the 105 first written). Mutation: twelve `380-` cases, all killed (836 cases on the branch). Full backend suite locally: 4177 passed, 1 xfailed. Sweep of the other 12 required text columns measured with an uncommitted probe: all already refused; table in the PR body.
  - `.agents/next-release.md`: `#380` section at the end (after #238's, if that lands first).
  - Reviews: Codex connector at `dd175a1`, no findings; Greptile at `dd175a1`, 5/5, no findings; CodeRabbit skipped. `6160067` changes only next-release.md.
  - **Merged:** squash-merged as **`706234c`** at the reviewed head `6160067`, with the owner's sign-off; #380 is closed. Briefed round 1 (Codex GPT-6.1 Sol, `6160067`): **GO** with one P3 (an order edit that echoes a stored blank kit name or grade unchanged is refused), answered on the PR without a push; the PR body's deliberate call 5 and coverage record brought up to the round. Re-run by the orchestrator: the negative control on `e256f8e`, 98 failed / 7 passed / 2 deselected, as stated. After the merge: the `#380` release note's sentence corrected on `main` to disclose the P3. Follow-ups filed: #388 (the P3), #389 (the dialogs send a name of only spaces), #390 (two required text fields answer `request.validation`, not `field.blank`).
- **Decisions:** refuse, don't trim (reasons in the PR's deliberate call 1); `field.blank`, not `name.blank`; `""` stays the schema's `request.validation`; no browser change (the dialogs send spaces, the banner shows the server's sentence; not driven in a browser); no data migration; a kit already stored blank blocks only growing or restating its order line. The owner's instance was checked read-only (2026-11-23): no kit has a blank name or grade.
- **State:** CI green at `6160067` (Backend, Frontend, Integration). No migration. Worker's test databases and throwaway Postgres container removed; its worktree removed by the orchestrator; branch left. Sol's T3 worktree (detached at `6160067`) is T3's to remove. The dev DB container (`plamotrack-db-1`) is stopped and another project holds 127.0.0.1:5432.
- **Waiting on the owner:** nothing for this PR.
- **Next:** #388, #389, #390 are filed and untriaged.

## 2026-11-19 — Claude Code (Opus 5.5) — orchestrator: wave 3 MERGED (#377 as `a7d005a`, #378 as `0daf5e5`); #379–#385 filed; nothing in flight

- **Done:**
  - **Wave 3.** [PR #377](https://github.com/DeusMaximus/plamotrack/pull/377) (#356, lane 2) merged as **`a7d005a`** and [PR #378](https://github.com/DeusMaximus/plamotrack/pull/378) (#358, lane 1) as **`0daf5e5`**, each at its reviewed head with the owner's sign-off. The two entries below are the workers', with what was re-measured.
  - **#378 took three briefed rounds' worth of review:** the connector's P2 at `e1a45fb`, Sol's round 1 NO-GO at `b90cdf2` (two P2s), round 2 GO at `397a295`. Round 1's second P2 landed in the money rule the previous fix had made, so it went to the owner (orchestration.md → "Briefed rounds" step 6): the owner chose to ship as scoped with the rule narrowed so nothing regresses against `main`, and file the structural fix (#382).
  - **On `main` after the merges:** `.agents/next-release.md`'s `#356` entry says a blank cell keeps whitespace-only text (#377 round 1), and its `#358` entry names both money limitations and #382 (#378 round 2's P3).
  - **Filed, at the owner's word:** [#379](https://github.com/DeusMaximus/plamotrack/issues/379) (the scenario harness: a settings seed fails the new seed check; the Python/Swift trim difference is untested), [#380](https://github.com/DeusMaximus/plamotrack/issues/380) (a whitespace-only kit name or grade makes its own export unimportable), [#381](https://github.com/DeusMaximus/plamotrack/issues/381) (Replace everything brings stored text back trimmed), [#382](https://github.com/DeusMaximus/plamotrack/issues/382) (the order dialog doesn't notice its money changed under it), [#383](https://github.com/DeusMaximus/plamotrack/issues/383) (a save stored but answered with an error; [comment](https://github.com/DeusMaximus/plamotrack/issues/383#issuecomment-7004082497) adds the kit and retailer dialogs' source comments), [#384](https://github.com/DeusMaximus/plamotrack/issues/384) (a retry re-adds a line the first try created), [#385](https://github.com/DeusMaximus/plamotrack/issues/385) (Settings → Language and region sends all five settings on every save). All `bug`, none triaged.
- **Decisions (the owner's, 2026-11-19):** #378's call 1 accepted (a retry does not re-send what the first try stored over an agent's later write); #378's money rule is "each amount travels with the order's currency, never with the other amount", two cases left as on `main` (#382); merge both PRs; file #379–#385 and make (c) on `main`; triage in a new session.
- **State:**
  - `main` is at `0daf5e5` plus this entry. CI on `0daf5e5` was running when this was written: read `gh run list --branch main` before starting a wave. Neither PR added a migration.
  - **No PR open, no worker or reviewer running, both lanes free.** Worker worktrees, scratch worktrees and every database made this wave are gone. Branches `356-import-text-whitespace` and `358-order-dialog-header-fields` remain, locally and on the remote. Six T3 reviewer worktrees (detached or `t3/…`) are T3's to remove, three of them this wave's Sol rounds at `876a1f4`, `b90cdf2` and `397a295`.
  - `backend/mutation_test.py` has 824 cases (#356 added six). #358's 20 mutants are frontend and live only in PR #378's body.
  - **This session's orchestrator ran on Opus 5.5, not the roster's Fable 5.2,** because the owner opened it that way. Nothing in the loop depended on it; the roster is unchanged.
  - **Unreleased on `main`:** #333, #341/#343, #346/#352, #348, #349, #350, #366, #354, #361, #356, #358, plus #351's docs drift.
  - **Carried:** the owner's LXC is on v0.6.0-alpha. Owed to plamotrack-ios: #348–#350's fields, codes and scenarios, and #356's comparison rule (Python's `str.strip` set) and a scenario runner that seeds `given` text as written. The dev DB may be behind (`alembic upgrade head`). PR #184 (Japanese, draft) waits on a native reviewer.
- **Waiting on the owner:**
  - Readiness comments for #369–#371, #374–#376 and #379–#385; none is triaged. #376 needs a decision first (notes or one-line boxes). #382 needs one too: what the dialog says and does when its money changed under it.
  - #184 still needs a native Japanese reviewer.
- **Next:** a new session as orchestrator, from `.agents/orchestration.md` step 1; triage comes first.
  - **`OrderFormModal.tsx` queue, one at a time:** #369 (briefed), #382, #383, #384. Pair each with a backend issue: #374 (`backend/app/mcp.py`), #370, #371, #379, #380, #381 (#381 needs normalising on write and a migration: briefed). Keep #371 out of #355's wave (`app/auth/mcp_oauth.py`).
  - **Later:** #375 (briefed, `ui.tsx`), #376, then #355 (OAuth: briefed, the likeliest to meet a refusal). The next release: #351, #344. M6.7: #279's edge probes, then #281, #282. M7 waits on #28.

## 2026-11-19 — Claude Code (Opus 5.5) — #358: PR #378 at `397a295`, briefed round 2 GO with one P3 (handled after the merge); ready for the owner
- **Done:**
  - [PR #378](https://github.com/DeusMaximus/plamotrack/pull/378) (closes #358), branch `358-order-dialog-header-fields`, head `397a295`, against `main` at `a7d005a`. `OrderFormModal.tsx`: header fields sent only when changed; `base` (what the dialog knows is stored, re-based after each successful step) and `holds` replace the four `applied` latches; lines compared by id; a line's quantity is a string in the form, as its box holds it (round 1, finding 1); each amount stored in the order's currency (shipping, discounts) travels with the currency, never with the other amount (owner's decision on round 1, finding 2). `KitFormModal.tsx` and `RetailersPage.tsx` send dirty fields only. `lib/sameValue.ts`. Release note in `.agents/next-release.md`, after `#356`'s.
  - Tests: `order-lossless.spec.ts` (66, a 35-test `describe` for #358), `dialog-agent-writes.spec.ts` (6). Negative control over the 72: `a7d005a` 27 red / 45 green, `b90cdf2` 5 / 67, `397a295` 0 / 72. 20 mutants, all killed. Full from-empty Chromium at `397a295`: 357 passed, 99 skipped, counts 0. WebKit app/phone/tablet, four dialog specs: 109 passed, 15 skipped.
  - Reviews: Codex connector at `e1a45fb` (one P2, fixed at `9f6d9b7`), at `9f6d9b7`, `b90cdf2` and `397a295` (no findings). Briefed round 1 (Sol, `b90cdf2`): NO-GO; findings 1 and 2 fixed at `397a295`, finding 3 filed as #383. Briefed round 2 (Sol, `397a295`): GO, one P3 (finding 4), answered [on the PR](https://github.com/DeusMaximus/plamotrack/pull/378#issuecomment-7003449101). PR body's Coverage record brought up to round 2 without moving the head. `b90cdf2` merged `main` at `a7d005a` (#377).
  - **Merged:** squash-merged as **`0daf5e5`** at the reviewed head `397a295`; #358 is closed. Reviews as above; Greptile did not run (credits). Re-run by the orchestrator: `b90cdf2` merging `main` checked as mechanical (outside `.agents/next-release.md`, the same patch id against `a7d005a` as against `30b5865`); round 1's five regression tests, with the head's spec in a scratch worktree, 5 red at `b90cdf2` on the request-body and stored-value assertions and green at `397a295`, counts 0 afterwards. Round 2 re-measured by Sol: the counts above, all 20 mutants, a 384-cell money sweep against `a7d005a` (288 identical, 80 intended differences, 16 retry cells that now answer 422 where `main` deletes an agent's voucher, stated under #382). After the merge: finding 4 corrected in `.agents/next-release.md` on `main`; [#383 comment](https://github.com/DeusMaximus/plamotrack/issues/383#issuecomment-7004082497) for the kit and retailer source comments. Follow-ups filed: #382, #383, #384.
- **Decisions:** call 1 (a retry does not re-send what the first try stored) accepted by the owner (2026-11-19). The money rule narrowed by the owner, keeping two limitations as on `main` (#382). Finding 4 and the kit/retailer source-comment qualification are handled after the merge: the release note corrected on `main`, the comments on #383. No push after round 2.
- **State:** CI green on `397a295` (Backend, Frontend, Integration). No migration, no backend change. Databases dropped; worktree removed by the orchestrator; branch left.
- **Waiting on the owner:** nothing for this PR.
- **Next:** the proposed Settings → Language and region follow-up is filed as #385. #369 (`OrderFormModal.tsx`) can follow.

## 2026-11-19 — Claude Code (Opus 5.5) — #356: the importer compares stored text as parse_text reads the cell (PR #377)

- **Done:**
  - [PR #377](https://github.com/DeusMaximus/plamotrack/pull/377) on branch `356-import-text-whitespace`, head `876a1f4`, against `main` at `30b5865`. Closes #356.
  - `ColumnSpec.as_read` (`spec.py`): for a `parse_text` column, the stored value through `stripped_or_none`; otherwise the value itself. `_classify` (`importing.py`) compares through it; `FieldChange.before` stays the raw stored value. No write path or stored value changes.
  - `tests/test_import_text_whitespace.py`, 9 tests: all 30 stored `parse_text` columns × 4 wrapped values; an update of another column leaves trimmed text as stored; genuine edits in merge (`update`) and replace_all (`create`); the export carries the whitespace.
  - Four scenarios in `imports.json`. `test_scenarios.py` seeds `given` text as written and checks every `given` value was stored before step 1. `testing-and-review.md` → "Behaviour scenarios" says so.
  - Mutation cases `356-1`…`356-5` and `scn-20` (818 → 824), all killed. `tests/test_import_text_whitespace.py` added to `TEST_FILES`. The anchor test passes.
  - `.agents/next-release.md` entry, as its own section at the end.
  - **Merged:** squash-merged as **`a7d005a`** at the reviewed head `876a1f4`; #356 is closed. Reviews: the Codex connector covered `7d000fd` with no findings (`876a1f4` changes one line of `.agents/next-release.md`); briefed round 1 (Codex GPT-6.1 Sol, at `876a1f4`) **GO** with two P3s, both reproduced and answered on the PR, the coverage record brought up to the round; Greptile did not run (credits). Re-run by the orchestrator at `876a1f4` in a scratch worktree: mutants `356-1` and `356-3` RED under the harness; the new file, `test_scenarios.py` and the anchor test 70 passed. Follow-ups, at the owner's word: (a) and (b) filed as [#379](https://github.com/DeusMaximus/plamotrack/issues/379), (d) as [#380](https://github.com/DeusMaximus/plamotrack/issues/380), (e) as [#381](https://github.com/DeusMaximus/plamotrack/issues/381), and (c) made on `main` in `.agents/next-release.md`: (a) the scenario seed check keys an id-less row as `"singleton"` where `state()` uses `"1"`, so an `instance_settings` seed fails (P3 1); (b) the shared scenarios don't exercise U+001C–U+001F, the Python/Swift trim difference (P3 2); (c) the release note should say a blank cell now leaves a whitespace-only stored value in place; (d) `POST /kits` accepts a whitespace-only `name`/`grade`, whose export is then refused on re-import; (e) replace_all restores free text trimmed.
- **Decisions:** the issue's first option (compare, don't normalise). replace_all pinned, not changed. The blank-reading case skips the 13 required columns and the `other` line's description.
- **State:** CI green at `876a1f4`. Local suite at `7d000fd`: 4072 passed, 1 xfailed. No migration. Databases dropped; the worker's worktree removed; branch `356-import-text-whitespace` left locally and on the remote. Sol's T3 worktree (detached at `876a1f4`) is T3's to remove.
- **Waiting on the owner:** readiness comments for #379, #380, #381.
- **Next:** owed to plamotrack-ios: the comparison rule (Python's `str.strip` set), and a scenario runner that seeds `given` text as written.
