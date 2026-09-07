# Running an instance

Backing up, restoring, upgrading and exposing the bundled Docker Compose stack.

> **This instance has a single owner login.** Since M6-3 every collection route
> requires the owner's browser session: a fresh install comes up *unclaimed* and
> prints a one-time setup token to the API log — see [First run](#first-run-claim-the-instance).
> Scripts and MCP clients authenticate with a [personal access token](#access-tokens)
> instead. The door is on loopback by default; [Four ways to run it](#four-ways-to-run-it)
> covers opening it — on a private network, behind your own reverse proxy, through a
> Cloudflare Tunnel, or on a VPS behind Caddy — and says what was tested for each.
> Whatever you choose, the instance answers only to names you list; reach it by any
> other name and it says `421 Misdirected Request`; see [`ALLOWED_HOSTS`](#allowed_hosts).

## Four ways to run it

Four settings in `.env` decide who can reach an instance and by what name:
`WEB_BIND`, `ALLOWED_HOSTS`, `PUBLIC_BASE_URL` and `TRUSTED_PROXIES` —
[each explained below](#the-four-settings). The four ways people actually run it map
onto them like this. "Tested" means the deployment gate (design notes §5.8, T12 and
T13) ran against that configuration before the release that shipped this page; the
results block is in that release's notes.

| | Reached from | `.env` | Tested |
| --- | --- | --- | --- |
| [1. Your own machine or a private network](#1-your-own-machine-or-a-private-network) | that machine; every device on the mesh or LAN | `WEB_BIND` (+ `PUBLIC_BASE_URL`, `ALLOWED_HOSTS` off the machine) | yes — every CI run is the loopback case; the LAN case is the same stack with two lines |
| [2. Behind your own reverse proxy](#2-behind-your-own-reverse-proxy) | whatever the proxy is | `PUBLIC_BASE_URL`, `TRUSTED_PROXIES` | the contract is documented; no named proxy other than Caddy was run |
| [3. Behind a Cloudflare Tunnel](#3-behind-a-cloudflare-tunnel) | the internet, via Cloudflare | `WEB_BIND`, `PUBLIC_BASE_URL`, `TRUSTED_PROXIES` | yes |
| [4. On a VPS behind Caddy](#4-on-a-vps-behind-caddy) — **the reference** | the internet | `PUBLIC_BASE_URL`, `TRUSTED_PROXIES` | yes — this is what T12 and T13 run against |

Plain HTTP carries the session cookie and any token in clear. Ways 1 and 3 have a
plain-HTTP hop on *your* network; ways 2 and 4 terminate TLS in front of the stack.
What plamotrack does in every case: the login, the tokens, the Host allowlist, the
rate limits and the audit trail. What it never does: open a port you didn't ask for.

### 1. Your own machine, or a private network

**On the machine itself** nothing needs setting. `http://localhost:8080` is the
instance, `http://localhost:8080/mcp/` the MCP endpoint, and a local MCP client
(Claude Code, or Claude Desktop through `mcp-remote`) pastes a personal access token
— the README's *Wiring up the MCP server* has the snippets.

**From your laptop, occasionally** — an SSH tunnel. Nothing to configure, nothing
exposed, and it works from anywhere you can SSH:

```bash
ssh -N -L 8080:127.0.0.1:8080 you@your-server
```

`http://localhost:8080` on your laptop is now the instance. `WEB_BIND` stays on
loopback. plamotrack still asks for the login and the token; SSH keeps them, and
everything else, off the network.

**Always available on your own devices** — a WireGuard-based mesh (Tailscale,
Netbird, headscale, plain WireGuard) gives the server an address only your devices
can route to. Bind to *that* interface rather than to everything:

```bash
WEB_BIND=100.x.y.z                   # the server's mesh address, not 0.0.0.0
ALLOWED_HOSTS=nas.tail1234.ts.net    # only if you'll use the mesh's DNS name rather than the address
```

The mesh supplies the confidentiality plain HTTP lacks. The bind address is a name
the instance answers to on its own; a mesh hostname is not, hence the second line.

**On the LAN**:

```bash
WEB_BIND=0.0.0.0
ALLOWED_HOSTS=nas.lan,192.168.1.10   # whatever you'll type into the address bar
```

`0.0.0.0` names nothing, so the second line is not optional: without it every
request from another machine is `421`. Every device on the network can now reach
the login, and any of them positioned on the path can read the session cookie or a
token in transit. Reasonable on a network where you trust every device and every
person; a bad idea on a shared, office or student-house network. **Never route this
in from the internet or put it on a public-facing interface** — that is what ways 3
and 4 are for.

> ### ⚠️ On Linux, a published port ignores your firewall
>
> Docker inserts its own iptables rules to forward published ports into
> containers. That traffic is *forwarded*, not delivered to the host, so it never
> passes the `INPUT` rules `ufw` and `firewalld` mostly work with — `ufw deny 8080`
> typically will **not** block a published container port. Plenty of self-hosted
> services have ended up on the open internet exactly this way.
>
> The reliable control is the bind address, not the firewall: keep `WEB_BIND` on
> `127.0.0.1` or a private-network address, and let it decide who can connect.
> If you do need host-firewall rules to apply to Docker traffic, they belong in
> the `DOCKER-USER` chain.

### 2. Behind your own reverse proxy

Nginx Proxy Manager, Zoraxy, Traefik, an nginx or Apache you already run: any TLS
proxy works if it meets the contract below. Only Caddy on the same host
([way 4](#4-on-a-vps-behind-caddy)) was run through the gate; treat the others as
untested until someone runs them and reports back (a PR with the config and the
matrix output is very welcome).

The contract:

- **Pass the `Host` header through unchanged**, and set `PUBLIC_BASE_URL` to the
  `https://` address in the browser's bar. Its host is then a name the instance
  answers to, and its origin is what lets a browser save (without it every save is
  `403 ingress.origin_not_allowed`), and what makes the session cookie `Secure`.
- **Set `X-Forwarded-For`**, and name the proxy in `TRUSTED_PROXIES` — `127.0.0.1`
  if it runs on the same host, its own address otherwise. Otherwise every visitor
  is the proxy: the per-address rate limits and the audit log key on one address.
  A degradation, not a hole.
- **Do not buffer `text/event-stream` responses**, and **do not put a short read
  timeout on `/mcp`**. MCP is a streaming protocol; a buffering proxy holds the
  response and the client hangs, silently. The bundled nginx's own settings for
  the two `/mcp` spellings (`frontend/nginx/default.conf.template`) are the
  reference: buffering off, an hour's read and send timeout, the hop-by-hop
  `Connection` header cleared.
- **Keep `WEB_BIND` on `127.0.0.1`** if the proxy is on the same host, so the
  proxy is the only way in; a proxy on another machine reaches the LAN address
  from way 1, and the hop between them is plain HTTP on your network.
- **Mind the proxy's access log.** A proxy that logs full request URIs logs the
  one-time codes an OIDC callback carries; see [Access logs](#access-logs-and-callback-credentials).

### 3. Behind a Cloudflare Tunnel

`cloudflared` connects out to Cloudflare; the public name resolves to Cloudflare's
edge, which terminates TLS and forwards to the connector, which forwards to the
instance over your network. Nothing on your side is reachable from the internet
directly. The connector can run on the same host as the stack or on another
machine; the tested configuration was the second.

In the Cloudflare dashboard (Zero Trust → Networks → Tunnels), add a **public
hostname** route on your tunnel: the hostname you want, service type **HTTP**,
URL `http://<address the connector reaches the instance at>:8080`. Then in `.env`:

```bash
WEB_BIND=10.0.0.9                  # the address the connector reaches; 127.0.0.1 if it runs on this host
PUBLIC_BASE_URL=https://plamotrack.example
TRUSTED_PROXIES=10.0.0.5           # the connector's address; 127.0.0.1 on the same host
```

and `docker compose up -d`. `PUBLIC_BASE_URL`'s host is allowed automatically;
add a LAN name to `ALLOWED_HOSTS` only if you also reach it that way. Cloudflare
sets `X-Forwarded-For` to the visitor, so with the connector trusted the rate limits
and the audit log see visitors, not the connector. The hop from the connector to the
instance is plain HTTP on your own network — way 1's assumption; keep it there.

What Cloudflare's proxy does with plamotrack's traffic, as run: the MCP transport
streams (the API sends `Content-Type: text/event-stream`, which is what tells the
tunnel not to buffer), and a stream held idle stays open — Cloudflare's 125-second
limit is on the time to a response's *headers*, not on a stream, and its idle limit
is 900 s while the API pings every 15 s. A long non-streaming request (a very large
CSV import, say) that takes over 125 s to answer is a Cloudflare `524`; the work on
the instance still completes. Cloudflare Access can sit in front as well; the
plamotrack login still applies behind it.

### 4. On a VPS behind Caddy

The reference remote deployment: Caddy on the same host terminates TLS and proxies
to the bundled stack on `127.0.0.1:8080`, so the only ports open are Caddy's 80 and
443. The certificate comes from Let's Encrypt through the **DNS-01** challenge on
Cloudflare — the deployment gate runs exactly this — which works whether or not the
host is reachable from the internet, and is the only way to a certificate for a
name that isn't. If your host *is* reachable on 80 and 443 under its name, Caddy's
default challenge works with no module and no token: delete the `tls` block. That
variant is Caddy's standard behaviour, not something the gate ran.

**Install Caddy** from its repository, and add the Cloudflare DNS module (it
replaces the binary with a build from caddyserver.com that includes it):

```bash
# Debian / Ubuntu — https://caddyserver.com/docs/install
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
sudo caddy add-package github.com/caddy-dns/cloudflare
```

**The token.** In Cloudflare, create an API token with **two** permissions on the
zone your name is in — Zone → DNS → Edit *and* Zone → Zone → Read (the module reads
the zone id before it edits a record, so both are required; Cloudflare's built-in
"Edit zone DNS" template grants exactly these two). Put it, and only it, in a
root-only file — added in an editor, never as a shell argument, so it never lands in
your shell history or a process list:

```bash
sudo install -m 0600 /dev/null /etc/caddy/cloudflare.env
sudoedit /etc/caddy/cloudflare.env        # add one line:  CLOUDFLARE_API_TOKEN=<the token>
sudo install -d /etc/systemd/system/caddy.service.d
sudo cp deploy/caddy/caddy.service.d/cloudflare.conf /etc/systemd/system/caddy.service.d/
sudo systemctl daemon-reload
```

**The Caddyfile** is [`deploy/caddy/Caddyfile`](../deploy/caddy/Caddyfile) — copy
it to `/etc/caddy/Caddyfile` and replace the name:

```caddyfile
plamotrack.example {
    reverse_proxy 127.0.0.1:8080
    tls {
        dns cloudflare {env.CLOUDFLARE_API_TOKEN}
    }
}
```

Nothing else is needed, and nothing else was tested. Caddy obtains and renews the
certificate, redirects `http://` to `https://`, passes the `Host` header through
unchanged, sets `X-Forwarded-For` and `X-Forwarded-Proto`, and streams
`text/event-stream` responses without buffering or a read timeout. There is no
`log` directive on purpose: a proxy access log records full request URIs, and an
OIDC instance's callbacks carry one-time codes in theirs.

**Three lines in `.env`**, then start the stack:

```bash
PUBLIC_BASE_URL=https://plamotrack.example
TRUSTED_PROXIES=127.0.0.1
# WEB_BIND stays 127.0.0.1 — Caddy is the only way in
```

```bash
sudo systemctl restart caddy
docker compose up -d --build --wait
```

**Check it** from another machine: `https://plamotrack.example/api/healthz` is
`{"status":"ok"}`, `https://plamotrack.example/api/readyz` is 404 (readiness is for
the container's own healthcheck; a stranger cannot learn whether the database is
up), and the setup screen loads. Then [claim the instance](#first-run-claim-the-instance).

Behind TLS the session cookie is `Secure` and `__Host-`-prefixed, and OIDC mode —
Google or your own provider for the login, Claude web and ChatGPT web linking as MCP
clients — is available; see [Signing in through an identity provider](#signing-in-through-an-identity-provider-oidc-mode).

### Unsupported

The docs say so rather than leaving it to be discovered:

- `WEB_BIND=0.0.0.0` on a public interface without TLS in front.
- Publishing `api:8000` directly. The ingress's route separation and default-deny
  are part of the control set, and the API's own controls assume nginx is its peer.
- A proxy in front of the stack that is not named in `TRUSTED_PROXIES`. Forwarded
  headers are then ignored: the rate limits key on the proxy's address and the
  audit log records it — a degradation, not a bypass.
- Changing `PUBLIC_BASE_URL` on an instance with linked MCP clients without
  relinking them: the OAuth issuer changed, and every link is invalid.

## The four settings

Everything lives in `.env` at the repo root — one file, read by both Compose and
the API — and a change needs `docker compose up -d` to take effect. The
[full table](#configuration) is below; these four are the ones that decide who
reaches the instance, and the API and the ingress read the same lines.

### `WEB_BIND`

The interface the one published port listens on; `127.0.0.1` by default, so only
the host itself can connect. It is the reliable control, not the host firewall
(the box under [way 1](#1-your-own-machine-or-a-private-network)). A non-loopback
value here is also a name the instance answers to; `0.0.0.0` names nothing. Keep
it on loopback behind a proxy on the same host ([way 4](#4-on-a-vps-behind-caddy));
set it to the address a connector or proxy on another machine reaches
([way 3](#3-behind-a-cloudflare-tunnel)). `WEB_PORT` (default `8080`) is the port.

### `ALLOWED_HOSTS`

Since 0.2.10 the instance refuses a request whose `Host` header is not a name it
knows, with `421 Misdirected Request` and a JSON body naming the setting to fix. It
is the Host-allowlist half of the M6 threat model (design notes §5.6): a page in your
browser that points its own hostname at your instance (DNS rebinding) can no longer
talk to it. It is also the one setting here that can lock you out of your own
install, which is why it shipped as a release of its own.

Always known: `localhost`, `127.0.0.1`, `[::1]`, a `WEB_BIND` address that names an
interface, and the host of `PUBLIC_BASE_URL`. Everything else — `nas.lan`,
`plamotrack.home.arpa`, a container name, a name a reverse proxy forwards that is
not the public one — goes in `ALLOWED_HOSTS`. Ports don't matter (`nas.lan:8080` is
`nas.lan`), nor does a trailing DNS dot or letter case; wildcards like `*.home.arpa`
work (that leading `*.` is the only wildcard form); a bare `*`, a `*:8080`, or a `*`
anywhere else is refused at startup, because an allowlist of everything is the hole
the setting closes. `WEB_BIND=0.0.0.0` names *nothing*, so the LAN address or
hostname you actually type still has to be listed.

**Locked out?** You typed a name into a browser or an MCP client and got 421. Nothing
was written and nothing is lost. Add the name:

```bash
# in .env
ALLOWED_HOSTS=nas.lan
```

then `docker compose up -d`. The API and the ingress read the same line, so that is
the whole fix. Behind a proxy or tunnel the name is `PUBLIC_BASE_URL`'s host, which
is known on its own — set that instead. The SSH-tunnel path — `localhost:8080` on
your laptop — never needs either.

### `PUBLIC_BASE_URL`

The address a browser uses, when it isn't `http://localhost:<WEB_PORT>`: scheme,
host and port, nothing after. Three things hang off it.

*The Origin half of the allowlist.* A write (`POST`, `PATCH`, `DELETE`) that
arrives with an `Origin` header — every browser sends one — must come from the
instance's own origin, from a loopback origin against a loopback name, or from a
listed one; anything else is `403` with the code `ingress.origin_not_allowed`.
Behind TLS the app sees plain HTTP on its socket while the browser's origin is
`https://…`, so **without `PUBLIC_BASE_URL` every save from the browser is that
403** — reads work, the login works, and the first save fails. The fix is the line,
then `docker compose up -d`; nothing is lost. Scripts, `curl` and MCP clients send
no `Origin` and are not affected. Reaching the instance over plain HTTP by one name
and through an HTTPS proxy by another is the case for `PUBLIC_BASE_URL` (the
canonical one) plus `ALLOWED_ORIGINS` (the rest).

*The cookie.* On plain HTTP the session cookie cannot be marked `Secure` (a browser
limitation), so its confidentiality rests on the network being yours; with an
`https://` `PUBLIC_BASE_URL` it is `Secure` and `__Host-`-prefixed. The API's start
log says which it is.

*Installation identity.* In OIDC mode it is required and must be `https` (or
`localhost` / `127.0.0.1` while developing): the provider's callbacks and the MCP
OAuth issuer (`<PUBLIC_BASE_URL>/mcp`) are built from it, and linked MCP clients are
bound to it. Choose the name you mean to keep; changing it later means every linked
client re-authorises.

### `TRUSTED_PROXIES`

IPs or CIDRs of a reverse proxy or tunnel connector in front of the stack whose
`X-Forwarded-For` should be believed for the client's address. nginx keys its
per-client rate limits on that resolved address and the API records it in security
audit events; without the right entry every visitor *is* the proxy, and the limits
and the audit trail see one address. A degradation, not a hole — nothing in the
application's own identity (cookies, redirects, the OAuth issuer) ever comes from a
forwarded header; that is `PUBLIC_BASE_URL`'s job.

**A proxy on this same host is `127.0.0.1`** — Caddy in way 4. Inside the bundled
stack that entry also trusts the Docker network's gateway, which is where a process
on the host actually arrives from (Docker's port forwarding rewrites the source of
loopback-originated connections); the gate observed nginx recording the gateway
before that line and the visitor after it. **A connector or proxy on another
machine is its own address** — way 3. Leave it empty when clients connect directly
to the bundled stack. Every walked hop must be a valid IP (an optional numeric port
is accepted); a malformed or empty hop stops resolution at the last verified address.

In the bundled stack, nginx performs that proxy walk and the unpublished API trusts
the client-address header nginx overwrites. Every container attached to the private
Compose network is therefore inside that header's trust boundary: do not attach an
untrusted companion container to it, and do not treat audit addresses on requests
sent directly to `api:8000` by another container as verified. Host clients cannot
reach that port through the supplied Compose configuration; all published traffic
passes through nginx, which overwrites a forged value.

## First run: claim the instance

A fresh install (and an existing instance upgraded onto M6-3) starts **unclaimed**:
every collection route answers `401` and the UI shows a setup screen. Claim it once:

```bash
docker compose logs api | grep -A6 "no owner yet"
```

The API prints a one-time **setup token** at every start while the instance is
unclaimed. Copy it, open the instance in a browser, and enter the token with the
owner password you want. That's it — the token is single-use, and the instance
stops printing one once claimed. Lost the token? Restart the container
(`docker compose restart api`) and read the fresh one from the log.

After that, one owner password signs you in from any browser that can reach the
instance. Sign out from the sidebar. Forgot the password? See
[Recovery](#recovery-locked-out). Prefer to sign in with Google or your own
identity provider instead of a password? See
[OIDC mode](#signing-in-through-an-identity-provider-oidc-mode).

### Recovery: locked out

Three ways to be locked out, three ways back, none of which loses anything.

**Forgot the password.** Reset it from **inside the API container** — never over
the network:

```bash
docker compose exec api python -m app.auth.recovery reset-password
```

It prompts for a new password, sets it, and signs every browser out. To sign
everyone out without changing the password, use `revoke-sessions` instead. Both
run only where you already have shell access to the host, which is the point.
Neither touches access tokens — revoke those from Settings once you are back in.

**`421 Misdirected Request`.** The name you used isn't listed —
[`ALLOWED_HOSTS`](#allowed_hosts), or `PUBLIC_BASE_URL` behind a proxy — then
`docker compose up -d`.

**Reads work behind your new TLS proxy, but every save is `403`.** The browser's
`https://` origin isn't yet the instance's own — [`PUBLIC_BASE_URL`](#public_base_url),
then `docker compose up -d`. The gate runs both of these lockouts and their
recoveries on every release.

### Signing in through an identity provider (OIDC mode)

Instead of a password, the owner can sign in at an OpenID Connect provider —
Google, or a self-hosted Keycloak or Authentik. It is a mode, not an add-on: an
instance is either `local` (password) or `oidc`, never both, and the switch is an
edit to `.env`. Register a client with the provider whose one authorised redirect
URI is `<PUBLIC_BASE_URL>/api/auth/oidc/callback`, then:

```ini
AUTH_MODE=oidc
PUBLIC_BASE_URL=https://plamotrack.example        # required in this mode
OIDC_ISSUER=https://accounts.google.com           # exactly as the provider's discovery document states it
OIDC_CLIENT_ID=…
OIDC_CLIENT_SECRET=…
```

and `docker compose up -d`. The API prints a setup token at start, as for a fresh
install; the setup screen asks for it and then sends you to the provider. **The
account you sign in with becomes the owner**, bound to the stable identity the
provider asserts (its issuer and subject) — not to an email address, which is
shown in the UI and used for nothing else. Any other account that signs in at
the same provider is refused and recorded in the audit log. An instance switched
from local mode keeps its data; the API signs every browser out at its first
start in the new mode (an `auth.mode_changed` audit row records how many), the
old password is ignored, and the first provider sign-in with the new setup token
binds the owner. Switching back to local mode signs everyone out the same way.
The client you register must be the **only audience** of the id_tokens the
provider issues for it — a token naming an additional audience is refused, so do
not attach other clients' audience mappers to it.

If the provider is down, new sign-ins fail with a clear message; sessions that
already exist, access tokens and MCP clients keep working. The mode never falls
back to a password on its own.

OIDC mode needs an **https** `PUBLIC_BASE_URL` — TLS in front of the stack, ways 2
to 4 — or `localhost` / `127.0.0.1` while developing. The reason is the MCP side
below: in this mode the instance is an OAuth authorization server at
`<PUBLIC_BASE_URL>/mcp`, which the standard requires to be https. A plain-http
address on your LAN stays on local mode.

**Lost the identity-provider account, or changing provider?** From inside the
API container:

```bash
docker compose exec api python -m app.auth.recovery rebind-oidc
```

It clears the bound identity and signs every browser out. Restart the API
(`docker compose restart api`), read the new setup token from its log, and sign
in at the provider — that account is the owner from then on. Access tokens are
untouched; revoke any you no longer trust from Settings. MCP clients linked
through the provider stop working at their next request until the new owner
signs in through them again.

### MCP clients that sign in through the provider (OIDC mode)

In OIDC mode, MCP clients that speak OAuth — **Claude web, ChatGPT web, MCP
Inspector**, any client that can register itself — connect to
`<PUBLIC_BASE_URL>/mcp/` with no token pasted: they discover the instance as an
OAuth server, show you a consent page, send you to the same identity provider
the browser login uses, and receive access tokens of their own. Two more lines
in `.env`, and the provider's client needs a second redirect URI:

```ini
MCP_OAUTH_SIGNING_KEY=…                          # 32 random bytes as 64 hex characters: openssl rand -hex 32
# MCP_OAUTH_ALLOWED_REDIRECT_URIS=…              # optional, see .env.example before setting it
```

Register `<PUBLIC_BASE_URL>/mcp/auth/callback` with the provider beside the browser
callback. Then add the connector in the client — Claude web and ChatGPT web take the
URL `<PUBLIC_BASE_URL>/mcp/` in their custom-connector dialog and handle the rest —
and sign in when asked. Only the **bound owner's** account is accepted: anyone else
who signs in at the provider is refused before any token is issued, and the refusal
is recorded in the audit log (`auth.mcp_identity_refused`). Every token a client
receives acts as the owner with read *and* write access to the collection — never
the instance settings, imports or token management, which stay with the browser —
so link a client only where you would paste a read-and-write access token.
Personal access tokens keep working on `/mcp/` in this mode too; a client that can
send a header needs nothing new.

Clients that register themselves are registered as **public** clients (PKCE, no
client secret) whatever they ask for, and the registration response says so — a
client secret would add nothing here, since anyone can register. Claude web and
ChatGPT web bring their own client metadata documents instead of registering and
authenticate the way those documents say, on every endpoint.

Ending a link: a client that revokes either of its tokens (`POST /mcp/revoke`) ends
the whole grant at once — its access token, its refresh token, and, best effort,
the provider's own refresh token — recorded as `auth.mcp_grant_revoked`, and it
does so whatever the provider is doing at the time (the grant is found by the
instance's own signature, not by asking the provider); rebinding
the owner (`recovery rebind-oidc`) ends every grant at the next request, and a
client left holding one can still revoke it; a
grant whose provider token can no longer be refreshed ends with it; and a refresh
the provider answers with another identity, or with an id_token that fails
verification, ends the grant too — `auth.mcp_grant_revoked` with
`ended_by=upstream_refresh`, beside the refusal — and the client links again.
Revoking a linked client at the provider (its sessions or consent) has the same
effect once its token comes up for refresh.

What the signing key is: installation identity, like `PUBLIC_BASE_URL`. Rotate it
(or change `PUBLIC_BASE_URL`) and every linked client asks you to sign in again;
nothing else is lost. The proxy's state — registered clients, the provider's
tokens, encrypted — lives in the database (`mcp_oauth_state`), so a database
backup plus `.env` is the whole backup and there is no second volume. Restore a
dump taken before a client was linked, or lose the key, and that client relinks;
data, browser sessions and access tokens are untouched — [Backups](#backups) has
the three cases as the gate ran them.

## Access tokens

The browser session is for people. A script, a cron job or an MCP client (Claude
Desktop, Claude Code, anything else that speaks MCP over HTTP) authenticates with a
**personal access token** instead: **Settings → Access tokens** in the app, owner
login required. A token looks like `ptk_<id>_<secret>`, is shown once when it is
created, and is stored only as a digest — if you lose it, revoke it and make
another. Send it as an `Authorization: Bearer ptk_…` header on the REST API
(`/api/…`) and on the MCP endpoint (`/mcp/`). **Never put a token in a URL:** a
query parameter is ignored as a credential, but request URIs are what access
logs record — nginx's and the API's both go to `docker compose logs` — so a token
there is a token in your logs. The README's *Wiring up the MCP server* section has
the Claude Desktop and Claude Code configuration.

What a token can do is chosen when it is minted and never widens:

- **Read-only** — list and look up: kits, orders, the catalog, retailers, settings,
  the CSV exports.
- **Read and write** — the above plus adding kits and catalog items, recording and
  editing orders, adjusting stock, applying upgrades, and CSV import in `merge` or
  `add_only` mode.

No token can change the instance settings, run a `replace_all` import, or manage
tokens — those stay with the owner login, so a leaked token cannot lock you out or
erase the collection. An optional expiry (30, 90 or 365 days) is offered at
creation. The list shows when each token was last used; **Revoke** stops it
immediately and keeps the row as a record. The MCP endpoint takes *only* a token —
the browser's session cookie never authenticates it, by design, so a page in your
browser cannot drive an agent's tools. Minting, revoking, and any use of a revoked
token are recorded in the audit table.

## Security audit retention

Security-relevant authentication and ingress events are kept in Postgres's
`audit_event` table: owner claim, login success/failure/throttling, logout and
session revocation, token mint/revocation/use-after-revocation, host-side recovery,
and app-layer Host/Origin refusals. Rows carry the credential's kind and id when
one exists, the resolved client address, and the route or tool — never a request
body, query string, or secret. The bundled nginx rejects an unknown Host before
it can reach the API, so that outer refusal is in nginx's access log; the app's
defence-in-depth Host refusal is the database event. Collection edits are not
audited in Milestone 6.

OAuth client references (DCR ids and CIMD URLs) and refused OIDC subjects are stored
as `sha256:<hex digest>` in audit details. The digest covers the whole identifier,
so clients whose URLs differ only by query or fragment can still be distinguished;
the URL, userinfo and other opaque text are not displayed. Protocol identifiers and
verified principal ids are unchanged. Browser callback failures record only
`access_denied`, `missing_code`, or `other`; token-exchange diagnostics retain the
HTTP status without copying a provider's error body. These rules apply to new rows;
existing audit rows are not rewritten. Use retention if older records must expire.

The table is append-only during normal operation. Retention is the operator's
choice; this host-side command deletes rows older than 180 days and appends a row
recording the prune itself:

```bash
docker compose exec api python -m app.auth.recovery prune-audit --older-than-days 180
```

Use a different positive day count if your policy requires it. Take a database
backup first if those events must remain available elsewhere.

### Access logs and callback credentials

The API and bundled nginx record request paths, methods and statuses without
query strings. nginx also omits request headers, including `Referer`, because an
OAuth callback URL can contain an authorization code and state. Its access records
include upstream status and request/upstream timing for diagnosing 429 and 5xx
responses. nginx's request error diagnostics cannot be reformatted and include the
raw request, so the bundled HTTP context discards them; configuration/startup
failures still reach stderr. Authentication-library diagnostics retain severity
and source with a fixed message: the libraries can embed state values, provider
errors and exceptions in their text. The application's own safe auth messages,
audit events and other application errors remain available. Do not restore
nginx's default combined access format or request error log on an OIDC instance.

A proxy in front needs the same hygiene. The reference Caddyfile has no `log`
directive for exactly this reason; if you enable one, or your proxy logs by
default (most do), it records the full request URI — including an OIDC callback's
one-time code — unless you configure it not to.

## What's running

`docker compose up -d --build --wait` gives you four things:

| Service | What it is | Published? |
| --- | --- | --- |
| `web` | nginx: the UI, plus `/api` and `/mcp` proxied to the API | **yes** — `127.0.0.1:8080` |
| `api` | FastAPI + the MCP server, one process | no |
| `migrate` | runs `alembic upgrade head`, then exits | no |
| `db` | Postgres 16 | no — Compose network only |

Only `web` is reachable, so an instance has one door. `migrate` showing as
`Exited (0)` is what success looks like — it's a startup step, not a service.

The API is deliberately not published. Anything you'd have pointed at
`localhost:8000` now goes through the ingress: `http://localhost:8080/api/…`, and
MCP at `http://localhost:8080/mcp/`.

## Backups

A backup is **two things: the database and `.env`.** Nothing else holds state —
not a volume, not a file the containers write. The database holds the collection,
the browser sessions, the access-token digests and, in OIDC mode, the MCP clients'
encrypted OAuth state (`mcp_oauth_state`). `.env` holds the secrets that make the
last two usable: the database password and, in OIDC mode, `MCP_OAUTH_SIGNING_KEY`,
which encrypts that state and signs the tokens clients hold.

Two kinds of database copy, and they answer different questions.

**`pg_dump` — exact restore.** Everything, byte for byte, including ids and
timestamps. This is your disaster-recovery copy; with `.env` beside it, it is the
whole backup.

```bash
docker compose exec -T db sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' \
  > plamotrack-$(date +%F).dump
```

**The CSV archive — portable copy.** Readable, diffable, and importable into a
future version whose schema has moved on. Slower to restore and it won't preserve
ids exactly, but it survives things a dump doesn't — and it never carries
credentials, so it is safe to keep anywhere. Grab it from
**Settings → Data management → Export** in the UI, or:

```bash
curl -o plamotrack-archive.zip http://127.0.0.1:8080/api/export/archive
```

Both are point-in-time: the archive is read from a single database snapshot, so
taking one while the app is in use — an agent adding an order mid-download — gives
you the collection as it stood when the export began reading, never a mix of
before and after.

Keep both. The dump is what you restore from on Sunday; the archive is what still
opens in three years. See [import-export.md](import-export.md) for the format.

### Restoring a dump

Into an **empty** database — `pg_restore` will not merge cleanly into a populated
one:

```bash
docker compose down -v          # destroys the current database. See the warning below.
docker compose up -d db --wait
docker compose exec -T db sh -c \
  'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
  < plamotrack-2026-08-10.dump
docker compose up -d --build --wait
```

> `docker compose down -v` deletes the `db-data` volume, which **is** your
> collection. Without `-v` the volume survives and `down` is safe. Take a backup
> first regardless.

The quoted variables are expanded inside the database container, so these commands
follow the active `POSTGRES_USER` and `POSTGRES_DB` values from `.env` rather than
assuming the defaults.

**What comes back** depends on which half of the backup you have. The deployment
gate runs all three of these with the commands above, verbatim, against a client
linked through Claude-style OAuth, on every release:

| You restore | Collection | Browser sessions | Access tokens | Linked MCP clients (OIDC mode) |
| --- | --- | --- | --- | --- |
| the dump **and** the `.env` it was taken with | intact | still signed in | still valid | still linked — the client's next refresh succeeds, nothing re-registers |
| the dump with a **different `.env`** (a new database password, a new or lost `MCP_OAUTH_SIGNING_KEY`) | intact | still signed in | still valid | every link invalid — the client signs in again and is linked afresh; nothing else is lost |
| a dump taken **before** a client was linked, with the same `.env` | intact | still signed in | still valid | that client signs in again; the earlier links in the dump are fine |

Sessions and tokens survive a changed `.env` because they are stored as digests,
not signatures; only the OAuth state is encrypted under the key. A restore without
`.env` at all means a fresh `.env` with a new database password: the dump still
restores (the password only matters when the volume is first created, which the
restore does), and the second row applies.

## Upgrading

```bash
git pull
docker compose up -d --build --wait
```

The `migrate` service applies any new migrations before the API starts, so
there's no separate step. If a migration fails, `up` exits non-zero and the API
is not started at all — you get a stopped deploy with a readable error rather
than a half-migrated database serving traffic. Check it with:

```bash
docker compose logs migrate
```

**Back up before upgrading.** Migrations run forward automatically; rolling one
back is a manual `alembic downgrade` and some are deliberately lossy about it.

### Upgrading to 0.2.10: set `ALLOWED_HOSTS` first

0.2.10 makes the instance refuse names it doesn't know
([`ALLOWED_HOSTS`](#allowed_hosts)). If you reach it by anything other
than `localhost` or `127.0.0.1` — a LAN hostname, a container name, a mesh DNS
name, a reverse proxy — add that name to `ALLOWED_HOSTS` in `.env` **before** the
`docker compose up`, or the first thing you'll see afterwards is
`421 Misdirected Request`. It is recoverable (edit `.env`, `up -d` again, nothing
lost), but there is no reason to meet it by surprise. No migration in this release.

### If you imported CSVs before 0.2.7

Importers before 0.2.7 could leave a kit order line holding a different number of
kits than its quantity said. Nothing in the app minds, but an archive exported from
such a collection is refused when you try to restore it with *replace everything*
("this line says quantity N, but this upload supplies M kit(s)"). Check once, before
your next export:

```bash
docker compose exec -T db sh -c 'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT oi.id, oi.quantity, count(k.id) AS kits
FROM order_items oi LEFT JOIN kits k ON k.order_item_id = oi.id
WHERE oi.item_type = 'kit'
GROUP BY oi.id, oi.quantity
HAVING count(k.id) <> oi.quantity;
SQL
```

No rows means nothing to do. For each row it lists, open that order in the app and
save the line — the order editor reconciles the count against the kits actually
there (it spawns the missing one, or leaves an extra one where it is once you set
the quantity to match). Then export again.

### If your database predates 2026-08-06 (the first public schema)

The migration that introduced pending/received orders marked every order that
existed before it as received — those orders had their stock applied at entry, so
they were received by definition. It did **not** touch the kits those orders had
spawned. A database that crossed that revision can therefore hold a received order
whose kit still says *Ordered* or *In transit*, which the app would never produce
on its own.

This is cosmetic, and it is deliberately not repaired by a later migration: a
repair running today would overwrite kit statuses set by hand since, which is
worse than the blemish. If you see such a kit, drag it to the right column (or
edit its status) — that is the whole fix. Fresh installations are unaffected; the
window was a single day of pre-public history.

## Configuration

Everything lives in `.env` at the repo root — one file, read by both Compose and
the API. `.env.example` documents every key. The ones worth knowing:

| Key | Default | Notes |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | — | Required. Only read when the database volume is first created. |
| `WEB_BIND` | `127.0.0.1` | [The four settings](#web_bind). |
| `WEB_PORT` | `8080` | Host port for the UI, `/api`, and `/mcp`. |
| `ALLOWED_HOSTS` | — | [The four settings](#allowed_hosts). Comma-separated, no ports; `*.home.arpa` wildcards work. Any other name gets **421**. |
| `PUBLIC_BASE_URL` | — | [The four settings](#public_base_url). Scheme, host and port, nothing after. Required and `https` in OIDC mode. |
| `AUTH_MODE` | `local` | `local`: the setup token and a password. `oidc`: a sign-in at an OpenID Connect provider — see [Signing in through an identity provider](#signing-in-through-an-identity-provider-oidc-mode). Mutually exclusive; there is no "off". |
| `OIDC_ISSUER` | — | OIDC mode. The provider's issuer URL, exactly as its discovery document states it (`https://accounts.google.com`, `https://keycloak.example/realms/home`). `https`, unless the provider is on loopback. |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | — | OIDC mode. The client registered with the provider, whose authorised redirect URIs are `<PUBLIC_BASE_URL>/api/auth/oidc/callback` (the browser) and `<PUBLIC_BASE_URL>/mcp/auth/callback` (MCP clients). |
| `MCP_OAUTH_SIGNING_KEY` | — | OIDC mode, required. 32 random bytes as 64 hex characters (`openssl rand -hex 32`): signs the tokens MCP clients receive and encrypts the proxy's state in the database. Installation identity — rotating it means every MCP client re-authorises. See [MCP clients that sign in through the provider](#mcp-clients-that-sign-in-through-the-provider-oidc-mode). |
| `MCP_OAUTH_ALLOWED_REDIRECT_URIS` | — | OIDC mode, optional. Comma-separated patterns a dynamically registering MCP client may use as its callback (`http://localhost:*`). Narrows registration, never replaces it; applies to every client kind when set, so it must also admit the web clients' callbacks. Leave unset unless you have a reason. |
| `ALLOWED_ORIGINS` | — | Extra browser origins allowed to write, beyond the instance's own and loopback ones. Rarely needed. |
| `TRUSTED_PROXIES` | — | [The four settings](#trusted_proxies). `127.0.0.1` for a proxy on this host; a connector's or proxy's own address otherwise. |
| `REFERENCE_CURRENCY` | `AUD` | Your currency — **first-run bootstrap only**. The migration seeds it into the instance settings; after that the database row is the setting (`PATCH /settings`), and editing the env var does nothing. Changing the setting affects new entries only — stored snapshots keep the currency they were recorded in. |
| `DATABASE_URL` | — | Set it to use a Postgres you manage yourself; the `POSTGRES_*` values then only configure the bundled `db`. |

Changes to `.env` need `docker compose up -d` to take effect.

### Bootstrap vs runtime settings

Interface language, formatting locale, time zone, date style, hour cycle, and the
reference currency are **runtime settings**: they live in the database (the
one-row `instance_settings` table), so every browser and agent sees the same
values. Read them with `GET /api/settings`, change them with `PATCH /api/settings`. The
Settings page shows them all: General changes the reference currency, while
Language & region changes the interface language, formatting locale, time zone,
date style, and hour cycle. A fresh install bootstraps them once:
`en-AU` interface language and formatting locale, `UTC` time zone, locale-default
date style and hour cycle, and the reference currency from `REFERENCE_CURRENCY`
in `.env`. After that first migration the env var is inert. The full-archive
export includes the settings row and a restore updates it in place — details in
`docs/import-export.md`.

Existing instances upgrade to the same `en-AU`/UTC defaults. The configured time
zone applies prospectively when an import reads a naive CSV timestamp; existing
stored instants, dates, currency snapshots, and CSV identifiers are never
reinterpreted. Downgrading past the settings migration removes the settings row,
so record any changed values before a rollback and set them again after upgrading.

## When something's wrong

**`up --wait` hangs or fails.** Find the unhealthy service:

```bash
docker compose ps
```

**The UI loads but everything is empty and the console shows failed requests.**
The API isn't ready. `docker compose logs api`, and `docker compose ps` for the
api healthcheck — it probes `/readyz` from *inside* the container, which is the
only place that answers (from outside, `/api/readyz` is deliberately 404 so a
stranger can't learn whether the database is up); `/api/healthz` only says the
process is alive.

**`421 Misdirected Request`, from a browser or an MCP client.** You reached the
instance by a name it doesn't know. [`ALLOWED_HOSTS`](#allowed_hosts) — add it (or
set `PUBLIC_BASE_URL` behind a proxy), `docker compose up -d`, nothing lost.

**`403` with `ingress.origin_not_allowed` on a save.** The page you saved from is
on an origin the instance doesn't recognise as its own — an HTTPS proxy or tunnel
in front of a plain-HTTP instance, and `PUBLIC_BASE_URL` not yet set to the
address in your browser's bar. [`PUBLIC_BASE_URL`](#public_base_url).

**Caddy shows a certificate error, or never gets a certificate.** `journalctl -u
caddy`. For the DNS-01 challenge: the token file exists, is `CLOUDFLARE_API_TOKEN=…`,
the drop-in is installed and `systemctl daemon-reload` was run, and the token has
**both** Zone → DNS → Edit and Zone → Zone → Read on the right zone (a token missing
Zone Read fails to look up the zone id — "an unknown error occurred" from the module).
For the default challenge: the name resolves to this host from the internet and ports
80 and 443 reach Caddy.

**`502 Bad Gateway` from Caddy.** The stack isn't up, or `WEB_BIND` isn't
`127.0.0.1`: `docker compose ps`, and `curl http://127.0.0.1:8080/api/healthz` on the
host.

**Every visitor is being rate-limited at once, or the audit log shows one address
for everyone.** The proxy or connector isn't in `TRUSTED_PROXIES`, or is listed by
the wrong address — [`TRUSTED_PROXIES`](#trusted_proxies).

**`password authentication failed`.** `POSTGRES_PASSWORD` changed after the
database volume was created. Postgres only reads it when initialising an empty
data directory. Either put the old value back, or `docker compose down -v` and
restore from a backup — that flag deletes the database.

**Port already in use.** Something else has 8080. Set `WEB_PORT` in `.env`.

**MCP client connects but hangs.** Check you're on `…/mcp/`. Both spellings
work through the bundled ingress, but a client pointed at a *different* proxy you
put in front of this one needs buffering off and no short read timeout — MCP is a
streaming protocol, and a buffering proxy holds the response instead of passing it
on. It fails as a hang, not an error. `frontend/nginx/default.conf.template` is a
working reference; the [contract](#2-behind-your-own-reverse-proxy) lists what a
proxy must do.

**A `524` from Cloudflare on one long request.** A non-streaming response took over
125 seconds to begin — a very large import, say. The instance finished the work; the
tunnel gave up waiting for the headers. Everything streaming (MCP) is unaffected.
