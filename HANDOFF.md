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

## 2026-09-07 — Claude Code (Fable 5.1) — #215 fixed (PR #216 → `a322f15`) and the #208 `aud-` set folded (PR #217 → `3344066`, 56/56 on the committed tree); both MERGED, no review; #194 next

- **Done:** (1) **#215** on `fix/215-ci-setup-token-argv` → **PR #216** (`040c613`): the
  Integration matrix step's three variable-valued options spelled attached
  (`--setup-token="$SETUP_TOKEN"`, `--token-out=…`, `--log-secrets-out=…`) with a comment
  above the step saying why; the procedure doc's hand-run instruction says the same.
  Proven against the real `ingress_matrix.main` parser with a leading-hyphen token
  (separate word: `SystemExit(2)`; attached: parsed). Backend/Frontend/Integration green.
  (2) **The `aud-` fold-in** on `chore/193-aud-mutants` → **PR #217** (`0cfdeb5`): 56 cases —
  aud-1…17 reconstructed from PR #208's prose descriptions against `bd40687` (aud-14 on the
  normalised snapshot), 18…58 verbatim from the record's two JSON blocks; four suites join
  `TEST_FILES` (`test_audit`, `test_audit_privacy`, `test_access_logging`,
  `test_deployment_hygiene`); the nginx template, `Dockerfile` and `ingress_matrix.py` join
  the clean-tree check. Harness **570 cases / 51 files** (procedure doc's count line
  re-derived). **56/56 RED on the committed tree** (`-k aud-`, ~8 min, tree clean after);
  first pass 55/56 — aud-23 GREEN on the record's selection (the id_token-rejected test
  asserts the row's detail, not its actor) → re-pointed at
  `the_owner_cancelling_at_the_provider_spends_the_transaction`, RED on replay.
- **Decisions:** aud-34/35 stay out — nothing in `tests/` reads the access-log format or
  `error_log /dev/null;`, so their only witness is the release gate's packaged log scan.
  aud-17/36, packaged-only in the record, fold on the four-families test's literal
  assertions (added by the P3 round). No full-harness run: the branch touches no emission
  site or anchored line; every anchor checked once (570/570), replacements compile, no
  `-k` prefix collision. No reviewer requested on either PR — owner's call (CI/process,
  not app code). Commit/push/PR for both was the owner's explicit choice this session.
- **State:** **both squash-merged 2026-09-07** on the owner's call — PR #216 → `a322f15`
  (#215 closed by the merge), PR #217 → `3344066` — with no review, matching the five
  prior fold-ins (#199/#201/#203/#207/#211, all unreviewed); CI green on both. `main` at
  `3344066` + this amended hand-off, tree clean, nothing uncommitted, **nothing in flight**.
  Branches `fix/215-ci-setup-token-argv` and `chore/193-aud-mutants` left in place.
  Dev `db` up; the Keycloak spike compose still up (`.agents/spikes/190/`, untracked —
  needed for the OIDC-mode release gate). The owner's **#194 work-in-progress is
  uncommitted on their MacBook**; they expect to redo it on this Mac — treat #194 as not
  started here. LXC untouched (**stays put until M6 is finished**).
- **Next:** (1) **#194** (M6-9: reference TLS deployment with Caddy + the operations/README
  rewrite) on a fresh branch — read the issue and design §5.4 first. (2) **#195**, the M6 release:
  the gate in `.agents/testing-and-review.md` — `ingress_matrix.py --mode oidc` against a
  packaged stack with the Keycloak spike, the register burst last — then bump via PR, tag,
  prerelease notes leading with the fail-closed upgrade path; the open M6 P3s
  **#206/#210/#213/#214** need a defer-or-fix call before the tag, #30 closes with the
  release. (3) Only then the LXC upgrade (back up first; `ALLOWED_HOSTS`; relink MCP
  clients; refresh the personal Gunpla skill).

## 2026-09-06 — Codex (GPT-6 Astra) — #208 post-merge GO; feature branch deleted

- **Done:** verified Daybreak's independent GO at `3f93b3c`, recorded in PR #208
  issuecomment-5558944536: P3-5/P3-6 resolved, no new P1–P3 findings, all ten calls
  accepted, no revert or corrective follow-up warranted. #208 was already squash-
  merged as `bd40687`; #193 is closed and #212 remains integrated. No second merge.
  Deleted local and remote `codex/193-audit-rate-limit-log-hygiene` at `f7f6089`,
  after confirming its tree equals the squash merge. Remote deletion used a lease.
- **Review evidence:** 113/113 privacy tests; independent negative control 70 red /
  27 green; all 21 new anchors checked; 10 source mutants plus packaged aud-17/35
  detected. Added temporary duplicate-XFF/empty-boundary and overlapping ASGI-task
  attribution/reset probes (2 passed, removed afterward). CI at reviewed `3f93b3c`
  passed (run 34029727544); the fix-head CI also passed. No code changed this turn.
- **History/state:** preserved all 123 prior entries and rotated the oldest verbatim:
  124 unique entries, five live. #212's merge record is archived intact. The separate
  #208 worktree remains on main; the primary dirty #194 checkout is untouched.
  PR body updated with the GO and added coverage. No release or deployment performed.
- **Next:** fold queued aud-1..58 in a separate change after checking current anchors,
  adding test_audit_privacy.py and test_access_logging.py to harness targets.
  #194 and the separate end-of-M6 security/deployment gates remain: concurrent real-
  socket attribution, live provider, TLS/Caddy/LXC/restore and long-duration limiter
  behaviour are not signed off by this GO. #206/#210/#213/#214/#215 remain separate
  questions. Keep the LXC upgrade behind the remaining M6 gates.

## 2026-09-06 — Codex (GPT-6 Astra) — #208 merged; independent post-merge verdict pending

- **Done:** committed P3-5/P3-6 and the redirect-test repair as `f7f6089`, pushed,
  and squash-merged PR #208 to main as `bd40687` after Backend, Frontend and
  Integration CI passed at the exact fix head (run 34029077765). #193 is closed.
  The PR body records the fixes, exact mutation recipes and coverage boundaries.
- **Review status:** the owner explicitly requested merge before the next Daybreak
  verdict. The prior review at `43c5826` remains NO-GO; the merge is not a new GO.
  A post-merge independent review is pending, findings numbered from 7. The separate
  end-of-M6 security/deployment gate remains; no release or LXC upgrade performed.
- **Validation:** local 2537 backend cases across full/focused runs; all 514 tracked
  plus 21 new mutants detected across full pass/replays. Full tracked pass was
  513/514 until oidc-19's collapsed Host/BASE witness was repaired; no production
  redirect change. aud-57/58 cover start/refused-callback siblings. Exact restoration,
  lint/format/generated ingress/whitespace pass. CI supplies the fresh complete run.
- **History:** all 122 prior branch entries and main's #212 records are unchanged.
  Added this entry and rotated the oldest verbatim: 123 unique entries, five live.
  The primary dirty #194 checkout is untouched. The #208 worktree is now on main;
  this follow-up commit only records the completed merge and rotates the handoff.
- **Review materials:** `/private/tmp/plamotrack208-daybreak-postmerge-brief.md`
  pins the merge/fix/review commits and is printed in full for the owner. The local
  `/private/tmp/plamotrack208-daybreak-run.py` wrapper selects a dedicated review DB;
  original dev DB remains healthy. Prior task DBs were removed. Evidence/recipes:
  `/private/tmp/plamotrack208-r2-*.log` and `/private/tmp/plamotrack208-r2-mutants/`.
- **Next:** obtain Daybreak's post-merge verdict and address findings on a follow-up
  branch. Fold queued aud-1..58 separately after rechecking anchors, adding
  test_audit_privacy.py and test_access_logging.py to harness targets. #206/#210/
  #213/#214/#215 remain separate questions. #194 and the remaining M6 gates precede
  the LXC upgrade; no deployment sign-off follows from this merge.

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

