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

## 2026-10-18 — Claude Code (Opus 5.5) — #342 MERGED as `e536064` (PR #345); #341 + #343 MERGED as `8a8c31c` (PR #347); #346 filed; #344 answered

- **Done:**
  - **[PR #345](https://github.com/DeusMaximus/plamotrack/pull/345)** (#342): four shared scenarios in `scenarios/imports.json`. Each imports a received order (a consumable line of 2) with its catalog sheet into an empty collection, then edits it up or down, deletes it, or deletes it below its line (refused `stock.insufficient` `{name, on_hand: 1, requested: 2}`). Two mutants in `orders.py` each kill exactly their pair. Reviews clean: Codex 👍, Greptile 5/5.
  - **[PR #347](https://github.com/DeusMaximus/plamotrack/pull/347)** (#341, #343), all in `services/portability/importing.py`:
    - Zip: `_ExpansionBudget.read` catches `ValueError` (a negative seek, or a per-file name flagged UTF-8 that isn't). `ZipFile()` catches `ValueError` and `NotImplementedError` beside `BadZipFile`.
    - CSV: `csv.field_size_limit` raised to the import's own size limits, so a long `build_notes` from our own export imports again. `StringIO(newline="")`, which also fixes CR-only line endings (found by the probe). The new code `import.csv_unreadable` `{source, line}` is registered in all three code files. `line` is the inner reader's, because `DictReader.line_num` lags one line on a failed row.
    - Tests: 18 in `test_portability.py`, two of them byte-flip sweeps (archive, CSV) through `read_upload`. On the unfixed code the archive sweep finds 13 escapes. Mutants `341-1`…`341-8` are in `mutation_test.py`. Backend 3134 passed. Reviews: Codex no findings, Greptile 5/5, CodeRabbit skips (fewer than 10 stars).
  - **#346 filed:** a NUL character in any text value is a 500, from `POST /retailers` and from import apply. The preview plans the row as a create. Postgres refuses U+0000 in `text`, and no writer checks first. It crosses all three writers, so it was left out of #347.
  - **#344 answered** ([comment](https://github.com/DeusMaximus/plamotrack/issues/344#issuecomment-6247492937)): plamotrack-ios should start its compat servers from the tag's release bundle (digest-pinned images plus `SHA256SUMS`) instead of building the source. Pins here help only tags cut after them.
- **Decisions (owner, 18/10):**
  - **A manifest that can't be unpacked refuses the import.** One that unpacks but isn't readable JSON is still the warning. Recorded on [#341](https://github.com/DeusMaximus/plamotrack/issues/341#issuecomment-6247038717) for plamotrack-ios.
  - **#344 is low priority**, before or with the next release. The owner is taking the plamotrack-ios side.
- **State:**
  - **Unreleased on `main`:** #333 and #341/#343 (`.agents/next-release.md`). #342 is tests only. README and docs site: nothing.
  - `main` is clean. Merged branches are left on origin: `test/342-imported-order-stock-scenarios`, `fix/341-343-upload-500s`.
  - **#344 when it's picked up:**
    - Five images, not four: `backend/Dockerfile:8` copies `ghcr.io/astral-sh/uv:0.5`.
    - Postgres is in three places: the compose default, the `ci.yml` service, and `release-candidate.yml:57`. Line 57 re-resolves `postgres:16` on release day, so it must read the pin instead.
    - The bump mechanism isn't chosen. Dependabot's handling of `COPY --from`, `${VAR:-image}` and workflow service images is unverified. The comment suggests a script plus a weekly check plus a runbook step.
  - **Carried from 13/10:**
    - The owner's LXC is on 0.5.2; refresh the Gunpla skill at upgrade (#289 changed `create_order`).
    - testhost is in the tunnel configuration from the 0.6.0 gate (`.env.before-claude-check`); don't recreate its Keycloak container.
    - Owner: allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access, and delete Claude.ai's "Testing" connector. #278 is open for the skill-zip check.
    - Known gaps: #238, #324 (local e2e needs `--workers=1`), #320.
- **Next:** the owner's pick.
  - #346 (one predicate shared by the schemas and `parse_text`; refuse, don't strip), or #344.
  - **M6.7:** #279's edge probes, then #281's packaging; #282's VPS path. **M7** waits on #28.

  Can wait: #320, #324, #167, #162, #223–#227, #123–#125, #110, #116, #134, #137, #238, #249, #230, #179.
- **Also next:** plamotrack-ios can re-sync the scenarios (#342's four). Its runner picks them up once plamotrack-ios#15 adds `update_order` and `delete_order`.

## 2026-10-13 — Claude Code (Opus 5.5) — #333 MERGED as `a25b57f` (PR #340): a failed sign-out says so, and the page keeps working

- **Done:**
  - **[PR #340](https://github.com/DeusMaximus/plamotrack/pull/340)** squash-merged as **`a25b57f`**, pinned to head `0f39652` after all three checks. #333 is closed.
    - **The defect:** `useSignOut` cleared the CSRF token whatever the logout answered. `AuthGate` sets it only when it *changes*, so after a refused logout every write was 403 until a reload. The rejection escaped `onClick` unhandled, and nothing was said.
    - **`lib/signOut.ts`:** one attempt for the tab, a module store read through `useSyncExternalStore` (the `importRun.ts` shape). It never clears the token up front. It re-reads the session and decides from that:
      - still `owner` → keep the token; if the logout didn't answer, record **refused** against the session the press was made in (`csrfTokenInUse()` at the press);
      - neither the logout nor the re-read answered → **unconfirmed** ("Couldn't confirm the sign-out…"); a second press settles it;
      - otherwise signed out, as before.
      A failure is shown only in the session it was recorded in. The hook returns `{ signOut, pending, message, dismiss }` and never rejects.
    - **Said beside the control (owner's call, 12/10):** an `ErrorBanner` under Sign out in the sidebar and under More's panel (`reveal`), and in the rail a `fixed` bubble 8 px clear of the rail's edge. It goes on the next press, a pointerdown or click elsewhere, or Escape. All three controls are `aria-disabled` while waiting (#268's rule), and a second press, in any control, sends nothing.
    - e2e in `shell.spec.ts`, "Sign out, from this shell": 6 new tests across `app`/`phone`/`tablet`. Each review finding's test was red before its fix. Mutants: about 20 over three rounds, all killed or removed as duplicates; one survivor ("decide from the logout's answer alone") is equivalent in effect.
    - Design §13.7 bullet; `.agents/next-release.md` entry (the only one).
  - **Review:** CodeRabbit had no findings. Greptile raised two P2s (per-control guard; More's banner under the tab bar), answered in `0a1a6f4`. Codex had none on `067a228`, then three P2s on `0a1a6f4` (failure keyed to the re-read's session; "still signed in" when nothing answered; the bubble ignored the keyboard), answered in `0f39652`. The owner merged without a further round.
  - `.agents/testing-and-review.md`: three e2e traps from this work (forced click on an `aria-disabled` control, WebKit's Tab skipping buttons, React Query's `visibilitychange` on `window`).
- **Decisions (owner):** the rail's failure is a bubble beside the icon (12/10); merge at `0f39652` without a further Codex round (13/10).
- **State:**
  - **Unreleased on `main`:** #333 only (`.agents/next-release.md`). README and docs site: nothing.
  - `main` is clean. No worktrees, servers or e2e databases are left. Merged branches on origin include `fix/333-failed-sign-out` and the ones listed on 07/10.
  - **The owner's LXC is on 0.5.2.** Upgrading to 0.6.0 is the owner's; refresh the Gunpla skill then (#289 changed `create_order`). The release's `plamotrack-gunpla.zip` is current.
  - **testhost** is in the tunnel configuration from the 0.6.0 gate (`.env.before-claude-check` holds the gate's end state); the next gate run resets it. Don't recreate its Keycloak container: a new one changes `sub`.
  - **Carried, owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete Claude.ai's "Testing" connector (still linked to `plamotest.gunp.la`). #278 is open for the skill-zip check.
  - **Known gaps, filed:** #238, #324 (local e2e needs `--workers=1`), #320.
- **Next:** the owner's pick.
  - **M6.7**: #279's edge probes, then #281's packaging; #282's VPS path.
  - **M7** waits on #28.

  Can wait: #320, #324, #167, #162, #223–#227, #123–#125, #110, #116, #134, #137, #238, #249, #230, #179.
- **Also next:** **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`; cloud candidates #124, #125, #238, #110, #116, #134 and #137; posting the rehearsal on #285.

