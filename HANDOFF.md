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

## 2026-09-25 — Claude Code (Opus 5.5) — #299, #300, #301 filed and fixed in PR #302 (open): an IPv6 `POSTGRES_HOST`, a `%` in the URL alembic reads, and secrets echoed by a settings refusal

- **Done:**
  - Filed three bugs, each reproduced on `main` at `23e4b0e`:
    - [#299](https://github.com/DeusMaximus/plamotrack/issues/299): the IPv6 `POSTGRES_HOST` carried from the last entry;
    - [#300](https://github.com/DeusMaximus/plamotrack/issues/300): alembic's ConfigParser refuses any `%`, so a punctuated `POSTGRES_PASSWORD` stops the **published** `migrate` service;
    - [#301](https://github.com/DeusMaximus/plamotrack/issues/301): a `Settings` refusal printed `input_value=`, which held the head and tail of `.env`'s secrets, into the container log.
  - [PR #302](https://github.com/DeusMaximus/plamotrack/pull/302) on `claude/relaxed-albattani-vvepwn` closes all three:
    - `config.py` renders the URL with `URL.create`, unwraps `[::1]`, and refuses a colon outside an IPv6 literal (only when assembling). It also sets `hide_input_in_errors=True`.
    - `alembic/env.py` doubles `%`.
    - `asyncpg_dsn` writes a host's `%` as `%25`.
  - Tests:
    - `tests/test_database_url.py` (51): 29 red / 22 green on unfixed `main`.
    - `tests/test_settings_errors.py` (4): 4 red.
    - The `dsn-` mutation set: 9/9 killed, and both files are in `TEST_FILES`.
    - Backend: 2930 passed, 1 xfailed (predates the branch).
  - `.agents/next-release.md` has the entry.
- **Decisions (the owner's, 2026-09-25):**
  - **A zone id is raw in the SQLAlchemy URL, `%25` only for asyncpg's parser**, not RFC 6874 everywhere as the task first said. SQLAlchemy never decodes a host, and the resolver refuses `fe80::1%25lo`.
  - **#300 and #301 ride in the same PR** as separate issues: same class, and each is needed for #299's fix to be complete and not leak.
- **State:**
  - **PR #302 is open and cleared for merge by review: GLM 5.3's round 2 at `b3aa1e9` is GO.** Greptile scored it 5/5 with no findings. Round 1 at `dd6f3df` was **NO-GO**, with a P2 and three P3s, answered on the thread. Round 2's one finding (5, a P3 record clause) is taken in the PR body. The merge itself is the owner's.
    - P2 fixed: the harness's first dsn-5 sent the mutant session to the dev database. Re-anchored, then made judge-only at `b3aa1e9`, because the re-anchor still redirected under an IPv6 `.env` host. Proven with a canary row; the rule is in testing-and-review, the case in lessons.md.
    - P3 finding 2: the finding was right, the remedy was declined with a counterexample. The state store reads the engine's host; decoding `%25` first breaks a real zone `%25`.
    - P3s 3 and 4: a tripwire comment in `config.py`, and record corrections.
    - The subscription to #302 and a fallback check-in are live in the session that wrote this.
  - **This entry rides on the PR branch, not `main`**: the session could push only to its branch. Once the PR merges it lands on `main` as usual. `main` got the #280 entry below first, so `main` was merged into the branch: both entries kept, and the #294 entry rotated out.
  - **Proven in Compose, not with the shipped image:** Docker runs in the cloud session once `dockerd` is started (`.agents/testing-and-review.md` → Docker in a cloud session). The `migrate` service ran with its image swapped for the Python base plus the locked dependencies, the source mounted, and a punctuated `POSTGRES_PASSWORD` in `.env`.
    - `main` failed with #300's interpolation error, and its log printed the URL and password.
    - The branch migrated to head.
    - With an OIDC misconfiguration, `main`'s log printed the signing key's tail (#301); the branch's printed none.
    - The API image itself can't be built there: the `uv` blob on `ghcr.io` is refused by the egress policy.
  - **Not testable in the cloud session:** a live IPv6 connection (the container's kernel has no IPv6 stack), and the shipped image (the ghcr blob host is refused). GLM round 2 closed both on the owner's Mac.
    - Postgres on `[::1]`: the engine and the state store's pool both connected.
    - The packaged stack built as written: `migrate` ran online with a punctuated password, and the OIDC refusal printed no secret.
    - Still open: a pool to a zone-id host, which needs Linux.
  - **Unreleased on `main`:** #294, #289, #247, plus this PR once merged; see `.agents/next-release.md`. It also owes the Pocket ID docs page.
  - **Carried from the 2026-09-25 #280 entry:**
    - #280 is decided and closed: Pocket ID is an optional supported provider, documented from the release that ships #294.
    - testhost is back in the gate's state: `probe.py teardown` ran, and the gate's stack (v0.5.2) and the same Keycloak container are up.
    - **Owner:** delete the Claude.ai "Testing" connector; the spike it pointed at is gone.
    - Don't recreate Keycloak's container on testhost: a new one changes `sub`, and the gate's collection then needs `recovery rebind-oidc`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
    - Merged branches still on origin: `claude/plamotrack-cloud-setup-jgjfo0`, `fix/294-upstream-resource`, `claude/practical-heisenberg-fminub`.
- **Next:**
  1. PR #302: merge (the owner's call; earlier PRs were squash-merged). After it, check that #299, #300 and #301 closed, and record the merge on `main`.
     - The real-image check no longer waits on the cloud environment for #302: GLM round 2 ran it on the owner's Mac. Allowing `pkg-containers.githubusercontent.com` in the environment's Network access (the owner said they would, 25/09/2026) is still what lets a cloud session build the API image; the recipe is in `.agents/testing-and-review.md` → Docker in a cloud session.
  2. At the next release: work through `.agents/next-release.md` (release step 7), the Pocket ID page included.
  3. Carried from the #280 entry: #279's two edge probes, then #281's packaging, which includes whether to bundle Pocket ID; #282's VPS path can build on the Pocket ID recipe (findings §4–§5, §8).
  4. Carried:
     - Cloud-feasible candidates: #124, #125, #268, #238; the importer bugs #110, #116, #134 and #137.
     - Posting the rehearsal on #285.
     - Untested: the release-to-release update and the Git Bash commands.

## 2026-09-25 — Claude Code (Opus 5.5) — #280 DECIDED and closed: Pocket ID is an optional supported provider; Claude.ai linked on the #294 build with no API registration; testhost back in the gate's state

- **Done:**
  - **The owner's last #280 leg.** On testhost, the #294 build with **0 Pocket ID APIs registered**, the owner removed the Claude.ai connector and added it again.
    - Pocket ID's `/authorize` got `scope=openid` and no `resource`, and accepted it.
    - The rest held: the Proton Pass passkey sign-in, `auth.mcp_grant_issued`, six tool calls returning 200, and a transparent refresh after the 1-minute token expired.
    - Claude.ai first presented the old link's refresh token, which it had kept after the connector was removed. Pocket ID refused it, because its audience names a removed API, and Claude.ai asked to reconnect.
    - Redacted evidence: `.dev/280/2026-09-25-claude-ai-no-workaround.txt` (gitignored).
  - **`55c0d3c` on `main`:**
    - Findings: §7 gains the run, and §8 becomes the decision.
    - `.agents/next-release.md`, the #294 entry: the reconnect line, and the **Pocket ID docs page** owed at the next release.
    - The `AGENTS.md` roadmap and design §11.1 record the decision.
  - [Decision comment](https://github.com/DeusMaximus/plamotrack/issues/280#issuecomment-5828486387) posted on #280; the issue is **closed** as completed.
  - **`probe.py teardown` ran.** The spike's stacks, its volumes and `/opt/plamotrack-280` are gone. The gate's stack (v0.5.2, `/opt/plamotrack`) and the **same** Keycloak container are up and healthy, so `sub` is unchanged. Two images are left on testhost, `plamotrack-api:294-spike` and Pocket ID v2.16.0: harmless and reusable.
- **Decisions (the owner's, 2026-09-25):**
  - Pocket ID is an **optional supported provider**. The owner's reason: it makes setting up OAuth for an assistant much easier.
  - It is documented from the release that ships #294, because the docs describe the published release.
  - Bundling it in a hosting template is #281's call, together with #279's platform. #282 can document it next to the reference Caddy.
- **State:**
  - **Owner:** delete the Claude.ai "Testing" connector. Its tunnel name pointed at the spike, which is gone.
  - Unreleased on `main`: #294, #289 and #247. What each owes at release is in `.agents/next-release.md`.
  - **Don't recreate Keycloak's container on testhost.** Its realm pins no user ids, so a new container changes `sub`, and the gate's collection then needs `recovery rebind-oidc`. It mounts `realm.json` from `/opt/plamotrack/.agents/deployment-gate/keycloak/`.
  - Spike secrets remain in `~/.plamotrack-gate/spike-280/` for a rerun; `probe.py prepare` rebuilds the spike from scratch.
  - Carried:
    - The unfiled IPv6 `POSTGRES_HOST` defect (`_assemble_database_url` in `app/config.py`).
    - #278 is open for the owner's skill-zip check.
    - The LXC is a v0.5.2 release install.
    - Merged branches still on origin: `claude/plamotrack-cloud-setup-jgjfo0`, `fix/294-upstream-resource`, `claude/practical-heisenberg-fminub`.
- **Next:**
  1. #279: two edge probes, a header-echo image on Railway's trial and a Render free service. They check the edge's source addresses, `X-Forwarded-For`, the resolver and the health-check `Host`. Then #281's packaging, which now includes whether to bundle Pocket ID, then one proof deployment.
  2. #282's VPS path can build on the Pocket ID recipe: findings §4–§5 and §8.
  3. At the next release: work through `.agents/next-release.md`, the Pocket ID page included.
  4. Carried:
     - The IPv6 defect.
     - Posting the rehearsal on #285.
     - Untested: the release-to-release update, and the Windows commands in Git Bash.
     - Cloud-feasible candidates: #124, #125, #268, #238, and the importer bugs #110, #116, #134 and #137.

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
