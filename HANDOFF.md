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

## 2026-09-11 — Claude Code (Fable 5.1) — #243 built on `feat/243-fastmcp4-bump` (nine commits, head `1715d66`), the FastMCP 4.0.3 / MCP SDK 2.2.0 bump with the era probes; **PR #246 open against `m6.1-fastmcp4`** (pushed on the owner's word), Codex brief printed; next: the Codex round, then #242 stacked

- **Done:** #243 whole, rebuilt from the spike's commits against `main`'s lock (httpx already runtime, #241).
  `d31f9f9` the lock (fastmcp 4.0.3, mcp 2.2.0, httpx2/httpcore2 2.12.0, mcp-types, truststore; httpx-sse
  gone; nothing else moves). `93a6144` the mechanical adaptations (legacy 406 probe pins its session,
  `input_schema`, RFC 9207 `iss` on the denial, the digest-suffixed consent cookie) and the **five
  CIMD-row cases `xfail(strict=True)` naming #242**. `0d76aac` the seam: `_create_upstream_oauth_client`
  returns FastMCP's own client always and re-homes its `_client` onto `upstream_transport` (now httpx2)
  under a type guard; `FakeIdp.upstream_handler` is the httpx2 twin; a control asserts the class with and
  without the transport and reads Basic off the exchange. `1021aab` the binding's 405 writes the SDK's
  null id (`exclude_unset`), the literal body test unchanged. `867ccef` `discovery_metadata` sets
  `authorization_response_iss_parameter_supported`; the `private_key_jwt` DCR refusal (SDK 2's 400
  before `register_client`) accepted — parametrize row dropped, a refusal test and an `iss`-on-the-code-
  redirect test added. `98b1c78` `tests/test_mcp_eras.py`, 16 cases, the four brief-contract assertions
  corrected to the mount's RFC 6750 challenge (no envelope), the no-routing-headers case pinned to the
  SDK's `-32020`. `a4347e4` docs (design §7.1 both eras + the §11 marker still Planned; AGENTS rule 13's
  mount-refusal and DCR sentences; design §5.5 row; operations "first protected request"; the release
  step checks both eras; the spike report → `.agents/spikes/241/findings.md` + README; `.agents/README`).
  `75bdbdb` four `243-` mutants. `1715d66` **CI's real-client row rewritten**: SDK 2 folds the anonymous
  401 into `MCPError(-32603, "Server returned an error response")` — the old `"401" in str(exc)` would
  have failed the Integration job with the server refusing correctly; the row now asserts the SDK's
  refusal plus the two wire requests (modern probe, handshake) each 401 `Bearer`.
- **Verified:** targeted sets green before the full run (211 + 5 xfailed; the two OAuth suites 455);
  full backend suite **2713 passed, 5 xfailed (the #242 five), 0 failed, 17m21s**; ruff clean; harness `-k 243-` **4/4 killed**; negative control (era probes
  in a worktree of `dd183db`, 3.4.5, own venv) **10 red / 6 green**. Packaged stack under Compose project
  `plamotrack-243` from this tree: migrate exit 0, `ingress_matrix.py` **187 ok / 0 failing**, real
  4.0.3 clients through nginx on both spellings (`auto` → `2026-07-28`, `mode="legacy"` → `2025-11-25`,
  31 tools, `get_meta`, `server_info.version` 0.4.0 in both eras), an unmodified 3.4.5 client the same
  and refused with its 401 anonymously, CI's step extracted from the workflow file and run verbatim.
- **Decisions (mine, for the owner to ratify on the PR):** strict xfail for #242's five rather than
  delete/red; the binding mirrors the null id rather than pin both (the spike's edit would have hidden
  the drift); the seam reaches FastMCP's `_client` under a guard rather than patching `httpx2.AsyncClient`
  module-wide; the four probes corrected, not the server; the report at `.agents/spikes/241/`; the CI
  row proves the 401 on the wire beside the client. All seven are in the PR body's "Deliberate calls".
- **State:** `feat/243-fastmcp4-bump` = `1715d66`, pushed; **PR #246** open against `m6.1-fastmcp4`
  (`dd183db`, = `main` less the hand-offs), body in the review-brief shape, CI triggered. `main` holds
  this entry (local unless pushed). The Codex brief printed in the 2026-09-11 session chat (scratchpad
  `243-review-brief.md`). The packaged project `plamotrack-243` torn down (`down -v`); the control
  worktree removed. Dev overlay up. Checkout parked on `main` for the review window.
- **Next:** the owner pastes the brief into a fresh Codex chat; answer the round per
  `.agents/testing-and-review.md` (reproduce at `1715d66` first; attribution line; coverage record).
  Merge on the owner's word (squash, as #245). Then #242 stacked on this branch (remove the five strict
  xfails when the contract is restated), #244, the release PR (merge commit, gated, v0.5.0-alpha suggested).

## 2026-09-11 — Claude Code (Fable 5.1) — #241 built on `fix/241-upstream-revocation` → PR #245, one Codex Astra round (NO-GO on a cancelled Backend job only, no findings), **MERGED → `459c8b3`**; integration branch **`m6.1-fastmcp4` cut**; next #243

- **Done:** #241 whole, five commits. `9e99c31` httpx to the runtime deps (lock: only the
  project's own entry moves). `96cbe69` `_revoke_upstream` delegates to `OidcProvider.revoke_token`
  (the app's own httpx, HTTP Basic as the code exchange), skips only when no discovery document
  is held, and has no catch-all — a defect is the binding's 500 after the local end; the fake
  records `Authorization` and gains `revoke_error`; six tests (the control with a
  FastMCP-4-shaped upstream client lacking `revoke_token`, the access-only hint, the
  defect → 500 with the grant already dead, refused / no endpoint, a fresh process with the
  provider down) and the witness asserts Basic; design §5.6's row; lesson "The fake stood in
  for the very object under test". `815b7dd` six `241-` mutants in the tracked harness.
  `687c9ed` the prose (module docstring, two test comments, design §5.9) follows the code.
  **Verified:** full backend **2700 passed** at `815b7dd` (the head differs by prose in three
  files); negative control on unfixed `main` **3 red / 26 green** — both control cases on
  `[] == [upstream refresh]`, the defect case on `200 == 500`; mutants **6/6 killed**; ruff
  clean. The PR body carries the four deliberate calls, both tables and the coverage record.
- **The round (Codex, GPT-6 Astra):** NO-GO solely because the Backend CI job was cancelled at
  its 20-minute cap at 66 % — no P1–P3; it re-measured the control (3/26), the six mutants
  (6/6, failing assertions captured), the full suite (2700 at `687c9ed`), retained all four
  deliberate calls, added 34 supplementary cases, and corrected one count (five new test
  functions / seven cases, the table's last row the existing witness — PR body amended). The
  cancellation profiled against the base's Backend log: **uniformly** 3.4× slower (median 17 s vs
  5 s per progress line, same slow regions, pre-test steps normal) — a slow runner, not a stalled
  test; attempt 2 on the same head green (2700 in 14m37s, job 15m40s). Response posted
  (issuecomment-5624914927); squash-merged on the owner's word, branch deleted.
- **Decisions:** the four deliberate calls on PR #245 (a defect is the 500, not a warning;
  share the provider client, no dead public-client branch — OIDC mode requires the secret; one
  proxy guard, the never-held document, none for "no endpoint" which the provider client
  checks; `upstream_transport` stays for exchange and refresh until #243). Reviewer: **Codex
  Astra**, a fresh chat — it reviewed this file's rounds 12–15 on #212; the brief was printed in
  the 2026-09-11 session chat (scratchpad copy `245-review-brief.md`).
- **State:** `main` = `459c8b3` + this entry, pushed; #241 closed by the merge. **`m6.1-fastmcp4`**
  cut from that `main` and pushed — the base for #243, #242 (stacked) and #244; merge `main` into
  it when `main` moves, never rebase (AGENTS → Git conventions). Checkout on `main`, tree clean,
  dev overlay up. Codex's spike branch `spike/m61-fastmcp4` (`bbb58e7`, local) untouched. The LXC: last recorded 0.3.0 with the 0.4.0 upgrade queued (unconfirmed).
  Evidence outside git: the spike's `/private/tmp/plamotrack-m61-fastmcp4-20260908`; this
  session's scratchpad logs for #241 (negative control, mutants, full suite).
- **Next:** **#243** on a branch from `m6.1-fastmcp4`, rebuilt from the spike's commits
  (`0ff1633`…`1c41ae6`: lock regenerated against `main`'s — httpx is already a runtime dep; the
  httpx2 twin replaces the `upstream_transport` authlib injection; the mechanical test fixes; the
  discovery flag; the `private_key_jwt` refusal accepted; the null 405 id; the era probes with the
  four envelope assertions corrected to the challenge contract; the report to `.agents/spikes/241/`).
  Then #242 stacked, #244, the release PR (merge commit, gated, v0.5.0-alpha suggested). If the
  Backend cap bites again at a normal count, that is a CI issue to file, not a branch's.

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
