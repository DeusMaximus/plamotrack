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

## 2026-09-22 — Codex (GPT-6) — PR #290: GLM GO; three P3s addressed

- **Done:** the owner requested the three small review follow-ups. Added candidate-digest and post-copy drift witnesses for both API and web, plus same-digest retries for either or both existing version tags. Promotion behavior is unchanged. Runtime identity refusals now name the resolved Compose project and API/migrate/web image references, with a hint to reuse the startup directory and Compose/source-tag settings. The runbook explicitly records the first candidate's `GITHUB_ENV`/`COMPOSE_FILE` precedence and native-runner plugin-path watchpoints.
- **Review:** [GLM's review](https://github.com/DeusMaximus/plamotrack/pull/290#issuecomment-5770928209) is GO with three P3s at `6bed308`. The owner identifies the actual reviewer as **GLM 5.3**, despite the supplied brief and copied self-attribution saying Flash; this round took **19 minutes / $2.28 on OpenRouter** (owner-reported). No new review round is requested for these bounded follow-ups. This is not a fresh independent GO at the follow-up head.
- **Validation:** both digest mutants survived the old six-case matrix; the expanded matrix kills each (2 failed / 11 passed), and rejects a mutant refusing same-digest retries (3 failed / 10 passed). The diagnostic regression was 8 failed / 1 passed before the helper change; removing the new context kills the same eight cases. Each mutation restored byte-for-byte. Focused suite: **64 passed** (49 packaging + 15 existing controls). Real Docker/Compose smoke with isolated surrogate containers: matching identities pass; a deliberately mismatched configured API image names the project and all three images. No application or migration execution is claimed for that diagnostic smoke. Containers/network removed. Ruff, frontend production build, actionlint and diff checks passed. Evidence: `.dev/278/p3/` (gitignored).
- **State:** branch `codex/278-release-packaging`, PR #290 against `main`. Backend, Frontend and Integration CI passed at the reviewed `6bed308`; follow-up CI must be checked at the new pushed SHA. CodeRabbit's success is a skipped review, not an approval. The prior implementation/reviewer architecture and packaged-stack evidence remains historical; these edits change only tests, refusal text and maintainer documentation. The original development DB remains running.
- **Next:** update the PR coverage record and attributed response, verify the follow-up branch push and its CI; merge only when requested. #278 remains open, without a closing-issue link. The first real candidate still needs authorized GHCR publication, public/anonymous pulls, both native hosted gates, downloaded-artifact deployment/client evidence and actual promotion. No candidate run, tag, release, merge or deployment was performed. #285 retains existing-install upgrade acceptance.

## 2026-09-22 — Codex (GPT-6) — #278 committed and pushed; PR #290 open for review

- **Done:** the owner approved the implementation, requested commit/push, then the PR. Committed the 23 implementation/doc files as `c8743ab` and pushed `codex/278-release-packaging`; verified remote SHA and clean tree. Opened [PR #290](https://github.com/DeusMaximus/plamotrack/pull/290) against `main`, labelled enhancement and assigned to M6.7. Its attributed body contains the coverage record, measured controls and publication limitations; it says “Part of #278” so the issue remains open. This entry is the PR bookkeeping commit.
- **State:** release packaging is implemented, not published. Candidate build and promotion are manual, and publishing a release itself triggers no build. No version bump, registry images, tag, release, production deployment or docs-site change. #278 still needs public GHCR visibility/anonymous pulls, both native candidate jobs, artifact deployment/client evidence and a real promotion. #285 retains existing-install upgrade acceptance. The original development DB remains running; temporary stacks/volumes are gone.
- **Validation:** runtime/configuration evidence is for the tree committed as `c8743ab`: 48 focused tests, ARM64 native and AMD64 emulated builds/startup, 190 ingress rows per architecture, current modern/legacy MCP and REST versions plus credential-log scans. Ruff and the frontend production build were rerun before committing. actionlint/diff checks passed. Correction to the prior entry's wording: the four mutation configurations include three single-site promotion mutants and one pull-policy mutant changing both API-anchor and web declarations together; all were detected, but that is not independent mutation coverage of both policy declarations. The PR body makes this limit explicit. No unfixed-main red/green count or full local backend/e2e result is claimed.
- **Next:** await exact-head PR CI and independent review; no reviewer commissioned by this task. The review envelope follows `.agents/review-brief.md` and is saved in `.dev/278/review-brief.md`. No merge or candidate publication is authorized. After review and merge, follow `.agents/releases.md`, obtaining explicit authorization for registry publication, tagging and release publication. Inspect the live PR for its latest checks; this entry makes no CI-success claim. Evidence remains in `.dev/278/` (gitignored).

## 2026-09-22 — Codex (GPT-6) — #278 release packaging implementation on `codex/278-release-packaging`; commit/push authorized

- **Done:** read the live issue, repository instructions and current handoff; fetched origin and verified clean main at `f82ad7a` before branching. Added pull-only Compose plus explicit source-build override; API/migrate share an image, source tags and `pull_policy: build` exclude published-image substitution. Added revision/version image labels, deterministic skill ZIP and release bundle generator/checksums, manually dispatched candidate and promotion workflows, native amd64/arm64 candidate CI, and running-image/version checks. Promotion requires an existing tag at the successful candidate's exact SHA, copies digests without rebuilding, refuses conflicting version tags, and creates only a draft release. Source deployment-gate calls now require `--source-build`; release bundles use `--no-build`. README, configuration examples, design and maintainer procedures updated.
- **Decisions:** no moving release-channel tags; explicit versions and literal digests in downloadable Compose, including Postgres. The ZIP remains `plamotrack-gunpla.zip`, versioned by its release URL and manifest. Candidate reruns are not promotable: dispatch a fresh run so partial reruns cannot mix old gates and new artifacts. The normal PR check remains named `Integration`. First GHCR use needs owner-confirmed public package visibility; native jobs must pull anonymously. No release version chosen or bumped. Historical LXC build cause remains unknown.
- **Validation:** focused backend suites **48 passed**, Ruff check/format and actionlint passed. Both API/web architectures built; independent local stacks migrated fresh databases, served the app, and passed the packaged ingress matrix (**190 ARM64 / 190 AMD64 positive rows, zero failures**). ARM64 ran natively; AMD64 ran under OrbStack emulation. Both passed authenticated REST/current modern and forced-legacy MCP/version checks and non-vacuous credential-log scans. Image identity checks passed; wrong-source revision was refused. **4/4 single-site mutants killed**, restored byte-for-byte (pull policy, candidate SHA, rerun attempt, version overwrite). Evidence: `.dev/278/implementation-evidence.md`, build/start/ingress logs, `pytest-final.log`, `mutations.json` (gitignored).
- **State:** the owner approved the implementation and explicitly requested commit/push; this commit records the implementation and handoff on `codex/278-release-packaging`. No PR or GitHub comment, no tag/release/registry publication. #278 remains open. No claim of native GitHub runs, anonymous GHCR pulls or live promotion yet; full backend/e2e and remote TLS/OIDC gate not rerun locally. Disposable test stacks/volumes removed; the pre-existing development DB remains running. Local build images/evidence retained. Testhost, production and docs-site repo untouched. Current published release remains v0.5.0-alpha without the new assets.
- **Next:** verify the authorized branch push, then open the PR when requested. This changes the shared release/distribution boundary and warrants independent review before landing; none commissioned yet. After review, authorize the first candidate publication, verify public GHCR pulls and both native hosted gates, run the artifact deployment/client gate, then tag/promote/publish as separately authorized in `.agents/releases.md`. #278 acceptance is not complete until that publication evidence exists; #279/#280 remain separate investigations, and #285 owns existing-install upgrades. The handoff keeps five entries and rotates the oldest verbatim in this commit.
