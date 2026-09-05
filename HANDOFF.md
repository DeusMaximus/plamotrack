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

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 5 (GPT-6, NO-GO: P2/P3, discovery + the hint) answered on the branch — head `8cae6c7`, reply posted (issuecomment-5549456569), PR body amended with a **coverage record**, brief template changed, round-6 brief printed

- **Done:** **f14** discovery owned by the contract — `discovery_metadata` (SDK `build_metadata`
  + FastMCP's CIMD flag + `CLIENT_AUTH_METHODS`/`CLIENT_ASSERTION_ALGORITHMS`), served by
  `get_routes` on the AS route (the root documents are that list filtered): both spellings
  publish `["none","private_key_jwt"]` for `/token` and `/revoke` and `["RS256"]`; **f15**
  `RevocationForm.token_type_hint: str | None` — a recognised value chooses order, anything
  else is ignored (RFC 7009 §2.2). Tests: contract suite **34** (+7: hints `""`/unknown × 2,
  both discovery spellings pinned to literals, an ES256 assertion under a CIMD EC key refused);
  control at `139b26e`: **34 rows, 6 red / 28 green**. Mutants moa-67…70, moa-57 re-anchored again; **69/69 killed**. Corrections
  asked for: r4 control breakdown 5/21/2/4; moa-65 kills in the lifecycle suite; `client_id`
  beside an assertion named a compatibility restriction (RFC 7521 §4.2); replay per process
  (restarts included); call 13's rationale scope/complexity not "no protection"; discovery in
  the ownership audit. **Process (Codex's three points, adopted):** `.agents/review-brief.md`
  — the reviewer's two jobs in order (own coverage list vs the PR body's record first, fixes
  second), the round ends with the coverage it added; PR body — a **Coverage record** section
  (surface × checked/by what/at which head, unresolved, explicitly untested); procedure — the
  two-jobs bullet, the coverage-record bullet (incl. keep one reviewer session through
  corrective rounds where practical), step 7.1 in "Responding", the protocol-value-space
  clause in rule 2; lessons → "Verifying the fixes is not examining the contract". Docs: design
  §5.5 row 8, §5.9 (k); AGENTS.md rule 13; procedure count (**471/46**).
- **Decisions:** rebuild the AS document from the SDK's `build_metadata` rather than introspect
  FastMCP's handler closure (explicit ownership; the literal pin catches drift); RS256 alone
  advertised because the pinned validator builds its verifier with the default algorithm
  (measured by the ES256 row); no distributed replay store (documented per-process limit);
  the session-continuity suggestion recorded as a trade-off for the owner, not a rule.
- **State:** backend **2101 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants **69/69 killed** (scratch runner, targets hashed, restored). Commit
  `8cae6c7` pushed; PR #212 body amended (coverage record added); the reply is issuecomment-5549456569.
  Codex's r5 probes at `/private/tmp/plamotrack-212-r5/` (untracked, `test_review_r5.py`).
  Dev `db` up, Keycloak spike up. LXC untouched (**stays put until M6 is finished**).
- **Next:** (1) **Codex round 6 on PR #212** — the owner decides whether in the same Codex
  session (Codex's suggestion: keep one session through corrective rounds) or a fresh one for
  an independent pass; either way the brief was printed in this session's chat — regenerate
  from `.agents/review-brief.md` (GPT-6 footer; **the template changed this round**) if needed,
  naming runtime head `8cae6c7`, the branch tip, `main` `a497481`, rules 1/6/7.1/9/11/12/13;
  findings from 16; reproduce at `8cae6c7` first; update the PR body's coverage record in the
  reply (procedure 7.1). If GO: squash-merge with `Closes #192`; nothing to fold in. (2) After
  merge: #215, #193, M6-9 TLS docs, the M6 release — gate `ingress_matrix.py --mode oidc` on a
  packaged stack with the Keycloak spike, the register burst concurrent — then the LXC upgrade;
  relink any MCP client first (records before `e90550f` carry no binding).

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
