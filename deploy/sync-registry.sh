#!/usr/bin/env bash
# Copy the running stack's registry to contracts/deploy/addresses.json.
#
# The stack itself only reads the rtm-registry volume (/registry/addresses.json,
# also served by /api/meta). This host copy is for local tools and tests
# (platform load_settings() defaults, Hardhat scripts). It is gitignored:
# addresses differ per machine because up.sh deploys with a fresh key.
set -euo pipefail
cd "$(dirname "$0")"
# Git Bash would otherwise rewrite /registry/... into a Windows path.
export MSYS_NO_PATHCONV=1

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi

port=$(grep '^BESU_RPC_PORT=' .env.stack | cut -d= -f2- || true)
host_rpc="http://127.0.0.1:${port:-8546}"
target=../contracts/deploy/addresses.json
tmp="$target.tmp"

"${COMPOSE[@]}" --env-file .env.stack -f docker-compose.yml exec -T \
  -e HOST_RPC="$host_rpc" api python -c '
import json, os
with open("/registry/addresses.json", encoding="utf-8") as handle:
    data = json.load(handle)
data["rpc"] = os.environ["HOST_RPC"]
print(json.dumps(data, indent=2))
' > "$tmp"
mv "$tmp" "$target"
printf 'synced contracts/deploy/addresses.json from the running stack (rpc=%s)\n' "$host_rpc"
