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

## 2026-09-04 — Claude Code (Fable 5.1) — #189 (M6-4) PR #202: Codex round 1 (NO-GO, 3×P3) addressed at `732b8aa`, round 2 pending

- **Done:** Codex round 1 (GPT 5.6 Sol) on `789357d`: NO-GO, three P3s, no bypass, calls 1–7 and 9
  retained. All reproduced and fixed at `732b8aa` (after merging `main` at `7bd91a1` — HANDOFF
  conflict, main's entry kept): (f1) `Bearer␠␠<token>` was 200 on REST / 401 on MCP — FastMCP's
  backend drops one space and passes the rest verbatim → `resolve_bearer` strips the value (the
  shared helper, not the verifier), header-form matrix through both surfaces (3 red at `789357d`),
  mutant pat-24 killed; (f2) "WWW-Authenticate on every 401" was false (login/setup 401s carry
  none) and a blanket default would advertise `Bearer` on routes that refuse a bearer → contract
  narrowed to the bearer boundary, pinned by a test, design §5.9 item 4 / call 8 / docstrings
  amended; (f3) the matrix put a live PAT in `?access_token=` (uvicorn + nginx access logs) and
  the unit T10 captured root only → fake token in that row, CI step greps `docker compose logs`
  for the `--token-out` token, T10 attaches to every logger and states its bound, docs say never
  to put a token in a URL. Reply posted, PR body amended (head, call 8, counts, pat-24).
- **Decisions:** the f2 narrowing keeps the family-3 statuses at 401 (no move to 400/403);
  design §5.9 item 4 (i)/(j) record f1/f3.
- **State:** branch head `732b8aa` pushed; backend **1760**, `test_auth_tokens.py` **100**; CI on
  `732b8aa` was still running when this was written — the new log-scan step is the thing to
  check. Tree parked on `main`. Dev DB claimed with `e2e-owner-password`. **Round 2 pending.**
- **Next:** (1) Codex round 2 on `732b8aa` → address in its numbering (4 onward); merge on GO;
  (2) harness fold-in PR for pat-1…24 (`TEST_FILES` + `tests/test_auth_tokens.py`); (3) the two
  family-13 hardening items (design §5.9 item 3(b)); (4) #190/#192 OAuth spike; (5) **LXC stays
  put until M6 is finished** (owner, 03/09) — `ALLOWED_HOSTS` into its `.env` before the pull,
  back up first, it comes up unclaimed.

## 2026-09-04 — Claude Code (Fable 5.1) — #189 (M6-4) personal access tokens: PR #202 OPEN at `789357d`, Codex round 1 pending

- **Done:** #189 built on `feature/m6-4-personal-access-tokens`, one commit (`789357d`),
  pushed, **PR #202** open against `main` `17751a1`. The branch's own HANDOFF entry (in
  that commit) has the file-by-file state; in short: `ptk_<12 hex>_<secret>` tokens,
  `services/tokens.resolve_bearer` behind both the REST resolver and a FastMCP
  `TokenVerifier` on the `/mcp` mount, `ToolScopeMiddleware` on `tools/call` reading
  `MCP_TOOL_SCOPES`, `/auth/tokens` as family 6, `RoutePolicy.bearer_refused` (family 3),
  `WWW-Authenticate` on every 401, audit `auth.token_minted/revoked/use_after_revoke`,
  Settings → Access tokens, e2e `tokens.spec.ts`, matrix + CI probe carrying a token,
  README/operations/design/AGENTS updated. Deliberate calls a–h in design §5.9 item 4 and
  1–9 in the PR body.
- **Decisions:** review by Codex (M6 security work); the `pat-` mutants (23, all killed)
  were hand-run from a scratch runner because the tracked harness refuses a dirty tree —
  tuples in the PR body's collapsed block, **fold into `mutation_test.py` after merge**
  (`TEST_FILES` + `tests/test_auth_tokens.py`, the #197/#199/#201 precedent).
- **State:** backend 1754 / `test_auth_tokens.py` 94, frontend 485, e2e tokens 2/2, packaged
  stack from empty: matrix 54 rows 0 failing, `fastmcp` client 30 tools with the token and
  401 without. Negative control: the new file does not collect on `main` (imports the
  feature); the adapted matrix files go 6 red / 145 green there. Tree parked on `main` for
  the review window. Dev DB claimed with `e2e-owner-password` (re-claimed after the
  packaged run's `down -v`). CI on `789357d` not yet observed.
- **Next:** (1) Codex round 1 on `789357d` → reproduce, fix, reply in its numbering; merge on
  GO; (2) harness fold-in PR for `pat-`; (3) the two family-13 hardening items (design §5.9
  item 3(b)); (4) #190/#192 OAuth spike; (5) **LXC stays put until M6 is finished** (owner,
  03/09) — `ALLOWED_HOSTS` into its `.env` before the pull, back up first, it comes up
  unclaimed (setup token in `docker compose logs api`).

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

