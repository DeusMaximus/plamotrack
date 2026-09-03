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

## 2026-09-04 — Claude Code (Fable 5.1) — #188 (M6-3) MERGED (PR #200 → `a84ca48`, Codex round 2 GO); m63- fold-in MERGED (PR #201 → `66bc922`)

- **Done:** Codex round 2 (GPT 5.6 Sol) on `5be4414`: **GO, no new findings** — round-1 f1–f3
  confirmed fixed by replay (4 red / 24 green on `641b214`, 28/28 and 1658/1658 at head, five
  mutants independently killed), calls 1–7 retained. PR #200 squash-merged as `a84ca48` on the
  owner's call (04/09), branch deleted, **#188 closed**. **The shipped app is default-deny from
  `a84ca48`:** an unclaimed instance prints a setup token; the owner claims and signs in through
  the browser; CSRF on cookie-borne writes; docs/schema behind `collection:read`. Then the
  harness fold-in: `chore/fold-m63-mutants` → **PR #201** (harness-only, no external review —
  the #197/#199 precedent): m63-1…10 into `mutation_test.py`, `TEST_FILES` +
  `tests/test_auth_local.py`, four file constants; `-k m63-` → all 10 killed at fold-in.
- **Decisions:** none new; #201 rides CI only.
- **State:** `main` at `66bc922` plus this entry (#201 squash-merged on green, owner's call).
  Dev DB is claimed with the e2e default password (`e2e-owner-password`); the packaged stack
  (`docker compose up`) on this Mac reuses the same volume — to see the first-run token locally,
  `docker compose down -v` first. No release cut — M6 ships as one release at the end.
- **Next:** (1) **#189 (M6-4) PATs** — mint/list/revoke in Settings,
  bearer on REST+MCP as the resolver's next credential (the strict presented-and-failed → 401
  rule applies there; design §5.9 item 3(a)), per-tool scope, T5/T6/T10; `revoke_all_sessions`
  callers from a request should pass `principal`/`request` (Codex round 2 note); (2) the two
  family-13 hardening items (unrouted `/api/*` → 401 for anon; parse-before-auth) — design §5.9
  item 3(b); (3) #190 (OAuth spike) can run in parallel; (4) **LXC stays put until M6 is
  finished** (owner, 03/09) — `ALLOWED_HOSTS` into its `.env` before the pull, back up first, and
  it will come up **unclaimed**: read the setup token from `docker compose logs api`.

## 2026-09-04 — Claude Code (Fable 5.1) — #188 (M6-3) PR #200: Codex round 1 (NO-GO, 3×P3) addressed at `5be4414`, CI green, round-2 brief handed over

- **Done:** Codex round 1 (GPT 5.6 Sol) on `641b214`: **NO-GO**, three P3s, no bypass, calls 1–5
  retained. All three reproduced at `641b214` and fixed at `5be4414` (backend only): (f1) the
  promised plain-http cookie-mode startup line didn't exist → `sessions.announce_cookie_mode`
  from the lifespan at every auth-enabled start (warning on plain http, info on https); (f2)
  `auth.sessions_revoked` declared, never recorded → `revoke_all_sessions` records it with
  `count=N` in the caller's transaction (target/address from the caller; both recovery commands
  pass `"host"`); (f3) three M6-3 security mutants survived (CSRF `==`, `verify_password(None)`
  short-circuit, unconditional `claimed_at` re-stamp) + stale PR-body counts → tests spy on the
  verifier's argument (`DUMMY_HASH`, via a wrapper — argon2's methods are read-only) and on
  `hmac.compare_digest`, pin `claimed_at` across recovery, assert the audit rows; **ten** M6-3
  mutants replayed by hand at `5be4414`, all killed, tuples in the PR body for the post-merge
  harness fold-in. Reply posted, PR body amended (head, counts, mutant table, e2e work out of
  "Deferred", token prose narrowed). Round-2 brief printed for the owner.
- **Decisions:** the cookie-mode tests patch the module logger with a recorder, not `caplog` —
  alembic's `fileConfig` in the session conftest disables already-imported app loggers
  (`test_integrity.py`'s note; re-verified). The https line is `info`, so under uvicorn's default
  logging (no root handler; last-resort prints WARNING+) it is **invisible in the shipped
  container** while the plain-http warning shows — put to Codex as deliberate call 6, not changed.
- **State:** `main` at this entry; branch head `5be4414`, **CI green** (Backend / Frontend /
  Integration). Backend **1658**, `test_auth_local.py` **28**; negative control of the round-1
  tests on `641b214`: 4 red / 24 green. Tree parked on `main` for the review window; dev DB owner
  password is `e2e-owner-password` (reset so the suite's default works). **Round 2 pending.**
- **Next:** (1) Codex round 2 on `5be4414` → address in the reviewer's numbering (4 onward);
  (2) merge #200 on GO; (3) harness-only PR folding m63-1…10 into `mutation_test.py`
  (`TEST_FILES` + `tests/test_auth_local.py`); (4) **#189 (M6-4) PATs**; (5) the two family-13
  hardening items (design §5.9 item 3(b)); (6) **LXC stays put until M6 is finished** (owner,
  03/09) — `ALLOWED_HOSTS` into its `.env` before the pull, back up first.

## 2026-09-04 — Claude Code (Fable 5.1) — #188 (M6-3) PR #200: e2e + CI Integration adapted to default-deny (PR #199 merged as `f713c8c`)

- **Done:** (1) **PR #199 merged** (`f713c8c`, auth- mutant fold-in) — found merged at session
  start. (2) On `feature/m6-3-local-owner-auth` (PR #200), the adaptation the flip owed:
  **Playwright** — a `setup` project (`e2e/auth.setup.ts`) that claims an *unclaimed*
  instance through the recovery command (`E2E_OWNER_PASSWORD`, default `e2e-owner-password`)
  and only ever *signs into* a claimed one (refuses, with the two ways out, rather than reset
  a credential it didn't create); signs in through the Vite proxy so the cookie lands on
  `localhost`; storage state + an `e2e/.auth/api.json` (gitignored) that `e2e/api.ts`'s
  `apiContext()` turns into Cookie + `Origin` + `X-CSRF-Token` for the specs' own API calls
  (every `request.newContext({ baseURL: API })` replaced; screenshots.spec too). New
  `e2e/auth.spec.ts`: signed-out browser → sign-in screen, wrong password refused (waits out
  `BASE_DELAY`), right one opens the app + a cookie-borne write, sign out → sign-in screen,
  reload stays out. **It caught a real bug:** `Layout.signOut` cleared the query cache *then*
  invalidated the session query — nothing left to invalidate, the gate kept rendering the app.
  Fixed (invalidate first, then `removeQueries` everything but the session). **Ingress
  matrix** — `--setup-token`/`--password`: claims (or logs into) the stack through
  `/api/auth/setup|login` and runs the positives cookie-borne (docs/openapi/kits/retailers/
  meta 200; writes 201 with the CSRF token; the absent-Origin write is now the app's 403
  `auth.origin_required`); with no credential the same rows expect the dependency's 401; an
  anonymous `/api/kits → 401` and `/api/auth/session → 200` row always. **CI** — the smoke
  curl on `/openapi.json` (now guarded) became `/api/auth/session` asserting `unclaimed`; a
  new step reads the setup token out of `docker compose logs api` (masked) and the matrix
  claims with it — the first-run path proven through the packaged nginx. Docs: procedure
  E2E + Integration rows and the matrix command, README e2e line, design §5.5 T2 sentence.
- **Decisions:** the suite never overwrites an existing owner credential; the matrix's
  anonymous mode stays meaningful (401 ≠ nginx's 404 / ingress 403) rather than requiring a
  credential; the packaged CI stack is claimed with a disposable password on argv.
- **State:** local: e2e **42 passed / 1 skipped** on one worker from an empty DB, zero rows
  left, owner claimed; frontend build/lint/481 unit green; backend ruff clean, pytest
  **1655 passed**; packaged stack (`up -d --build --wait` locally): token read from `docker compose logs api` (43 chars), matrix **0 failing** claimed / logged-in / anonymous, MCP `tools/list` ok. The pre-order spec flaked once locally
  under 10 workers (row not yet in the table) — passes alone and on one worker (CI's
  setting); not a regression. Committed as `27e4d32`, then `641b214` (CI: `docker compose down -v` before the packaged
  stack — the e2e had claimed the owner in the same Compose project's database, so the stack
  came up claimed with no token to read; locally the two used different databases). **CI green
  on `641b214`** (Backend / Frontend / Integration); PR #200 body updated. PR #200 body still says CI is red by construction — update it on push.
- **Next:** (1) review + merge #200 (Codex, high-stakes — the PR body's deliberate calls plus
  this entry's e2e/CI design); (3) **#189 (M6-4) PATs**; (4) the two deferred family-13
  hardening items (design §5.9 item 3(b)); (5) **LXC stays put until M6 is finished**
  (owner, 03/09) — `ALLOWED_HOSTS` into its `.env` before the pull, back up first.

## 2026-09-04 — Claude Code (Opus 4.8) — auth- fold-in (PR #199) + #188 (M6-3) local owner auth OPEN (PR #200, default-deny flip landed)

- **Done:** (1) **auth- mutant fold-in → PR #199** (harness-only, branched off `main`):
  the 22 tuples queued on #198 (auth-1…4, 6…23; auth-5 retired) plus the round-1 set
  written at fold-in (auth-24…42 — principal/scope algebra, the dependency's 401/403 +
  family branches, the classifications, the MCP tool scope map, `plan_requires_admin`,
  the owner seed, the generated nginx rejections). Four auth test files → `TEST_FILES`.
  Two fold-in findings: auth-22 as queued *appended* a 2nd profile middleware outermost
  and survived → re-anchored as one block move; auth-37 survived because the
  collection-only import test planned a CREATE, never an UPDATE → the test now seeds the
  retailer (state-axis). **All 42 killed**; backend 1626. Doc count 277→318/30 files.
  (2) **#188 (M6-3) → PR #200** off `feature/m6-3-local-owner-auth`: local owner auth,
  shipped app now **default-deny** (`create_app(authorization=True)`). New under
  `app/auth`: credentials, budget, sessions, setup_token, recovery; `services/auth` +
  `services/audit`; `routers/auth` (family 2/3, anonymous+self-checking); `schemas/auth`.
  Resolver reads the session cookie on the *request's own session*; dependency enforces
  CSRF (Origin presence + `X-CSRF-Token`) on cookie-borne unsafe requests. Docs/schema
  re-registered as guarded APIRoutes (OAuth2 redirect dropped); GoneError 410 +
  RateLimitedError 429; `apply_import` wired to `plan_requires_admin`. Frontend AuthGate
  (setup/login/owner) + CSRF-aware client + sidebar sign-out. Backend **1653**, frontend
  **481**, ruff + build clean, `render_ingress --check` ok. `argon2-cffi` added; no new
  migration (inherits #187's `f1058c5de0f3`).
- **Decisions (PR #200 body + design §5.9 item 3):** a non-resolving session cookie → `anon`,
  not 401 (an `HttpOnly` cookie can't be cleared out of a 401 loop on `/auth/session`;
  the strict rule is the bearer's, #189); resolve on the request session (a 2nd
  connection deadlocked vs the teardown TRUNCATE); CSRF cookie-borne-only; docs always
  re-registered as APIRoutes; conftest injects an owner by default so the ~1600 pre-auth
  tests pass; `test_auth_local.py` uses `anon_client` + real cookies.
- **State:** both PRs **OPEN, unmerged, unreviewed**. **CI Integration on #200 is red by
  construction** — the Playwright e2e specs hit the API anonymously and now 401; the flip
  needs an e2e global-setup (claim via the recovery command, reuse storage state) + auth
  on the specs' own `request.newContext` calls, **NOT done** (no Chromium / dev stack in
  this env). **Merge ordering: #199 before #188** — else #199's anchors need re-checking
  after #188 moves `dependency.py`/`main.py`/`registry.py`. Two family-13 hardening items
  deferred (unrouted `/api/*` → 401; parse-before-auth), design §5.9 item 3(b).
- **Next:** (1) the e2e/CI-Integration auth adaptation for #200 (the one blocker to green);
  (2) review + merge **#199 then #200** (order above); (3) **#189 (M6-4) PATs** — mint/list/
  revoke in Settings, bearer on REST+MCP as the resolver's next credential, per-tool
  scope, T5/T6/T10 — **not started this session**; (4) the two deferred hardening items;
  (5) **LXC stays put until M6 is finished** (owner, 03/09) — `ALLOWED_HOSTS` into its
  `.env` before the pull, back up first.

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

