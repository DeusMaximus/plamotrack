#!/bin/zsh
# restart.sh <store_dir> <key_hex>  — restart the phase-B probe server with a given store + signing key
set -u
HERE=${0:A:h}
STORE=$1
KEY=$2
pkill -f probe_b_server.py 2>/dev/null
sleep 1
cd "$HERE"
SPIKE_STORE_DIR="$STORE" SPIKE_PG_URL="${SPIKE_PG_URL:-}" SPIKE_OWNER_SUB="${SPIKE_OWNER_SUB:-}" SPIKE_OWNER_AT_ISSUANCE="${SPIKE_OWNER_AT_ISSUANCE:-}" SPIKE_JWT_KEY_HEX="$KEY" SPIKE_VERIFY_ID_TOKEN="${SPIKE_VERIFY_ID_TOKEN:-}" SPIKE_REQUIRED_SCOPES="${SPIKE_REQUIRED_SCOPES:-openid}" \
SPIKE_OIDC_CONFIG_URL=http://localhost:8081/realms/plamotrack/.well-known/openid-configuration \
SPIKE_CLIENT_ID=plamotrack-mcp SPIKE_CLIENT_SECRET=plamotrack-mcp-secret \
nohup "$HERE/../../../backend/.venv/bin/python" probe_b_server.py > probe_b_server.out 2>&1 &
for i in {1..30}; do
  curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/.well-known/oauth-authorization-server/mcp 2>/dev/null | grep -q 200 && break
  sleep 0.5
done
echo "--- MARK restart store=$STORE key=${KEY[1,8]}…" >> access.log
