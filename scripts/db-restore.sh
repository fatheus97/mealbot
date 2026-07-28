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
# To restore OVER the live database, target the literal word `live` AND confirm:
#
#     TARGET_DB=live I_UNDERSTAND=yes ./scripts/db-restore.sh <dump>
#
# NOT `TARGET_DB="$POSTGRES_DB"`: that variable lives in .env, which compose
# reads but never exports, so in your shell it expands to the EMPTY STRING —
# which used to fall through to the scratch default and cheerfully report
# "rehearsal passed" in the middle of an outage. `live` is resolved from the
# running container instead, so it cannot silently mean something else.
#
# Everything written since the dump is lost. The previous live database is
# RENAMED aside (not dropped), so a bad restore is still reversible. Stop the
# backend first so it cannot write mid-restore:
#
#     docker compose -f docker-compose.yml -f docker-compose.prod.yml stop backend

set -euo pipefail

COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"
BACKUP_DIR="${BACKUP_DIR:-/opt/mealbot/backups}"
# Scratch by default. Only an explicit TARGET_DB can point this at anything else.
# `${TARGET_DB-…}` (no colon) so an explicitly EMPTY value is an error rather
# than silently becoming the scratch default — the empty case is exactly what
# `TARGET_DB="$POSTGRES_DB"` produces in an operator shell.
TARGET_DB="${TARGET_DB-mealbot_restore_check}"
[ -n "$TARGET_DB" ] || { echo "db-restore: TARGET_DB is empty — did you mean TARGET_DB=live?" >&2; exit 1; }
# The name is interpolated into a psql -c string, so constrain it to a plain
# identifier. Also closes the injection route through that interpolation.
case "$TARGET_DB" in
  [a-zA-Z_][a-zA-Z0-9_]*) ;;
  *) echo "db-restore: invalid TARGET_DB '$TARGET_DB'" >&2; exit 1 ;;
esac
# Dropping a shared/maintenance database would break the whole cluster, not just
# mealbot. No legitimate restore ever targets these.
case "$TARGET_DB" in
  postgres|template0|template1)
    echo "db-restore: refusing to target the cluster database '$TARGET_DB'" >&2; exit 1 ;;
esac
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
# An empty answer means the container didn't tell us the live name. Refuse: every
# safety decision below is a comparison against it, and comparing against "" would
# make the live database look like just another target.
[ -n "$live_db" ] || { echo "db-restore: could not read the live database name — refusing" >&2; exit 1; }

# `live` is the only spelling that resolves to production. An `if` (not
# `[ … ] && …`) because under `set -e` a false test as the last command of an
# AND-list would abort the script.
if [ "$TARGET_DB" = live ]; then
  TARGET_DB="$live_db"
  # Re-check the denylist AFTER resolution: the earlier check saw the literal
  # "live", so a cluster running with POSTGRES_DB=postgres would otherwise walk
  # straight past it and rename the maintenance database aside.
  case "$TARGET_DB" in
    postgres|template0|template1)
      echo "db-restore: live database is '$TARGET_DB' — refusing to touch a cluster database" >&2
      exit 1 ;;
  esac
fi

if [ "$TARGET_DB" = "$live_db" ]; then
  if [ "${I_UNDERSTAND:-}" != "yes" ]; then
    echo "db-restore: REFUSING to overwrite the live database '$live_db'." >&2
    echo "db-restore: re-run with I_UNDERSTAND=yes if that is genuinely what you want." >&2
    exit 1
  fi
  echo "db-restore: ***** OVERWRITING LIVE DATABASE '$live_db' *****"
  KEEP_SCRATCH=yes
  # Rename the live database aside instead of dropping it. The DROP below then
  # finds nothing, and if the restore turns out bad the pre-restore state is
  # still on disk to rename back — the difference between a recoverable mistake
  # and an unrecoverable one. Costs no disk and no time (it is a catalog
  # update), and needs no open connections, which is the same precondition
  # DROP DATABASE already had.
  prev="${live_db}_pre_$(date -u +%Y%m%d%H%M%S)"
  # shellcheck disable=SC2086
  docker compose $COMPOSE_FILES exec -T db \
    sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -v ON_ERROR_STOP=1 \
             -c 'ALTER DATABASE \"$live_db\" RENAME TO \"$prev\"'"
  echo "db-restore: previous live database kept as '$prev'"
  echo "db-restore: reclaim it later with: DROP DATABASE \"$prev\""
fi

echo "db-restore: restoring $dump -> $TARGET_DB"

# Recreate the target so the restore lands in a known-empty database. pg_restore
# without this can half-succeed against existing objects and report success.
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T db \
  sh -c "psql -U \"\$POSTGRES_USER\" -d postgres -v ON_ERROR_STOP=1 \
           -c 'DROP DATABASE IF EXISTS \"$TARGET_DB\"' \
           -c 'CREATE DATABASE \"$TARGET_DB\"'"

# --no-owner/--no-privileges match how the dump was taken. --exit-on-error so a
# partial restore fails the script instead of being papered over by one row
# count: the target was created EMPTY a moment ago, so nothing legitimate can
# collide and there is no "benign already-exists noise" to tolerate. `set -e`
# aborts here on any restore error.
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T db \
  sh -c "pg_restore -U \"\$POSTGRES_USER\" -d \"$TARGET_DB\" --no-owner --no-privileges --exit-on-error" \
  < "$dump"

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
