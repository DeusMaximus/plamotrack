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

## 2026-09-08 — Codex (GPT-6) — M6.1 FastMCP 4 compatibility spike completed locally

- **Done:** Fable's attached brief on `spike/m61-fastmcp4`, forked from `main` at
  `925c56d`. Report: `.agents/spikes/2026-09-m61-fastmcp4.md` **on that branch**.
  Commits `0ff1633` (FastMCP 4.0.3 / SDK 2.2.0 lock), `0fc80ca` (httpx must be a
  runtime dependency), `43e0d82` (mechanical test adaptations), `1c41ae6` (16 era
  probes), `bbb58e7` (report). No PR, push, GitHub comment or deployment.
- **Findings:** the production FastMCP 4 upstream OAuth client lacks `revoke_token`:
  exchange/refresh and local revocation work, but provider revocation is never sent;
  the old httpx test factory masks it. Custom discovery omits the issuer-response
  flag. CIMD clients now use the bounded memory cache rather than persistent client
  rows, invalidating five lifecycle assertions; a DCR request for private_key_jwt
  is refused before our public-client canonicalization. No runtime app/ingress code
  was edited. Modern and legacy tools work; issuer identity stays byte-identical.
- **State:** baseline **2655 passed**; unchanged upgraded suite **2644 passed / 11
  failed**. Final full suite at `1c41ae6`: **2661 passed / 10 failed**. Same era file
  on untouched 3.4.5: **11 red / 5 green**; on 4.0.3: **4 red / 12 green**. Four reds are the
  brief's pre-existing envelope mismatch (empty anonymous challenge; invalid_token
  rather than REST auth.bearer_invalid), intentionally retained for the decision.
  Packaged local matrix **186 passed / 0 failed**; real 4.x auto/legacy and frozen
  3.x clients work on both `/mcp` spellings. No optional long hold, packaged OIDC,
  remote gate or browser-client/conformance run. Ruff and frontend build pass.
- **Cleanup:** temporary main worktree removed; isolated Compose stack and its own
  volume removed; normal dev DB overlay healthy. Unrelated Keycloak left alone.
  Evidence logs/scripts are outside git at
  `/private/tmp/plamotrack-m61-fastmcp4-20260908`. Final checkout is the spike;
  `main` gains only this handoff and verbatim rotation, no lock or code changes.
- **Next:** preparation PR for independent HTTP/revocation coupling, then an atomic
  bump plus OAuth/era compatibility PR. Proposed M6.1 issues and acceptance matrix
  are in the report, not filed. Do not call this branch a finished migration.
  v0.3.0-alpha is the existing release; the prior handoff's LXC upgrade and open
  #223–#227/#230 follow-ups were not investigated or changed by this spike.

## 2026-09-08 — Claude Code (Fable 5.1) — **v0.3.0-alpha RELEASED** (M6 complete): PR #220 → `c46b652`, tag pushed, prerelease published, #30 + #195 closed, milestone M6 closed; next the LXC upgrade

- **Done:** the whole of #195's tail on the owner's word ("do the lot"): **PR #220 squash-merged →
  `c46b652`** (closes #195); annotated tag `v0.3.0-alpha — the instance has an owner` on it,
  pushed; `gh release create --prerelease --verify-tag` with the notes —
  https://github.com/DeusMaximus/plamotrack/releases/tag/v0.3.0-alpha ; #30 closed with the
  criterion-by-criterion evidence comment; #195 closed with the record; **milestone M6 closed**
  (20 closed, 0 open). The notes lead with the upgrade path (unclaimed on upgrade, back up,
  the setup token, a PAT for every MCP client), then §5.5's client-visible changes, the
  features, the scan's four bounds (#221) and the healthcheck fix (#228), the four
  migrations and what each downgrade discards, the three observed gate blocks, the known
  limitations (#206, #214's residual, #227's boundary, one worker, mode P, `PUBLIC_BASE_URL`,
  M6.1). Earlier today: #222 merged `94fd2f9` (the scan's mediums, three Codex rounds); #229
  merged `37ef344` (the db healthcheck over TCP, found by the gate's restore phase); the release
  branch rebased twice; the gate rerun green on the final tree `c270127`.
- **Decisions:** (1) **The tagged tree differs from the gated tree by `HANDOFF.md` alone** — the
  hand-off I committed on `main` between the rebase and the merge; no image builds from it
  (`backend/` and `frontend/` are the build contexts), so every byte the stack runs is the
  gated byte; stated in the notes' gate paragraph. **Lesson for the next release: hold the
  hand-off commit until after the release PR merges, or gate the merge commit** — a tree hash
  argument should not need a caveat. (2) The tunnel phase was rerun alone after the
  workstation's temporary IPv6 rotated mid-run (nginx attributed correctly, to the new
  address); the first rerun died on a Cloudflare reset mid-hold → **#230** (harness gap: a
  peer reset should be a failed row, not a crash; not a blocker). (3) #227 filed as the
  product question (a device capability surviving a normal logout) rather than folded in.
- **State:** `main` = `c46b652` + this entry; tag `v0.3.0-alpha` = `c46b652`. CI on `main`
  triggered by the merge — check it. Branches `fix/scan-0.3.0-availability`,
  `fix/db-healthcheck-init-race`, `release/0.3.0` deleted (remote). testhost left in mode R
  (OIDC mode, Keycloak up); gate state dirs under `~/.plamotrack-gate/` (run #3 current, two
  older beside it). Dev overlay up; tree clean. **The LXC still runs 0.2.10 — the real
  collection; it has not been touched.** Open from the scan: #223–#226 (lows), #227, #230.
- **Next:** **the LXC upgrade** — back up first (dump + `.env`), set `ALLOWED_HOSTS` if not
  already, `git pull` to `v0.3.0-alpha`, `up -d --build --wait`, claim with the setup token
  from `docker compose logs api`, mint PATs and relink every MCP client, refresh the personal
  Gunpla skill to the deployed version (memory: it deliberately lags main). Then M6.1 /
  M6.5 per the roadmap; the lows #223–#226 whenever.

## 2026-09-08 — Claude Code (Fable 5.1) — #195 held behind the owner's security scan: the four mediums fixed as #221 → **PR #222; Codex round 1 NO-GO (f1, f2 P2; f3 P3) fixed at `6395a5d`; round 2 NO-GO (f4 P3, docs) fixed at `b4d9aa4`; round 3 NO-GO (f5 P3, docs) fixed at `ec171fd`; PR #222 MERGED `94fd2f9`; the gate rerun found #228 → PR #229 MERGED `37ef344`; release branch at `511ea90` (tree `c270127`), **gate GREEN on it, CI green — awaiting the owner's go: merge #220 → tag → release**; release PR #220 waits (rebase + gate rerun after #222 merges)

- **Done:** (1) **#195 run to the edge of the outward steps** (2026-09-07): `release/0.3.0`
  at `ed48038` (tree `92015d9`) → **PR #220** (bump 0.3.0, design §5 flipped to Built,
  operations *Upgrading to 0.3.0*, AGENTS roadmap 6 struck), CI green; the whole release
  gate run on that tree — local packaged stack under Compose project `plamotrack-release`
  (fresh volume; the dev volume was kept), `/api/meta` and MCP `serverInfo` 0.3.0, manifest
  0.3.0/d5e9362140ea, matrix 0 failing, T10 clean; `deployment_gate.py --phase all` + tunnel
  on testhost after a fresh-install reset — GREEN, exit 0, every phase (results comment on
  #220). Notes, #30 and #195 closing comments drafted. (2) **The owner then ran a Codex
  Security scan on `ed48038`**: NO-GO for Internet exposure until four medium availability
  findings are fixed. Filed **#221**; fixed on `fix/scan-0.3.0-availability` → **PR #222**
  (four commits, one per item): item 4 `FailureBudgets` — a ladder per (action, client
  address) with decay + an instance-wide verification bucket (`app/auth/budget.py`,
  `services/auth.py`, `services/oidc.py`, `routers/auth.py`); item 3 `RefusalBudget` on
  the audit recorder + `AUDIT_RETENTION_DAYS` (closes #210); item 1 `RoutePolicy.max_body_bytes`
  + one bounded reader (`app/auth/body.py`) in the pre-routing gate and the three protocol
  guards (+ `BoundedBody` on consent), nginx exact locations generated as a second region
  of `render_ingress.py`, 413 envelope `ingress.body_too_large`, `MAX_FORM_FIELDS`; item 2
  `ClientRecords` on FastMCP's client collection (24 h lifetime until `keep` at issuance —
  a permanent record stays permanent through FastMCP's refresh writes — cap 1024, quota
  20/h/address, `count_live`/`cull_expired` on the store, `cull_if_due` from the registration
  guard and `authorize`, FastMCP's CIMD cache a `BoundedCache`), 503
  `auth.mcp_registrations_full`. Docs: design §5.6 rows + T8 + §5.9 item 11 (the calls),
  operations, AGENTS rule 14, `.env.example`, the CI row in testing-and-review. Verified:
  full backend **2641 passed**; CI Backend/Frontend/Integration green at `4b35c73`
  (Integration = the matrix's new `body_budget_rows`/`origin_flood_rows` through the
  packaged nginx + the new refusal-row count step); 25 `scan-` mutants in the tracked
  harness **all killed**; six behavioural control probes **6 red on main / 6 green** on
  the branch (file kept out of the tree; verbatim in the brief). Four lows filed, not
  blockers: #223 CSV formula syntax, #224 OIDC endpoint validation, #225 MCP untrusted-text
  marking, #226 HSTS. The release notes draft gained a scan section and lost #210.
- **Decisions:** 0.3.0 not 0.2.11 (every caller's contract changed). The seven deliberate
  calls are on PR #222 (the verification bucket can delay the owner by seconds under a
  distributed flood; the suppressed count is written with a later window's first recorded
  refusal; the registration cap is checked before the write, a race overshoots by nginx's
  burst; the constants are constants; nginx's 413 has no `params.limit`; consent GET
  unbounded; a CIMD lookup at the cap is an unknown client). Reviewer: **Codex** (M6
  security work) — brief printed in the 2026-09-08 session chat, scratchpad copy.
- **Round 1 (Codex, GPT-6) — NO-GO, fixed at `6395a5d`:** f1 (P2) the setup token and the OIDC start charged
  the verification bucket for a cheap comparison, and the general bucket alone let a stream of fresh
  addresses hold the owner out → `refuse_throttled(verification=False)` on both cheap paths, and a login
  presenting any session cookie the instance ever stored (rows are never deleted) is verified from a
  reserved bucket of 10/min (`FailureBudgets.known`), falling back to the general one; the
  new-browser-under-flood case is documented as the ingress's boundary (operations 429 paragraph,
  design §5.6/§5.9 item 11). f2 (P2) `/mcp/token` and `/mcp/revoke` materialise CIMD clients through
  `get_client` with no cull reached → the client-collection cull now lives in `ClientRecords.put` on a
  new key (`cull_expired(collection)`). f3 (P3) a disconnect mid-body was replayed as a whole body →
  `read_bounded` raises `Disconnected`, the gate and the three guards answer nothing. Tests for each;
  scan-26…31 added (31/31 killed); full backend **2653**; response posted; coverage record updated.
- **Round 2 (Codex) — NO-GO on f4 (P3, documentation), fixed at `b4d9aa4`:** the runbook promised the
  reserved login path to "the browser you signed in with"; a normal logout clears that cookie. The
  three documents now state the contract as built (a recognised cookie — idled out or host-revoked —
  plus an open ladder and capacity; a logged-out / expired / cleared / restored-past-row browser
  competes, the ingress is the boundary; a shared address shares a ladder); a cookie-jar lifecycle
  test; the flood tests on small buckets (they had put the Backend CI job past its 15-min cap,
  cancelled at `6395a5d` — now 20 with the reason in the workflow); **#227** filed for the device
  capability as a product contract. Round 2 explicitly ran no replays, control or mutants; re-run
  at `b4d9aa4`: 31/31 killed, control 6 red on `c527176` / 6 green, full backend **2654**.
- **Round 3 (Codex) — NO-GO on f5 (P3, documentation), fixed at `ec171fd`:** the runbook said "at most
  thirty passwords a minute in total"; the policy is two additive token buckets (30 + 10, continuous
  refill). The 429 paragraph is rewritten as one contract (ladder → reserved bucket → general bucket,
  capacity + refill, every cookie state, a restore's present-but-unrecognised cookie); budget comments
  matched; an accounting test pins 30 + 10, the 41st refused, both refill rates; lesson filed ("A
  runbook paragraph is one promise"). Rounds 2 and 3 both explicitly ran neither the control nor the
  mutants; author's record at `ec171fd`: 31/31 killed, full backend **2655**, CI green (Backend 12m49s).
- **PR #222 MERGED → `94fd2f9`** (squash, 2026-09-08; #221 and #210 closed) after the owner ran the
  control (6 red) and the mutants (31 killed) himself. `release/0.3.0` rebased onto it → `9f2c52a`
  (tree `36b2749`), PR #220 updated; the design.md conflicts resolved (item 10's note before item
  11; dates to 08/09). **Gate rerun on that tree: local step 4 green; the deployment gate stopped
  in T13** — the runbook's `pg_restore` after `down -v; up -d db --wait` met "the database system
  is shutting down": the socket healthcheck is satisfied by the image's temporary init server
  (`listen_addresses=''`). Filed **#228**, fixed on `fix/db-healthcheck-init-race` → **PR #229**
  (TCP probe in compose and CI's service container, a runbook sentence; verified 3× on a fresh
  volume). The lockout/local/oidc phases were green before the stop (matrices 179 and 182 ok rows).
- **PR #229 MERGED → `37ef344`** (#228 closed) on the owner's word; `release/0.3.0` rebased again →
  **`511ea90`, tree `c270127`**, PR #220 updated, CI green (Backend 12m50s). **Gate run #3 on that tree
  GREEN**: local step 4 green; `--phase all` green through T13 on the fixed healthcheck (local matrix
  177 ok, oidc 181 ok, three restores); the tunnel rows failed only because the workstation's temporary
  IPv6 rotated mid-run — the tunnel phase rerun alone passed (attribution to the current address,
  both spellings held 130 s+, matrix 87 ok, audit row = visitor); the first tunnel rerun crashed on a
  peer reset mid-hold → **#230** filed (harness gap, not a blocker). Results comment on #220; the
  notes draft (scratchpad `release-notes-v0.3.0-alpha.md`) carries the three observed blocks, the
  #221 section, the #228 line, and no longer lists #210.
- **State:** `main` = `37ef344` + these entries. PR #220 open at `511ea90`; **no tag exists**. testhost
  left in mode R after the tunnel phase's restore (OIDC mode, Keycloak up). Gate state dir
  `~/.plamotrack-gate/testhost…/` holds run #3 (`…release-run-1`, `…release-run-2-stopped` beside it). **Recommendation given (2026-09-08): stop the Codex rounds** — the NO-GOs
  are the reviewer's own unrun verification, not defects — and merge once the owner has run the two
  mechanical checks himself (the control file in a `c527176` worktree → 6 red; `mutation_test.py -k
  scan-` → 31 killed). A round-4 brief exists (scratchpad `brief-222-r4.md`) if a reviewer's name is
  wanted on those two items; GLM would do for that. PR #220
  open at `ed48038`, **stale once #222 merges** (rebase; the only expected conflict is
  design.md's "Last revised" line — keep 08/09; §5.9 item 11 and the §5.6 rows are #222's).
  No tag exists. testhost left in the gate's end state (OIDC mode, Keycloak up); a rerun
  needs the fresh-install reset (`down -v`, `.env` from `.env.example`, `git archive` the
  tree) — the memory file `plamotrack-194-deployment-gate-setup` has the exact steps. Gate
  state dir `~/.plamotrack-gate/testhost…/` (the #194 run's moved aside). Dev overlay up;
  tree clean; LXC untouched.
- **Next:** owner merges #220 (squash) → verify the merge commit's tree is `c270127` → tag `v0.3.0-alpha — the instance has an owner` on the
  merge commit → push tag → `gh release create --prerelease --verify-tag` with the notes
  (scratchpad `release-notes-v0.3.0-alpha.md`, the gate block replaced by the rerun's) →
  post the #30/#195 comments, close both, close the M6 milestone. Then the LXC upgrade.

## 2026-09-07 — Claude Code (Fable 5.1) — #213 closed (already fixed); #214 fixed on `fix/214-rebind-purges-mcp-oauth-state` → PR #219 reviewed GO + 1 P3, fixed, **MERGED → `b333ebf`**; #206 closed / #210 deferred; #195 next

- **Done:** (1) **#213 closed** as already fixed: rounds 2–3 of #212 keyed both refresh
  paths on the grant id (`exchange_refresh_token` and `_try_transparent_refresh` both take
  `_one_transition(…, upstream_token_id)`); the comment on the issue points at the two lines.
  What is not on record is a rotating-provider test — test coverage, not a defect. (2) **#214
  fixed** on the branch, **PR #219**: `recovery rebind-oidc` purges the four grant collections
  of `mcp_oauth_state` in its own transaction under every grant's advisory lock, records
  `auth.mcp_grant_revoked` per grant (`ended_by=rebind`), and the command then asks the
  provider, best effort, to revoke what the records held (`revoke_purged_grants_upstream` →
  `OidcProvider.revoke_token`, after the commit). New leaf `app/auth/mcp_oauth_state.py`
  holds the collection names, `GRANT_COLLECTIONS`, the lock key and the store — the proxy
  imports the service, so the service could not import the proxy. (3) **PR #219 reviewed**
  at `0c76771` by Cursor Grok 4.6 — picked in T3 Chat **by mistake** instead of GLM; Cursor
  is available until **2026-09-15** and then gone, not back — **GO + 1 P3**: an unexchanged
  authorization code (in the purge set *because* it holds the provider's tokens) was deleted
  unread, its tokens never revoked upstream. **Fixed at `cc51a01`**: code records read under
  `idp_tokens` (the review named the top-level read as the wrong remedy), revoked at the
  provider, `codes_purged` on the `RECOVERY_RUN` row and in the output; no grant row, no lock
  for a code (deliberate call 7). Round-1 control at `0c76771` red on the upstream list;
  rbp-17/18/19, **19/19 killed**; full backend **2598** at `cc51a01`. `b5ff8ed` = roster/brief
  note on Cursor. Response + coverage record posted on the PR. Lesson filed: "The
  classification you wrote is a promise the same branch keeps". Docs: operations, design
  §5.6/§5.9, AGENTS 13.
- **Decisions:** #206 **closed not-planned** and #210 **deferred** past the M6 release (owner's
  call, 2026-09-07): #206 discloses only the Streamable HTTP verb set on a path called `/mcp`;
  #210 needs measurement, a policy and a packaged-stack proof, on an Origin-only flood behind
  nginx at zero adoption, with `prune-audit` already the retention answer — one known-limitation
  line each in the release notes. #214's residual (deliberate call 1 on the PR): a grant
  *issued* concurrently with the rebind can leave one record, refused at its next use and
  purged by the next rebind. Cursor's #219 round is recorded in `.agents/testing-and-review.md`
  as history, with a footer in `review-brief.md` for the window to the 15th; GLM stays default.
- **State:** **PR #219 squash-merged → `b333ebf`** (owner's call, 2026-09-07), #214 closed,
  branch deleted; `main` = `b333ebf` + these hand-offs, pushed. No fold-in owed — the 19
  `rbp-` cases are tracked (harness now 589 cases / 51 files). Tree clean. Control worktrees
  removed. testhost (LXC 117) untouched, still claimed local, Keycloak fixture up.
- **Next: #195**, as the previous entry lays out — gate step 4b (`deployment_gate.py --phase
  all` + `--tunnel-*`) against the **tagged** commit on testhost, the bump (three files via
  PR), tag, `--prerelease`, #30 closes with it; the notes carry #206/#210 as deferred and
  lead with the §5.5 client-visible changes. Then the LXC upgrade (back up first;
  `ALLOWED_HOSTS`; relink MCP clients; refresh the personal Gunpla skill).

## 2026-09-07 — Claude Code (Opus 4.8) — #194 (M6-9) MERGED: PR #218 squash → `b32ffe2` after two Codex rounds (NO-GO→GO); #195 next

- **Done:** #194 (M6-9, reference TLS deployment + the T12/T13 gate + the ops/README
  rewrite) merged to `main` as `b32ffe2`; issue closed. Two Daybreak Blue (Codex GPT 5.6)
  rounds: round 1 **NO-GO** (2×P2, 2×P3) → round 2 **GO** (4×P3), all fixed. Final head on
  the branch was `807fb26`. What shipped: nginx bare `/mcp` carries the family's settings;
  a loopback `TRUSTED_PROXIES` entry also trusts the Docker gateway; `ingress_matrix.py` +
  HTTPS/`--behind-proxy`/`--credential-file`/`--hold-stream`/`--skip-rate-limits`;
  `backend/deployment_gate.py` (the T12/T13 driver); `deploy/caddy/` reference + systemd
  drop-in; `.agents/deployment-gate/` fixtures; `docs/operations.md` rebuilt around the four
  ways to run it + the two-part backup set; README/`.env.example`/design §5.4-10/AGENTS
  rule 12/testing-and-review step 4b.
- **Review fixes (all with regressions):** P2 the Cloudflare token needs Zone:DNS:Edit **and**
  Zone:Zone:Read (docs); P2 the gate leaked secrets to ssh argv/results → `env_set` sends
  values on stdin, `run` has a redacting label, docs use `sudoedit`; P3 tunnel required an
  exact `--tunnel-visitor` on nginx `$remote_addr` **and** the `auth.token_minted` audit row;
  P3 T13 partial restores assert `refresh 401 invalid_client`; P3 the tunnel runbook names
  `--tunnel-visitor` (+ drift-guard test); P3 the systemd `systemctl edit --stdin` alt was
  wrong (sudoedit only); P3 `phase_local` reads `/api/auth/session` first (no swallowed ssh
  error as "already claimed"); P3 `mcp_link`/`mcp_verify` parse the SSE JSON-RPC result
  (`mcp_result`), not HTTP 200. Plus a pre-existing rate-check flake found re-verifying:
  `rate_limit_checks` now admits 404 for a non-canonical discovery spelling (nginx 404s it,
  rule 12; the limiter still keys on it) — only ever flaked in OIDC mode, masked by the
  limiter tripping first.
- **State:** `main` at `b32ffe2` + this hand-off; tree clean, nothing in flight. Gate proven
  GREEN end-to-end (`--phase all` + tunnel) on **testhost.internal.tlgnet.net** (LXC 117,
  10.1.1.129, VM04): Caddy 2.11.4 + cloudflare DNS module, Let's Encrypt DNS-01, both `/mcp`
  spellings held 130 s through the Cloudflare Tunnel `plamotest.gunp.la`, all three T13
  restores. **testhost is kept** (owner's call) — it is exactly what #195's release gate
  reuses; it is running, claimed in local mode, and its Keycloak fixture is up. Branch
  `feat/194-tls-deployment-gate` left in place. The `.agents/spikes/190/` Keycloak is a
  separate fixture from the gate's.
- **Next: #195, the M6 release.** The gate now includes `.agents/testing-and-review.md`
  step 4b — a release runs `deployment_gate.py --phase all` (with `--tunnel-*`) against the
  **tagged** commit on testhost and pastes its results block into the notes. Then the bump
  (three files via PR), tag, `--prerelease`; the open M6 P3s **#206/#210/#213/#214** need a
  defer-or-fix call before the tag, **#30** closes with the release. Only then the LXC
  upgrade (back up first; `ALLOWED_HOSTS`; relink MCP clients; refresh the personal Gunpla
  skill).
