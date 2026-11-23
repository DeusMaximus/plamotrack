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

## 2026-11-23 — Claude Code (Opus 5.5) — orchestrator: the pre-release hardening wave MERGED (#380, #238, #351, #376, #394, #344); version bump PR #403 open; v0.7.0-alpha next

- **Done:**
  - **The owner's plan (2026-11-23):** a short hardening wave, then v0.7.0-alpha, then per-kit and per-order pages (like plamotrack-ios's `KitDetailView` / `OrderDetailView`) before M7. The record-page design is done in a **Claude Code desktop** session, not T3 Code. The order-dialog cluster (#369, #382–#385, #392, #400) waits until after the release, so it can be shaped by the record pages.
  - **Merged, each at its reviewed head with the owner's sign-off** (the per-issue entries below and in the archive hold the detail): #380 → `706234c` (PR #386), #238 → `5d597d1` (PR #387), #351 → `e92b1e2` (PR #393), #376 → `d293691` (PR #397), #394 → `dbf4e7e` (PR #401), #344 → `378436c` (PR #398). Every briefed round (Sol 6.1 high) was GO at round 1.
  - **Filed:** #388–#392 (from #386/#387), #394–#396 (from #393; #394 then fixed), #399–#400 (from #397), #402 (from #398, the pin inventory fails open; started on branch `344-inventory-fail-closed` at `fc0e6d5`, no PR).
  - **On `main` by the orchestrator:** #380's release note discloses #388; `AGENTS.md` → Release artifacts says which pin forms the test enforces (#402).
  - **Release, step 1:** `python3 backend/base_image_pins.py` green (all 9 pins current, 2026-11-23). [PR #403](https://github.com/DeusMaximus/plamotrack/pull/403), branch `version-0.7.0`, head `8eb76f2`: 0.6.0 → 0.7.0 in `app/__init__.py`, `pyproject.toml`, `uv.lock`; 416 release-related tests passed. Its body lists what ships against `git log v0.6.0-alpha..main`.
- **Decisions (the owner's, 2026-11-23):** #376's notes are multi-line; #238 keeps the form closed until all inputs load, with Retry; #344 ships with a pin-check script, not Dependabot; #398 merged as is with its gap in #402; #394 joined the wave.
- **State:**
  - **Release candidate passed:** PR #403 merged as **`9189910`** (main at 0.7.0); **Release candidate** dispatched on it for `v0.7.0-alpha` with the owner's approval, [run 45120172234](https://github.com/DeusMaximus/plamotrack/actions/runs/45120172234), attempt 1, **success** (build; Backend; Frontend; Integration on native amd64 and arm64), 2026-11-23 05:49–06:25 UTC. Its `release-bundle` artifact expires 30 days after the run: promote before then, or gate a new candidate. Next is step 5 (the gate on its files).
  - **Nothing else in flight.** No worker or reviewer running; both lanes free. Every worker worktree, scratch worktree and lane database of this session is gone. Branches of the merged PRs remain on the remote. Sol's T3 reviewer worktrees are T3's to remove.
  - **Event subscriptions are off for this GitHub account** (`gh event listen` answers 403): a delegated worker hands back at PR open, and the orchestrator, watching the PR through T3 Code, sends it the reviews.
  - **The dev Postgres container (`plamotrack-db-1`) is stopped and another project holds 127.0.0.1:5432**; workers and reviewers ran throwaway containers on other ports. Its named volume `plamotrack_db-data` is intact.
  - `backend/mutation_test.py` has 836 cases (#380 added twelve).
  - The owner's LXC is on v0.6.0-alpha (checked read-only 2026-11-23: no kit with a blank name or grade). PR #184 (Japanese, draft) waits on a native reviewer.
  - **Owed to plamotrack-ios:** #348–#350's fields, codes and scenarios; #356's comparison rule; #380's `field.blank` on a kit's name and grade.
- **Waiting on the owner:**
  - **The release, each step its own approval** (`.agents/releases.md`): merge PR #403; dispatch **Release candidate** on the merge commit with `v0.7.0-alpha` (the first candidate from the #344 pins, without `--db`); the deployment gate on the candidate's files on the test host, **including the update from v0.6.0-alpha's files** (three migrations); tag and promote; the draft's notes from `.agents/next-release.md` (add the PostgreSQL digest move, `65b16a8b…` → `3950ad7c…`, and the observed gate results); publish; then the README and the docs site (the `#351` lines, #394's `tokens.png`, install versions).
  - One manual dispatch of the **Base image pins** workflow (never run on GitHub).
  - #395 (the GitHub About text).
  - Triage for #369–#371, #374, #375, #379, #381–#385, #388–#392, #396, #399, #400, #402 (#402 already has its readiness parts).
- **Next:** the release, from step 2. Then the record-page design in Claude Code desktop. Proposed from #398, not filed: `nginx:1.27-alpine` and `uv:0.5` are frozen lines the check can't flag; Python bookworm → trixie.

## 2026-11-23 — Claude Code (Opus 5.5) — #344 worker, lane 1: PR #398 open, CI and reviews pending
- **Done:** branch `344-pin-base-images`, [PR #398](https://github.com/DeusMaximus/plamotrack/pull/398) against `main` at `936cf0f`, head `b6fe4b4`, closes #344. Six base images pinned `tag@sha256:<index>` (both Dockerfiles' `# syntax=`, python ×2, uv, node, nginx; postgres in compose + ci.yml), resolved 2026-11-23 02:41 UTC. New `backend/base_image_pins.py` (stdlib; check / `--update` / `--offline`; `--update` verifies the index's hash and amd64+arm64) and weekly `.github/workflows/base-images.yml` (not required). `release_artifacts.py bundle` reads the PostgreSQL pin from compose and refuses any other; `--db` removed; `release-candidate.yml` no longer resolves `postgres:16`. Docs: `.agents/releases.md` step 1, `AGENTS.md` Release artifacts, design §8.
  - **Merged:** squash-merged as **`378436c`** at the reviewed head `b6fe4b4`, with the owner's sign-off; #344 is closed. Reviews: Codex connector at `b6fe4b4`, no findings; Greptile 4/5, one finding (`inventory()` skips a workflow `image: ${{ … }}` expression); briefed round 1 (Codex GPT-6.1 Sol, `b6fe4b4`) **GO** with one P3, the same fail-open class wider (a continued Dockerfile `FROM`, `docker-compose.dev.yml` not scanned, a scalar workflow `container:`). The owner's call: merge as is and take both in one follow-up, **#402**, started on branch `344-inventory-fail-closed` (`fc0e6d5`, no PR; covers the scalar `container:` and the expression). Both answered on the PR; the PR body brought up to the round (suite 4,205 passed / 1 xfailed, Sol's coverage: registry failure modes, native arm64 packaged stack and ingress matrix, v0.6.0-alpha's bundle passing `verify`). After the merge, `AGENTS.md`'s claim that every new unpinned reference fails the test narrowed on `main` to the forms enforced, pointing at #402.
- **Decisions:** `# syntax=` pinned too (sixth image). Script in `backend/` beside the other stdlib release tools. Runbook step folded into step 1 so numbering holds. No next-release entry.
- **State:** `tests/test_base_image_pins.py` 26 tests; 16/17 mutants killed, 1 equivalent. Packaged stack from the branch: healthy, `ingress_matrix.py` 0 failing (worker, amd64 host; Sol, native arm64). No migration. Worker's worktree removed by the orchestrator. **Untested until release:** the weekly workflow on GitHub (one `workflow_dispatch` of "Base image pins" after merge, the owner's), the candidate workflow without `--db`. The next bundle ships PostgreSQL `3950ad7c…`, not v0.6.0-alpha's `65b16a8b…` (same `postgres:16` line).
- **Waiting on the owner:** one manual dispatch of "Base image pins".
- **Next:** #402. Proposed, not filed: `nginx:1.27-alpine` and `uv:0.5` are frozen lines the check can't flag; bookworm → trixie.

## 2026-11-23 — Claude Code (Opus 5.5) — #394 worker, lane 2: PR #401 open, CI and reviews pending
- **Done:** branch `394-token-scope-note`, [PR #401](https://github.com/DeusMaximus/plamotrack/pull/401) against `main` at `433bff2`, head `20afdfb` (code at `2d14dc5`; `20afdfb` only fills in the PR number in next-release.md). `settings.tokens.scopeNote` in the en-AU catalogue now says that over REST a read token downloads every export and a write token can also import in Merge or Add only mode; changing settings, managing tokens, Replace everything and any import that would change a setting stay with the owner login. Same terms as the README after #351. The section's other strings and `token_scope_invalid` were checked; none made the wrong claim; table in the PR body. Release entry `#394` at the end of `.agents/next-release.md`, including the docs site's `images/screenshots/tokens.png` (shows the note) to regenerate at release.
  - **Merged:** squash-merged as **`dbf4e7e`** at the reviewed head `20afdfb`, with the owner's sign-off; #394 is closed. Reviews: Codex connector at `2d14dc5` and at `20afdfb`, no findings; Greptile 4/5 at `2d14dc5`, one P2 (the `PR #PRNUM` placeholder, already fixed at `20afdfb`), answered and resolved. No briefed round. Checked by the orchestrator by reading: the wording against `plan_requires_admin` (an import needs `instance:admin` only for Replace everything or a settings UPDATE). No follow-ups.
- **Decisions:** the note says "Over the REST API" but doesn't mention MCP (keeps it to two sentences; the README covers it). Replace everything and a settings-changing import are listed as owner-only although a write token can preview them ("stay with" refers to applying, as the README says).
- **State:** frontend unit 718 passed (catalogue test file 320), lint and build pass. No test asserts the text, so no negative control or mutation pass. e2e not run; page not looked at in a browser. No backend change, no migration. Worktree removed by the orchestrator; branch left.
- **Waiting on the owner:** nothing for this PR.
- **Next:** at release, regenerate `tokens.png` on the docs site per the `#394` entry.

## 2026-11-23 — Claude Code (Opus 5.5) — #376 worker, lane 2: PR #397 open, CI and reviews pending
- **Done:** branch `376-multiline-notes`, [PR #397](https://github.com/DeusMaximus/plamotrack/pull/397) against `main`, head `9e34661` (code at `bef2de5`). A tool's Condition notes and a display item's Notes are now `Textarea`s in `ItemFormModal`. Their opening values go through the new `asTextareaValue` (`src/lib/oneLine.ts`), which turns CRLF and lone CR into LF, so a note that was only clicked into is never sent. The lists draw the two notes through `oneLine` (each break a space) in the table cells, the folded lines and the phone cards. Release note added at the end of `.agents/next-release.md`.
  - **Merged:** squash-merged as **`d293691`** at the reviewed head `9e34661`, with the owner's sign-off; #376 is closed. The orchestrator added `briefed-review` once the diff reached `lib/oneLine.ts`, the list cells inside `FoldToFit` and the lossless-save property. Reviews: Codex connector at `bef2de5`, no findings; Greptile 5/5, no findings; briefed round 1 (Codex GPT-6.1 Sol, `9e34661`) **GO** with one P3 (the `whitespace-pre-line` drawn-span mutant is inert, not killed; the table has 11 rows, 10 killed), answered and the PR body corrected without a push, with deliberate call 4 corrected (the catalog service trims both notes columns on write). Re-run by the orchestrator: the new spec on `6710912` from empty, Chromium `app`: 12 failed, setup passed. Follow-ups filed: #399 (other list cells leave a lone CR to WebKit), #400 (the other `Textarea` forms re-send a CRLF note rewritten).
- **Decisions:**
  - Rows show a note as one run of words, not with `pre-line`: the fold and `Measured` budgets were measured on one-line values.
  - The space comes from `oneLine` because WebKit draws a lone CR as nothing.
  - `oneLine` is applied at the six call sites, not inside `Measured`, because that would change every free-text cell on every page (#399).
  - The submit code is unchanged; the catalog service trims both columns on write.
- **State:**
  - **Tests:** new `e2e/multiline-notes.spec.ts` (12 tests a project; `app` + `phone`; added to `phone`'s `testMatch`). `lists.spec.ts` seeds its ordinary Tools note with a CR and its Display note with a CRLF, and checks how the row draws them. `one-line-breaks.spec.ts` now expects the break in the condition box.
  - **Counts:** full Chromium suite from empty 408 passed / 99 skipped / 0 failed, counts 0. Negative control on `main`: 24 red / 0 green (re-measured by the reviewer). 11 mutants, 10 killed, 1 inert. Unit 718 passed.
  - No backend change, no migration. Lane 2's Postgres container and volume and the worker's worktree removed by the orchestrator; branch left. Untested: `lists.settings.spec.ts` under WebKit, the iOS Simulator.
- **Waiting on the owner:** nothing for this PR.
- **Next:** #394 in lane 2.

## 2026-11-23 — Claude Code (Opus 5.5) — #351 docs drift: PR #393 open (lane 1)
- **Done:** [PR #393](https://github.com/DeusMaximus/plamotrack/pull/393) (branch `351-docs-drift`, head `06dfd78`) closes #351. All ten audit findings re-checked at `706234c` (README user-facing ones also at `v0.6.0-alpha`) and corrected: README token reach / MCP's two credentials / phone Data management / dev `.env` step / Node 20.19+, 22.12+ or 24+; `docs/import-export.md` export_version vs schema_version; design §2 (no dnd-kit), §4 (auth routes Built), §8, §11/§11.1 (M6 ✅, M6.7 in progress, release files shipped since v0.5.2); `AGENTS.md` release status, dev `.env` step, roadmap 4 and 6.7; `frontend/README.md` replaced; `.env.example` comment names the bundle's `env.example`. The `#351` entry in `.agents/next-release.md` now holds only the docs-site lines.
  - **Merged:** squash-merged as **`e92b1e2`** at the reviewed head `06dfd78`, with the owner's sign-off; #351 is closed. Reviews: Codex connector at `06dfd78`, no major issues; Greptile 4/5 at `6b9867b`, one P2 (the `PR #PRNUM` placeholder, already fixed at `06dfd78`), answered and resolved. No briefed round (docs only). Checked by the orchestrator by reading: the README's user-facing changes are true of v0.6.0-alpha (phone import shipped with #304 before the tag), no personal detail in the diff. Follow-ups filed: #394 (Settings → Access tokens says neither level can import or export; in this release), #395 (GitHub About text says Kanban; `owner`), #396 (README says `npm install`, not `npm ci`).
- **Decisions:** README fixes land on `main` now (each true of v0.6.0-alpha). #278 described as shipped, not closed (still open; #285).
- **State:** docs only, no migration. Clean-clone setup check done on a throwaway container, since removed. Worktree removed by the orchestrator; branch left. **Event subscriptions are off for this GitHub account** (`gh event listen` answers 403), so a delegated worker cannot wait on its PR: it hands back at PR open, and the orchestrator (watching the PR through T3 Code) sends it the reviews.
- **Waiting on the owner:** #395 (the About text).
- **Next:** at release, apply the `#351` docs-site lines (`authentication/overview.mdx`, `authentication/access-tokens.mdx`, and the `using/import-export.mdx` wording with #349). #344 rewords the same `AGENTS.md`/design §8 paragraphs.
