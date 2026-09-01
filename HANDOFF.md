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

## 2026-09-02 — GPT-5 Codex (OpenAI) — PR #184 Japanese editorial review completed

- **Done:** Finalised the disabled Japanese catalogue on PR #184 at `0470285`.
  Corrected the value-dependent withdrawal prompt for both the empty and
  preformatted `(×N)` suffixes; completed the 注文明細/CSV 行 terminology
  distinction; and applied Fable 5's remaining high-confidence wording fixes.
  Added a value-level catalogue regression test and pushed the commit to
  `feature/ja-localisation`.
- **Decisions:** Keep `ja` disabled until a native Japanese hobbyist reviews the
  rendered application. Settled terms remain: インベントリ, 購入先, 追加パーツ,
  ディスプレイ用品 and 受領済み. Further LLM-wide rewrites would be churn.
- **State:** PR #184 remains open as a draft at exact head `0470285`. Frontend
  **470 passed**, focused catalogue **286 passed**, lint and production build
  green, and coverage **604/604** for both catalogues. The old withdrawal copy
  failed the new control on the empty suffix; byte-identical restoration was
  verified. Rendered Japanese checks passed for quantity 1/2 withdrawal,
  expanded order details/totals, and a blocking import diagnostic. Japanese was
  restored to disabled; disposable DB, preview hook and servers were removed.
- **Next:** Native Japanese hobbyist review. Do not enable or merge the language
  solely on the LLM reviews; action any human findings on this same PR first.


## 2026-09-01 — Gemini 3.1 Pro (High) (Google) — Initial Japanese localisation (disabled)

- **Done:** Created an initial Japanese translation catalogue `ja.json` mapped from `en-AU.json`, registered it as a disabled language in `manifest.json`, and exposed it in `registry.ts`. Validated the changes using the contributor checks. Pushed to `feature/ja-localisation` and opened draft PR #184. Fixed NO-GO review findings from GPT 5.6 Sol (P3-1 through P3-6) at head `0d3dbf9`.
- **Decisions:** Followed all translator documentation guidelines: kept all identifier variables exactly intact, translated to natural polite Japanese (Desu/Masu), strictly used `_other` for plurals according to CLDR rules, and left no English text purely for coverage padding.
- **State:** PR #184 is open as a draft. `ja` is currently disabled pending a native language and rendered view review. All checks (`npm test`, `lint`, `build`, `git diff --check`) passed locally. Head is `0d3dbf9`.
- **Next:** Await independent structural and Japanese-language review of PR #184 before any enablement.


## 2026-08-31 — GPT-5.6 Sol (OpenAI) — Translation contribution guide expanded

- **Done:** Expanded `docs/translating.md` into a self-contained contributor
  guide for the shipped M5.1 design: interface language versus independent
  regional formatting; the synchronous manifest → registry → i18next →
  settings runtime path; catalogue structure, placeholders, CLDR plurals and
  untranslated identifiers; exact disabled and enabled language changes;
  local checks; and enablement, update and human-review expectations. Named the
  coverage trap where copied-but-untranslated English values look complete.
  GLM 5.3 Flash reviewed PR #183 at `1e53a12`: **GO with three wording-level
  P3s**. All reproduced and corrected — value/placeholder terminology, the
  validator's group-wide plural-placeholder contract, and enabled-versus-disabled
  coverage drift; its locale-extension carve-out was documented too. The owner
  then authorised merge; PR #183 squash-merged as `6cf0f71` and the feature
  branch was deleted.
- **Decisions:** Documentation only — no application or catalogue changes.
  Partial translations remain welcome but disabled, omit untranslated leaves
  or whole plural groups, and use the `en-AU` fallback. A new formatting locale
  requires no registry entry; `Intl` consumes the stored canonical locale.
- **State:** `main` at `6cf0f71` (+ this entry), with PR #183 merged and its
  local/remote branch removed. Final-head CI: Backend, Frontend and Integration
  all green. Local verification: frontend **469 passed**, i18n report **604/604**
  `en-AU`, lint and production build green; backend settings **69 passed**;
  focused catalogue suite after review **285 passed**; `git diff --check` clean.
  No application code changed.
- **Next:** M6 remains the next product milestone.

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

---
