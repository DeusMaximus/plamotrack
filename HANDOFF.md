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

## 2026-10-07 — Claude Code (Opus 5.5) — v0.6.0-alpha RELEASED (tag at `6dfc008`, prerelease); docs site and README updated

- **Done:**
  - **[v0.6.0-alpha](https://github.com/DeusMaximus/plamotrack/releases/tag/v0.6.0-alpha)** was published 2026-10-07 07:33 UTC as a prerelease, on the owner's approval at each step. It ships everything the ledger held, from #294 to #326.
    - **Bump:** PR #338 → `6dfc008` (0.5.2 → 0.6.0 in the app, `pyproject.toml` and `uv.lock`).
    - **Candidate:** [run 37581036003](https://github.com/DeusMaximus/plamotrack/actions/runs/37581036003), attempt 1, green, with Integration on native amd64 and arm64.
    - **Annotated tag** `v0.6.0-alpha` at `6dfc008`.
    - **Promote:** [run 37585808722](https://github.com/DeusMaximus/plamotrack/actions/runs/37585808722) → draft → published.
    - **Checked by hand:** the published files downloaded anonymously pass `sha256sum -c` and are byte-identical to the gated bundle. Both version tags resolve anonymously to the gated digests. PostgreSQL is pinned at 16.15.
  - **The first update from a release's files**, v0.5.2 → the candidate on testhost: green. Scripted by hand, since the driver has no phase for it. The state was a claimed owner, a retailer, two kits, an order and a PAT, plus a −3 low-stock threshold stored through 0.5.2's importer.
    - After the update, `migrate` logged `cleared 1 negative value(s)`.
    - The version, the 0.5.2 session, the token, the data and the volume all held, and MCP via the token listed 31 tools.
    - The script and notes are in `.dev/release-0.6.0/` (gitignored). The procedure is in `.agents/releases.md`, step 5.
  - **The deployment gate on the release files, every phase plus the tunnel:** green.
    - Matrix: local 180, OIDC 183, tunnel 87 rows, 0 failing.
    - T13: the link and all three restores.
    - `/mcp` held 130 s through Cloudflare.
  - **Real-client run (owner, 2026-10-07):** Claude.ai linked through `plamotest.gunp.la` and recorded an order through `create_order`. Confirmed server-side by the `auth.mcp_grant_issued` audit row and the order.
  - **Docs site:** [plamotrack-docs#9](https://github.com/DeusMaximus/plamotrack-docs/pull/9) merged as `11561d3` (the changelog, install version, phone import, sorts, MCP reference, retaken screenshots, and a **new Pocket ID page**). Review fixes: Codex's Caddy HTTP-challenge P2, plus Greptile's four style-guide P2s.
  - **README:** [PR #339](https://github.com/DeusMaximus/plamotrack/pull/339) merged as `36dfed4`. Codex caught the phone row still saying export-only; the same sweep fixed Milestone 6.7's row (Pocket ID supported, images published).
  - **This commit:** `.agents/next-release.md` is emptied (all 15 entries shipped). `.agents/releases.md` records the update step's first run, and adds to step 7 that the README's own claims are read against the release, not only the ledger's lines.
- **Decisions (owner, 07/10):** run the real-client check on Claude.ai; publish.
- **State:**
  - **Nothing is unreleased on `main`.**
  - **testhost** is left in the **tunnel** configuration (`WEB_BIND` on the LAN, `PUBLIC_BASE_URL=https://plamotest.gunp.la`, OIDC with the gate's Keycloak). The gate's end state is saved on the host as `.env.before-claude-check`. The next gate run resets the host anyway. Claude.ai's test connector to `plamotest.gunp.la` is still linked on the owner's account.
  - **The owner's LXC is on 0.5.2.** Upgrading it to 0.6.0 is the owner's; the Updating page covers it. **Gunpla skill refresh** at that upgrade, because `create_order` changed (#289). The release's `plamotrack-gunpla.zip` is current.
  - **Known gaps, filed:** #333 (failed sign-out), #238, #324 (local runs need `--workers=1`), #320.
  - **Tooling:**
    - `main` is clean.
    - The local `.dev/release-bundle`, `.dev/release-draft` and `.dev/gate-stage` directories can go.
    - Merged branches left on origin: `release/v0.6.0-alpha`, `docs/readme-v0.6.0-alpha`, `fix/326-…`, `fix/268-…`, `fix/331-…`, `fix/316-…`, and older ones. In the docs repo: `release/v0.6.0-alpha`.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost:** don't recreate its Keycloak container; a new one changes `sub`.
    - #278 is open for the owner's skill-zip check.
- **Next:** the owner's pick. Candidates:
  - **#333** (failed sign-out; small, `signOut.ts` and `AuthGate.tsx`);
  - **M6.7**: #279's edge probes, then #281's packaging; #282's VPS path;
  - **M7** waits on #28.

  Can wait: #320, #324, #167, #162, #223–#227, #123–#125, #110, #116, #134, #137, #238, #249, #230, #179.
- **Also next:** **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`; cloud candidates #124, #125, #238, #110, #116, #134 and #137; posting the rehearsal on #285.

## 2026-10-07 — Claude Code (Opus 5.5) — #326 MERGED as `8862a79` (PR #337): Home's strip rows stack under the name; the pre-release plan is done

- **Done:**
  - **[PR #337](https://github.com/DeusMaximus/plamotrack/pull/337)** squash-merged as **`8862a79`**. #326 is closed.
    - **Owner's call (07/10):** a strip row stacks under its name, the narrow Recently completed strip's shape, by need at every width.
    - `KitStrip` (`pages/HomePage.tsx`): every row is a grid with the pencil in its own column, beside both lines. The name and the meta share the other column: one line where they fit (an ordinary row is as it was), the meta under the name where they don't. `stacked` is now only the decree under 26rem (`basis-full`); the `display: contents` grid is gone.
    - Home is measured as a table is: one `TableRuler` over the page. The grade, scale, kit number and a mail card's date line go through `Measured`. A bench card's name is a heading with `break-words`.
    - e2e in `pages.spec.ts` seeds the issue's 92-character value in every field. It covers 320–1440 px in the three projects, plus 32 and 40 px browser fonts on a 320 px phone. The existing phone Home test's row locator is now `../..`.
    - Mutants: 8, all killed.
  - **Review:**
    - Codex and CodeRabbit: no findings.
    - Greptile: one P2 (the bench name's `Measured` floor ran under its edit control at a 32 px font). Reproduced, then fixed in `2cf4710`.
  - Design §13.7 has an amendment under #323's "Not in this change: Home"; `.agents/next-release.md` has an entry.
- **Decisions (owner, 07/10):** the bots alone reviewed #337, with no briefed round. **Release prep starts now.**
- **State:**
  - **The pre-release plan (owner, 06/10) is complete:** #316, #331, #268 and #326 are merged.
  - **Unreleased on `main`:** 17 ledger entries in `.agents/next-release.md`, from #294 through #326. Among them are a migration (#313) and a changed MCP tool (#289: `create_order` takes the shop's id).
  - **CI Integration:** 26:36 on #337, with the cap at 40 since #336.
  - **Known gaps, filed:**
    - #333 (owner: after the release);
    - #324 (local runs need `--workers=1`);
    - #320.
  - **Tooling:**
    - `main` is clean; no worktrees, servers or e2e databases are left.
    - Merged branches left on origin: `fix/326-home-strips-stack`, `fix/268-stepper-keeps-focus`, `fix/331-token-dates-subscribe`, `fix/316-errors-beside-their-controls`, and older ones.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next — the release**, likely **v0.6.0-alpha**:
  - Work through `.agents/releases.md` and `.agents/next-release.md`.
  - Owed:
    - #315's paragraph for the docs site's `using/import-export.mdx`;
    - #309's upgrade-notes line (drafted in the ledger);
    - the owner's Gunpla skill refresh at the LXC upgrade, because of #289.
  - After the release: #333.

  Can wait: #320, #324, #167, #162, #223–#227, #123–#125, #110, #116, #134, #137, #238, #249, #230, #179.
- **Also next:**
  1. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`.
  2. Carried: #279's edge probes, then #281's packaging; #282's VPS path; cloud candidates #124, #125, #238, #110, #116, #134 and #137; posting the rehearsal on #285.

## 2026-10-07 — Claude Code (Opus 5.5) — #268 MERGED as `fa68abc` (PR #336): a pressed control keeps the keyboard, or hands it on; CI Integration cap 25 → 40 min

- **Done:**
  - **[PR #336](https://github.com/DeusMaximus/plamotrack/pull/336)** squash-merged as **`fa68abc`**, pinned to head `b14aa8a` after all three checks. #268 is closed.
    - **Owner's call (07/10):** fix the class (a control disabling itself under the keyboard), not only the stepper.
    - **A control waiting on its own request keeps the keyboard.** `Button`'s new `pending` prop sets `aria-disabled` and refuses a press, form submission included (#55). It covers the steppers (both shapes), Export CSV, both Settings Saves, Create token, Revoke, and `AuthGate`'s four buttons.
    - **A control that can't act any more** (disabled, or removed) hands the keyboard to the stand-in it names, through one `MutationObserver` (`stranded`) in `useFocusAcrossShells`:
      - − at zero → +
      - a saved Save → the field before it (**owner's call, 07/10**)
      - a revoked token's Revoke → the next token's, then the previous, then the name field
      - Create → Copy; Done → the name field; Enter in the name field → Copy
    - The observer re-reads the focused control's keys on every mutation. It answers a loss once; a removed control nothing could answer is forgotten two frames later.
    - `focusByKey` skips a disabled carrier. WebKit leaves `activeElement` on a just-disabled control, and in the first version + was never reached.
    - Not changed: Data management's import (it has its own handling) and dialogs (`Modal`).
  - **CI:** Integration's `timeout-minutes` went from 25 to 40 (**owner's call**). The last two runs took 22:57 and 26:25.
  - **Docs:** design §13.7 has a bullet ("A control that changes its own state…"); `AGENTS.md`'s focus line is updated.
  - **Tests:**
    - `e2e/keyboard-place.spec.ts` (new) runs in app, phone and tablet: 9 tests.
    - `settings.spec.ts` has the Save test; `auth.spec.ts` checks that a refused password keeps the keyboard on Sign in.
    - Mutants: 22 killed (17 in the first pass, 5 in the review round). 3 survived (K3, K5, R6), and the code they mutated was removed. The tables are in the PR body.
  - **Review:**
    - Round 1 (Codex and Greptile): five P2s, all fixed in `b14aa8a`.
    - Round 2: a focused `@codex review`, which came back clean.
- **State:**
  - **Unreleased on `main`:** #294, #289, #247, #302, #310, #313 (a migration), #314, #319, #322, #328, #330, #332, #334, #335, and now **#336**. See `.agents/next-release.md`.
  - **Runs at `b14aa8a`:** focus suites in three projects, Chromium: 187 passed, 0 failed. keyboard-place under WebKit: 26 passed, 1 skipped. Earlier, at the pre-review head, the full Chromium suite: 244 passed, 0 failed.
  - **Known gaps, filed:** #333, #326, #324 (local runs need `--workers=1`), #320.
  - **Tooling:**
    - `main` is clean; no worktrees, servers or e2e databases are left.
    - Merged branches left on origin: `fix/268-stepper-keeps-focus`, `fix/331-token-dates-subscribe`, `fix/316-errors-beside-their-controls`, and the ones listed in older entries.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next — the pre-release plan (owner, 06/10), continued:**
  1. **#326** (Home scrolls sideways): the owner's call on a strip's grade and scale is still open (wrap, truncate, or stack under the name; recommended: stack). Expect a briefed Codex round.

  **Then the release**, likely **v0.6.0-alpha**: a migration (#313), a changed MCP tool (#289: `create_order` takes the shop's id) and two new phone features. Work through `.agents/releases.md` and `.agents/next-release.md`.
  - The owner's Gunpla skill needs a refresh at the LXC upgrade, because of #289. #309's upgrade-notes line is drafted in the ledger.
  - #333 can wait for after the release.

  Can wait: #320, #324, #167, #162, #223–#227, #123–#125, #110, #116, #134, #137, #238, #249, #230, #179.
- **Also next:**
  1. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`.
  2. Carried: #279's edge probes, then #281's packaging; #282's VPS path; cloud candidates #124, #125, #238, #110, #116, #134 and #137; posting the rehearsal on #285.

## 2026-10-07 — Claude Code (Opus 5.5) — #316 MERGED as `6d0252d` (PR #334), #331 MERGED as `30bb0c0` (PR #335); #268 in progress

- **Done:**
  - **#316, [PR #334](https://github.com/DeusMaximus/plamotrack/pull/334)**, squash-merged as **`6d0252d`**. The session that merged it left no entry, so this restates it.
    - A failure in Settings is said beside the control that failed. A download's failure is shown in its own card, and a form's error appears above its Save or Create. A refused Revoke is scrolled into view at the list's head; a failed list load is not (`ErrorBanner`'s `reveal`).
    - The bots' round (Codex, Greptile, CodeRabbit) is answered in the PR.
  - **#331, [PR #335](https://github.com/DeusMaximus/plamotrack/pull/335)**, squash-merged as **`30bb0c0`**. #331 is closed.
    - `AccessTokensSection` and `DataSection` call `usePresentationVersion()` at their root. A Settings section is behind an `<Outlet>`, so a re-render above it can't reach it.
    - The sweep found Data management's file size and import counts were stale too. Its table is in the PR body.
    - e2e in `settings.spec.ts`, in `ar-EG` with full dates: both response orders for Access tokens, and a late settings row under a chosen file's size. Four mutants, all killed; Chromium and WebKit.
    - Review: Codex 👍 and Greptile 5/5, with no findings. CodeRabbit was rate-limited.
- **State:**
  - **CI Integration is at its 25-minute cap** (`ci.yml`, `timeout-minutes: 25`). #335's first attempt was cancelled at 25:05; the rerun passed in 24:12. It was 16 min on 06/10. The owner reran it by hand. **Next PR to `main` may need the cap raised**; that call is the owner's.
  - **Unreleased on `main`:** #294, #289, #247, #302, #310, #313 (a migration), #314, #319, #322, #328, #330, #332, and now **#334** and **#335**. See `.agents/next-release.md`.
  - **#268 is in progress** on `fix/268-stepper-keeps-focus`, uncommitted on the primary Mac:
    - **Owner's call (07/10):** fix the class (a control disabling itself under the keyboard), not only the stepper.
    - A waiting control keeps the keyboard: `Button`'s new `pending` prop sets `aria-disabled` and refuses a press.
    - A control that can't act any more hands the keyboard to the stand-in it names, through one `MutationObserver` in `useFocusAcrossShells`.
    - **Owner's call (07/10):** a saved Save gives the keyboard to the field before it.
    - New `e2e/keyboard-place.spec.ts` runs in app, phone and tablet.
    - On mutants: 18 killed, and two survivors whose code was removed.
    - A full Chromium run was in flight when this was written.
  - **Known gaps, filed:** #333, #326, #324 (local runs need `--workers=1`), #320.
  - **Tooling:**
    - Merged branches left on origin: `fix/331-token-dates-subscribe`, `fix/316-errors-beside-their-controls`, and the ones listed in the entry below.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next — the pre-release plan (owner, 06/10), continued:**
  1. **#268**: finish, open the PR, and let the bots review it.
  2. **#326** (Home scrolls sideways): the owner's call on a strip's grade and scale is still open (wrap, truncate, or stack under the name; recommended: stack). Expect a briefed Codex round.

  **Then the release**, likely **v0.6.0-alpha**: a migration (#313), a changed MCP tool (#289: `create_order` takes the shop's id) and two new phone features. Work through `.agents/releases.md` and `.agents/next-release.md`.
  - The owner's Gunpla skill needs a refresh at the LXC upgrade, because of #289. #309's upgrade-notes line is drafted in the ledger.
  - #333 can wait for after the release.

  Can wait: #320, #324, #167, #162, #223–#227, #123–#125, #110, #116, #134, #137, #238, #249, #230, #179.
- **Also next:**
  1. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`.
  2. Carried: #279's edge probes, then #281's packaging; #282's VPS path; cloud candidates #124, #125, #238, #110, #116, #134 and #137; posting the rehearsal on #285.

## 2026-10-07 — Claude Code (Opus 5.5) — #315 MERGED as `48c37b9` (PR #332): an import sent outlives leaving Data management; #333 filed

- **Done:**
  - **[PR #332](https://github.com/DeusMaximus/plamotrack/pull/332)** squash-merged as **`48c37b9`**, pinned to `c303e38` after all three checks. #315 is closed.
    - **Owner's call (06/10):** hold the sent import above the routes, not block navigation (`<BrowserRouter>` has no `useBlocker`).
    - `frontend/src/lib/importRun.ts` (new) is a module store, one import per tab. It holds the request, its outcome, a `beforeunload` hold while in flight, and the owner session the import was sent under (its CSRF token, one per session).
    - A section mounted under a running import says so and holds the picker. The outcome is shown once, then acknowledged two animation frames after it is drawn.
    - `DataSection.tsx` holds **one** `outcome` state, drawn and acknowledged as the same thing. A preview's refusal is a draft state of its own. The phone's fall-back clears only the draft. An accepted send replaces the last outcome.
    - `AuthGate.tsx` calls `keepImportRunFor(...)` on every session read: the import goes on any read that is not its own session (signed out, expired, another owner session in another tab). `useSignOut` forgets it on a confirmed 204. A forgotten import is told to the section, so its card lets go.
  - **Review:** Codex rounds 1–3 were each GO with P3s, all fixed in the PR. Codex's GitHub bot raised one P1 ("told is not shown"), also fixed.
    - Withdrawn claims: M3 and M17 "equivalent", and "M2 can't be seen in the browser".
    - Lesson: `.agents/lessons.md` → "Equivalent until someone finds the ordering".
  - **Filed [#333](https://github.com/DeusMaximus/plamotrack/issues/333):** a failed sign-out clears the CSRF token and `AuthGate` never restores it (the re-read token is the same), and nothing says it failed. It predates #315.
- **Decisions (owner, 06–07/10):** fix round 2's structural finding in the PR, not as a follow-up; merge after round 3 without a round 4, once a production-build check passed (15/15).
- **State:**
  - **Unreleased on `main`:** #294, #289, #247, #302, #310, #313 (a migration), #314, #319, #322, #328, #330, and now **#332**. See `.agents/next-release.md`. #315's entry owes the docs site's `using/import-export.mdx` a paragraph.
  - **Tests:**
    - `importRun.test.ts` has 22 unit tests.
    - `pages.spec.ts` has the #315 e2e: leave and come back by Back and by links, a stubbed-frames step, the phone-turn answer, the mount-to-listener answer, the retry in three modes, two cross-tab session orderings, and a late sign-in. Several are Codex's reproductions; some open their own browser context with a real sign-in.
    - 19 mutants, all killed; the table is in PR #332's body.
  - **Runs at `c303e38`:** Chromium suite 207 passed / 89 skipped / 0 failed; WebKit and the production build, the import tests 15/15.
  - **Known gaps, filed:** #333, #331, #326, #324 (local runs need `--workers=1`), #320, #316.
  - **Tooling:**
    - `main` is clean; no worktrees, servers or e2e databases are left.
    - Merged branches left on origin: `fix/315-import-outlives-section`, `fix/329-fold-to-fit`, `fix/323-unbroken-names`, `fix/321-focus-row-page`, `fix/317-narrow-list-lookups`, `feat/318-page-size`.
    - Briefs, responses and Codex's harnesses are in `.dev/315/`.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next — the pre-release plan (owner, 06/10), continued.** Each is its own PR, in this order:
  1. **#316** (same file, `DataSection.tsx`): on a phone, a failed download's error shows a screen away from its button. Mind the new state shape: `error` (downloads), `refusal` (previews) and `outcome` (the sent import) are separate.
  2. **#331**: subscribe `TokenList` to the presentation version, test both response orders, and sweep the other formatters (rule 11).
  3. **#268**: the Inventory stock stepper drops focus to `<body>` on every press. Give the keyboard back to the record's control.
  4. **#326** (Home scrolls sideways): the owner's call is still open on a strip's grade and scale (wrap, truncate, or stack under the name; recommended: stack). Expect a briefed Codex round.

  #316, #331 and #268 are small enough for the bots' automatic reviews alone. **Then the release**, likely **v0.6.0-alpha**: a migration (#313), a changed MCP tool (#289: `create_order` takes the shop's id) and two new phone features. Work through `.agents/releases.md` and `.agents/next-release.md`.
  - The owner's Gunpla skill needs a refresh at the LXC upgrade, because of #289. #309's upgrade-notes line is drafted in the ledger.
  - #333 can wait for after the release, or go in with #316 if it's convenient (`signOut.ts`, `AuthGate.tsx`).

  Can wait: #320, #324, #167, #162, #223–#227, #123–#125, #110, #116, #134, #137, #238, #249, #230, #179.
- **Also next:**
  1. **plamotrack-ios** can copy `backend/tests/fixtures/scenarios/` and the golden archive from `main`.
  2. Carried: #279's edge probes, then #281's packaging; #282's VPS path; cloud candidates #124, #125, #238, #110, #116, #134 and #137; posting the rehearsal on #285.
