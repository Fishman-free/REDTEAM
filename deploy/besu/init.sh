#!/bin/sh
# Generate a single-validator QBFT genesis + key inside the shared Docker volume.
# Runs in the Besu 24.5.1 operator image; the runtime image is 25.10.0.
set -eu

SHARED=/shared
TEMPLATE=/template/genesis.json

mkdir -p "$SHARED/networkFiles" "$SHARED/keydir" "$SHARED/data"

if [ ! -f "$SHARED/networkFiles/genesis.json" ]; then
  echo "[besu-init] generating QBFT genesis and validator key"
  cat > "$SHARED/qbftConfig.json" <<EOF
{
  "genesis": $(cat "$TEMPLATE"),
  "blockchain": {
    "nodes": {
      "generate": true,
      "count": 1
    }
  }
}
EOF

  besu operator generate-blockchain-config \
    --config-file="$SHARED/qbftConfig.json" \
    --to="$SHARED/networkFiles" \
    --private-key-file-name=key

  set -- "$SHARED"/networkFiles/keys/*/
  if [ "$#" -ne 1 ] || [ ! -d "${1:-}" ]; then
    echo "[besu-init] expected exactly one generated validator key" >&2
    exit 1
  fi
  VALIDATOR_DIR="${1%/}"
  cp "$VALIDATOR_DIR/key" "$SHARED/keydir/key"
  cp "$VALIDATOR_DIR/key.pub" "$SHARED/keydir/key.pub"
  basename "$VALIDATOR_DIR" > "$SHARED/keydir/address"
  chmod 600 "$SHARED/keydir/key" 2>/dev/null || true
else
  echo "[besu-init] existing genesis/key found; keeping them"
fi

if [ ! -f "$SHARED/keydir/key" ]; then
  echo "[besu-init] keydir/key is missing" >&2
  exit 1
fi

# The Besu image entrypoint drops to uid/gid 1000 (besu). Docker named volumes
# are root-owned, so make the generated key/genesis readable by that user.
chown -R 1000:1000 "$SHARED/keydir" "$SHARED/networkFiles" 2>/dev/null || true
chmod 755 "$SHARED/keydir" "$SHARED/networkFiles" 2>/dev/null || true
chmod 600 "$SHARED/keydir/key" 2>/dev/null || true
chmod 644 "$SHARED/keydir/key.pub" "$SHARED/keydir/address" 2>/dev/null || true
chown -R 1000:1000 "$SHARED/data" 2>/dev/null || true

cat > "$SHARED/config.toml" <<'EOF'
data-path="/shared/data"
genesis-file="/shared/networkFiles/genesis.json"
node-private-key-file="/shared/keydir/key"
rpc-http-enabled=true
rpc-http-host="0.0.0.0"
rpc-http-port=8545
min-gas-price=0
tx-pool-enable-balance-check=false
EOF

echo "[besu-init] validator address: $(cat "$SHARED/keydir/address")"
echo "[besu-init] done"
