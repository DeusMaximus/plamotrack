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

## 2026-09-04 — Claude Code (Fable 5.1) — #187 (M6-2) MERGED (PR #198 → `6604658`, Codex round 4 GO)

- **Done:** Codex round 4 (GPT 5.6 Sol) on `0d594d0`: **GO, no remaining or new findings**
  in the foundation-first scope. PR #198 squash-merged as `6604658` on the owner's call
  (04/09), branch deleted, **#187 closed**. CI on `0d594d0` green. Rounds 1–3 are in the
  previous entries; the merged design: the route policy registry + default-deny dependency
  behind `create_app(authorization=True)`; the response profile bound adjacent to the
  selecting router (innermost middleware for the app's routes; a `RouteBinding` on each
  mounted route, which also enforces the transport's declared verbs before the SDK);
  ambiguous route graphs refused at build; the nginx `/api` rejections generated from the
  registry; five auth tables (migration `f1058c5de0f3`, additive, owner seeded unclaimed).
  The shipped app is still **not** default-deny — activation lands with #188.
- **Decisions:** none new — deliberate calls 1–11 in the PR body all accepted by review.
- **State:** `main` at `6604658` plus this entry. Backend 1626 / frontend 473 at the merged
  head. **Not yet done:** the `auth-` mutant fold-in (tuples auth-1…4, 6…23 in the PR body;
  auth-5 retired) into `mutation_test.py` — harness-only PR, no external review (#197
  precedent). No release cut — M6 ships as one release at the end (0.2.10 was the M6-1
  exception). HANDOFF rotated (the 2026-09-02 "M6 begun" entry → `.agents/handoff/2026-09.md`).
- **Next:** (1) fold the `auth-` tuples into `mutation_test.py` — add the four auth test
  files to `TEST_FILES`, re-check every anchor at fold-in (the code moved under some in
  round 3), run `-k auth-`; (2) **#188 (local owner auth)** — flips the `create_app`
  default, suite-wide injection, e2e login, family 11 re-registered guarded, `apply_import`
  wired to `plan_requires_admin`, plus the activation checklist (unrouted `/api/*` 404 → 401;
  the parser-stage 422 before the dependency); #190 (the OAuth spike) can run in parallel.
  (3) **The LXC stays put until M6 is finished** (owner, 03/09) — `ALLOWED_HOSTS` into its
  `.env` before the pull, back up first.

## 2026-09-04 — Claude Code (Fable 5.1) — #187 (M6-2) PR #198: Codex round 3 addressed at `0d594d0`, round 4 pending

- **Done:** Round-3 fix on `feature/m6-2-auth-foundation` at `0d594d0` — both P3s accepted.
  (1) The response profile is applied **adjacent to the router that selects the route**:
  `ResponseProfileMiddleware` is added *first* in `create_app` (innermost user middleware —
  only Starlette's `ExceptionMiddleware` and FastAPI's `AsyncExitStackMiddleware` sit
  between it and the router, both pass the same dict on) and reads the endpoint the router
  recorded in the very dict it holds, so a scope-copying middleware above it changes nothing
  (pinned: `test_the_profile_middleware_is_innermost` + a `CopyScope`-above test); every
  mounted route carries a `RouteBinding` (`bind_route_policies`, `app/auth/dependency.py`)
  that stamps on the route's own send, below the child's own middleware. A "report from the
  dependency" design was tried and rejected: FastAPI parses the body before solving
  dependencies, so the parser-stage 422 lost its stamp. (2) The same binding enforces the
  transport's declared verbs (`MCP_TRANSPORT_POLICY.methods`) before the SDK runs, refusing
  with the SDK's own JSON-RPC 405 built from `mcp.types` (byte-equal to the SDK's, minus
  `mcp-session-id` — a refused verb creates no session); `CONNECT` and an extension verb
  joined the sweeps. `RouteIndex.response_profile_for` removed (dead). `AGENTS.md` rule 13
  and design §5.9 item 2 restated. HANDOFF rotated (the 2026-09-02 GPT-5 Codex entry →
  `.agents/handoff/2026-09.md`).
- **Decisions:** the REST side reads `scope["endpoint"]` *by stack position* rather than
  propagating a report (the call a round 4 would weigh — stated in the reply); the mount is
  bound at the route; the shipped app binds nothing (foundation-first, owner 03/09); the
  refusal deliberately carries no `mcp-session-id`.
- **State:** four auth modules 156 (80/7/65/4); full backend 1626 passed; frontend 473,
  lint + build green; ruff clean; `render_ingress.py --check` up to date. Mutants: eight new
  (auth-16…23) all killed; the round-2 set re-run on the reworked code — auth-1 16 failed / 4 passed, auth-2 2 / 0, auth-3 8 / 12, auth-4 6 / 0, auth-6 3 / 0, auth-7 1 / 0, auth-8 1 / 0, auth-9 1 / 0, auth-10 1 / 0, auth-11 2 / 0, auth-12 1 / 0, auth-13 1 / 0, auth-14 2 / 38, auth-15 19 / 0 — all killed (the header-table counts doubled, since the table now runs through both stampers); auth-5's anchor no longer exists (retired, its site was removed); auth-5
  retired (its site was removed, auth-16 succeeds it). Codex's round-3 probes replayed in
  their original shape: the `CopyScope` mount → all rows correct; CONNECT inside the binding
  → 405; CONNECT above it → the structural pin fails. PR body amended (round-3 section,
  calls 10/11, the tuples); the round-3 reply and a round-4 brief are drafted in the session
  scratchpad — **posting/editing on GitHub awaits the owner's go**. Migration unchanged.
- **Next:** (1) post the reply, apply the PR body, run Codex round 4 with the brief; (2) on
  GO, squash-merge #198 (`Closes #187`), then fold the `auth-` tuples into
  `mutation_test.py` (harness-only PR, no external review, per #197); (3) #188 (session
  auth) next — its activation checklist carries the family-13 and parser-stage items Codex
  named in round 1; #190 (the OAuth spike) can run in parallel. (4) **The LXC stays put
  until M6 is finished** (owner, 03/09) — `ALLOWED_HOSTS` goes into its `.env` before the pull.

## 2026-09-03 — Claude Code (Fable 5.1) — #187 (M6-2) PR #198 open: Codex rounds 1–2 addressed, round 3 pending

- **Done:** Branch `feature/m6-2-auth-foundation`, PR #198 (closes #187): `dd7e53e` the
  foundation (principal model, route policy registry, default-deny dependency behind
  `create_app(authorization=True)`, five auth tables + migration `f1058c5de0f3`, the
  import-admin predicate), `66a2e04` the nginx `/api` rejection list generated from the
  registry, `b2a82b2` the Codex round-1 fixes (Opus 4.8: no-store via a response
  middleware, the mounted-surface snapshot, the write-only principal). **Round-2 fix at
  `6354dad`** (Fable 5.1) — both P3s accepted, the invariants moved one level up:
  (1) `ResponseProfileMiddleware` *enforces* the declared `Cache-Control` on the final
  response: every handler/library line replaced, case-insensitive on the raw key,
  `no-transform` alone kept beside `no-store` (`KEPT_BESIDE_NO_STORE`), `ResponseProfile.
  cache_control` the single source, `no_store`+`cache` refused. The sweep found the `/mcp`
  mount declared `no_store` and unstamped (the SDK's `no-cache, no-transform` stood) →
  `RouteIndex.response_profile_for` covers mounted endpoints; `policy_for` stays REST-only.
  (2) `build_route_index` refuses ambiguous graphs (`DuplicateRouteError`: a shadowed
  dispatch entry with parameter names erased, a `*` beside a verb, a shared endpoint),
  refuses unknown route types, descends nested mounts, treats a bare-callable mount as a
  leaf, *declares* mounted routes (`_classify_mounted`); the transport's verbs and every
  REST path are pinned behaviourally (405 exactly off the literal snapshot, `Allow`
  checked). `AGENTS.md` rule 13 and design §5.9 items 2/7 updated. HANDOFF rotated
  (the 2026-09-01 entry → `.agents/handoff/2026-09.md`, new file).
- **Decisions:** `no-transform` is the one directive retained beside `no-store` (the SSE
  stream through nginx); a 500 from `ServerErrorMiddleware` is not stamped (generic text
  only); overlap by specificity (`/kits/series` before `/kits/{kit_id}`) is allowed,
  duplication refused; the `auth-` mutant set stays queued for a post-merge fold-in (#197
  precedent), tuples in the PR body. Shipped app still unenforced (owner's
  foundation-first call, 03/09).
- **State:** four auth modules 130 (77/7/42/4); full backend 1600 passed; frontend 473,
  lint + build green; ruff clean; `render_ingress.py --check` up to date. Mutants: 15
  single-site, all killed (auth-15 survived the first run — a dead second copy of the
  `no-store` literal in the middleware, fixed — then 10 failed); Codex's three graph
  probes replayed in their original shape, all refused. Migration unchanged since round
  1. PR body amended (round-2 section, mutant table + tuples); the round-2 reply and a
  round-3 brief are drafted in the session scratchpad — **posting/editing on GitHub
  awaits the owner's go**.
- **Next:** (1) post the round-2 reply, apply the PR-body amendment, run Codex round 3
  with the brief; (2) on GO, squash-merge #198 (`Closes #187`), then fold the `auth-`
  tuples into `mutation_test.py` (harness-only PR, no external review, per #197);
  (3) #188 (session auth) next — its activation checklist carries the family-13 and
  parser-stage items Codex named (unrouted `/api/*` 404 → 401; malformed JSON 422
  before the dependency); #190 (the OAuth spike) can run in parallel. (4) **The LXC
  stays put until M6 is finished** (owner, 03/09) — needs `ALLOWED_HOSTS` before its pull.

## 2026-09-03 — Claude Code (Opus 4.8) — #187 (M6-2) auth foundation — PR #198 OPEN, Codex round 1 addressed (`b2a82b2`)

- **Done:** M6-2 auth foundation on `feature/m6-2-auth-foundation` (commits
  `dd7e53e`, `66a2e04`, review-fix `b2a82b2`), **PR #198 open** against `main`. Landed
  **foundation-first** (owner's call, 03/09): the machinery is built and tested against
  the real route graph, but the shipped `app` is **not** default-deny —
  `create_app(authorization=True)` installs enforcement; the module-level app keeps it
  off until credentials exist (#188/#189), so CI/e2e stay green. Pieces:
  `app/auth/principal.py` (the five principals, three scopes, write⇒read, admin=owner);
  `app/auth/registry.py` (route policy registry — every effective route → a policy keyed
  on the **endpoint**, the MCP tool scope map, `build_route_index` raises on an undeclared
  route; `API_ALIAS_REJECTIONS` + `render_api_alias_rejections`); `app/auth/dependency.py`
  + `resolver.py` (the default-deny dependency: 401 anon / 403 insufficient / no-store on
  scoped responses; readiness self-guards on the raw peer; the pytest injection seam is a
  test-only `app.state` attr); `models/auth.py` + migration `f1058c5de0f3` (owner seeded
  **unclaimed**, credential, session, personal_access_token, audit_event — never portable,
  rule 9); auth codes `auth.unauthenticated`/`auth.forbidden` through the #25 envelope +
  frontend fixture/catalogue; `importing.py::plan_requires_admin`; the nginx `/api/`
  rejection list **generated** from the registry (`scripts/render_ingress.py`,
  byte-identical to #186's blocks); `AGENTS.md` rule 13 + rule 12 update.
- **Decisions (in the PR body's *Deliberate calls*):** (1) foundation-first, shipped app
  not default-deny — activate with #188; (2) policy keyed on the resolved endpoint,
  classified by router tag + method; (3) the `mcp`/`internal` → 401-on-REST cells are the
  **resolver's** (audience/peer, #189/#186, T5), not the scope dependency, so the matrix
  injects only `{anon, owner, pat:read, pat:write}`; (4) auth tables land unwritten until
  #188/#189/#193; (5) import-admin is a predicate now, the raise wired at activation;
  (6) no-store stamped on the final outgoing response by a middleware — exports and the
  401/403 deny envelope too (Codex r1 fix 1, superseded the earlier follow-up); (7) nginx
  list generated, `/.well-known` declared ahead of its #192 routes.
- **State:** backend **1532 passed**, frontend **473 passed**, ruff + format clean,
  `render_ingress.py --check` up to date; migration `f1058c5de0f3` round-trips both
  directions, enum CHECKs + owner seed intact. Tests: `test_route_policy.py` (30),
  `test_auth_tables.py` (7), `test_authorization.py` (21 — T1 on the real graph + the
  plan-mutation axis), `test_ingress_generation.py` (4). **Codex round 1 (GPT 5.6 Sol):
  NO-GO, three P3s, all reproduced at `66a2e04` and fixed at `b2a82b2`**, each mutant
  hand-confirmed (backup, not `git checkout`): (1) no-store was lost on handler-returned
  exports — a `ResponseProfileMiddleware` now stamps the final response from
  `scope["endpoint"]` (exports + deny envelope); (2) the enumeration skipped the `/mcp`
  mount and copied `route.methods` — added `iter_mounted_routes` + a full HTTP-surface
  snapshot (REST + mounted, methods pinned); (3) `write⇒read` was never exercised (the pat
  factory holds read) — a write-only principal now reads only through the implication.
  Answered per finding on the PR; **PR body attribution corrected Fable → Opus 4.8**
  (owner's note; commit trailers already Opus 4.8). **No `auth-` mutation set folded** —
  queued after merge (principal algebra, dependency branches, `plan_requires_admin`, owner
  seed). Deferred criteria tracked in the PR body + scratchpad: shipped-app flip,
  suite-wide injection, e2e login, family-11 enforcement, `apply_import` wiring, and the
  round-1 activation checklist (family-13 unrouted → 401, parser-stage 422) → **#188**;
  MCP tool-scope + bearer/audience → **#189**.
- **Next:** **awaiting Codex round 2 on #198** (round 1 addressed at `b2a82b2`, tree parked
  on `main`). Expect another round; on GO + merge, then
  **#188 (local owner auth)** activates default-deny. **LXC unchanged — still held until M6
  is finished** (owner, 03/09): no 0.2.10 upgrade there yet; when the time comes,
  `ALLOWED_HOSTS=<its LAN name>` goes into `.env` before the pull, then the pending
  migrations (incl. `f1058c5de0f3`) land together (back up first).

## 2026-09-03 — Claude Code (Fable 5.1) — #186 (M6-1) MERGED (PR #196 → `7954e47`, #39 closed), **v0.2.10-alpha RELEASED**, mutant fold-in MERGED (PR #197 → `987c6da`)

- **Done:** M6-1 — ingress identity and the Host/Origin guard — implemented end to
  end on branch `feature/m6-1-ingress-guard` (absorbs #39). `app/config.py` gains
  `PUBLIC_BASE_URL`, `ALLOWED_HOSTS`, `ALLOWED_ORIGINS`, `TRUSTED_PROXIES` (+ reads
  `WEB_BIND`) with validators (bare `*` refused); new `app/ingress.py` — one
  `IngressPolicy` from settings, `HostOriginGuardMiddleware` (421 / 403 in the #25
  envelope, `params.setting` names the key), `ForwardedClientMiddleware`
  (`request.state.client_address` from `TRUSTED_PROXIES` peers; `scope["client"]`
  untouched), `is_internal_peer`; `app/main.py` is now a factory (`create_app`,
  `build_mcp_app`) with FastMCP in strict mode on the same lists,
  `redirect_slashes=False` on both routers, `/readyz` raw-loopback-only; uvicorn
  `--no-proxy-headers` (Dockerfile, Playwright, README, AGENTS.md); nginx moved to
  `frontend/nginx/default.conf.template` + `15-plamotrack-server-names.envsh`
  (default-deny 421 server, the four `/api/` rejections, root `.well-known`
  locations, security headers + SPA CSP, `Host $http_host`); compose passes exactly
  three keys to `web`; `.env.example`; two error codes through registry, fixture,
  catalogue and the envelope audit; `backend/ingress_matrix.py` (T2, 44 rows) run
  by CI Integration with `ALLOWED_HOSTS=ci.plamotrack.test`; docs (operations:
  *Names it answers to*, *Upgrading to 0.2.10*; README; AGENTS.md rule 12;
  design.md §5 status + §5.9 item 1 shipped note; testing-and-review CI row).
  **Version bumped to 0.2.10** (three files, `uv lock`). No migration.
- **Decisions:** (1) an unsafe request with neither `Origin` nor `Referer` passes —
  T3's denial is for cookie-borne principals (none until M6-3); `null` is refused;
  (2) `TRUSTED_PROXIES` ships as mechanism only, compose sets nothing for nginx
  until M6-8 has a consumer; (3) REST guard wraps the MCP mount too, FastMCP's guard
  asserted separately; (4) `Host $http_host` at nginx so same-origin sees the port.
  All four in the PR body's *Deliberate calls* and in §5.9 item 1.
- **State:** **PR #196 squash-merged as `7954e47`** on the owner's call (03/09), branch
  deleted, **#186 and #39 closed**. Head before merge was `dc0c7d8` (`1e134f7` the
  feature, then the round-1 fixes). **Codex round 1 (GPT 5.6 Sol):
  GO, three non-blocking P3s, all reproduced at `1e134f7` and fixed at the head** —
  one defect in three places (Python derivation vs sh generator disagreeing on the
  effective allowlist): (1) `*:8080`/`[*]`/`www.*` survived validation and became `*`
  after port-stripping → new `app/hostnames.py`, every host-producing setting judged
  on its normalised form; (2) `WEB_BIND=127.0.0.2` dropped by the app, listed by
  nginx → only the three built-ins are dropped; (3) `PUBLIC_BASE_URL=http://nas.lan.`
  emitted a dotted `server_name` nginx can never match → one terminal dot stripped
  at both layers, FastMCP handed dotted names too. Plus a seven-case corpus test
  running the real `.envsh` under `sh` against the Python policy. Answered per
  finding in the PR thread; frontend count corrected to 471; call 5 reworded
  (uvicorn's `scope.server` is the concrete local address). After the fixes:
  `tests/test_ingress.py` **240 passed**, full backend **1470 passed**, seven more
  mutants killed (ing-20…26, two of them the first against the sh generator; ing-25
  survived once because the parity helper normalised the dot away before comparing —
  fixed by asserting the raw `server_name` first). **Release gate (testing-and-review.md) run on `7954e47`:** M6 milestone still holds
  #187–#195 + #30 by design (this is item 1 of ten, its own release — the notes say
  so); version 0.2.10 in the three files; packaged stack `up -d --wait --build` from
  the merge commit — `migrate` Exited (0), four services healthy, `GET /api/meta` →
  0.2.10, MCP `serverInfo.version` → 0.2.10 through nginx, archive manifest
  `app_version` 0.2.10 / `schema_version` f9979ec7b9cb (= alembic head), ingress
  matrix 0 failures on the release build; stack `down` (no `-v`), dev `db` overlay
  restored. **Released on the owner's word:** annotated tag `v0.2.10-alpha — the instance knows
  its own name` on `7954e47` pushed, `gh release create --prerelease --verify-tag`
  with notes leading with the `ALLOWED_HOSTS` lockout and recovery, then the
  client-visible changes, upgrade steps and the mid-milestone note —
  https://github.com/DeusMaximus/plamotrack/releases/tag/v0.2.10-alpha. CI on
  `7954e47` green (Backend, Frontend, Integration). **Fold-in: PR #197, squash-merged as `987c6da`** on the owner's call once CI was
  green (branch deleted) — puts the 26 tuples into `mutation_test.py` as **`ingr-`**
  — relabelled because `-k ing-` substring-matches wdr-8's "missing-application" —
  with `tests/test_ingress.py` in `TEST_FILES`, the nginx generator in the
  clean-tree check (ingr-25/26 are the first cases against a shell file), ingr-15
  re-anchored to the round-1 grammar; measured through the tracked harness:
  **all 26 killed**, tree clean after; procedure doc count 251 → 277 over 27 files.
  Harness-only change, no app code — rides the gate, no external review bought
  (owner's criterion from #40). Verified before the first push: `tests/test_ingress.py` 175 passed; full backend suite 1405 passed; ruff
  clean; frontend 470 passed, lint + build green; negative control in a worktree at
  `main` (`ea4ce81`) **30 red / 14 green** with the greens the positive controls;
  hand mutation pass **19/19 killed** (ing-5 survived the first pass — child has one
  route today — killed by the added probe-route test); packaged stack built and
  probed (matrix 0 failures with `nas.lan:8080` + `PUBLIC_BASE_URL` in a scratch
  `.env`, fastmcp `Client` through nginx on both spellings, SPA under the CSP with an
  empty console incl. the *Add kit* dialog); stack `down` (no `-v`), dev `db` overlay
  restored, `.env` restored from backup. PR body + release-notes draft in the session
  scratchpad (`pr-body.md`, now posted as the PR body); PR #184 (`ja`) unchanged. LXC still pre-0.2.9 — and
  **needs `ALLOWED_HOSTS=<its LAN name>` in `.env` before pulling 0.2.10**.
- **Next:** (1) **#187 (M6-2, the route policy registry)** is the next implementation
  branch — it replaces the typed nginx rejections and `ingress_matrix.py`'s hand-typed
  rows; #190 (the OAuth spike) can start in parallel now that M6-1's topology exists.
  (2) **The LXC stays where it is until M6 is finished** — owner's call, 03/09: no
  0.2.10 upgrade, no `ALLOWED_HOSTS` edit there yet; when the time comes, that name
  goes into its `.env` before the pull, and the two 0.2.8/0.2.9 migrations plus
  whatever M6 adds land together (back up first). Do not raise the LXC upgrade
  before then. (Was: fold
  the `ing-` tuples into `mutation_test.py` (`ing-1`…`ing-26`, + `tests/test_ingress.py` in
  `TEST_FILES`), then the release gate for **0.2.10-alpha** — notes lead with
  `ALLOWED_HOSTS`; (3) #187 (registry) next — it replaces the typed nginx rejections
  and the matrix's hand-typed rows.
