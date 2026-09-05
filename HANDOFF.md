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

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 9 (GPT-6, NO-GO: 2×P3, "parsing is not validation") answered on the branch — head `cb69559`, reply posted (issuecomment-5551526055), PR body + coverage record amended, round-10 brief printed

- **Done:** both reproduced at `d2e1297` on their own assertions first (32 new/changed contract
  rows in a worktree at that head: **23 red / 9 green**), then fixed at `cb69559`. **f31**
  `ABSOLUTE_URI` — RFC 3986 Appendix A's `absolute-URI` as one regex — judged in
  `resource_identity` on the decoded string *before* `urlsplit` (which admitted a tab in the
  authority, a CR in the path, a leading NUL, and never looked at the ignored query: `%zz`,
  an unescaped space); a valid escape admitted. **f32** `with_usable_inline_keys` in the
  `private_key_jwt` branch: `keys` must be an array, non-object entries dropped (RFC 7517
  §5.1, matching the remote path) from a copy handed to FastMCP's validator, none usable →
  `invalid_client`; the snapshot still returned. Correction adopted: call 16's scheme wording
  (the scheme case-folds via `urlsplit`/`urlparse`; the authority as written) — the round-8
  `spelling` row split into `scheme_case` (accepted) and `host_case` (foreign). Tests: contract
  suite **209** (+29; the whole-URI test 12 values × 3 flows, the key-set test 4 × 2); mutants
  moa-100…103; harness **504/46**. Docs: module docstring, design §5.9 (k) + row 8, AGENTS.md
  rule 13, procedure, lessons → "Parsing is not validation". PR body: What, By file, call 16
  corrected, **new call 17** (the grammar's approximations; the §5.1 ignore rule and the
  single-key-fallback consequence), Tests, controls, mutants, coverage record.
- **Decisions:** `IPvFuture`/`IPv6address` approximated as a bracketed hex/colon/dot literal,
  `IPv4address` under `reg-name`; unusable key entries dropped rather than the set refused
  (Codex offered either); the grammar judged on the once-decoded form value; no other
  exception translated at the key boundary.
- **State:** backend **2276 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants ****102/102 killed** — 101 first pass; moa-92 GREEN (equivalent under the new grammar) → redesigned as the fragment stripped before comparing, killed alone** (tracked harness, committed tree, `nohup`).
  Commits `cb69559` (runtime) and `e7ad8c4` (moa-92 redesign, procedure) pushed; PR #212 body amended; the reply is issuecomment-5551526055. Codex's r9 material
  at `/private/tmp/plamotrack-212-r9/` (untracked). Exact-tip CI was green at `559c6f8` (the
  round-8 timing flake did not recur). Dev `db` up, Keycloak spike up. LXC untouched (**stays
  put until M6 is finished**).
- **Next:** (1) **Codex round 10 on PR #212** — the brief was printed in this session's chat;
  regenerate from `.agents/review-brief.md` (GPT-6 footer) if needed, naming runtime head
  `cb69559`, the branch tip (hand-off only above it), `main` `a497481`, rules 1/6/7.1/9/11/12/13;
  findings from 33; reproduce at `cb69559` first; update the coverage record in the reply
  (procedure 7.1). If GO: squash-merge with `Closes #192`; nothing to fold in. (2) After
  merge: #215, #193, M6-9 TLS docs, the M6 release — gate `ingress_matrix.py --mode oidc` on a
  packaged stack with the Keycloak spike, the register burst concurrent — then the LXC
  upgrade; relink any MCP client first.

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 8 (GPT-6, NO-GO: 4×P3, "admitted once" at the SDK seam) answered on the branch — head `d2e1297`, reply posted (issuecomment-5551101166), PR body + coverage record amended, round-9 brief printed

- **Done:** all four reproduced at `9bf1925` on their own assertions first (45 new contract rows in
  a worktree at that head: **35 red / 10 green**), then fixed at `d2e1297` to the invariant Codex
  named — a request is admitted once, from its recognised fields and every credential occurrence,
  against one client snapshot, with the resource decision carried through the hand-off. **f27**
  `resource_identity` (own comparison over `urlsplit`: a fragment or no scheme malformed → direct
  400; whole path with `;parameters`; trailing slash and query the only equivalences; scheme and
  authority *as written*, call 16) under `accepts_resource`, and `authorize` applies it before
  FastMCP's looser check; the two private FastMCP helpers removed. **f28** `RECOGNISED_PARAMETERS`
  per endpoint; unknown parameters dropped before the repetition rule (erratum 5708). **f29**
  `ClientAssertionAuthenticator` rewritten over the SDK's base `ClientAuthenticator`: every
  `Authorization` occurrence (`getlist`) inventoried first and any one refused `invalid_client`
  with the challenge, with or without an assertion; `presented_scheme` over every occurrence.
  **f30** one `get_client` per request; dispatch by the snapshot's method through FastMCP's
  `validate_private_key_jwt`. Corrections adopted: NumericDate ±2^53 described as local policy;
  call 15's claim now true; CI's `test_archive_structure_is_processed_in_linear_time` (1.5 s
  budget, 2.49 s on the runner) noted as unrelated — owner to re-run/file. Tests: contract suite
  **180** (+45); mutants moa-92…99, moa-71/86/87/90 re-anchored; harness **500/46**. Docs:
  module docstring, design §5.9 (k) + §5.5 row 8, AGENTS.md rule 13, procedure, lessons →
  "Admitted once". PR body: What, By file, calls 12/14/15, **new call 16**, Tests, controls,
  mutants, coverage record (Codex's r8 untracked probes and "still unexamined" folded in).
- **Decisions:** scheme/authority compared as written (an equivalence FastMCP's normaliser
  behind the hand-off lacks would let it refuse what we accepted → `server_error`); a
  scheme-less resource is *malformed* (direct 400), not foreign (redirect); any `Authorization`
  header at `/token`/`/revoke` refused even on a public client (no HTTP scheme admitted);
  unknown parameters dropped before the SDK (its models ignore them anyway); the FastMCP
  authenticator no longer a base class — its cryptographic validator is called directly.
- **State:** backend **2247 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants ****98/98 killed** first pass (tracked harness on the committed tree, ~12 min)** (tracked harness, committed tree, detached with
  `nohup`). Commit `d2e1297` pushed; PR #212 body amended; the reply is issuecomment-5551101166. Codex's r8
  material at `/private/tmp/plamotrack-212-r8/` (untracked). Dev `db` up, Keycloak spike up.
  LXC untouched (**stays put until M6 is finished**).
- **Next:** (1) **Codex round 9 on PR #212** — the brief was printed in this session's chat;
  regenerate from `.agents/review-brief.md` (GPT-6 footer) if needed, naming runtime head
  `d2e1297`, the branch tip (hand-off only above it), `main` `a497481`, rules 1/6/7.1/9/11/12/13;
  findings from 31; reproduce at `d2e1297` first; update the coverage record in the reply
  (procedure 7.1). If GO: squash-merge with `Closes #192`; nothing to fold in; re-run the tip's
  Backend CI if the timing test is the only red (or file it). (2) After merge: #215, #193, M6-9
  TLS docs, the M6 release — gate `ingress_matrix.py --mode oidc` on a packaged stack with the
  Keycloak spike, the register burst concurrent — then the LXC upgrade; relink any MCP client
  first.

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
