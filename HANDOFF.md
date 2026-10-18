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
