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
- **State:** branch = `m6.5-workbench` + `c4cdcc3`, pushed; PR #236. Green: `npm run lint`, `npm test`
  (537), `npm run build`, the e2e serially on an empty DB (51 + 1 skipped), ruff; the full backend
  suite was in flight at hand-off time (the touched suites green) — the PR body gets its count.
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

## 2026-09-08 — Codex (GPT-6) — M6.1 FastMCP 4 compatibility spike completed locally

- **Done:** Fable's attached brief on `spike/m61-fastmcp4`, forked from `main` at
  `925c56d`. Report: `.agents/spikes/2026-09-m61-fastmcp4.md` **on that branch**.
  Commits `0ff1633` (FastMCP 4.0.3 / SDK 2.2.0 lock), `0fc80ca` (httpx must be a
  runtime dependency), `43e0d82` (mechanical test adaptations), `1c41ae6` (16 era
  probes), `bbb58e7` (report). No PR, push, GitHub comment or deployment.
- **Findings:** the production FastMCP 4 upstream OAuth client lacks `revoke_token`:
  exchange/refresh and local revocation work, but provider revocation is never sent;
  the old httpx test factory masks it. Custom discovery omits the issuer-response
  flag. CIMD clients now use the bounded memory cache rather than persistent client
  rows, invalidating five lifecycle assertions; a DCR request for private_key_jwt
  is refused before our public-client canonicalization. No runtime app/ingress code
  was edited. Modern and legacy tools work; issuer identity stays byte-identical.
- **State:** baseline **2655 passed**; unchanged upgraded suite **2644 passed / 11
  failed**. Final full suite at `1c41ae6`: **2661 passed / 10 failed**. Same era file
  on untouched 3.4.5: **11 red / 5 green**; on 4.0.3: **4 red / 12 green**. Four reds are the
  brief's pre-existing envelope mismatch (empty anonymous challenge; invalid_token
  rather than REST auth.bearer_invalid), intentionally retained for the decision.
  Packaged local matrix **186 passed / 0 failed**; real 4.x auto/legacy and frozen
  3.x clients work on both `/mcp` spellings. No optional long hold, packaged OIDC,
  remote gate or browser-client/conformance run. Ruff and frontend build pass.
- **Cleanup:** temporary main worktree removed; isolated Compose stack and its own
  volume removed; normal dev DB overlay healthy. Unrelated Keycloak left alone.
  Evidence logs/scripts are outside git at
  `/private/tmp/plamotrack-m61-fastmcp4-20260908`. Final checkout is the spike;
  `main` gains only this handoff and verbatim rotation, no lock or code changes.
- **Next:** preparation PR for independent HTTP/revocation coupling, then an atomic
  bump plus OAuth/era compatibility PR. Proposed M6.1 issues and acceptance matrix
  are in the report, not filed. Do not call this branch a finished migration.
  v0.3.0-alpha is the existing release; the prior handoff's LXC upgrade and open
  #223–#227/#230 follow-ups were not investigated or changed by this spike.

## 2026-09-08 — Claude Code (Fable 5.1) — **v0.3.0-alpha RELEASED** (M6 complete): PR #220 → `c46b652`, tag pushed, prerelease published, #30 + #195 closed, milestone M6 closed; next the LXC upgrade

- **Done:** the whole of #195's tail on the owner's word ("do the lot"): **PR #220 squash-merged →
  `c46b652`** (closes #195); annotated tag `v0.3.0-alpha — the instance has an owner` on it,
  pushed; `gh release create --prerelease --verify-tag` with the notes —
  https://github.com/DeusMaximus/plamotrack/releases/tag/v0.3.0-alpha ; #30 closed with the
  criterion-by-criterion evidence comment; #195 closed with the record; **milestone M6 closed**
  (20 closed, 0 open). The notes lead with the upgrade path (unclaimed on upgrade, back up,
  the setup token, a PAT for every MCP client), then §5.5's client-visible changes, the
  features, the scan's four bounds (#221) and the healthcheck fix (#228), the four
  migrations and what each downgrade discards, the three observed gate blocks, the known
  limitations (#206, #214's residual, #227's boundary, one worker, mode P, `PUBLIC_BASE_URL`,
  M6.1). Earlier today: #222 merged `94fd2f9` (the scan's mediums, three Codex rounds); #229
  merged `37ef344` (the db healthcheck over TCP, found by the gate's restore phase); the release
  branch rebased twice; the gate rerun green on the final tree `c270127`.
- **Decisions:** (1) **The tagged tree differs from the gated tree by `HANDOFF.md` alone** — the
  hand-off I committed on `main` between the rebase and the merge; no image builds from it
  (`backend/` and `frontend/` are the build contexts), so every byte the stack runs is the
  gated byte; stated in the notes' gate paragraph. **Lesson for the next release: hold the
  hand-off commit until after the release PR merges, or gate the merge commit** — a tree hash
  argument should not need a caveat. (2) The tunnel phase was rerun alone after the
  workstation's temporary IPv6 rotated mid-run (nginx attributed correctly, to the new
  address); the first rerun died on a Cloudflare reset mid-hold → **#230** (harness gap: a
  peer reset should be a failed row, not a crash; not a blocker). (3) #227 filed as the
  product question (a device capability surviving a normal logout) rather than folded in.
- **State:** `main` = `c46b652` + this entry; tag `v0.3.0-alpha` = `c46b652`. CI on `main`
  triggered by the merge — check it. Branches `fix/scan-0.3.0-availability`,
  `fix/db-healthcheck-init-race`, `release/0.3.0` deleted (remote). testhost left in mode R
  (OIDC mode, Keycloak up); gate state dirs under `~/.plamotrack-gate/` (run #3 current, two
  older beside it). Dev overlay up; tree clean. **The LXC still runs 0.2.10 — the real
  collection; it has not been touched.** Open from the scan: #223–#226 (lows), #227, #230.
- **Next:** **the LXC upgrade** — back up first (dump + `.env`), set `ALLOWED_HOSTS` if not
  already, `git pull` to `v0.3.0-alpha`, `up -d --build --wait`, claim with the setup token
  from `docker compose logs api`, mint PATs and relink every MCP client, refresh the personal
  Gunpla skill to the deployed version (memory: it deliberately lags main). Then M6.1 /
  M6.5 per the roadmap; the lows #223–#226 whenever.
