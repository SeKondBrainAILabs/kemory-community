#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
INFRA_DIR="${SHARED_INFRA_DIR:-$HOME/infra}"
ENV_FILE="${1:-$ROOT_DIR/.env.shared}"
APP_NAME="kemory_community"

die() {
  echo "kemory-community shared infra: $*" >&2
  exit 1
}

read_existing() {
  local key="$1"
  if [[ -f "$ENV_FILE" ]]; then
    sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
  fi
}

[[ -x "$INFRA_DIR/scripts/start.sh" ]] || die "missing $INFRA_DIR/scripts/start.sh"
[[ -x "$INFRA_DIR/scripts/create-app-db.sh" ]] || die "missing $INFRA_DIR/scripts/create-app-db.sh"
[[ -f "$INFRA_DIR/.env" ]] || die "missing $INFRA_DIR/.env"

"$INFRA_DIR/scripts/start.sh"
"$INFRA_DIR/scripts/create-app-db.sh" "$APP_NAME"

# shellcheck disable=SC1090
set -a
source "$INFRA_DIR/.env"
set +a

ADMIN_USER="${POSTGRES_USER:-admin}"
ADMIN_PASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is missing from shared infra .env}"
DB_PASSWORD="$(printf '%s' "${APP_NAME}:${ADMIN_PASSWORD}" | shasum -a 256 | awk '{print $1}' | head -c 32)"

docker exec postgres psql -U "$ADMIN_USER" -d "$APP_NAME" -v ON_ERROR_STOP=1 -c \
  'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;'

API_KEY="$(read_existing KEMORY_LOCAL_API_KEY)"
BLOB_KEY="$(read_existing KEMORY_LOCAL_BLOB_SIGNING_KEY)"
OPENAI_KEY="$(read_existing OPENAI_API_KEY)"
VOYAGE_KEY="$(read_existing VOYAGE_API_KEY)"
COHERE_KEY="$(read_existing COHERE_API_KEY)"
[[ -n "$API_KEY" ]] || API_KEY="kc_$(openssl rand -hex 24)"
[[ -n "$BLOB_KEY" ]] || BLOB_KEY="$(openssl rand -hex 32)"

mkdir -p "$(dirname "$ENV_FILE")"
TMP_FILE="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
trap 'rm -f "$TMP_FILE"' EXIT
cat >"$TMP_FILE" <<EOF
KEMORY_COMMUNITY_API_PORT=8111
KEMORY_COMMUNITY_DASHBOARD_PORT=5175
KEMORY_COMMUNITY_DB_NAME=$APP_NAME
KEMORY_COMMUNITY_DB_USER=$APP_NAME
KEMORY_COMMUNITY_DB_PASSWORD=$DB_PASSWORD
KEMORY_COMMUNITY_REDIS_DB=14
KEMORY_LOCAL_API_KEY=$API_KEY
KEMORY_LOCAL_BLOB_SIGNING_KEY=$BLOB_KEY
OPENAI_API_KEY=$OPENAI_KEY
VOYAGE_API_KEY=$VOYAGE_KEY
COHERE_API_KEY=$COHERE_KEY
EOF
chmod 600 "$TMP_FILE"
mv "$TMP_FILE" "$ENV_FILE"
trap - EXIT

echo "Shared infrastructure provisioned for Kemory Community."
echo "Environment: $ENV_FILE"
echo "Start: docker compose --env-file $ENV_FILE -f $ROOT_DIR/docker-compose.shared.yml up -d --build"
