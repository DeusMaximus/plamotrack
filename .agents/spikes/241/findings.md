# FastMCP 3.4.5 → 4.0.3: M6.1 compatibility spike

FastMCP 4 supplies the required modern/legacy transport without a tool or service rewrite. A dependency-only upgrade is not ready to ship: the packaged image initially failed to import, the production OAuth client loses upstream revocation, and CIMD storage changes invalidate part of plamotrack's client-lifecycle policy.

Base: `925c56daaa800dbfe6d12d22be8368c0abb4ffe8`, verified equal to local and remote `main` at the start. Branch: `spike/m61-fastmcp4`. Final code/test head: `1c41ae6db19d260f029bd465cb9baeb9e4ea00b0`. Python 3.14.2 for both final dependency-generation comparisons. This is a local spike, with no PR, push, GitHub comment, or deployment to the real instance.

## 1. Lock diff

`fastmcp>=4.0` plus `uv lock --upgrade-package fastmcp && uv sync` resolved without conflicts. The lock contains 94 packages, previously 90.

| Dependency | Before | After |
|---|---|---|
| fastmcp / fastmcp-slim | 3.4.5 | 4.0.3 |
| mcp | 1.29.0 | 2.2.0 |
| uncalled-for | 0.3.2 | 0.4.0 |
| httpx2 / httpcore2 | absent | 2.12.0 |
| httpx2-jsfetch | absent | 1.0, conditional lock entry |
| mcp-types | absent | 2.2.0 |
| truststore | absent | 0.10.4 |
| httpx-sse | 0.4.3 | removed |

FastAPI 0.141.1, Starlette 1.4.0, Pydantic 2.13.4, Authlib 1.7.2 and httpx 0.28.1 did not change. `uncalled-for` provides async dependency injection; 0.4 adds argument-bound dependencies. No direct application use of that API was found, and no measured failure points to its bump. FastMCP's release notes record the integration. [FastMCP 4.0.0 release](https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.0)

Local commits:

- `0ff1633`: dependency resolution.
- `0fc80ca`: promote existing `httpx>=0.27` from the dev group to runtime dependencies. The browser OIDC code and the module containing the test seam still import it; FastMCP 4 no longer supplies it transitively.
- `43e0d82`: five failing assertions adapted to confirmed SDK behavior, plus the camelCase warning fixed.
- `1c41ae6`: the requested 16 era probes, including four deliberately red assertions exposing mismatches between the brief and the existing MCP refusal contract.

## 2. Audit-prompt findings

Read the guide and its copyable prompt verbatim, then applied every search category to the requested application, tests, ingress matrix, deployment gate and mutation harness: 131 Python files at the baseline. The import inventory records 47 SDK/FastMCP submodule import sites. The harness was searched, not executed. [Upgrade guide](https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3)

| Actual hit | Change or disposition |
|---|---|
| [test_int4_bounds.py:118](../../../backend/tests/test_int4_bounds.py:118): `tool.inputSchema` | Guide replacement: `tool.input_schema`. Applied in `43e0d82`. Raw JSON keys remain camelCase. |
| [mcp_oauth.py:1884](../../../backend/app/auth/mcp_oauth.py:1884): upstream client factory; test transport injected at [test_mcp_oauth.py:141](../../../backend/tests/test_mcp_oauth.py:141) | The guide requires httpx2 objects at FastMCP HTTP seams. The injected branch still constructs Authlib's old-httpx OAuth client, bypassing FastMCP 4's production factory. A transport twin alone must not retain that bypass. |
| [mcp_oauth.py:1789](../../../backend/app/auth/mcp_oauth.py:1789): proxy constructed with `base_url`, no distinct issuer | Both token kinds and discovery retain the same issuer; measured below. |
| Legacy initialize/session fixtures in the named tests and harnesses | Valid legacy coverage, not obsolete wholesale. Pin the era where the test depends on it; add modern coverage separately. |

No incompatible environment pin, removed import/method/keyword, positional `McpError(ErrorData(...))`, bare-path `Client`, task use, `ctx.elicit`, sampling, roots, `on_initialize`, cross-call `ctx.set_state`, or assumption in an `on_message` hook was found. The application hooks only `on_call_tool`. Its own browser OIDC httpx client and exception handling are separate and remain appropriate.

`uv run python -c "import app.main"` passed in the upgraded development environment. All imported internal/private names still resolve, including `_hash_token` and `_matches_registered_redirect_uri`; that is an observation at 4.0.3, not a compatibility guarantee. No bucket-A rewrite was needed. The guide does not specify replacements for all custom OAuth internals below; those are marked unconfirmed rather than invented.

## 3. Failure table

The unchanged existing suite produced **11 failures / 2,644 passes**. Each failure is assigned one bucket. C denotes a framework/SDK behavior change; where the upgrade guide supplies no replacement, that limitation is explicit. These are not automatically FastMCP defects. No standalone FastMCP defect was established, so bucket D is empty.

| Cases | Bucket | Location | Cause | Minimal fix or no fix | Commit |
|---|---|---|---|---|---|
| `test_the_mcp_transport_carries_no_store_over_the_sdk_header`, both scope-copy settings (2) | B | [test_authorization.py:467](../../../backend/tests/test_authorization.py:467) | SDK 2 treats implicit `Accept: */*` as accepting SSE, so the bare GET reaches missing-session validation and returns 400 instead of 406. An absent version header still selects legacy; this is not automatic modern routing. | Use the initialized legacy session, explicit 2025 protocol header and JSON-only Accept. Header-profile assertions still run. | `43e0d82` |
| `test_the_owner_can_deny_at_the_consent_page` (1) | C | [test_mcp_oauth.py:595](../../../backend/tests/test_mcp_oauth.py:595) | Redirect now adds RFC 9207 `iss`; exact query comparison rejected it. | Assert the canonical issuer in the expected query. | `43e0d82` |
| `test_every_transaction_and_credential_response_is_no_store_and_discovery_is_not` (1) | C | [test_mcp_oauth.py:1232](../../../backend/tests/test_mcp_oauth.py:1232) | Consent-state cookie now has a per-token digest suffix; fixed-name assertion fails. | Match the new cookie prefix; retain all subsequent no-store, binding-cookie, exchange and refusal assertions. Guide replacement unconfirmed; installed consent code and the [upstream change](https://github.com/PrefectHQ/fastmcp/pull/4818) confirm the new shape. | `43e0d82` |
| `test_every_dynamic_registration_is_a_public_client[private_key_jwt]` (1) | C | [test_mcp_oauth_clients.py:181](../../../backend/tests/test_mcp_oauth_clients.py:181) | SDK 2's registration handler rejects this requested method with 400 before our `register_client` can canonicalize it to `none`. | **No fix.** Decide whether to preserve accept-and-canonicalize or deliberately document refusal. This does not affect CIMD private-key client authentication. Guide replacement unconfirmed. | — |
| `test_a_cimd_record_is_stored_with_the_lifetime_too` (1) | C | [test_mcp_oauth_registrations.py:101](../../../backend/tests/test_mcp_oauth_registrations.py:101) | CIMD lookup creates no database client row; the key lookup fails. | **No fix.** Reconcile persistence policy with the new bounded cache. | — |
| `test_a_refresh_does_not_put_a_linked_client_back_on_the_clock` (1) | C | [test_mcp_oauth_registrations.py:114](../../../backend/tests/test_mcp_oauth_registrations.py:114) | Same absent row, before linkage/refresh assertions can run. | **No fix.** The old keep/TTL lifecycle no longer describes new CIMD clients. | — |
| `test_a_cimd_lookup_at_the_cap_is_not_a_client` (1) | C | [test_mcp_oauth_registrations.py:148](../../../backend/tests/test_mcp_oauth_registrations.py:148) | Lookup succeeds at the database cap because it does not write through `ClientRecords.put`. | **No fix.** Decide whether the cap covers persistent DCR records or admission of CIMD clients too. | — |
| `test_a_client_materialised_by_a_lookup_alone_rolls_over_within_the_cap`, token/revoke (2) | C | [test_mcp_oauth_registrations.py:299](../../../backend/tests/test_mcp_oauth_registrations.py:299) | Expected materialized client rows are absent; measured set is empty. | **No fix.** Replace the obsolete lifecycle coverage only after agreeing its new contract. | — |
| `test_the_binding_refusal_is_the_sdk_protocol_error` (1) | C | [test_route_policy.py:596](../../../backend/tests/test_route_policy.py:596) | SDK 405 JSON-RPC id changed to null. Its session-header assertion actually still passes. | Explicitly pin SDK null id and our existing `server-error` id, then compare the remaining body/status/headers. Production boundary unchanged. Guide replacement unconfirmed. | `43e0d82` |

CIMD's removal from persistent registration storage is intentional upstream behavior, including lazy removal of old rows after successful document refresh. The public OAuth guide still describes persistent CIMD storage, so use the installed implementation and the upstream change as evidence here. Our own memory cache remains bounded at 256 entries; these failures do **not** demonstrate renewed unbounded database growth. [Upstream CIMD change](https://github.com/PrefectHQ/fastmcp/pull/4852), [OAuth guide](https://gofastmcp.com/servers/auth/oauth-proxy)

Additional checks found problems outside those eleven:

| Bucket | Location | Measured outcome | Disposition |
|---|---|---|---|
| C | [pyproject.toml:17](../../../backend/pyproject.toml:17) | Clean runtime image: `ModuleNotFoundError: httpx`, although development import and most tests worked. | Fixed by explicit runtime dependency, `0fc80ca`; rebuilt packaged stack passed. |
| E | [mcp_oauth.py:1884](../../../backend/app/auth/mcp_oauth.py:1884), [upstream revocation:2558](../../../backend/app/auth/mcp_oauth.py:2558) | Production factory uses `fastmcp.server.auth.oauth_proxy.upstream.AsyncOAuth2Client` over httpx2. It has no `revoke_token`; normal exchange=200, refresh=200, local revoke=200, **provider revocation calls=0**. Existing fake uses the old client and conceals this. | **No fix.** Restore an explicit supported upstream revocation path and test the actual production factory. Local grant ending is distinct from provider revocation. |
| C | [discovery_metadata:2036](../../../backend/app/auth/mcp_oauth.py:2036) | Custom authorization metadata omits `authorization_response_iss_parameter_supported`, which FastMCP 4 publishes as true. | **No fix.** Carry the flag into both root AS documents; preserve plamotrack's deliberate client-auth metadata overrides. |

The mechanical re-run passed all six selected existing checks, with only the four brief-contract mismatches red among the new probes: **18 passed / 4 failed**. No router, service, authorization dependency, registry, pre-routing gate, nginx configuration, or existing legacy initialize payload was changed.

## 4. Explicit seam checks

**Transport factory.** Inspected the actual signature and ran a standalone FastMCP echo server through real clients for all four `json_response` × `stateless_http` settings, plus Host/Origin checks: **20 checks passed**. All five named kwargs still exist. Unknown Host=421, refused Origin=403, listed Origin=200. Legacy stateful connections have a session; legacy stateless connections do not. Modern short replies use JSON and no session under either setting. `json_response=False` does not force modern short replies into SSE. The existing T1/route tests ran in the full suite.

**Tool middleware.** The new in-memory and HTTP tests exercise list, a normal read tool, and a missing-arguments write request using a read principal. `on_call_tool` runs once per call in each era, and the scope refusal precedes argument validation. `get_http_request()` works in HTTP, including modern requests, and raises in memory, leaving the injected-principal seam effective. No application `on_message` or `on_initialize` assumption was found.

**Error models.** A direct construction test passed for `JSONRPCError(..., error=ErrorData(code=..., message=...))`. The names remain importable from `mcp.types`; the new package owns their implementation. The changed SDK-generated 405 id is accounted for separately above.

**Discovery.** Fetched all three public documents from the OIDC app and compared them with routes generated by base `OAuthProxy.get_routes` on the same configured proxy. Protected-resource documents matched exactly, including resource `http://localhost/mcp/` and authorization server `http://localhost/mcp`. Our AS and OpenID alias both miss the new issuer-response flag. The remaining differences are intentional: our revoke methods are `none`/`private_key_jwt`, with RS256 advertised on both assertion endpoints; blindly copying base metadata would regress that contract. `application_type` is registration metadata, not an extra AS capability field observed in these documents. No additional SEP-2352 field was observed.

**Authorization-response issuer.** Normal code redirect, owner denial, and our own `invalid_target` redirect all carry `iss=http://localhost/mcp` under 4.0.3. The inherited authorization handler stamps the returned redirect, including one our override constructs. No hand-built-redirect repair is needed for that path. The old `invalid_target` response lacks `iss`.

**DCR application type.** Three normal registration cases passed: native+loopback=201, web+public HTTPS=201, web+loopback=400. The accepted type survives canonicalization in both the response and stored client; accepted registrations are public. A changed native loopback port is still accepted by `BoundDCRClient`. Omitted type retains FastMCP's native default; historical stored records require upgrade-fixture coverage before release. DCR remains available. The protocol announces its deprecation with a twelve-month transition, not immediate removal. [Protocol announcement](https://blog.modelcontextprotocol.io/posts/2026-07-28/)

**Issuer identity before/after.** One dedicated control passed on each version. Both access and refresh token `iss`, discovery issuer, `issuer_url`, and `base_url` equal `http://localhost/mcp` on 3.4.5 and 4.0.3. The distinct-issuer warning therefore does not itself force clients to relink in this configuration. This does **not** prove that an actual persisted 3.x grant survives every 4.x lookup, refresh, cache miss and restart; that cross-version storage test remains required.

**Real upstream HTTP stack.** Ran exchange, refresh and revocation with the production factory restored and an httpx2 transport twin wrapping the existing fake provider. Exchange and refresh passed; provider revocation failed as detailed above. Browser OIDC retained its independent httpx fake. No provider revocation repair or discovery repair was applied in the spike. The seven disposable seam tests finished **5 passed / 2 failed**: upstream revocation and missing discovery flag. The two issuer controls are additional, one pass per version.

**Warnings.** Exactly one unique `FastMCPDeprecationWarning` appeared in the first full upgraded run: `Tool.inputSchema` at the integer-bound test. It was fixed. Other warnings were the existing unstable-store and duplicate-ZIP warnings. No excluded feature was adopted.

## 5. Era probes and unfixed-tree controls

The committed [test_mcp_eras.py](../../../backend/tests/test_mcp_eras.py) has **16 cases**. Before authoring the requests, captured real SDK 2 client traffic and checked `_make_modern_stamp` and the HTTP transport implementation. Requests use `params._meta` with `io.modelcontextprotocol/protocolVersion`, `io.modelcontextprotocol/clientInfo`, and `io.modelcontextprotocol/clientCapabilities`; `MCP-Protocol-Version` and `Mcp-Method` are headers, and `Mcp-Name` accompanies name-bearing methods. `server/discover` is served. These are wire fixtures corroborated by a real client, not guessed spellings.

The exact same file, SHA-256 `faa442a7f5f0417f584a99659e2c078ccb2e0f215ef29dc2525ba77148f1c9b8`, ran against untouched 3.4.5 application/lock files in the temporary main worktree. Both final runs used Python 3.14.2. The worktree was removed afterwards.

| Probe group | Cases | 3.4.5 | 4.0.3 | Why each old-tree red fails |
|---|---:|---:|---:|---|
| In-memory auto / forced legacy: list, call, scope refusal | 2 | 1 red / 1 green | 2 green | Auto negotiates 2025-11-25, not 2026-07-28. Old mode keyword absence is handled, so this is behavioral. |
| PAT tools/list and server/discover without initialize | 2 | 2 red | 2 green | Each returns 400 missing session id, not 200. |
| Anonymous and invalid bearer, each method | 4 | 4 red | 4 red | Anonymous bodies are empty, not the brief's JSON envelope (2); invalid bearer bodies use `invalid_token`, not REST code `auth.bearer_invalid` (2). All four already return 401 with challenge/no-store/no session. |
| RouteBinding undeclared verb | 1 | 1 green | 1 green | 405, declared Allow, no-store, no session. |
| HTTP scope hook, modern / legacy | 2 | 1 red / 1 green | 2 green | Modern request gets 400 missing session id before a tool call. |
| Routing headers present / absent | 2 | 1 red / 1 green | 2 green | With headers, authenticated modern call is still 400 on old SDK. Without headers, old SDK's missing-session refusal keeps this case green; it is not proof of modern routing. |
| Modern-header registration body budget | 1 | 1 green | 1 green | Body guard acts independently of transport era. |
| Modern OAuth call and owner comparison | 1 | 1 red | 1 green | Initial owner-authorized modern call is 400 on old SDK; the post-rebind assertion is not reached there. |
| Unknown-only version | 1 | 1 red | 1 green | Old SDK gives -32600 missing session id. New SDK gives HTTP 400 / -32022 with supported versions, no session. |
| **Total** | **16** | **11 red / 5 green** | **4 red / 12 green** | Seven reds discriminate modern support; four expose a pre-existing brief mismatch. |

The four envelope assertions deliberately remain red in this spike. Existing tests already describe the bare RFC 6750 challenge, and MCP uses the SDK's invalid-token error body. Choose and document the intended contract before converting these probes into migration CI; changing authentication responses merely to satisfy an inaccurate assumption would not be a mechanical upgrade.

On 4.0.3, modern PAT list/discovery replies are 200 with no session id and `Cache-Control: no-store`. Missing or wrong routing headers never grant access: absent/failed credentials remain 401; a read token cannot execute a write. Header omission can cause an earlier protocol rejection, so equal authorization safety does not imply equal HTTP status. The OIDC modern request passes with the bound owner and becomes 401 after rebind.

Initial probe drafts had lifespan-fixture teardown errors; those were corrected by entering/exiting live transport lifespans in the test task. One intermediate mechanical run was interrupted after a wildcard Accept opened a legacy stream; it was rerun with explicit JSON Accept. Neither draft/error/interrupted run is included in the final comparison counts.

## 6. Packaged matrix

Built and started a fresh isolated Compose project, `plamotrack-m61-spike`, with `up -d --build --wait`. Its own database volume protected the development data. The first image failed its API import because runtime httpx was missing; after `0fc80ca`, migration exited 0 and the stack became healthy.

Read the setup token from API logs, claimed the disposable instance, and ran the unchanged local-mode ingress matrix through nginx: **186 checks passed, zero failed, exit 0**. No failing matrix rows remain after the runtime dependency fix.

| Actual client through nginx | Era | Paths | Result |
|---|---|---|---|
| FastMCP 4.0.3 / SDK 2.2.0, auto | 2026-07-28 | `/mcp/`, `/mcp` | Both list 30 tools and call `get_meta`, returning app version 0.3.0. |
| Same client, `mode="legacy"` | 2025-11-25 | Both | Same result. |
| Unmodified FastMCP 3.4.5 / SDK 1.29.0 | 2025-11-25 | Both | Same result. |

A non-vacuous log check found none of six run-specific secret/probe values, with API and nginx access records present. Frontend production build also passed; Vite was not started.

The optional hold-stream row was **not run**. It remains legacy-pinned, as does the deployment gate's 2025-06-18 fixture. Keep it and add a modern twin that holds an actual in-flight POST, observes streaming/timeout behavior, aborts it, and verifies cancellation/cleanup without a session id or standalone GET channel. Successful short calls do not prove long-stream behavior.

CI's real-client row now negotiates modern by default; add an explicit legacy sibling and retain a frozen 3.x client compatibility row. Packaged OIDC mode, the remote deployment gate, browser OAuth clients, and formal protocol conformance were deliberately not run in this spike. They are migration-PR work.

The isolated stack was taken down and only its disposable volume removed. The normal development db overlay was restored healthy; the unrelated Keycloak container was left in place.

## 7. Docs sweep — report only

Searched all requested files for the seven supplied terms, then followed the measured OAuth/storage changes to related statements. No docs or nginx file was edited.

| Location | Required treatment |
|---|---|
| [design.md:2156](../../../docs/design.md:2156) | The description of the current server as handshake/session-era only becomes false. Describe both eras. |
| [operations.md:777](../../../docs/operations.md:777) | “Refused at the handshake” is not universal for modern clients. Describe refusal of the first protected request; retain the historical 0.3.0 upgrade context. |
| [testing-and-review.md:562](../../../.agents/testing-and-review.md:562) | Release version verification cannot rely solely on a handshake's `serverInfo.version`; check legacy initialize and modern discovery/client server information. |
| [README.md:151](../../../README.md:151); [design.md:77](../../../docs/design.md:77), [2154](../../../docs/design.md:2154), [2355](../../../docs/design.md:2355) | Planned M6.1 status changes only when conformance and real-client acceptance are complete. It remains truthful during this spike; a lock bump alone must not mark it built. |
| [design.md:1090](../../../docs/design.md:1090), [1099](../../../docs/design.md:1099), [1100](../../../docs/design.md:1100) | T3/T12/T13 initialize-oriented checks remain valid legacy rows but become incomplete as the overall MCP gate. Add modern equivalents. |
| [design.md:1025](../../../docs/design.md:1025), [1808](../../../docs/design.md:1808), [1819](../../../docs/design.md:1819) | New CIMD clients no longer have the described persistent lifetime/keep/cap lifecycle. Resolve the storage decision and update the current contract; preserve dated history. |
| [design.md:879](../../../docs/design.md:879) | Its promise to ask the provider for revocation is false on this spike's production client path. Restore the behavior before release; do not weaken the promise to hide the regression. Review “whatever it asked for” DCR wording against the new private-key registration refusal. |

The dated 3.4.5 observations at design lines 708, 733, 879 and 1018 remain historical evidence. The old initialize failure recorded in `.agents/lessons.md:463` also remains true. Browser-session, database-session and agent-session references are unrelated. The nginx long-stream comment remains valid for supported legacy connections and streaming responses. No nginx wording was found that requires a mechanical change.

## 8. Recommendation and proposed M6.1 issues

**Split the work, with an atomic migration PR after preparation.** First remove the independent runtime dependency/revocation coupling while still on 3.x. Then bump FastMCP together with the necessary OAuth compatibility changes and era tests. Do not merge a bare bump and leave OIDC broken between PRs. Conformance, deployed-client checks and accurate release docs must pass before M6.1 is called complete.

The application imports and tool/service model survive; this is an integration migration, not a 3,000-line OAuth rewrite. Prioritize the real exposure: runtime startup was broken for everyone until fixed; upstream revoke is an OIDC lifecycle regression; CIMD/DCR changes need contract decisions. The observed failures do not establish an owner-authentication bypass. Review the affected upstream transitions, issuance/refresh/revocation and persisted state, plus the client admission and discovery controls; passing the old fake-based suite alone cannot close those paths.

The following are proposed issue bodies, **not filed**:

**M6.1: Exercise the production OAuth HTTP client and preserve provider revocation**

**GPT-6 (OpenAI) — proposed M6.1 issue from the FastMCP compatibility spike.** Make httpx an explicit runtime dependency and remove the test-only substitution of Authlib's client for FastMCP's production client. Provide httpx/httpx2 provider doubles at the network boundary and preserve upstream revocation using an application-owned, supported path; the existing browser provider's revocation method is a candidate, requiring verification of its credential choice and authentication behavior. Acceptance covers normal exchange, explicit and transparent refresh, local and provider revocation, and recovery behavior using the same client factory as production. — **GPT-6 (OpenAI)**, via Codex

**M6.1: Define CIMD persistence and admission across the FastMCP 4 upgrade**

**GPT-6 (OpenAI) — proposed M6.1 issue from the FastMCP compatibility spike.** Decide whether CIMD documents should follow FastMCP 4's bounded memory-cache model or retain application-owned persistence/admission. Update the five obsolete lifecycle tests only after that decision. Prove bounded state, document refresh and outage behavior, old-row fallback/removal, linked-client continuity, token/revoke lookup behavior and restart/restore, including real 3.x state loaded by 4.x. Keep DCR's lifetime, cap and quota explicit and preserve the one-client-snapshot contract. — **GPT-6 (OpenAI)**, via Codex

**M6.1: Migrate FastMCP and reconcile OAuth discovery and registration contracts**

**GPT-6 (OpenAI) — proposed M6.1 issue from the FastMCP compatibility spike.** Upgrade to the reviewed locked 4.x release with the runtime dependency, mechanical test fixes and era probes. Advertise the issuer-response capability without losing the custom token/revoke methods and algorithms. Decide the handling of a DCR request for `private_key_jwt`, preserve application_type and native/web redirect semantics, retain DCR, and reconcile the brief's REST-style error-code expectations with the existing MCP challenge contract. Include all dependency-coupled compatibility fixes in the bump PR and require a clean full suite. — **GPT-6 (OpenAI)**, via Codex

**M6.1: Gate both eras with real clients, persisted grants and the packaged deployment**

**GPT-6 (OpenAI) — proposed M6.1 issue from the FastMCP compatibility spike.** Extend T2 and the release gate with modern and forced-legacy clients, the frozen 3.x compatibility case, modern streaming/cancellation, both auth modes and both MCP spellings. Run formal protocol conformance and record exact client versions and negotiated eras for Inspector, Claude and ChatGPT. Exercise old grants across upgrade, restart and documented backup/restore, then update roadmap status and upgrade notes from measured results. — **GPT-6 (OpenAI)**, via Codex

Upgrade-note content for the eventual release:

- Keep `PUBLIC_BASE_URL` and `MCP_OAUTH_SIGNING_KEY` unchanged and back up the database plus `.env`. The measured issuer stays the same; no blanket issuer-driven relink is expected. Grant continuity across the actual version transition still needs a release test.
- Rebuild with `docker compose up -d --build --wait`; the runtime must include both the browser's httpx and FastMCP's httpx2.
- Existing legacy clients remain supported at the same endpoint; updated FastMCP clients normally use modern discovery and independent requests. PAT configuration remains the same.
- FastMCP's HTTP stack now uses system trust roots through truststore and different logger names. Verify the deployed container's provider/CIMD TLS path; macOS and the container need not trust the same private CA. Browser OIDC's separate httpx path remains its own dependency.
- Retain DCR during the transition. Publish the final application_type, CIMD storage and registration-refusal decisions, and ensure provider revocation works before recommending the upgrade.

Proposed acceptance matrix; entries below are required future coverage, not claims that these products were tested today:

| Client / path | Required era and authentication coverage |
|---|---|
| FastMCP 4.0.3 / SDK 2.2.0 | Auto modern and forced legacy; in-memory, direct HTTP and nginx; read/write PAT and proxy OAuth. |
| Frozen FastMCP 3.4.5 / SDK 1.29.0 | Legacy HTTP compatibility against the upgraded packaged server. |
| MCP Inspector | DCR/native OAuth, exact installed version and negotiated era recorded; retain legacy and exercise modern when that version supports it. |
| Claude Desktop and Claude Code | Existing supported PAT/bridge configurations; record the bridge and app versions plus actual era. Do not infer wire protocol from the product name. |
| Claude web and ChatGPT web | Real CIMD OAuth, actual negotiated era recorded; link, list/call, refresh, revoke, restart and upgrade continuity. |
| Protocol conformance runner | Modern 2026-07-28 plus supported legacy versions on the real route graph, both auth modes; routing headers, discovery, refusal profiles and streaming/cancellation. No adoption of deferred protocol features. |

All HTTP rows cover `/mcp` and `/mcp/`, owner and insufficient-scope behavior, and no-store/Host/Origin enforcement. The packaged OIDC and Caddy/Cloudflare deployment checks remain outstanding.

Evidence is retained outside the repository in [/private/tmp/plamotrack-m61-fastmcp4-20260908](/private/tmp/plamotrack-m61-fastmcp4-20260908): baseline/full-run logs, audit prompt/inventory, captured SDK wire traffic, transport and OAuth seam measurements, issuer controls and packaged matrix/client results. No credential values are included in this report.

The final ten failures comprise the six deliberately unresolved DCR/CIMD migration expectations and four pre-existing brief-contract mismatches. The two disposable seam failures are additional evidence, outside the full suite. No FastMCP deprecation warning remains.

Suite counts before and after:

| Run | Result |
|---|---|
| Untouched main, FastMCP 3.4.5 | **2,655 passed**, 585 warnings, 1,029.79 s |
| Existing suite unchanged, FastMCP 4.0.3 | **2,644 passed / 11 failed**, 586 warnings, 1,139.42 s |
| Final full suite at `1c41ae6`, including 16 era probes | **2,661 passed / 10 failed**, 587 warnings, 1,067.60 s |
