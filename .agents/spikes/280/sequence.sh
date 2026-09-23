#!/bin/sh
# The #280 spike end to end, in order, from `backend/`:
#   sh ../.agents/spikes/280/sequence.sh https://NAME root@HOST
# Every step appends its rows to .dev/280/log.md; `set -e` stops at the first
# step that exits non-zero except where a failure is the expected result.
set -u
BASE=$1 SSH=$2
p() { uv run --with 'playwright==1.62.*' python ../.agents/spikes/280/probe.py "$@" --base "$BASE" --ssh "$SSH"; }
p prepare || exit 1
p enrol owner && p enrol stranger || exit 1
p claim && p login && p stranger || exit 1
p mcp                      # expected to FAIL: Pocket ID refuses the forwarded `resource`
p matrix
p api-resource add || exit 1
p mcp && p verify || exit 1
p lifetime 1 && p mcp || exit 1
sleep 75                   # past the provider's one-minute access token
p transparent && p race && p reuse || exit 1
p restart idp && p restart api || exit 1
p revoke || exit 1
p mcp && p backup-restore && p wrong-key && p lost-passkey || exit 1
