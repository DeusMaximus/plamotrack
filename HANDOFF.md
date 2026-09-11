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

## 2026-09-11 — Claude Code (Opus 4.8) — #244 built on `feat/244-era-gate` (head `5eb84fa`, clean off `m6.1-fastmcp4` = `c6cd383`): both protocol eras gated with real clients + the #56 description/schema test; PR #250 open, CI green, the remote deployment gate GREEN on testhost; next the Codex round → merge → the release PR

- **Done:** #244 whole (closes #244 + #56), one commit `5eb84fa`.
  - **Modern hold-and-cancel.** The `2026-07-28` mount serves no long-lived stream
    (`subscriptions/listen` is not wired; every tool is short), so the held stream is built
    around an existing `get_meta` call made to wait by `app/mcp_hold_probe.py` — an env-gated
    (`PLAMOTRACK_ENABLE_TEST_HOLD`), off-by-default FastMCP middleware holding a DB connection
    idle-in-transaction under a marker. Adds no tool and no route (registry/enumeration
    untouched); never armed in the shipped image. `json_response=False` makes the SDK commit
    SSE + ping past 15 s with no notification (the owner's insight). `tests/test_mcp_modern_hold.py`
    proves it over a **real uvicorn socket** (ASGITransport buffers, useless for streaming): SSE
    commit, no session id, no-cache, keepalive pings, abort → server-side cancellation → the held
    connection returned; parser bounds; the shipped mount carries no probe. `pg_sleep` was rejected —
    Postgres does not interrupt it on client disconnect, so cleanup was unobservable.
  - **Through the proxy chain:** `ingress_matrix.hold_stream_modern` + the gate's new `modern-hold`
    phase (in `ALL` after `local`) — arms the flag, holds+aborts the modern SSE on both `/mcp`
    spellings, asserts the backend gone in `pg_stat_activity`, disarms.
  - **CI (`ci.yml`):** a 4.0.3 client in `auto` (asserts 2026-07-28) + `mode="legacy"`, and a
    **frozen fastmcp 3.4.5 / mcp 1.29.0** client (both pinned — 3.4.5 alone floats to 1.30.0,
    #248 f1). **#56:** three `test_mcp.py` guards on `create_order`'s description vs the exposed
    input schema (get_meta not a `meta` resource; order currency optional, line required; a line
    without a currency refused).
  - **Docs:** design §7.1 records the coverage + the instrumentation; §5.8 T12 gains the modern
    twin. **The Built flip is NOT here (owner's Q3)** — README/§7.1/§11 stay Planned; §7.1's
    contradictory "flips with #244" sentence corrected to the release PR.
- **Verified:** full suite **2741 passed, 1 xfailed** (fixed the one drift-guard I tripped —
  `test_deployment_hygiene`'s ALL-tuple); ruff clean; **CI #250 all three jobs pass**; #56 negative
  control (mutate the description → pointer test reds; mutate the schema → asymmetry test reds).
  **Remote gate GREEN on testhost** (Q2 Full — a fresh install of this tree behind Caddy DNS-01 +
  a Cloudflare Tunnel): every phase 0 failing incl. `modern-hold` both spellings (cleanup ok),
  holds 75 s/130 s past the 15 s ping and Cloudflare's 125 s cliff, matrices 180/182/87 ok, T13
  three restores, visitor attribution 87.121.75.73, T10 clean. Results on PR #250
  (issuecomment-5629938030). testhost left in the gate end-state (OIDC, mode R); the real LXC untouched.
- **Decisions (owner, this session):** modern hold on an existing call via env-gated instrumentation,
  no new method/subscription (Q1); the remote gate run in this PR (Q2 Full); Built flip deferred to
  the release PR (Q3). Reviewer: **Codex (GPT-6)** — brief printed in chat (scratchpad `pr244-codex-brief.md`).
- **State:** `main` = this entry. PR #250 (`feat/244-era-gate`, `5eb84fa`) open against `m6.1-fastmcp4`
  (= `c6cd383`), CI green, awaiting the Codex round. #244/#56 close on merge. Scratchpad holds the PR
  body, the brief, and both gate results blocks. Local packaged validation stack torn down; dev overlay up.
- **Next:** the Codex round on #250 → merge into `m6.1-fastmcp4` → the **release PR** (merge commit,
  gated, v0.5.0-alpha suggested; hold the hand-off commit until after the merge). The release acceptance
  run does the real-client matrix (Inspector, Claude web, ChatGPT web, Claude Desktop/Code) and a
  conformance run against an unauthenticated build (the runner has no auth flag), then the Built flip.
  #249 is a known-limitation line for the notes. Open: #223–#227, #230, #238.

## 2026-09-11 — Claude Code (Fable 5.1) — #242 built on `feat/242-cimd-dcr-only` (four commits, head `a323b52`, from `m6.1-fastmcp4` = `c1949a4`): the client-record contract restated DCR-only, the five strict xfails replaced, the 0.4.0-row transition and the document outage probed; PR #248 → one Codex round (GO + 2×P3, answered at `a323b52`, #249 filed) → **MERGED into `m6.1-fastmcp4` as `c6cd383`** (squash); next #244

- **Done:** #242 whole. `e0b5f24` the suite and the proxy: `tests/test_mcp_oauth_registrations.py`
  12 → 17 functions / 20 cases — a CIMD client stored nowhere before or after its link, the
  adapter's permanent-stays-permanent rule driven over the record's three states, a CIMD client
  resolving and linking at the registrations' cap, a lookup from `/mcp/token` or `/mcp/revoke`
  materialising no record (`401 invalid_grant` / `200`, the collection empty), the cull at
  creation rolling expired rows over on its one caller (the registration), FastMCP 4's own
  cache bound looser than ours with its store path writing through ours; **the transition** —
  a real 3.4.5 row (captured in a throwaway 3.4.5 venv, `ProxyDCRClient.model_dump(mode="json")`,
  pasted as a literal) in both lifetimes is the fallback while the document is unreachable
  (resolves, links), deleted at the first successful fetch, then an unreachable document leaves
  the client unknown; an expired row backs nothing and waits for the cull; **the outage** — the
  document's own cache policy decides a brief outage's cost in a running process (kept an hour
  by default → 200; `no-store` → 401), and after a restart an unreachable document makes the
  client's own refresh and revocation `401 invalid_client` (provider asked nothing, grant
  standing, no revocation row) while the access token works and the transparent refresh reaches
  the provider, and the same refresh token and revocation succeed once the host answers (the real
  `CIMDFetcher.fetch` in front of a faked `ssrf_safe_fetch_response`). The proxy: `ClientRecords`'
  docstring, the `CIMD_CACHE_ENTRIES` note, the writer inventory and the cull comment restated;
  the dead `except ClientRecordsFull` in `get_client` removed (no lookup writes now). `71abf65`
  the harness: scan-29 re-pointed at the registration rollover; `242-1` (a later write re-arms a
  permanent record), `242-2` (our cache bound raised above FastMCP's). `dbe5ed1` the docs: AGENTS
  rule 14's client-records paragraph, design §5.6's row, a dated amendment closing §5.9 item 11,
  operations' MCP-client paragraph (the transition sentence lives there; the "Upgrading to
  0.5.0" section is the release PR's).
- **Verified:** the file green here (20); **negative control** in a worktree of `dd183db`
  (3.4.5, own venv) **11 red / 9 green** — every red on the row assertion, the fallback's 200, or
  3.x's missing `MAX_CACHE_SIZE`; the greens the DCR-side behaviours both versions share (the PR
  body has the table); harness `-k 242-` **2/2** and `-k scan-29` **1/1** killed (643 cases / 57
  files re-derived); full backend suite **2725 passed, 0 failed, 0 xfailed, 20m42s** (the five strict xfails gone); ruff clean. Measured, not assumed: `401
  invalid_grant` for a never-issued refresh token is FastMCP's `TokenHandler` (MCP spec's 401
  over RFC 6749's 400), already pinned four times in `test_mcp_oauth.py`; FastMCP 4's proxy calls
  `get_client` nowhere but the CIMD manager, so the transparent refresh never resolves the client;
  `application_type` is the one field 4.0.3 added to `ProxyDCRClient`, with a default.
- **Decisions (mine, for the owner to ratify on the PR — eight "Deliberate calls" in the body):**
  the dead except removed rather than kept; the adapter rule kept and tested at the seam though
  no FastMCP writer drives it; our 256 bound kept beside FastMCP's 1000; the outage contract
  recorded, not changed (no database copy of the document); the 0.4.0 row a captured literal;
  the SDK's 401 pinned; scan-29 re-pointed not retired; the upgrade note left to the release.
- **The round (Codex, GPT-6):** GO, two P3s, one prose slip — all reproduced and answered at
  `a323b52`. f1: the captured 0.4.0 row carried `issuer`, which the shipped lock's MCP 1.29.0 model
  lacks — my throwaway `pip install fastmcp==3.4.5` had resolved MCP 1.30.0; recaptured in a
  `dd183db` worktree under the real lock through the real old proxy and the encryption wrapper
  (diff: `issuer` alone), the comment records the versions, and a new case pins the literal's key
  set against the current model (adds exactly `application_type` + `issuer`; the excluded
  `allow_unregistered_redirect_uris` named). f2: FastMCP's fetcher reads neither `Age` nor `Date`
  (RFC 9111 §4.2 — a response aged upstream keeps a full lifetime from receipt), inherited from
  3.4.5; **#249 filed**, the operations paragraph and the design §5.9 amendment qualified ("from
  receipt"), the case a **strict xfail naming #249**. Prose: seven unchanged cases, not nine; call
  6's rationale qualified (the MCP 401 is for access-token usage; the token-endpoint 401 is the
  SDK's reading). Codex re-measured everything (11/9, 3/3, 643/57, CI 2725) and added 34
  supplementary cases, listed in the PR's coverage record with its "left unexamined" list as open
  rows. Response posted (issuecomment-5628824763).
- **State:** **`m6.1-fastmcp4` = `c6cd383`** (PR #248 squash-merged on the owner's word after CI green on
  `a323b52`: Backend 13m59s, Integration, Frontend; the feature branch deleted). #242 and #243 stay
  open until the release PR lands the branch on `main`. `main` = this entry. Checkout on `main`,
  tree clean, dev overlay up. The control worktree is gone; the scratchpad holds the PR body, the
  brief, the response and the capture (`row_0_4_0_captured.json`).
- **Next:** **#244** on a branch from `m6.1-fastmcp4` (both eras gated with real clients — Claude web
  and ChatGPT web through a real document fetch belong there — the private-CA/TLS path, the CI legacy
  + frozen-3.x rows, the Built flip; #249's `Age` limitation is a known-limitation line for the notes,
  not a blocker), then the release PR (merge commit, gated, v0.5.0-alpha suggested; hold the hand-off
  until after the merge). Merge `main` into the integration branch first if `main` has moved. Then **#244** (both eras gated with real clients — Claude web and ChatGPT web
  through a real document fetch belong there — the private-CA/TLS path, the CI legacy + frozen-3.x
  rows, the Built flip), then the release PR (merge commit, gated, v0.5.0-alpha suggested; hold
  the hand-off until after).

## 2026-09-11 — Claude Code (Fable 5.1) — #243 built on `feat/243-fastmcp4-bump` (ten commits, head `4d6f6c7`), the FastMCP 4.0.3 / MCP SDK 2.2.0 bump with the era probes; PR #246 → one Codex round (GO, no findings, two claims corrected) → **MERGED into `m6.1-fastmcp4` as `c1949a4`** (squash); next #242 stacked on the integration branch

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
- **The round (Codex, GPT-6):** GO, no P1–P3; every number re-measured and matching (control 10/6
  with the per-case reasons, suite 2713/5/0, 4/4 mutants on the named assertions, the five strict
  xfails run with the marks off — each red on the row assertion, CI green at `1715d66`); 26
  supplementary cases (the two 401 writers per era and mode, the 75-entry route snapshot, the
  metadata diff, Host/Origin under modern requests in both modes, `application_type`). Two claims
  corrected at `4d6f6c7`: the TLS scope (exchange, both refreshes and a fetched client-assertion
  JWKS move onto httpx2/truststore beside CIMD — not confined to CIMD, not proved inert; #244 measures
  a private CA) and CI's fixture (now the SDK's real fallback: `initialize` at 2025-11-25, id 2);
  the bare `Bearer` named as local mode's. Response posted (issuecomment-5627478871). The owner's
  note: Codex spent heavily on a control-tracing pass — that is the brief's first job, and its output
  is where the corrections came from; not a distraction on this round.
- **State:** `m6.1-fastmcp4` = `c1949a4` (PR #246 squash-merged on the owner's word, branch deleted);
  #243 stays open until the release PR lands the branch on `main`. `main` = the hand-offs (pushed).
  Packaged project torn down; control worktree removed; dev overlay up; checkout on `main`.
- **Next:** **#242** on a branch from `m6.1-fastmcp4` (restate the CIMD contract DCR-only, replace the
  five strict xfails, the unreachable-document probe, the 3.x-state transition); then #244 (both eras
  gated with real clients, the private-CA/TLS path, the CI legacy + frozen-3.x rows, the Built flip);
  then the release PR (merge commit, gated, v0.5.0-alpha suggested; hold the hand-off until after).

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

