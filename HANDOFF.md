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

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 1 (NO-GO, 5 findings) answered on the branch — head `e248a4b`, reply posted (issuecomment-5545491101), PR body amended

- **Done:** all five findings reproduced at `4bd2e88` on their own assertions, then fixed as one
  state machine (`app/auth/mcp_oauth.py`): **f1** `revoke_token` removes the grant record first
  (JTI mapping, upstream set, refresh hash) then revokes the provider's refresh token through the
  injectable client (`auth.mcp_grant_revoked`); **f2** `_one_redemption` — a per-handle
  transaction-scoped advisory lock (`_GrantLock`, class-based: the SDK's `TokenError` is a frozen
  dataclass and dies in a generator CM) around the code and refresh exchanges; **f3** the owner
  binding is grant state (`OwnerBinding` in `upstream_claims`, `_extract_upstream_claims`,
  `IdTokenOwnerCheck.still_bound` per request in `load_access_token`; `GrantVerifier` is FastMCP's
  hook, the upstream token bounds the grant); **f4** `RouteBinding` stamps a handler's 500,
  `ClientMetadataBody` gives a non-JSON registration RFC 7591's 400, nginx `@rate_limited` 429 in
  the envelope (`ingress.rate_limited` — error_codes + fixture + en-AU catalogue), matrix rows
  fixed/added (mode-aware challenge, revoke 401, three register bodies, the burst run last);
  **f5** the three upstream-endpoint attributes are properties over `OidcProvider.cached_metadata`
  and `_handle_consent` resolves first. Config comment (call 3) corrected. Docs: design §5.5 row,
  §5.6 outage bullet, §5.8 audit list, §5.9 (b)(d)(e)(f)(f′)(j); operations (ending a link);
  AGENTS.md rule 13; `.agents/testing-and-review.md` (448/34, moa paragraph, gate burst);
  `.agents/lessons.md` → "Overriding the entry points, not the state machine (#212, round 1)".
- **Decisions:** the lock, not a claim row (keeps FastMCP's minting as the one path; upstream
  failure leaves the refresh token retryable); RFC 6749 revoke-on-code-reuse deliberately not
  done (a retrying client is the realistic second use); the binding in the proxy's own JWT rather
  than a stored grant row; the REST-side unhandled-500 profile (the sweep's find) closed in the same branch — `unhandled_error_envelope` in `main.py`, moa-48.
- **State:** backend **2046 green** (`test_mcp_oauth.py` 90, was 69), lint/format clean,
  `render_ingress.py --check` clean, frontend build/lint/catalogue green. Mutants: moa-4/6/10/11/23
  re-anchored, moa-12/14/15 re-pointed at the cold-start tests, moa-34…48 added — **46/46 killed (42 first pass; moa-12/14/15 after the cold-start witnesses were written, moa-47 after the store assertion, moa-48 with its test)**. Packaged matrix from this tree: local **0
  failing** (71 rows incl. the burst), **OIDC 0 failing** against the Keycloak spike through a
  loopback socat sidecar in the api container's netns (scratchpad `compose.oidc.yml` — not
  tracked; `.agents/spikes/190/` is where such an overlay would live if kept). Packaged
  api/web/sidecar stopped, dev `db` up, Keycloak spike up. Siblings drafted, filed as #213 (A) and #214 (B): (A)
  explicit-vs-transparent refresh race on a rotating provider, (B) `rebind-oidc` purging
  `mcp_oauth_state`. LXC untouched (**stays put until M6 is finished**).
- **Next:** (1) Codex round 2 on PR #212 at `e248a4b` (brief from `.agents/review-brief.md`;
  push on f2's lock-vs-claim call, f3's binding-in-JWT, the `GrantVerifier` shell); if GO, merge
  with `Closes #192`; (2) after merge nothing to fold in (tuples tracked); (3) #193, M6-9 TLS docs,
  the M6 release (gate: `ingress_matrix.py --mode oidc` + the burst), then the LXC upgrade.

## ## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) MCP OAuth on `feature/m6-7-mcp-oauth` — **PR #212** open (runtime head `4bd2e88`), Codex round 1 next, in a new session

- **Done:** the whole of #192 on the branch, committed as `4bd2e88` and pushed on the owner's call; **PR #212** opened from the body drafted this session (12 deliberate calls, the mutant paragraph, the live check).
  `app/auth/mcp_oauth.py` — `PlamotrackOAuthProxy` over FastMCP's `OAuthProxy` (not `OIDCProxy`,
  whose constructor fetches discovery synchronously): owner binding **at issuance**
  (`exchange_authorization_code` → `invalid_grant` + `auth.mcp_identity_refused`, nothing minted)
  and per request (`OwnerBoundIdTokenVerifier`: the id_token through `validate_id_token_claims`
  with the new `nonce=None`, then `(iss, sub)` against the owner row); the two `OIDCProxy` hooks
  that make the id_token the verified token; lazy upstream endpoints from `OidcProvider.metadata()`
  at authorize/callback/refresh/revoke; `BoundDCRClient` (registration *then* allowlist), the
  upstream-id client refused, CIMD by its document; PATs routed to their verifier on the OIDC-mode
  mount (the mount requires no OAuth scope; `valid_scopes=["openid"]` is what is advertised); the
  Postgres state store (`mcp_oauth_state`, migration **`d5e9362140ea`**, Alembic-owned DDL, Fernet
  under an HKDF of `MCP_OAUTH_SIGNING_KEY`); root discovery routes on the parent (bare OpenID pruned),
  `NotInThisMode` stubs for the nine paths in local mode, `declare_child_verbs`. Registry:
  `ProtocolRole`, `RoutePolicy.role`, `DISCOVERY_ROUTES` + `MCP_OAUTH_ROUTES` by path, the
  protocol-namespace build check; the gate decides `/.well-known/` first (no principal resolved,
  route or no route). Settings: `MCP_OAUTH_SIGNING_KEY` (64 hex, required in OIDC mode),
  `MCP_OAUTH_ALLOWED_REDIRECT_URIS`; **OIDC mode now requires an https or loopback
  `PUBLIC_BASE_URL`** (RFC 8414 via the SDK). Audit: `auth.mcp_grant_issued`,
  `auth.mcp_identity_refused`. nginx: slash-less PRM path → 404 (not 301), `limit_req` on
  authorize/token/register. `ingress_matrix.py --mode local|oidc` + `family_8_rows` (24 rows);
  run green (0 failing) against the packaged stack built from this branch, local mode. Docs:
  design §5 header/§5.5/§5.6/§5.8/§5.9 items 5+7 ("Shipped" calls (a)–(i)), operations (new MCP
  OAuth section, config rows, backup note), `.env.example`, README, AGENTS.md rule 13,
  `.agents/testing-and-review.md` (OIDC matrix as a release-gate step; moa- paragraph, 434/34),
  `.agents/lessons.md` ("Building on the parent of the class the spike measured").
- **Decisions:** on PR #212's body ("Deliberate calls" 1–12) and design
  §5.9 item 7 — notably: https-or-loopback in OIDC mode rather than a degraded third state; the
  allowlist applies to **every** client kind when set (FastMCP re-checks it at the callback where
  the kind is unknown), documented rather than special-cased; `HEAD` declared on no protocol route;
  `access_type=offline&prompt=consent` forwarded to every provider; `/revoke` registered
  unconditionally. Reviewer for the PR: **Codex** (M6 security work, per the roster).
- **State:** backend **2024 green** (`tests/test_mcp_oauth.py` **69**, fake provider
  moved to `tests/oidc_fake.py`, OIDC tests' `BASE` → `http://localhost`), lint + format clean,
  `render_ingress.py --check` clean, frontend untouched (nginx template only). **32 `moa-` mutants
  queued in `mutation_test.py` and hand-run: 32/32 killed** — three first-pass survivors were test
  gaps, now tests (moa-1 the upstream-id refusal shadowed by the registration binding on loopback
  rows; moa-15 no refresh-first-in-a-fresh-process test; moa-25 the verbs test read its expectation
  off the registry). Dev DB at `d5e9362140ea` (the packaged migrate ran it); its owner is still
  bound to the Keycloak `owner`; **the live run against the real Keycloak is done and green**:
  the API source-run in OIDC mode on `http://127.0.0.1:8000` (a scratchpad runner for this
  session; `.claude/launch.json` reverted), a DCR client registered, authorize → consent → the
  owner's Keycloak sign-in → callback → `POST /mcp/token` 200 (`expires_in` 3600, `scope`
  `openid profile email`, `no-store`) → MCP initialize 200 → `list_kit_series` answered → the same
  token on `GET /kits` 401 `invalid_token` → refresh 200 → one `auth.mcp_grant_issued` row
  (`mcp:write`, `client=<dcr id>`), five state collections in `mcp_oauth_state`. One trap met on
  the way, worth knowing: the consent transaction lives 15 minutes, so a sign-in long after
  "Allow" is FastMCP's "Invalid or expired authorization transaction" 400 at the callback —
  start over from `/mcp/authorize`, not from the provider. Packaged `api`/`web` containers stopped, dev `db` up. Keycloak
  spike container up. LXC untouched (**stays put until M6 is finished**, owner 03/09).
- **Next:** (1) **Codex round 1 on PR #212, in a new session** (this one closed at ~77%
  context): the brief was printed in this session's chat and is not stored — regenerate it from
  `.agents/review-brief.md` (Codex footer) if needed; the runtime head is `4bd2e88` (every commit
  after it on the branch is a hand-off entry — brief at the branch tip and say so), `main`
  `a497481`, rules 1/6/7.1/9/11/12/13 in play; answer findings per `.agents/testing-and-review.md`
  → "Responding to a review"; if GO, merge with `Closes #192`. Where to push: call 1 (https-or-loopback), call 3 (allowlist on
  every kind), the `_handle_idp_callback` private override, the `mcp_oauth_state` DDL parity with
  the store's, the mount requiring no scope; (2) the live Keycloak run's output above is what the PR body's
  "Live check" reports; the `stranger` refusal path was not driven live (the suite covers it);
  (3) after merge nothing to fold in — the tuples are already tracked; (4)
  #193 audit/rate limiting (the app's budget for `/mcp/token`; the ingress `limit_req` landed
  here); (5) M6-9 TLS docs, the M6 release (gate now includes `ingress_matrix.py --mode oidc`),
  then the LXC upgrade. Release-notes items so far: `AUTH_MODE=oidc`; the mode switch sign-out;
  the setup token once on local→oidc; `session.auth_mode`; **`MCP_OAUTH_SIGNING_KEY` required in
  OIDC mode and OIDC mode needs an https `PUBLIC_BASE_URL`**; MCP clients can link by signing in.

## 2026-09-05 — Claude Code (Fable 5.1) — #191 (M6-6) MERGED (PR #209 → `b84f757`, Codex round 3 GO); oidc- fold-in MERGED (PR #211 → `ffaddd4`)

- **Done:** Codex round 3 (GPT 5.6 Sol) on `59eb9a4`: **GO, no findings**. PR #209 squash-merged
  to `main` as `b84f757` (`Closes #191` — issue closed), branch deleted. Then the usual
  harness-only fold-in, PR #211 → `ffaddd4`: 34 `oidc-` cases in `backend/mutation_test.py`
  (constants `OIDC_SVC`, `AUTH_ROUTER`, `MODE`; `TEST_FILES` + `tests/test_auth_oidc.py`;
  procedure count 368/32 → 402/33 with the oidc- paragraph). Not folded: oidc-1/2/3/11
  (anchored on the joserfc registry round 1 replaced; superseded by 23/22/27/26) and oidc-13
  (equivalent — no symmetric key in the JWKS); oidc-20 and oidc-25 re-anchored. `-k oidc-`
  all 34 killed on the fold-in head, no external review (the #199/#201/#203/#207 precedent).
- **Decisions:** owner's — #192 (M6-7, MCP OAuth) starts in a **new session** (context, not
  scope); this session closes here. Memory (agent-side): the owner switches sessions at
  ~80–90% context after a hand-off update and never relies on compaction.
- **State:** `main` at `ffaddd4` + this entry; tree clean. Backend 1949 green at the merge,
  frontend 487. Dev DB at `4f3a9c1e7b2d` (head), owner bound to the Keycloak `owner` user
  (spike realm) in OIDC mode and still holding the local credential — note the migration
  stamped its existing sessions `local`, so the next OIDC-mode start of the API signs that
  browser out once (sweep + `auth.mode_changed` row); local-mode starts are unaffected.
  Keycloak spike container state as the #190 entry left it (`.agents/spikes/190/`, tracked at
  `a642d0b`). The LXC is on the pre-M6 reset and **stays put until M6 is finished** (owner,
  03/09) — it will need `ALLOWED_HOSTS` and, if it ever switches modes, expect the one-time
  sign-out.
- **Next:** (1) **#192 (M6-7) MCP OAuth** on a branch off `main` — build from design §5.9
  item 7 and the #190 spike's decisions (`.agents/spikes/190/findings.md` §10: CIMD on,
  synthesised upstream-id client refused, allowlist narrows DCR only, path-aware OpenID doc
  kept and the bare one pruned, Postgres adapter for proxy state with the table owned by
  Alembic, explicit `MCP_OAUTH_SIGNING_KEY`, `verify_id_token=True`, owner binding at
  issuance, fixed rw scope mapping); same issuer/client as #191, so `services/oidc.py`'s
  provider/discovery is the thing to reuse, and family 8's registry declarations + the
  generated ingress rejections are where `test_route_policy.py` / `test_ingress_generation.py`
  will push back first; (2) #193 audit/rate limiting; (3) M6-9 TLS docs, then the M6 release
  (gate in `.agents/testing-and-review.md`) and only then the LXC upgrade. Release-notes
  items so far: `AUTH_MODE=oidc`; a mode switch signs every browser out at the first start in
  the new mode; a local→oidc switch needs the setup token once; `session.auth_mode` migration.

## 2026-09-05 — Claude Code (Fable 5.1) — #191 (M6-6) PR #209: Codex round 2 (NO-GO, 2×P3) addressed at `59eb9a4`, round 3 pending

- **Done:** Codex round 2 (GPT 5.6 Sol) on `083ad08`: NO-GO, two P3s, no P1/P2, round-1 P2s
  confirmed closed, calls 3/6/11/12 not overruled (its provider survey backs call 12's no
  trusted-audience list). **f3 — non-finite NumericDates:** `_numeric_date` in
  `services/oidc.py` now names the value domain — an `int` (never the bool) on its own branch,
  or a `float` that `math.isfinite` — because JSON cannot spell NaN/Infinity (RFC 8259 §6)
  but Python's parser admits them and every clock comparison against NaN is false.
  Reproduced first: nine shapes (NaN, ±∞ on each of `exp`/`iat`/`nbf`) added to the matrix,
  six opened a session at `083ad08`; a pinned-clock unit test drives all nine plus the
  positive side (`10**400`, negative huge ints, float instants). Mutant **oidc-39** (finite
  condition removed) killed by `[exp-nan]`. Design §5.9 (f) says "finite". **f4 — PR body
  provenance:** Tests intro 35 → 70 → 80 by round; the Negative-control paragraph now carries
  the reviewed-head baselines (`910a335`: 14 red / 56 green; `083ad08`: 7 red / 3 green) and
  the matrix count (41 refused + 4 accepted), oidc-39 row and tuple.
- **Decisions:** the domain is stated at the predicate, not by a JSON-strictness layer under
  joserfc — the three time claims are the only numerically compared values, and the predicate
  is the one place that admits them.
- **State:** backend **1949 green**, `tests/test_auth_oidc.py` **80**, frontend untouched
  (487), lint clean; tree clean at `59eb9a4` + this entry, both pushed. Reply posted on PR #209;
  body amended. Dev DB at `4f3a9c1e7b2d`. Round-1 state still true: `session.auth_mode` +
  start-up sweep (`auth.mode_changed`), one claim validator, migration `4f3a9c1e7b2d`.
- **Next:** (1) Codex **round 3** on PR #209 — brief per `.agents/review-brief.md` (Codex
  footer) at the new head, pointing at the round-2 reply; if GO, merge with `Closes #191`;
  (2) after merge, fold oidc-1…39 into `mutation_test.py` (1/2/3/11 superseded by 21–30);
  (3) #192 (M6-7) on top; (4) #193; (5) **LXC stays put until M6 is finished** (owner, 03/09).
  Release-notes items unchanged: `AUTH_MODE=oidc`; a mode switch signs every browser out at the
  first start in the new mode; a local→oidc switch needs the setup token once.

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
