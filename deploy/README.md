# deploy/

Reference configuration for running an instance behind TLS — the files
`docs/operations.md` ("Standalone VPS: Caddy with Cloudflare DNS") tells you to
copy. They are what the deployment gate (design notes §5.8, T12/T13) runs against
before a release; the results are in the release notes.

- `caddy/Caddyfile` — the site block: Caddy in front of the bundled stack on
  `127.0.0.1:8080`, certificate via the DNS-01 challenge on Cloudflare.
- `caddy/caddy.service.d/cloudflare.conf` — the systemd drop-in that supplies the
  DNS token from a root-only file.

Nothing here is read by the application or the Compose stack.
