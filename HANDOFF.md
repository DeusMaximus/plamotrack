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

## 2026-09-04 — Claude Code (Fable 5.1) — #204 (M6-3b) family-13 hardening: branch `feature/m6-3b-family-13-hardening` PUSHED, PR OPEN, Codex round 1 pending

- **Done:** Issue **#204** filed (M6 milestone) for §5.9 item 3(b)'s two deferred items, then the
  branch. The fix is **the pre-routing gate** `app/auth/prerouting.py`: one middleware directly
  above `ResponseProfileMiddleware`, inside the ingress guards, that resolves the principal once
  per REST request (own short session), stashes it on `request.state` (the dependency reuses it —
  no double `last_used_at` touch / audit row), and refuses `anon` with the dependency's 401
  envelope (bare `Bearer`, `no-store`, no `Allow`) wherever the router would answer 404, 405 or a
  scoped 401 — read off the registry's `iter_dispatch_order` walk + `compile_path`, never the URL.
  Never grants; the dependency stays the authority. Calls recorded in design §5.9 item 3(b):
  anonymous families keep their 405/422; `INTERNAL` admitted on full, refused on partial; the
  `/mcp` mount is the child's; bare `/mcp` at the source-run app is now 401 anon / 404 owner.
  Also: `ingress_matrix.py` trailing-slash rows → family-13 rows (+ `/api/no-such-route`,
  `DELETE /api/kits`); design §5 header + family-7 row; AGENTS.md rule 13 paragraph.
- **Decisions:** the gate renders through `domain_error_handler` passed in by `create_app` (one
  envelope author, no circular import). `PUT /mcp/` → 405 with `Allow` to anon (the
  `RouteBinding`) is **out of scope, recorded on #204** for the reviewer to classify.
- **State:** committed and pushed on the owner's instruction; PR open (number in the entry title's
  follow-up commit). New suite
  `tests/test_auth_unrouted.py` **97 green**; negative control on unfixed `main` (trimmed copy,
  worktree, own DB) **23 red / 65 green**, every red an anon-side 404/405/422; **13 hand mutants
  f13-1…13 all killed** (runner + verdicts in the session scratchpad; tuples in the PR-body draft
  `scratchpad/pr-body-204.md`, to be folded into `mutation_test.py` by the usual harness-only PR
  after merge). Auth/ingress suites green (523); full backend run **1855 green** (started before the last two pins landed; the final file's own run is 97 green → 1857). T2's new rows are
  CI Integration's to prove (packaged stack not run locally — `up` would recreate the dev `db`).
  Dev DB still claimed with `e2e-owner-password`.
- **Next:** (1) **Codex review** round 1 (M6 security → Codex per `.agents/testing-and-review.md`);
  (2) on GO, merge
  (`Closes #204`), then the f13- fold-in PR; (3) #190/#192 OAuth spike; (4) #193 audit/rate
  limiting; (5) **LXC stays put until M6 is finished** (owner, 03/09). Release-notes items for the
  M6 release unchanged plus: anonymous unrouted/wrong-verb/malformed requests under `/api/` are
  401, not 404/405/422.

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
