#!/usr/bin/env bash
# Generate a single-validator QBFT genesis and validator key for the RTM testnet.
set -euo pipefail
cd "$(dirname "$0")"

BESU_IMAGE="${BESU_IMAGE:-hyperledger/besu:24.5.1}"
NETWORK_FILES="networkFiles"
KEY_DIR="keydir"

log() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not found; install/start Docker Desktop"
docker info >/dev/null 2>&1 || die "Docker daemon is not available; start Docker Desktop and retry"

if [ -e "$NETWORK_FILES" ] || [ -e "$KEY_DIR" ]; then
  cat >&2 <<EOF
error: $NETWORK_FILES/ or $KEY_DIR/ already exists.

Refusing to overwrite the existing validator identity/genesis. Back them up,
then remove both directories and re-run generate.sh:

  rm -rf "$NETWORK_FILES" "$KEY_DIR"

If a node already used the old genesis, also delete data/ so the chain starts
from the regenerated genesis:

  rm -rf data
EOF
  exit 1
fi

[ -f genesis.json ] || die "genesis.json not found"

# Wrap the source genesis template into the operator's config without jq.
# The generated networkFiles/genesis.json is the one that carries extraData;
# the source genesis.json intentionally stays free of extraData.
cat > qbftConfig.json <<EOF
{
  "genesis": $(cat genesis.json),
  "blockchain": {
    "nodes": {
      "generate": true,
      "count": 1
    }
  }
}
EOF

# Docker Desktop on Windows requires a Windows-style host path for bind mounts.
# Git Bash provides pwd -W; Linux/macOS fall back to plain pwd.
HOST_DIR="$(pwd -W 2>/dev/null || pwd)"

log "Generating QBFT genesis + 1 validator key with $BESU_IMAGE ..."
# MSYS_NO_PATHCONV keeps the in-container /work paths intact under Git Bash.
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "${HOST_DIR}:/work" \
  "$BESU_IMAGE" \
  operator generate-blockchain-config \
  --config-file=/work/qbftConfig.json \
  --to=/work/networkFiles \
  --private-key-file-name=key

[ -f "$NETWORK_FILES/genesis.json" ] \
  || die "generated $NETWORK_FILES/genesis.json not found"
grep -Eq '"extraData"[[:space:]]*:[[:space:]]*"0x[0-9a-fA-F]+"' "$NETWORK_FILES/genesis.json" \
  || die "generated genesis has no non-empty extraData"

mapfile -t KEY_DIRS < <(find "$NETWORK_FILES/keys" -mindepth 1 -maxdepth 1 -type d)
[ "${#KEY_DIRS[@]}" -eq 1 ] \
  || die "expected exactly 1 generated validator key directory, found ${#KEY_DIRS[@]}"

VALIDATOR_DIR="${KEY_DIRS[0]}"
VALIDATOR_ADDRESS="$(basename "$VALIDATOR_DIR")"

mkdir -p "$KEY_DIR"
cp "$VALIDATOR_DIR/key" "$KEY_DIR/key"
cp "$VALIDATOR_DIR/key.pub" "$KEY_DIR/key.pub"
printf '%s\n' "$VALIDATOR_ADDRESS" > "$KEY_DIR/address"
chmod 600 "$KEY_DIR/key" 2>/dev/null || true

log ""
log "Done."
log "  generated genesis: $NETWORK_FILES/genesis.json (extraData set)"
log "  validator key:     $KEY_DIR/key (secret; testnet only, never commit)"
log "  validator address: $VALIDATOR_ADDRESS"
log ""
log "Next:"
log "  docker compose up -d"
log "  curl -s -X POST -H 'Content-Type: application/json' \\"
log "    --data '{\"jsonrpc\":\"2.0\",\"method\":\"eth_chainId\",\"params\":[],\"id\":1}' \\"
log "    http://127.0.0.1:8545"
