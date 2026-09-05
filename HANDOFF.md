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

## 2026-09-06 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 13 (GPT-6 Astra, NO-GO: 1×P3, the fallback counts records, not cache slots) answered on the branch — head `ff8a5ec`, reply posted (issuecomment-5553924170), PR body + coverage record amended, round-14 brief printed

- **Done:** f37 reproduced at `2a786a6` on its own assertions first (20 new contract rows in a
  worktree at that head: **4 red / 16 green** — Codex's four fetched cells, two unnamed records
  × token/revoke, on `200 == 401`; the inline, mixed and sole-record rows controls), then
  fixed at `ff8a5ec`. Cause: the fetched path kept records by the SDK's cache slots (`kid or
  "_default"`), so two unnamed records were one and the fallback counted slots. **The invariant
  is now one function, `select_records`, over usable records, for both paths** (procedure 6:
  rounds 10–13 all landed in this seam): a named `kid` → the records carrying it, none a
  refusal; no `kid` → the only usable record, two ambiguous. `RestrictedKeyVerifier` keeps
  every usable record of the fetch in order (`_jwks_records`), the SDK's selection runs
  behind it (refuse-only), its PEM the disagreement check and the same-`kid` tie-break (last —
  the documented boundary, unchanged); the inline path takes `[0]`. Tests: contract suite
  **295** (+20); mutants moa-113/114, moa-108/110/112 re-anchored; harness **513/46**. Docs:
  module docstring, design §5.9 (k) + row 8, AGENTS.md rule 13, procedure (moa- paragraph +
  count), lessons → "The cache is not the set". PR body: opening line, What, By file, calls
  12/17/18 (revised as overruled), Tests, negative control, mutants, coverage record (Codex's
  r13 untracked coverage folded in; a record's non-string `kid` stays untested here).
- **Decisions:** the SDK's remote selection stays in front on the fetched path (its cache,
  TTL and fetch are its own) as a refuse-only layer, ours the owner of cardinality; the
  same-`kid` collision stays inline-first / fetched-last (Codex asked to preserve it); the
  corrected set on the fetched path is met by dropping the cached verifier (round 10's idiom).
- **State:** backend **2362 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants **111/111 killed** at `ff8a5ec` (tracked harness, committed tree,
  ~13 min; the two new killed first pass). Commit `ff8a5ec` pushed; PR #212 body amended;
  the reply is issuecomment-5553924170. Codex's r12 material at `/private/tmp/plamotrack-212-r12/`
  (untracked; r13 named no directory). Dev `db` up, Keycloak spike up. LXC untouched (**stays
  put until M6 is finished**).
- **Next:** (1) **Codex round 14 on PR #212** — the brief was printed in this session's chat;
  regenerate from `.agents/review-brief.md` (Codex footer; the reviewer names its model) if
  needed, naming runtime head `ff8a5ec`, the branch tip (hand-off only above it), `main`
  `a497481`, rules 1/6/7.1/9/11/12/13; findings from 38; reproduce at `ff8a5ec` first; update
  the coverage record in the reply (procedure 7.1). If GO: squash-merge with `Closes #192`;
  nothing to fold in. (2) After merge: #215, #193, M6-9 TLS docs, the M6 release — gate
  `ingress_matrix.py --mode oidc` on a packaged stack with the Keycloak spike, the register
  burst concurrent — then the LXC upgrade; relink any MCP client first.

## 2026-09-06 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 12 (GPT-6 Astra, NO-GO: 1×P3, a named `kid` must match) answered on the branch — head `2a786a6`, reply posted (issuecomment-5553421733), PR body + coverage record amended, round-13 brief printed

- **Done:** f36 reproduced at `5ecef8f` on its own assertions first (28 new contract rows in a
  worktree at that head: **4 red / 24 green** — Codex's two inline cells plus the two
  case-variant rows red on `200 == 401`; every fetched-path, fallback and non-string row a
  control), then fixed at `2a786a6`. Cause: **FastMCP has two selection rules** — its inline
  extraction falls back to the only key whenever no record matched the `kid`, named or not;
  its remote selection only when no `kid` is named — and round 11 wrote out the inline one
  while the docs described the remote one. `RestrictedKeyAssertionValidator.
  _extract_public_key_from_jwks` now applies the remote rule with its texts (`Key ID '…' not
  found in JWKS`; `Multiple keys in JWKS but no key ID (kid) in token`); `_header_kid` is the
  one reading for both paths (non-empty string names; absent/empty names none, the SDK's
  remote reading; a non-string reads as none and joserfc's decode refuses the header on both
  paths — **no type guard added**: it would be a second owner, measured before writing).
  Round 11's two tests **re-linked under a published name** — their link assertions had named
  `client-key` against sets not publishing it and passed *through* the fallback under test
  (Codex's own r12 repro links the same way and refuses at the new head; said in the reply).
  Tests: contract suite **275** (+28); mutants moa-110…112; harness **511/46**. Docs: module
  docstring, design §5.9 (k) + row 8, AGENTS.md rule 13, procedure (moa- paragraph + count),
  lessons → "The library had two rules". PR body: opening line, What, By file, calls 12/17/18,
  Tests, negative control, mutants, coverage record (a record's own empty/non-string `kid`
  listed untested; Codex's r12 untracked coverage folded in).
- **Decisions:** the rule is the SDK's *remote* one on both paths; an empty `kid` names none
  (the SDK's remote reading, and its cache keeps a record's empty `kid` under `_default`);
  a non-string `kid` is joserfc's refusal, not ours; the same-`kid` collision stays the
  documented inherited boundary (Codex r12 measured it and called it not a finding).
- **State:** backend **2342 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants **109/109 killed** at `2a786a6` (tracked harness, committed
  tree, ~14 min; the three new killed first pass). Commit `2a786a6` pushed; PR #212 body
  amended; the reply is issuecomment-5553421733. Codex's r12 material at `/private/tmp/plamotrack-212-r12/`
  (untracked). Dev `db` up, Keycloak spike up. LXC untouched (**stays put until M6 is
  finished**).
- **Next:** (1) **Codex round 13 on PR #212** — the brief was printed in this session's chat;
  regenerate from `.agents/review-brief.md` (Codex footer; the reviewer names its model) if
  needed, naming runtime head `2a786a6`, the branch tip (hand-off only above it), `main`
  `a497481`, rules 1/6/7.1/9/11/12/13; findings from 37; reproduce at `2a786a6` first; update
  the coverage record in the reply (procedure 7.1). If GO: squash-merge with `Closes #192`;
  nothing to fold in. (2) After merge: #215, #193, M6-9 TLS docs, the M6 release — gate
  `ingress_matrix.py --mode oidc` on a packaged stack with the Keycloak spike, the register
  burst concurrent — then the LXC upgrade; relink any MCP client first.

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
- **Next:** (1) **Codex round 12 has landed — NO-GO, one P3, finding 36, unaddressed**
  (issuecomment-5553107067, signed "GPT-6 Astra" again; this session closed at ~80 % context
  before reading past the title, owner's call): *an inline assertion naming an unknown `kid`
  is accepted through the no-`kid` fallback* — `RestrictedKeyAssertionValidator.
  _extract_public_key_from_jwks` falls back to the single usable key when the named `kid`
  matches nothing, where the SDK's remote selection refuses a named `kid` it cannot find
  (RFC 7517 §4.5). Answer in a new session per `.agents/testing-and-review.md` →
  "Responding to a review": read the comment in full first, reproduce at `5ecef8f` in the
  contract suite (both endpoints; the remote parity control), fix so a *named* `kid` must
  match and only an assertion naming none takes the fallback, add the mutant (moa-110),
  re-run `-k moa-` on the committed tree, update the coverage record (procedure 7.1),
  print the round-13 brief from `.agents/review-brief.md` (the reviewer names its model;
  findings from 37). If GO: squash-merge with `Closes #192`; nothing to fold in. (2) After merge: #215, #193, M6-9 TLS docs, the M6 release — gate
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
