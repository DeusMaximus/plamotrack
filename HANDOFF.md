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

## 2026-11-19 — Claude Code (Opus 5.5) — #359: twelve stale mutation anchors repaired, CI anchor check; PR #367 open
- **Done:** [PR #367](https://github.com/DeusMaximus/plamotrack/pull/367), branch `359-mutation-anchors`, head `d668eea`, against `main` at `4fab42c`, closes #359. The twelve stale cases in `backend/mutation_test.py` (auth-22, m63-10, oidc-20, oidc-35, moa-22, moa-25, moa-45, moa-76, aud-6, 341-1, 341-4, 346-6) are re-anchored on where their code moved; none retired. moa-22 now targets `app/auth/mcp_oauth_state.py`. New `backend/tests/test_mutation_anchors.py` requires each anchor in `CASES` to match its file exactly once, so the Backend check fails the PR that moves an anchored line. `.agents/testing-and-review.md` → "Mutation testing" gained one paragraph on it.
  - **Merged:** squash-merged as **`95adab3`** at the reviewed head `d668eea`; #359 is closed. Reviews: the Codex connector and Greptile both covered `d668eea` with no findings, and no briefed round was owed. Run again by the orchestrator: the anchor test red on `4fab42c` (naming the twelve) and green on the branch; `moa-45.` and `341-1.` RED under the harness; the f4 test passing with the guard not installed. Follow-ups: [#370](https://github.com/DeusMaximus/plamotrack/issues/370) filed (the guard's JSON check); the full harness run on `main` is the orchestrator's, in the entry above; the compile check of each mutant was not taken up.
- **Decisions:** a unit test, not a `--check-anchors` flag (both were allowed). moa-45's `-k` re-pointed at the registration quota and cap tests: its f4 test stays green with the guard removed, because the SDK under FastMCP 4 returns the same 400.
- **State:** CI is green on `d668eea`. The Codex connector and Greptile both reviewed `d668eea` with no findings. All twelve re-anchored cases go RED under the harness. Stale count 12 → 0 (813 cases). Nothing under `backend/app/`. The harness ran correctly with a non-default `TEST_DATABASE_URL` (`plamotrack_test_359`, now dropped).
- **Waiting on the owner:** merge of #367. Whether to file: `ClientMetadataBody`'s JSON check may be redundant with the SDK's; a compile check of each mutant in the anchor test; a full harness run on `main`.
- **Next:** wave 2 (#354, #361). #354 and #356 may add mutation cases, and the anchor test now fails their PRs if any anchor goes stale.

## 2026-11-19 — Claude Code (Fable 5.2) — orchestration set up: #364 MERGED as `69ba794`, #365 as `ca5eb75`; #366 filed; three waves triaged, nothing launched

- **Done:**
  - **[PR #364](https://github.com/DeusMaximus/plamotrack/pull/364)** squash-merged as **`69ba794`**; #144 is closed. `DEV_API_PORT` and `DEV_WEB_PORT` (`frontend/devPorts.ts`) move the dev servers Vite, Playwright and the e2e helpers use, so two checkouts can run e2e at once. `.agents/testing-and-review.md` → "More than one session at a time" is the setup for a second session: its own worktree, `TEST_DATABASE_URL` and port pair.
  - **[PR #365](https://github.com/DeusMaximus/plamotrack/pull/365)** squash-merged as **`ca5eb75`**. `.agents/orchestration.md` is new: the loop, what makes an issue ready, lanes, the roster by seat, the worker brief, the checklist before a PR is called ready, refusals, where to stop for the owner. The review docs and the brief template follow it, and this file's template gained "Waiting on the owner".
    - Both had the Codex connector and Greptile on their final heads. The connector's one finding on #365 (a P2: the lane setup it points at was missing) was the unmerged #364; answered on its thread by merging `main` in, and clean at `cd630bf`.
  - The labels `briefed-review` and `owner` exist on the repository.
  - **#366 filed:** a new-order dialog opened just after a currency change keeps the old reference currency. Found by the two-suite run below, reproduced every time by holding `/api/meta` for 1.5 s.
  - **Triage, with the owner's agreement:** readiness comments posted on #366, #359, #354, #356, #361 and #358. #356 and #358 are labelled `briefed-review`. Each comment carries the owner's decisions for its issue.
- **Decisions (the owner's, 2026-11-18):**
  - A briefed round is owed by the `briefed-review` label, set at triage or when the work turns out bigger than it looked. The orchestrator starts it.
  - The Codex connector has to cover the final head of a PR that owes no round. Greptile's first pass is a bonus.
  - Two lanes for now. Claude Opus 5.5 implements every issue; Sonnet has no seat here. GPT-6.1 Sol reviews until the owner has tried 6.2.
  - A refusal is a stop: the owner pastes the work into the Codex app with Daybreak Blue, which T3 Code cannot reach.
  - The goal is a PR the owner can sign off. Stop and change tracks when review rounds loop.
  - **2026-11-19:** GPT-6.1 Sol is the only reviewer for now; GLM and Cursor hold no seat (the roster's second-opinion row is gone).
  - **#356:** the importer compares as the parser reads. **#361:** fix the editor only (a stored line break shows as a space); the Other line's description stays one line. **#358:** re-base the form after each stored step, and the person's save wins when both wrote a field.
- **State:**
  - `main` is at `ca5eb75` plus this entry; CI passed on `ca5eb75`. No PR of this session is open, no worker or reviewer is running. PR #184 (Japanese, draft) still waits on a native reviewer.
  - **The loop has not run in this repository.** Wave 1 is its first test; edit `.agents/orchestration.md` in place where a step turns out wrong.
  - Measured for #364: two full e2e suites at once, each on a database migrated from empty. On 8001/5174 from a second worktree: 300 passed, 99 skipped. On the defaults: 291 passed, 1 failed (`settings.spec.ts:129`, which is #366; 3 of 3 alone), 8 not run. Two backend sessions on separate databases: `tests/test_orders.py`, 42 passed in each.
  - **Until #366 is fixed, `settings.spec.ts:129` can fail in a local e2e run when two lanes are busy.** Put it in the other lane's "already known" list.
  - A worktree whose `frontend/node_modules` is a symlink fails six `lists.spec.ts` font tests. Anything that runs e2e needs its own `npm ci` (the docs say so now).
  - Not run: the mutation harness with a non-default `TEST_DATABASE_URL`. #359's readiness comment asks its worker to report on it.
  - The reviewer table in `testing-and-review.md` → "Which reviewer" keeps its GLM and Cursor rows as history. The roster in `orchestration.md` holds the seats and wins.
  - The readiness drafts are also in `.dev/wave-1/` in the main checkout (gitignored). The merged branches `144-dev-ports` and `orchestration-docs` are still on the remote.
  - **Carried, unchanged:** the owner's LXC is on v0.6.0-alpha. Unreleased on `main`: #333, #341/#343, #346/#352, #348, #349, #350, plus #351's docs drift (`.agents/next-release.md`); #364 and #365 change nothing a user sees. Owed to plamotrack-ios: #348–#350's fields, codes and scenarios. The dev DB may be three migrations behind (`alembic upgrade head`). Two T3 reviewer worktrees from 2026-11-12 are T3's to remove.
- **Waiting on the owner:** nothing from this session. #184 still needs a native Japanese reviewer.
- **Next:** a new session as orchestrator, starting from `.agents/orchestration.md`. #366, #361 and #358 all touch the dialogs, so each is in a different wave.
  - **Wave 1:** lane 1 #366 (frontend; a briefed round only if a wrong snapshot turns out to be stored), lane 2 #359 (`backend/mutation_test.py` and an anchor check in CI; nothing under `backend/app/`).
  - **Wave 2:** #354 (`backend/app/mcp.py`) and #361 (the dialogs' one-line inputs).
  - **Wave 3:** #356 (the importer's comparison) and #358 (the order dialog), both briefed. #354 and #356 may add mutation cases, so tell each worker which the other owns.
  - Then #355 (OAuth and token territory: briefed, and the likeliest to meet a refusal; no readiness comment yet). The next release: #351, #344. M6.7: #279's edge probes, then #281, #282. M7 waits on #28.

## 2026-11-12 — Claude Code (Opus 5.5) — #184 (Japanese catalogue) brought up to `main` at `034df59`; still disabled, waiting on a native reviewer

- **Done:**
  - **[PR #184](https://github.com/DeusMaximus/plamotrack/pull/184)** (draft, `feature/ja-localisation`): merged `main` in at `d5370bd` (clean), then one catalogue commit, `034df59`. Summary comment: [#184 comment](https://github.com/DeusMaximus/plamotrack/pull/184#issuecomment-6821012916).
    - Coverage 593/797 → **797/797**. The 204 keys added since September are translated (Home, auth/OIDC, access tokens, theme, phone shell/filter sheet, order notes, adjustments, `other` lines, `api.auth.*`, `api.ingress.*`).
    - Deleted the 11 keys `main` removed (`nav.board`, `layout.tagline`, `board.*`). After the merge they were the one failing `catalogue.test.ts` case. Dropped the leading `+` from the six buttons that lost it in English. `kit_move_to_catalog_line` follows its #349 rewording.
    - `ja.json` is now in `en-AU.json`'s key order (plural groups carry `_other` only).
    - Meaning fixes: `orders.pillPending` was 保留中 ("on hold") for `ordered` orders, now 発送待ち. The pre-order tooltip said "not arrived" for "not released" (発売前). The future-date errors ruled out today. Also the reference-cost placeholder, "no longer exists", and count word order.
- **Decisions (owner deferred to the author, 2026-11-12):** the terminology, recorded in the comment above and superseding the PR body's list. 完成 (complete), 製作中 (building), ディテールアップパーツ (upgrade), 作品 (series), 到着 (received), 工具 / 在庫 (tools / inventory). Backlog is **split**: 未組立 as the kit status, 積みプラ for the Home heading and its strings. Data labels stay neutral; the hobby idiom goes on Home, as English does with "On the bench". The empty-backlog joke stays; 積みプラゼロ、お見事です。 is the safer alternative if a native reviewer prefers praise to teasing.
- **State:**
  - Local at `034df59`: vitest 684/684, lint (one existing warning in `Layout.tsx`), build, `git diff --check`, `i18n:report`. PR CI: Frontend passed; Backend and Integration were still pending when this was written.
  - Not done: no rendered pass with `ja` enabled. ディテールアップパーツ is the longest label: the inventory tab row scrolls on a phone (§13.7) and should fit from 768 px, unchecked on screen.
  - **Not for merging yet (owner):** enabling `ja` needs a named human Japanese reviewer plus the visual pass in `docs/translating.md`. The owner has no reviewer yet. Until then, keep the branch current: merge `main` in (never rebase), translate new `en-AU` keys, and compare changed `en-AU` values by hand, since coverage can't see them.
  - **Carried from the entry below, unchanged:** CI on `main` at `341119d` passed. The owner's LXC is on v0.6.0-alpha. Unreleased on `main`: #333, #341/#343, #346/#352, #348, #349, #350, plus #351's docs drift (`.agents/next-release.md`). Owed to plamotrack-ios: #348–#350's fields, codes and scenarios. The dev DB may be three migrations behind (`alembic upgrade head`). Two T3 reviewer worktrees are T3's to remove.
- **Next:** unchanged from the entry below: #358, #354, #355, #356, #359, #361; the next release (#351, #344); M6.7 (#279's edge probes, then #281, #282); M7 waits on #28. #184 waits on a reviewer.

## 2026-11-12 — Claude Code (Fable 5.2) — #349 MERGED as `6c70787` (PR #360); #350 MERGED as `0c8478b` (PR #362); #359, #361 filed

- **Done:**
  - **[PR #360](https://github.com/DeusMaximus/plamotrack/pull/360) merged** at reviewed head `b3cbae0`, closing #349: a sixth order-line type, `other`, with a `description`. It dispatches nothing in any order state. Migration `61442608b20e`. `EXPORT_VERSION` 1 → 2. One Codex gpt-6.1-sol round: GO, no findings.
  - **[PR #362](https://github.com/DeusMaximus/plamotrack/pull/362) merged** at head `acb7704`, closing #350: `order_adjustments` (a label and a positive amount in the order's currency), `adjustments` and per-currency `totals` on every order read, `order_adjustments.csv`, the editor's section and the Paid row. Migration `b7d4f0a3c915`. One Codex round at `a5e2fa1`: GO with two P3s, both fixed at `acb7704` and not re-reviewed (owner's call).
  - **The two P3s:** a retry after a half-failed save kept the intermediate adjustments (a second latch, `applied.current.adjustments`); and on a narrow phone at an enlarged font the Paid row ran past its card. The test for the second also found a card's line amounts cut at 40 px on any order, older than the PR, and fixed with it. Lesson appended: `lessons.md` → "A dialog's opening value stops being what's stored".
  - **Filed:** [#359](https://github.com/DeusMaximus/plamotrack/issues/359), twelve mutation cases whose anchors are stale on `main`. [#361](https://github.com/DeusMaximus/plamotrack/issues/361), a line break in a single-line field is dropped when the browser edits it (found by Greptile on #360; now also an adjustment's label). #363 was a duplicate of #358's retry section and is closed; #358 has the new measurement as a comment.
- **Decisions (owner):**
  - **#349:** untracked lines stay out of `get_summary` spend, and there is no conversion to a tracked line.
  - **#350:** spend summaries keep the shelf price; adjustments that exceed items plus shipping are refused, not clamped; adjustments are a list.
  - **#350, the author's calls, accepted by the review and merged:** the ceiling counts only lines in the order's own currency, plus shipping. The Orders list's Total is what was paid. The browser renders the server's `totals` and has no live Paid figure. An id-less CSV row matches on order and label, not amount. `EXPORT_VERSION` stays 2, since no release shipped between the two PRs.
- **State:**
  - PR checks at `acb7704`: Backend, Frontend and Integration passed. CI on `main` at `0c8478b` was still running when this was written.
  - Measured locally for #362: backend 4023 passed, 1 xfailed (at `65b84ee`; no backend change after). Frontend 683. Playwright 300 passed, 99 skipped (at `acb7704`, Chromium, one worker). 35 backend mutants and 10 frontend mutants killed. Not run: the fixes under WebKit, a real MCP client over HTTP, the table's Paid row under an enlarged font, two writers racing on one order's adjustments.
  - **`mutation_test.py`:** #362 re-anchored the two cases it moved (`stg-4`, `348-4`). The twelve from #359 are still stale. A change can stale an older case without touching it, and the harness only says so when that case is run: count every anchor against `main` before a review round (#359 has the script as a comment).
  - **The dev database was not touched.** The last entry had it behind `8e41c7d2a9f6`; if so it is now three migrations behind. Run `alembic upgrade head` before running `main` against it.
  - **The owner's LXC is on v0.6.0-alpha.** **Unreleased on `main`:** #333, #341/#343, #346/#352, #348, #349, #350, with #351's docs drift pending (`.agents/next-release.md`). The next release has two migrations that refuse a downgrade once used, and a version-2 archive that v0.6.0-alpha refuses.
  - **Owed to plamotrack-ios, unmeasured:** #348's field and column. #349: the type, the column, three diagnostic codes, three scenarios, export version 2. #350: the table, two read fields, one code (`order.adjustments_exceed_total`), three scenarios. Also still owed: two diagnostics for an unreadable required cell, a NUL, and `request.text_unstorable` in its `api-error-codes.json`.
  - **#358 is larger than when filed.** The dialog still restates `currency_code` and `shipping_cost_minor` on every save, and #350's ceiling now reads both. There are two per-field retry latches where the issue said eight would be the wrong shape.
  - **Left behind:** two T3 Code reviewer worktrees (`t3/review-349-brief`, `t3/review-order-adjustments`), T3's to remove. Merged branches are left on origin as before.
  - **Carried, not reverified:** #344 (image pins, before or with the next release; bump mechanism undecided). testhost is in the tunnel configuration from the 0.6.0 gate; don't recreate its Keycloak container. Owner: allow `pkg-containers.githubusercontent.com` in cloud Network access, delete the Claude.ai Testing connector, complete #278's skill-zip check. Known gaps: #238, #324 (local e2e uses `--workers=1`), #320. plamotrack-ios can re-sync #342's scenarios once its #15 adds `update_order` and `delete_order`.
- **Next:**
  - #358 (the general answer for the order dialog, now with a server rule behind it), #354, #355, #356, #359, #361.
  - **The next release:** #351, #344. **M6.7:** #279's edge probes, then #281, #282. **M7** waits on #28.
