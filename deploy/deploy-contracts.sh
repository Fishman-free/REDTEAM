#!/bin/sh
# Deploy the five contracts once and publish artifacts/addresses to volumes.
set -eu

mkdir -p /registry /artifacts

if [ -f /registry/addresses.json ]; then
  echo "[contracts] registry already exists; skipping deployment"
  node /app/wait-for-rpc.mjs http://besu:8545
  node /app/check-registry.mjs /registry/addresses.json http://besu:8545
else
  node /app/wait-for-rpc.mjs http://besu:8545
  export BESU_TESTNET_RPC=http://besu:8545
  export BESU_TESTNET_KEY="$(tr -d '\r\n' < /shared/keydir/key)"
  export DEPLOY_ALLOW_REDEPLOY=1
  npx hardhat run deploy/deploy-testnet.js --network besu-testnet
  cp deploy/addresses.json /registry/addresses.json
  echo "[contracts] registry written"
fi

cp -R artifacts/. /artifacts/
echo "[contracts] artifacts published"
