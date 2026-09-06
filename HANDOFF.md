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

## 2026-09-06 — Claude Code (Fable 5.1) — #192 (M6-7) MERGED: PR #212 squash → `538640b` after Codex round 15 (GPT-6 Astra, **GO, no findings**); nothing to fold in; next #215, #193, M6-9 TLS docs, the M6 release

- **Done:** Codex round 15 replayed at `1476976` (issuecomment-5555934731): finding 38's negative
  control 4/20 → 24/24, 112/112 mutants, 2386 green, the six-round representation sweep closed
  (raw document → usable records → SDK cache → `select_records` → PEM tie-break → selected JWK →
  imported key, every consumer accounted for at FastMCP 3.4.5), boolean/object record `kid`,
  an assertion naming an unusable record, fetched root extensions, overlapping fetches and a
  failed-refetch recovery all driven untracked; calls 1–18 stand. Squash-merged with
  `Closes #192` in the squash body (procedure 8). **Nothing to fold in**: every `moa-` tuple
  (1…115 less the withdrawn/retired 16, 101, 103 → 112) is already in the tracked harness —
  `.agents/testing-and-review.md`'s "on `main` after #212: 514 cases over 46 target files" is
  now literally true. Branch `feature/m6-7-mcp-oauth` left in place (not deleted).
- **Decisions:** merged on the owner's report of GO (the hand-off's standing "if GO:
  squash-merge" since round 1); no release cut — M6 is one release at the end.
- **State:** `main` at `538640b` (+ this hand-off). Dev `db` up; the Keycloak spike compose
  is still up (`.agents/spikes/190/`, untracked) — stop it when it is no longer needed for
  the OIDC-mode ingress gate. LXC untouched (**stays put until M6 is finished** — #215, #193,
  M6-9 and the release are still ahead of it).
- **Next:** (1) **#215** and **#193** (the app's own request budget; the ingress limits landed
  with #212) — read each issue first; branch + PR each. (2) **M6-9 TLS docs** — the tested
  TLS/VPS deployment path (design §5.4 modes), on a branch. (3) **The M6 release**: the
  release gate in `.agents/testing-and-review.md` — `ingress_matrix.py --mode oidc` against a
  packaged stack with the Keycloak spike, the register burst concurrent — then tag, notes
  (client-visible changes are itemised per round in the PR #212 body, "Deliberate calls"),
  and only then the LXC upgrade (back up first; needs `ALLOWED_HOSTS`; relink any MCP client;
  refresh the personal Gunpla skill to the new version).

## 2026-09-06 — Claude Code (Fable 5.1) — #192 (M6-7) PR #212: Codex round 14 (GPT-6 Astra, NO-GO: 1×P3, the SDK fed the raw array below the rule) answered on the branch — head `1476976`, reply posted (issuecomment-5554588219), PR body + coverage record amended, round-15 brief printed

- **Done:** f38 reproduced at `ff8a5ec` on its own assertions first (24 new contract rows in a
  worktree at that head: **4 red / 20 green** — fetched × list-`kid` record × token/revoke ×
  named/unnamed on `401 == 200`; the inline rows and the fetched number/`null` rows
  controls), then fixed at `1476976`. Cause: `_fetch_jwks` derived `_jwks_records` and then
  returned the raw document, so FastMCP's own skip loop (which the inline path never runs)
  put each unusable record's `kid` into a set and choked on an unhashable one — a false
  refusal, no admission. Fix (Codex's measured remedy): `_fetch_jwks` returns `{"keys":
  <the usable records>}`, so the SDK's cache and `_jwks_records` consume one set; the SDK's
  `skipped_kids` branch is dead. Tests: contract suite **319** (+24; joserfc refuses every
  non-string record `kid` at import, measured first); mutant moa-115; harness **514/46**.
  Docs: module/class docstrings, design §5.9 (k) + row 8, AGENTS.md rule 13, procedure
  (moa- paragraph + count), lessons → "The consumer below the rule". PR body: opening line,
  What, By file, calls 12/17/18 (17 overruled → fixed), Tests, negative control, mutants,
  coverage record (Codex's r14 untracked coverage folded in; a record's boolean/object
  `kid` stays untested here).
- **Decisions:** the SDK is fed `{"keys": records}` only (it reads nothing else at 3.4.5);
  no guard added for a non-list `keys` on the fetched side (the comprehension filters it;
  a mutant there would be equivalent); the same-`kid` boundary untouched. **Six rounds in
  the selection seam** (10–14 + the fold): rule over records (r13) + every consumer fed the
  records (r14) — the invariant is complete as far as the author can see; say so in the
  brief and ask for a seventh representation.
- **State:** backend **2386 green**, lint/format clean, `render_ingress.py --check` clean;
  frontend untouched. Mutants **112/112 killed** at `1476976` (tracked harness, committed
  tree, ~12 min; moa-115 killed first pass). Commit `1476976` pushed; PR #212 body
  amended; the reply is issuecomment-5554588219. Codex's r12 material at `/private/tmp/plamotrack-212-r12/`
  (untracked; r13/r14 named no directory). Dev `db` up, Keycloak spike up. LXC untouched
  (**stays put until M6 is finished**).
- **Next:** (1) **Codex round 15 on PR #212** — the brief was printed in this session's chat;
  regenerate from `.agents/review-brief.md` (Codex footer; the reviewer names its model) if
  needed, naming runtime head `1476976`, the branch tip (hand-off only above it), `main`
  `a497481`, rules 1/6/7.1/9/11/12/13; findings from 39; reproduce at `1476976` first; update
  the coverage record in the reply (procedure 7.1). If GO: squash-merge with `Closes #192`;
  nothing to fold in. (2) After merge: #215, #193, M6-9 TLS docs, the M6 release — gate
  `ingress_matrix.py --mode oidc` on a packaged stack with the Keycloak spike, the register
  burst concurrent — then the LXC upgrade; relink any MCP client first.

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
