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

## 2026-09-11 — Claude Code (Fable 5.1) — M6.1 planned and filed: Codex's FastMCP 4 spike verified; **#241** (prep, `main`) → **#243** (bump) + **#242** (CIMD) + **#244** (gate) on integration branch `m6.1-fastmcp4`; the #241 Codex brief printed; the integration-branch rule generalised

- **Done:** (1) 2026-09-08 — the brief for the FastMCP 4 compatibility spike printed; Codex ran it
  (its entry is in `.agents/handoff/2026-09.md`; branch `spike/m61-fastmcp4` at `bbb58e7`, report
  `.agents/spikes/2026-09-m61-fastmcp4.md` **on that branch only**, evidence under
  `/private/tmp/plamotrack-m61-fastmcp4-20260908`). Its three headline findings re-verified against
  FastMCP 4.0.3's source: `_revoke_upstream` calls `revoke_token` on FastMCP's upstream client, which
  4.x's httpx2 client lacks — the `except Exception` hides the AttributeError and the provider is never
  asked, while the fixture's `upstream_transport` injection builds authlib's old client, so the suite is
  green for the wrong reason; CIMD clients resolve through a bounded cache and are no longer persisted
  (`OAuthProxy.get_client`), so five `test_mcp_oauth_registrations.py` cases are obsolete; SDK 2's
  registration handler refuses `private_key_jwt` before `register_client` runs. Codex's raw log at the
  spike head: **2661 passed / 10 failed** — the five CIMD cases, one registration case, and four
  era-probe assertions the brief got wrong (a failed bearer on `/mcp/` is the RFC 6750 challenge
  header, not REST's `auth.bearer_invalid` envelope; rule 13's "on every route" wording misled).
  Packaged local matrix 186/0; real 4.x (auto and forced-legacy) and 3.4.5 clients through nginx on
  both spellings. (2) 2026-09-11, on the owner's "lets do it": **#241** (prep PR on 3.x — httpx as a
  runtime dep, own the RFC 7009 upstream revocation POST behind an injectable transport, narrow the
  catch-all, a control whose factory lacks `revoke_token`), **#242** (CIMD contract restated DCR-only,
  an unreachable-document probe), **#243** (the atomic bump: lock, httpx2 test twin, mechanical fixes,
  `authorization_response_iss_parameter_supported`, `private_key_jwt` refusal accepted, null 405 id,
  era probes corrected), **#244** (gate both eras with real clients; the Built flip lives there) filed
  under M6.1 beside #56, each with the attribution line. The Codex brief for #241 printed in chat
  (scratchpad copy). (3) Docs: AGENTS "Git conventions" — the M6.5 paragraph generalised into the
  integration-branch rule with M6.5 and M6.1 as instances; design §7.1 gained a sequencing paragraph;
  #243 and #244 name their base branch.
- **Decisions (owner, 2026-09-11):** two-PR shape — prep on 3.x first, then one atomic bump; CIMD
  follows FastMCP 4's model (lifetime/cap/quota now DCR-only); the `private_key_jwt` refusal is the
  contract; the discovery flag is added; the binding's 405 mirrors the SDK's null id; the four red
  probes are fixed, not the app. **Integration branch `m6.1-fastmcp4`** cut from `main` after #241
  merges; #243 → branch, #242 stacked on it, #244 → branch; release PR with a merge commit, gated,
  suggested tag v0.5.0-alpha (the number is the owner's call). #241 alone goes straight to `main`.
- **State:** `main` = `3eeca81` + this entry; tag `v0.4.0-alpha` = `64d23de`. `spike/m61-fastmcp4`
  (`bbb58e7`, local, unpushed) merges cleanly onto `main` — #243 is rebuilt from its commits with the
  lock regenerated against `main`'s; the report moves to `.agents/spikes/241/` in that PR.
  `m6.5-workbench` still exists (`64d23de^2`). Tree clean, checkout on `main`, dev overlay up.
  **The LXC** was last recorded on 0.3.0 with the 0.4.0 upgrade queued (liveness carries no version;
  unconfirmed from here). The evidence dir under `/private/tmp` does not survive a reboot. Nothing
  pushed this session.
- **Next:** **#241** — the owner pastes the brief into Codex (branch `fix/241-upstream-revocation`
  from `3eeca81`, PR to `main`, a fresh Codex chat reviews). Then cut `m6.1-fastmcp4` and start #243
  from the spike commits. The LXC upgrade to 0.4.0 whenever; #238 and the lows (#223–#227, #230)
  unaffected.

## 2026-09-10 — Claude Code (Fable 5.1) — **v0.4.0-alpha RELEASED** (M6.5 complete): release PR #240 merged with a merge commit `64d23de` (tree `509f832`, the gated tree), tag pushed, prerelease published, #231–#234 + #122 closed, milestone M6.5 closed; next the LXC upgrade, then M6.1

- **Done:** #239 (#234) squash-merged → `2fa0219` on `m6.5-workbench` (no review, owner's call);
  the version bumped to 0.4.0 in the three files (`900e2ea`, with an *Upgrading to 0.4.0* note in
  `docs/operations.md`); **release PR #240** (`m6.5-workbench` → `main`, `Closes` the five)
  merged with a **merge commit `64d23de`** on the owner's "do the lot"; annotated tag
  `v0.4.0-alpha — the Workbench interface` on it, pushed; `gh release create --prerelease
  --verify-tag` with the notes — https://github.com/DeusMaximus/plamotrack/releases/tag/v0.4.0-alpha ;
  **milestone M6.5 closed** (5/0). The notes lead with the upgrade path (nothing to migrate,
  pull + build), the client-visible changes (`stage` on order rows, `GET /summary` +
  `get_summary`, `sort`/`limit`, `/board` → `/`, the Orders `?status=` vocabulary, `board.*` →
  `home.*`), the features, the three observed gate blocks, the known limitations (no phone
  layout, #238, one worker, #223–#227, #230, M6.1).
- **The gate, on tree `509f832`:** local packaged stack under Compose project
  `plamotrack-release` (fresh volume; the dev `.env` gained `ALLOWED_HOSTS` for the run and
  was restored) — migrate `Exited (0)`, matrix 0 failing, refusal rows 10, `/api/meta` and the
  MCP `serverInfo` 0.4.0, archive manifest 0.4.0 / `d5e9362140ea`, T10 clean, `down -v`.
  `deployment_gate.py --phase all` on testhost after a fresh-install reset (`down -v`, the tree
  **wiped** before `git archive` — a stale `BoardPage.tsx` would have reached the frontend build —
  `.env` regenerated by `host-prepare.sh`) — every phase green (local 179 ok, oidc 182 ok, T13 ×3).
  The **tunnel phase crashed at DNS** (the route `plamotest.gunp.la` had been removed; the owner
  re-added it → `http://10.1.1.129:8080`), then failed twice on the visitor attribution only — the
  Mac's public address changed between the fetch and the check (an IPv6 temporary address
  rotating, then the family flipping between connections) — and passed on the third run with
  IPv4 pinned on both sides (`curl -4` for the visitor; a process-local `sitecustomize.py` on
  `PYTHONPATH` restricting `socket.getaddrinfo` to `AF_INET`; scratchpad only, not committed).
  **Lesson for the next release:** run the tunnel phase IPv4-pinned from the start, or give the
  driver a `--visitor-family` option (#230's neighbour — the crash on an unresolvable name is
  the same harness gap: a failed row, not a traceback).
- **Decisions:** (1) the hand-off commits `main` gained mid-milestone were merged into the
  integration branch before the release PR, so the merge commit's tree is the branch's — a
  tree-hash argument with no caveat this time; (2) the release hand-off is this entry, after the
  tag; (3) `m6.5-workbench` left in place (delete when the owner likes; it is `64d23de^2`).
- **State:** `main` = `64d23de` + this entry; tag `v0.4.0-alpha` = `64d23de`. CI on `main`
  triggered by the merge — check it. testhost left in the gate's end state (mode R, OIDC,
  Keycloak up); gate state dirs under `~/.plamotrack-gate/` (this run's current; the 0.3.0 run's
  aside as `…release-0.3.0-run-3`). Dev overlay up (`plamotrack-db-1`); Vite preview may still
  be running from this session; the `api` preview stopped. **The LXC still runs 0.3.0** — the real
  collection, untouched. Open: #238 (order dialog waiting state), #223–#227, #230.
- **Next:** **the LXC upgrade** — back up (dump + `.env`), `git pull` to `v0.4.0-alpha`,
  `up -d --build --wait`, sign in as before (nothing to claim, no migration); refresh the personal
  Gunpla skill to the deployed version (memory: it lags main by design). Then M6.1 (FastMCP 4,
  two PRs pending the owner's plan), #238, the lows.

## 2026-09-10 — Claude Code (Fable 5.1) — #234 (M6.5 PR 4/4) built on `feat/234-settings-about-e2e-readme`: Settings chrome, the plain description on sign-in and About, the last glyph, seven captures, README and design §13 marked built; **PR #239 open against `m6.5-workbench` at `c7965bf`, no review (owner's call) — merge when CI is green, then the release**

- **Done:** the Settings section navigation in the sidebar's row shape (`navRowClass` exported from
  `Layout.tsx`), `SectionHeader` at the bench card's scale, the Access tokens table in the list
  pages' shape (`TABLE_HEAD_ROW_CLASS`, bordered); `layout.description` ("A self-hosted Gunpla and
  plamo collection and build tracker.") replaces `layout.tagline` on the sign-in screen and About;
  the catalog picker's "＋" is a Lucide `Plus` (`display-items.spec.ts`'s locator follows);
  `screenshots.spec.ts` writes `home-light.png` (a light-device context, `data-theme="light"`
  asserted) and `sign-in.png` (an anonymous context — `storageState: { cookies: [], origins: [] }`
  said explicitly, because `browser.newContext()` inside a test starts from the project's `use`
  options and produced a signed-in Home the first time); all seven captures regenerated from the
  seed on a fresh DB. README: "One look, two themes" with the light capture, the sign-in capture
  under Installing, the roadmap row ✅. design §13 header ✅ (10/09/2026, #231–#234), §11 item 11 ✅,
  "Built as" paragraphs in §13.1 (light tokens darkened for 4.5:1, `--faint` on the chip, the
  palette guard's arbitrary-value refusal) and §13.3 (the description line, the Settings chrome),
  §13.6's four items ✅ with PRs and merge commits; AGENTS.md roadmap 6.5 struck through.
- **Decisions:** (1) the app's line is plain, the README keeps the joke; (2) the Settings nav reuses
  the sidebar's row class; (3) the tokens table takes the list pages' shape inside its card; (4) two
  new captures only (light Home, sign-in); (5) §13 and the README row read built on the integration
  branch now — `main` serves the 0.3.0 README until the release PR.
- **State:** `feat/234-settings-about-e2e-readme` = `m6.5-workbench` (`03673e5`, i.e. `8bac10a` +
  the hand-off merges) + `c7965bf`, clean, pushed; PR #239 open. Green: unit 568, e2e 65 + 1 skipped serially
  from an empty DB (tables 0 after, DB dropped), lint, build; screenshots spec 2 passed on a fresh
  DB. Backend untouched since `d6c8def`. No harness change (no backend). Dev servers: Vite up, `api`
  preview stopped. PR body drafted in the session scratchpad (`pr-body-234.md`).
- **Next:** merge PR #239 once CI is green (no review — owner's call, the release gate is the
  check). Then **the release**: merge `main`
  into `m6.5-workbench` once more, a packaged-stack run (`docker compose up -d --build --wait`) on
  the integration tree, the release PR onto `main` with a **merge commit** (never a squash), gate
  that commit (`deployment_gate.py --phase all` on testhost per `.agents/testing-and-review.md`),
  bump the three version files to 0.4.0 via the release PR, tag `v0.4.0-alpha`, `gh release create
  --prerelease`, notes (the theme switch, Home, the list-page URLs, `stage` on order rows, the
  Orders `?status=` vocabulary, `/board` → `/`, `board.*` → `home.*`, `GET /summary` + `get_summary`,
  no migration), close #231–#234 and #122 with the merge, close the milestone; **hold the release
  hand-off commit until after the merge** (the 0.3.0 lesson). Open follow-ups: #238 (order dialog
  waiting state), #223–#227, #230.

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
