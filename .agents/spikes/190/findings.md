**Claude Fable 5.1 (Anthropic) — #190 spike, every leg run, 2026-09-04. Draft of the evidence comment.**

Pinned: FastMCP 3.4.5, MCP SDK 1.29.0, py-key-value-aio 0.4.5, Starlette as locked. Harness: `.agents/spikes/190/` (README there). Every number below was read off a run, not off the docs, except where a line says "from source".

## 1. Providers and clients

| Leg | Status | Version | Notes |
|---|---|---|---|
| Self-hosted OIDC: **Keycloak** | run | 26.6.4 (`quay.io/keycloak/keycloak:26.6`, `start-dev --import-realm`) | chosen over Authentik: one container, a realm import file, and FastMCP ships a Keycloak provider; Authentik needs Postgres + Redis + a worker. Confidential client, PKCE S256, redirect `http://127.0.0.1:8000/mcp/auth/callback`. |
| **Google** | run | Google OAuth 2.0 (owner's client, type Web application) | `OIDCProxy(config_url=<Google discovery>, verify_id_token=True)` works through the tunnel: the verified claims are the id_token's (`iss` `https://accounts.google.com`, the owner's `sub`, `email`, `email_verified`). Two Google-only facts (section 7): scopes come back as full URIs, and no refresh token is issued unless the authorize request carries `access_type=offline&prompt=consent`. Google access tokens are opaque, so the default `JWTVerifier` path is not an option here — the id_token path is the one shape that serves both providers. |
| **MCP Inspector** | run | 2.5.0 (Node 24.15.0) | DCR public client (`token_endpoint_auth_method=none`), callback `http://127.0.0.1:6274/oauth/callback`, negotiated **MCP 2025-11-25** with FastMCP 3.4.5 — no M6.1 dependency. |
| **Claude web** | run | claude.ai, 2026-09-04, via `https://testing.gunp.la` (Cloudflare tunnel → the packaged nginx → the probe) | **CIMD client**: `client_id=https://claude.ai/oauth/mcp-oauth-client-metadata`, callback `https://claude.ai/api/mcp/auth_callback`, scope `openid`, a `resource` parameter; the add-connector dialog detected "Always required" auth and offered three client kinds — *Anthropic's hosted client metadata (CIMD), Recommended, Detected* (because the AS document advertises `client_id_metadata_document_supported`), *register automatically (DCR)*, *your own OAuth client*. It did **not** send the upstream client id: FastMCP's source comment about claude.ai is out of date for the current client. Transport user agent `Claude-User`; auth traffic `python-httpx/0.28.1`. |
| **ChatGPT web** | run | chatgpt.com, 2026-09-04, same path | **CIMD client** too, with a per-connector document: `client_id=https://chatgpt.com/oauth/<connector id>/client.json` (`client_name=ChatGPT`), callback `https://chatgpt.com/connector/oauth/<connector id>`, scope `openid`, `resource` and `ui_locales` parameters. Transport user agent `openai-mcp/1.0.0`; auth traffic `Python/3.13 aiohttp/3.13.5`. |

**Discovery URLs the Inspector actually requests** (from the probe's access log, user-agent `node` = its proxy process, `Mozilla` = the browser):

```
POST /mcp/                                          401  (WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp/")
GET  /.well-known/oauth-protected-resource/mcp/     200  ← the pointer, verbatim, trailing slash included
GET  /.well-known/oauth-authorization-server/mcp    200  ← path-aware RFC 8414
POST /mcp/register                                  201
GET  /mcp/authorize → 302 /mcp/consent → 302 Keycloak → GET /mcp/auth/callback → 302 http://127.0.0.1:6274/oauth/callback?code=…&state=…
POST /mcp/token                                     200
POST /mcp/  (bearer)                                200 …
```

It never asked for `/.well-known/openid-configuration/mcp` or the bare `/.well-known/openid-configuration`.

**Claude web**, through the packaged nginx: `POST /mcp/` 401 → `GET /.well-known/oauth-protected-resource/mcp/` → `GET /.well-known/oauth-authorization-server/mcp` → `/mcp/authorize` (CIMD) → consent → Google → `/mcp/auth/callback` → 302 `https://claude.ai/api/mcp/auth_callback?code=…` → `POST /mcp/token` 200 → transport. **Against the bare source-run probe it stalled**: on Connect it strips the trailing slash and posts to `/mcp`, and with no 401 pointer it walked a fallback chain — `/.well-known/oauth-protected-resource/mcp` (no slash), `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, then `POST /register` at the root — every one 404, and gave up. (Its *detection* probe in the add dialog had used `/mcp/` with the slash.) So **nginx's bare-`/mcp` rewrite is load-bearing for Claude web**, and the source-run app's family-13 401 for bare `/mcp` (a bare `Bearer` challenge, no `resource_metadata`) would not rescue it — see section 10.

**ChatGPT web**: `POST /mcp/` 401 → PRM (slash form) → AS document → **`GET /mcp/.well-known/openid-configuration` (the pruned child alias) → 404 → `GET /.well-known/openid-configuration/mcp` 200** → authorize (CIMD) → consent → Google → callback → 302 `https://chatgpt.com/connector/oauth/<id>?code=…` → token 200 → transport; it re-runs the whole discovery chain on every connection, tolerating the 404 each time. So the **path-aware OpenID document is required** (ChatGPT reads it), the child alias is not, and **nobody requested the bare `/.well-known/openid-configuration`** — it stays pruned.

## 2. The route table

Raw child (`create_streamable_http_app(streamable_http_path="/", auth=proxy)`, methods as Starlette reports them, HEAD added by Starlette):

```
/.well-known/oauth-authorization-server        GET HEAD OPTIONS   ← pruned before mounting
/.well-known/oauth-protected-resource/mcp/     GET HEAD OPTIONS   ← pruned before mounting
/authorize                                     GET HEAD POST
/token                                         OPTIONS POST
/register                                      OPTIONS POST
/revoke                                        OPTIONS POST       (present because Keycloak advertises revocation)
/auth/callback                                 GET HEAD
/consent                                       GET HEAD POST
/                                              DELETE POST        (+GET once the session manager is up)
```

`get_well_known_routes("/")` for `base_url=…/mcp` — exactly the four §5.5 predicted; the parent installs the first three:

```
/.well-known/oauth-authorization-server/mcp    GET HEAD OPTIONS
/.well-known/openid-configuration/mcp          GET HEAD OPTIONS
/.well-known/openid-configuration              GET HEAD OPTIONS   ← pruned
/.well-known/oauth-protected-resource/mcp/     GET HEAD OPTIONS   (resource = …/mcp/, slash included)
```

**Through the packaged nginx** (the `frontend/` image built at head, `PUBLIC_BASE_URL` unset, in front of the probe) — everything §5.5 says, with two things it does not say:

- `GET /.well-known/oauth-protected-resource/mcp` (no slash) → **301** `/.well-known/oauth-protected-resource/mcp/` — nginx's own rule for a proxied location ending in `/`, relative (`absolute_redirect off`). A new ingress-produced redirect beside `/api` → `/api/`; #192's T2 either lists it or suppresses it (`location = …/mcp { return 404; }` in front). No client needed it: all three requested the slash form from the pointer once they had one (Claude web asks for the slash-less form only in its no-pointer fallback, where a 301 would not have saved it — its next step was the bare documents).
- `PUT /mcp/authorize` → **405 `Allow: GET, HEAD, POST`** from Starlette, before any policy — the family-8 sibling of #206.

The rest: three root documents 200 with `public, max-age=3600` and the nginx security-header set; `…/mcp/` on the AS document, bare `oauth-authorization-server`, bare `openid-configuration`, `/.well-known/anything` → 404; `/mcp/.well-known/*` → 404 (pruned); `/api/.well-known/…`, `/api/%2ewell-known/…`, `/api//.well-known/…`, `/api/mcp/authorize`, `/api/mcp/.well-known/…` → 404 at nginx; `/mcp/authorize/`, `/mcp/token/`, `/mcp/consent/`, `/mcp/auth/callback/?code=x&state=y` → 404 with **no `Location`** (`redirect_slashes=False` on the child holds through the mount); bare `/mcp` → 401 with the challenge (the rewrite); hostile `Host` → 421 on discovery and on `/mcp/authorize` alike; the discovery documents name `PUBLIC_BASE_URL`'s issuer, not the request's Host. Full matrix: `probe_c_ingress.py`.

## 3. Proxy-state persistence — decide for the Postgres adapter

What the proxy stores (six collections, all through one `AsyncKeyValue`): `mcp-oauth-proxy-clients` (DCR registrations), `mcp-oauth-transactions` (15-min consent transactions), `mcp-authorization-codes` (5-min), `mcp-upstream-tokens` (the IdP's access/refresh tokens — **the secrets**), `mcp-jti-mappings` (FastMCP JWT → upstream token), `mcp-refresh-tokens` (metadata keyed by hash).

**Default store**: `FernetEncryptionWrapper(FileTreeStore)` under `<fastmcp home>/oauth-proxy/<sha256(key)[:12]>/` — `fastmcp.settings.home` is platformdirs' user data dir (`~/Library/Application Support/fastmcp` here; `~/.local/share/fastmcp` in the image). The Fernet key is derived from the signing key and the directory name from that, so a rotated key silently starts an empty store.

**Postgres adapter**: `key_value.aio.stores.postgresql.PostgreSQLStore(url=…, table_name=…)` — imports and runs on the locked tree because it uses asyncpg, already a dependency. It opens its own asyncpg pool and creates its table on first use:

```sql
CREATE TABLE IF NOT EXISTS mcp_oauth_state (collection TEXT NOT NULL, key TEXT NOT NULL, value JSONB NOT NULL,
  ttl DOUBLE PRECISION, created_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, PRIMARY KEY (collection, key));
CREATE INDEX … idx_mcp_oauth_state_expires_at ON … (expires_at) WHERE expires_at IS NOT NULL;
```

Wrapped in the same Fernet wrapper every `value` is `{"__encrypted_data__": …}` — the database never holds an upstream token in clear. Run: link → restart → refresh 200 → initialize 200 → **0 registrations**.

**T13 with the file store** (same procedure, `verify` = the saved refresh token, then initialize with the old and the new access token):

| Restart with | refresh | old access token | registrations after |
|---|---|---|---|
| same store, same key | 200 | 200 | 0 |
| **empty store**, same key | 401 `invalid_client` "Invalid client_id" | 401 `invalid_token` | 0 (nothing tried) |
| same store, **other key** | 401 `invalid_client` | 401 `invalid_token` | 0 |
| back to same store, same key | 200 | 200 | 0 |

So a lost store or a lost key both surface as **`invalid_client`** at refresh — the DCR registration itself lives in the store — and the client re-registers, re-consents, and the owner logs in again; data, sessions and PATs untouched (§5.6 safe failure, confirmed). The stale-bearer 401 carries FastMCP's own guidance text in `error_description` ("clear authentication tokens in your MCP client and reconnect").

**Decision the evidence supports:** the Postgres adapter. The backup set collapses to **two** parts (the database, which already carries every session and PAT digest, plus `.env`); no second volume, no new restore step in `docs/operations.md`; the table is outside `services/portability/spec.py` so an export cannot carry it and `replace_all` cannot truncate it. Costs to carry into #192: the store's DDL runs outside Alembic (`IF NOT EXISTS`, so an Alembic migration can own the table with identical DDL and the store's create becomes a no-op — do that, one schema owner); a second connection pool on the same database (size it: the proxy touches the store a handful of times per request); the pytest truncation list gains or explicitly skips the table.

## 4. The signing key — explicit, bytes, and never the default store with it

- `jwt_signing_key` **bytes** are used as-is (0.003 s); a **str** goes through PBKDF2, 1.2 M iterations (0.27 s at startup here, once).
- Omitted, it is HKDF-derived from the **upstream client secret** — rotating the IdP secret would then invalidate every issued token *and* the store's encryption key. Explicit it is.
- The default store derives its Fernet key by `.decode()`-ing the key bytes as UTF-8: `OAuthProxy(jwt_signing_key=<32 random bytes>)` with no `client_storage` raises `UnicodeDecodeError` at construction. With our own store (section 3) that path is never taken; derive the storage key ourselves (HKDF, distinct salt).
- Recommendation: `MCP_OAUTH_SIGNING_KEY`, 32 random bytes hex in `.env`, separate from the session secret; documented as installation identity beside `PUBLIC_BASE_URL` (both invalidate every MCP link when changed).

## 5. Client-redirect binding per client kind

Measured on `GET /mcp/authorize` (registered DCR client, `http://localhost:3000/cb`):

| `allowed_client_redirect_uris` | requested redirect | result |
|---|---|---|
| none | `http://localhost:3000/cb` | 302 → consent |
| none | `http://localhost:4000/cb` | 302 → consent (**RFC 8252 loopback port varies**) |
| none | `http://127.0.0.1:3000/cb` | 400 "not registered" (loopback *host* must match) |
| none | `http://localhost:3000/other` | 400 |
| none | `http://localhost:3000/cb/../x` | 400 (normalised to `/x`, then refused) |
| none | `http://localhost@evil.example/cb` | 400 |
| none | `https://evil.example/cb` | 400, no `Location` |
| none | `https://evil.example/cb` **as the upstream client id** | **302 → consent** (the §5.6 probe, reproduced) |
| none, registered `https://claude.ai/api/mcp/auth_callback` | exact / `…callback2` / `:8443` / other host | 302 / 400 / 400 / 400 |
| `["http://localhost:*"]` | `http://localhost:5000/anything-at-all` | **302** — the pattern **replaces** the registration, as §5.6 says |
| `["http://localhost:*"]` | `https://evil.example/cb` as the upstream id | 400 (the allowlist binds the synthesised client too) |
| `["http://localhost:*"]` | registering `https://client.example/cb` | 400 `invalid_redirect_uri` (the allowlist narrows registration) |
| any | registering `javascript:alert(1)` | 400 |

**The thin constraint exists and is 15 lines** (`probe_a2.py`, `BoundProxy`): `get_client` returns `None` for the upstream client id and wraps a stored DCR client in `BoundDCRClient`, whose `validate_redirect_uri` checks the registration (exact, loopback port free) *and then* the allowlist. Re-run of the matrix: `localhost:5000/anything-at-all` → 400 under the allowlist, `localhost:4000/cb` still 302, both upstream-id rows 400 with no `Location`.

**Which named client uses which kind** (measured): MCP Inspector → **DCR** (public, loopback callback, the port-varies exception is what it relies on); Claude web → **CIMD**; ChatGPT web → **CIMD**; **nobody used the synthesised upstream-id client**, so it is refused outright. CIMD therefore **stays on** (`enable_cimd=True`, advertised as `client_id_metadata_document_supported`) — it is the kind both web clients chose first. Its binding is the document's own `redirect_uris` (`https://claude.ai/api/mcp/auth_callback`; `https://chatgpt.com/connector/oauth/<id>`) *and* the operator allowlist if one is set, which means an allowlist that only names loopback would lock the web clients out — the allowlist is for narrowing DCR, and the CIMD document is the binding for web clients. Cost carried into #192: the proxy fetches an attacker-chosen `https://` URL on `/authorize` (FastMCP's SSRF guard refuses private ranges; the document is cached per client id), so `authorize` needs the family-8 rate limit and the fetch a timeout, and the consent page's "Verified domain: claude.ai" line is the user-facing signal that the binding held.

## 6. The response profile FastMCP emits

| Route | status | `Cache-Control` | cookies / headers |
|---|---|---|---|
| discovery ×3 (GET, HEAD, OPTIONS preflight) | 200 | `public, max-age=3600` | `Access-Control-Allow-Origin: *` |
| `GET /mcp/authorize` no params / unknown client / bad redirect | 400 JSON | `no-store` | — |
| `GET /mcp/authorize` ok | 302 → `/mcp/consent?txn_id=…` (built from `base_url`; `Host: evil.example` + `X-Forwarded-Host` change nothing) | `no-store` | — |
| `GET /mcp/consent` | 200 HTML | **none** | `__MCP_CONSENT_STATE` HttpOnly SameSite=lax **Path=/** Max-Age=900; `X-Frame-Options: DENY`; CSP as a `<meta>` only |
| `POST /mcp/consent` approve | 302 → upstream authorize (`redirect_uri=<base_url>/auth/callback`, PKCE S256, `state=<txn>`, the client's `resource` forwarded) | **none** | `__MCP_CONSENT_STATE` (60 s) + `__MCP_CONSENT_BINDING` (900 s) |
| `POST /mcp/consent` deny | 302 → client `?error=access_denied&state=…` | **none** | — |
| `POST /mcp/consent` bad CSRF / no txn | 400 HTML | none | — |
| `GET /mcp/auth/callback` ok | 302 → client `?code=…&state=…` | **none** | clears the binding entry |
| `GET /mcp/auth/callback` error + valid txn | 302 → client `?error=…` | none | — |
| `GET /mcp/auth/callback` no params / unknown txn | 400 HTML | none | — |
| `POST /mcp/token` bad code / bad refresh, with or without a stray bearer | **401** `invalid_grant` (FastMCP maps the SDK's 400 to 401) | `no-store` | — |
| `POST /mcp/token` ok | 200 | `no-store` | — |
| `POST /mcp/revoke` ok | 200 | `no-store` | — |
| `POST /mcp/revoke` no `client_id` / bad form | 401 `unauthorized_client` / 400 | **none** | — |
| `POST /mcp/register` | 201 | none | — |

Under an `https://` `base_url` the cookies become `__Host-MCP_CONSENT_STATE` / `__Host-MCP_CONSENT_BINDING` with `Secure` (the `__Host-` prefix is why `Path=/`). A blanket `no-store` middleware on the mount (`probe_a3.py`) stamps consent GET/POST, both callback redirects and the token error, **leaves every `Set-Cookie` intact**, and discovery keeps `public, max-age=3600`. §5.6's sentence needs one amendment: the SDK's revocation handler sets `no-store` on its **200 only** — its 400/401 error paths carry nothing, so the middleware covers them too. The consent HTML gets nosniff / CSP / Referrer-Policy from nginx at the ingress; source-run it has only `X-Frame-Options`, so the app's own profile stamp is what makes §5.6's clickjacking row true off the packaged stack.

## 7. Identity and scopes — three findings that shape #192

**(a) FastMCP issues tokens to whoever the IdP authenticates.** A second realm user linked and called `whoami` with their own `sub`/email. The natural hook — a `TokenVerifier` wrapper refusing `(iss, sub) ≠ owner` — is **per request only**: the stranger still received a full token pair from `POST /mcp/token` and was refused at the first `POST /mcp/` (401 `invalid_token`). Refusing at **issuance** is a 12-line override of `OAuthProxy.exchange_authorization_code` (`probe_b_server.py`, `OwnerProxy`): load the code's stored IdP tokens, run the verifier, delete the code and raise `TokenError("invalid_grant", …)` → the stranger gets `401 invalid_grant` at `/token` and nothing is minted or stored; the owner is unaffected. Keep both (the wrapper is defence in depth and is what refuses a rebound owner's old link).

**(b) `sub` is not guaranteed by `openid` alone.** Keycloak 25+ moved `sub` (and `auth_time`) into the `basic` client scope; a realm whose client lacks it returned tokens with `email`, `preferred_username`, `azp` and **no `sub`** — FastMCP's `JWTVerifier` then falls back to `azp` as the client id and never notices. The owner binding must refuse a token without `sub`, never fall back to email.

**(c) The MCP-facing scope vocabulary is the upstream's, not ours.** `valid_scopes` = `token_verifier.required_scopes`; DCR with `scope: "openid collection:read collection:write"` → **400** at `/register`; a client requesting a scope outside its registration → `invalid_scope` at `/authorize`; and whatever is advertised is forwarded **verbatim** in the upstream authorize URL (`scope=…` built from the transaction's requested scopes), then the FastMCP JWT's `scope` claim is whatever the IdP granted (`openid profile email` here). Google refuses unknown scope strings outright. So `collection:read` / `collection:write` cannot be per-grant OAuth scopes on FastMCP 3.4.5 without translating in both directions — `_translate_scopes_from_idp` is a documented hook, but the outbound side is `_build_upstream_authorize_url`, a private method. Under #30's rule that is not M6. **Recommendation:** every proxy-issued token is the owner's delegated grant with a **fixed** mapping to `collection:read` + `collection:write`, never `instance:admin`; the advertised scopes are the identity scopes (`openid email profile` or the provider's equivalents); §5.5's `mcp` row loses "if granted".

**(d) Google, measured.** With `required_scopes=["openid","email","profile"]` the first Google link issued a token whose scopes were `https://www.googleapis.com/auth/userinfo.email openid https://www.googleapis.com/auth/userinfo.profile` — Google normalises the short names to URIs on the way back — and the transport answered **403 `insufficient_scope`** to a freshly issued token (FastMCP checks the required scopes against the token's scope claim at the mount). Require `openid` alone (or the URI forms); `GoogleProvider` has a normaliser for exactly this, the generic `OIDCProxy` does not. Second, Google's token response carried **no `refresh_token`** until the authorize request included `access_type=offline` and `prompt=consent` (`extra_authorize_params`; `GoogleProvider` sets both by default, `OIDCProxy` sets neither) — without them the link dies with the hour-long access token. With them, both web clients received a refresh token. Not measured: the transparent upstream refresh after the hour (needs an hour), and re-consent behaviour on Google's side after revocation.

Also measured: with `verify_id_token=True` the claims the tool sees are the id_token's (`sub`, `aud=<client_id>`, `typ: ID`, no `scope`), so a custom verifier must **declare** `required_scopes` itself (they are what the AS document advertises and what DCR defaults to — with none, every client is refused `invalid_scope`) while its inner JWKS verifier checks none. The FastMCP access token is HS256 with `iss=<base_url>`, `aud=<resource …/mcp/>`, `client_id`, `scope`, `exp` = the upstream `expires_in` (Keycloak's default **300 s**; Google's is 3600 s) — `fastmcp_access_token_expiry_seconds` decouples it; refresh tokens rotate on use, default lifetime one year.

## 8. The failure rule (#30)

Nothing measured needs custom protocol code. The adapters are three subclass methods and one verifier wrapper, ~45 lines together, each replacing a documented extension point: `get_client` + a `ProxyDCRClient` subclass (binding), `exchange_authorization_code` (owner at issuance), `TokenVerifier` (owner per request, id_token verified against the provider's JWKS); plus two constructor arguments for Google (`extra_authorize_params`, `required_scopes=["openid"]`). M6.1 dependency: none — the Inspector negotiated MCP 2025-11-25 with FastMCP 3.4.5, and both web clients completed initialize and tool listing against it.

## 9. Not measured

- Authentik (Keycloak was the self-hosted provider; nothing in the flow is Keycloak-specific beyond the `basic` scope note).
- Google's transparent upstream refresh once the hour-long access token expires, and Google-side revocation.
- A native DCR client other than the Inspector exercising the loopback-port exception in anger (Claude Desktop through `mcp-remote` uses a PAT in M6, by design).
- The web clients against the pre-routing gate's bare-`/mcp` 401 source-run (the packaged stack is what they will meet; the source-run case is the developer's).

## 10. §5 amendments the evidence supports so far (to apply with the remaining legs)

- §5.5 `mcp` principal: fixed `collection:read` + `collection:write`, no "if granted" (7c).
- §5.5 family 8: the bare OpenID document stays pruned (no client asked for it); the path-aware OpenID document is **required** (ChatGPT reads it) and the child alias stays pruned (ChatGPT tolerates its 404); the two nginx facts (301 on the slash-less PRM path; `PUT` → 405 + `Allow`) into T2 and #206; **bare `/mcp` is a client-facing spelling** — Claude web posts to it — so the nginx rewrite is load-bearing and T2 keeps its row, and the source-run family-13 401 for bare `/mcp` (no `resource_metadata` pointer) is a developer-only gap to note beside §5.9 item 3(b)(iv).
- §5.6 proxy trust: client kinds are now measured — DCR (Inspector), CIMD (Claude web, ChatGPT web), the upstream-id client used by nobody and refused; CIMD stays enabled and its document is the web clients' binding; the operator allowlist narrows DCR only.
- §5.6 credential leakage: revocation's error paths carry no `no-store` either; the backup set is **two** parts (database + `.env`) once the store is the Postgres table (3).
- §5.6 open redirect / §5.9 items 6–7: owner binding at issuance via `exchange_authorization_code`, per request via the verifier; a token without `sub` refused (7a, 7b).
- §5.9 item 5 → decided: Postgres adapter, table owned by Alembic; explicit `MCP_OAUTH_SIGNING_KEY` bytes (3, 4).
- §5.9 item 7: `verify_id_token=True` as the one verifier shape; `required_scopes=["openid"]` (Google returns URI-form scopes); `extra_authorize_params={"access_type": "offline", "prompt": "consent"}` for Google, or no refresh token; CIMD on; FastMCP token lifetime pinned deliberately rather than inherited from the IdP's default (7).
- §5.8 T12: the tunnel run stands in for the Caddy path only for the OAuth clients — TLS termination, the 60 s stream and the `ALLOWED_HOSTS` lockout are still the release gate's.

— **Claude Fable 5.1 (Anthropic)**, via Claude Code
