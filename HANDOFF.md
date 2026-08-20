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

## 2026-08-20 — Claude Code (Fable 5) — #97 implemented: PR #115 open at `b7318c4`, Cursor round pending; 0.2.7 now gated only by #86

- **Done:** **#97 (MCP order read + correction) implemented on
  `feat/97-mcp-order-edit`; PR #115 open at `b7318c4`** (one commit, ~430
  insertions, no migration, no frontend). `get_order` and `update_order` tools
  in `mcp.py`, thin over the existing services; `changes` reuses `OrderUpdate`
  verbatim so #93's `received_at` correction works now and #95's fields flow in
  later (the `_KitPatch` precedent). **The issue's design question, decided:**
  items keeps REST's full-replacement semantics, but `update_order` (service)
  gained keyword `allow_line_removal` (default True — REST unchanged); the MCP
  tool passes `remove_missing_lines` (default False), so an items list that
  omits stored lines is refused *naming each line*, under the order's
  FOR UPDATE lock — a wrapper-side read-then-check would race a concurrent
  line addition. Explicit quantity decreases need no flag (a stated number is
  not silent). Docs: design §7 + README tool rows.
- **Decisions (on the PR as "Deliberate calls"):** per-surface defaults over one
  mechanism; omission-only gate; the refusal names the MCP flag from the
  service layer (only MCP can trigger it today); `InvalidInputError` not
  Conflict (payload completeness, not state); order deletion stays off MCP.
- **State:** backend **755** (742 + 13 in `tests/test_mcp_order_edit.py` — the
  §3.9 diff branches, both halves of the §6 snapshot contract through FastMCP's
  nested fields_set, both 409 guards *with* the flag, receipt correction,
  get_order axes), ruff clean, frontend untouched. Negative control: **13 red /
  0 green on unfixed `main`** (tools don't exist — expected shape for a
  new-capability suite; stated in the PR body). Both fix sites one-site-mutated
  and killed by the omission test; tuples in the PR body for the #86 fold-in
  queue (now #109's 17 + #111's 6 + #113's 8 + #115's 2). **Cursor brief in
  this session's scratchpad (`cursor-brief-115.md`), handed to the owner —
  round not yet run.** CI in progress at hand-off time. Live and still true:
  **#86 at `dfa7f29` owes its Codex round** and gates #44/#77/#87/#90, #95,
  #110, #112; #114 is M5.1-shaped; #104/#98/#99/#53/#54/#61/#63/#67 → 0.2.8,
  all clear of #86.
- **Next:** the Cursor round on #115, then answer it (reproduce at `b7318c4`
  first). Once #115 lands, **0.2.7 is #95-or-defer + the #86 gate** — nothing
  else in the milestone can move without #86. The 0.2.8 list is open ground.

## 2026-08-20 — Claude Code (Fable 5) — #94 + #96 closed: PR #113 merged as `93ec9cc` after one Cursor round; #112 + #114 filed

- **Done:** **#94 + #96 closed — PR #113 squash-merged as `93ec9cc`**, branch
  deleted, on the owner's call after one Cursor round (Grok 4.6) at `523deed`:
  GO, P2-1 + P3-1, both taken at `8928f3e`; CI green at every head. No second
  round: both remedies were the reviewer's own prescription, verified red-first
  and one-site-mutated (the #109/#111 precedent). P2-1: the
  #112 caveat omitted `series` from its own dropped-field list — one docs
  sentence. P3-1: blank/whitespace series stored and served by /kits/series —
  `_normalize_series` on both write paths (blank → null, values trimmed,
  matching parse_text) plus a `names.WHITESPACE` btrim guard on the distinct
  values; two tests red-first at `523deed`, three fix sites one-site-mutated.
  Also took the review's two pins (re-completion mirror; MCP naive build date)
  and filed **#114** (naive CSV dates read as midnight UTC — the class behind
  the starter sheet's date columns; M5.1-shaped). Reply posted at `8928f3e`.**
  Five separable commits: one additive hand-checked migration (three nullable
  `kits` columns, **no backfill** per #94's decision); #94 — `stamp_build_date`
  in `services/kits.py`, called by both live status writers (`update_kit`,
  `receive_order`'s advance), stamps only-when-null and never against an
  explicit value in the same request; importer and creation never derive
  (rule 10 by analogy; cell states keep absent=keep / blank=clear /
  populated=overwrite over a stored date); #96 — free-text `series`,
  `GET /kits/series` + MCP `list_kit_series` (most-frequent-first) feeding the
  kit form's datalist (`staleTime: 0`, the #49/#108 rule), `series=` filter on
  service/REST/MCP with the #49 fold; spec.py + starter sheet + docs updated.
  On owner feedback the Kits table now shows **Started/Completed** columns
  (elapsed days inline) and dropped the `status_updated_at` "Since" column;
  kit-side arrival date **considered and deferred** (recorded in design §3.1 —
  derivable only via the spawning order; lives on the order side for now).
  **#112 filed**: the starter sheet's retailer-bearing rows silently drop every
  kit-only field (`rating`, `build_notes`, now the three new ones) — proven via
  `expand()`; fix leans on the hybrid dispatch #86 is re-deciding, so sequenced
  after #86; disclosed in import-export.md meanwhile.
- **Decisions (on the PR as "Deliberate calls"):** stamp-only-when-null incl.
  re-completion; creation never derives; **no cross-field validation** (user
  owns the values; a service check would diverge from the importer); the
  browser series *filter* is client-side while the form typeahead uses the
  endpoint; `/kits/series` declared before `/{kit_id}` (route test pins it).
- **State:** backend **742** (713 + 19 `test_build_dates.py` + 10
  `test_series.py`), vitest 109, e2e 20 against a DB migrated from empty, all
  zero after; ruff/oxlint/builds clean. Negative control: **24 red / 1 green
  of 25 on unfixed `main`** (re-measured by the reviewer); round 1's four
  additions split 2 red (P3-1) / 2 green (pins) against `523deed`, stated in
  the PR body. **Worktree trap, learned:** `plamotrack_test`
  migrated to a branch head makes `main`'s conftest downgrade explode — drop the
  DB first; the Cursor brief warns about it. No mutants in the harness (#86's
  file); five hand-mutant tuples with once-matching anchors are in the brief,
  queued for the fold-in with #109's and #111's. **Cursor brief for #113 is in
  this session's scratchpad** (`cursor-brief-113.md`), handed to the owner —
  round complete — GO, answered. Live and still true: **#86 at `dfa7f29` owes its Codex
  round** and gates #44/#77/#87/#90; #104/#98/#99 → 0.2.8; #110, #112 and #114
  unmilestoned. Dev servers may be running on :8000/:5173 (this branch).
- **Next:** clear of #86, 0.2.7 has only **#97** left (MCP `update_order` /
  `get_order` — reuse `OrderUpdate` so #111's `received_at` correction and any
  later fields flow in like `_KitPatch` does for kits; the line-set-replacement
  foot-gun is the design question on the issue). **#95 needs #86** (its importer
  half mirrors the arriving-receipt question), so 0.2.7's release gate is #86
  itself unless the owner defers #95. Clear-of-#86 beyond the milestone: the
  whole 0.2.8 list (#104 keyboard picker, #98, #99, #53, #54, #61, #63, #67);
  #114 is M5.1-shaped. Waiting on #86: #95, #110, #112, and the mutant fold-ins
  (#109's 17, #111's 6, #113's 8).

## 2026-08-20 — Claude Code (Fable 5) — #93 closed: PR #111 merged as `322afe9` after one Cursor round

- **Done:** **#93 closed — PR #111 squash-merged as `322afe9`**, branch deleted,
  on the owner's call after one Cursor round (Grok 4.6) at `1ae9c4d`: GO, one P3,
  taken at `a78ce76`; CI green at both heads. P3-1: the UTC-12 test could
  not kill the `now(tzinfo)` → `now(UTC)` mutant at any hour (a behind offset's
  calendar date is never ahead of UTC's — the brief's "last second" claim was
  wrong, owned on the thread). Fix: a pinned-clock test (monkeypatched
  `app.services.orders.datetime`, frozen 2026-08-20T20:00Z) driving an honest
  "today in UTC+14 while UTC is on yesterday's date"; written red against the
  live mutant (`422 == 200`), green on restored production code; production
  check unchanged. Reply posted at `a78ce76`; PR body corrected (a negative-
  control red was mislabelled — it reds on the kit≠order microsecond stamp gap)
  and now carries the 5 `rcpt-` mutant tuples in a collapsed block for the #86
  fold-in. Design §3.9 gained the reviewer's Board-ordering cost sentence
  (an accepted behind-offset "today" can sit atop Backlog ~36 h). The
  REST/import stamp divergence the review confirmed was commented onto PR #86
  — importer-spawned kits on a received order still stamp now, by design;
  whether they should borrow `orders.received_at` is #86's decision. Entry takes an
  optional `received_at` (schema-refused without `received=true`); the receive
  route takes an optional `OrderReceive` body (absent / `{}` / explicit null =
  now, unchanged); `PATCH /orders/{id}` corrects an **already-set** date only —
  409 on a pending order (the transition stays in `receive_order` under its
  lock), explicit null refused. Kits a receipt lands in backlog are stamped with
  the order's instant — at receive, at received-at-entry create, and when a line
  edit spawns into an already-received order (previously server-now). A
  correction restamps exactly the kits whose stamp equals the old receipt; kits
  moved since keep their own. MCP `create_order` + `mark_order_received` gained
  `received_at` (offset required, friendly ToolErrors). Browser: receive is now
  a dated dialog (today = no body, server stamps the moment), the create
  checkbox reveals an inline date, edit of a received order gets "Received on"
  sent only when dirty. Helpers `isoToLocalDateInput`/`localMidnightISO` in
  `lib/format.ts` write the browser's offset out, never folded to Z. Docs:
  design §3.9 "Backdatable receipts" block, §7 signatures, README tool row.
  No migration; importer deliberately untouched (rule 10, #86's file).
- **Decisions (all flagged on the PR):** the future is refused as a calendar
  date judged in the instant's **own offset** (service 422) — an instant-vs-
  server-clock compare refuses an honest "today" over skew; a receipt earlier
  than `order_date` is deliberately allowed (plain date vs timestamptz is not
  comparable across unknown time zones); naive datetimes refused everywhere;
  the interim no-instance-tz decision is recorded in §3.9 for M5.1 (#23/#27).
  Kits asserted building/complete at entry keep entry-time stamps.
- **State:** backend **713** (684 + 29 in `tests/test_receipt_dates.py`), vitest
  109 (+9 `dates.test.ts`), e2e 20 (+`receive-backdate.spec.ts`), e2e verified
  against a DB migrated from empty, all tables zero after. Negative control:
  **23 red / 6 green on unfixed `main`** (re-measured at `a78ce76`), the 6 being
  compatibility controls (named in the PR body). Mutants: 5 hand-run tuples in
  the PR body (`rcpt-` prefixed, anchors verified to match once) — they join
  the fold-in queue with #109's 17 once #86's harness lands. GitHub
  runners recovered from the 2026-08-19 outage; every #111 run green. Live
  and still true: **#86 at `dfa7f29` owes its Codex round** and gates
  #44/#77/#87/#90; #104/#98/#99 → 0.2.8; #110 unmilestoned. Stale worktrees
  `/private/tmp/plamotrack-pr100` and `-pr108-main` remain, not this session's,
  left alone.
- **Next:** 0.2.7's remaining items clear of #86: **#94 + #96** (one branch, one migration,
  separate commits; both touch `spec.py` AND the hand-curated
  `STARTER_SHEET_COLUMNS`), **#95** after #86 (its importer half mirrors #86's
  arriving-receipt question), **#97** last — its order-edit tool should carry
  `received_at` so MCP gains the correction path #111 leaves REST/browser-only.

## 2026-08-20 — Claude Code (Fable 5) — #107 closed: PR #109 merged as `c177ea6` after one Cursor round; #110 filed; review-brief template landed

- **Done:** **#107 closed — PR #109 squash-merged as `c177ea6`**, branch deleted,
  on the owner's call after one Cursor round (CI all green at `486e14c`, the last
  code commit; the final docstring-only head was caught in the runner outage
  below, and `main` has no protection). **Cursor round 1 (Grok 4.6) at `49c1a9f`: GO, two
  P3s, both taken at `486e14c`** — P3-1: plain `btrim` trims `0x20` only, so a
  legacy row padded with tab/NBSP/U+3000 was two keys here and one to the
  importer; the trim set is now `names.WHITESPACE`, generated from `str.isspace()`
  at import (exactly `str.strip()`'s set), handed to `btrim(text, text)`. P3-2: the
  race test is pinned (holder takes the gate, both POSTs launched, wait on
  `pg_stat_activity` for both parked, release) — o5 killed deterministically.
  Drive-bys owned: I had miscounted the negative control (74 not 70 red) and the
  mutant table (16 rows under "17"; n1b makes it 17), and a regenerated tuple in
  the PR body was corrupted; all corrected, every anchor now checked to match once.
  "an upgrade" not "a upgrade". Reply posted at `d1d051d`; Turkish-`İ` addendum
  (importer key ≠ Postgres key, the reverse direction) commented on **#110**.
  **#110 filed** — the importer sibling, unmilestoned, owner's call.
  `services/names.py` is the predicate written once —
  `lower(btrim(name, WHITESPACE))` on both sides in Postgres, per #49 — plus
  `clean_name` (stored trimmed; whitespace-only → 422) and `require_unique_name`
  (409 naming the row and its id; own id excluded on a rename). Six sites, all
  after the write gate:
  `create_retailer`, `update_retailer`, the three catalog creates (one insert now),
  `update_catalog_item`, and `_build_catalog_row` (async) for `new_item` at entry
  and on edit. `get_or_create_retailer` reads through the same `find_by_name`, so
  `create_order` reuses exactly what `create_retailer` refuses. MCP docstrings and
  instructions updated; design §3.9/§7/§12.4 and import-export.md too. Browser
  untouched (forms already render `detail`). No migration.
- **Decisions:** refuse not merge (issue option 1); trim on store and refuse blank
  (not in the issue's text, follows from defining the key — said on the PR); two
  `new_item` lines naming one thing in one request 409 and roll the order back
  (declared, tested); the 409 carries the uuid (for agents; droppable). Importer
  **deliberately untouched** (#86's file) — probed, not assumed: an id-less
  in-upload pair is already an error row, an id-less match is an update; only a
  fresh *id-bearing* pair still lands, by design for round-trips → #110.
- **State:** backend **684** (556 + 128 in `tests/test_name_uniqueness.py`), ruff
  clean, frontend untouched. Negative control in a worktree: **99 red / 29 green on
  unfixed `main`**, the 29 being the controls. **17 single-site mutants killed**
  (n1b new) — run through a scratch copy of the harness because `mutation_test.py`
  is mid-rewrite on #86; the 17 tuples are in the PR body (collapsed block) for
  folding in once #86 lands. Two existing helpers that created one name twice now
  suffix it; `test_two_retailers_with_one_name_still_round_trip` seeds through the
  session. **`.agents/review-brief.md` landed on `main` (`d2180ef`)** — the
  fill-in template for briefing Cursor / Codex / Claude, pointed at from
  `testing-and-review.md` → "Briefing a reviewer"; use it for the next round
  instead of writing a brief from memory. CI: GitHub's runners have been hanging in
  `playwright install --with-deps` since ~15:12 UTC on every job, including
  docs-only commits — external; jobs self-cancel at the 25-minute timeout; re-kick,
  don't debug. Live and still true: **#86 at `dfa7f29`
  owes its Codex round** and gates #44/#77/#87/#90; #107 → 0.2.7; #104/#98/#99 →
  0.2.8. Worktrees `/private/tmp/plamotrack-pr100` and `-pr108-main` still stale,
  left alone; this session's `-107-main` removed.
- **Next:** fold the 17 mutant tuples from #109's PR body into `mutation_test.py`
  once #86's version of the harness lands (they are in a collapsed block there,
  anchors verified at `d1d051d`). Then 0.2.7's remaining items clear of #86: **#93**
  (backdatable `received_at` — must backdate the kits it advances),
  **#94 + #96** (one migration, separate commits; importer needs no logic change
  because it must not invent timestamps), **#95** after #86 (its importer half
  mirrors #86's arriving-receipt question), **#97** last.

## 2026-08-19 — Claude Code (Fable 5) — #86 pre-round: `main` merged in, harness false-kill fixed, two defects closed, authority rule changed

- **Done:** owner asked for a same-family pre-round on **#86** to make the next
  Codex round cheaper (not to replace it). Branch head is **`dfa7f29`**, pushed;
  two comments posted (at `e8cd2b3`, then `dfa7f29`). (1) `main` merged forward
  (`aefaecc`, clean). (2) **The mutation harness reported 13 mutants killed that
  never ran** (`fd8d195`): pytest exits 5 when `-k` deselects everything, read as
  RED; the merge at `5c0963b` had unioned the case sets under this branch's two
  target files. `TEST_FILES` is all three files; exit 5 reports `NONE`, counts as
  surviving. (3) **Defect:** a mistyped `order_item_id` on one kit in a pristine
  archive → 200, kit detached (#82 nulls a dangling optional ref) and a
  replacement spawned. `_refuse_unresolved_overwrite` in `_classify` (`43b947c`,
  `e8cd2b3`): an unresolvable optional REF may not clear a stored non-null link;
  also speaks first for a mistyped `catalog_ref_id` on a stored catalog line.
  (4) The arriving-receipt message offered a remedy the check never reads
  (`7c0dc55`). (5) **Owner's call, design question A taken (`5b1ccdd`):** a line
  is reconciled only where the upload *writes* its quantity (`_writes_quantity`:
  create, or `quantity` in `changes`), and the kit-move refusal reads only rows
  that *move* a kit. A restated archive line no longer authorises a delete or a
  spawn; a drifted archive merge re-imports as a no-op. Reverses round one's
  "any stated quantity" — flagged as such on the PR. Two tests re-driven where the
  change had shadowed their mutants (`2c7c082`, `5b19290`; the refusal's `present`
  guard is live only on a drifted line). (6) Docs: import-export states the rule;
  **operations.md "If you imported CSVs before 0.2.6"** — the drift query and the
  in-app fix (the order editor reconciles against the actual kit count); design
  §12.5 records the rule.
- **Decisions:** B (drift) → docs only, no migration/script: two fixes only a human
  can pick, and the app already reconciles on save; owner will start the dogfood
  instance fresh anyway. `test_review_rating_this_upload_writes_protects_provenance`
  (Codex's embedded reproducer) edited to add a replacement kit — the only review
  test touched, said on the PR.
- **State:** 651 backend, ruff clean, **63/63 mutants**, frontend untouched since
  `e8cd2b3` (build/lint/vitest clean there); e2e via CI. No migration. `main` is
  `2772cb1` plus this entry (amended in place, same session). Codex budget resets
  Thursday evening (owner); the round is owed at `dfa7f29`, and both
  `_refuse_unresolved_overwrite` and `_writes_quantity` are new code with no
  independent eye — the "where to push next" sections name the seams. Two stale
  worktrees on this Mac (`/private/tmp/plamotrack-pr100`,
  `/private/tmp/plamotrack-pr108-main`), not this session's, left alone. Live and
  still true: #86 gates #44/#77/#87/#90; #107 → 0.2.7; #104/#98/#99 → 0.2.8.
- **Next:** Codex round on #86 at `dfa7f29` — brief it with both comments' "where
  to push next" and say A is a reversal it should judge. Then the 0.2.7 list
  stands: #107, #93, #95, #94 + #96.
