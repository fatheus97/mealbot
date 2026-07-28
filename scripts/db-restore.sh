#!/usr/bin/env bash
#
# mealbot — restore a dump produced by scripts/db-backup.sh.
#
# Default target is a SCRATCH database, not the live one. That is the point:
# the routine use of this script is the periodic rehearsal that proves the
# backups are real, and a rehearsal must not be able to destroy production.
#
#     ./scripts/db-restore.sh                              # newest dump -> scratch db, verify, drop
#     ./scripts/db-restore.sh backups/mealbot-....dump     # a specific dump
#
# ─── Real recovery (destructive) ─────────────────────────────────────────────
# To restore OVER the live database you must name it explicitly AND confirm:
#
#     TARGET_DB="$POSTGRES_DB" I_UNDERSTAND=yes ./scripts/db-restore.sh <dump>
#
# That path DROPS AND RECREATES the live database. Everything written since the
# dump is lost. Stop the backend first so it cannot write mid-restore:
#
#     docker compose -f docker-compose.yml -f docker-compose.prod.yml stop backend

set -euo pipefail

COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-/opt/mealbot/backups}"
# Scratch by default. Only an explicit TARGET_DB can point this at anything else.
TARGET_DB="${TARGET_DB:-mealbot_restore_check}"
KEEP_SCRATCH="${KEEP_SCRATCH:-no}"

dump="${1:-}"
if [ -z "$dump" ]; then
  # Newest by name — the timestamp format is lexicographically sortable, and
  # .partial files are excluded so a killed run is never picked up.
  dump=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'mealbot-*.dump' | sort | tail -1)
fi
if [ -z "$dump" ] || [ ! -s "$dump" ]; then
  echo "db-restore: no usable dump found (looked in $BACKUP_DIR)" >&2
  exit 1
fi

# shellcheck disable=SC2086
live_db=$(docker compose $COMPOSE_FILES exec -T db sh -c 'printf %s "$POSTGRES_DB"')

if [ "$TARGET_DB" = "$live_db" ]; then
  if [ "${I_UNDERSTAND:-}" != "yes" ]; then
    echo "db-restore: REFUSING to overwrite the live database '$live_db'." >&2
    echo "db-restore: re-run with I_UNDERSTAND=yes if that is genuinely what you want." >&2
    exit 1
  fi
  echo "db-restore: ***** OVERWRITING LIVE DATABASE '$live_db' *****"
  KEEP_SCRATCH=yes
fi

echo "db-restore: restoring $dump -> $TARGET_DB"

# Recreate the target so the restore lands in a known-empty database. pg_restore
# without this can half-succeed against existing objects and report success.
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T db \
  sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -v ON_ERROR_STOP=1 \
           -c 'DROP DATABASE IF EXISTS \"$TARGET_DB\"' \
           -c 'CREATE DATABASE \"$TARGET_DB\"'"

# --no-owner/--no-privileges match how the dump was taken. Not --exit-on-error:
# pgvector extension objects can emit benign "already exists" noise, so the
# real success check is the row count below, not pg_restore's exit code.
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T db \
  sh -c "pg_restore -U \"\$POSTGRES_USER\" -d \"$TARGET_DB\" --no-owner --no-privileges" \
  < "$dump" || echo "db-restore: pg_restore reported warnings (checking content anyway)"

# The actual proof. A restore that produces an empty schema is a failed restore
# no matter what pg_restore's exit code said. `user` is quoted because it is a
# reserved word, and it is the table whose loss would end the business.
# shellcheck disable=SC2086
users=$(docker compose $COMPOSE_FILES exec -T db \
  sh -c "psql -U \"\$POSTGRES_USER\" -d \"$TARGET_DB\" -tAc 'SELECT count(*) FROM \"user\"'")
# shellcheck disable=SC2086
sales=$(docker compose $COMPOSE_FILES exec -T db \
  sh -c "psql -U \"\$POSTGRES_USER\" -d \"$TARGET_DB\" -tAc 'SELECT count(*) FROM salerecord'")

echo "db-restore: restored $users user row(s), $sales salerecord row(s)"

if [ "$users" -eq 0 ]; then
  echo "db-restore: FAILED — restored database has no users" >&2
  exit 1
fi

if [ "$KEEP_SCRATCH" = "yes" ]; then
  echo "db-restore: leaving '$TARGET_DB' in place"
else
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES exec -T db \
    sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -c 'DROP DATABASE IF EXISTS \"$TARGET_DB\"'" \
    > /dev/null
  echo "db-restore: scratch database dropped — rehearsal passed"
fi
