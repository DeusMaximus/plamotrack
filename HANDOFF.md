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

## 2026-11-19 — Claude Code (Fable 5.2) — orchestrator: wave 1 MERGED (#367 as `95adab3`, #368 as `b515041`); wave 2 MERGED (#373 as `de7fa0d`, #372 as `95a3906`); #369–#371 and #374–#376 filed; nothing in flight

- **Done:**
  - **Wave 1, the loop's first run.** [PR #367](https://github.com/DeusMaximus/plamotrack/pull/367) (#359) merged as **`95adab3`** and [PR #368](https://github.com/DeusMaximus/plamotrack/pull/368) (#366) as **`b515041`**, each at its reviewed head with the owner's sign-off. The two entries below are the workers', with what was re-measured.
  - **Filed, at the owner's word:** [#369](https://github.com/DeusMaximus/plamotrack/issues/369), an order dialog open while the reference currency changes records a new line's snapshot in the old currency (Sol's P3 on #368; `bug`, `briefed-review`). [#370](https://github.com/DeusMaximus/plamotrack/issues/370), the registration guard's JSON check has no test of its own. A [comment on #238](https://github.com/DeusMaximus/plamotrack/issues/238#issuecomment-6992455678) adds a failed `/meta` refetch to its scope.
  - **Full mutation harness run on `main` at `b515041`:** 813 cases, 808 RED. Four GREEN: `inv-17b`, `inv-20`, `inv-21` (the three whose tests live in `mutation_test.py`) and `moa-61` (`register_client`'s public-client normalisation). One NONE: `scan-20`, whose test #248 removed. `inv-20` was confirmed alone through the unmodified harness. None is diagnosed. Filed as [#371](https://github.com/DeusMaximus/plamotrack/issues/371).
  - **Docs, from what the first run got wrong:** `review-brief.md` tells the reviewer to check the PR head out (a delegated worktree is cut from the briefing session's commit). `orchestration.md` → "Briefed rounds" has a step for sending the posted review to the worker's thread. `testing-and-review.md` → "Mutation testing" has the measured timing and a shard wrapper.
- **Decisions (the owner's, 2026-11-19):** merge both; file #369, #370 and then #371; the failed `/meta` refetch is a comment on #238, not an issue; the orchestrator runs the full harness; start wave 2; merge #373 and file #374; merge #372 and file #375 and #376; a field that was only tabbed through may be saved with the space (#361). The compile check of each mutant (#367's third proposal) was not taken up.
- **State:**
  - `main` is at `95a3906` plus this entry, with all four merges of the session. Each PR's three checks passed on its merged head; CI on `main` with both wave 2 merges had not finished when this was written: read `gh run list --branch main` before starting a wave. After wave 1 the orchestrator ran the anchor test on merged `main` and read one Alembic head, `b7d4f0a3c915`; wave 2 added no migration.
  - **Wave 2 is merged and both lanes are free.** [PR #373](https://github.com/DeusMaximus/plamotrack/pull/373) (#354) as **`de7fa0d`** and [PR #372](https://github.com/DeusMaximus/plamotrack/pull/372) (#361) as **`95a3906`**; their entries are below. No PR of this session is open, and no worker or reviewer is running. Wave 2's worker worktrees, scratch worktrees and databases are gone; the branches `354-mcp-schema-errors` and `361-line-break-one-line-fields` remain, locally and on the remote.
  - **Filed from wave 2, none triaged:** [#374](https://github.com/DeusMaximus/plamotrack/issues/374) (MCP `create_order` reads an empty `currency_code` as the reference currency; `backend/app/mcp.py`), [#375](https://github.com/DeusMaximus/plamotrack/issues/375) (an `Input` given its value as a prop still joins the words on first mount; `briefed-review`; `frontend/src/components/ui.tsx`), [#376](https://github.com/DeusMaximus/plamotrack/issues/376) (two notes columns edited in one-line boxes; `InventoryPage.tsx`).
  - **#361 turned out to owe a round:** its fix wraps the `value` setter of the shared `Input`, so the orchestrator added `briefed-review` during the wave. Greptile reviewed neither wave 2 PR: the organisation's free-plan credits are used up for the period.
  - Wave 1's worker worktrees, the scratch worktrees and every `plamotrack_test_*` and `plamotrack_e2e_*` database made for wave 1 are gone. The local and remote branches `359-mutation-anchors` and `366-stale-meta-order-dialog` remain.
  - `settings.spec.ts:129` should no longer fail when two lanes run e2e (#366 is fixed). Not re-measured under two lanes.
  - **A serial harness run is now hours:** about 12 s a case over the first eight, so roughly 2.7 hours at 813 cases. Six shards took 28 minutes.
  - **What the loop's first run showed, beyond the doc edits:** a worker hands back before the briefed round posts, and it had stopped watching its PR by then. Greptile's first pass found the one P1 of the wave (#368: a late import wiped an open draft).
  - **Unreleased on `main`:** #333, #341/#343, #346/#352, #348, #349, #350, #366, #354, #361, plus #351's docs drift (`.agents/next-release.md` has #366's entry). #359 changes nothing a user sees.
  - **Carried, unchanged:** the owner's LXC is on v0.6.0-alpha. Owed to plamotrack-ios: #348–#350's fields, codes and scenarios. The dev DB may be three migrations behind (`alembic upgrade head`). PR #184 (Japanese, draft) waits on a native reviewer. Four T3 reviewer worktrees are T3's to remove: two from 2026-11-12 and this session's two Sol rounds (detached at `047328d` and `2a0be11`).
- **Waiting on the owner:**
  - Readiness comments for #369, #370, #371, #374, #375 and #376: none is triaged. #376 needs a decision first: whether the two boxes are notes (multi-line) or one-line labels. `moa-61` and `scan-20` (#371) are in `app/auth/mcp_oauth.py`, so keep #371 out of #355's wave.
  - #184 still needs a native Japanese reviewer.
- **Next:** a new session as orchestrator, from `.agents/orchestration.md` step 1.
  - **Wave 3:** #356 (the importer's comparison) and #358 (the order dialog), both briefed. #356 may add mutation cases; `mutation_test.py` has 818 since #354 added five, and the anchor test fails a PR that stales one. #358 is `OrderFormModal.tsx`, which #368 changed.
  - **Later:** #369 (briefed; it is `OrderFormModal.tsx` again, so after #358), #370, #371, #374 (`backend/app/mcp.py`), #375 (briefed) and #376, then #355 (OAuth and token territory: briefed, the likeliest to meet a refusal, no readiness comment yet). The next release: #351, #344. M6.7: #279's edge probes, then #281, #282. M7 waits on #28.

## 2026-11-19 — Claude Code (Opus 5.5) — #361: PR #372 at `f84ad16` (main merged in), round 1 GO with two P3s, answered; CI queued at hand-back
- **Done:**
  - [PR #372](https://github.com/DeusMaximus/plamotrack/pull/372) (closes #361), branch `361-line-break-one-line-fields`. `frontend/src/components/ui.tsx`: the shared `Input` wraps its node's `value` setter (before the caller's ref) so a stored CR/LF/CRLF shows as a space; `frontend/src/lib/oneLine.ts` (+ unit test); `frontend/e2e/one-line-breaks.spec.ts`, 8 tests (four dialogs × `\n`/`\r\n`, typed and never-focused fields). Writers unchanged (owner's decision). Release note in `.agents/next-release.md`.
  - Measured at `c6631a7`: 8 red on `main` in Chromium and in WebKit; 9/9 green in both at the fix; full Chromium suite from empty 312 passed, 99 skipped, counts 0; WebKit `phone` dialog-keyboard/dialogs/lists 28 passed, 22 skipped. Three mutants killed.
  - Briefed round 1 (Codex GPT-6.1 Sol, at `2a0be11`): GO, two P3s, both reproduced and answered. Finding 1 (a `value`/`defaultValue` prop on first mount still joins the words, e.g. `?q=Alpha%0ABeta`): left for a follow-up; overclaims corrected. Finding 2 (a focused field is saved with the space, since react-hook-form copies the box on blur): accepted; wording fixed at `8c54d32`, no code or test change.
  - `f84ad16` merges `main` at `de7fa0d` (#373). Conflict only in `.agents/next-release.md`: `main`'s text kept, `#361` placed after `#354`, unchanged. The merge commit kept git's default message, without the Co-Authored-By line; not amended because it was already pushed.
  - **Merged:** squash-merged as **`95a3906`** at head `f84ad16`; #361 is closed. Reviews: briefed round 1 GO at `2a0be11` with two P3s, both answered; the Codex connector covered `c6631a7`, `2a0be11`, `8c54d32` and `f84ad16` with no findings; Greptile did not run (out of credits). The orchestrator added `briefed-review` to #361 once the fix reached the shared `Input`. No second round: the orchestrator read `8c54d32` as comments and Markdown only, and checked `f84ad16` as mechanical (outside `.agents/next-release.md` the merge's change equals `main`'s own, by patch id). Run by the orchestrator at `2a0be11`, Chromium, from empty: the spec 9 passed; 8 failed with `main`'s `ui.tsx`; a field focused and left with Tab is saved with the space, a never-focused one keeps its break. CI passed on `f84ad16`. The owner accepted the tab-through behaviour (2026-11-19). Follow-ups filed: [#375](https://github.com/DeusMaximus/plamotrack/issues/375) (finding 1, with the blur regression test; `briefed-review`) and [#376](https://github.com/DeusMaximus/plamotrack/issues/376) (the two notes boxes).
- **Decisions:** fix in the shared `Input`, not in form defaults. The guarantee as stated: a field that never had focus keeps its break; one that had focus can be saved as shown.
- **State:** head `f84ad16`, mergeable. No code changed after the reviewed head `2a0be11`. CI on `f84ad16` queued at hand-back; `8c54d32`'s run still in progress. Codex connector: no findings at `c6631a7` or `2a0be11`; review requested on `8c54d32` and `f84ad16`, not yet reported. Greptile: no review (credits used up). Databases dropped. Worktree and branch left for the orchestrator.
- **Waiting on the owner:** the merge of #372 once CI is green; filing the follow-ups below.
- **Next:** proposed, not filed: (1) finding 1: normalise a string `value`/`defaultValue` at render in `Input`, keeping the caller's raw value, with a first-mount test and the focus-and-blur regression test; (2) the catalog dialog's display-item Notes and tool Condition notes as a `Textarea`. #358 and #369 touch `OrderFormModal.tsx` after this one.
