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

## 2026-09-03 — Claude Code (Fable 5.1) — #187 (M6-2) auth foundation — PR #198 OPEN (foundation-first)

- **Done:** M6-2 auth foundation on `feature/m6-2-auth-foundation` (commits
  `dd7e53e`, `66a2e04`), **PR #198 open** against `main`, awaiting review. Landed
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
  (6) no-store on allowed responses (deny-envelope no-store a small follow-up); (7) nginx
  list generated, `/.well-known` declared ahead of its #192 routes.
- **State:** backend **1527 passed**, frontend **473 passed**, ruff + format clean,
  `render_ingress.py --check` up to date; migration `f1058c5de0f3` round-trips both
  directions, enum CHECKs + owner seed intact. New tests: `test_route_policy.py` (27),
  `test_auth_tables.py` (7), `test_authorization.py` (19 — T1 on the real graph + the
  plan-mutation axis), `test_ingress_generation.py` (4). **No `auth-` mutation set run** —
  queued for a fold-in after merge (principal algebra, the dependency branches,
  `plan_requires_admin`, the owner seed). Deferred acceptance criteria tracked in the PR
  body: shipped-app flip, suite-wide injection, e2e login, family-11 enforcement,
  `apply_import` wiring → **#188**; MCP tool-scope + bearer/audience → **#189**.
- **Next:** **Codex (GPT 5.6 Sol) review round on #198** — the security foundation, per the
  roster; brief prepared this session. Park the tree during the round. On GO + merge, then
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

## 2026-09-02 — Claude Code (Fable 5.1) — M6 begun: threat model MERGED (PR #185, #29 closed), ten issues filed #186–#195

- **Done:** `docs/design.md` §5 rewritten as the M6 threat model and route
  authorization matrix: current state (5.1), assets and actors (5.2–5.3), four
  deployment modes L/P/R/Dev (5.4), five principals × three scopes × thirteen route
  families with app-vs-ingress columns (5.5), fourteen threat rows + safe failure
  (5.6), what loopback keeps (5.7), the thirteen gating tests T1–T13 (5.8), a
  ten-issue implementation split (5.9); pointer edits in §4 and §11. Branch
  `feature/m6-threat-model`, **PR #185 squash-merged as `1d9b3b2` on the owner's call
  (03/09) after four Codex rounds**; branch deleted; **#29 closed**; the ten §5.9 items
  filed under `M6 — Secure remote access` as **#186–#195** (M6-1…M6-10, dependencies in
  each body); #39 noted as absorbed by #186 and left open so the fixing PR closes both;
  status note on #30. Round history: **Codex
  round 1 (GPT 5.6 Sol): NO-GO, four findings, all reproduced at `81ff6bb` and fixed
  at `414f076`**, answered per finding in the PR thread: (1, P2) `/api/mcp/*` and
  `/api/openapi.json` are live ingress aliases of `/mcp/` and `/openapi.json` → §5.5
  gains "one spelling per family" at the ingress, T2 the encoded/doubled spellings,
  split item 1 the rejection; (2, P2) a `mode=merge` import updates
  `instance_settings`, crossing the admin boundary with a write token → import
  privilege is decided on the plan's content, T1/T6 gain that axis; (3, P3) uvicorn
  0.52.1 runs its proxy-headers middleware by default (trusts `127.0.0.1`), so
  `internal` must read the raw TCP peer → `--no-proxy-headers` + app-side forwarded
  address, T9 control; (4, P3) a FastMCP child mounted at `/mcp` emits
  `/mcp/.well-known/*` and no root discovery routes → parent installs
  `get_well_known_routes(...)`, child aliases pruned, both route sets snapshotted.
  Reviewer's qualifications on calls 5/7/9/11 folded in. **Codex round 2: NO-GO,
  three P3s, all reproduced at `414f076` and fixed at `790140d`**: (5) the parent-root
  discovery routes are reachable under `/api/.well-known` by the same rewrite → that
  namespace rejected too, the rejection list derived from the route table by T2, T2
  snapshots responses not route tables; (6) Starlette 1.4.0's slash redirect builds
  `Location` from the request scheme/Host with the query intact (`/kits/` → 307
  `http://<Host>/kits` on the real app) → `redirect_slashes=False` on both routers,
  T2/T9 assert no `Location` on non-canonical spellings; (7) T13 promised `pg_dump`
  restores MCP links while split item 5 allowed a file-tree store → storage-
  independent backup contract (database + OAuth store + `.env`). Family 8's root set
  tightened to the four routes `get_well_known_routes` really emits; `add_only` named;
  family 3/9 `mcp` cells → 401. **Codex round 3: NO-GO, three P3s, all reproduced at
  `790140d` and fixed at `9e72a77`**: (8) "derive the rejection list from the route
  table" is not a property the table has (15 top-level entries, 8 `_IncludedRouter`
  without `path`, 57 effective; `/docs` vs `/openapi.json` indistinguishable) → §5.5's
  mechanism is now a **route policy registry** (family, credential policy, external
  spellings, serving layer, redirect destinations per effective route/mount) that the
  dependency, the nginx template and T1/T2 all read — the rule-9 shape applied to
  routes; (9) FastAPI's generated `/openapi.json`, `/docs`, `/redoc`,
  `/docs/oauth2-redirect` are `add_route` routes an app-level dependency never runs
  for (probed: 0 calls) → disabled and re-registered as guarded routes, the OAuth2
  helper dropped; (10) "every Location names PUBLIC_BASE_URL" would break OAuth
  (provider and client redirects are protocol) → redirects classified by destination,
  only request-derived ones forbidden, nginx's relative `/api`→`/api/` 301 retained,
  T2 rows are ingress spellings (`/api/kits/`, not `/kits/`). Also: bare `/mcp`
  ingress-only, bare `/.well-known/openid-configuration` pruned (issuer mismatch),
  T13 proved via old-client refresh + initialize. **Codex round 4: NO-GO, two P3s,
  both reproduced at `9e72a77` and fixed at `0018162`**: (11) the registry lacked a
  response policy — FastMCP's consent page and redirects carry no `Cache-Control`
  while the SDK's token/revoke do → registry gains protocol role per child route,
  effective methods, modes and a response profile; `no-store` supplied by a thin
  middleware on the mount; T1/T2/T10 extended; (12) "exact registered redirect URI"
  is false for two client classes — FastMCP synthesises a client for the upstream
  client id with `allow_unregistered_redirect_uris=True` (probed: 302 to consent for
  an unlisted URI) and an allowlist replaces rather than narrows registration →
  binding per client kind (DCR exact + RFC 8252 loopback-port exception, allowlist
  AND registration, synthesised client refused/pinned, CIMD declared), T9 one row per
  kind. Call 17 marked superseded by 19. **Reviewer's exit signal: after these
  amendments, the useful gates are a focused replay of the round-4 controls and the
  client/provider spike, not another broad wording round.** PR body lists calls
  13–23. Earlier probes stand: non-JSON / no-`Content-Type` bodies 422 on
  `POST /retailers`; FastMCP's route set read from the pinned libraries.
- **Decisions (proposed in the doc; the owner approves via the PR):** every mode
  authenticates, no `AUTH_MODE=disabled` in the image; `instance:admin` = owner
  session only, no admin PATs in M6; `/meta`, OpenAPI and docs → `collection:read`;
  `GET /auth/session` is the anonymous bootstrap; `import/preview` + `mode=merge` →
  write, `replace_all` → admin; MCP OAuth tokens audience-bound to `/mcp`, PATs valid
  on both surfaces; `/readyz` → loopback TCP peer only, nginx 404 on top;
  loopback-origin-vs-loopback-host accepted (dissolves the Vite `changeOrigin` trap);
  CSRF = `SameSite=Lax` + Origin/Referer + session token, independent of `plan_hash`;
  anonymous unrouted `/api/*` → 401; the Host/Origin guard (absorbs #39) ships as
  **its own release** before any auth; cookie `Secure`/`__Host-` only on an https
  `PUBLIC_BASE_URL`; mode P (plain HTTP, private network) supported with the
  cleartext caveat. Nothing in #30's credential thread was re-decided.
- **State:** `main` at `1d9b3b2` (+ this entry). PR #185 was docs-only — no code, no
  migration, no suites run beyond the one settings-portability control; `git diff
  --check` clean, table columns checked by script; CI green at every head including
  `0018162`; the merge commit's CI is the next thing to glance at. The packaged stack was built once for the alias replay, then `down`
  (no `-v`) and the dev `db` overlay restored — `db` is up on `127.0.0.1:5432`.
  Working tree parked on `main` for the review window. PR #184 (`ja`, draft)
  unchanged, awaiting a native reviewer.
- **Next:** (1) **#186 (M6-1)** is the first implementation branch — ingress identity
  + Host/Origin guard, `--no-proxy-headers`, `redirect_slashes=False`, the nginx
  envsubst template with the four `/api/` rejections and their positive controls;
  **its own release**, Codex-lane review, release notes leading with `ALLOWED_HOSTS`;
  the owner's LXC is reached by LAN hostname and will need `ALLOWED_HOSTS` set before
  that upgrade; (2) #187 (registry + foundation) next, then #188/#189; #190 (spike)
  can start once #186's topology exists; (3) #30 stays open as the credential
  decision — its calls land in #190/#191/#192; (3) on merge, **file the ten §5.9
  issues** under `M6 — Secure remote access` with their dependencies, close #29,
  and mark #39 absorbed by item 1; (4) the first implementation branch is §5.9
  item 1 (ingress identity + Host/Origin guard) — its own release, nothing rides
  with it. LXC: still pre-0.2.9, **back up before pulling** (two migrations
  pending) — unchanged from the 29/08 entry.

## 2026-09-02 — GPT-5 Codex (OpenAI) — PR #184 Japanese editorial review completed

- **Done:** Finalised the disabled Japanese catalogue on PR #184 at `0470285`.
  Corrected the value-dependent withdrawal prompt for both the empty and
  preformatted `(×N)` suffixes; completed the 注文明細/CSV 行 terminology
  distinction; and applied Fable 5's remaining high-confidence wording fixes.
  Added a value-level catalogue regression test and pushed the commit to
  `feature/ja-localisation`.
- **Decisions:** Keep `ja` disabled until a native Japanese hobbyist reviews the
  rendered application. Settled terms remain: インベントリ, 購入先, 追加パーツ,
  ディスプレイ用品 and 受領済み. Further LLM-wide rewrites would be churn.
- **State:** PR #184 remains open as a draft at exact head `0470285`. Frontend
  **470 passed**, focused catalogue **286 passed**, lint and production build
  green, and coverage **604/604** for both catalogues. The old withdrawal copy
  failed the new control on the empty suffix; byte-identical restoration was
  verified. Rendered Japanese checks passed for quantity 1/2 withdrawal,
  expanded order details/totals, and a blocking import diagnostic. Japanese was
  restored to disabled; disposable DB, preview hook and servers were removed.
- **Next:** Native Japanese hobbyist review. Do not enable or merge the language
  solely on the LLM reviews; action any human findings on this same PR first.


## 2026-09-01 — Gemini 3.1 Pro (High) (Google) — Initial Japanese localisation (disabled)

- **Done:** Created an initial Japanese translation catalogue `ja.json` mapped from `en-AU.json`, registered it as a disabled language in `manifest.json`, and exposed it in `registry.ts`. Validated the changes using the contributor checks. Pushed to `feature/ja-localisation` and opened draft PR #184. Fixed NO-GO review findings from GPT 5.6 Sol (P3-1 through P3-6) at head `0d3dbf9`.
- **Decisions:** Followed all translator documentation guidelines: kept all identifier variables exactly intact, translated to natural polite Japanese (Desu/Masu), strictly used `_other` for plurals according to CLDR rules, and left no English text purely for coverage padding.
- **State:** PR #184 is open as a draft. `ja` is currently disabled pending a native language and rendered view review. All checks (`npm test`, `lint`, `build`, `git diff --check`) passed locally. Head is `0d3dbf9`.
- **Next:** Await independent structural and Japanese-language review of PR #184 before any enablement.

---
