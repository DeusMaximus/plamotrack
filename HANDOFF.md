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

## 2026-09-25 — Claude Code (Opus 5.5) — #247 MERGED as `6000d96` (PR #298): kit lists sort by the date they print (`started`, `completed`, `newest`); list pages drop an unknown filter or sort from the URL

- **Done:**
  - [PR #298](https://github.com/DeusMaximus/plamotrack/pull/298) squash-merged as **`6000d96`**, pinned to the reviewed head `09f2260`; #247 closed.
    - `GET /kits` and MCP `list_kits` gain `started` and `completed` (the build's own date, newest first, undated kits last, `NULLS LAST` spelled out, ties by creation then id) and `newest` (created, newest first). `created`, `recent` and `name` are unchanged; `created` is still the API default.
    - Home: the bench sorts by `started`; Recently completed by `completed`, its *view all* `/kits?status=complete&sort=completed`. The Backlog strip keeps `recent` (newest arrivals); its *view all* is `/kits?status=backlog`, the page's default.
    - `completedOn` is the build date or null; an undated build prints "—" on Home and in the Kits page's Completed column.
    - Kits page menu: Newest added (the default), Oldest added, Recently started, Recently completed, Name A–Z. `recent` is not offered.
    - `useEnumParam` now drops a filter or sort value outside a page's vocabulary from the URL (replace, no history entry), on every list page. This came from Greptile's P2 in round 1: old `/kits?sort=recent` links, and old Orders links with `status=shipped`.
    - Docs: design §7, §13.2, §13.4. Its README lines were reverted to the release's wording afterwards (below).
  - Tests:
    - One shared fixture, `frontend/src/lib/__fixtures__/kit-sort-cases.json`, read by `backend/tests/test_kit_sorts.py` (16 cases) and `src/lib/home.test.ts` (18).
    - Negative control on unfixed `main`: backend 12 red / 4 green, frontend 7 red / 36 green.
    - The `247-` mutation set: 7/7 killed.
    - E2E: the full Chromium suite, 184 passed. `list-urls.spec.ts` covers the URL clean-up, and its new assertions fail without the fix.
  - `.agents/testing-and-review.md`: the cloud e2e recipe, a note on running the mutation harness in a worktree, and the suite counts.
- **Decisions (the owner's, 2026-09-25):**
  - New sorts beside `recent`, not a status-aware `recent`.
  - `recent` comes off the Kits page and nowhere else; the page defaults to `newest`.
  - The Backlog *view all* opens the page's default order.
  - **No fallback for a missing build date:** undated builds print none and sort last. The issue had proposed falling back to the status clock.
  - **Review call:** Greptile only, with Codex in its own cloud session available. Greptile went 4/5 then 5/5. The owner triggered CodeRabbit once: two Minor doc findings, both taken; its docstring warning declined.
- **State:**
  - **On the live instance once released:** completed kits imported without a completion date show "—" and sort last until dated. So do kits created directly as `complete`, because a create never stamps a build date.
  - **Unreleased on `main`:** #294 (Pocket ID `resource`), #289 (`create_order` `retailer_id`), #247.
  - **Cloud image:** Playwright drives the preinstalled Chromium through the recipe; no WebKit.
  - **New rule (the owner's, 2026-09-25; `AGENTS.md` → Release artifacts, `.agents/releases.md` step 7):** the docs site and the README's user-facing parts describe the **published release**, never `main`. The README lines #289 and #247 had changed went back to the v0.5.2-alpha wording on `main` the same day.
  - **Owed at the next release:** see `.agents/next-release.md` (the owner's call, 2026-09-25). It has entries for #247, #289 and #294; each user-visible PR adds its own, and after publication the entries that release shipped are removed.
  - **Unfiled defect, carried:** `_assemble_database_url` in `app/config.py` does not bracket an IPv6 `POSTGRES_HOST`. Compose pins `POSTGRES_HOST: db`, so only a source run with an IPv6 literal hits it.
  - **Carried from the 2026-09-23 #294 entry:**
    - **testhost is in the spike's state, not the gate's.** `/opt/plamotrack-280` runs the #294 build behind the tunnel against Pocket ID. The gate's stack and Keycloak are stopped. `probe.py teardown --base https://NAME --ssh root@HOST` restores them.
    - **Don't recreate Keycloak's container:** its `sub` would change.
    - The Claude.ai "Testing" connector points at the tunnel name.
    - The LXC is a v0.5.2 release install. #278 is open for the owner's skill-zip check.
  - Merged branches still on origin: `claude/plamotrack-cloud-setup-jgjfo0`, `fix/294-upstream-resource`, `claude/practical-heisenberg-fminub`.
- **Next:**
  1. At the next release: work through `.agents/next-release.md` (release step 7). Nothing changes on docs.gunp.la before then.
  2. The IPv6 `POSTGRES_HOST` defect: file it and fix it (small; can be done in a cloud session).
  3. Cloud-feasible candidates:
     - #124 (possibly already covered by the description; owner's call);
     - #125 (bigger than it looks: order edits, the importer, the dialog);
     - #268 and #238 (Chromium e2e now runs in the cloud);
     - the importer bugs #110, #116, #134 and #137.
  4. Carried: #279's edge probes then #281's packaging; the #280 decision; `probe.py teardown`; posting the rehearsal on #285; the release-to-release update and Git Bash commands, untested.

## 2026-09-25 — Claude Code (Opus 5.5) — #289 MERGED as `e72a7cc` (PR #297): MCP `create_order` names its shop by `retailer_id` or by name, and an id is never a name; the first cloud session from `main` checks the hook

- **Done:**
  - [PR #297](https://github.com/DeusMaximus/plamotrack/pull/297) squash-merged as **`e72a7cc`**, pinned to the reviewed head `5bbf46b`; #289 closed.
    - `create_order` takes `retailer_id` beside `retailer`, exactly one per call. The id goes straight to the order service, so an unknown id is `retailer.not_found` and nothing is written.
    - `get_or_create_retailer` refuses a name that parses as an id (any spelling `uuid.UUID()` takes, after the trim), even where a stored row already carries that string as its name. New code `name.is_id`, plus its fixture and en-AU catalogue entries.
    - Docs: the tool description, design §7 and the README's MCP table.
  - Tests: `tests/test_mcp_order_retailer.py`, 23 cases, 20 red / 3 green on unfixed `main`. The `289-` mutation set killed 7/7, and the file joins `TEST_FILES`. Backend 2859 passed, 1 xfailed (predates the branch); frontend vitest 631; CI 3/3 green.
- **Decisions (the owner's, 2026-09-25):**
  - **No delete tools on MCP.** Deleting anything is the user's call. `update_order`'s existing `changes.retailer_id` repoints an order; the UI renames or deletes.
  - The CSV importer's `retailer_name` keeps its select-or-create without the refusal: its preview lists the stub before anything is written, and an old archive must still import. No sibling filed.
  - **Review call:** Greptile and CodeRabbit only. Greptile gave 5/5 with no findings; CodeRabbit had no actionable comments. Its docstring-coverage warning was declined, as on #295 and #296. The owner's note: CodeRabbit allows about one included review per hour, while Greptile can be re-run for follow-up rounds.
  - The owner cleaned up the junk retailers #289 had minted on the live instance.
- **State:**
  - **The cloud hook, first session from `main`:** its summary matched the #296 entry. `TEST_DATABASE_URL` reached later shells, so the `CLAUDE_ENV_FILE` export works. Whether the snapshot is cached after the hook is still unobserved.
  - **Playwright in the cloud image:** `@playwright/test` 1.62.1 expects Chromium build 1234. It drives the preinstalled build 1194 (Chrome 141) when given `executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome'`. WebKit is not installed. The e2e suite itself has not been tried here.
  - `.agents/testing-and-review.md`'s suite counts are behind: backend ~1750 there, 2859 measured; frontend ~628, 631.
  - **Unfiled defect, carried:** `_assemble_database_url` in `app/config.py` does not bracket an IPv6 `POSTGRES_HOST`. `::1` yields a DSN `make_url` rejects.
  - **Unreleased on `main`:**
    - #294: v0.5.2 still forwards `resource`, so a Pocket ID install needs the API-registration workaround (#280 findings §2a) until the next release.
    - #289: v0.5.2's `create_order` still has no `retailer_id`.
  - **Carried from the 2026-09-23 #294 entry:**
    - **testhost is in the spike's state, not the gate's.** `/opt/plamotrack-280` runs the #294 build (`-f docker-compose.yml -f override-294.yml`) behind the tunnel in OIDC mode against Pocket ID. The gate's stack (`/opt/plamotrack`, v0.5.2) and Keycloak are stopped, volumes kept. `probe.py teardown --base https://NAME --ssh root@HOST` removes the spike and starts both.
    - **Don't recreate Keycloak's container.** It mounts `realm.json` from `/opt/plamotrack/.agents/deployment-gate/keycloak/`. A new container changes `sub`, and the gate's collection then needs `recovery rebind-oidc`.
    - The owner's Claude.ai "Testing" connector points at the tunnel name; remove it when the spike is done. Spike secrets are in `~/.plamotrack-gate/spike-280/`.
    - The LXC is a v0.5.2 release install. #278 is open for the owner's skill-zip check.
  - Merged branches still on origin: `claude/plamotrack-cloud-setup-jgjfo0`, `fix/294-upstream-resource`, `claude/practical-heisenberg-fminub`.
- **Next:**
  1. Owner: file the IPv6 `POSTGRES_HOST` defect, or start it; it's small and cloud-feasible.
  2. **Cloud-feasible candidates** from this session's survey:
     - #247: needs the owner's pick first; the issue recommends new `completed` and `started` sort values.
     - #124 and #125: `create_order`'s undocumented constraints; no `series` on its kit.
     - #268 and #238: frontend; the Chromium-only e2e above is unproven.
     - The importer bugs #110, #116, #134 and #137.
  3. Carried:
     - #279's two edge probes, then #281's packaging, then one proof deployment.
     - The #280 decision (owner).
     - `probe.py teardown` when the spike is done.
     - Posting the rehearsal on #285 (offered).
     - Untested: the release-to-release update, and the Windows commands in Git Bash.

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
