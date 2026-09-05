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

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 4 (GPT-6, NO-GO: 2×P2/P3, the client-auth boundary) answered on the branch — head `139b26e`, reply posted (issuecomment-5549077553), PR body amended, round-5 brief printed

- **Done:** per Codex's own brief to the owner (contract first, tested from the wire, SDK
  ownership audited, grant machinery untouched). **The contract** (design §5.9 item 7 (k),
  AGENTS.md rule 13, the module docstring): every dynamically registered client is **public**
  (`none` + PKCE) whatever it asked for and the registration response says so — no secret, no
  expiry; a CIMD client authenticates as its document says (`none` / `private_key_jwt`) on
  `/token` **and** `/revoke`, the assertion bound to the endpoint; wire forms are the RFCs'
  (`client_id` in the form for every kind, no secret from a public client, `401 invalid_client`
  on a failed client authentication on either endpoint). Code (`app/auth/mcp_oauth.py`): **f11**
  `register_client` makes the SDK's object truthful before it is stored *or* returned (the SDK's
  handler returns that same object); **f12** `GrantRevocation` over `RevocationForm` +
  `RevocationRefused` (the SDK's steps, an optional-secret form, `invalid_client`); **f13**
  `_revocation_authenticator` = FastMCP's `PrivateKeyJWTClientAuthenticator` bound to `/revoke`.
  Tests: **new `tests/test_mcp_oauth_clients.py`, 27 rows, every request built by hand** (six
  requested methods × the lifecycle; the secret field absent/empty/stray; hint × half; CIMD
  none/private_key_jwt lifecycle; refusals on both endpoints × absent/wrong key/wrong
  audience/replayed; the missing-field rows); the lifecycle suite's `revoke()` helper now sends
  the public form (it had padded `client_secret=""` — the lesson). Negative control at
  `4b720ec`: **39 rows, 32 red / 7 green** on the findings' own assertions. Mutants: moa-61…66,
  the contract suite added to `TEST_FILES`, moa-57 re-anchored on the new handler class; **65/65 killed**. Corrections asked for by the review:
  round 3's greens are three refresh controls + four race cells (PR body); a *freshly*
  re-issued old-owner id_token ends the record, only omitted/identical carries forward (PR body
  call 5); the expired-access policy documented (design (e)). Docs: design §5.5 row 8, §5.9 (e)
  + (k) with the per-endpoint ownership audit; operations (how clients register); procedure
  moa- paragraph + count (**467/46**); lessons → "The helper that padded the form".
- **Decisions:** public-only DCR by substitution (RFC 7591 §3.2.1), not refusal — the MCP Python
  client *requests* `client_secret_post` by default; confidential DCR rejected (a credential with
  no authority behind it, plus the SDK's Basic branch to repair, plus a second matrix); one
  error code `invalid_client` on both endpoints (RFC 6749 §5.2 via RFC 7009 §2.2.1), which
  nothing in the matrix asserts; `client_id` stays required in the form beside an assertion
  (parity with FastMCP's `/token`); no packaged re-run (no route/registry/nginx change).
- **State:** backend **2094 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants **65/65 killed** (scratch runner, targets hashed, restored). Commit
  `139b26e` pushed; PR #212 body amended; the reply is issuecomment-5549077553. Codex's round-4 probes are at
  `/private/tmp/plamotrack-212-r4/` (its `test_review.py` is the 44-row matrix — not tracked,
  will not survive a reboot). Dev `db` up, Keycloak spike up. LXC untouched (**stays put until
  M6 is finished**).
- **Next:** (1) **Codex round 5 on PR #212, in a new session**: the brief was printed in this
  session's chat — regenerate from `.agents/review-brief.md` (GPT-6 footer) if needed, naming
  runtime head `139b26e`, the branch tip (hand-off commits only above it), `main` `a497481`,
  rules 1/6/7.1/9/11/12/13; findings numbered from 14; reproduce at `139b26e` first; the
  contract suite is where a client-auth finding's reproduction belongs. If GO: squash-merge with
  `Closes #192`; nothing to fold in. (2) After merge: #215 (one line in `ci.yml`), #193, M6-9
  TLS docs, the M6 release — gate `ingress_matrix.py --mode oidc` against a packaged stack with
  the Keycloak spike, the register burst concurrent — then the LXC upgrade; relink any MCP
  client first (records written before `e90550f` carry no binding and end at their next refresh).

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 3 (GPT-6, NO-GO: P2/P3) answered on the branch — head `4b720ec`, reply posted (issuecomment-5547333495), PR body amended, round-4 brief printed

- **Done:** both findings reproduced at `e90550f` on their own assertions (the 12 new rows written
  first: **5 red / 7 green** — f9's two access-token rows and the rebound-owner sibling red on the
  record still present behind the 200, f10's two paths red on `200 == 401`; the four refresh-token
  rows and the race test's four cells green), then fixed one step to either side of round 2's gate
  (`app/auth/mcp_oauth.py`): **f9** the `/revoke` route is built over `RevocationLookup`
  (`get_routes`, FastMCP's own seam) — the SDK's handler and client authenticator given a provider
  whose access-token lookup is `locate_access_token`: the proxy's signature, the client id and
  binding from the claims, the JTI mapping; no provider call, no upstream set, no owner row — so
  the locked ending in `revoke_token` runs whatever the provider is doing; `load_access_token` and
  the `unavailable` policy for requests unchanged. Sibling closed by the same change: a client can
  end a grant the owner row no longer names (the per-request `still_bound` had made that lookup
  answer `None` too). **f10** the record gate compares a verified candidate's `(iss, sub)` with the
  **record's** binding before the write — a mismatch is `_GrantRefused(identity)`, the grant ends.
  Also per the review's evidence replay: the race test's witness tightened to the `pg_blocking_pids`
  edge on the grant's own lock key (`_blocked_on_the_grant_lock`; the transparent/access cell is a
  real witness for the first time, since revocation no longer enters the transparent refresh); the
  round-2 10/4 breakdown carried into the PR body; the CI `--setup-token` argv edge filed as
  **#215**. Fake: `FakeIdp.unreachable` (per-path outage). Tests: `test_mcp_oauth.py` **111** (+8).
  Mutants: moa-57…60 added; **59/59 killed**. Docs: design §5.5 row 8, §5.9 (d)/(e); AGENTS.md rule 13;
  operations "Ending a link"; procedure moa- paragraph + count (**461/46**); lessons → "Located,
  not authorized; the record's identity, not the owner's".
- **Decisions:** a second object for the revocation handler rather than a context flag inside
  `load_access_token` (two callers with opposite failure semantics get two methods); no second
  `still_bound` under the lock for f10 (narrows the window, does not close it — the continuity
  comparison is the invariant); the rebind-mid-transition cells that re-issue the old owner's
  id_token or omit one still write the old binding forward and are refused at the next request
  (the lingering record is #214); #215 filed rather than fixed here (Codex's ask, no shared cause).
- **State:** backend **2067 green** on the final tree, lint/format clean, `render_ingress.py
  --check` clean; frontend untouched. Mutants **59/59 killed** (scratch runner past the clean-tree
  refusal, targets hashed, restored). Commit `4b720ec` pushed; PR #212 body amended to that head;
  the reply is issuecomment-5547333495. Packaged stack not re-run (no route/registry/nginx/matrix change). Dev `db`
  up, Keycloak spike up. LXC untouched (**stays put until M6 is finished**).
- **Next:** (1) **Codex round 4 on PR #212, in a new session**: the brief was printed in this
  session's chat — regenerate from `.agents/review-brief.md` (GPT-6 footer) if needed, naming
  runtime head `4b720ec` and the branch tip (hand-off commits only above it), `main` `a497481`,
  rules 1/6/7.1/9/11/12/13. Findings: reproduce at `4b720ec` first, answer per
  `.agents/testing-and-review.md` → "Responding to a review" (numbering continues from 10),
  re-verify by mutation (`-k moa-`; the scratch runner shape is in this entry's Done). If GO:
  squash-merge with `Closes #192`; nothing to fold in — every moa- tuple is tracked. (2) After
  merge: #215 (one line in `ci.yml`), #193, M6-9 TLS docs, the M6 release — gate
  `ingress_matrix.py --mode oidc` against a packaged stack with the Keycloak spike (the socat
  sidecar overlay is not tracked; rebuild under `.agents/spikes/190/` if kept) with the register
  burst concurrent — then the LXC upgrade; relink any MCP client first (records written before
  `e90550f` carry no binding and end at their next refresh).

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 2 (GPT-6, NO-GO: P1/P2/P3) answered on the branch — head `e90550f`, reply posted (issuecomment-5546424919), PR body amended, round-3 brief printed

- **Done:** all three findings reproduced at `e248a4b` on their own assertions (the 14 new
  rows written first: 10 red on `200 == 401`/`401 == 200`, 4 controls green), then fixed as
  the review's closing paragraph asked — on the **grant record**, not the transitions
  (`app/auth/mcp_oauth.py`): **f6** every transition of a grant (issuance, the refresh
  exchange, the transparent refresh, revocation) runs under one advisory lock keyed on the
  record's id (`_one_transition`/`_GrantTransition`; the per-JTI lock is gone),
  `_try_transparent_refresh` overridden as a transition whose outcome `load_access_token`
  reads (the SDK answers a failed refresh from the set it had loaded); **f7** `GrantRecords`,
  one gate on every write to `mcp-upstream-tokens` — a declared `_Transition` only, the
  record read back under the lock, the identity checked against the record's own binding
  (`GrantRecord.owner`, the digest of the id_token last verified) before the SDK's `put`;
  a stranger's or forged id_token on either path **ends the grant** (`_refuse_transition`:
  record + mapping + hash gone, `auth.mcp_grant_revoked` `ended_by=upstream_refresh` beside
  the refusal) — round 1's retry withdrawn; `unavailable` verdicts leave the grant standing;
  **f8** counts corrected to what `CASES` yields, rule stated in the procedure. Sibling
  found by the sweep and closed here (same root cause): a binding renewed by a transparent
  refresh drifted from the tokens' digest and the next exchange re-verified an expired
  id_token. Tests: `test_mcp_oauth.py` **103** (+14, −1 superseded retry test). Mutants:
  moa-49…56 added, 34/36/37/38/39/42 re-anchored — **55/55 killed** (first pass 52: moa-47 a redundant hash delete in `revoke_token` — fixed; moa-56 masked
  by the round-1 fallback in `_extract_upstream_claims` — the hook now raises on a digest the gate did
  not leave; moa-49 the fake's "same" id_token byte-identical within one second — `jti` added, the drift
  test had been red at `e248a4b` by the clock). Docs:
  design §5.5 row 8, §5.9 (d) + new (f″); AGENTS.md rule 13; operations "Ending a link";
  procedure counts (457/46 with the one-liner), moa- paragraph, roster + brief footer
  (**Codex is GPT-6 since 2026-09-05**); lessons → "The record, not the transitions".
- **Decisions:** the gate over the SDK's adapter rather than reimplementing the two refresh
  transitions (the SDK's arithmetic stays the SDK's; a future writer meets the gate or
  fails loudly); no tombstone — serialization plus the read under the lock is the boundary
  and the gate refuses undeclared writes; the binding on the record, the tokens keep theirs
  for the per-request owner-row check; terminate-and-relink on a hostile refresh response
  (Codex's "defensible policy"); call 10's concurrent burst noted for the release-gate work,
  not done (matrix unchanged this round — no route/ingress change).
- **State:** backend **2059 green** on the final tree (`test_mcp_oauth.py` 103), lint/format
  clean, `render_ingress.py --check` clean; frontend untouched. Mutants **55/55 killed** (54 in the
  final full run plus moa-47 re-run alone after its anchor moved under a new comment). Commit
  `e90550f` pushed; PR #212 body amended to that head; the reply is issuecomment-5546424919. Records written before this head have no `owner` and end at
  their next refresh (relink) — dev DB only. Packaged stack not re-run (nothing under
  `frontend/nginx/`, the registry or the routes changed). Dev `db` up, Keycloak spike up.
  LXC untouched (**stays put until M6 is finished**).
- **Next:** (1) **Codex round 3 on PR #212, in a new session** (this one closed after the round-2
  reply): the brief was printed in this session's chat and the owner pastes it — it is not
  stored; regenerate from `.agents/review-brief.md` (GPT-6 footer) if needed, naming runtime head
  `e90550f` and branch tip `ed5a7d7`+ (hand-off commits only above it), `main` `a497481`, rules
  1/6/7.1/9/11/12/13. The round-2 reply (issuecomment-5546424919) is the record of what changed
  and why; its "where I'd push" bullets were: the gate as the only writer of the record, the
  lock-plus-re-read boundary with no tombstone, the `unavailable` verdict leaving the grant
  standing, the transparent outcome reaching the request through `_Transition.outcome`, the
  `pg_locks` witness in the racing test, the fake's same-second id_token. Findings: reproduce at
  `e90550f` first, answer per `.agents/testing-and-review.md` → "Responding to a review"
  (numbering continues from 8), re-verify by mutation (`-k moa-`; the scratch runner that
  bypasses the clean-tree check on a dirty tree is trivial to rewrite: apply/run/restore per
  case, hash targets before and after). If GO: squash-merge with `Closes #192` (as #209 was);
  nothing to fold in — every moa- tuple is tracked. (2) After merge: #193, M6-9 TLS docs, the
  M6 release — gate `ingress_matrix.py --mode oidc` against a packaged stack with the Keycloak
  spike (the socat-sidecar compose overlay is not tracked; rebuild it under
  `.agents/spikes/190/` if kept) and make the register burst concurrent there (Codex's call-10
  remark) — then the LXC upgrade; relink any MCP client first, since records written before
  `e90550f` carry no binding and end at their next refresh.

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

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) MCP OAuth on `feature/m6-7-mcp-oauth` — **PR #212** open (runtime head `4bd2e88`), Codex round 1 next, in a new session

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
