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

## 2026-09-06 — Codex (GPT-6 Astra) — #208 security review P3-5/P3-6 repaired locally

- **Context:** the independent review at `43c5826` is NO-GO (P3-5 malformed XFF
  attribution, P3-6 opaque OAuth values in audit details), issuecomment-5557756710.
  The review is posted as GPT-5; the owner identifies the reviewer as Daybreak Blue.
  #208 was pushed at `43c5826`, CI all green, main remains `1fd3b36` with #212 merged.
- **Done:** reproduced both at the reviewed head, then fixed the class. The shared
  IP parser validates/canonicalizes whole IP/port/bracket spellings and rejects
  interface scope ids; a malformed or empty XFF hop stops at the last verified
  address. Bundled-header validation uses the same parser; raw peers stay intact.
  `audit.external_reference` fingerprints complete client ids and refused OIDC
  subjects at every emitter. Protocol ids and verified principal ids are unchanged.
  Browser callback errors use fixed categories. The sweep also reproduced and
  removed a raw provider-error log; HTTP status remains. Docs/rule 14 updated;
  lessons: "A field name is not a safe audit representation".
- **Decisions:** digest-only references rather than displaying a URL with just its
  query stripped: its path/userinfo can carry credentials too. Query/fragment
  differences remain correlatable. Missing and empty values differ; every Python
  string is handled. Existing audit rows are not rewritten; retention remains the
  host-side way to expire them. #212's authorization/grant/client decisions remain.
- **Validation:** new regression selection at `43c5826`: **70 red / 27 green**,
  all final data assertions after correcting two witness setup/expectation mistakes.
  New suite is now **113 cases**, including fingerprint and bundled-parser controls.
  Full backend run **2527 passed / 9 failed**; the nine were old raw-identifier
  audit expectations, updated and rerun **9 passed** with runtime code unchanged.
  Three redirect controls also passed after a test-witness repair (one added case):
  2537 cases validated across full/focused runs, not one final-tree green invocation.
  Ruff/format/render/whitespace pass.
- **Mutation:** aud-38..56 **19/19 killed** with green baselines and byte restoration:
  parser validation/stop/empty/port/bracket/scope/private-header, five client emitters,
  two subject emitters, callback category, provider-error log, whole/missing/Unicode
  fingerprint handling. Tracked moa-54 re-anchored. Full tracked replay: **513/514**;
  oidc-19 survived because #212 changed fixture BASE to localhost, equal to its Host
  witness. No production redirect defect. Corrected the contrasting Host in start
  and both callback branches: oidc-19 replay **1/1**, adjacent aud-57/58 **2/2**.
  All 514 tracked plus 21 new mutants detected across runs; exact restoration.
  Lesson: "A changed fixture can erase the contrasting value".
- **State:** fixes applied but **uncommitted/unpushed** in the #208 worktree,
  `/Users/tlgja/Code/plamotrack-208`; primary dirty #194 untouched. No PR reply/body
  update or merge this turn. Review worktree `/private/tmp/plamotrack-208-r2` and
  logs `/private/tmp/plamotrack208-r2-*.log`; runner
  `/private/tmp/plamotrack208-r2-mutations.py`, evidence/recipes under
  `/private/tmp/plamotrack208-r2-mutants/`. Local reply/body drafts are
  `/private/tmp/plamotrack208-r2-{response,pr-body}.md`; not posted. Both dedicated
  test DBs removed; dev DB healthy. No frontend/packaged/TLS/restore/LXC rerun.
- **Next:** commit/push when asked, then publish the per-finding response/updated
  coverage at the new head. Obtain another independent review before merging.
  Fold aud-1..58 after merge, adding
  test_audit_privacy.py and test_access_logging.py to harness targets. #206/#210/
  #213/#214/#215 remain separate issue questions. #194 and the M6 release gates
  still precede the LXC upgrade; the end-of-M6 security review remains planned.

## 2026-09-06 — Codex (GPT-6) — #208 integration committed; #212 handoff history preserved

- **Done:** this merge commit integrates freshly fetched `origin/main` `1fd3b36`
  (including #212 squash `538640b`) into `codex/193-audit-rate-limit-log-hygiene`,
  together with the OAuth limiter, audit-attribution and log-hygiene fixes detailed
  in the preceding entry. The owner requested this commit and handoff reconciliation.
- **History:** compared every entry in `HANDOFF.md` and `.agents/handoff/` against
  both parents before committing: all 114 main entries and all 103 branch entries
  remain unchanged, without duplicate titles. #212's final GO/merge record remains
  in the live handoff. Added this entry and rotated the oldest verbatim; five live
  entries, 121 total. No historical entry was rewritten to describe the new state.
- **State:** committed locally in `/Users/tlgja/Code/plamotrack-208`; no push or
  GitHub prose update. The primary checkout remains on dirty #194 with its existing
  files intact. #208 still needs a fresh PR-specific security review before merging;
  the earlier GO predates #212 and the new logging changes. The broader end-of-M6
  security review remains planned. #212 itself is no longer a merge-order blocker.
- **Validation:** retained final affected backend run **589 passed**, frontend
  **488 passed** plus lint/build, and packaged local/OIDC ingress matrices with zero
  failures. Full backend 2417 passed before the final SDK diagnostic refinement;
  the full final backend and 514-case mutation harness were not rerun. Eleven
  targeted mutants killed. Packaged OIDC used a discovery fixture; provider lifecycle
  is covered by backend fake-provider tests. Current lint/format/render/whitespace
  and history-preservation checks passed; this step changed handoff files only.
- **Next:** push when requested, refresh the stale PR body/coverage with the committed
  head, then obtain the fresh security review before merging #208. Fold aud-1..37
  after merge, adding test_access_logging.py to the harness targets. Evidence and
  runners remain in `/tmp/plamotrack208-current/`. #210/#214/#215 remain separate;
  #194/TLS/restore and the M6 release precede the LXC upgrade. Disposable stack/test
  DBs are removed; the original dev Postgres remains. No LXC operation.

## 2026-09-06 — Codex (GPT-6) — #208 integrated with merged #212; OAuth/logging gaps repaired locally

- **Context:** #212 merged as `538640b`; main is `1fd3b36` (remote checked again at
  finish). Primary checkout is now dirty #194 (`codex/194-caddy-deployment-harness`),
  so work is isolated in `/Users/tlgja/Code/plamotrack-208` on the existing #193 branch.
  HEAD stays `2449ed7`: merge of `1fd3b36` and all fixes are prepared, **uncommitted**.
  No push, GitHub edit, PR merge, or LXC operation. #194's files were left intact.
- **Done:** resolved the merge, preserving both handoff histories. Removed #212's
  duplicate OAuth zone/three exact locations; discovery and all six protocol routes
  inherit the shared family-8 limiter and trusted-address header. Retained the 429
  envelope/no-store/Retry-After/security profile. MCP claim/identity refusals now name
  anon; six address witnesses cover raw, trusted-proxy and bundled attribution.
  #212's grant/client/resource/registration decisions are retained.
- **Logging finding/fix:** real callbacks leaked code/state in both access logs,
  Referer in nginx, query credentials in nginx limiter diagnostics, and invalid state
  in the SDK's diagnostic. `app/log_hygiene.py` chains the record factory before app
  auth construction: uvicorn queries stripped; SDK auth messages/args/tracebacks
  replaced with a fixed diagnostic retaining source/severity. App auth messages and
  audit rows stay detailed. nginx overrides the image's combined log per server,
  keeps path/status/size/timing, and discards its unformattable request-error log.
  This diagnostic tradeoff is documented; a stopped-upstream 502 still logged status
  and timing fields without query/Referer. Startup/config errors still reach stderr.
- **Harness:** discovery expectations/challenge now follow mode, family-8 contract
  rows paced before intentional bursts; all six protocol paths and 30 alternate
  spellings covered. Unrewritten root spellings may be 401/404 at the app while still
  sharing the ingress budget. Private log-scan JSON includes OAuth query/Referer
  probes on normal and throttled callbacks, also in the anonymous OIDC-mode run.
- **Validation:** full backend 2409, then 2417 passed before the final SDK-record
  sanitization/installation refinement; final affected suites **589 passed**, including
  six further diagnostic cases. Frontend lint/**488 tests**/build green; Ruff, format,
  render and whitespace green. Packaged local AND OIDC matrices: zero failures;
  real PAT/anonymous MCP clients on both spellings; non-vacuous credential/query scans.
  OIDC packaged provider was a minimal loopback discovery fixture, not a live provider
  login. Lifecycle/crypto/refresh/revocation are the backend fake-provider suites.
- **Mutation/negative controls:** six actor assertions and both real-server query-log
  tests failed before fixes; packaged leaks observed directly. All 514 tracked anchors
  match once and Python replacements compile. Repaired auth-17/22/pat-16 plus new
  aud-30..37 killed (**11 distinct cases**); full 514 harness not rerun. New queue:
  30/31 MCP refusal actors; 32 log-policy installation; 33 query stripping; 34 nginx
  raw access URI; 35 raw nginx error diagnostics; 36 family-8 limiter; 37 SDK auth
  payload sanitization. Fold aud-1..37 after merge; add test_access_logging.py to targets.
- **Evidence:** `/tmp/plamotrack208-current/integration-review.md` has coverage/limits
  and mutation runners/logs. Disposable stack/volume and the two dedicated test DBs
  removed; original dev Postgres remains. Worktree dependencies are installed.
- **Next:** commit/push only when requested; refresh the stale PR body/coverage at the
  resulting head and obtain a **fresh security review** before merging #208. #212 is
  no longer the blocker. #210, #214 and #215 remain separate open work. #194/TLS/restore
  and the M6 release still precede the LXC upgrade. This session publishes nothing.

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
- **State:** `main` at `538640b` (the squash) + this hand-off; **nothing in flight** — the
  session closed here with the tree clean on `main`, #192 closed by the merge (COMPLETED),
  PR #212 MERGED, no open branch work. Dev `db` up; the Keycloak spike compose is still up
  (`.agents/spikes/190/`, untracked) — stop it when it is no longer needed for the OIDC-mode
  ingress gate. LXC untouched (**stays put until M6 is finished** — #215, #193, M6-9 and the
  release are still ahead of it). Frontend untouched throughout #212.
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
