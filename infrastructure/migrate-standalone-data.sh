#!/usr/bin/env bash
set -euo pipefail

INFRA_DIR="${SHARED_INFRA_DIR:-$HOME/infra}"
SOURCE_CONTAINER="${KEMORY_STANDALONE_POSTGRES_CONTAINER:-kemory-community-postgres-1}"
SOURCE_DATABASE="${KEMORY_STANDALONE_DATABASE:-kora_vault}"
SOURCE_USER="${KEMORY_STANDALONE_DATABASE_USER:-kora}"
TARGET_CONTAINER="${KEMORY_SHARED_POSTGRES_CONTAINER:-postgres}"
TARGET_DATABASE="${KEMORY_COMMUNITY_DB_NAME:-kemory_community}"
TARGET_USER="${KEMORY_COMMUNITY_DB_USER:-kemory_community}"

die() {
  echo "kemory-community database migration: $*" >&2
  exit 1
}

[[ -f "$INFRA_DIR/.env" ]] || die "missing $INFRA_DIR/.env"
# shellcheck disable=SC1090
set -a
source "$INFRA_DIR/.env"
set +a
ADMIN_USER="${POSTGRES_USER:-admin}"

docker inspect "$SOURCE_CONTAINER" >/dev/null 2>&1 || die "source container $SOURCE_CONTAINER is not running"
docker inspect "$TARGET_CONTAINER" >/dev/null 2>&1 || die "target container $TARGET_CONTAINER is not running"

TARGET_TABLES="$(
  docker exec "$TARGET_CONTAINER" psql -U "$ADMIN_USER" -d "$TARGET_DATABASE" -Atc \
    "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
)"
[[ "$TARGET_TABLES" == "0" ]] || die "target $TARGET_DATABASE already has $TARGET_TABLES public tables; refusing to overwrite"

DUMP_FILE="$(mktemp /tmp/kemory-community.XXXXXX.sql)"
SOURCE_MANIFEST="$(mktemp /tmp/kemory-community-source.XXXXXX.rows)"
TARGET_MANIFEST="$(mktemp /tmp/kemory-community-target.XXXXXX.rows)"
trap 'rm -f "$DUMP_FILE" "$SOURCE_MANIFEST" "$TARGET_MANIFEST"' EXIT

docker exec "$SOURCE_CONTAINER" pg_dump \
  -U "$SOURCE_USER" -d "$SOURCE_DATABASE" --format=plain --no-owner --no-privileges \
  --exclude-extension=vector --exclude-extension=pg_trgm >"$DUMP_FILE"
docker cp "$DUMP_FILE" "$TARGET_CONTAINER:/tmp/kemory-community.sql"
docker exec "$TARGET_CONTAINER" psql \
  -U "$TARGET_USER" -d "$TARGET_DATABASE" -v ON_ERROR_STOP=1 \
  -f /tmp/kemory-community.sql
docker exec "$TARGET_CONTAINER" rm -f /tmp/kemory-community.sql

write_row_manifest() {
  local container="$1"
  local user="$2"
  local database="$3"
  local output="$4"
  local table
  local tables

  tables="$(
    docker exec "$container" psql -U "$user" -d "$database" -Atc \
      "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
  )"
  while IFS= read -r table; do
    [[ -n "$table" ]] || continue
    printf '%s\t' "$table" >>"$output"
    docker exec "$container" psql -U "$user" -d "$database" -v table="$table" -Atc \
      'SELECT count(*) FROM public.:"table"' >>"$output"
  done <<<"$tables"
}

write_row_manifest "$SOURCE_CONTAINER" "$SOURCE_USER" "$SOURCE_DATABASE" "$SOURCE_MANIFEST"
write_row_manifest "$TARGET_CONTAINER" "$TARGET_USER" "$TARGET_DATABASE" "$TARGET_MANIFEST"
if ! cmp -s "$SOURCE_MANIFEST" "$TARGET_MANIFEST"; then
  diff -u "$SOURCE_MANIFEST" "$TARGET_MANIFEST" >&2 || true
  die "source and target table row counts differ"
fi

TABLE_COUNT="$(wc -l <"$TARGET_MANIFEST" | tr -d ' ')"
MEMORY_ROWS="$(awk -F '\t' '$1 == "kemory_memories" { print $2 }' "$TARGET_MANIFEST")"
MEMORY_ROWS="${MEMORY_ROWS:-0}"

echo "Migrated $TABLE_COUNT tables and $MEMORY_ROWS memories from $SOURCE_CONTAINER to shared PostgreSQL."
echo "The source database and its Docker volume were not modified."
