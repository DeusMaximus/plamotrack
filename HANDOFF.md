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

## 2026-09-07 — Claude Code (Opus 4.8) — #194 (M6-9) built, gate GREEN on a real host, PR #218 OPEN

- **Done:** M6-9 whole, on `feat/194-tls-deployment-gate` (`d53282e`), **PR #218 open,
  awaiting review**. Closes #194. **nginx:** bare `location = /mcp` gains the family's
  settings (buffering off, 1 h timeouts, `Connection ""`, the two `X-Forwarded-*`) so both
  `/mcp` spellings are one family (§5.5 alias; Claude web posts to the bare one, #190) — the
  1 h timeouts are the family's, not a measured need (SDK pings every 15 s). The envsh
  renders a **loopback `TRUSTED_PROXIES` entry's `set_real_ip_from` plus the Docker gateway**
  (a host proxy reaches nginx from the gateway, not `127.0.0.1`; else every visitor keys the
  limits/audit on the gateway). **`ingress_matrix.py`:** HTTPS (`--ca-cert`), `--behind-proxy`,
  `--credential-file` (first signed-in OIDC-mode run), `--hold-stream` (raw socket, both
  spellings, max inter-byte gap), `--skip-rate-limits`, base-name-aware rows (loopback Origin
  → 403 off-loopback; the two OIDC rows mode-aware). CI local run unchanged (0 failing on the
  Mac packaged stack). **`backend/deployment_gate.py`** (new): the T12/T13 driver over ssh,
  secrets in `--state-dir` (0600, never printed). **Docs:** `operations.md` rebuilt around the
  four ways to run it (private net / own proxy / Cloudflare Tunnel / VPS+Caddy = reference),
  the four settings, the **two-part** backup set + three partial-restore outcomes; README,
  `.env.example`, `deploy/caddy/`, `.agents/deployment-gate/`, design §5.4/§5.6/§5.8/§8/§10,
  AGENTS rule 12, testing-and-review step 4b.
- **Gate run (real, LXC 117 `testhost.internal.tlgnet.net` 10.1.1.129):** Caddy 2.11.4 +
  cloudflare DNS module, Let's Encrypt via DNS-01 (split-horizon name issues fine). One clean
  `--phase all` + tunnel, **every phase 0 failing**. **Both `/mcp` spellings held 130 s through
  the Cloudflare Tunnel `plamotest.gunp.la`** (Jamie's route → 10.1.1.129:8080, connector LXC
  105 = 10.1.1.155) — past the 125 s cliff, 15 s ping, clean DELETE close; 75 s through Caddy.
  T13 all three restores as documented. Results block sent to Jamie + in the session scratch.
- **Findings folded into code (not caveated):** (a) `--hold-stream` header read tolerates a
  buffering CDN's delayed SSE headers; (b) `--skip-rate-limits` for the tunnel — a CDN's
  latency + URL normalisation make nginx's per-second/per-spelling limiter unobservable (it
  trips through Caddy + CI); (c) break-glass is its own phase (matrix leaves the login family
  throttled ~1 min); (d) OIDC rows mode-aware; (e) macOS `tar` `._*` broke Alembic on the host
  → README `COPYFILE_DISABLE=1`, host-prepare refuses the wrong token var name.
- **State:** on `main` this is the hand-off only; the feature is on the branch/PR, **not
  merged**. Lint + render clean; touched-file tests 309 pass; full backend 2544 passed before
  the last harness edits (T2 harness, not app code; CI Integration exercises it). `testhost`
  left running, claimed local; tear-down is Jamie's. The `.agents/spikes/190/` Keycloak is
  separate from the new gate's Keycloak fixture.
- **Next:** review PR #218 (roster — GLM default, Codex if high-stakes). Then **#195** (M6
  release): the gate now has step 4b, so a release runs `deployment_gate.py --phase all` against
  the tagged commit and pastes its block into the notes; bump/tag/prerelease; #206/#210/#213/#214
  need a defer-or-fix call, #30 closes with it. Then the LXC upgrade.

## 2026-09-07 — Claude Code (Fable 5.1) — #215 fixed (PR #216 → `a322f15`) and the #208 `aud-` set folded (PR #217 → `3344066`, 56/56 on the committed tree); both MERGED, no review; #194 next

- **Done:** (1) **#215** on `fix/215-ci-setup-token-argv` → **PR #216** (`040c613`): the
  Integration matrix step's three variable-valued options spelled attached
  (`--setup-token="$SETUP_TOKEN"`, `--token-out=…`, `--log-secrets-out=…`) with a comment
  above the step saying why; the procedure doc's hand-run instruction says the same.
  Proven against the real `ingress_matrix.main` parser with a leading-hyphen token
  (separate word: `SystemExit(2)`; attached: parsed). Backend/Frontend/Integration green.
  (2) **The `aud-` fold-in** on `chore/193-aud-mutants` → **PR #217** (`0cfdeb5`): 56 cases —
  aud-1…17 reconstructed from PR #208's prose descriptions against `bd40687` (aud-14 on the
  normalised snapshot), 18…58 verbatim from the record's two JSON blocks; four suites join
  `TEST_FILES` (`test_audit`, `test_audit_privacy`, `test_access_logging`,
  `test_deployment_hygiene`); the nginx template, `Dockerfile` and `ingress_matrix.py` join
  the clean-tree check. Harness **570 cases / 51 files** (procedure doc's count line
  re-derived). **56/56 RED on the committed tree** (`-k aud-`, ~8 min, tree clean after);
  first pass 55/56 — aud-23 GREEN on the record's selection (the id_token-rejected test
  asserts the row's detail, not its actor) → re-pointed at
  `the_owner_cancelling_at_the_provider_spends_the_transaction`, RED on replay.
- **Decisions:** aud-34/35 stay out — nothing in `tests/` reads the access-log format or
  `error_log /dev/null;`, so their only witness is the release gate's packaged log scan.
  aud-17/36, packaged-only in the record, fold on the four-families test's literal
  assertions (added by the P3 round). No full-harness run: the branch touches no emission
  site or anchored line; every anchor checked once (570/570), replacements compile, no
  `-k` prefix collision. No reviewer requested on either PR — owner's call (CI/process,
  not app code). Commit/push/PR for both was the owner's explicit choice this session.
- **State:** **both squash-merged 2026-09-07** on the owner's call — PR #216 → `a322f15`
  (#215 closed by the merge), PR #217 → `3344066` — with no review, matching the five
  prior fold-ins (#199/#201/#203/#207/#211, all unreviewed); CI green on both. `main` at
  `3344066` + this amended hand-off, tree clean, nothing uncommitted, **nothing in flight**.
  Branches `fix/215-ci-setup-token-argv` and `chore/193-aud-mutants` left in place.
  Dev `db` up; the Keycloak spike compose still up (`.agents/spikes/190/`, untracked —
  needed for the OIDC-mode release gate). The owner's **#194 work-in-progress is
  uncommitted on their MacBook**; they expect to redo it on this Mac — treat #194 as not
  started here. LXC untouched (**stays put until M6 is finished**).
- **Next:** (1) **#194** (M6-9: reference TLS deployment with Caddy + the operations/README
  rewrite) on a fresh branch — read the issue and design §5.4 first. (2) **#195**, the M6 release:
  the gate in `.agents/testing-and-review.md` — `ingress_matrix.py --mode oidc` against a
  packaged stack with the Keycloak spike, the register burst last — then bump via PR, tag,
  prerelease notes leading with the fail-closed upgrade path; the open M6 P3s
  **#206/#210/#213/#214** need a defer-or-fix call before the tag, #30 closes with the
  release. (3) Only then the LXC upgrade (back up first; `ALLOWED_HOSTS`; relink MCP
  clients; refresh the personal Gunpla skill).

## 2026-09-06 — Codex (GPT-6 Astra) — #208 post-merge GO; feature branch deleted

- **Done:** verified Daybreak's independent GO at `3f93b3c`, recorded in PR #208
  issuecomment-5558944536: P3-5/P3-6 resolved, no new P1–P3 findings, all ten calls
  accepted, no revert or corrective follow-up warranted. #208 was already squash-
  merged as `bd40687`; #193 is closed and #212 remains integrated. No second merge.
  Deleted local and remote `codex/193-audit-rate-limit-log-hygiene` at `f7f6089`,
  after confirming its tree equals the squash merge. Remote deletion used a lease.
- **Review evidence:** 113/113 privacy tests; independent negative control 70 red /
  27 green; all 21 new anchors checked; 10 source mutants plus packaged aud-17/35
  detected. Added temporary duplicate-XFF/empty-boundary and overlapping ASGI-task
  attribution/reset probes (2 passed, removed afterward). CI at reviewed `3f93b3c`
  passed (run 34029727544); the fix-head CI also passed. No code changed this turn.
- **History/state:** preserved all 123 prior entries and rotated the oldest verbatim:
  124 unique entries, five live. #212's merge record is archived intact. The separate
  #208 worktree remains on main; the primary dirty #194 checkout is untouched.
  PR body updated with the GO and added coverage. No release or deployment performed.
- **Next:** fold queued aud-1..58 in a separate change after checking current anchors,
  adding test_audit_privacy.py and test_access_logging.py to harness targets.
  #194 and the separate end-of-M6 security/deployment gates remain: concurrent real-
  socket attribution, live provider, TLS/Caddy/LXC/restore and long-duration limiter
  behaviour are not signed off by this GO. #206/#210/#213/#214/#215 remain separate
  questions. Keep the LXC upgrade behind the remaining M6 gates.
