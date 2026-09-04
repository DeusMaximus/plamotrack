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

## 2026-09-04 — Claude Code (Fable 5.1) — #189 (M6-4) MERGED (PR #202 → `f685c30`, Codex round 6 GO); pat- fold-in MERGED (PR #203 → `d237bb3`)

- **Done:** Codex round 6 (GPT 5.6 Sol) on `1479e1c`: **GO, no findings**, nothing open across
  six rounds. PR #202 squash-merged as `f685c30` on the owner's call (04/09), branch deleted,
  **#189 closed**. Then the harness fold-in `chore/fold-pat-mutants` → **PR #203** (harness-only,
  no external review — the #197/#199/#201 precedent): pat-1…25 into `mutation_test.py` with
  four new path constants (`TOK_SVC`, `TOK_FMT`, `RESOLVER`, `MCP_AUTH`), `TEST_FILES` +
  `tests/test_auth_tokens.py`; `-k pat-` → **all 25 killed** at fold-in; procedure doc: 353
  cases over thirty-one files. Squash-merged as `d237bb3` on green CI. Memory pointer updated.
- **Decisions:** none new. The six-round record is on PR #202; the two lessons that came out of
  it are in `.agents/lessons.md` ("The 401 contract").
- **State:** `main` at `d237bb3` plus this entry. Backend 1760, frontend 485, e2e 43+1 (CI). The
  shipped app: browser = owner session; REST scripts and MCP = personal access token
  (`ptk_…`, Settings → Access tokens); `/mcp/` bearer-only; wrong password / setup token = 403;
  no tested TLS path yet. Dev DB claimed with `e2e-owner-password`. No release cut — M6 ships as
  one release at the end. **Release-notes items so far:** `ALLOWED_HOSTS` lockout risk (M6-1);
  the instance comes up unclaimed (M6-3); `/mcp/` requires a PAT, wrong password / setup token
  is 403, never a token in a URL (M6-4).
- **Next:** (1) the two family-13 hardening items (design §5.9 item 3(b)): unrouted `/api/*`
  → 401 for anon, and parse-before-auth → both need a middleware-level check ahead of
  routing / body parsing; (2) #190/#192 MCP OAuth spike (§5.9 item 5) — can run in parallel;
  (3) audit/rate limiting (§5.9 item 8); (4) **LXC stays put until M6 is finished** (owner,
  03/09) — `ALLOWED_HOSTS` into its `.env` before the pull, back up first, it comes up
  unclaimed (setup token in `docker compose logs api`), and the personal Gunpla skill's
  MCP config will need a token.

## 2026-09-04 — Claude Code (Fable 5.1) — #189 (M6-4) PR #202: Codex round 5 (NO-GO, 2×P3, prose/evidence) addressed at `4fb946b`, round 6 pending

- **Done:** Codex round 5 (GPT 5.6 Sol) on `77fb1c9`: NO-GO, two P3s, no bypass; finding-9
  class gone, "other than 10–11, no remaining P1–P3 across five rounds". (f10) the round-4
  rewrite overcorrected to "every request / everything is authenticated" — liveness,
  `GET /auth/session` and login/setup are anonymous by design → both sentences (operations
  *Reaching it…*, AGENTS.md roadmap note) now say collection and administrative access is
  authenticated and name the anonymous entry points. (f11) PR body named `622965f` not the
  final corrective head `09ef061` → opening line now names `4fb946b`, rounds 1–5. Reply posted.
- **Decisions:** none new. Option 3's "positioned on the path" wording retained (Codex: accurate).
- **State:** branch head `4fb946b` (docs/process only since `ef7764d`; runtime unchanged since
  `5aca2e6`); CI on the merged head running when written. Tree parked on `main`. Dev DB
  claimed with `e2e-owner-password`. **Round 6 pending** (findings from 12).
- **Next:** (1) Codex round 6 → merge on GO (`Closes #189`), branch delete; (2) harness fold-in
  PR for pat-1…25; (3) the two family-13 hardening items (design §5.9 item 3(b)); (4) #190/#192
  OAuth spike; (5) **LXC stays put until M6 is finished** (owner, 03/09). Release notes for
  the M6 release: wrong password / setup token is 403; `/mcp/` requires a PAT; never a token
  in a URL.

## 2026-09-04 — Claude Code (Fable 5.1) — #189 (M6-4) PR #202: Codex round 4 (NO-GO, 1×P3, docs only) addressed at `09ef061`, round 5 pending

- **Done:** Codex round 4 (GPT 5.6 Sol) on `98a82b2`: NO-GO, one P3, no bypass; f6/f7/f8 held,
  "other than finding 9, no remaining P1–P3 across the four rounds". f9 = the posture sweep's
  last class: operations' *Reaching it from another machine* + its `WEB_BIND`/`PUBLIC_BASE_URL`
  rows, design §5.4 mode P and §10's alpha disclosures still said nothing was authenticated —
  plus two siblings the sweep found (AGENTS.md roadmap note, `.agents/review-brief.md` context
  line). All rewritten at `622965f` (+ `09ef061` fixing a "Nothing is authenticated" wording
  slip): owner session for the browser, PAT for REST/MCP automation, no tested TLS path, plain
  HTTP exposes cookie/token to a device on the path, SSH/VPN preferred, internet waits for
  §5.9 item 9. §5.1 stays the dated record. Reply + addendum posted; PR body head updated.
- **Decisions:** none new.
- **State:** branch head `09ef061` (docs/process only since `ef7764d`; runtime unchanged since
  `5aca2e6`); CI on the merged head running when written. Tree parked on `main`. Dev DB
  claimed with `e2e-owner-password`. **Round 5 pending** (findings from 10) — expected GO.
- **Next:** (1) Codex round 5 → merge on GO (`Closes #189`), branch delete; (2) harness fold-in
  PR for pat-1…25; (3) the two family-13 hardening items (design §5.9 item 3(b)); (4) #190/#192
  OAuth spike; (5) **LXC stays put until M6 is finished** (owner, 03/09) — `ALLOWED_HOSTS`
  into its `.env` before the pull, back up first, it comes up unclaimed. Release notes for the
  M6 release: wrong password / setup token is 403; `/mcp/` requires a PAT; never a token in a URL.

## 2026-09-04 — Claude Code (Fable 5.1) — #189 (M6-4) PR #202: Codex round 3 (NO-GO, 3×P3) addressed at `ef7764d`, round 4 pending

- **Done:** Codex round 3 (GPT 5.6 Sol) on `9ad3d4d`: NO-GO, three P3s, no bypass; f4/f5
  confirmed fixed, every call retained. Fixed at `ef7764d`: (f6) `e2e/auth.setup.ts` diagnosed
  "already has an owner" on `status === 401`, obsolete since the round-2 403 → keyed on the
  envelope code `auth.login_failed`, generic assertion for every other refusal; replayed by hand
  against the claimed dev DB with `E2E_OWNER_PASSWORD=definitely-wrong-password` (the intended
  message on the `auth.login_failed` branch) and with the right one (setup + `tokens.spec.ts`
  green). (f7) four stale "no MCP tokens yet" statements — `.env.example`, two
  `docker-compose.yml` comments, the README warning after the tool list — now state the real
  boundary (owner login for the browser, PAT for REST/MCP automation, no tested TLS path).
  (f8) PR-body counts corrected: `tokens.spec.ts` is 1 test (the "2/2" counted the setup
  project), matrix 54 rows locally without `--allowed-host`, 58 in CI with it. Reply posted.
- **Decisions:** none new. Release-notes item for the M6 release: **wrong password / setup
  token is 403** (was 401 in #188, never released), `/mcp/` requires a PAT, never a token in a URL.
- **State:** branch head `ef7764d` pushed (plus this hand-off merged in); backend 1760, frontend
  485, e2e tokens 1/1; CI on the merged head running when written. Tree parked on `main`. Dev DB
  claimed with `e2e-owner-password`. **Round 4 pending** (findings numbered from 9).
- **Next:** (1) Codex round 4 → merge on GO (`Closes #189`); (2) harness fold-in PR for
  pat-1…25 (`TEST_FILES` + `tests/test_auth_tokens.py`); (3) the two family-13 hardening items
  (design §5.9 item 3(b)); (4) #190/#192 OAuth spike; (5) **LXC stays put until M6 is
  finished** (owner, 03/09) — `ALLOWED_HOSTS` into its `.env` before the pull, back up first,
  it comes up unclaimed.

## 2026-09-04 — Claude Code (Fable 5.1) — #189 (M6-4) PR #202: Codex round 2 (NO-GO, 2×P3) addressed at `5aca2e6`, round 3 pending

- **Done:** Codex round 2 (GPT 5.6 Sol) on `51a7366`: NO-GO, two P3s, no bypass; f1 confirmed
  fixed, calls 1–7, 9, (i) retained, 8 and (j) overruled. Fixed at `5aca2e6`: (f4) the round-1
  narrowing ("challenge only at the bearer boundary") left challenge-less 401s on wrong
  password / wrong setup token, which RFC 9110 §15.5.2 forbids → those are now **403** via a new
  `CredentialRejectedError` (§15.5.4), codes unchanged, T11 intact; every remaining 401 carries
  `WWW-Authenticate`; prose aligned in `exceptions.py`, `services/auth.py`, `error_codes.py`,
  `dependency.py`, `main.py`, design §5.5 family 3 + §5.9 item 4, PR body (What + call 8); the
  envelope walker learned the class; `.agents/lessons.md` → "The 401 contract". (f5) the unit
  query-string test still sent a live PAT in a URI → fixed fake; CI's log scan was vacuous →
  captures `api`+`web` logs once, requires an access record from each (`GET /healthz` /
  `GET /api/healthz`), then greps for the token. Mutant pat-25 (403→401) killed; replay at
  `51a7366`: 6 red / 1 green. Reply posted, PR body amended.
- **Decisions:** 403 (not 400) for rejected form credentials — "credentials provided and
  insufficient" is the closest RFC fit and the codes stay the client contract.
- **State:** branch head `5aca2e6` pushed; backend **1760**, `test_auth_tokens.py` 100; CI on
  `5aca2e6` running when written — the non-vacuous scan step is the one to check. Tree parked
  on `main`. Dev DB claimed with `e2e-owner-password`. **Round 3 pending.**
- **Next:** (1) Codex round 3 on `5aca2e6` (findings numbered from 6) → merge on GO; (2) harness
  fold-in PR for pat-1…25; (3) the two family-13 hardening items (design §5.9 item 3(b)); (4)
  #190/#192 OAuth spike; (5) **LXC stays put until M6 is finished** (owner, 03/09) —
  `ALLOWED_HOSTS` into its `.env` before the pull, back up first, it comes up unclaimed.

