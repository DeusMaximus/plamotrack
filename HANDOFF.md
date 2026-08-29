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

## 2026-08-29 — Claude Code (Fable 5) — #178 implemented: order ambiguity split to its own code; PR #180 through Codex round 1

- **Done:** Branch `claude/178-order-match-ambiguous` → **PR #180** (`Closes
  #178`, **unmerged** — awaiting independent review). The order matcher now
  speaks `import.order_match_ambiguous`, declared `{count, matched_by}`
  exactly; generic `import.match_ambiguous` keeps `{count, table}`. The en-AU
  entry renders `{{matchedBy}}` via `matchedByLabel` (unknown values raw,
  singular/plural pinned); `LABELLED_PARAMS.matched_by` restored legitimately
  (#177 P3-4's guard now holds it reachable); the stale `apiError.ts` comment
  rewritten. Class sweep: `order_line.item_type_immutable` fixed in-branch
  (REST raise now sends `{before, after}`; registry declares the pair) and
  **#179 filed** for the raise-side siblings (`catalog_item.not_found`
  item_type, `_row_problem`'s undeclared row; `import.blocked`'s structural
  diagnostics named there as deliberate). The diagnostic-site audit is
  tightened to **exact equality** with the registry, extracted pure
  (`_diagnostic_param_violations`) with synthetic per-class negative controls;
  the two bridges are pinned by a runtime matrix in
  `test_import_diagnostics.py`. Fixture note updated to state both regimes.
- **Decisions:** issue option 1 (split the code) over optional registry params
  or a fabricated generic `matched_by`; no `table` param on the order code
  (the code names the table — retires "orders rows" phrasing); raise sites
  keep the superset audit deliberately (#179 owns the rest).
- **State:** evidence measured at `fb34b79` (later commits are comment/docs
  only): backend **1229**, vitest **469**, ruff + oxlint + build clean,
  from-empty e2e **40 + 1 skipped** (tables zero, e2e DB dropped). Pre-fix
  controls in the PR body: backend 3 red (both order emitters observed on the
  old code; the audit naming exactly importing.py:1297 + invariants.py:115),
  frontend 4 red. Seven hand-run mutations killed (1/1/1/3/5/1/1 failing
  tests), byte-identical restores verified; **`oma-` tuples queued in the PR
  body** for post-merge fold-in (two frontend mutants stay manually measured —
  no tracked frontend harness). Full harness at `20d0687`: **244/244 killed**,
  no anchor rot. Two aborted e2e runs were the owner's omlx-server holding
  `*:8000` (owner confirmed, stopped it) — environmental, not a defect. #167
  can't fire from-empty; not seen. No dev servers left running.
- **Round 1 (Codex, GPT 5.6 Sol): NO-GO, 2×P3 — both actioned at `d356ef1`.**
  P3-1: the bridge runtime matrix covered one of three reachable codes per
  bridge; a probe param on the `quantity_too_large` raise rode through 34/34
  green (reproduced at `7fc20d6` first). Matrix now drives every reachable
  outcome (small/large quantity, aggregate fan-out against a real order,
  starter-sheet cell + both quantity ends); both probe mutations
  (`quantity_too_large`, `order.fanout_limit`) re-measured killed; stale
  `_BORROWED` docstring fixed. Backend **1230** at `d356ef1`. P3-2: the PR
  body's "additive wire change" claim overruled and amended in place —
  **the 0.2.9 release notes owe one compatibility line**: order-match
  ambiguity moved from `import.match_ambiguous` to
  `import.order_match_ambiguous`.
- **Next:** owner's call on merging after the reply (round 2 if Codex
  re-reviews); do not merge on a standing NO-GO. After merge: fold
  the `oma-` set into the harness (re-check anchors, and whether the
  clean-tree/restore cover reaches the fixture and test files it mutates the
  way #151 extended it to `alembic/`). Then the 0.2.9-alpha release gate
  (M5.1 theme) from `testing-and-review.md`; M6 not begun. LXC: **back up
  before pulling** (real collection; 0.2.8's settings migration still pending
  there, and the instance zone/locale need setting after the M5.1 upgrade —
  see the `4bd98c0` entry).

## 2026-08-28 — Claude Code (Opus 5) — PR #177 review rounds actioned; #178 filed

- **Done:** Actioned the Codex review of #177 (five P3s, NO-GO) in `6fa048b` on
  `codex/176-m51-localisation-gaps`. Every finding reproduced at `0f77635`
  first, then fixed: **P3-1** `BoardPage`/`RetailersPage` now take
  `usePresentationVersion` (a `formatting_locale` change that is not also a
  language change never reached them), and the four raw visible numbers an
  independent re-sweep confirmed — both rating tooltips, `low_stock_threshold`,
  `row_number` — go through the formatter, the tooltips via a new
  `ratingTooltip` over `common.ratingOutOf`; **P3-2** `renderRequestValidation`
  is path-aware, translating an item only where its structured `field`/`type`
  both equal the English finding beside it (`field` vs `loc[1:]` dot-joined),
  degrading per item, never re-pairing; **P3-3** `importActionLabel` gains the
  `exists ? label : raw` fallback; **P3-4** the `action` and `matched_by`
  presentation branches were *unreachable* — which is why their mutants
  survived 449/449 — so both are deleted and `presentationValue` is now a
  table (`LABELLED_PARAMS`) held against the shipped catalogue; **P3-5** the
  `design.md` hardening paragraph is historical, stale open-issue inventory
  gone. Re-review confirmed all five fixed and re-measured the mutants
  independently, leaving one P3: the **PR body still carried the disproved
  evidence**. Body amended in place (banner + attribution), naming the invalid
  `7/240` control, the real `79/238` with 72 import failures, the withdrawn
  five-and-three mutant claims, and measured final-head totals.
- **Decisions:** Finding 4 answered at the root rather than by its suggested
  remedy — a `matched_by` consumer control **cannot** be written today, so a
  class guard replaced the dead branches. Disproved figures **named, not
  deleted**, so the correction records what the finding was about. #178 filed
  rather than folded in: different root cause, and it reproduces on `4bd98c0`.
- **State:** **PR #177 squash-merged `5b4635d`, #176 closed** — merged on the
  owner's call with the re-review's verdict on the amended body never recorded,
  so M5.1 shipped one round short of a GO. Nothing was known-broken at merge.
  Every number in the body is measured at `6fa048b` on a clean tree: backend
  1225, frontend 463, ruff check + format, lint, build, Playwright 40 passed /
  1 skipped on an isolated
  empty DB (created, migrated, verified zero, dropped). Six mutations killed
  1/1/4/1/7/2, plus the cold-Board e2e control red without the subscription.
  **Known, not ours:** `display-items.spec.ts:45` fails on any DB holding a
  categorised display item (`getByLabel("Category")` also matches the filter)
  — reproduced with the branch stashed, filed as #167; run e2e on an empty DB.
- **Next:** M5.1 is done and merged; **M6 is the next milestone** and is not
  begun. No version bump, tag or release yet — v0.2.8-alpha remains the latest.
  **#178** (`import.match_ambiguous`: two emitters share one code, so the orders-side
  `(retailer + date + lines)` hint is dropped and `matched_by` is undeclared in
  `api-error-codes.json` and pinned by nothing) is unstarted — the `apiError.ts`
  comment describing that gap predates the number and should gain the `#178`
  reference when someone next touches the file.

## 2026-08-28 — GPT-5 Codex (OpenAI) — #176 ready for independent review

- **Done:** Branch `codex/176-m51-localisation-gaps` implements #176 without
  migrations or API/CSV/data-model changes. Known portable field/table/action/
  matching values render through catalogue labels with unknown raw fallbacks;
  change rows use the same field helper. `request.validation` renders known
  `{field,type}` findings from `validation.request.*` and retains each unknown
  type's English `detail`. Counts keep raw `count` for plural selection while
  `countDisplay` uses the instance locale; the sweep covers import previews and
  results, diagnostics, order/kit/stock summaries, Board pills, and file size.
  `border-r` is now logical `border-e`; whitespace-only manifest native names
  are invalid; README/design/operations and nearby comments describe shipped
  M5.1 and its real limits/upgrade effects.
- **Decisions:** Preserve canonical API/MCP/database/CSV values, user-entered
  data, and English error detail on the wire; localisation is browser-boundary
  presentation only. One cohesive PR: all changes share that boundary.
- **State:** Direct pre-fix controls: 7 failures across the target frontend
  tests. Final: backend `1225 passed` (2 known zipfile duplicate-name warnings),
  frontend `449 passed`, lint/build green, and fresh-DB Playwright `39 passed,
  1 skipped`, tables zero; test DB removed. Mutations killed: count display,
  field/table/item/action/matching labels, request validation, RTL, manifest
  trim, and file-size formatter. No full backend mutation harness run: no
  backend emission sites changed. Working tree is ready to commit/push/open PR.
- **Next:** independent GLM 5.3 Flash review from the PR brief, re-measuring
  negative controls and mutation claims before any merge/release. Do not begin
  M6, version/tag/release work, or merge this PR before that gate.

---

## 2026-08-28 — Claude Code (Fable 5) — M5.1 CODE-COMPLETE: #26/#114/#27 closed; GLM 5.3 Flash is the new default reviewer

- **Done:** **#26 — PR #171 merged `359c8fe`** (2,087 ins, no migrations):
  every string in a successful preview payload is a `{code, params, detail}`
  Diagnostic on the #25 registry, rendered at `api.<code>` via
  `resolveDiagnostic`; per-problem `errors` list replaces `error`; 56 new
  codes; `matched_by` canonicalised; blocked apply carries its diagnostics in
  `params.diagnostics`; `tests/diag.py` kept ~150 old assertions meaningful.
  Fold-in **#172 merged `e7758a9`** (nd-1..5). **#114 — PR #173 merged
  `ac6788c`**: naive CSV datetimes read in the instance zone, attached once
  per plan in `_parse_row`; explicit offsets win; exports write `+00:00` so
  old archives re-import unchanged; zone change between preview/apply = stale
  409. Fold-in **#175 merged `825898b`** (tz-1..3; harness **244 cases**).
  **#27 — PR #174 merged `fedcc08`**: Language & region form (5 settings),
  `src/lib/presentation.ts` + `usePresentationVersion`
  (useSyncExternalStore) subscribing KitsPage/OrdersPage/InventoryPage/
  ImportPreview, Layout applies the row → i18next + document lang/dir,
  format helpers instance-aware (**plain dates render as the day they name in
  every zone**), `/meta` advertises `supported_interface_languages`, physical
  LR utilities → logical. **M5.1 has no open issues.**
- **Decisions:** #26 reuses the #25 registry/namespace (no `diag.*` fork);
  full per-PR lists in each PR body. **GLM 5.3 Flash (Zhipu, via T3 Code on
  OpenRouter) replaced Cursor as the default reviewer** (`13eff54` — roster
  table + brief footer updated; ~$0.07/round, 1M context; four rounds today,
  all substantive). Its #174 P3-1 *diagnosis* (cold-load staleness) was
  right; its *remedy* failed measurement — React Router's Outlet returns the
  same element reference, so page subtrees bail out of Layout re-renders; the
  shipped fix is the subscription store, pinned red/green both ways. Measure
  a reviewer's remedies like any claim. Codex reserved for write-gate/money/
  migrations/M6-security rounds.
- **State:** `main` at `825898b` (+ this entry), CI green at every merged
  head. Backend **1218–1224** per pre-merge branch (merged union unmeasured —
  CI's Backend job on `main` is the check), vitest **374**, e2e from-empty
  **39 + 1 skipped** (tables zero). Harness **244/244**; a #26 full run also
  fixed **six anchors rotted since #25** (n5/n6a/n6b/cat-13/14/wdr-8) — rule
  in `testing-and-review.md`: emission-site rewrites owe a FULL harness run.
  Known e2e: #162/#167 dev-DB-only; preorder-toggle #17-class flake fires
  under concurrent local load, clean quiet. Two process slips, owned on PR
  threads: a scratch runner restored uncommitted `Layout.tsx` via
  `git checkout` (the recorded trap — re-applied, re-verified), and branch
  switches ran under GLM's #173 round (park the tree during reviews — now in
  the procedure doc). No dev servers left running.
- **Next:** **release** (0.2.9-alpha — the M5.1 theme) via the gate in
  `testing-and-review.md`; then M6 (secure remote access — Codex-lane
  reviews). LXC: **back up before pulling** (real collection; 0.2.8's
  settings migration still pending there, and after this pull the instance
  time zone/locale start mattering — set them in Settings → Language & region
  after upgrade, or naive CSV imports and all rendering stay UTC/en-AU).


## 2026-08-28 — Claude Code (Fable 5) — #25 CLOSED: the REST error envelope (PR #169, two Codex rounds)

- **Done:** **#25 closed — PR #169 squash-merged as `28e32f7`** on the
  owner's call, branch deleted (final head `d76a20d`,
  1,188 insertions, **no migrations**): every failed REST response is now
  `{detail, code, params}` — **additive on the wire**: `detail` byte-identical
  in both shapes (string = service refused, FastAPI list = schema spoke; the
  discriminator stays load-bearing), and the pre-existing backend suite passed
  **untouched** (1187, zero test edits) as the proof. `DomainError(detail, *,
  code, params)` with code keyword-required; `app/error_codes.py` = 58
  `<domain>.<condition>` codes for the **81 raise sites**, all migrated (AST
  audit: none missing). New `RequestValidationError` handler labels the 422
  list shape `request.validation`; `ErrorEnvelope` on every router via one
  `include_router(responses=…)` line. Browser: `ApiError` gains
  code/params/detail, `message` = catalogue rendering via new
  `src/lib/apiError.ts` (63 `api.*` leaves; wire snake_case params camelized
  to `{{placeholders}}`), fallback = the exact pre-#25 behaviour; zero
  consumer churn. Registry ↔ catalogue ↔ params held together by
  `frontend/src/lib/__fixtures__/api-error-codes.json` (the money-cases
  device) from both suites. MCP ToolError = the bare sentence, pinned.
- **Decisions (full list in the PR body):** codes name conditions not sites;
  fixture declares the params **intersection** (guaranteed, not union);
  `request.validation` renders as its joined findings (sole code without a
  catalogue entry, named in the test); existing message-coupled assertions
  stay (they pin the fallback contract); `import.blocked` carries only
  `count` — restructuring the blocking diagnostics is #26's.
- **State:** **Codex round 1 (GPT 5.6 Sol): NO-GO — P2 + 2×P3, all real,
  all reproduced at `152f7cb` first, fixed at `23d9cf4`, reply posted.** P2:
  parser-stage multipart 400s escaped the envelope — now `request.body_invalid`
  via a StarletteHTTPException handler that envelopes 400s ONLY and delegates
  the rest (unrouted 404/405 keep the stock body, pinned). P3: OpenAPI marked
  `params` optional — default_factory removed, `required` == all three on both
  envelopes. P3: the declared-params invariant was inventory, not audit — a
  fixture-driven AST walk now asserts every raise site's literal params ⊇ its
  code's declared keys + every code raised-or-handler-emitted (≥81-site
  vacuity guard); Codex's surviving orders-writer mutant dies on it, upgrades
  writer measured too. **Round 2: GO + 2 P3s, both answered at `d76a20d`** —
  P3-4: the 400 was invisible to OpenAPI path responses (ERROR_RESPONSES
  gains 400 → ErrorEnvelope; /import/preview's 400 asserted); P3-5: stale
  counts in the amended PR body (fixed in place; **second count-correction a
  review caught this session** — re-measure from the final head, never carry
  forward). Suites at `d76a20d`: backend **1204** (17 in the envelope file),
  vitest **281**, from-empty e2e 36+1, zero leftovers. **Twelve measured
  mutants killed** (env-1..9 queued in the PR body for the post-merge
  fold-in + 3 frontend). No dev servers running.
- **Next:** merge fold-in **PR #170** (env-1..9 in the tracked harness,
  measured 9/9 killed; review skipped per #132/#160, owner concurs by
  merging)
  (TEST_FILES + `tests/test_error_envelope.py`), then **#26** (import-preview
  diagnostics on this contract — row messages, warnings, blocking errors,
  the stock note; `import.cell_invalid` is already coded and waiting to be
  threaded through). Then #27 (language/region controls), #114. LXC: **back
  up before pulling** (real collection; 0.2.8's settings migration still
  pending there).
