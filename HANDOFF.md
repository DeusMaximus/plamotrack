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

## 2026-11-04 — Claude Code (Opus 5.5) — #348 MERGED as `ff50f94` (PR #357); reviews now start through T3 Code; #358 filed

- **Done:**
  - **[PR #357](https://github.com/DeusMaximus/plamotrack/pull/357) merged** at reviewed head `11a280f`, closing #348: `orders.notes` on REST, MCP, `orders.csv`, the order editor and the expanded lines, with one additive migration, `8e41c7d2a9f6`.
  - **Three Codex gpt-6.1-sol rounds:** NO-GO on a P2 (a save that never touched the note erased what an agent wrote, fixed `039007b`), NO-GO on a P3 (restoring a note on a retry after a failed ship or receive was ignored, fixed `11a280f`), then GO with no findings. Lesson: `lessons.md` → "A dialog's opening value stops being what's stored (#348, PR #357 rounds 1–2)".
  - **Filed [#358](https://github.com/DeusMaximus/plamotrack/issues/358):** the order dialog's eight other header fields overwrite what an agent wrote while it was open (measured). Order lines already have the retry trap (measured), a likely fix would give header fields the same trap, and the kit and retailer dialogs look the same from reading only.
  - **Docs on `main`:** `testing-and-review.md` and `review-brief.md` now say how a round starts through T3 Code. Scratch stays out of `.dev/<issue>/`.
- **Decisions (owner, 04/11):** the authoring agent starts a round itself with `delegate_task` once the owner asks for one, and the paste is the fallback outside T3 Code. T3 reviewers post on the PR, for the public record. An all-P3 NO-GO has to justify why it can't merge and be fixed in a separate issue, and whether that holds is the owner's call.
- **State:**
  - PR checks at `11a280f`: Backend, Frontend and Integration all passed. CI on `main` at `ff50f94` was still running when this was written.
  - Round 3 passed `order-lossless.spec.ts` in Chromium and WebKit, 19 probes of its own, ten negative controls and frontend 672. Not run on this PR: the rest of Playwright locally, `settings`, enlarged fonts, a request that fails in transport after the server committed it, a real MCP client over HTTP.
  - **The dev database is not migrated to `8e41c7d2a9f6`:** run `alembic upgrade head` before running `main` against it.
  - **The owner's LXC is on v0.6.0-alpha.** **Unreleased on `main`:** #333, #341/#343, #346/#352, #348, with #351's docs drift pending (`.agents/next-release.md`).
  - **Owed to plamotrack-ios, unmeasured:** the new API field and CSV column. Also: its planner still reports two diagnostics for an unreadable required cell, its handling of a NUL hasn't been run, and it hasn't re-synced `api-error-codes.json` for `request.text_unstorable`.
  - **Left behind:** reviewer scratch from rounds 1 and 2 in gitignored `.dev/348/`, harmless. It predates the scratch rule.
  - **Carried, not reverified:** #344 (image pins, before or with the next release; bump mechanism undecided). testhost is in the tunnel configuration from the 0.6.0 gate; don't recreate its Keycloak container. Owner: allow `pkg-containers.githubusercontent.com` in cloud Network access, delete the Claude.ai Testing connector, complete #278's skill-zip check. Known gaps: #238, #324 (local e2e uses `--workers=1`), #320. plamotrack-ios can re-sync #342's scenarios once its #15 adds `update_order` and `delete_order`.
- **Next:**
  - #350 and #349, which have open product questions for the owner (does `get_summary` spend use paid or shelf price); #354, #355, #356, #358.
  - **The next release:** #351, #344. **M6.7:** #279's edge probes, then #281, #282. **M7** waits on #28.

## 2026-11-03 — Claude Code (Opus 5.5) — #348 order notes: PR #357 open at `a25fce9`, awaiting review; #356 filed

- **Done:**
  - **[PR #357](https://github.com/DeusMaximus/plamotrack/pull/357)** open, not merged, on `feat/348-order-notes`. Closes #348. `orders.notes` (nullable, one additive migration `8e41c7d2a9f6`) on REST, MCP, `orders.csv` (last column), the order editor, and the foot of the expanded lines in both shapes. Omitted leaves it; null or blank clears it.
  - `services/text.stripped_or_none` is read by `OrderNotes` and `parse_text`, so a note never holds surrounding whitespace and its export re-imports as no change (rule 10).
  - Tracked mutants `348-1` to `348-6`, all killed. `.agents/next-release.md` has the entry.
  - **Filed [#356](https://github.com/DeusMaximus/plamotrack/issues/356):** on `main`, a stored text value with surrounding whitespace makes a re-import an update. Measured on `retailers.notes` only.
  - Review brief for Codex at `.dev/348/review-brief-1.md` (gitignored, in the main checkout). The owner runs it; no review round has happened.
- **Decisions (owner, 03/11):** notes are not searched, and searching an order by what it contains is for much later, alongside the planned gift-card, voucher and untracked-item work. Notes stay off the starter sheet.
- **State:**
  - At `a25fce9`: backend 3764 passed, 1 xfailed; frontend 672 passed; lint and build clean. Playwright (Chromium; `order-lossless`, `lists`, `dialogs`; app, phone, tablet): 76 passed, 51 skipped, before the last e2e edit; after it only the new not-cut test and the sideways-scroll test were rerun. CI on the PR was not read before this entry.
  - Not run: the rest of Playwright locally, WebKit, `settings`, the packaged stack, a real MCP client, an older release reading a newer archive.
  - **The dev database has not been migrated to `8e41c7d2a9f6`:** run `alembic upgrade head` before running that branch against it. `plamotrack_test` was left migrated by the branch's last run, and its head isn't on `main` until the PR merges. A pytest run on `main` before then can't downgrade it: use a scratch `TEST_DATABASE_URL`, or drop that database.
  - **The owner's LXC is on v0.6.0-alpha.** **Unreleased on `main`:** #333, #341/#343, #346/#352, with #351's docs drift pending (`.agents/next-release.md`).
  - **Owed to plamotrack-ios, unmeasured:** the new API field and CSV column, once #357 lands. From the last entry: its planner still reports two diagnostics for an unreadable required cell, its handling of a NUL hasn't been run, and it hasn't re-synced `api-error-codes.json` for `request.text_unstorable`.
  - **Carried, not reverified:** #344 (image pins, before or with the next release; bump mechanism undecided). testhost is in the tunnel configuration from the 0.6.0 gate; don't recreate its Keycloak container. Owner: allow `pkg-containers.githubusercontent.com` in cloud Network access, delete the Claude.ai Testing connector, complete #278's skill-zip check. Known gaps: #238, #324 (local e2e uses `--workers=1`), #320. plamotrack-ios can re-sync #342's scenarios once its #15 adds `update_order` and `delete_order`.
- **Next:**
  - **PR #357:** the review round, then the owner's merge call (`gh pr merge --squash --auto --match-head-commit <reviewed sha>`, never `--admin`).
  - Then #350 and #349, which have open product questions for the owner (does `get_summary` spend use paid or shelf price); #354, #355, #356.
  - **The next release:** #351, #344. **M6.7:** #279's edge probes, then #281, #282. **M7** waits on #28.
