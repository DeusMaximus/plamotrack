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

## 2026-09-04 — Claude Code (Fable 5.1) — #191 (M6-6) PR #209: Codex round 1 (NO-GO, 2×P2) addressed at `083ad08`, round 2 pending

- **Done:** Codex round 1 (GPT 5.6 Sol) on `910a335`: NO-GO, two P2s on the authorization
  boundary, both **reproduced first** (the new tests went red on the review's own assertions),
  then fixed, then mutated. **f1 — superseded sessions across `AUTH_MODE` changes:** the
  invariant is *a session is authority only in the mode that minted it* — `session.auth_mode`
  (`AuthMode` in `models/enums.py`; migration **`4f3a9c1e7b2d`**, text + CHECK, backfilled
  `local`), `new_session_row(..., auth_mode=)` stamps it, `resolve_session(..., auth_mode=)`
  refuses the other mode's row (→ `anon`), and the lifespan calls
  `revoke_sessions_of_other_modes` (write gate; `auth.sessions_revoked` + new
  `auth.mode_changed` audit rows, target `startup`, client `host`; a log line) so the switch is
  durable in both directions. The mode is read off the provider's presence on `app.state`
  (new **`app/auth/mode.py`**: `OIDC_PROVIDER_ATTR`, `auth_mode_of`; `routers/auth.py` re-exports
  the attr); the lifespan now reads the provider from `app_.state`, not the closure (so a test's
  fake-backed provider is what warms). **f2 — id_token claim shapes:** the joserfc
  `JWTClaimsRegistry` is gone; `validate_id_token_claims` (module-level in `services/oidc.py`,
  pinned-clock `now=`) is the one contract — types before values, `aud` exactly this client
  (string or single-member list; any extra audience refused whatever `azp`), `azp` == client id
  when present, `iat` required, `exp`/`iat`/`nbf` NumericDates with bools excluded, `nonce` a
  string; `complete_login` reads `claims["sub"]` (the `no_subject` branch and audit detail are
  gone — every shape is `id_token_rejected`). Docs: design §5.6 (session row, audit list), §5.8
  T7, §5.9 item 6 calls **(f)** and **(g)**; `docs/operations.md` (sign-out at the first start in
  the new mode, both directions; the client must be the token's only audience); AGENTS.md rule 13.
- **Decisions:** stamp-and-sweep, not an auth-epoch column (the mode switch was the only regime
  change that did not already write the DB; reset/rebind revoke as before); no trusted-audience
  setting (single owner, nothing to trust); `read_session`'s ordering unchanged (owner-and-unbound
  is now unreachable, a reorder would be a dead branch); backfill `local` is a fact for every
  released instance, disclosed in the migration docstring (the dev DB's OIDC-minted sessions get
  `local` too — one sign-out on a throwaway DB).
- **State:** backend **1939 green** (`test_migration_data.py` HEAD → `4f3a9c1e7b2d`),
  `tests/test_auth_oidc.py` **70** (matrix 6 → 32 refused + 4 accepted shapes, a leeway-edge
  unit test, four mode-switch tests), frontend untouched (487). Mutants oidc-21…38 (18, one site
  each): **18 killed, 0 survived (oidc-30 killed as a 500 from the comparison, not a refusal — the type check is what makes it one)**; runner + tuples in the session scratchpad and in the PR body's
  `<details>`. `uv run alembic check` on the dev DB reports "removed check constraint" for every
  text-enum CHECK in the schema (pre-existing autogenerate noise; `ck_session_auth_mode` joins the
  list) and no column difference. Dev DB is at `4f3a9c1e7b2d`. Tree: clean at `083ad08` (the fix) + this entry; both pushed.
- **Next:** (1) Codex **round 2** on PR #209 — brief per `.agents/review-brief.md` (Codex footer)
  at the new head, pointing at the round-1 reply and the two new `<details>` rows; (2) after merge,
  fold oidc-1…38 into `mutation_test.py` (the four registry-anchored tuples are superseded by
  21–30); (3) #192 (M6-7) on top; (4) #193; (5) **LXC stays put until M6 is finished** (owner,
  03/09). Release-notes items: `AUTH_MODE=oidc` exists; a mode switch signs every browser out at
  the first start in the new mode (both directions) and a local→oidc switch needs the setup token
  once.

## 2026-09-04 — Claude Code (Fable 5.1) — #191 (M6-6) browser OIDC on `feature/m6-6-browser-oidc` — **PR #209** open for Codex review; #190 closed

- **Done:** #190 closed (evidence comment + harness on `main` at `a642d0b`). Owner chose
  **#191 before #192** (the declared order: #192's owner binding and mode switch are #191's).
  Branch `feature/m6-6-browser-oidc` off `a642d0b`, committed and pushed (owner's call) as
  **PR #209** (body carries the deliberate calls and the mutant table). Shape: `AUTH_MODE=local|oidc` + `OIDC_ISSUER/CLIENT_ID/CLIENT_SECRET`
  (env-only; `PUBLIC_BASE_URL` required in OIDC mode, the callback
  `<PUBLIC_BASE_URL>/api/auth/oidc/callback` is built from it); `services/oidc.py` (discovery
  cached lazily and issuer-checked, JWKS, code exchange `client_secret_basic` + PKCE, id_token
  via **joserfc** — asymmetric algs only — for iss/aud/sub/exp/nonce; `begin_login` /
  `complete_login` / `recovery_rebind_oidc`); table `oidc_login` (migration `0db6c35d0a7e`:
  digests of `state` + a browser-binding cookie, nonce, PKCE verifier, `claiming`, 10 min,
  single use); routes `POST /auth/oidc/start` (JSON → `{authorization_url}` + binding cookie)
  and `GET /auth/oidc/callback` (302 to the SPA root; `?auth_error=<word>` on refusal); the
  password pair 404 in OIDC mode and vice versa (`auth.not_in_this_mode`); registry `modes`
  field; `GET /auth/session` gains `auth_mode`/`oidc_issuer` and reports `unclaimed` while the
  owner is **unbound** (claimed but no `(issuer, subject)` — a mode switch or a rebind), so the
  setup token is the claim gate in OIDC mode too; `recovery rebind-oidc`; SPA screens; docs
  (operations, .env.example, README, design §5.5 row + §5.9 item 6 "Shipped" calls (a)–(e),
  AGENTS.md rule 13). **Verified against the real Keycloak** (spike realm, `localhost:8081`,
  API run in OIDC mode with `PUBLIC_BASE_URL=http://localhost:5173`): setup token → provider
  → bound owner in the SPA; a stranger → `auth_error=oidc_identity_refused` + audit row.
- **Decisions:** on PR #209's body ("Deliberate calls" 1–10) and design §5.9 item 6 — notably `start` is a POST returning JSON (token never in a URL,
  Origin-guarded), the transaction is a DB row not a signed cookie (no app secret exists),
  unbound ⇒ `unclaimed` ⇒ setup token, joserfc over Authlib's deprecated `jose`.
- **State:** backend **1903 green** (`test_migration_data.py` HEAD bumped to `0db6c35d0a7e`),
  `tests/test_auth_oidc.py` **35**; frontend 487, build + lint clean. Hand mutants oidc-1…20
  (exact tuples in a `<details>` block on the PR body): **18 killed, 2 equivalent**
  (oidc-11 sub fallback — joserfc's essential `sub` refuses first; oidc-13 HS256 — no symmetric
  key in the JWKS); three first-pass survivors (5, 12, 19) were test gaps, now tests.
  T2 rows added to `ingress_matrix.py` (CI Integration proves them; packaged stack not run
  locally). Dev DB: owner is now **bound to the Keycloak `owner` user** in OIDC mode and still
  holds the local credential (`e2e-owner-password`) — switching the API back to local mode
  just works; Keycloak spike container is **up** (`.agents/spikes/190/keycloak/`, realm now
  lists the `localhost:5173` callback). No e2e change (local mode).
- **Next:** (1) **Codex round 1 on PR #209** — the brief was printed once in the authoring
  session and is not stored; regenerate it from `.agents/review-brief.md` (Codex footer), the
  PR body's "Deliberate calls" and its **"Where a reviewer should push"** section; the
  runtime head is `96f24ab` (every commit after it on the branch is a hand-off entry —
  brief the reviewer at the branch tip and say so), `main` `a642d0b`, rules 1/6/7.1/9/11/13 in play; answer findings per
  `.agents/testing-and-review.md` → "Responding to a review". Tree parked on the branch.
  (2) fold oidc- mutants
  into `mutation_test.py` after merge (the usual harness-only PR); (3) #192 (M6-7) on top —
  same issuer/client, the spike's decisions; (4) #193; (5) **LXC stays put until M6 is
  finished** (owner, 03/09). Release-notes item: `AUTH_MODE=oidc` exists; a local→oidc switch
  signs everyone out and needs the setup token once.

## 2026-09-04 — Claude Code (Fable 5.1) — #190 spike: EVERY leg run (Keycloak, Google, MCP Inspector, Claude web, ChatGPT web, nginx, T13); evidence comment POSTED

- **Done:** #190's spike, every leg that needs no external account, against the pinned
  FastMCP 3.4.5 / MCP SDK 1.29.0. Harness + raw outputs in **`.agents/spikes/190/`**
  (untracked — owner decides whether it is committed; `.agents/README.md` gained a line for
  `spikes/`); **`findings.md` there is the #190 evidence comment, posted** as
  https://github.com/DeusMaximus/plamotrack/issues/190#issuecomment-5538814198 (owner's call). Phase A
  (in-process, no network): raw child + parent well-known route tables — exactly §5.5's four;
  the response profile per route; the redirect-binding matrix (every §5.6 claim reproduced:
  pattern replaces registration, synthesised upstream-id client → consent for any URI) and the
  **thin constraint** (`BoundProxy`, 15 lines: registration AND allowlist, upstream id refused).
  Phase B: **Keycloak 26.6.4** (realm import, `basic` scope needed for `sub`) + **MCP Inspector
  2.5.0** (DCR public client, callback `http://127.0.0.1:6274/oauth/callback`, negotiated MCP
  2025-11-25, requested only the PRM from the 401 pointer + path-aware AS doc — **never the bare
  `openid-configuration`**); scripted client end to end; **T13 matrix**: same store+key → refresh
  200 / 0 registrations; empty store or other key → 401 `invalid_client` (the DCR record is in
  the store) → clients relink, nothing else lost. **Postgres adapter proven** (py-key-value-aio
  `PostgreSQLStore` over asyncpg, one table `mcp_oauth_state`, values Fernet-encrypted, link →
  restart → refresh 200). Phase C: packaged nginx (built from `frontend/`) in front of the probe —
  the family-8 T2 surface matches §5.5 except two new facts: nginx **301**s the slash-less
  `/.well-known/oauth-protected-resource/mcp`, and `PUT /mcp/authorize` is Starlette's 405 +
  `Allow` (#206's family-8 sibling). **Then the owner-supplied legs, same session**, through a
  Cloudflare tunnel `https://testing.gunp.la` → the packaged nginx (built from `frontend/`, tunnel
  host in its allowlist) → the probe: **Google** (`verify_id_token=True`; scopes come back as
  URIs so require `openid` only, else 403 `insufficient_scope`; **no refresh token without
  `access_type=offline&prompt=consent`**), **Claude web = CIMD**
  (`https://claude.ai/oauth/mcp-oauth-client-metadata`, callback `…/api/mcp/auth_callback`;
  it **strips the trailing slash and posts to bare `/mcp`** — source-run it stalled on a
  404/no-pointer fallback chain, so nginx's rewrite is load-bearing), **ChatGPT web = CIMD**
  (per-connector `client.json`, callback `chatgpt.com/connector/oauth/<id>`; it reads the
  **path-aware `openid-configuration/mcp`** after 404 on the pruned child alias). Nobody used
  the bare OpenID document or the upstream-client-id path.
- **Decisions (proposed in `findings.md` §10, not yet in `docs/design.md`):** CIMD **on** (both
  web clients chose it), the synthesised upstream-id client refused, the allowlist narrows DCR
  only; path-aware OpenID doc kept, bare one pruned; bare `/mcp` is a client-facing spelling; Postgres adapter
  for proxy state, table owned by Alembic, backup set becomes DB + `.env`; explicit
  `MCP_OAUTH_SIGNING_KEY` as 32 random bytes (the default store crashes on non-UTF-8 key bytes,
  so always pass `client_storage`); `verify_id_token=True` as the one verifier shape (Google's
  access tokens are opaque; proven on Keycloak); **owner binding at issuance** via an
  `exchange_authorization_code` override (the verifier alone refuses a stranger only at the first
  MCP call — they still get a token pair); refuse a token without `sub`; **the MCP scope
  vocabulary is the IdP's** — `collection:*` cannot be per-grant scopes on 3.4.5 without
  translating both directions (outbound is a private method) → fixed rw mapping for every
  proxy-issued token; CIMD off until a named client needs it; FastMCP token lifetime = upstream
  `expires_in` (Keycloak 300 s) unless pinned.
- **State:** `main` at `4366695` + this entry, `.agents/README.md` edited, `.agents/spikes/190/`
  untracked (its `.gitignore` keeps `secrets.env` — the owner's Google client — plus stores,
  state and key out); **nothing committed** (owner's call). Spike containers: Keycloak stopped
  (realm inside), nginx spike stack removed, image `plamotrack-web-spike` kept, scratch DB
  dropped; ports 8000 / 8001 / 6274 / 8082 free. The tunnel `testing.gunp.la` → `10.86.64.128:8000`
  route has been deleted by the owner; both web-client connectors removed (the Claude one may
  linger as "Reconnect" — harmless, points nowhere). No code change in
  `backend/` or `frontend/`. Dev DB still claimed with `e2e-owner-password`.
- **Next:** (1) owner closes #190 when satisfied; (2) the §5 amendments (`findings.md` §10) and #192 (M6-7) on a
  branch: CIMD on, owner binding at issuance, Postgres store under Alembic, fixed rw scope
  mapping, Google's two parameters, bare `/mcp` carrying the pointer; (3) #193 audit / rate
  limiting can run in parallel (family-8 `limit_req` on `authorize` matters more now that the
  proxy fetches CIMD URLs); (4) **LXC stays put until M6 is finished** (owner, 03/09).

## 2026-09-04 — Claude Code (Fable 5.1) — #204 (M6-3b) MERGED (PR #205 → `70d6b3d`, Codex round 2 GO); f13- fold-in MERGED (PR #207 → `4366695`)

- **Done:** Codex round 2 (GPT 5.6 Sol) on `388de0b`: **GO, no findings** — replayed f1–f3, instrumented
  the gate's session order (open → resolve → commit/rollback → close → router/render, so "no
  overlap" holds), confirmed #206 as the right family-7 cut. PR #205 squash-merged as `70d6b3d` on
  the owner's call, branch deleted, **#204 closed**. Shipped: `app/auth/prerouting.py` (the
  pre-routing gate), `PROTOCOL_NAMESPACES` + `iter_dispatch_order` in the registry, the dependency
  reusing the stashed principal, T2 family-13 rows, `tests/test_auth_unrouted.py` (106).
- **Decisions:** none new; the nine deliberate calls are recorded in design §5.9 item 3(b) (i)–(vi)
  and on the PR. `.agents/lessons.md` owes nothing: the family-8 miss is the sweep rule as written
  (enumerate the families the ingress forwards, not just the ones with routes) — the hand-off
  entries below carry the case.
- **State:** `main` at `4366695` plus this entry. Backend 1866, frontend 485, e2e 43+1 (CI). The
  shipped app: anonymous unrouted / wrong-verb / malformed requests under `/api/` are 401 with the
  bare `Bearer` challenge; `/.well-known/*` stays the router's 404 until M6-7; `/mcp/*` untouched.
  The f13- fold-in landed as **PR #207 → `4366695`** (harness-only, no external review): `PRE`
  path constant, `TEST_FILES` + `tests/test_auth_unrouted.py`, `-k f13-` → all 15 killed on a
  clean tree; procedure doc: 368 cases over thirty-two files. Dev DB
  claimed with `e2e-owner-password`. No release cut — M6 ships as one release at the end.
- **Next:** (1) #190/#192 MCP OAuth spike (§5.9 item 5); (2) #193 audit/rate limiting (item 8);
  (3) #206 (family-7 `Allow` to anon) rides with whichever of those touches the
  mount; (5) **LXC stays put until M6 is finished** (owner, 03/09). Release-notes items for the M6
  release: `ALLOWED_HOSTS` lockout risk (M6-1); the instance comes up unclaimed (M6-3); `/mcp/`
  requires a PAT, wrong password / setup token is 403, never a token in a URL (M6-4); anonymous
  probes under `/api/` are 401, not 404/405/422 (M6-3b).

## 2026-09-04 — Claude Code (Fable 5.1) — #204 (M6-3b) PR #205: Codex round 1 (NO-GO, 3×P3, record only) addressed at `5df44bc`, round 2 pending

- **Done:** Issue **#204** filed (M6 milestone) for §5.9 item 3(b)'s two deferred items, then the
  branch. The fix is **the pre-routing gate** `app/auth/prerouting.py`: one middleware directly
  above `ResponseProfileMiddleware`, inside the ingress guards, that resolves the principal once
  per REST request (own short session), stashes it on `request.state` (the dependency reuses it —
  one lookup per request, pinned by counting), and refuses `anon` with the dependency's 401
  envelope (bare `Bearer`, `no-store`, no `Allow`) wherever the router would answer 404, 405 or a
  scoped 401 — read off the registry's `iter_dispatch_order` walk + `compile_path`, never the URL.
  Never grants; the dependency stays the authority. Calls recorded in design §5.9 item 3(b):
  anonymous families keep their 405/422; `INTERNAL` admitted on full, refused on partial; the
  `/mcp` mount is the child's; bare `/mcp` at the source-run app is now 401 anon / 404 owner;
  **family 8's `/.well-known/` namespace passes through** (`PROTOCOL_NAMESPACES`, derived from
  the family-8 `API_ALIAS_REJECTIONS` entry) — the first head's sweep missed it and CI
  Integration's three root-discovery T2 rows (404 until M6-7) went red with the gate's 401.
  Also: `ingress_matrix.py` trailing-slash rows → family-13 rows (+ `/api/no-such-route`,
  `DELETE /api/kits`); design §5 header + family-7 row; AGENTS.md rule 13 paragraph.
- **Round 1** (Codex, GPT 5.6 Sol, on `543f4eb`): NO-GO, three P3s, no bypass, calls 1–9 accepted.
  f1 `resolve_principal` docstring still said pre-gate session contract → rewritten; f2 the
  "two audit rows under double resolution" witness for f13-6 was false (a revoked token is refused
  at the gate, never reaches the dependency) → the count test is the kill, prose corrected in
  comment/test/design/PR body; f3 PR-body trailing total 1857 → 1866 (CI). All at `5df44bc`,
  runtime unchanged since `dfd6e16`. Reply posted; PR body has a round-1 section.
- **Decisions:** the gate renders through `domain_error_handler` passed in by `create_app` (one
  envelope author, no circular import). `PUT /mcp/` → 405 with `Allow` to anon (the
  `RouteBinding`): Codex classed it same disclosure class, different boundary → **filed as #206**
  (family-7 follow-up, non-blocking).
- **State:** **PR #205** open at `dfd6e16` (gate `ec77ff8`, hand-off `1912fbe`, family-8 fix). New
  suite `tests/test_auth_unrouted.py` **106 green**; negative control on unfixed `main` (trimmed
  copy, worktree, own DB) **23 red / 73 green**, every red an anon-side 404/405/422; **15 hand mutants
  f13-1…15 all killed** (runner + verdicts in the session scratchpad; tuples in the PR-body draft
  `scratchpad/pr-body-204.md`, to be folded into `mutation_test.py` by the usual harness-only PR
  after merge). Auth/ingress suites green; full backend run **1855 green** at `ec77ff8` (before the last pins) → 1866 by count at the head; CI Backend and Frontend green at `1912fbe`, Integration red there on exactly the family-8 rows (fixed at `dfd6e16` — check `gh pr checks 205`). T2's new rows are
  CI Integration's to prove (packaged stack not run locally — `up` would recreate the dev `db`).
  Dev DB still claimed with `e2e-owner-password`.
- **Next:** (1) **Codex round 2** on `5df44bc` (findings from 4) → expected GO; (2) on GO, merge
  (`Closes #204`), then the f13- fold-in PR; (3) #190/#192 OAuth spike; (4) #193 audit/rate
  limiting; (5) **LXC stays put until M6 is finished** (owner, 03/09). Release-notes items for the
  M6 release unchanged plus: anonymous unrouted/wrong-verb/malformed requests under `/api/` are
  401, not 404/405/422.
