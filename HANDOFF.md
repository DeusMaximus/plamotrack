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

## 2026-11-02 — Claude Code (Opus 5.5) — #346 + #352 MERGED as `1188a67` (PR #353); #354, #355 filed; the owner's LXC is on 0.6.0

- **Done:**
  - **[PR #353](https://github.com/DeusMaximus/plamotrack/pull/353)** squash-merged as **`1188a67`**, pinned to head `eb94002`. #346 and #352 are closed. Text a column or a response can't carry is a refusal, never a 500:
    - `services/text.py` is the one predicate (NUL, unpaired surrogate). `schemas/base.py`'s `RequestModel` covers every request body; `parse_text` covers a CSV cell, so the preview now errors the row; `refuse_unstorable_text` covers filters and MCP's flat arguments (new code `request.text_unstorable`); `OAuthStateStore` reads a NUL key as absent. Sign-in's three models stay on `BaseModel`, so a NUL in a password stays a wrong answer.
    - `has_utf8_form` judges JSON read and shown rather than stored, where it enters: a manifest (the warning, and the rows import) and a fetched CIMD document (an unknown client). `_is_usable_endpoint` does the same for OIDC discovery.
    - `_EchoResponse`: a 422 that can't echo a surrogate or `1e999` leaves without `input`.
    - `_ExpansionBudget.read` catches every `Exception` but `DomainError` and `MemoryError`, after three misses in its list (#341, #352, Zstandard).
    - OIDC: an unstorable `sub` is refused by the claim validator, a bad label is skipped, and the setup token is spent after the commit.
    - An unreadable required import cell reports one diagnostic, for every column type.
    - `tests/test_unstorable_text.py` names every body, text query parameter and flat MCP argument, and fails on a new one. Mutants `352-*` and `346-*` (32) are in `mutation_test.py`. Rule 6 in `AGENTS.md` carries the rule.
  - **Review:** Codex (gpt-6.1-sol, high) NO-GO twice, every finding P3, all reproduced and fixed. GLM 5.3 (Mistral-hosted) GO on a narrower brief, which I wrote and which said P3s alone aren't a NO-GO, so it is less independent than an open round. Greptile 5/5 at `df5ef1a`. All on the PR body's coverage record. The reviewers' findings came back to the session, not the thread.
  - **Filed:** [#354](https://github.com/DeusMaximus/plamotrack/issues/354) (`create_order`'s flat arguments that fail `OrderCreate` answer a generic error naming no field) and [#355](https://github.com/DeusMaximus/plamotrack/issues/355) (external JSON nobody has driven with these values: token responses, JWKS, other CIMD fields).
  - `.agents/lessons.md`: "A phrase the next refusal quotes (#353)". `.gitignore` ignores `.cursor/` (8e8b4c7, with the 29/10 entry below).
- **Decisions (owner, 02/11):** merge on GLM's GO without a third Codex round. `.cursor/` is ignored.
- **State:**
  - **The owner's LXC is on v0.6.0-alpha** (owner, 02/11). Older entries saying 0.5.2 were behind.
  - **Unreleased on `main`:** #333, #341/#343, #346/#352 (`.agents/next-release.md`). #351's docs drift is pending there too, as work to do in the next release cycle.
  - Backend 3675 tests collected. The last full local run was at `beb544f` (3606 passed, 1 xfailed); CI's Backend and Frontend passed on `eb94002`, and its required checks gated the merge. Packaged stack beyond CI, Playwright and a local 3.12 run: not run for this.
  - **Owed to plamotrack-ios, unmeasured:** its planner still reports two diagnostics for an unreadable required cell, its handling of a NUL hasn't been run, and it hasn't re-synced `api-error-codes.json` for `request.text_unstorable`. No behaviour scenario was added for NUL.
  - `main` is clean. Reviewer worktrees and branches are removed; `fix/346-352-nul-and-archive-500s` is left on origin as usual.
  - **Carried from 29/10, not reverified:** #344 (image pins, low priority, before or with the next release): five images including uv, Postgres in Compose, CI and release-candidate, bump mechanism undecided. testhost is in the tunnel configuration from the 0.6.0 gate; don't recreate its Keycloak container. Owner: allow `pkg-containers.githubusercontent.com` in cloud Network access, delete the Claude.ai Testing connector, complete #278's skill-zip check. Known gaps: #238, #324 (local e2e uses `--workers=1`), #320. plamotrack-ios can re-sync #342's scenarios once its #15 adds `update_order` and `delete_order`.
- **Next:** the owner's pick.
  - **#348** (order notes, a problem the owner actually hit; `RequestModel` and `parse_text` now cover a new text field), then #350 and #349, which have open product questions for the owner (does `get_summary` spend use paid or shelf price).
  - **The next release:** #351, #344.
  - **M6.7:** #279's edge probes, then #281, #282. **M7** waits on #28.

## 2026-10-29 — Codex (GPT-6) — documentation drift filed as #351 for the next release cycle

- **Done:**
  - Created [#351](https://github.com/DeusMaximus/plamotrack/issues/351), labelled
    `documentation`, at the owner's request. Ten checklist items cover token
    permissions and OAuth wording, phone import, archive compatibility, source
    setup, Node requirements, implemented auth still marked planned, release
    status, the retired Kanban dependency, and the generic frontend README.
  - Findings link to `9908d5f`; the published baseline checked was v0.6.0-alpha.
    Configuration-only Compose check reproduced the missing-password failure;
    a compatibility-function probe confirmed export-format versus app-version
    behaviour. No service was started or collection data changed.
  - Added #351 as explicitly pending work in `.agents/next-release.md`.
    Documentation corrections are not implemented by this bookkeeping change.
  - Rotated the oldest hand-off entry into `.agents/handoff/2026-10.md` verbatim.
- **Decisions (owner):** include the smaller documentation items and complete the
  cleanup in the next release cycle. No existing milestone names that release;
  the issue and release checklist carry the scheduling intent.
- **State:**
  - Issue #351 is published. Local ledger and hand-off changes are uncommitted
    on `main`; no commit or push was requested.
  - Unreleased implementation remains #333 and #341/#343; #342 was tests only.
    The release ledger retains those entries separately from the pending task.
  - Carried from 18/10, not reverified here: #346 (NUL text reaches Postgres)
    and #344 (dependency/image pins, low priority before or with next release).
    #344 needs five images including uv, and the Postgres pin in Compose, CI,
    and release-candidate; the bump mechanism remains undecided.
  - Carried operational notes: owner's LXC on 0.5.2; refresh the Gunpla skill at
    upgrade (#289). testhost remains in the tunnel configuration from the 0.6.0
    gate; do not recreate its Keycloak container. Owner follow-ups: allow
    `pkg-containers.githubusercontent.com` in cloud Network access, delete the
    Claude.ai Testing connector, and complete #278's skill-zip check.
  - Known gaps: #238, #324 (local e2e uses `--workers=1`), #320.
- **Next:** implement #351 in the next release cycle, with the docs-site claim
  check it lists. Other sequencing remains #279's edge probes, then #281's
  packaging and #282's VPS path; M7 waits on #28. plamotrack-ios can re-sync
  #342's scenarios once its #15 adds `update_order` and `delete_order`.
