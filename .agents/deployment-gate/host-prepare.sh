#!/bin/sh
# Prepare the deployment-gate host (T12/T13, design notes §5.8; #194): Docker
# and Compose from Docker's repository, Caddy from its repository plus the
# cloudflare DNS module, the reference Caddyfile with the test fixture beside
# it, the stack's .env, and Keycloak. Run as root on a fresh Debian 13 host
# whose working tree is already at $PLAMOTRACK_DIR (the driver rsyncs it; the
# branch under test is not necessarily pushed). Idempotent: re-running
# refreshes what changed and leaves the rest.
#
#   PLAMOTRACK_TEST_NAME=testhost.example \
#   PLAMOTRACK_TUNNEL_NAME=tunnel.example \
#   sh /opt/plamotrack/.agents/deployment-gate/host-prepare.sh
#
# What it refuses to do: write the DNS token. The operator creates
# /etc/caddy/cloudflare.env (CLOUDFLARE_API_TOKEN=…, mode 0600) beforehand.
set -eu

: "${PLAMOTRACK_TEST_NAME:?the public name Caddy serves plamotrack on}"
: "${PLAMOTRACK_TUNNEL_NAME:=tunnel.invalid}"
PLAMOTRACK_DIR="${PLAMOTRACK_DIR:-/opt/plamotrack}"
GATE="$PLAMOTRACK_DIR/.agents/deployment-gate"
export DEBIAN_FRONTEND=noninteractive

step() { printf '\n== %s\n' "$*"; }

step "host"
. /etc/os-release
echo "$PRETTY_NAME; virt=$(systemd-detect-virt 2>/dev/null || echo unknown)"
test -d "$PLAMOTRACK_DIR/backend" || { echo "no working tree at $PLAMOTRACK_DIR" >&2; exit 1; }
test -s /etc/caddy/cloudflare.env 2>/dev/null || {
    echo "write CLOUDFLARE_API_TOKEN=... to /etc/caddy/cloudflare.env (mode 0600) first" >&2
    mkdir -p /etc/caddy
    exit 1
}
# The variable name is what the Caddyfile reads; a token under another name
# (CF_API_TOKEN, a bare value) leaves Caddy with nothing and no certificate.
# Checked by name only — the value is never read here.
grep -q '^CLOUDFLARE_API_TOKEN=.' /etc/caddy/cloudflare.env || {
    echo "/etc/caddy/cloudflare.env must contain one line: CLOUDFLARE_API_TOKEN=<token>" >&2
    exit 1
}

step "base packages"
apt-get update -q
apt-get install -y -q ca-certificates curl gnupg git rsync openssl jq debian-keyring debian-archive-keyring apt-transport-https

step "Docker Engine + Compose from download.docker.com"
install -m 0755 -d /etc/apt/keyrings
if [ ! -s /etc/apt/keyrings/docker.asc ]; then
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
fi
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $VERSION_CODENAME stable" \
    > /etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker --version; docker compose version

step "Caddy from dl.cloudsmith.io + the cloudflare DNS module"
if [ ! -s /usr/share/keyrings/caddy-stable-archive-keyring.gpg ]; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
fi
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -q
apt-get install -y -q caddy
if ! caddy list-modules 2>/dev/null | grep -q '^dns.providers.cloudflare$'; then
    # Replaces /usr/bin/caddy with a build from caddyserver.com that includes
    # the module — the documented route for the package install.
    caddy add-package github.com/caddy-dns/cloudflare
fi
caddy version
caddy list-modules | grep '^dns.providers.cloudflare$'

step "Caddyfile + token drop-in"
install -d /etc/systemd/system/caddy.service.d
install -m 0644 "$PLAMOTRACK_DIR/deploy/caddy/caddy.service.d/cloudflare.conf" \
    /etc/systemd/system/caddy.service.d/cloudflare.conf
chmod 0600 /etc/caddy/cloudflare.env
sed "s/PLAMOTRACK_TEST_NAME/$PLAMOTRACK_TEST_NAME/g" "$GATE/Caddyfile.test" > /etc/caddy/Caddyfile
caddy fmt --overwrite /etc/caddy/Caddyfile
# validate needs the token in its own environment (systemd supplies it to the
# service); a subshell loads the file and exits — nothing is printed.
( set -a; . /etc/caddy/cloudflare.env; set +a; caddy validate --config /etc/caddy/Caddyfile )
systemctl daemon-reload
systemctl enable --now caddy
systemctl restart caddy

step "the stack's .env"
cd "$PLAMOTRACK_DIR"
if [ ! -f .env ]; then
    cp .env.example .env
    sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 16)/" .env
    echo "wrote .env with a generated POSTGRES_PASSWORD (WEB_BIND stays 127.0.0.1; no public name yet)"
else
    echo ".env exists; left alone"
fi

step "Keycloak (test fixture) behind idp.$PLAMOTRACK_TEST_NAME"
sed -e "s/PLAMOTRACK_TEST_NAME/$PLAMOTRACK_TEST_NAME/g" \
    -e "s/PLAMOTRACK_TUNNEL_NAME/$PLAMOTRACK_TUNNEL_NAME/g" \
    "$GATE/keycloak/realm.template.json" > "$GATE/keycloak/realm.json"
( cd "$GATE/keycloak" && PLAMOTRACK_TEST_NAME="$PLAMOTRACK_TEST_NAME" docker compose up -d --wait )

step "done"
echo "next: docker compose up -d --build --wait in $PLAMOTRACK_DIR, then the driver's phases"
