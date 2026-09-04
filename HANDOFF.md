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

## 2026-09-04 — Codex (GPT-5.6 Sol) — #193 PR #208 open; ready for external review

- **Done:** rebased `codex/193-audit-rate-limit-log-hygiene` onto `main` `a642d0b` after
  the #190 spike archive, preserving #204's pre-routing gate; opened PR #208. M6-8 adds
  Host/Origin audit recording and audited pruning; explicit anonymous/internal actors; trusted
  client-address propagation through the bundled nginx and FastMCP verifier; four independent
  nginx limit zones for families 2/3/8/9; and a non-vacuous full-login/PAT/MCP container-log scan.
  The PR body carries the numbered calls, negative control, and exact hand-mutant table.
- **Decisions:** nginx owns the external `TRUSTED_PROXIES` walk and overwrites its private address
  header on all seven proxy paths; only the unpublished Compose API trusts it. Rate maps read
  `$request_uri` because `/api/` rewriting precedes nginx's limit phase. Retention is explicit,
  strict-before, and self-auditing. No migration: #187 supplied the table. `auth.oidc_rebound` is
  reserved until OAuth ships. #206's family-7/family-8 `Allow` disclosure remains separate.
- **State:** PR #208 is open at feature head `20eb1d0` plus this hand-off commit; CI is running.
  Post-rebase: backend **1878 passed**, ruff/format green; frontend lint + **485 tests** + build
  green. Changed-test negative control on `main` `a642d0b`: **14 red / 2 green**; branch 16/16.
  All **16** single-site `aud-` hand mutants killed. Packaged matrix previously passed with all
  four 429s, zero failures, and password/PAT/session absent from non-vacuous logs. Packaged stack
  is stopped; dev Postgres is healthy on loopback and claimed with `e2e-owner-password`.
- **Next:** wait for CI, then give the prepared round-1 brief to GLM 5.3 Flash (different family
  from the Codex author); reproduce and answer every finding before another round. After merge,
  fold `aud-1…16` into `mutation_test.py`. The LXC stays put until M6 is finished.

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
## 2026-09-04 — Codex (GPT-5.6 Sol) — #193 rebased onto #205/#207; post-rebase verification green

- **Done:** implemented M6-8 on `codex/193-audit-rate-limit-log-hygiene`: Host/Origin audit
  recording plus audited retention CLI; explicit anonymous/internal audit principals; resolved
  client identity through trusted proxies and the bundled nginx; revoked-PAT MCP audit address
  propagation; independent nginx `limit_req` zones for families 2/3/8/9; full
  setup→logout→password-login/PAT/MCP log-hygiene scan; operations/design/process docs updated.
  The packaged test exposed and fixed two nginx traps: `limit_req` takes `zone=...` (not a key
  argument), and the maps must read `$request_uri` because `/api/` rewrites `$uri` before the
  limit phase. The local feature commit was rebased onto `main` at `916a337`, after #205 and its
  f13- harness fold-in #207 merged; the pre-routing gate and audit middleware both remain.
- **Decisions:** nginx performs the external `TRUSTED_PROXIES` walk and overwrites the internal
  client-address header on all seven proxied paths; only the unpublished compose API enables
  trust in it. Source runs leave that flag false. The bundled default-server Host 421 is an nginx
  access-log event because it never reaches the API; the app's repeated Host refusal is the
  database event. `auth.oidc_rebound` is reserved now; the OIDC item emits it when that flow exists.
- **State:** original commit `9f4b204` was fully green before rebase: backend 1772; focused
  security 286; frontend lint + 485 tests + production build. After rebase: ruff/format/render
  green; combined auth/audit/ingress 556 passed; packaged matrix 0 failures, including #204's
  family-13 rows and all four 429s; password/PAT/session absent from non-vacuous logs. Packaged
  stack is stopped; dev Postgres is healthy on loopback and claimed with `e2e-owner-password`;
  no disposable matrix PAT remains live.
- **Next:** push/open a PR only on the owner's instruction, run the security review loop, and fold
  resulting mutants after merge. #206 (family-7 `Allow` disclosure) is still open. The LXC stays
  put until M6 is finished.
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
