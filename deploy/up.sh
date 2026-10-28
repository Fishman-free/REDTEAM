#!/usr/bin/env bash
# One-command RTM Arena stack: Besu + contracts + API + web BFF + demo model.
set -euo pipefail
cd "$(dirname "$0")"

log() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker is required"
docker info >/dev/null 2>&1 || die "Docker daemon is not running; start Docker Desktop/engine first"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  die "docker compose (v2) or docker-compose is required"
fi

gen_hex() {
  local bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  else
    head -c "$bytes" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

if [ ! -f .env.stack ]; then
  umask 077
  log "Generating deploy/.env.stack (secrets are not printed)"
  cat > .env.stack <<EOF
PLATFORM_MASTER_KEY=$(gen_hex 32)
PLATFORM_API_TOKEN=$(gen_hex 24)
PLATFORM_ADMIN_KEY=$(gen_hex 24)
PLATFORM_MODEL_KEY=demo-key
FAUCET_CAPTCHA_REQUIRED=false
BESU_RPC_PORT=8546
API_PORT=8080
WEB_PORT=3000
EOF
fi

log "Building and starting the stack..."
"${COMPOSE[@]}" --env-file .env.stack -f docker-compose.yml up -d --build

log ""
log "Stack started."
log "  dApp:      http://localhost:$(grep '^WEB_PORT=' .env.stack | cut -d= -f2-)"
log "  Ops gate:   http://localhost:$(grep '^WEB_PORT=' .env.stack | cut -d= -f2-)/ops"
log "  Admin key: deploy/.env.stack (PLATFORM_ADMIN_KEY)"
log "  API health: http://127.0.0.1:$(grep '^API_PORT=' .env.stack | cut -d= -f2-)/health"
log "  RPC (host): http://127.0.0.1:$(grep '^BESU_RPC_PORT=' .env.stack | cut -d= -f2-)"
log ""
log "The included local-mock model is a deliberately vulnerable demo agent."
log "For a real model, edit MODEL_ALLOWLIST_JSON / PLATFORM_MODEL_PROVIDER in deploy/docker-compose.yml."
log "Logs: ${COMPOSE[*]} --env-file .env.stack -f docker-compose.yml logs -f"
