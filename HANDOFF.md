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

## 2026-10-02 — Claude Code (Opus 5.5) — #305 MERGED as `8ba9c6e` (PR #310): the importer holds a value to its column's range; #306 fixed on the docs site; #309 filed

- **Done:**
  - **#306** closed by [plamotrack-docs#8](https://github.com/DeusMaximus/plamotrack-docs/pull/8), merged as `bb30824`.
    - The backups page no longer says an archive "does not preserve ids". The import page now says a restore into a new instance keeps them.
    - Checked first against `v0.5.2-alpha`, in a worktree: the golden archive restored into an empty instance kept all 35 ids.
    - The merge sentence names only retailers, catalog items and orders. Kits match by id alone, so "matching records" would have overclaimed.
  - **[PR #310](https://github.com/DeusMaximus/plamotrack/pull/310)** squash-merged as **`8ba9c6e`**, pinned to the reviewed head `96a8ff0`; #305 is closed.
    - Reproduced on `main` first. 11 range CHECKs previewed clean and then failed the apply with a 500. `shipping_cost_minor` and `low_stock_threshold`, which have no CHECK, stored negative values.
    - The fix:
      - `ColumnSpec.minimum` / `maximum` on 12 columns;
      - `RATING_MIN` / `RATING_MAX` in `services/numeric.py`, read by `schemas.numeric.Rating` too;
      - `_check_ranges` after money scaling, quoting the cell as written (header, alias included, and text);
      - codes `import.cell_below_minimum` and `import.cell_above_maximum`.
    - `tests/test_import_ranges.py`, 63 cases:
      - CHECKs, request schemas and declarations agree, and the CHECK walk is total;
      - every bound one step out, in merge and `replace_all`;
      - the bound itself imports;
      - update rows, the alias header, the starter sheet.
    - The `305-` mutants: 10/10 killed. Full suite at `f28eb28`: 3060 passed, 1 xfailed.
    - Greptile: 4/5 with two P2s (the source cell; the audit skipping unknown CHECK forms), both taken in `96a8ff0`; round 2 5/5. CI green.
    - `.agents/next-release.md` has the entry; it owes the docs site and `docs/import-export.md` a line on ranges.
  - **Filed [#309](https://github.com/DeusMaximus/plamotrack/issues/309)** (`enhancement`): CHECKs for `orders.shipping_cost_minor` and `consumables.low_stock_threshold`. The migration must clear negatives an older import may have stored.
- **Decisions (the owner's, 2026-10-01/02):**
  - `docs/import-export.md` was left for the release under the published-release rule; the owner did not object. Before that rule, PRs edited it directly.
  - Greptile reviews; the PRs squash-merge pinned to the reviewed head.
- **State:**
  - **Unreleased on `main`:** #294, #289, #247, #302 (#299, #300, #301) and #310 (#305); see `.agents/next-release.md`. #303 (PR #308) is test-only and owes nothing. The release also owes the Pocket ID docs page. #300 remains the most exposed: v0.5.2-alpha's `migrate` stops on a punctuated `POSTGRES_PASSWORD`.
  - Merged branches left on origin: `feat/303-golden-archive`, `fix/305-import-range-checks`, `fix/archive-keeps-ids` (docs repo), plus the three older ones.
  - **Carried:**
    - **Owner:** allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access; delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
- **Next:**
  1. **#307**, the shared scenario fixtures: design the JSON format first (starting rows, an operation, an expected state or a refusal with `code` and `params`). Reuse `tests/fixtures/golden/seed.py`'s deterministic ids. Document the format in `.agents/testing-and-review.md`.
  2. **#304**, import on a phone: the owner's decisions on modes and the 390 px preview, then mockups, before code.
  3. #309 when convenient: a migration plus a migration-data test.
  4. Carried:
     - #279's edge probes, then #281's packaging; #282's VPS path;
     - at the next release, work through `.agents/next-release.md`;
     - cloud candidates: #124, #125, #268, #238, #110, #116, #134 and #137;
     - posting the rehearsal on #285.

## 2026-10-01 — Claude Code (Opus 5.5) — #303 MERGED as `e5ad6cc` (PR #308): a golden archive pins the CSV contract; #303–#307 triaged

- **Done:**
  - **Triage of #303–#307**, the plamotrack-ios follow-ups, in this order:
    - #303, the golden fixture (in review, below);
    - #306, the docs-site ids sentence: a docs-repo PR, and v0.5.2 already preserves ids, so it does not wait for a release;
    - #305, the import range checks;
    - #307, the scenario fixtures, which reuse #303's seed;
    - #304, import on a phone, which needs the owner's UI decisions first.
    - Nothing was posted on the issues.
  - **[PR #308](https://github.com/DeusMaximus/plamotrack/pull/308)** squash-merged as **`e5ad6cc`**, pinned to the reviewed head `c20fad2`; #303 is closed.
    - The fixture: `backend/tests/fixtures/golden/archive/`, members committed as files. It is an export of an invented collection that `tests/fixtures/golden/seed.py` builds through REST.
    - The tests: `tests/test_golden_archive.py`, 49 of them, with literal headers, member order and manifest keys, plus the byte, cell and amount rules and three round trips.
    - Regenerate with `GOLDEN_REGENERATE=1 uv run pytest tests/test_golden_archive.py -k reproduces`.
    - **Found and fixed:**
      - `.gitattributes`' `eol=lf` would have rewritten the fixture's CRLF on `git add`; the fixture folder is now `-text`.
      - `upgrade_applications` exported with no tiebreak; it now sorts by `(applied_at, id)`.
    - The `303-` mutants: 10/10 killed. 303-7 survived the first run (the manifest's formatting was never compared), and the comparison was fixed. 303-10 came from review.
    - Full backend suite at `f130461`: 2924 passed, 1 xfailed.
    - Docs: design §12.1 (the contract) and `.agents/testing-and-review.md` → "The golden archive".
    - Merging `main` (#302) conflicted in `mutation_test.py`. Both case sets are kept, 678 labels, every anchor matches once; the three affected suites pass (129).
- **Decisions (the owner's, 2026-10-01):**
  - **Row order is stable, not meaningful.** The importer never reads it. Name order follows the database's collation, so the fixture uses names every collation sorts alike, and a test holds that. `COLLATE "C"` was declined.
  - **Greptile** reviews #308.
  - Also in the PR body: the manifest's `schema_version`, `app_version` and `exported_at` are excluded from the pin, and `README.txt` is regenerable prose, not contract.
- **State:**
  - **Review:** Greptile round 1 at `f130461` scored 4/5 with three P2s, all taken in `c20fad2`:
    - the export's `schema_version`, `app_version` and `exported_at` are now checked before they are excluded from the byte comparison (new mutant 303-10);
    - the second import is now applied, not only previewed;
    - the harness's refusal message names `.gitattributes`.
    - Round 2 at `c20fad2` scored 5/5 with no findings. CI passed: Backend, Frontend, Integration.
  - #303 needs no `.agents/next-release.md` entry, because nothing a user sees changes.
  - The merged branch `feat/303-golden-archive` is left on origin, as the others are.
  - **Carried from the #302 entry:**
    - **Unreleased on `main`:** #294, #289, #247, and #302 (#299, #300, #301); see `.agents/next-release.md`. The next release also owes the Pocket ID docs page. #300 is the most exposed: v0.5.2-alpha's `migrate` stops for a `POSTGRES_PASSWORD` holding anything but letters, digits and `- _ . ~`.
    - **Owner:**
      - allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access;
      - delete the Claude.ai "Testing" connector.
    - **testhost** is in the gate's state. Don't recreate its Keycloak container: a new one changes `sub`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
    - Merged branches still on origin: `claude/plamotrack-cloud-setup-jgjfo0`, `fix/294-upstream-resource`, `claude/practical-heisenberg-fminub`.
- **Next:**
  1. plamotrack-ios can copy `backend/tests/fixtures/golden/archive/` from `main` now.
  2. #306 in `plamotrack-docs`: confirm against `v0.5.2-alpha` that a restore into an empty instance keeps ids, then fix the sentence.
  3. #305:
     - reproduce first (`rating=7`, `quantity_on_hand=-2`, preview then apply);
     - list the range CHECKs from the models' metadata, not from the issue's list: `low_stock_threshold` has no CHECK, while `quantity > 0`, `quantity_used > 0` and `unit_cost_reference_minor >= 0` are missing from the issue;
     - a test that fails on any range CHECK on a portable table that the preview doesn't diagnose.
  4. #307: design the scenario fixture format, reusing #303's seed; then #304, starting with the owner's decisions and mockups.
  5. Carried:
     - #279's edge probes, then #281's packaging; #282's VPS path;
     - at the next release, work through `.agents/next-release.md`;
     - cloud candidates: #124, #125, #268, #238, #110, #116, #134 and #137;
     - posting the rehearsal on #285.

## 2026-09-25 — Claude Code (Opus 5.5) — #299, #300, #301 MERGED as `b7f8a47` (PR #302): an IPv6 `POSTGRES_HOST`, a `%` in the URL alembic reads, and secrets echoed by a settings refusal

- **Done:**
  - Filed three bugs, each reproduced on `main` at `23e4b0e`:
    - [#299](https://github.com/DeusMaximus/plamotrack/issues/299): the IPv6 `POSTGRES_HOST` carried from the last entry;
    - [#300](https://github.com/DeusMaximus/plamotrack/issues/300): alembic's ConfigParser refuses any `%`, so a punctuated `POSTGRES_PASSWORD` stops the **published** `migrate` service;
    - [#301](https://github.com/DeusMaximus/plamotrack/issues/301): a `Settings` refusal printed `input_value=`, which held the head and tail of `.env`'s secrets, into the container log.
  - [PR #302](https://github.com/DeusMaximus/plamotrack/pull/302) squash-merged as **`b7f8a47`**, pinned to the reviewed head `c927060`. #299, #300 and #301 are closed.
    - `config.py` renders the URL with `URL.create`, unwraps `[::1]`, and refuses a colon outside an IPv6 literal (only when assembling). It also sets `hide_input_in_errors=True`.
    - `alembic/env.py` doubles `%`.
    - `asyncpg_dsn` writes a host's `%` as `%25`.
  - Tests:
    - `tests/test_database_url.py` (76): 46 red / 30 green on unfixed `main`.
    - `tests/test_settings_errors.py` (4): 4 red.
    - The `dsn-` mutation set: 10/10 killed, and both files are in `TEST_FILES`.
    - Backend: 2955 passed, 1 xfailed (predates the branch).
    - A one-off credential fuzz, 28,128 pairs through all four readers, found 0 regressions. The script is in the PR body.
  - `.agents/next-release.md` has the entry.
- **Decisions (the owner's, 2026-09-25):**
  - **A zone id is raw in the SQLAlchemy URL, `%25` only for asyncpg's parser**, not RFC 6874 everywhere as the task first said. SQLAlchemy never decodes a host, and the resolver refuses `fe80::1%25lo`.
  - **#300 and #301 ride in the same PR** as separate issues: same class, and each is needed for #299's fix to be complete and not leak.
  - **Session bookkeeping commits straight to `main`**, a cloud session included: hand-off entries, their rotation, the merge record. This is the owner's standing go-ahead (2026-09-25), matching `AGENTS.md` → Git conventions.
- **State:**
  - **Reviews:**
    - Greptile scored it 5/5 with no findings.
    - GLM 5.3's round 1 at `dd6f3df` was **NO-GO**, with a P2 and three P3s, answered on the thread.
    - Round 2 at `b3aa1e9` was **GO**. Its one finding (5, a P3 record clause) was taken in the PR body.
    - P2 fixed: the harness's first dsn-5 sent the mutant session to the dev database. Re-anchored, then made judge-only at `b3aa1e9`, because the re-anchor still redirected under an IPv6 `.env` host. Proven with a canary row; the rule is in testing-and-review, the case in lessons.md.
    - P3 finding 2: the finding was right, the remedy was declined with a counterexample. The state store reads the engine's host; decoding `%25` first breaks a real zone `%25`.
    - P3s 3 and 4: a tripwire comment in `config.py`, and record corrections.
  - **This entry reached `main` with the squash; the merge record was committed on `main` directly.** `main` got the #280 entry below first, so `main` was merged into the branch: both entries kept, and the #294 entry rotated out.
  - **Proven in Compose, not with the shipped image:** Docker runs in the cloud session once `dockerd` is started (`.agents/testing-and-review.md` → Docker in a cloud session). The `migrate` service ran with its image swapped for the Python base plus the locked dependencies, the source mounted, and a punctuated `POSTGRES_PASSWORD` in `.env`.
    - `main` failed with #300's interpolation error, and its log printed the URL and password.
    - The branch migrated to head.
    - With an OIDC misconfiguration, `main`'s log printed the signing key's tail (#301); the branch's printed none.
    - The API image itself can't be built there: the `uv` blob on `ghcr.io` is refused by the egress policy.
  - **Not testable in the cloud session:** a live IPv6 connection (the container's kernel has no IPv6 stack), and the shipped image (the ghcr blob host is refused). GLM round 2 closed both on the owner's Mac.
    - Postgres on `[::1]`: the engine and the state store's pool both connected.
    - The packaged stack built as written: `migrate` ran online with a punctuated password, and the OIDC refusal printed no secret.
    - Still open: a pool to a zone-id host, which needs Linux.
  - **Unreleased on `main`:** #294, #289, #247, and #302 (#299, #300, #301); see `.agents/next-release.md`. It also owes the Pocket ID docs page. #300 is the most exposed: v0.5.2-alpha's `migrate` stops for a `POSTGRES_PASSWORD` holding anything but letters, digits and `- _ . ~` until the next release.
  - **Carried from the 2026-09-25 #280 entry:**
    - #280 is decided and closed: Pocket ID is an optional supported provider, documented from the release that ships #294.
    - testhost is back in the gate's state: `probe.py teardown` ran, and the gate's stack (v0.5.2) and the same Keycloak container are up.
    - **Owner:** delete the Claude.ai "Testing" connector; the spike it pointed at is gone.
    - Don't recreate Keycloak's container on testhost: a new one changes `sub`, and the gate's collection then needs `recovery rebind-oidc`.
    - #278 is open for the owner's skill-zip check. The LXC is a v0.5.2 release install.
    - Merged branches still on origin: `claude/plamotrack-cloud-setup-jgjfo0`, `fix/294-upstream-resource`, `claude/practical-heisenberg-fminub`.
- **Next:**
  1. Owner: allow `pkg-containers.githubusercontent.com` in the cloud environment's Network access (said 25/09/2026). That is what lets a cloud session build the API image; the recipe is in `.agents/testing-and-review.md` → Docker in a cloud session.
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
