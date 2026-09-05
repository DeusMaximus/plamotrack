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

## 2026-09-06 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 11 (Daybreak Blue after GPT-6 Astra's refusals; NO-GO: 2×P3, the record the kid named) answered on the branch — head `5ecef8f`, reply posted (issuecomment-5552863879), PR body + coverage record amended, round-12 brief printed

- **Done:** both reproduced at `f82b3b3` on their own assertions first (16 new contract rows in a
  worktree at that head: **12 red / 4 green** — Codex's eight plus four: with the restricted copy
  first the *allowed* copy's assertion was refused too, so material-identity followed array order
  both ways), then fixed at `5ecef8f`. **f34** the record carried by the identity the selection
  used: `RestrictedKeyVerifier` keeps the fetched JWKs **by `kid`** as the SDK caches their PEMs
  (`_default` for none, unusable skipped) and returns the record the assertion's `kid` names
  (or the only key), refusing a record whose material ≠ the SDK's selected PEM; the inline
  selection written out by the SDK's rule in `_extract_public_key_from_jwks`, returning the
  record; `selected_jwk` gone; `_header_kid` via the SDK's `decode_jwt_header`. **f35** the
  validator's inline selection owns usability and selection together (the remote path's
  predicate: RSA/EC + a joserfc import that succeeds), so an `OKP` or incomplete object no
  longer denies the single-key fallback inline; round 9's copy-based `with_usable_inline_keys`
  **retired** — the first full harness pass at the new head returned moa-101/102/103 GREEN
  (equivalent: a second owner of the decision) → 101/103 retired, 102 re-anchored, re-run.
  Tests: contract suite **247** (+16); mutants moa-107…109; harness **508/46**, 106 tuples. Docs: module docstring, design §5.9 (k) + row 8,
  AGENTS.md rule 13, procedure (moa- paragraph + count; reviewer roster: Daybreak Blue from
  this round), review-brief footer, lessons → "The record the selection named". PR body: What,
  By file, call 12, call 17 (predicate), call 18 (first-entry assumption withdrawn), Tests,
  controls, mutants, coverage record (same-`kid` divergence named as inherited/untested).
- **Decisions:** the inline selection is ours by the SDK's rule (no longer calling the SDK's
  extractor) so the record, not a PEM, is returned; a fetched record/PEM disagreement refused,
  never degraded; the SDK's inline-first/remote-last same-`kid` divergence inherited, not
  reconciled (RFC 7517 §4.5 wants `kid` unique) — named in the brief; the round-11 comment is
  signed "GPT-6 Astra" though the owner says Daybreak Blue reviewed — the brief's footer asks
  the reviewer to name itself.
- **State:** backend **2314 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants ****106/106 killed** at `5ecef8f` (tracked harness, committed tree, ~13 min; the first pass at `a77aa01` was 105 + three GREEN → the retirement)** (tracked harness, committed tree, `nohup`).
  Commits `5ecef8f` and `5ecef8f` (the filter's retirement after the first harness pass) pushed; PR #212 body amended; the reply is issuecomment-5552863879. Codex's r11 material
  untracked (its comment names no directory this round). Dev `db` up, Keycloak spike up. LXC
  untouched (**stays put until M6 is finished**).
- **Next:** (1) **Codex round 12 on PR #212** — the brief was printed in this session's chat;
  regenerate from `.agents/review-brief.md` (the Codex footer; the reviewer names its model)
  if needed, naming runtime head `5ecef8f`, the branch tip (hand-off only above it), `main`
  `a497481`, rules 1/6/7.1/9/11/12/13; findings from 36; reproduce at `5ecef8f` first; update
  the coverage record in the reply (procedure 7.1). If GO: squash-merge with `Closes #192`;
  nothing to fold in. (2) After merge: #215, #193, M6-9 TLS docs, the M6 release — gate
  `ingress_matrix.py --mode oidc` on a packaged stack with the Keycloak spike, the register
  burst concurrent — then the LXC upgrade; relink any MCP client first.

## 2026-09-05 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 10 (GPT-6, NO-GO: 1×P3, the selected key's authorization) answered on the branch — head `f82b3b3`, reply posted (issuecomment-5552103057), PR body + coverage record amended, round-11 brief printed

- **Done:** f33 reproduced at `cb69559` on its own assertions first (22 new contract rows in a
  worktree at that head: **14 red / 8 green**, Codex's twelve among the reds), then fixed at
  `f82b3b3` within Codex's constraints (both key paths, cached keys, the very key the verifier
  selects, no refetch, one cryptographic validator, nothing stripped, a mixed-purpose set still
  admitting its signing key): FastMCP converted the selected JWK to a PEM before verifying, so
  `alg`/`use`/`key_ops` never reached joserfc. `RestrictedKeyAssertionValidator` (over FastMCP's
  `CIMDAssertionValidator`: the inline selection returned as the JWK found by the PEM the SDK
  produced — `_pem_of`/`selected_jwk`, byte-identical across metadata) and `RestrictedKeyVerifier`
  (over `JWTVerifier`: the fetched JWKs kept beside the SDK's PEM cache, rebuilt on the SDK's
  refetch, the selected JWK returned in the PEM's place; installed in the SDK's per-client
  verifier cache under its own key) — joserfc enforces the restrictions in the signature's
  decode. One validator instance on the proxy (`assertion_validator`) for both endpoints; the
  authenticator calls `validate_assertion` directly (the manager's validator unused). Codex's
  corrections adopted: call 17 qualified as approximate (its 2,144-value corpus); the coverage
  record carries the interrupted-second-write observation forward. Tests: contract suite
  **231** (+22: 3 restrictions × inline/remote × 2 endpoints, explicit-ok + mixed-set controls,
  the cached-key rows); mutants moa-104…106; harness **507/46**. Docs: module docstring, design
  §5.9 (k) + row 8, AGENTS.md rule 13, procedure, lessons → "The selected key keeps its
  authorization". PR body: What, By file, call 12, call 17 qualified, **new call 18**, Tests,
  controls, mutants, coverage record.
- **Decisions:** replace the lossy representation, keep the SDK's selection (no second verifier,
  no refetch, no metadata check in front of the SDK); one material published twice → the first
  entry; a restriction changed after a fetch seen at the cache's expiry (FastMCP's TTL — named);
  the tracked suite plays the JWKS fetch below the verifier, links through the inline set so a
  fetched verifier's first fetch is the set under test, and drops the cached verifier (a
  private seam, named) to meet a corrected set.
- **State:** backend **2298 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants ****105/105 killed** first pass (tracked harness, committed tree, ~12 min)** (tracked harness, committed tree, `nohup`).
  Commit `f82b3b3` pushed; PR #212 body amended; the reply is issuecomment-5552103057. Codex's r10 material
  at `/private/tmp/plamotrack-212-r10/` (untracked). Dev `db` up, Keycloak spike up. LXC
  untouched (**stays put until M6 is finished**).
- **Next:** (1) **Codex round 11 on PR #212** — the brief was printed in this session's chat;
  regenerate from `.agents/review-brief.md` (GPT-6 footer) if needed, naming runtime head
  `f82b3b3`, the branch tip (hand-off only above it), `main` `a497481`, rules 1/6/7.1/9/11/12/13;
  findings from 34; reproduce at `f82b3b3` first; update the coverage record in the reply
  (procedure 7.1). If GO: squash-merge with `Closes #192`; nothing to fold in. (2) After
  merge: #215, #193, M6-9 TLS docs, the M6 release — gate `ingress_matrix.py --mode oidc` on a
  packaged stack with the Keycloak spike, the register burst concurrent — then the LXC
  upgrade; relink any MCP client first.

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
