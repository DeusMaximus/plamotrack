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

## 2026-08-31 — GPT-5.6 Sol (OpenAI) — Translation contribution guide expanded

- **Done:** Expanded `docs/translating.md` into a self-contained contributor
  guide for the shipped M5.1 design: interface language versus independent
  regional formatting; the synchronous manifest → registry → i18next →
  settings runtime path; catalogue structure, placeholders, CLDR plurals and
  untranslated identifiers; exact disabled and enabled language changes;
  local checks; and enablement, update and human-review expectations. Named the
  coverage trap where copied-but-untranslated English values look complete.
- **Decisions:** Documentation only — no application or catalogue changes.
  Partial translations remain welcome but disabled, omit untranslated leaves
  or whole plural groups, and use the `en-AU` fallback. A new formatting locale
  requires no registry entry; `Intl` consumes the stored canonical locale.
- **State:** Documentation-only branch `codex/translation-contribution-guide`,
  based on clean `main` at `378d736`; the owner authorised commit, push and PR.
  Verification: frontend **469 passed**, i18n report **604/604** `en-AU`, lint
  and production build green; backend settings **69 passed**; `git diff
  --check` clean. No application code changed.
- **Next:** Independent review and merge after the PR opens; M6 remains the next
  product milestone.

## 2026-08-29 — GPT-5.6 Sol (OpenAI) — Documentation drift corrected

- **Done:** Corrected the verified documentation drift at `392172d`: the README
  now scopes low-stock thresholds to consumables; `docs/design.md` has the current
  order-item conversion pair, a 29/08 revision date, and the four missing built
  routes in §4; `docs/import-export.md` now distinguishes kit-only receipt flips
  from catalog-bearing orders and uses an explicitly illustrative 0.2.9/current-head
  manifest; `AGENTS.md` names Settings/DataSection instead of the removed DataPage.
- **Decisions:** Kept every remaining `converted_price_aud_minor` reference because
  each describes the legacy CSV alias or rename history. Kept the separate
  “un-shipping isn't supported anywhere” statement because that claim is true on
  every writer. The manifest example carries current values but explicitly says
  exports write live metadata, preventing future example/version drift.
- **State:** Uncommitted documentation-only changes on clean-starting `main` at
  `392172d`. Focused backend verification: **6 passed** (exact MCP tool set, both
  kit-only receipt directions, archive manifest shape/version, and `/meta`
  language advertisement). `git diff --check` clean; no application code changed.
- **Next:** Review and commit the documentation update when the owner is satisfied.

## 2026-08-29 — Claude Code (Fable 5) — v0.2.9-alpha RELEASED (the M5.1 theme); oma- set folded (#181)

- **Done:** **#181 merged `df2702a`** — oma-1..7 in the tracked harness (7/7
  killed at fold-in; first targets outside `app/`, so the clean-tree check now
  covers the registry fixture — a dirtied fixture refusing the run was
  controlled before the counted run; `testing-and-review.md` corrected to the
  measured **251 cases over twenty-six target files**). **Bump PR #182 merged
  `f509c60`**; the release gate ran clean: M5.1 milestone 0 open / 8 closed
  (#179 unscheduled by design, no milestone); `GET /meta` **and** the MCP
  handshake's `serverInfo.version` both report 0.2.9; packaged stack built
  from `f509c60` — four services healthy, `migrate` Exited (0), `/api/meta`
  right, container-side export manifest carries `app_version 0.2.9` +
  `schema_version f9979ec7b9cb`; dev overlay restored after. **Tag
  `v0.2.9-alpha` pushed, release published `--prerelease`** (owner authorised
  this release explicitly). Notes lead with the data-facing changes: set
  Settings → Language & region right after upgrading; #114's naive-CSV
  time-zone change; the #178 `import.match_ambiguous` →
  `import.order_match_ambiguous` compatibility line.
- **Decisions:** packaged-stack `migrate` was a **no-op** — the compose volume
  was already at `f9979ec7b9cb` from this session's dev use — and I did not
  `down -v` to force a from-empty run: the volume holds the (throwaway but in
  use) dev collection, and from-empty coverage of the migration exists in
  every pytest session (downgrade base → upgrade head), the from-empty e2e
  DB, and the `mig-` harness cases.
- **State:** `main` at `f509c60` (+ this entry), CI green at every head
  including the merge and the bump. Suites at the tag: backend **1230**,
  vitest **469**, from-empty e2e **40 + 1 skipped**. No dev servers running
  (the session's preview pair was stopped for the packaged-stack step).
- **Next:** **M6 — secure remote access** (Codex-lane reviews per the
  roster) is the next milestone; M6.5/M7/M8 queue behind it. **LXC: BACK UP
  FIRST**, then pull/upgrade — it has **two migrations pending**
  (`2c97a5ced66a` display-items and `f9979ec7b9cb` settings; the old
  hand-off phrase "0.2.8's settings migration" was wrong — the settings
  singleton ships in 0.2.9), then **set Settings → Language & region
  immediately** or rendering and naive CSV imports stay UTC/en-AU.

## 2026-08-29 — Claude Code (Fable 5) — #178 CLOSED: order ambiguity split to its own code (PR #180, two Codex rounds)

- **Done:** **#178 closed — PR #180 squash-merged as `783a1a7`** on the
  owner's call after a Codex round-2 GO; branch deleted. The order matcher now
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
- **Round 2 (Codex): GO, no new findings** — replayed both probe mutations
  at `cfeb9ee` (exact undeclared-key failures, byte-identical restores, 16/16
  then 1230/1230 green) and independently re-derived the bridge-code
  enumeration: `_borrowed_diagnostic` ⊇ {quantity_too_small, quantity_too_large,
  order.fanout_limit}, `_row_problem` ⊇ {cell_invalid, both quantity codes} —
  the matrix drives every member. P3-2's amendment judged durable.
- **Next:** fold the **`oma-` mutant set** (queued in the PR #180 body) into
  `mutation_test.py` — re-check anchors, and whether the clean-tree/restore
  cover reaches the fixture and test files it mutates the way #151 extended it
  to `alembic/`. Then the **0.2.9-alpha release gate** (`testing-and-review.md`)
  — **the release notes owe one compatibility line**: order-match ambiguity
  moved from `import.match_ambiguous` to `import.order_match_ambiguous` (a
  client switching on the old code over order rows loses that branch). #179
  (raise-side catalogue-drop siblings) is filed, unscheduled. M6 not begun.
  LXC: **back up before pulling** (real collection; 0.2.8's settings migration
  still pending there, and zone/locale need setting after the M5.1 upgrade —
  see the `4bd98c0` entry). After merge: fold
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

---
