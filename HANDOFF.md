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

## 2026-09-10 — Claude Code (Fable 5.1) — #231 (M6.5 PR 1/4) built on `feat/231-workbench-tokens-theme-sidebar`: Workbench tokens, per-browser theme, bundled Inter, Lucide, new sidebar, every page swept; committed `eac24e1`, **PR #235 against the integration branch `m6.5-workbench`** — M6.5 lands on `main` in one release (owner's call)

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
- **Next:** the Codex round on #235 → respond per `.agents/testing-and-review.md` → merge it
  into `m6.5-workbench`. Then #232 (URL
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

## 2026-09-08 — Claude Code (Fable 5.1) — #195 held behind the owner's security scan: the four mediums fixed as #221 → **PR #222; Codex round 1 NO-GO (f1, f2 P2; f3 P3) fixed at `6395a5d`; round 2 NO-GO (f4 P3, docs) fixed at `b4d9aa4`; round 3 NO-GO (f5 P3, docs) fixed at `ec171fd`; PR #222 MERGED `94fd2f9`; the gate rerun found #228 → PR #229 MERGED `37ef344`; release branch at `511ea90` (tree `c270127`), **gate GREEN on it, CI green — awaiting the owner's go: merge #220 → tag → release**; release PR #220 waits (rebase + gate rerun after #222 merges)

- **Done:** (1) **#195 run to the edge of the outward steps** (2026-09-07): `release/0.3.0`
  at `ed48038` (tree `92015d9`) → **PR #220** (bump 0.3.0, design §5 flipped to Built,
  operations *Upgrading to 0.3.0*, AGENTS roadmap 6 struck), CI green; the whole release
  gate run on that tree — local packaged stack under Compose project `plamotrack-release`
  (fresh volume; the dev volume was kept), `/api/meta` and MCP `serverInfo` 0.3.0, manifest
  0.3.0/d5e9362140ea, matrix 0 failing, T10 clean; `deployment_gate.py --phase all` + tunnel
  on testhost after a fresh-install reset — GREEN, exit 0, every phase (results comment on
  #220). Notes, #30 and #195 closing comments drafted. (2) **The owner then ran a Codex
  Security scan on `ed48038`**: NO-GO for Internet exposure until four medium availability
  findings are fixed. Filed **#221**; fixed on `fix/scan-0.3.0-availability` → **PR #222**
  (four commits, one per item): item 4 `FailureBudgets` — a ladder per (action, client
  address) with decay + an instance-wide verification bucket (`app/auth/budget.py`,
  `services/auth.py`, `services/oidc.py`, `routers/auth.py`); item 3 `RefusalBudget` on
  the audit recorder + `AUDIT_RETENTION_DAYS` (closes #210); item 1 `RoutePolicy.max_body_bytes`
  + one bounded reader (`app/auth/body.py`) in the pre-routing gate and the three protocol
  guards (+ `BoundedBody` on consent), nginx exact locations generated as a second region
  of `render_ingress.py`, 413 envelope `ingress.body_too_large`, `MAX_FORM_FIELDS`; item 2
  `ClientRecords` on FastMCP's client collection (24 h lifetime until `keep` at issuance —
  a permanent record stays permanent through FastMCP's refresh writes — cap 1024, quota
  20/h/address, `count_live`/`cull_expired` on the store, `cull_if_due` from the registration
  guard and `authorize`, FastMCP's CIMD cache a `BoundedCache`), 503
  `auth.mcp_registrations_full`. Docs: design §5.6 rows + T8 + §5.9 item 11 (the calls),
  operations, AGENTS rule 14, `.env.example`, the CI row in testing-and-review. Verified:
  full backend **2641 passed**; CI Backend/Frontend/Integration green at `4b35c73`
  (Integration = the matrix's new `body_budget_rows`/`origin_flood_rows` through the
  packaged nginx + the new refusal-row count step); 25 `scan-` mutants in the tracked
  harness **all killed**; six behavioural control probes **6 red on main / 6 green** on
  the branch (file kept out of the tree; verbatim in the brief). Four lows filed, not
  blockers: #223 CSV formula syntax, #224 OIDC endpoint validation, #225 MCP untrusted-text
  marking, #226 HSTS. The release notes draft gained a scan section and lost #210.
- **Decisions:** 0.3.0 not 0.2.11 (every caller's contract changed). The seven deliberate
  calls are on PR #222 (the verification bucket can delay the owner by seconds under a
  distributed flood; the suppressed count is written with a later window's first recorded
  refusal; the registration cap is checked before the write, a race overshoots by nginx's
  burst; the constants are constants; nginx's 413 has no `params.limit`; consent GET
  unbounded; a CIMD lookup at the cap is an unknown client). Reviewer: **Codex** (M6
  security work) — brief printed in the 2026-09-08 session chat, scratchpad copy.
- **Round 1 (Codex, GPT-6) — NO-GO, fixed at `6395a5d`:** f1 (P2) the setup token and the OIDC start charged
  the verification bucket for a cheap comparison, and the general bucket alone let a stream of fresh
  addresses hold the owner out → `refuse_throttled(verification=False)` on both cheap paths, and a login
  presenting any session cookie the instance ever stored (rows are never deleted) is verified from a
  reserved bucket of 10/min (`FailureBudgets.known`), falling back to the general one; the
  new-browser-under-flood case is documented as the ingress's boundary (operations 429 paragraph,
  design §5.6/§5.9 item 11). f2 (P2) `/mcp/token` and `/mcp/revoke` materialise CIMD clients through
  `get_client` with no cull reached → the client-collection cull now lives in `ClientRecords.put` on a
  new key (`cull_expired(collection)`). f3 (P3) a disconnect mid-body was replayed as a whole body →
  `read_bounded` raises `Disconnected`, the gate and the three guards answer nothing. Tests for each;
  scan-26…31 added (31/31 killed); full backend **2653**; response posted; coverage record updated.
- **Round 2 (Codex) — NO-GO on f4 (P3, documentation), fixed at `b4d9aa4`:** the runbook promised the
  reserved login path to "the browser you signed in with"; a normal logout clears that cookie. The
  three documents now state the contract as built (a recognised cookie — idled out or host-revoked —
  plus an open ladder and capacity; a logged-out / expired / cleared / restored-past-row browser
  competes, the ingress is the boundary; a shared address shares a ladder); a cookie-jar lifecycle
  test; the flood tests on small buckets (they had put the Backend CI job past its 15-min cap,
  cancelled at `6395a5d` — now 20 with the reason in the workflow); **#227** filed for the device
  capability as a product contract. Round 2 explicitly ran no replays, control or mutants; re-run
  at `b4d9aa4`: 31/31 killed, control 6 red on `c527176` / 6 green, full backend **2654**.
- **Round 3 (Codex) — NO-GO on f5 (P3, documentation), fixed at `ec171fd`:** the runbook said "at most
  thirty passwords a minute in total"; the policy is two additive token buckets (30 + 10, continuous
  refill). The 429 paragraph is rewritten as one contract (ladder → reserved bucket → general bucket,
  capacity + refill, every cookie state, a restore's present-but-unrecognised cookie); budget comments
  matched; an accounting test pins 30 + 10, the 41st refused, both refill rates; lesson filed ("A
  runbook paragraph is one promise"). Rounds 2 and 3 both explicitly ran neither the control nor the
  mutants; author's record at `ec171fd`: 31/31 killed, full backend **2655**, CI green (Backend 12m49s).
- **PR #222 MERGED → `94fd2f9`** (squash, 2026-09-08; #221 and #210 closed) after the owner ran the
  control (6 red) and the mutants (31 killed) himself. `release/0.3.0` rebased onto it → `9f2c52a`
  (tree `36b2749`), PR #220 updated; the design.md conflicts resolved (item 10's note before item
  11; dates to 08/09). **Gate rerun on that tree: local step 4 green; the deployment gate stopped
  in T13** — the runbook's `pg_restore` after `down -v; up -d db --wait` met "the database system
  is shutting down": the socket healthcheck is satisfied by the image's temporary init server
  (`listen_addresses=''`). Filed **#228**, fixed on `fix/db-healthcheck-init-race` → **PR #229**
  (TCP probe in compose and CI's service container, a runbook sentence; verified 3× on a fresh
  volume). The lockout/local/oidc phases were green before the stop (matrices 179 and 182 ok rows).
- **PR #229 MERGED → `37ef344`** (#228 closed) on the owner's word; `release/0.3.0` rebased again →
  **`511ea90`, tree `c270127`**, PR #220 updated, CI green (Backend 12m50s). **Gate run #3 on that tree
  GREEN**: local step 4 green; `--phase all` green through T13 on the fixed healthcheck (local matrix
  177 ok, oidc 181 ok, three restores); the tunnel rows failed only because the workstation's temporary
  IPv6 rotated mid-run — the tunnel phase rerun alone passed (attribution to the current address,
  both spellings held 130 s+, matrix 87 ok, audit row = visitor); the first tunnel rerun crashed on a
  peer reset mid-hold → **#230** filed (harness gap, not a blocker). Results comment on #220; the
  notes draft (scratchpad `release-notes-v0.3.0-alpha.md`) carries the three observed blocks, the
  #221 section, the #228 line, and no longer lists #210.
- **State:** `main` = `37ef344` + these entries. PR #220 open at `511ea90`; **no tag exists**. testhost
  left in mode R after the tunnel phase's restore (OIDC mode, Keycloak up). Gate state dir
  `~/.plamotrack-gate/testhost…/` holds run #3 (`…release-run-1`, `…release-run-2-stopped` beside it). **Recommendation given (2026-09-08): stop the Codex rounds** — the NO-GOs
  are the reviewer's own unrun verification, not defects — and merge once the owner has run the two
  mechanical checks himself (the control file in a `c527176` worktree → 6 red; `mutation_test.py -k
  scan-` → 31 killed). A round-4 brief exists (scratchpad `brief-222-r4.md`) if a reviewer's name is
  wanted on those two items; GLM would do for that. PR #220
  open at `ed48038`, **stale once #222 merges** (rebase; the only expected conflict is
  design.md's "Last revised" line — keep 08/09; §5.9 item 11 and the §5.6 rows are #222's).
  No tag exists. testhost left in the gate's end state (OIDC mode, Keycloak up); a rerun
  needs the fresh-install reset (`down -v`, `.env` from `.env.example`, `git archive` the
  tree) — the memory file `plamotrack-194-deployment-gate-setup` has the exact steps. Gate
  state dir `~/.plamotrack-gate/testhost…/` (the #194 run's moved aside). Dev overlay up;
  tree clean; LXC untouched.
- **Next:** owner merges #220 (squash) → verify the merge commit's tree is `c270127` → tag `v0.3.0-alpha — the instance has an owner` on the
  merge commit → push tag → `gh release create --prerelease --verify-tag` with the notes
  (scratchpad `release-notes-v0.3.0-alpha.md`, the gate block replaced by the rerun's) →
  post the #30/#195 comments, close both, close the M6 milestone. Then the LXC upgrade.
