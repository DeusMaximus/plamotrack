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

## 2026-09-24 — Claude Code (Opus 5.5) — #296 MERGED as `8f4985c`: a SessionStart hook sets up Claude Code cloud sessions (native Postgres 16, `uv sync`, `npm ci`); an IPv6 `POSTGRES_HOST` DSN defect found, not filed

- **Done:**
  - [PR #296](https://github.com/DeusMaximus/plamotrack/pull/296) squash-merged as **`8f4985c`**, pinned to the reviewed head `d70d9ac`. `.claude/hooks/session-start.sh`, registered in `.claude/settings.json`, is a no-op unless `CLAUDE_CODE_REMOTE=true`. In a cloud session it:
    - starts the image's own Postgres 16 and creates the role and database `Settings()` defaults to;
    - exports CI's `TEST_DATABASE_URL`;
    - runs `uv sync --frozen --python 3.12`;
    - migrates the dev database only when `Settings()` names that local one, judged on the parsed URL (host resolving to 127.0.0.1; port, database and credentials equal);
    - runs `npm ci` only when `package.json` or `package-lock.json` changed, or `npm ls --depth=0` finds `node_modules` incomplete.
  - Database trouble is reported in the hook's stdout summary, never fatal; a failed `uv sync` or `npm ci` fails the hook. AGENTS.md → *Dev environment & commands* has the paragraph.
  - Validated by hand: 9 paths and 13 migration-target values through the whole hook, with negative controls against the earlier heads. The harness ran it on this session's resumes. CI 3/3 green at `d70d9ac`.
- **Decisions:**
  - `npm ci`, never `npm install`: Node 22's npm (10.9.7) strips the lockfile's `libc` fields (78 deletions), which would dirty `package-lock.json` every session.
  - The hook never migrates a database it did not provision: an override is reported and left alone.
  - **Review call** (owner agreed): Greptile and CodeRabbit only, no GLM or Codex. It is dev tooling with no app code, and its worst failure is a session starting without dependencies, which the summary says.
    - Greptile ran three rounds: 4/5, 4/5, then 5/5 at the merged head. Every finding was fixed or answered in-thread.
    - Declined with the owner: a CI smoke test for the hook (CI's runner is not the cloud image; Greptile withdrew it) and CodeRabbit's docstring-coverage warning.
- **State:**
  - **Cloud image, 2026-09-24:**
    - Ubuntu 24.04; a Postgres 16 cluster present but stopped; Node 22.22.2; uv 0.8.17; `python3` 3.11, with 3.12 at `/usr/bin`.
    - Docker 29.3.1 and Compose v5.1.1 installed with the daemon stopped. A hand-started `dockerd` runs, but its first Docker Hub pull was refused with 429.
    - No IPv6: `::1` is refused.
    - The preinstalled Chromium is build 1194 against `@playwright/test ^1.62`; whether they agree is unchecked.
  - **Untested until the first new cloud session from `main`:** whether the snapshot is cached after the hook, and whether `CLAUDE_ENV_FILE`'s export reaches later commands. The hook's summary at the top of that session is the evidence.
  - **Unfiled defect:** `_assemble_database_url` in `app/config.py` does not bracket an IPv6 `POSTGRES_HOST`. `POSTGRES_HOST=::1` yields `…@::1:5432/…`, which `make_url` rejects (`ValueError … ':1:5432'`), so the API, alembic and `conftest.py` fail. It was offered as a task card, not filed as an issue.
  - **CodeRabbit** reviewed #296's first push. On later pushes its summary said the repo no longer gets automatic reviews ("fewer than 10 stars"); a review needs its *Trigger review* checkbox.
  - The merged branches `claude/plamotrack-cloud-setup-jgjfo0` and `fix/294-upstream-resource` are still on origin.
  - **Carried from the 2026-09-23 #294 entry, not touched this session:**
    - **Unreleased:** v0.5.2 still forwards `resource`, so a Pocket ID install needs the API-registration workaround (#280 findings §2a) until the next release.
    - **testhost is in the spike's state, not the gate's.**
      - `/opt/plamotrack-280` (Compose project `plamotrack-280`) runs the #294 build: `plamotrack-api:294-spike` through `override-294.yml`, brought up with `-f docker-compose.yml -f override-294.yml`.
      - It sits behind the tunnel in OIDC mode against Pocket ID (project `plamotrack-spike-280-idp`, no APIs registered).
      - The gate's stack (`/opt/plamotrack`, v0.5.2) and Keycloak are stopped, volumes kept. `probe.py teardown --base https://NAME --ssh root@HOST` removes the spike and starts both.
    - **Don't recreate Keycloak's container.** It mounts `realm.json` from `/opt/plamotrack/.agents/deployment-gate/keycloak/`, where an identical copy sits. A new container changes `sub`, and the gate's collection then needs `recovery rebind-oidc`.
    - The owner's Claude.ai "Testing" connector points at the tunnel name; remove it when the spike is done. Spike secrets are in `~/.plamotrack-gate/spike-280/`; logs in `.dev/280/` (gitignored).
    - The LXC is a v0.5.2 release install. #278 is open for the owner's skill-zip check.
- **Next:**
  1. Read the first new cloud session's hook summary; fix the hook where it disagrees with this entry.
  2. Owner: file the IPv6 `POSTGRES_HOST` DSN defect, or start its task card.
  3. Carried:
     - Owner, optional: a real-client Claude.ai link on the #294 build (#280 findings §8).
     - Owner: the #280 decision, on an optional supported provider.
     - #279's two edge probes, then #281's packaging, then one proof deployment.
     - `probe.py teardown` when the spike is done.
     - Posting the rehearsal on #285 (offered).
     - Untested: the release-to-release update, and the Windows commands in Git Bash.

## 2026-09-23 — Claude Code (Opus 5.5) — #294 MERGED as `ee458f4` (PR #295): the MCP proxy's upstream authorization request is its own — no client `resource`, the scope pinned to `openid`; Pocket ID links with no workaround

- **Done:**
  - [PR #295](https://github.com/DeusMaximus/plamotrack/pull/295) squash-merged as **`ee458f4`**, pinned to the reviewed head `886c0a0` (the merge tree equals the head's); #294 closed. `forward_resource=False`, and `UPSTREAM_SCOPE` ("openid") set through `extra_authorize_params` — a sibling the value sweep found: a client that omits `scope` asked the provider for nothing, not even `openid`. Rule 13 (AGENTS.md) and the design's family-8 row say the upstream request is the proxy's.
  - Test `test_nothing_the_client_sends_reaches_the_provider_but_its_scope`, 12 cases (DCR/CIMD × `resource` absent / `…/mcp/` / `…/mcp` × `scope` sent / omitted): 10 red / 2 green on unfixed `main`. Harness cases `moa-116` and `moa-117`, each killed apart. Neighbouring suites 665 passed, 1 xfail that predates the branch; CI 5/5.
  - Live, before merging: Pocket ID v2.16.0 with **both API registrations removed**, through the tunnel — link, refresh, transparent refresh, the race, the browser login; Keycloak 26.6 through the reference Caddy — login, link, refresh, and the upstream request carried exactly the nine expected parameters.
- **Decisions:** the review call (the owner agreed) — Greptile and CodeRabbit only, no GLM or Codex round: the change only removes what goes upstream, and its worst failure is a loud false refusal at link time, which the release gate's OIDC and MCP legs would catch. Greptile 5/5, no findings; CodeRabbit no actionable comments, its docstring-coverage warning declined (the PR body's Review section says why).
- **State:**
  - **Unreleased:** v0.5.2 still forwards `resource`, so a Pocket ID install needs the API-registration workaround (#280 findings §2a) until the next release.
  - **testhost is in the spike's state, not the gate's.** `/opt/plamotrack-280` (Compose project `plamotrack-280`) runs **the #294 build** — `plamotrack-api:294-spike` through `override-294.yml` (bring it up with `-f docker-compose.yml -f override-294.yml`); web and db are the v0.5.2 release — behind the tunnel (`WEB_BIND` on the LAN address, `TRUSTED_PROXIES` the connector), in OIDC mode against Pocket ID (project `plamotrack-spike-280-idp`, the gate's `idp.` name on loopback 8081, provider access-token lifetime 1 min, **no APIs registered now**). The gate's stack (`/opt/plamotrack`, v0.5.2, back on its release images) and Keycloak are **stopped**, volumes kept. `probe.py teardown --base https://NAME --ssh root@HOST` removes the spike and starts both.
  - **Keycloak's container mounts `realm.json` from `/opt/plamotrack/.agents/deployment-gate/keycloak/`** — the path it was created at, before the rehearsal moved the checkout to `/opt/plamotrack-source`; an identical copy sits there. **Don't recreate it:** the realm pins no user ids, so a new container changes `sub` and the gate's collection then needs `recovery rebind-oidc`.
  - The owner's Claude.ai "Testing" connector points at the tunnel name; remove it when the spike is done. Spike secrets are in `~/.plamotrack-gate/spike-280/`; logs in `.dev/280/` (gitignored).
  - The merged branch `fix/294-upstream-resource` is still on origin.
  - The LXC is a v0.5.2 release install since 2026-09-23 (moved from its Git checkout by the docs' path, no friction). #278 is open for the owner's skill-zip check.
- **Next:**
  1. Owner, optional: reconnect the Claude.ai connector for a real-client link on the #294 build with no API registration — the remaining condition of #280's recommendation (findings §8).
  2. Owner: the #280 decision (an optional supported provider).
  3. #279: the two edge probes (a header-echo image on Railway's trial and a Render free service — the edge's source addresses, `X-Forwarded-For`, the resolver, the health-check `Host`), then #281's platform-neutral packaging, then one proof deployment.
  4. `probe.py teardown` when the spike is done.
  - Carried: posting the rehearsal on #285 (offered). Untested: the release-to-release update, and the Windows commands in Git Bash.

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
  - #278 is still open for the owner's skill-zip check.
  - **The LXC is on v0.5.2 as a release install** (corrected after this entry was first written): the owner moved it on 2026-09-23 by the docs' Updating → "If you installed with Git" — the checkout moved aside, `.env` copied back, the release files fetched with `curl` — and the collection (about 100 kits) came through; the owner reports the instructions were straightforward and the old `.env` needed no edits. The first real-world run of the Git → release path; evidence for #285. Its load, for #279's sizing: about 330 MiB RAM for the whole LXC and ~1.5 % of 2 cores at idle, ~11 % CPU briefly during the upgrade.
- **Next:**
  1. #294: the fix with a test run against the unfixed code first, then the spike **without** the API registration, and the gate's OIDC phase against Keycloak.
  2. Owner: the #280 recommendation (findings §8 — an optional supported provider once #294 lands and a real-device run passes without the workaround).
  3. `probe.py teardown` when the owner is done with the spike.
  4. The #279 proof deployment when the owner opens platform accounts.
  - Carried from the previous entry: posting the rehearsal on #285 (offered) — now with the LXC's real move beside it. Untested: the release-to-release update, and the Windows commands in Git Bash.

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
