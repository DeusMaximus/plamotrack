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

## 2026-09-15 — Claude Code (Fable 5.1) — `docs/operations.md` retired into the docs site (docs.gunp.la): **PR #254** (app) and **plamotrack-docs#5** open on the owner's go, CI pending; the docs PR must merge first

- **Done — docs site** (`~/Code/plamotrack-docs`, branch `docs/absorb-operations-md` off `main` = `0bd5b9c`, commit `21632cf`, **PR plamotrack-docs#5**; 13 pages modified, 2 new): `docs/operations.md` audited section by section against the site, every gap filled. **New pages:** `deployment/overview.mdx` (the four-ways table with the "tested" column, plain-HTTP vs TLS, the Unsupported list — the target of the README's "four ways" links) and `configuration/audit-log.mdx` (events recorded / never recorded, sha256 fingerprints, `prune-audit` + `AUDIT_RETENTION_DAYS`, the refusal budget, access-log hygiene incl. the proxy). **Expanded:** `env-reference` (per-key detail for `WEB_BIND`/`ALLOWED_HOSTS`/`PUBLIC_BASE_URL`/`TRUSTED_PROXIES`, fuller auth/MCP rows, the Compose-network trust note, bootstrap vs runtime settings); `reverse-proxy` (5th step: proxy log hygiene); `cloudflare-tunnel` (`WEB_BIND` = the address the connector reaches — the tested shape has the connector on another machine; Cloudflare Access; idle/keepalive); `vps-caddy` (`deploy/caddy/Caddyfile` named, `/api/readyz` 404); `troubleshooting` (readyz vs healthz); `password-login` (fix: the recognised-cookie bucket is the *reserved* one, not "larger"; per-address vs shared allowance); `oidc` (issuer+subject binding, other accounts refused + audited, rebind reports the provider count); `access-tokens` (read-only includes CSV export); `claude-web-chatgpt` (`PUBLIC_BASE_URL` as identity; disconnecting in the client ends the grant; new "Registration limits and edge cases": public clients, 24 h, 20/h, 1024, 16 KiB, CIMD document caching and the `401 invalid_client` case); `backups` (scripted archive export with a PAT — operations.md's `curl` line had lacked a token since 0.3.0 — snapshot consistency, in-container variable expansion, restore with a fresh `.env`); `upgrading` (0.4.1 `private_key_jwt` clause; "Data checks for older instances" carrying the pre-0.2.7 SQL check and the pre-public-schema note inline — the 0.2.7 entry had linked into the file being deleted). Owner review in the preview: the overview page retitled *Choose how to run plamotrack: four deployment options*; Mistral's Le Chat renamed **Vibe Chat** on the MCP overview table and the web-clients page (the only two mentions in either repo). `mint broken-links` clean; the new/expanded pages rendered under `mint dev` (temporary `docs` entry in `.claude/launch.json`, reverted).
- **Done — app repo** (branch `docs/retire-operations-md` off `main` = `a21dba3`, commit `fe0f6ab`, **PR #254**; 20 files + the deletion): `git rm docs/operations.md`. **README:** every reference is a docs.gunp.la link (deployment overview; Backups / Updating / Audit log / Configuration; `local-and-lan#got-a-421-error` ×2 — the old `#names-it-answers-to` anchor no longer existed; OIDC login + Web clients pages; a new "Anything else → troubleshooting" bullet); the prerequisites line corrected — Docker **with Compose and Git** (the block starts with `git clone`), "a few minutes" not "three". **Elsewhere:** `AGENTS.md` (layout note: operator docs live on the docs site; roadmap item 5; the "four documented ways" paragraph), `.env.example` ×2, `docker-compose.yml` ×2, `deploy/README.md`, `deploy/caddy/Caddyfile` ×2, the nginx `.envsh` comment, `app/config.py`'s two error strings (split for the 100-col limit), `deployment_gate.py` docstrings ×2, three migration comments, three test docstrings, the `ci.yml` comment, `docs/import-export.md` (→ `upgrading#kit-quantities-from-early-imports`), `docs/design.md` present-tense refs (mode R row, §5.8, §10, roadmap 7 — the past-tense "shipped" narrative near lines 1785/1791/2392 left as history), `.agents/deployment-gate/README.md`. `ruff check` + `format --check` clean; no test asserts the changed strings. Untouched by design: `.agents/lessons.md`, `.agents/spikes/*`, the handoff archives.
- **Decisions (mine, for the owner):** operator documentation has one home, the docs site; this repo's `docs/` keeps `design.md`, `import-export.md`, `translating.md`. The docs-site additions are content the site lacked, in its own voice — not a port of the wall of text. Committed and the PRs opened on the owner's go ("all good to proceed"); not merged — that is the owner's call, and the docs PR goes first. No review requested: docs-only, no behaviour change.
- **State:** app `main` = `a21dba3` + this entry (checkout on `main`, tree clean); `docs/retire-operations-md` pushed, PR #254 open against `main`. Docs repo `main` = `0bd5b9c`; `docs/absorb-operations-md` pushed, PR #5 open, checkout still on that branch, tree clean. A sibling session's worktree `.claude/worktrees/mystifying-herschel-*` sits on `handoff/pr-253` (= `main`); **PR #253** (screenshot capture, `chore/docs-screenshot-capture`) is open and not this session's. testhost and the LXC untouched.
- **Next:** **merge plamotrack-docs#5 first** (the README's new links resolve only once `deployment/overview` and `configuration/audit-log` are live; the site deploys within a minute of the merge), then #254 once CI is green; delete both branches after. Then whatever is next on the roadmap. Open: #223–#227, #230, #238, #247, #249, #251, PR #253.

## 2026-09-15 — Claude Code (Fable 5.1) — **v0.4.1-alpha RELEASED** (M6.1 complete): release PR #252 merged with merge commit `971af7e` (tree `ebc0f47`, the gated tree), tag pushed, prerelease published, #242/#243/#244/#56 closed, milestone M6.1 closed, docs site updated (plamotrack-docs#4); next the LXC upgrade and the personal Gunpla skill refresh — the owner's

- **Done:** release commit `994f759` on `m6.1-fastmcp4` (0.4.1 in the three files via `uv lock`; the Built flip in README's roadmap row, design §7.1 and §11 with the acceptance run recorded in §7.1, AGENTS' roadmap; *Upgrading to 0.4.1* in `docs/operations.md`; README points at https://docs.gunp.la in three places). **PR #252** (`m6.1-fastmcp4` → `main`, CI green on all jobs) merged with a **merge commit `971af7e`**, two parents, tree `ebc0f47` == the branch tip's == the gated tree (`main` was an ancestor with nothing outside the branch). Annotated tag `v0.4.1-alpha — MCP speaks both generations` on the merge commit, pushed; `gh release create --prerelease --verify-tag` → https://github.com/DeusMaximus/plamotrack/releases/tag/v0.4.1-alpha with the acceptance block and both gate blocks as observed. Milestone M6.1 closed (5/5). Docs site: PR DeusMaximus/plamotrack-docs#4 squash-merged (`0bd5b9c`, changelog entry dated 15 September 2026), live at docs.gunp.la within a minute.
- **Gate (both green, on tree `ebc0f47`):** step 4 local packaged stack under its own Compose project — migrate exit 0 (head `d5e9362140ea`), app 0.4.1 on fastmcp 4.0.3 / mcp 2.2.0, matrix local mode 0 failing with 75 s holds, refusal budget 10 rows, `/api/meta` 0.4.1, both eras through nginx with a PAT (31 tools, `serverInfo` 0.4.1), anonymous refused, archive manifest `app_version 0.4.1` / `schema_version d5e9362140ea` / `export_version 1`, T10 scan clean (210 api + 371 web access records, 7 values absent); torn down, dev volume untouched. Step 4b testhost `--phase all` + tunnel after a fresh-install reset, 07:19–07:35, exit 0: precheck, lockout, local (180 ok), modern-hold, break-glass, trusted-proxies, oidc (182 ok), t13 (three restores as documented), tunnel (87 ok, 130 s holds both spellings, visitor attribution exact). Results in the PR comment (issuecomment-5671138175) and the notes; the gate's state dir is `~/.plamotrack-gate/testhost.internal.tlgnet.net` (the #244 run's moved to `…244-run-2026-09-11`); the acceptance run's own secrets in `…rc-0.4.1/`.
- **Decisions (owner):** release is v0.4.1-alpha (patch, not 0.5.0); the acceptance run doubled as the mandatory final integration review; the bump a direct commit on the integration branch as for 0.4.0; the LXC upgrade and the Gunpla skill refresh are the owner's; `m6.1-fastmcp4` left in place, not deleted.
- **State:** `main` = `971af7e` + this entry; the tagged tree differs from the gated tree by nothing (the hand-off commit lands **after** the tag, as the rule says). Checkout on `main`, tree clean. testhost: the release tree in mode R, OIDC mode, Keycloak up, the gate's end state. The real LXC: **v0.4.0-alpha until the owner upgrades** (nothing to migrate; connected MCP clients stay linked). The local `m6.1-fastmcp4` branch still exists locally and on origin.
- **Next:** the owner upgrades the LXC to 0.4.1 (back up first; `git pull && docker compose up -d --build --wait`; sign in as before) and refreshes the personal Gunpla skill. Then whatever is next on the roadmap — M7 photos (#28 first) or M8 — and the open lows: #223–#227, #230, #238, #247, #249, #251. The conformance runner still has no `2026-07-28` server scenarios; re-run it when one ships.

## 2026-09-15 — Claude Code (Fable 5.1) — M6.1 final integration review: the real-client acceptance run GREEN on testhost through the Cloudflare Tunnel (Claude web, ChatGPT web, Gemini Spark, Mistral, Inspector 2.6.0, Claude Code 2.1.270, mcp-remote 0.14.2, the 4.0.3 client, modern-hold through the tunnel, conformance 0.1.16); 3.x→4.x grant continuity across upgrade + documented restore recorded; next the release PR (v0.4.1-alpha)

- **Done:** local `m6.1-fastmcp4` reset to `origin` (`d57af8b`) and `main` merged in → **`c3c356b`** (docs only; unpushed). testhost reset fresh-install to the **v0.4.0-alpha tree** in the documented tunnel + OIDC shape (`PUBLIC_BASE_URL=https://plamotest.gunp.la`, `WEB_BIND=10.1.1.129`, `TRUSTED_PROXIES=10.1.1.155`, Keycloak fixture); owner claimed headlessly through the tunnel; the owner linked Claude web (CIMD), ChatGPT web (CIMD), Gemini Spark (DCR) and Mistral (DCR) at 0.4.0; documented backup; **upgrade** to the branch tree with the documented command (28 s, migrate 0, no new migration); round 1; backup at 4.x; **documented restore** (`down -v` … `pg_restore` … `up --build`, 31 s); `--phase modern-hold --hold 130` through the tunnel; round 2 after every access token expired; Inspector by DCR; Claude Code and `mcp-remote` by PAT; the 4.0.3 client both eras; the conformance runner against a source-run `create_app()`.
- **Verified (every number observed; the block is `~/.plamotrack-gate/testhost.internal.tlgnet.net.rc-0.4.1/results-real-client-run.md`, copy in the session scratchpad):** all four web grants continued across the upgrade **and** the restore with no re-registration, no re-consent, no refusal; upstream tokens re-put ×4 on the first 4.x call (transparent refresh through httpx2); after the restore `POST /mcp/token` 200 ×4, refresh tokens rotated ×4, JTI 8→14, **both persisted CIMD rows deleted at the first document fetch (#242's transition, in production shape)**; owner cookie + 0.4.0 PAT valid after the restore. **Eras:** Claude web and Claude Code speak `2026-07-28` (stateless, routing headers; Claude web on bare `/mcp`); ChatGPT, Gemini, Mistral, Inspector `2025-11-25`; `mcp-remote` does its own legacy initialize then relays the client's modern calls. Modern hold through Cloudflare: both spellings 130 s, 15 s gaps, backend released. API log 0 warnings/errors for the run. Conformance 0.1.16: 8 transport scenarios pass (initialize, ping, logging level, tools/resources/prompts list, multiple SSE streams, DNS rebinding); 20 need fixtures plamotrack has none of; the two "passed" tool-call scenarios are vacuous (the per-tool middleware refuses anonymous `tools/call` even on the pre-auth app and the runner counted the refusal text as content) — the runner has **no `2026-07-28` server scenarios**; tool execution is proven by the real clients.
- **Findings, none blocking:** Gemini Spark's first link registered a client and obtained a code it never redeemed (the publicly reported Gemini behaviour), second attempt fine; Gemini and Mistral re-handshake per step (7 and 19 initializes for one question); Mistral reuses a session after its own DELETE (404s, same on 0.4.0) and probes `/.well-known/mcp/server-card/mcp/`; ChatGPT's pre-handshake 400 is unchanged from 0.4.0. Nothing to file against the server.
- **Decisions (mine, for the owner):** the restore round doubles as the restart row (the documented restore restarts every service); Mistral added as a bonus row on the owner's initiative; the conformance tool-call "passes" recorded as vacuous rather than claimed; Claude Desktop's native connector not run separately (same account-level connector as Claude web).
- **State:** testhost left **on the branch tree in tunnel + OIDC shape**, grants live, Keycloak up, `PLAMOTRACK_ENABLE_TEST_HOLD` disarmed, tcpdump stopped; the branch archive `/root/plamotrack-m6.1-c3c356b.tgz` and backups under `/root/backups/` on the host. Secrets of the run (owner cookie, PAT, capture, DB snapshots, results) in `~/.plamotrack-gate/testhost.internal.tlgnet.net.rc-0.4.1/` (0600). The integration branch is being pushed with `main` merged in; the release commit (bump, Built flip, upgrade note, README pointers) follows this entry. The gate on the tagged tree still needs the usual fresh-install reset first.
- **Docs:** the Mintlify site — **PR DeusMaximus/plamotrack-docs#4** (branch `docs/m6.1-v0.4.1`, 8 pages, `mint broken-links` clean) gains the v0.4.1 changelog entry (date placeholder "September 2026" — set at tag time), a "Which clients work" table and "Protocol versions" section on the MCP overview, Gemini Spark and Mistral sections plus an update/restore note on the web-clients page, the Claude Code / first-request notes, the corrected `create_order` currency rule, and client lists on the OIDC and tunnel pages — to be merged **with** the release (the site documents released behaviour only). `README.md` gains three pointers to https://docs.gunp.la (top, Installing, Wiring up MCP) in the release commit.
- **Next:** the **release PR** onto `main`: bump to **0.4.1** (three files, `uv lock`), the Built flip (README row, design §7.1, §11), an "Upgrading to 0.4.1" section in operations, notes carrying this block + the gate's blocks **as observed** and #249 as a known limitation; merge commit, gate step 4 + 4b on that tree (testhost reset first), tag `v0.4.1-alpha`, `--prerelease`; hold this hand-off commit until after the merge. Then the LXC upgrade. Open: #223–#227, #230, #238, #247, #249, #251.

## 2026-09-11 — Claude Code (Opus 4.8) — PR #250 (#244 + #56) squash-MERGED into `m6.1-fastmcp4` as `d57af8b` after Codex rounds 1–3 (all NO-GO→fixed, CI green at `c884d09`); left on the integration branch on the owner's word; next is the mandatory final integration/release-candidate review, then the release PR onto `main` (v0.4.1-alpha)

- **Done:** PR #250 (`feat/244-era-gate`, head `c884d09` — CI green: Backend/Frontend/Integration
  pass; CodeRabbit skipped, reviews disabled for this base) **squash-merged into `m6.1-fastmcp4`**
  → **`d57af8b`** (`M6.1: gate both protocol eras with real clients (#244), and the create_order
  description/schema test (#56) (#250)`), on the owner's word ("merge into the integration branch
  and we'll leave it there for now"). Feature branch deleted; squash style matches #246/#248.
  Integration-branch tip: `c6cd383` → `d57af8b`.
- **This session was the merge only** — no code changed, no review run, no release step. The
  release-cadence memory (`plamotrack-release-cadence-027`) + the index were updated to the new tip.
- **Note — nothing closed:** the merge landed on the **integration branch, not `main`**, so
  `Closes #244`/`#56` did NOT fire — **#244 and #56 stay open** until the release PR merges to
  `main` (a merge into the integration branch closes no issues; same as #241/#243/#242).
- **Decisions (owner, standing — restated, still live):** release is **v0.4.1-alpha**; a
  **mandatory final integration/release-candidate review runs before `m6.1-fastmcp4` merges to
  `main`**, carrying the remaining acceptance rows; the **Built flip is deferred to the release PR**
  (README/design §7.1/§11 stay Planned). **This is not permission to merge to `main`, tag, or
  release** — each needs the owner's explicit go.
- **State:** `main` = this entry (checkout on `main`, tree clean). `m6.1-fastmcp4` = `d57af8b`,
  CI green, now holds the whole M6.1 branch (#241/#243/#242/#244) ready for the final review.
  Nothing in flight. Rounds 1–3 on #250 are fully answered/recorded (see the #244 entry below;
  lesson under "When rounds keep landing in one function, the fix is an invariant one level up" in
  `.agents/lessons.md` — F2→F6→F7, closed at the `Host.psql` boundary with `-v ON_ERROR_STOP=1`).
  testhost is in the gate end-state (OIDC, mode R) from the #244 remote gate; the real LXC untouched
  (last recorded 0.4.0, unconfirmed from here). Scratchpad holds the #250 briefs/responses/gate results.
- **Next:** the **final integration/release-candidate review** of the whole `m6.1-fastmcp4` branch
  before it merges to `main` — the real-client matrix (MCP Inspector, Claude web, ChatGPT web,
  Claude Desktop/Code), a conformance run against an unauthenticated build (the runner has no auth
  flag), modern-hold through the Cloudflare Tunnel, and 3.x→4.x grant continuity (Codex demonstrated
  a released 3.x grant surviving the 4.x upgrade/restart/backup-restore with a fixture provider —
  record it formally here). Then the **release PR** onto `main` (merge commit, gated, **v0.4.1-alpha**,
  Built flip; hold the release hand-off commit until after the merge), tag `v0.4.1-alpha`, then the
  LXC upgrade. Open: #223–#227, #230, #238; #249 is a known-limitation line for the notes.

## 2026-09-11 — Claude Code (Opus 4.8) — #244 built on `feat/244-era-gate` (head `5eb84fa`, clean off `m6.1-fastmcp4` = `c6cd383`): both protocol eras gated with real clients + the #56 description/schema test; PR #250 open (now `1a05b82`), remote deployment gate GREEN on testhost; Codex rounds 1–3 answered (r1 1 P2 + 4 P3; r2 1 P3; r3 1 P3, all fixed, now `c884d09`), CI green; next the final integration review → merge → v0.4.1-alpha

- **Done:** #244 whole (closes #244 + #56), one commit `5eb84fa`.
  - **Modern hold-and-cancel.** The `2026-07-28` mount serves no long-lived stream
    (`subscriptions/listen` is not wired; every tool is short), so the held stream is built
    around an existing `get_meta` call made to wait by `app/mcp_hold_probe.py` — an env-gated
    (`PLAMOTRACK_ENABLE_TEST_HOLD`), off-by-default FastMCP middleware holding a DB connection
    idle-in-transaction under a marker. Adds no tool and no route (registry/enumeration
    untouched); never armed in the shipped image. `json_response=False` makes the SDK commit
    SSE + ping past 15 s with no notification (the owner's insight). `tests/test_mcp_modern_hold.py`
    proves it over a **real uvicorn socket** (ASGITransport buffers, useless for streaming): SSE
    commit, no session id, no-cache, keepalive pings, abort → server-side cancellation → the held
    connection returned; parser bounds; the shipped mount carries no probe. `pg_sleep` was rejected —
    Postgres does not interrupt it on client disconnect, so cleanup was unobservable.
  - **Through the proxy chain:** `ingress_matrix.hold_stream_modern` + the gate's new `modern-hold`
    phase (in `ALL` after `local`) — arms the flag, holds+aborts the modern SSE on both `/mcp`
    spellings, asserts the backend gone in `pg_stat_activity`, disarms.
  - **CI (`ci.yml`):** a 4.0.3 client in `auto` (asserts 2026-07-28) + `mode="legacy"`, and a
    **frozen fastmcp 3.4.5 / mcp 1.29.0** client (both pinned — 3.4.5 alone floats to 1.30.0,
    #248 f1). **#56:** three `test_mcp.py` guards on `create_order`'s description vs the exposed
    input schema (get_meta not a `meta` resource; order currency optional, line required; a line
    without a currency refused).
  - **Docs:** design §7.1 records the coverage + the instrumentation; §5.8 T12 gains the modern
    twin. **The Built flip is NOT here (owner's Q3)** — README/§7.1/§11 stay Planned; §7.1's
    contradictory "flips with #244" sentence corrected to the release PR.
- **Verified:** full suite **2741 passed, 1 xfailed** (fixed the one drift-guard I tripped —
  `test_deployment_hygiene`'s ALL-tuple); ruff clean; **CI #250 all three jobs pass**; #56 negative
  control (mutate the description → pointer test reds; mutate the schema → asymmetry test reds).
  **Remote gate GREEN on testhost** (Q2 Full — a fresh install of this tree behind Caddy DNS-01 +
  a Cloudflare Tunnel): every phase 0 failing incl. `modern-hold` both spellings (cleanup ok),
  holds 75 s/130 s past the 15 s ping and Cloudflare's 125 s cliff, matrices 180/182/87 ok, T13
  three restores, visitor attribution 87.121.75.73, T10 clean. Results on PR #250
  (issuecomment-5629938030). testhost left in the gate end-state (OIDC, mode R); the real LXC untouched.
- **Decisions (owner, this session):** modern hold on an existing call via env-gated instrumentation,
  no new method/subscription (Q1); the remote gate run in this PR (Q2 Full); Built flip deferred to
  the release PR (Q3). Reviewer: **Codex (GPT-6)** — brief printed in chat (scratchpad `pr244-codex-brief.md`).
- **Round 1 (Codex, GPT-6) = NO-GO, 1 P2 + 4 P3 — all confirmed and fixed at `1a05b82`** (PR #250
  now that head, CI all-green, response issuecomment-5631143524). Every finding was verification
  passing for the wrong reason, not a transport defect: F1 [P2] `hold_stream_modern` only reported
  `max_gap` → stalled/35 s-gap/completed-body streams passed; F2 the modern-hold cleanup was vacuous
  (0 before/after, never observed a held backend); F3 arming ran before the try/finally (a startup
  failure left the flag armed); F4 the create_order description *still* said "omit currency_code"
  unscoped (#56 not actually closed) and the tests read only the schema + a backtick-less guard; F5
  the frozen check used `except Exception`. Fixes: a shared `_observe_hold` asserting no >30 s silence
  and no early close/terminal-chunk (both the modern and legacy holds — a sweep) + offline
  `tests/test_hold_observer.py`; the pytest and gate now observe a live held PID *during* and assert
  it gone after; arm/disarm in try/finally; the description scoped + tests check its clauses and any
  `meta` spelling; the frozen refusal asserted as `httpx.HTTPStatusError` 401. Every negative control
  reproduced; the restructured `modern-hold` phase re-run **green live on testhost** (PID 12197/12374
  held during, gone after, both spellings). Coverage record corrected on the PR (CI step = write-PAT
  on `/mcp/`; the 130 s tunnel holds are legacy).
- **Owner (this session):** release is **v0.4.1-alpha** (not v0.5.0); a **final integration /
  release-candidate review runs before `m6.1-fastmcp4` merges to `main`**, carrying the remaining
  acceptance rows. Not permission to merge/tag/release.
- **State:** `main` = this entry. PR #250 (`feat/244-era-gate`, `c884d09`) open against `m6.1-fastmcp4`
  (= `c6cd383`), **CI green**, rounds 1–3 answered — awaiting the owner's word / the final review.
  **Round 3 (Codex) = NO-GO, one P3 (finding 7):** `Host.psql` ran without `ON_ERROR_STOP`, so a SQL
  error (a statement-timeout on an observation query) exited psql 0 with empty stdout and every reader
  (`_held_pids`, counts) read it as "no rows" — a false release. Fixed at `c884d09` at the boundary
  (`psql -v ON_ERROR_STOP=1` → a SQL error is a non-zero exit → GateError), covering every reader; a
  tracked regression + negative control, and the live modern-hold re-run green with the flag. This was
  the invariant one level up from F2/F6 — lesson filed under "When rounds keep landing in one
  function" in `.agents/lessons.md`.
  **Round 2 (Codex) = NO-GO, one P3 (finding 6):** `phase_modern_hold` seeded `gone = bool(during)`, so a
  held PID lingering through every cleanup poll (complete or partial) still reported "gone after abort";
  fixed at `949acc9` with a positive-confirmation `_backends_released` helper + a tracked regression
  (`test_hold_observer.py`) and its mutation control. Same class as F2 — the invariant is now explicit.
  Codex also demonstrated a real **3.x grant surviving the 4.x upgrade/restart/backup-restore** with a
  fixture provider, de-risking that acceptance row (record it formally at the final review).
  #244/#56 close on merge. Scratchpad holds the PR body, the brief, the review response and all gate
  results. testhost left in the gate end-state (OIDC, mode R); dev overlay up.
- **Next:** the next Codex round on #250 (if any) → merge into `m6.1-fastmcp4` → the **release PR**
  (merge commit, gated, **v0.4.1-alpha**; hold the hand-off commit until after the merge), which is
  the owner's required final integration review: the real-client matrix (Inspector, Claude web,
  ChatGPT web, Claude Desktop/Code), a conformance run against an unauthenticated build (the runner
  has no auth flag), modern-hold through the Cloudflare Tunnel, and 3.x→4.x grant continuity — then
  the Built flip. #249 is a known-limitation line for the notes. Open: #223–#227, #230, #238.
