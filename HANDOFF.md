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

## 2026-09-23 — Claude Code (Opus 5.5) — #280 Pocket ID: the browser login works as shipped, MCP needs the forwarded `resource` dropped (#294 filed); real passkeys and Claude.ai pass through the tunnel; #279 recorded on paper

- **Decisions (the owner's, 2026-09-23):** #279 is **paper only for now** — no platform accounts; the proof deployment comes back after #280. #280 ran on testhost; file #294, post the findings, commit the spikes.
- **Done:**
  - `.agents/spikes/279/README.md`: Railway vs Render from their documentation (prices are dated estimates, not measured), the five things #281's packaging needs on any platform (nginx's Docker resolver, the literal upstream and port, Railway's health-check `Host` against default-deny, undocumented edge ranges for `TRUSTED_PROXIES`, `migrate` as a pre-deploy command), and the questions only a deployment answers.
  - `.agents/spikes/280/`: `probe.py` (reuses `deployment_gate.py`; signs in with a CDP virtual passkey), `sequence.sh` (end to end from a clean start, exit 0), Pocket ID v2.16.0 pinned by digest, `findings.md`. Commits `9a544b4`, `38d29bd`; [report](https://github.com/DeusMaximus/plamotrack/issues/280#issuecomment-5788088730) and [follow-up](https://github.com/DeusMaximus/plamotrack/issues/280#issuecomment-5789076954) on #280.
  - Against the unmodified v0.5.2 release: claim, later login, a stranger refused. The **MCP link is refused at Pocket ID's `/authorize`** (`invalid_request`) because the proxy forwards the client's RFC 8707 `resource` (FastMCP `forward_resource=True`). With `<base>/mcp` registered as a Pocket ID API (the workaround): link, refresh, transparent refresh, the concurrent-refresh race (exactly one upstream call — Pocket ID ends the whole grant on reuse, measured), restarts, revocation (local only: no upstream revocation endpoint), export → `down -v` → import, a wrong `ENCRYPTION_KEY` (Pocket ID won't start), lost-passkey recovery (same `sub`, no rebind).
  - The owner's legs, through the gate's tunnel name: a Proton Pass passkey from Chrome on macOS and on Android; Claude.ai as a custom connector (a CIMD client), including a call past Pocket ID's one-minute token (transparent refresh); a browser write. **The provider only has to be reachable by the owner's browser** — Claude.ai's servers never talk to it.
  - Filed [#294](https://github.com/DeusMaximus/plamotrack/issues/294) (bug, M6.7): `forward_resource=False`, a fake-provider test, the sweep.
- **State:**
  - **testhost is in the spike's state, not the gate's.** `/opt/plamotrack-280` (Compose project `plamotrack-280`, OIDC mode against Pocket ID) is behind the tunnel: `WEB_BIND` on the LAN address, `TRUSTED_PROXIES` the connector. Pocket ID (project `plamotrack-spike-280-idp`) holds the gate's `idp.` name on loopback 8081, access-token lifetime 1 min, two APIs registered. The gate's stack (`/opt/plamotrack`, v0.5.2) and Keycloak are **stopped**, volumes kept. `probe.py teardown --base https://NAME --ssh root@HOST` removes the spike and starts both again.
  - **Keycloak's container mounts `realm.json` from `/opt/plamotrack/.agents/deployment-gate/keycloak/`**, the path it was created at before the rehearsal moved the checkout to `/opt/plamotrack-source`. Once stopped it would not start (Docker had made an empty directory there); an identical copy of the file now sits at that path, and the same container restarted with the owner's `sub` intact (the gate owner's sign-in was verified). **Don't recreate it:** the realm pins no user ids, so a new container changes `sub` and the gate's collection then needs `recovery rebind-oidc`.
  - Spike secrets are in `~/.plamotrack-gate/spike-280/` (the first run's in `spike-280.first-run/`); run logs and screenshots in `.dev/280/` (gitignored).
  - The owner's Claude.ai "Testing" connector points at the tunnel name; remove it when the spike is done.
  - #278 is still open for the owner's skill-zip check. The LXC is unchanged (0.4.1, source).
- **Next:**
  1. #294: the fix with a test run against the unfixed code first, then the spike **without** the API registration, and the gate's OIDC phase against Keycloak.
  2. Owner: the #280 recommendation (findings §8 — an optional supported provider once #294 lands and a real-device run passes without the workaround).
  3. `probe.py teardown` when the owner is done with the spike.
  4. The #279 proof deployment when the owner opens platform accounts.
  - Carried from the previous entry: the owner's LXC move (docs Updating → "If you installed with Git"; a read-only look offered, pending the owner's OK to SSH); posting the rehearsal on #285 (offered). Untested: the release-to-release update, and the Windows commands in Git Bash.

## 2026-09-23 — Claude Code (Opus 5.5) — the docs move to the release install: PR #293 (README + runbook) and plamotrack-docs#7 (all install/update pages) open; the Git → release move rehearsed on testhost, 0 failed

- **Decisions (the owner's, 2026-09-23):**
  - The docs lead with the published release files now, without waiting for M6.7 to finish.
  - The README's install section shows **only** the release method. The README is the public page for now. The contributor section "Developing on it" stays.
  - The repo's `docker-compose.yml` stays the source/pull-only template. Pinning the current release in it was declined for three reasons: a commit can't carry its own digests; `main`'s compose file must describe `main`'s code; and it would reopen #290's source-substitution class.
- **Done:**
  - [PR #293](https://github.com/DeusMaximus/plamotrack/pull/293): the README install moves to the release files, run verbatim on macOS. `.agents/releases.md` step 5 gains "update from the previous release's files" (its first real run is v0.5.2 → the next release), and step 7 bumps the version named in the README and docs commands.
  - [plamotrack-docs#7](https://github.com/DeusMaximus/plamotrack-docs/pull/7), retitled, now covers every page:
    - Installation: the release files, with Git Bash kept only as Windows' terminal.
    - Updating: release to release, plus "If you installed with Git" with the tested same-folder move and a collapsed block for Git updates.
    - Backups (`--no-build`), Troubleshooting, Configuration (the `COMPOSE_*` keys are Git-only), VPS + Caddy (the drop-in inline), Agent Skills (the zip comes from the release), and the v0.5.2 changelog.
    - `mint broken-links` is clean.
  - **Rehearsal** (`.dev/0.5.2/rehearsal/`, gitignored; `procedure.md` holds the table, `rehearse.py` the driver-based script):
    - Start: a `git clone` at v0.4.1 in OIDC mode, claimed, with data, a PAT and an OAuth MCP client linked.
    - (a) A new folder plus `COMPOSE_PROJECT_NAME`, and (b) the checkout renamed aside with a fresh folder of the same name. Both ran forward, rolled back and ran forward again, with **0 failed checks**: session, PAT, data, the same volume (CreatedAt), audit rows, MCP refresh and initialize, no re-registration.
    - The set-aside checkout is its own project (`plamotrack-source`).
    - The gate's matrices trip the limiters on purpose, so linking an MCP client right after them needs a ~2 min wait.
- **State:**
  - testhost is a **release install** at `/opt/plamotrack` (v0.5.2, project `plamotrack`), with the 0.4.1 checkout at `/opt/plamotrack-source`.
  - #278 is still open for the owner's skill-zip install check.
  - The LXC is unchanged (0.4.1, source).
- **Next:**
  1. ~~Owner: review and merge #293 and docs#7.~~ **Both merged 2026-09-23** after one Greptile round each (5 findings, all fixed): #293 as `157075f`, plamotrack-docs#7 as `4f54466`. docs.gunp.la serves the release install (checked live).
  2. The owner's LXC move, per Updating → "If you installed with Git". A read-only look first is offered, pending the owner's OK to SSH.
  3. Post the rehearsal on #285 as evidence (offered, not yet agreed).
  4. #279 and #280.
  - Untested: the release-to-release update (no predecessor yet), and the Windows commands in Git Bash (NEMESIS).

## 2026-09-23 — Claude Code (Opus 5.5) — **v0.5.2-alpha PUBLISHED**, the first release with its own install files; v0.5.1-alpha tagged and promoted but never published (GitHub renamed an asset); #292 fixed the pipeline; #278 open for one check; plamotrack-docs#7 awaits the owner's merge

- **Done — the chain, each gated step on the owner's word:**
  - **v0.5.1-alpha:** #291 was squash-merged as `e62bb02`. Candidate [35789572692](https://github.com/DeusMaximus/plamotrack/actions/runs/35789572692) passed on native amd64 and arm64, and both first-run watchpoints were observed working (now recorded in `.agents/releases.md`). The owner made both GHCR packages public; this is irreversible and one-time. The deployment gate on testhost against the release files had 0 failing checks. Tag `v0.5.1-alpha` was pushed and promotion 35794488988 succeeded. **Then the draft carried `default.env.example`:** GitHub renames an uploaded asset whose name starts with a period, so the draft's own `sha256sum -c` failed. **Not published.** The owner chose to fix the pipeline and ship 0.5.2. At the owner's request the v0.5.1 draft was deleted; its tag and its GHCR `v0.5.1-alpha` image tags stay, unmoved and unsupported.
  - **The fix, [#292](https://github.com/DeusMaximus/plamotrack/pull/292), squash-merged as `4586081`:**
    - The template ships as `env.example`.
    - `promote_release.py` downloads its own draft and runs `verify()` on it, then compares it to the gated manifest.
    - `host-prepare.sh` accepts a release directory (it required `backend/`), and the gate README has an "Against a release's files" recipe.
    - It also carried the 0.5.2 bump and a lesson in `.agents/lessons.md`: "The asset GitHub renamed".
    - Tests: 65 passed; the new tests fail 9 times on unfixed `main`; 5 single-site mutants were all caught. Greptile rated it 5/5 with no findings.
  - **v0.5.2-alpha:** candidate [35797496522](https://github.com/DeusMaximus/plamotrack/actions/runs/35797496522) passed on both native runners, then the gate on testhost with the **unmodified** `host-prepare.sh` (0 failing; matrix 180/183/87 ok rows). Tag `v0.5.2-alpha` → `4586081`. Promotion 35800649160 succeeded, including its read-back. By hand: `sha256sum -c` and `verify` pass on the draft's downloads, which are byte-identical to the gated bundle, and both image tags resolve anonymously to the tested digests. **Published 2026-09-23 as a prerelease.**
  - **Earlier today:** docs [plamotrack-docs#7](https://github.com/DeusMaximus/plamotrack-docs/pull/7) fixes the source-upgrade `denied` trap (an `.env` from v0.5.0 or earlier lacks `COMPOSE_FILE`) and now also carries the v0.5.2 changelog entry. `mint broken-links` is clean.
- **Decisions (the owner's):**
  - The version was 0.5.1, then 0.5.2 after the rename.
  - The real-client MCP run was skipped: `/mcp` hasn't changed since 0.4.1.
  - Delete the 0.5.1 draft.
  - The release notes redact **all** network addresses and the gate host's name, not only the public address; 0.5.0's notes had published the internal ones.
- **State:**
  - **#278 is OPEN.** Every acceptance line is shown except "the skill can be installed". The zip downloads and holds its parent folder, but uploading it to Claude Desktop hasn't been tried; the owner is to try it, then close #278. #285 owns the existing-install transition. **Trap for #285:** the Compose project, and so the DB volume, is named after the directory, so the release files in a new directory start an **empty** collection.
  - plamotrack-docs#7 is open, awaiting the owner's merge (merging publishes the docs site).
  - testhost holds the v0.5.2 bundle in the gate's end state (mode R, OIDC fixture, Keycloak up). Earlier `.env` copies are in `/root`.
  - Evidence is in `.dev/0.5.1/` and `.dev/0.5.2/` (gitignored): candidate logs, gate results and run logs, notes, downloads.
  - Merged branches `release/0.5.1` and `fix/278-release-asset-names` are still on origin (no deletion asked). The tree is clean on `main`.
- **The LXC (still 0.4.1, a source install):** before its next update, add the two `COMPOSE_FILE` lines to `.env`, or `up` stops with `denied`, changing nothing. To go back to 0.5.0, remove them again (0.5.0 has no `docker-compose.build.yml`). Stay on source until #285.
- **Next:**
  1. Owner: merge plamotrack-docs#7, then try the skill zip and close #278.
  2. Then #279 (platform: needs published images, now available) and #280 (Pocket ID, can start any time).
  3. Then #285, with the volume-name trap above.
  - Row counts in the gate matrix vary by one or two between runs (local 179–181, OIDC 182–183); **0 failing** is the criterion.

## 2026-09-23 — Claude Code (Opus 5.5) — PR #290 merged as `07859b5`; release PR #291 (v0.5.1-alpha) and plamotrack-docs#7 (upgrade fix) open; the oldest entry rotated

- **Done:** recorded that [PR #290](https://github.com/DeusMaximus/plamotrack/pull/290) (#278 release packaging) merged into `main` on 2026-09-22 as merge commit **`07859b5`**; main CI passed at that commit. #278 stays open (no closing link): acceptance is the first real release through the pipeline, and no candidate has been dispatched yet (`gh run list --workflow release-candidate.yml` is empty).
- **Found:** #290 made `docker-compose.yml` pull-only: `ghcr.io/deusmaximus/plamotrack-{api,web}:unreleased`, which is never published (GHCR: `denied`). The new `.env.example` sets `COMPOSE_PATH_SEPARATOR=:` and `COMPOSE_FILE=docker-compose.yml:docker-compose.build.yml`, so a **fresh** source install works. An `.env` copied at v0.5.0-alpha or earlier lacks both lines. After `git pull`, `docker compose up -d --build --wait` then fails with `Error response from daemon: error from registry: denied`. This was reproduced in a scratch project: nothing was created (no container, network or volume). The docs site's Updating page prescribed exactly that sequence. **The LXC (0.4.1) is in this class:** add the two lines before its next source upgrade.
- **Decisions:** the owner chose **v0.5.1-alpha** for the first release through the pipeline (2026-09-23). No application code changed since v0.5.0-alpha (`backend/app` and `frontend/src` are untouched), so the release tests only the pipeline.
- **State:**
  - [plamotrack-docs#7](https://github.com/DeusMaximus/plamotrack-docs/pull/7), branch `fix/upgrade-compose-file` at `0f77e84`: the Updating steps gain "check `.env` for `COMPOSE_FILE`", Troubleshooting gains the `denied` entry, and the Configuration reference gains a Docker Compose table. `mint broken-links` is clean. The 0.5.1 changelog entry is separate; it lands at publication with the gate results.
  - [PR #291](https://github.com/DeusMaximus/plamotrack/pull/291), branch `release/0.5.1` at `d2da19f`, milestone M6.7:
    - The version is 0.5.1 in `app/__init__.py`, `pyproject.toml` and `uv.lock`, done with `uv lock` as the gate requires. uv 0.9.30 also restores `secretstorage`'s two win32 dependency markers, which the 0.5.0 bump dropped; `secretstorage` is Linux-only, so nothing resolves differently.
    - README, AGENTS.md, `skills/README.md` and `.agents/releases.md` name v0.5.1-alpha as the first release with assets.
    - The PR body carries the gate checklist.
    - Checks: `validate_version('v0.5.1-alpha')` passes and v0.5.0-alpha is refused; version tests (8), `test_release_artifacts` (60) and portability + MCP + packaging (307) pass; `uv lock --locked` and ruff are clean. Exact-head CI was pending at this entry.
- **Next:**
  1. Check exact-head CI on #291 and merge it (owner's call). Merge docs#7 when the owner says.
  2. With the owner's explicit OK, dispatch **Release candidate** on #291's merge commit with `v0.5.1-alpha`. The owner then makes both GHCR packages public. Watch the two first-run watchpoints in `.agents/releases.md` step 4.
  3. Run the deployment gate on testhost against the downloaded bundle, without `--source-build`.
  4. Tag (owner OK), promote, fill the draft notes and the docs changelog, then publish (owner OK).
  5. Close #278 and record the observed watchpoints in the runbook.

  #280 (Pocket ID) can run in parallel. #279 needs the published images.

## 2026-09-22 — Codex (GPT-6) — PR #290: CodeRabbit's manifest/Compose binding fixed

- **Done:** owner approved fixing [CodeRabbit's review](https://github.com/DeusMaximus/plamotrack/pull/290#pullrequestreview-5274240328) at `04cc8bb`. Reproduced that changing any service image and recomputing checksums passed bundle verification. `verify` now parses the explicit bundle with Docker Compose and compares db, migrate, api and web individually to the manifest. Interpolation and env-file resolution are disabled: releases require literal digest pins and verification needs no operator `.env`. Explicit file/project arguments isolate caller Compose settings. Existing checksum/file/reference checks remain intact. The runbook and module docstring state the Compose CLI requirement; no running daemon is needed.
- **Validation:** 10 new mismatch cases failed at `04cc8bb`; the unrelated-caller positive control passed. Cases cover each service separately, API+migrate together, and an image variable whose caller value matches the manifest. Focused suite **75 passed** (60 packaging + 15 existing controls), including verification pointed at an unreachable Docker daemon. Three single-site mutants killed: disabled binding (10 failures), global substring comparison (4 failures), interpolation enabled (5 failures); byte-for-byte restoration. Ruff, frontend build, actionlint and diff checks passed. Evidence: `.dev/278/coderabbit/` (gitignored). No application/container deployment was needed.
- **Review/state:** GLM **5.3** (owner-corrected; not Flash) gave GO+3P3 at `6bed308`; those follow-ups were pushed as `04cc8bb`. CodeRabbit subsequently performed a real review at `04cc8bb`; the older skipped-review state is historical. Its one low-priority finding is addressed here. No additional independent round requested for these small follow-ups. Frontend and Integration passed at `04cc8bb`; Backend was still running at last check. Inspect current-head CI before merge; older checks/review are not a new-head verdict.
- **Next:** commit/push the authorized fix and update PR #290's coverage/response; merge only when requested. #278 remains open without a closing-issue link. First candidate publication still needs explicit approval, public/anonymous GHCR pulls, both native hosted gates (including the documented Compose environment/plugin watchpoints), downloaded-artifact deployment/client evidence and actual promotion. No registry publication, release, tag, merge or deployment performed. #285 retains existing-install upgrade acceptance. Original development DB remains running; no temporary stack was started.
