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

## 2026-11-19 — Claude Code (Opus 5.5) — #354: PR #373 open, CI green, Codex connector clean; ready for the owner
- **Done:**
  - [PR #373](https://github.com/DeusMaximus/plamotrack/pull/373), branch `354-mcp-schema-errors`, head `36f7d72` (code at `f693248`), against `main` at `5ea1431`, closes #354. `backend/app/mcp.py`: `_build(schema, argument, /, **fields)` is the one way a tool body builds a request schema; a `ValidationError` becomes a `ToolError` "invalid <argument>: <rule>" (no input echoed), inside the tool's transaction, so nothing is stored, a shop named in the same call included. Sites: `create_order` (the only one that could fail), `create_kit`, `update_kit`, `update_kit_status`. The PR body lists all 31 tools.
  - `backend/tests/test_mcp_schema_errors.py`, 35 tests: `create_order`'s flat arguments in memory, over HTTP (modern and legacy era, real PAT), against REST's 422; the kit tools; the helper; an AST scan that fails on a `RequestModel` called in `app/mcp.py` outside `_build`. On `5ea1431`: 18 red / 17 green (commands and output in the PR body).
  - Five `354-` mutation cases, file added to `TEST_FILES`; all killed at `f693248`. `test_unstorable_text.py`'s `_refused` now accepts `ToolError` only.
  - `.agents/next-release.md`: a `#354` section at the end, and the `#346, #352` entry's "except for a few `create_order` arguments (#354)" clause removed.
  - **Merged:** squash-merged as **`de7fa0d`** at the reviewed head `36f7d72`; #354 is closed. Reviews: the Codex connector covered `f693248` and `36f7d72` with no findings; Greptile did not run (out of credits); no briefed round was owed. Run again by the orchestrator at `36f7d72`: the new file 18 red / 17 green with the base's `mcp.py`; the new file, the anchor test and `test_unstorable_text.py` green (555 passed); the five `354-` cases RED under the harness; six bad values carrying a marker string, none echoed. Follow-up: [#374](https://github.com/DeusMaximus/plamotrack/issues/374) filed (the empty `currency_code`).
- **Decisions:** a helper at each site, not a middleware (keeps server-side read-model failures as server errors; no shared mechanism, so no briefed round owed). The kit sites go through `_build` although nothing reaches them failing. Pydantic's messages kept as they are.
- **State:** CI green on `36f7d72` (Backend, Frontend, Integration). Codex connector: no findings on `f693248` or `36f7d72`. Greptile had not posted at hand-back. Full backend suite locally at `f693248`: 4059 passed, 1 xfailed. `plamotrack_test_354` dropped. No migration, nothing under `frontend/`, no anchored `app/mcp.py` line moved.
- **Waiting on the owner:** the merge of #373. Whether to file: MCP `create_order` turns `currency_code=""` into the reference currency where REST answers 422 (rule 1).
- **Next:** wave 3 (#356, #358). #356 may add mutation cases; `354-1`…`354-5` are anchored in `app/mcp.py` (`_build` and the `create_order`/`create_kit` sites). #361's `.agents/next-release.md` entry and this one both append at the end: the PR that merges second takes `main` in for that file.

## 2026-11-19 — Claude Code (Opus 5.5) — #366: PR #368 at `047328d`, briefed round 1 GO with one P3, answered; ready for the owner
- **Done:**
  - [PR #368](https://github.com/DeusMaximus/plamotrack/pull/368) (closes #366), branch `366-stale-meta-order-dialog`, head `047328d`. `frontend/src/lib/formMeta.ts`: `useFormMeta()` ignores a stale `/meta` (invalidated and not answered since, under `staleTime: Infinity`) and latches its first current copy while the gate is mounted. `OrderFormModal` and the inventory `ItemFormModal` gate on it. Release note in `.agents/next-release.md`.
  - Four e2e tests in `e2e/settings.spec.ts` (`settings` project): held `/api/meta` after a General save (order, tool) and after an `instance_settings.csv` import (order); a draft surviving an import that answers while a dialog is open.
  - Measured on `4fab42c`: a stale dialog stored `converted_currency_code: "AUD"` on an NZD instance (saved before `/meta` answered), or `null` (saved after).
  - Briefed round 1 (Codex GPT-6.1 Sol, at `047328d`): **GO**, one P3 (finding 2). It re-measured the base, the mutants (20 cells) and 18 settings tests. Answered on the PR; the PR body's "cannot reach" paragraph corrected and the coverage record updated. No commit.
  - **Merged:** squash-merged as **`b515041`** at the reviewed head `047328d`; #366 is closed. Reviews: briefed round 1 GO with one P3, answered and filed as #369; the Codex connector had no findings at either head; Greptile's P1 was fixed and answered at `047328d`. The orchestrator ran the full e2e suite from an empty database at `047328d`: 304 passed, 99 skipped. The orchestrator added `briefed-review` to #366 during the wave. Follow-ups: [#369](https://github.com/DeusMaximus/plamotrack/issues/369) filed, labelled `briefed-review`; the failed `/meta` refetch is a [comment on #238](https://github.com/DeusMaximus/plamotrack/issues/238#issuecomment-6992455678).
- **Decisions:** the gate, not the save. A failed refetch stays on Loading. Latch kept (Greptile's P1). Finding 2 becomes a follow-up, not a fix here, as orchestrator and reviewer agreed: the fix belongs at save time.
- **State:** CI green on `047328d` (Backend, Frontend, Integration). Codex connector: no findings on `fc8b985` or `047328d`. Greptile: one P1 on `fc8b985`, fixed and answered at `047328d`, not re-reviewed. Full from-empty e2e ran at `fc8b985` (303 passed, 99 skipped); at `047328d` only `settings.spec.ts` (18 passed, by the author and by the reviewer). Untested after round 1: WebKit, phone and tablet replays, the packaged stack, a real second-tab writer, late Add-only and Replace-everything imports.
- **Waiting on the owner:** the merge of #368; whether to file the two follow-ups below.
- **Next:** proposed issues, not filed: (1) a snapshot the browser derives against a reference that moved under an open dialog (a late import, another tab, a REST script): check at save, never relabel, keep explicit and stored pairs; (2) a failed `/meta` refetch leaves the dialogs on Loading with no error or retry. #358 and #361 touch `OrderFormModal.tsx` after this one; `settings.spec.ts:129` should no longer flake when two lanes run.
