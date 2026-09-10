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

## 2026-09-10 — Claude Code (Fable 5.1) — #233 (M6.5 PR 3/4) built on `feat/233-home`: Home replaces the board, the order stage on the wire, `GET /summary` + `get_summary` from one function; **PR #237 MERGED into `m6.5-workbench` as `8bac10a`** (squash, 2026-09-10) after Codex round 1 NO-GO (P2 + 2×P3, fixed `7b4bbf1`) and round 2 GO + 3×P3 (fixed `80468d7`, merged on the owner's word without a replay round); #238 filed; next #234

- **Done:** `services/order_stage.py` — one predicate for where an order sits (`received`, else
  `in_transit`, else `pre_ordered` when every spawned kit is still one and there is at least one,
  else `ordered`); a computed `stage` on `OrderRead` (REST and the order tools alike); `GET /summary`
  (`routers/summary.py`, tag `summary` → family 4) and the `get_summary` tool over
  `services/summary.py::collection_summary` — kits per status, orders per stage, both statements
  under one `REPEATABLE READ READ ONLY` snapshot (rule 7.2, the export shape). Frontend:
  `pages/HomePage.tsx` (bench cards, the two strips capped at six with the server's counts and a
  *view all* link, three mail columns capped at three) over `lib/home.ts` (the pure rules); the two
  dialogs extracted verbatim into `components/KitFormModal.tsx` / `OrderFormModal.tsx`;
  `lib/invalidate.ts` (the one list of keys a kit write and an order write dirty, `summary`
  included); the Orders `?status=` filter speaks the stage vocabulary and reads `order.stage`;
  `BoardPage`, `kitStatusMutation` (#50's policy) and `@dnd-kit/core` deleted; `/board` → `/`;
  nav Home first (no `end` — React Router already treats `/` as a whole segment). Docs: README,
  AGENTS.md, design §1.1/§4/§7/§13.2 ("Built as #233"), translating, operations; the
  board/drag comment sweep; `docs/screenshots/home.png` replaces the two board captures.
- **Decisions:** (1) the stage is on the wire, not derived in the browser; (2) the Orders URL
  vocabulary changed to the wire's (`in_transit`, `ordered`, `pre_ordered`, `received`) — #232 is
  unreleased; the chip *words* on Orders and the column words on Home follow their artboards;
  (3) the summary reads one snapshot; (4) order counts bucket loaded rows, not SQL; (5) caps
  3 / 6 / none; (6) *day 1* on the start day; (7) catalog names from the four lists, fetched only
  when a card names a catalog line; (8) #50's test goes with the drag; (9) e2e counts are deltas
  against `/summary`, the empty case stubs by pathname.
- **Round 1 (Codex GPT-6, at `d6c8def`): NO-GO — P2** a kit edit refreshed the counts but not the
  order card's column (an order's `stage` is derived from its kits; `KIT_VIEW_KEYS` lacked
  `orders`); **P3** mail card headers lost the retailer / overflowed at 768–1024 px and under full
  dates (viewport breakpoints beside a 240 px sidebar); **P3** a tracking URL without a number was
  dropped. All three reproduced with e2e controls written first (red at `d6c8def` on the naming
  assertion), fixed at **`7b4bbf1`**: `orders` in `KIT_VIEW_KEYS`; the Home grids on a Tailwind
  `@container` with `@2xl/@3xl/@4xl` variants and a wrapping card header; tracking on number *or*
  URL (the Orders page's "link" fallback). Plus: `buildDay` comment (24-hour periods), harness
  **home-11** (Codex's `= 1` complement), the view-all assertion relative to the fixture's rows,
  a full-date width matrix in `settings.spec.ts`. Response + coverage-record round-1 block on the
  PR; Codex re-measured everything in round 1 (12/0 control, 10/10 + 8/8 + E1/E2, contrast of the
  grade chip and tag in both themes) and left a list of what stays untested (in the record).
  CI's first Backend attempt was cancelled at the 20-min cap at 89 % — a slow runner (every file
  1.2–3.8× slower than the last green run); the re-run passed in 12 m 33 s.
- **Round 2 (Codex, at `7b4bbf1`): GO + 3×P3, all fixed at `80468d7`** — full dates squeezed a completed
  kit's name to one letter on a two-up strip (rows wrap now, 9 rem floor under the name, no fixed
  height); a blank/whitespace tracking number hid a valid link (`lib/home.ts::trackingOf`, 10 unit
  cases); a failed retailer or catalog read passed off as "an unknown retailer" / "tool" with no
  banner (the banner covers the supporting reads; "Retailer unavailable" when the lookup failed —
  Codex overruled my scope deferral, rightly: the page is new). Controls red-first at `7b4bbf1`;
  hand mutants E5/E6 killed. Codex also ran a 42-combination width × locale matrix, a real
  PAT-over-HTTP `get_summary`, and an ARIA snapshot; the order dialog's `Loading…` on a failed
  catalog list is an accepted follow-up (predates the extraction) — **file it on merge**.
- **Merged:** PR #237 squash → **`8bac10a` on `m6.5-workbench`** (CI green on `80468d7`: Backend
  13 m 41 s, Frontend, Integration); the feature branch deleted. **#233 and #122 stay open** —
  a merge into the integration branch closes nothing on GitHub (only `main` does); they close
  with the release PR, like #231/#232 (status notes posted). **#238 filed**: the order dialog
  stays on Loading… when a catalog list request fails (Codex round 2's accepted follow-up).
- **State:** `m6.5-workbench` = `8bac10a` + merges of `main` (the hand-offs), local ahead of
  origin by those merges; `main` holds four unpushed hand-off commits. Green at that tree:
  backend 2693 (at `d6c8def`; no backend source since), unit 558, e2e 64 + 1 skipped serially
  from an empty DB (all tables 0 after), ruff, lint, build. Control 12/12 red on the base.
  Mutants: `home-` ×11 11/11 killed on `7b4bbf1` (no backend change since); 8 unit + 5 e2e (E1,
  E2, E4, E5, E6) killed by hand, 1 e2e mutant (NavLink `end`) dead → removed. Unit 568, e2e
  65 + 1 skipped at the round-2 head. PR body ready in the session scratchpad (`pr-body-233.md`), brief
  printed in the chat. Dev DB untouched; the Browser pane has a live owner session on it (used
  for the look); Vite left running, the `api` preview stopped. `.claude/launch.json` is tracked
  (`api`, `frontend`) — I overwrote it once from the wrong cwd and restored it.
- **Next:** #234 (Settings, About, the e2e suite, README captures in the new look) off
  `m6.5-workbench`; then the release PR. Then
  #234 (Settings, About, the e2e suite, README captures in the new look) off `m6.5-workbench`;
  merge `main` into the integration branch after each hand-off; a packaged-stack run before the
  release merge; hold the release hand-off commit until after the merge.

## 2026-09-10 — Claude Code (Fable 5.1) — #232 (M6.5 PR 2/4) reviewed by Codex (GPT-6) over four rounds and **MERGED into `m6.5-workbench` as `3faca69`** (squash); the order `recent` clock moved into the application; the kit status clock has one source; next #233 (Home) off `m6.5-workbench`

- **Done:** **Round 1 NO-GO (P2 + 5 P3)** — the order `recent` clock cast `order_date` in the SQL
  session's zone; the search box lost burst keystrokes (React Router navigates in a transition, and
  a controlled input read from the URL is restored before the update commits); the converted total
  suppressed on the header currency; a zero shipping cost hidden; the pencil 2.72:1 on a hovered
  row; the lines box's type column drifting — fixed `edd3ada`, plus a no-op merge of the base
  (`0baa1db`) to clear GitHub's stale "conflicting" state, which had also silently skipped CI on
  the branch. Found meanwhile: the kit status clock had two sources (create = Postgres `now()`,
  move = API clock; OrbStack's db clock runs 5–20 ms ahead of the host) → a Python default on the
  model, pinned by a frozen-clock test. **Round 2 NO-GO (P2 + P3)** — Postgres's zone files lack 97
  names the settings accept and read CET/EET/MET/WET as fixed offsets → the clock and the sort left
  SQL (`last_status_change`, a stable Python sort, `limit` after; an every-accepted-zone test;
  Havana's transition policy named in §13.4) `edd3564`; a same-currency snapshot of a different
  amount hidden → amounts compared. **Round 3 GO + P3** — equal instants across zone
  representations compared unequal (PEP 495: a `fold`-sensitive local datetime ≠ any other zone's)
  so the date tie-break never ran → `_recent_key` = clock − epoch, a timedelta, `5aa246d`. 32
  mutants over four rounds, all killed (table + exact edits on the PR; superseded anchors marked).
  README captures regenerated (round 2). Lesson: `.agents/lessons.md` → "Four rounds in one
  function". Roster row updated in `.agents/testing-and-review.md`.
- **Decisions:** (7) `useSearchParam` — the box owns its value, the URL follows with `replace`, any
  non-REPLACE navigation resets the box to the URL; (8) `convertedTotal` is suppressed only when
  every line is in the snapshot currency *and* the snapshots sum to the lines' subtotal; (9) a
  shipping line with a service and no cost shows the service and a dash, never a zero; (10) every
  *generated* kit status stamp is the API's clock — a supplied ship/receipt instant is recorded as
  given; (11) `--faint` retuned (dark `#746f66`, light `#878176`) so it holds 3:1 on the chip, the
  hover ground; (12) the `recent` order sort is computed by the application and loads every
  (pending-filtered) order before slicing — Codex measured 326 ms / 30 MiB at 3,000 orders — the
  milestone's trade (rank first, load the selected rows, if a collection ever needs it); (13) on a
  transition day a repeated midnight is its *first* occurrence and a skipped one reads with the
  offset that held before it (Postgres picks the second); (14) ties compare as instants.
- **State:** `m6.5-workbench` = `f99e085` (#231) + `3faca69` (#232) + merges of `main`; the
  feature branch deleted. CI green at `5aa246d` (run 34435324567). Green at that tree: backend 2680
  (three sequential chunks — one pytest at a time), unit 548, e2e 55 serial + 1 skipped, lint,
  build, ruff. Dev servers off; the dev DB untouched (its owner password is not the e2e default —
  the from-empty recipe is in the testing doc; free :8000 first). Checkout parked on
  `m6.5-workbench`. **Reviewer calibration:** Codex GPT-6 found two hidden P2s in the order clock
  across rounds 1–2 and the tie P3 in round 3, each with a ready reproduction and both halves of
  the remedy; it re-measured every mutant and corrected the author's table twice (B4 three not
  two; "ten" was thirteen); the visual leg (contrast composed in the browser, artboard comparison)
  worked. Four rounds in one function is the signal `testing-and-review.md` names — see the lesson.
- **Next:** **#233 (Home)** off `m6.5-workbench`: replaces the board, drops dnd-kit, per-status
  counts from one service function, `/board` → Home; the `?status=&sort=recent` links exist;
  Home's strips call `list_kits`/`list_orders` with `sort=recent` and a `limit`. Then #234. Merge
  `main` into the integration branch after each hand-off; a packaged-stack run before the release
  merge; hold the release hand-off commit until after the merge (the 0.3.0 lesson). Open
  observation from round 1, not fixed: two Playwright specs flake under parallel local workers
  (serial is CI's setting and green).

## 2026-09-10 — Claude Code (Fable 5.1) — #232 (M6.5 PR 2/4) built on `feat/232-list-urls-sort-edit-control`: URL filter/sort/page on the four list pages, one edit control per row with Delete in the dialog, `sort`/`limit` on the kit and order lists (REST + MCP); **PR #236 open against `m6.5-workbench`**, awaiting the owner's reviewer call

- **Done:** backend `list_kits(sort=created|recent|name, limit=)` and `list_orders(pending_only=,
  sort=placed|recent, limit=)` — "recent" is a kit's `status_updated_at`, an order's last status
  change (received, else shipped, else placed); one validator (`check_list_options`; codes
  `list.sort_unknown` / `list.limit_invalid` in the module, the shared fixture and the catalogue);
  routers typed with the Literal + `Query(ge=1)`; the MCP tools pass their strings through;
  `pending_only` moved into the query (REST gained it for parity). Frontend: `src/lib/listState.ts`
  (total readers, `paginate`, `pageWindow`, the hooks, `useWriteParams` for several keys in one
  navigation) and the four pages onto URL state — Kits `status/series/q/sort/page`, Orders
  `status/retailer/q/sort/page`, Inventory `tab/category/page`, Retailers `q/page`; the count beside
  the title; the toolbar; a ten-row pager; a pencil `IconButton` per row; Delete inside every edit
  dialog; the Orders lines box (kit status chips, "stock applies on receipt", the shipping line, the
  lines' converted total under the order's); icons on the header buttons, the "+ " gone from the
  labels. Docs: design §7 tools, §13.4 built, README rows. Tests: backend sort/limit/pending (rows
  diverging), MCP parity; unit 22; e2e `list-urls.spec.ts` (4); locators moved (labels,
  `getByLabel("Retailer")` → the combobox role, inventory edit says Save). README screenshots
  regenerated on the throwaway DB. Mutants B1–B6, U1–U4, E1–E3 all killed (table on the PR).
- **Decisions:** (1) filters and the search narrow the loaded list in the browser; only the sort is
  the server's (the page holds the whole list; Home will pass status + limit); (2) Kits default
  `recent`, Orders `placed`; the API defaults are unchanged; (3) ten rows a page, client-side, no
  `offset`; (4) the inventory edit dialog says Save (it said Add); (5) the quick-add retailer
  control is icon-only, named "New retailer"; (6) the converted total is the lines' snapshots and
  says nothing when a line lacks one.
- **State:** branch = `m6.5-workbench` + `c4cdcc3` + `514e0a3`, pushed; PR #236, **CI green at
  `514e0a3`**. `514e0a3`: `test_int4_bounds` refused the tools' bare `limit: int` — every integer an
  MCP tool takes declares its ceiling — so `limit` is `PositiveInt4` on both doors (replacing
  `Query(ge=1)`); that moved the parity test's `limit=0` refusal to the schema and mutant B5
  survived until the test asked *both* lists for an unknown sort. Green: `npm run lint`, `npm test`
  (537), `npm run build`, the e2e serially on an empty DB (51 + 1 skipped), ruff, the full backend
  suite 2672 passed (three sequential chunks).
  Both dev servers restarted on the dev DB; the dev DB untouched. One trap met twice today: a
  preview `api` on the dev DB makes Playwright *reuse* it — the setup project refuses (correctly)
  and nothing runs; free :8000 first. The from-empty scripts live in the session scratchpad only.
- **Next:** the owner picks the reviewer for #236 (Codex did #235 with a visual leg; the brief
  shape is on record) → respond → merge into `m6.5-workbench`. Then #233 (Home: replaces the
  board, drops dnd-kit, per-status counts from one service function, `/board` → Home; the
  `?status=&sort=recent` links now exist) off `m6.5-workbench`, then #234. Merge `main` into the
  integration branch after each hand-off; the packaged-stack run before the release merge.

## 2026-09-10 — Claude Code (Fable 5.1) — #231 (M6.5 PR 1/4) built on `feat/231-workbench-tokens-theme-sidebar`: Workbench tokens, per-browser theme, bundled Inter, Lucide, new sidebar, every page swept; PR #235 against the integration branch `m6.5-workbench` — **MERGED `f99e085`** (squash, 2026-09-10) after Codex round 1 (GO + 3 P3, fixed); M6.5 lands on `main` in one release (owner's call)

- **Done:** `frontend/src/index.css` holds the §13.1 tokens (dark default, light under
  `[data-theme="light"]`) and hands them to Tailwind through `@theme inline`, which also
  **removes** the stock palette, radii and shadows; `scripts/check-palette.mjs` refuses any
  palette utility under `src/` and `npm run lint` runs it (CI unchanged). Theme: light / dark /
  follow-the-device in `localStorage` (`src/lib/theme.ts`), applied before first paint by
  **`public/theme.js` as a blocking head script — not inline, because the bundled nginx serves
  the SPA under `script-src 'self'`**; `theme.test.ts` evaluates that file against the same
  cases as the module (value × device axes) and `e2e/theme.spec.ts` proves switch-without-reload,
  survive-a-reload, and follow-the-device live. `@fontsource-variable/inter` bundled (main.tsx);
  `lucide-react` for every icon (nav, theme, close, chevrons, stars); the emoji and the ★/▾/✕
  glyphs are gone. Sidebar (§13.3): sticky, wordmark + brand mark, Board/Kits/Orders/Inventory/
  Retailers, Settings alone below, footer with the theme switch, an identity line in OIDC mode
  ("name · via provider host") and Sign out; the tagline stays on sign-in and About. Backend:
  `SessionRead.display_name` (owner's read only, null in local mode) — 3 tests. `ui.tsx` gained
  `PageTitle`, `Chip` (dot + word in a status colour), `RatingStars`, `MICRO_LABEL_CLASS`,
  `TABLE_HEAD_ROW_CLASS`; `StatusBadge`, order/retailer/inventory/import pills all use `Chip`.
  README screenshots regenerated in dark (`screenshots.spec.ts` now sets `colorScheme: "dark"`).
  Docs: design §13.1 (head script, why), AGENTS.md lint line, testing-and-review lint row.
- **Decisions:** (1) nav's first entry stays **Board → `/board`** with a dashboard icon until
  PR 3 lands Home — a "Home" label on a kanban would lie for one PR. (2) Order-status chips use
  the pipeline colours: pending = ordered blue (was amber), shipped = in-transit amber, received
  = complete green, pre-order = pre-ordered purple — the artboards. (3) Button labels keep their
  "+ New order" text (e2e locators; PR 4 owns the e2e suite). (4) `th { text-align: start }` in
  the base layer — the UA centred every header. (5) Row Delete buttons stay until PR 2's one
  edit control per row. (6) **Integration branch** (owner, 2026-09-10): `m6.5-workbench`, cut
  from `e89f114`; #231–#234 open against it, `main` is merged *into* it whenever `main` moves
  (never rebased — the PRs stack on it), and it lands on `main` through a release PR with a
  merge commit, that commit gated, tagged v0.4.0-alpha — so a `git clone` mid-milestone (the
  README's install path) gets the 0.3.0 interface, not a redesign in progress. Recorded in
  AGENTS.md (Git conventions) and design §13.6.
- **State:** `feat/231-workbench-tokens-theme-sidebar` = `e89f114` + `eac24e1` + a merge of
  `main`, pushed; **PR #235** open against `m6.5-workbench` (= `main` after this hand-off
  commit, by merge). Checkout left on the feature branch so the dev stack shows the new look. Green: `npm run lint`,
  `npm test` (509), `npm run build`, backend `ruff`, `pytest tests/test_auth_local.py
  tests/test_auth_oidc.py` (122), full Playwright from an empty `plamotrack_e2e` (43 passed,
  self-cleaning) plus `theme.spec.ts` (3). The dev DB's owner password is **not** the e2e
  default, so e2e against it stops at setup — use the from-empty recipe. Dev DB untouched
  (fixtures from 2026-09-08). Both dev servers running from this session. Not done: a
  packaged-stack (`docker compose up --build`) run to see `theme.js` served under the CSP —
  do it before merge; and the LXC still runs what #195 shipped.
- **Review (owner's call, 2026-09-10): Codex (GPT-6), not GLM** — the round has a visual leg
  (captures in both themes against the Workbench artboards) that needs a reviewer that reads
  images; the brief was printed in the session chat and the PR body carries the coverage
  record and a 12-row mutant table. E3 (head script removed) had survived the theme e2e; the
  pre-paint test now records `document.readyState` at the first `data-theme` write and kills
  it (`1effab1`). The owner signed off the look on the dev stack. **Tree parked on the feature
  branch, both dev servers stopped**, for the review window.
- **Codex round 1 on #235 (GPT-6): GO + 3 P3, all reproduced at `46a7da5` and fixed at
  `7982565`** — P3-1 light-theme contrast (the artboard's light accent and five status hues
  measured 3.45–4.36:1 on the chip; the light set is the same hues darkened, informational
  `text-faint` moved to `text-muted`, new `src/lib/tokens.test.ts` parses `index.css` and
  asserts every composed pair in both themes); P3-2 the theme switch's arrows moved from the
  stored preference, not the focused radio (fixed; two-page e2e with a real `storage` event);
  P3-3 `rounded-[2px]` (now `rounded-sm`; the guard refuses arbitrary radius/shadow/colour
  values too). Response and the round-1 coverage record on the PR. **Observation, not a
  finding:** a *parallel* local Playwright run on this Mac timed out `preorder-toggle` and
  `dialog-keyboard`'s picker selection at their 5 s waits, twice; serial (`--workers=1`,
  CI's setting) is green — a load flake of the #17 shape, untouched.
- **Merged:** #235 squash → **`f99e085` on `m6.5-workbench`** (owner's call; CI green on the head
  `d36b2f5`); `feat/231-…` deleted. `main` = the 0.3.0 interface plus hand-offs, and is merged
  into `m6.5-workbench` after each hand-off. **`feat/232-list-urls-sort-edit-control` cut from
  `f99e085` and checked out, nothing on it yet**; both dev servers restarted on the dev DB so the
  owner can see the merged look. #231 stays open until the release (status note on the issue).
- **Next:** #232 on that branch, PR against `m6.5-workbench` (URL
  filter/sort, row edit control, sort/limit on REST **and** MCP), #233 (Home, drop dnd-kit),
  #234 (Settings, About, e2e, README) per design §13.6 — each branched from and targeting
  `m6.5-workbench`. Before the release merge: the packaged-stack run above.

## 2026-09-09 — Claude Code (Fable 5.1) — M6.5 direction decided: **Workbench** (design §13); mockups on a private design canvas; dev DB seeded with fixtures; docs committed, the four-PR split filed as #231–#234; no code yet

- **Done:** a design walkthrough with the owner on the running dev stack, then three
  directions drawn on the same screens (Home dashboard, Kits, Orders; dark, plus a light
  variant) on a Claude Design canvas — a private artifact on the owner's account, not in
  the repo. **Owner chose Workbench** (warm near-black, one amber accent, hairline borders,
  flat surfaces, Inter, Lucide, no emoji); Console liked and kept as a possible second
  selectable theme later; Editorial set aside. Every product decision from the walkthrough
  is written into **`docs/design.md` §13** (13.1 tokens + per-browser light/dark/system,
  13.2 Home replaces the board, 13.3 sidebar, 13.4 URL filter/sort on the list pages, 13.5
  phone/tablet deferred, 13.6 the four-PR split); §11 item 11, `AGENTS.md` roadmap 6.5 and
  the README row point at it.
- **Decisions:** (1) theme is the one per-browser preference (localStorage, applied before
  first paint) — everything else stays instance-wide (rule 11); (2) Home replaces the
  kanban: Building as a hero strip, Backlog / Recently completed capped at six with true
  counts and view-all links into the list pages filtered by status and sorted by
  `status_updated_at`, an In-the-mail strip of ORDER cards (a mixed order sits under
  Ordered with a pre-order tag); no drag-and-drop on Home; edit is a visible corner
  control, not right-click; (3) Settings alone above a footer with the theme switch and
  Sign out (+ an identity line in OIDC mode only), the sidebar fixed while the page
  scrolls; (4) the tagline leaves the sidebar for sign-in and About; (5) phone/tablet is a
  later, separate UI; (6) confirmed by the owner in the same session: no drag-and-drop on Home, and one
  edit control per list row with Delete inside the dialog.
- **State:** tree on `main` at `20b05ac` plus the doc edits above and this entry, **committed and pushed on `main`** on the
  owner's word (docs only, per the convention), together with Codex's spike hand-off
  commit `20b05ac`, which had been local only. **The dev DB holds INVENTED fixture data** — 15 kits across all six
  statuses, 6 orders, 4 retailers, catalog stock, two upgrade applications — seeded
  2026-09-08 through the service layer for the walkthrough; disposable, not the owner's
  collection; the owner reset the dev password themselves. Copies of the mock artboards
  sit in `frontend/node_modules/.cache/plamotrack-drafts/` (ignored; delete freely). The
  dev overlay and both dev servers were running from this session. `spike/m61-fastmcp4`
  is untouched, one docs commit behind `main`.
- **Next:** M6.5 PR 1 per §13.6, on a branch off `main`: semantic tokens in
  `frontend/src/index.css` through Tailwind v4 `@theme`, `[data-theme]` with an inline
  pre-paint script, `@fontsource-variable/inter`, `lucide-react`, the new sidebar; then
  sweep every `zinc-*` / `indigo-*` utility (`ui.tsx`, `Modal`, `StatusBadge`, `Layout`,
  `AuthGate`, the pages and settings sections) onto the tokens. Then PR 2 (URL filter/sort
  + sort/limit on the kit and order list endpoints, REST **and** MCP, registry), PR 3
  (Home, drop dnd-kit), PR 4 (Settings, About, e2e, README screenshots). Filed as
  **#231 → #234** (milestone M6.5), one per PR, in that order — **start with #231 in a fresh session** (owner's call,
  2026-09-09). Brief for it: this entry, design §13.1 / §13.3 / §13.6, and #231 itself;
  the reference artboards are on the owner's private design canvas — ask the owner for
  exported PNGs if exact spacing or colour is in doubt. M6.1's two-PR plan from the spike hand-off is unaffected.
