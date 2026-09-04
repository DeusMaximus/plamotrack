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

## 2026-09-05 — Codex (GPT-6) — #208 integration finalized; next session is #194

- **Done:** this merge commit integrates `main` `a497481` into
  `codex/193-audit-rate-limit-log-hygiene`, retaining #191 and the #193 fixes described in
  the entry below. All conflicts resolved; worker pin, descriptor-based secret output,
  OIDC audit actors, and seven repaired mutation cases are included. Corrected design §5.9
  to name the actual `auth.oidc_rebind` emitter. The owner requested commit, push, then a
  return to fast-forwarded `main`; no PR merge was requested.
- **Validation:** full backend 1,971 passed; the subsequent deployment/authorization selection
  11 passed, including the newly added dependency-only test. Frontend 487 passed plus lint
  and build; Ruff/format/render green. Fresh isolated packaged matrix: zero failures, all
  four limit families and 12 alternate spellings, real PAT/anonymous MCP checks, full
  password/PAT/session log scan. Seven repaired + twelve new hand mutants killed (19/19);
  all 402 tracked anchors match once. Full mutation harness was not rerun. The earlier
  entry retains the negative-control counts and local scratch evidence location.
- **Decisions:** #208 stays open until #212 is reviewed and merged. #212 is still open at
  `529ad68`, with the latest review NO-GO (f6 grant resurrection, f7 unvalidated refresh
  state, f8 evidence counts); the desktop owns those repairs. #210 remains a separate item.
  After #212, reconcile the OAuth/family limiters and private client-address overwrites,
  retain the 429 response profile, rerun local/OIDC packaged gates and get a fresh review.
  PR prose/review replies were not updated by this commit/push request. Fold aud-1…29 after
  #208 merges; the original entry lists the twelve new cases.
- **Next session:** #194 in its own feature branch/worktree from current main: prepare the
  Caddy deployment harness and draft operations documentation. Read issues #194 and PRs
  #208/#212 for pending integration changes. Final OAuth/restore verification and supported
  remote-deployment claims wait for #192/#193. The existing LXC stays untouched until M6
  is finished. Local dev Postgres is running; disposable stack, volume and mutant DB are gone.

## 2026-09-05 — Codex (GPT-6) — #208 laptop integration prepared; hold the PR for #212

- **Done:** verified GitHub instead of treating this laptop's hand-off as current. #191 is
  merged (#209/#211); `origin/main` is `a497481`. Prepared `git merge --no-commit --no-ff
  origin/main` on `codex/193-audit-rate-limit-log-hygiene` (`HEAD` remains `1b18bbb`). All five
  conflict files resolved: recovery keeps both prune and OIDC rebind; setup failures keep
  anonymous attribution AND the caller's OIDC target; audit keeps #191's real `auth.oidc_rebind`
  and removes #193's unused `auth.oidc_rebound` placeholder. Both hand-off histories retained
  and rotated without changing entry content.
- **Review follow-up:** reproduced CodeRabbit's worker and secret-output findings. Dockerfile
  now passes `--workers 1`, overriding both WEB_CONCURRENCY and UVICORN_WORKERS. Harness
  secret files use one O_NOFOLLOW descriptor, fchmod before writing, and no path reopening.
  #210 remains the separately filed refusal-volume policy; the old six-entry hand-off finding
  was already obsolete. No GitHub review reply or PR-body edit posted this session.
- **Class sweep:** #191's OIDC failure/identity-refusal audit rows now explicitly identify anon;
  startup mode changes/session revocation and OIDC recovery/rebind rows identify internal.
  Existing OIDC tests assert these actors and the setup-failure route. New deployment tests
  cover environment defaults, new/empty/existing files, live/dangling symlinks and a pinned
  path replacement between chmod and write.
- **Mutation maintenance:** re-anchored ingr-16, auth-21/22/28, oidc-14/33/37. auth-21/22/28
  were already stale on main; auth-28 now exercises the dependency without the pre-routing
  gate, so that gate cannot hide a broken dependency. All 402 anchors match once. All seven
  repaired cases and twelve new single-site mutants killed in a detached snapshot with its
  own test DB: aud-18 worker pin; 19 nofollow; 20 chmod; 21 descriptor write; 22 setup target;
  23/24 OIDC failure/refusal actors; 25/26 startup actors; 27/28/29 rebind actors. Exact runner
  and logs remain in the local scratch directory named by `/tmp/plamotrack-208-scratch-path`.
  The complete 402-case mutation harness was not rerun.
- **State:** full backend **1,971 passed**, plus the subsequently added dependency-only check
  in the focused deployment/authorization run. Negative control before these fixes: **9 red /
  5 green**, all reds at the intended behavior. Ruff/format/render green; frontend lint,
  **487 tests**, build green. Fresh isolated packaged stack: matrix **0 failures**, all four
  canonical limits and 12 alternate spellings, authenticated/anonymous real MCP-client controls,
  non-vacuous password/PAT/session log scan. Exactly one API worker despite environment 4/8.
  Disposable stack/volume and mutation DB removed; dev Postgres left running and untouched by
  the packaged checks. No commit or push; resolved merge remains pending locally.
- **Next:** hold #208 until #212 is reviewed and merged. Live #212 tip is `529ad68`, CI green
  but latest review is **NO-GO**: f6 P1 refresh resurrects a revoked grant; f7 P2 rejected or
  unchecked refresh state becomes active; f8 P3 evidence-count correction. Desktop owns that
  work. After it lands, integrate latest main (complete this prepared merge first if keeping
  it), reconcile #212's OAuth limiter with #208's four family zones, preserve its 429 no-store
  envelope, and ensure every retained proxy path overwrites the private client-address header.
  Adapt the matrix to active discovery responses in OIDC mode; rerun local AND OIDC packaged
  gates, log scan, and a fresh security review before merging #208. Update the PR body/reply
  with the new evidence and real OIDC event name when posting is requested. Fold aud-1…29
  after merge. #210 is still open; the LXC stays put until M6 is finished.

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

## 2026-09-04 — Codex (GPT-5.6 Sol) — #193 review GO; four P3s addressed, PR #208 held for #191/#192

- **Done:** GLM 5.3 Flash reviewed PR #208 at `6a3c4ff`: **GO, four P3s, no P1/P2**.
  Reproduced all four before editing. At `f91a643`, nginx snapshots its normalised `$uri` in
  the server rewrite phase before `/api/` is stripped, so doubled-slash, dot-segment and
  percent-encoded spellings cannot bypass family 2/3/8/9 limit keys. The packaged matrix now
  drives all three spellings for all four families (12 cases). Documented that every private
  Compose-network peer is inside the client-address-header trust boundary. Rule 7.1 now names
  append-only audit recording as the sole no-write-gate exception. The unbounded pre-routing
  audit-volume sibling is filed as #210. PR body and numbered review reply are updated.
- **Decisions:** #210 is storage/commit pressure, not an auth bypass; do not put the audit
  recorder behind the collection write gate. Keep PR #208 open while Fable finishes #191 and
  starts #192, because #192 activates the family-8 surface and overlaps MCP/ingress. No merge
  now; the P3-1 normalisation fix must be present no later than #192's endpoint activation.
- **State:** feature fix pushed at `f91a643`; this hand-off commit follows. Local verification:
  backend **1878 passed**, focused auth/audit/ingress **556 passed**, Ruff/format/render green;
  frontend lint + **485 passed** + build; packaged matrix 0 failures across canonical routes and
  all 12 alternate spellings; non-vacuous password/PAT/session log scan clean. Runtime aud-17
  mutant (`$uri` snapshot → raw `$request_uri`) killed: all 12 spellings remained unthrottled.
  Scratch stack/worktree and disposable volume removed; packaged stack stopped; dev Postgres
  healthy on loopback. CI at `f91a643`: Frontend and Integration green; Backend running.
- **Next:** wait for #191/#192 integration state, rebase #208 if main moves, rerun the packaged
  ingress gate after any conflict resolution, and only then choose review/merge timing. After
  merge, fold aud-1…17 into `mutation_test.py`. The LXC stays put until M6 is finished.
