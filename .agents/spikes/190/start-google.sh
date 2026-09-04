#!/bin/zsh
# start-google.sh <store_dir> [extra authorize params, e.g. 'access_type=offline&prompt=consent']
set -u
HERE=${0:A:h}; cd "$HERE"
pkill -f probe_b_server.py 2>/dev/null; sleep 1
set -a; source ./secrets.env; set +a
SPIKE_BIND=0.0.0.0 SPIKE_PORT="${SPIKE_PORT:-8000}" SPIKE_BASE_URL=https://testing.gunp.la SPIKE_STORE_DIR="$1" SPIKE_JWT_KEY_HEX="$(cat jwt_key.hex)" \
SPIKE_OIDC_CONFIG_URL=https://accounts.google.com/.well-known/openid-configuration \
SPIKE_VERIFY_ID_TOKEN=1 SPIKE_REQUIRED_SCOPES="${SPIKE_REQUIRED_SCOPES:-openid}" SPIKE_EXTRA_AUTHORIZE="${2:-}" \
nohup "$HERE/../../../backend/.venv/bin/python" probe_b_server.py > probe_b_server.out 2>&1 &
for i in {1..40}; do curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:${SPIKE_PORT:-8000}/.well-known/oauth-authorization-server/mcp 2>/dev/null | grep -q 200 && break; sleep 0.5; done
echo "--- MARK start-google store=$1 extra=${2:-}" >> access.log
