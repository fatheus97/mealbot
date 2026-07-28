#!/usr/bin/env bash
#
# mealbot — nightly Postgres dump.
#
# Run by mealbot-db-backup.service (systemd timer). Safe to run by hand:
#
#     cd /opt/mealbot && ./scripts/db-backup.sh
#
# Writes ONE file per run to $BACKUP_DIR and prunes anything older than
# $BACKUP_RETENTION_DAYS. Restore with scripts/db-restore.sh.
#
# ─── What this protects against, and what it does NOT ────────────────────────
# This is a LOCAL dump on the same box (and the same disk) as the database, so
# it covers the losses that actually happen day to day: a bad migration, an
# accidental DELETE, a botched admin action, a corrupted table. It does NOT
# cover losing the box or the disk.
#
# ponytail: local-only. Off-box copy is the obvious upgrade and needs a
# destination decision + credentials (Hetzner Storage Box over rsync/sftp is the
# cheap fit). Until then, check that VM snapshots are enabled in the Hetzner
# console — a snapshot is crash-consistent rather than a clean dump, but it is
# the difference between "lost a day" and "lost the company".
#
# The `SaleRecord` VAT/OSS ledger is the reason this is not optional: it is
# deliberately `ondelete=SET NULL` so it survives user deletion, it is legally
# required to be retained, and nothing else in the system can reproduce it.

set -euo pipefail

# pg_dump runs inside the db container and its exit status arrives through a
# pipe; without pipefail a dump that dies mid-stream still exits 0 and we would
# happily publish a truncated file as a good backup.
BACKUP_DIR="${BACKUP_DIR:-/opt/mealbot/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"

mkdir -p "$BACKUP_DIR"

stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
final="$BACKUP_DIR/mealbot-$stamp.dump"
# Write to a .partial name first and rename only after pg_dump succeeds AND the
# archive verifies. A crash, a full disk or a killed container therefore leaves
# a .partial file that the restore script ignores and the prune sweeps up —
# never a half-written file sitting in the directory looking like a backup.
partial="$final.partial"

cleanup() { rm -f "$partial"; }
trap cleanup EXIT

echo "db-backup: dumping to $final"

# --format=custom, not plain SQL: it is already compressed (so no gzip in the
# pipeline), and it is what pg_restore needs for selective/parallel restore.
# Credentials are read from the container's own environment rather than being
# passed in, so they never appear in the process list or the journal.
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-privileges' \
  > "$partial"

if [ ! -s "$partial" ]; then
  echo "db-backup: FAILED — dump is empty" >&2
  exit 1
fi

# Verify before publishing. `pg_restore --list` parses the archive's table of
# contents, so it fails on a truncated or corrupt custom-format file. A backup
# that has never been read is a guess, not a backup.
# shellcheck disable=SC2086
if ! docker compose $COMPOSE_FILES exec -T db pg_restore --list < "$partial" > /dev/null; then
  echo "db-backup: FAILED — archive did not verify" >&2
  exit 1
fi

mv "$partial" "$final"
trap - EXIT

echo "db-backup: wrote $(du -h "$final" | cut -f1) to $final"

# Prune old dumps AND any stale .partial files from previously killed runs.
# Retention is what keeps this job from being the thing that fills the disk.
deleted=$(find "$BACKUP_DIR" -maxdepth 1 -type f \
  \( -name 'mealbot-*.dump' -o -name 'mealbot-*.dump.partial' \) \
  -mtime "+$BACKUP_RETENTION_DAYS" -print -delete | wc -l)
echo "db-backup: pruned $deleted file(s) older than ${BACKUP_RETENTION_DAYS}d"

remaining=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'mealbot-*.dump' | wc -l)
echo "db-backup: $remaining dump(s) retained in $BACKUP_DIR"
