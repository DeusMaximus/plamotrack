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

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 7 (GPT-6, NO-GO: 7×P3, admission/decoding/cardinality at the SDK seam) answered on the branch — head `9bf1925`, reply posted (issuecomment-5550571202), PR body + coverage record amended, round-8 brief printed

- **Done:** all seven reproduced at `855c0e1` on their own assertions first (47 new contract rows
  copied into a worktree at that head: **38 red / 9 green**), then fixed at `9bf1925`. **f20**
  `ProtocolRequest` reads the media type as HTTP defines it (case-insensitive, parameters aside)
  and refuses any non-form POST body `400 invalid_request` before the SDK parses it. **f21**
  `NUMERIC_DATE_BOUND` ±2^53 (RFC 7493) judged before any float conversion. **f22** `resource` is a
  set: exempt from the repetition rule, collapsed, every member judged by the proxy's
  `accepts_resource` (FastMCP's comparison as a predicate; two more private helper imports); a
  foreign set `invalid_target` — at `/authorize` via the SDK's redirect, now rendered by the
  proxy's `authorize` through `construct_redirect_uri` because the SDK's vocabulary lacks the code
  (it said `server_error`; the lifecycle test's hedge is gone); at `/token` the guard's own 400
  (the SDK judges nothing there — a *single* foreign resource at `/token` is refused now, a
  client-visible change); unparseable → direct 400. **f23** `_claim_defect(name)` dates the
  fixture at run time. **f24** an assertion beside `client_secret`/`Authorization` → `401
  invalid_client` before anything is spent; `_challenge_on_refusal` wraps the `/token` and
  `/revoke` handlers so a 401 to a header-authenticating client carries `WWW-Authenticate`
  (scheme echoed when an RFC 9110 token, realm the issuer). **Call 14** fixed rather than
  reworded: an assertion from a client not registered for `private_key_jwt` is refused. **f25**
  moa-76 repaired (`_unwritten = (…)`), every round-7 mutant compile-checked; **f26** `jwks` +
  `jwks_uri` → `invalid_client_metadata`. Tests: contract suite **135** (+47); mutants
  moa-81…91; harness **492/46**. Docs: design §5.9 (k), AGENTS.md rule 13, module docstring,
  procedure moa- paragraph + count, lessons → "Admission, decoding, cardinality and the
  hand-off are one decision". PR body: What, By file, calls 11 (SSRF sentence withdrawn in the
  body), 12, 13, 14 (rewritten), **new call 15** (the challenge + the client-visible changes),
  Tests (round 6's control corrected to **36/18**, thirteen decoding rows, six repeated
  token/revocation rows; round 7's control), coverage record (Codex's "still unexamined" folded
  in; consent/callback last-value multiplicity "recorded, not hardened").
- **Decisions:** the `/token` resource policy is the guard's, not a new SDK hook — RFC 8707 §2.2
  "MUST reject"; the `/authorize` form is the SDK's redirect, produced by handing it the first
  foreign value (the PKCE-`plain` precedent), the code corrected in `authorize`; JSON bodies are
  400 where they were the SDK's 401; a stray secret on a public client that presents no
  assertion stays ignored; the challenge echoes the client's scheme (RFC 6749 §5.2 read
  literally — a "where I'd push" bullet); multipart refused, not implemented.
- **State:** backend **2202 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants: ****90/90 killed** — 88 first pass, moa-12 and moa-74 re-anchored (their anchors moved under this round's edits: the `authorize` docstring, the f21 range line) and re-run alone, killed** — run by the **tracked harness on the committed
  tree** (`uv run python mutation_test.py -k moa-`, detached with `nohup` because the run exceeds
  a tool call's ceiling; ~11 min). Commits `9bf1925` (runtime) and `118d242` (harness re-anchors, docs) pushed; PR #212 body amended; the reply is
  issuecomment-5550571202. Codex's r7 material at `/private/tmp/plamotrack-212-r7/` (untracked). Dev `db`
  up, Keycloak spike up. LXC untouched (**stays put until M6 is finished**).
- **Next:** (1) **Codex round 8 on PR #212** — the brief was printed in this session's chat;
  regenerate from `.agents/review-brief.md` (GPT-6 footer) if needed, naming runtime head
  `9bf1925`, the branch tip (hand-off commits only above it), `main` `a497481`, rules
  1/6/7.1/9/11/12/13; findings from 27; reproduce at `9bf1925` first; the contract suite is where
  a boundary finding's reproduction belongs; update the coverage record in the reply (procedure
  7.1). If GO: squash-merge with `Closes #192`; nothing to fold in. If NO-GO and the findings
  keep landing in `ProtocolRequest` / `ClientAssertionAuthenticator`, stop patching and look
  for the invariant one level up (procedure, "Responding" 6). (2) After merge: #215, #193,
  M6-9 TLS docs, the M6 release — gate `ingress_matrix.py --mode oidc` on a packaged stack with
  the Keycloak spike, the register burst concurrent — then the LXC upgrade; relink any MCP
  client first.

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 6 (GPT-6, NO-GO: P2 + 3×P3, the SDK boundary field by field) answered on the branch — head `855c0e1`, reply posted (issuecomment-5549938526), PR body + coverage record amended, round-7 brief printed

- **Done:** the two-jobs brief found four pre-existing boundary gaps, none in the grant machinery.
  **f16** `validate_client_assertion_claims` + `ClientAssertionAuthenticator` (one class, built per
  endpoint by `_client_authenticator`, on `/token` via FastMCP's `TokenHandler` and `/revoke`): the
  claim contract on the unverified assertion *before* the SDK's validator — `alg` advertised, object
  payload, string `iss`/`sub`/`jti`, `aud` str|list, `exp` required, finite non-bool NumericDates,
  `nbf` with 30 s skew — refuse-only, `401 invalid_client`, spends no `jti`. **f17** `register_client`
  canonicalises the whole metadata and stores that object (`null` redirect list →
  `invalid_client_metadata`; response/grant types substituted; blank scope → default; display fields
  kept). **f18** `ProtocolRequest` (ASGI guard, `guard_protocol_requests` in `build_mcp_app`) on
  `/authorize` `/token` `/revoke`: repeated parameter → 400 direct; empties omitted; unknown
  `grant_type` → `unsupported_grant_type`; omitted `code_challenge_method` → `plain` for the SDK to
  refuse (error redirect for a registered client, RFC 7636 §4.4.1). **f19**
  `UnregisteredClientGuidance` → root discovery URL. Tests: contract suite **88** (+54); control at
  `8cae6c7`: **54 rows, 37 red / 17 green**. Mutants moa-71…80, moa-64 re-anchored; **79/79 killed**.
  Docs: design §5.5 row 8, §5.9 (k) (per-field ownership rows); AGENTS.md rule 13; procedure
  moa- paragraph + count (**481/46**); lessons → "The seam has an owner per field, not per
  endpoint"; PR body call 14 (decoding decisions), call 12/13 amended, coverage record updated
  with Codex's ten-surface inventory (checked / untracked / untested).
- **Decisions:** the PKCE omission handed to the SDK as `plain` rather than answered by the guard
  (the SDK knows whether to redirect; §4.4.1 wants the redirect for a registered client); a client
  presenting an assertion is judged by it whatever its method (a stray secret stays ignored); the
  guard does not touch `/consent`/callback, unknown extension params, or non-form bodies; null
  redirect list refused, not defaulted; call 11's "SSRF guard makes remote-JWKS tests impossible"
  withdrawn (Codex drove it with played DNS/transport — the tracked suite still plays the fetch).
- **State:** backend **2155 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants **79/79 killed** (scratch runner, targets hashed, restored). Commit
  `855c0e1` pushed; PR #212 body amended; the reply is issuecomment-5549938526. Codex's r6 material at
  `/private/tmp/plamotrack-212-r6/` (README, `coverage-plan.md` — its ten-surface inventory —
  and four probe files; untracked). Dev `db` up, Keycloak spike up. LXC untouched (**stays put
  until M6 is finished**).
- **Next:** (1) **Codex round 7 has landed — NO-GO, seven P3s, 20–26, unaddressed**
  (issuecomment-5550272371; this session closed at ~72 % context before reading it in full,
  owner's call). Titles: 20 apply request decoding to every admitted form representation;
  21 map numeric-range failures to a client-authentication error; 22 give the repeatable
  `resource` field its own multiplicity rule (RFC 8707 allows it more than once — the
  `ProtocolRequest` repetition rule must exempt it); 23 create the future-`nbf` fixture at
  execution time (`_CLAIM_DEFECTS` computes `NOW` at import — a test defect); 24 refuse
  competing client-authentication mechanisms before spending the assertion; 25 repair
  moa-76 before counting it as killed (the tuple's replacement is not a behavioural mutant —
  re-anchor it as one before the next `-k moa-` claim); 26 canonical registration metadata
  must also obey its cross-field constraints. Answer in a new session per
  `.agents/testing-and-review.md` → "Responding to a review": reproduce each at `855c0e1`
  first (the contract suite is where the reproductions belong), fix 23 and 25 as test/harness
  corrections and say so, update the coverage record (procedure 7.1), print the round-8 brief
  from `.agents/review-brief.md` (GPT-6 footer; findings from 27). If the next round is GO:
  squash-merge with `Closes #192`; nothing to fold in. If GO:
  squash-merge with `Closes #192`; nothing to fold in. (2) After merge: #215, #193, M6-9 TLS docs,
  the M6 release — gate `ingress_matrix.py --mode oidc` on a packaged stack with the Keycloak
  spike, the register burst concurrent — then the LXC upgrade; relink any MCP client first.

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
