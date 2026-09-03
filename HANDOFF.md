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

## 2026-09-02 — Claude Code (Fable 5.1) — M6 begun: threat model + route matrix (PR #185, #29); Codex rounds 1–2 answered

- **Done:** `docs/design.md` §5 rewritten as the M6 threat model and route
  authorization matrix: current state (5.1), assets and actors (5.2–5.3), four
  deployment modes L/P/R/Dev (5.4), five principals × three scopes × thirteen route
  families with app-vs-ingress columns (5.5), fourteen threat rows + safe failure
  (5.6), what loopback keeps (5.7), the thirteen gating tests T1–T13 (5.8), a
  ten-issue implementation split (5.9); pointer edits in §4 and §11. Branch
  `feature/m6-threat-model`, **PR #185 open at head `790140d`** (not draft). **Codex
  round 1 (GPT 5.6 Sol): NO-GO, four findings, all reproduced at `81ff6bb` and fixed
  at `414f076`**, answered per finding in the PR thread: (1, P2) `/api/mcp/*` and
  `/api/openapi.json` are live ingress aliases of `/mcp/` and `/openapi.json` → §5.5
  gains "one spelling per family" at the ingress, T2 the encoded/doubled spellings,
  split item 1 the rejection; (2, P2) a `mode=merge` import updates
  `instance_settings`, crossing the admin boundary with a write token → import
  privilege is decided on the plan's content, T1/T6 gain that axis; (3, P3) uvicorn
  0.52.1 runs its proxy-headers middleware by default (trusts `127.0.0.1`), so
  `internal` must read the raw TCP peer → `--no-proxy-headers` + app-side forwarded
  address, T9 control; (4, P3) a FastMCP child mounted at `/mcp` emits
  `/mcp/.well-known/*` and no root discovery routes → parent installs
  `get_well_known_routes(...)`, child aliases pruned, both route sets snapshotted.
  Reviewer's qualifications on calls 5/7/9/11 folded in. **Codex round 2: NO-GO,
  three P3s, all reproduced at `414f076` and fixed at `790140d`**: (5) the parent-root
  discovery routes are reachable under `/api/.well-known` by the same rewrite → that
  namespace rejected too, the rejection list derived from the route table by T2, T2
  snapshots responses not route tables; (6) Starlette 1.4.0's slash redirect builds
  `Location` from the request scheme/Host with the query intact (`/kits/` → 307
  `http://<Host>/kits` on the real app) → `redirect_slashes=False` on both routers,
  T2/T9 assert no `Location` on non-canonical spellings; (7) T13 promised `pg_dump`
  restores MCP links while split item 5 allowed a file-tree store → storage-
  independent backup contract (database + OAuth store + `.env`). Family 8's root set
  tightened to the four routes `get_well_known_routes` really emits; `add_only` named;
  family 3/9 `mcp` cells → 401. PR body now lists calls 13–18. Earlier probes stand: non-JSON / no-`Content-Type` bodies 422 on
  `POST /retailers`; FastMCP's route set read from the pinned libraries.
- **Decisions (proposed in the doc; the owner approves via the PR):** every mode
  authenticates, no `AUTH_MODE=disabled` in the image; `instance:admin` = owner
  session only, no admin PATs in M6; `/meta`, OpenAPI and docs → `collection:read`;
  `GET /auth/session` is the anonymous bootstrap; `import/preview` + `mode=merge` →
  write, `replace_all` → admin; MCP OAuth tokens audience-bound to `/mcp`, PATs valid
  on both surfaces; `/readyz` → loopback TCP peer only, nginx 404 on top;
  loopback-origin-vs-loopback-host accepted (dissolves the Vite `changeOrigin` trap);
  CSRF = `SameSite=Lax` + Origin/Referer + session token, independent of `plan_hash`;
  anonymous unrouted `/api/*` → 401; the Host/Origin guard (absorbs #39) ships as
  **its own release** before any auth; cookie `Secure`/`__Host-` only on an https
  `PUBLIC_BASE_URL`; mode P (plain HTTP, private network) supported with the
  cleartext caveat. Nothing in #30's credential thread was re-decided.
- **State:** `main` at `a944ec8` + this entry. PR #185 is docs-only — no code, no
  migration, no suites run beyond the one settings-portability control; `git diff
  --check` clean, table columns checked by script; CI green at `81ff6bb` and `414f076`,
  running at `790140d`. The packaged stack was built once for the alias replay, then `down`
  (no `-v`) and the dev `db` overlay restored — `db` is up on `127.0.0.1:5432`.
  Working tree parked on `main` for the review window. PR #184 (`ja`, draft)
  unchanged, awaiting a native reviewer.
- **Next:** (1) owner decides whether to buy a **Codex round 3** at `790140d`
  (findings would number from 8; re-fill the brief from `.agents/review-brief.md`) or
  to rule directly — rounds 1–2 both landed in family 8 (the MCP/OAuth route surface),
  which is the row to read hardest; (2) owner rules on the eighteen "Deliberate
  calls" in the PR body; (3) on merge, **file the ten §5.9
  issues** under `M6 — Secure remote access` with their dependencies, close #29,
  and mark #39 absorbed by item 1; (4) the first implementation branch is §5.9
  item 1 (ingress identity + Host/Origin guard) — its own release, nothing rides
  with it. LXC: still pre-0.2.9, **back up before pulling** (two migrations
  pending) — unchanged from the 29/08 entry.

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

---
