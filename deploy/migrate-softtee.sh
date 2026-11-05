#!/usr/bin/env bash
# Deploy the SoftTEE BYOA contracts on an already-running stack.
#
# This is a migration, not a chain reset. It deploys a new Arena/TaskSink/
# RTMToken/DataMarket/Treasury/Faucet set on the same Besu chain, backs up the
# previous address registry, and switches the API/web to the new registry.
# Existing contests remain on the old contracts but are no longer served by
# the new Arena. Back up the rtm-platform-data volume before running.
set -euo pipefail
cd "$(dirname "$0")/.."

log() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is required"
docker info >/dev/null 2>&1 || die "Docker daemon is not running"
[ -f deploy/.env.stack ] || die "deploy/.env.stack is missing; run deploy/up.sh first"

COMPOSE=(docker compose --env-file deploy/.env.stack -f deploy/docker-compose.yml)

# Add a SoftTEE keystore root without printing it. The API container reads it
# through env_file; rotating it makes old SoftTEE keystores undecryptable.
if ! grep -q '^PLATFORM_SOFTTEE_HOST_SECRET=' deploy/.env.stack; then
  secret=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
  printf 'PLATFORM_SOFTTEE_HOST_SECRET=%s\n' "$secret" >> deploy/.env.stack
  log "added PLATFORM_SOFTTEE_HOST_SECRET to deploy/.env.stack"
fi

log "1/5 building contracts, api and web images"
"${COMPOSE[@]}" build contracts api web

log "2/5 backing up the current registry"
"${COMPOSE[@]}" run --rm --no-deps --entrypoint /bin/sh contracts -c '
set -eu
if [ -f /registry/addresses.json ]; then
  cp /registry/addresses.json /registry/addresses.pre-softtee.json
  echo "backup: /registry/addresses.pre-softtee.json"
else
  echo "no previous registry"
fi
' || die "registry backup failed"

log "3/5 deploying the new contract set on the existing chain"
"${COMPOSE[@]}" run --rm --no-deps --entrypoint /bin/sh contracts -c '
set -eu
node /app/wait-for-rpc.mjs http://besu:8545
export BESU_TESTNET_RPC=http://besu:8545
export BESU_TESTNET_KEY="$(tr -d "\r\n" < /shared/keydir/key)"
export DEPLOY_ALLOW_REDEPLOY=1
export RUN_MINING_SMOKE=0
npx hardhat run deploy/deploy-testnet.js --network besu-testnet
cp deploy/addresses.json /registry/addresses.json
cp -R artifacts/. /artifacts/
echo "registry switched"
'

log "4/5 recreating api, web and mock-model"
"${COMPOSE[@]}" up -d --force-recreate api web mock-model

log "5/5 waiting for health and verifying metadata"
API_PORT=$(grep '^API_PORT=' deploy/.env.stack | cut -d= -f2)
deadline=$((SECONDS + 90))
while [ "$SECONDS" -lt "$deadline" ]; do
  if curl -fsS "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
curl -fsS "http://127.0.0.1:${API_PORT}/meta" > /tmp/rtm-meta-softtee.json
python3 - <<'PY' || die "metadata verification failed"
import json
meta = json.load(open("/tmp/rtm-meta-softtee.json", encoding="utf-8"))
addr = meta.get("addresses", {})
tiers = meta.get("byoa", {}).get("attestationTiers", [])
print("arena", addr.get("arena"))
print("taskSink", addr.get("taskSink"))
print("tiers", tiers)
if "softtee" not in tiers:
    raise SystemExit("softtee tier is not enabled; check PLATFORM_SOFTTEE_HOST_SECRET")
if not addr.get("taskSink"):
    raise SystemExit("taskSink is missing from /api/meta")
PY

log ""
log "SoftTEE migration complete."
log "  New registry: docker volume rtm-arena_rtm-registry/addresses.json"
log "  Backup:       docker volume rtm-arena_rtm-registry/addresses.pre-softtee.json"
log "  Old contests remain on the previous contracts and are not migrated."
log "  Rebuild web only: ${COMPOSE[*]} up -d --build web"
