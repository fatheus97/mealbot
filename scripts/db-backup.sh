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
# The off-box copy is scripts/offsite-backup.sh (encrypted, to Backblaze B2),
# run by mealbot-offsite-backup.timer half an hour after this one. It SHIPS
# PARKED — see deploy/systemd/README.md §6 — so until it is switched on, this
# local dump is still the only copy on its own. Hetzner's server backups (seven
# daily copies of the whole disk, these dumps included) are the copy that
# survives a lost disk; the owner switches them on in the Hetzner console. The
# retention below is sized for them.
#
# The `SaleRecord` VAT/OSS ledger is the reason this is not optional: it is
# deliberately `ondelete=SET NULL` so it survives user deletion, it is legally
# required to be retained, and nothing else in the system can reproduce it.

set -euo pipefail

# `set -e` is what catches a failed dump: the pg_dump call is a redirect, not a
# pipe, so its exit status is the command's own and aborts before the rename.
# `pipefail` matters only for the piped helpers further down.
BACKUP_DIR="${BACKUP_DIR:-/opt/mealbot/backups}"
# The privacy policy promises a deleted account is out of every backup within
# 14 days (frontend/privacy.html and frontend/cs/privacy.html, the retention
# table and the deletion section; auth.deleteAccount.pointBackups in the
# delete dialog). Worst case for a
# deletion during day 0: the 02:30 dump of day 0 holds the account;
# `-mtime +N` deletes a file once it is N+1 whole days old, and the timer's
# jitter can push that one more night, so the dump is gone by day N+2. A
# Hetzner disk backup taken on day N+1 still holds it, and Hetzner keeps seven
# daily backups, so the last copy goes by day N+9. N=5 gives day 14. Raising
# this breaks the promise while Hetzner backups are on: change the policy first.
# The parked off-site copy has its own knob, OFFSITE_RETENTION_DAYS in
# offsite-backup.sh, held to the same 14 days by a guard there.
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-5}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"

mkdir -p "$BACKUP_DIR"

# Prune BEFORE dumping, not after. `set -e` means a failed dump aborts the
# script, so a retention sweep placed at the end never runs on exactly the
# nights that repeat — and a week of failures would then accumulate old dumps
# while never writing a new one.
deleted=$(find "$BACKUP_DIR" -maxdepth 1 -type f \
  \( -name 'mealbot-*.dump' -o -name 'mealbot-*.dump.partial' \) \
  -mtime "+$BACKUP_RETENTION_DAYS" -print -delete | wc -l)
echo "db-backup: pruned $deleted file(s) older than ${BACKUP_RETENTION_DAYS}d"

# Refuse rather than fill the disk Postgres itself lives on — this box has
# already had one disk-full outage. Failing here fires OnFailure=, so the
# operator gets mail instead of a wedged database. `|| true` because pipefail is
# set and an unmatched glob (the very first run) would otherwise abort.
avail=$(df -Pk "$BACKUP_DIR" | awk 'NR==2{print $4}')
biggest=$(du -sk "$BACKUP_DIR"/mealbot-*.dump 2>/dev/null | sort -n | tail -1 | cut -f1 || true)
if [ -n "$biggest" ] && [ "$avail" -lt $((biggest * 3)) ]; then
  echo "db-backup: FAILED — less than 3x the largest dump free in $BACKUP_DIR" >&2
  exit 1
fi

stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
final="$BACKUP_DIR/mealbot-$stamp.dump"
# Write to a .partial name first and rename only after pg_dump succeeds AND the
# archive verifies. A crash, a full disk or a killed container therefore leaves
# a .partial file that the restore script ignores and the prune sweeps up —
# never a half-written file sitting in the directory looking like a backup.
partial="$final.partial"

cleanup() { rm -f "$partial"; }
# TERM/INT as well as EXIT: systemd sends SIGTERM on TimeoutStartSec, and bash's
# default disposition kills the shell WITHOUT running an EXIT trap — which would
# strand a full-size .partial on the disk until retention swept it days later.
trap cleanup EXIT TERM INT

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

# Verify before publishing. `pg_restore --list` parses the archive header and
# table of contents, so it rejects a file that is empty, truncated at the FRONT,
# or not a custom-format archive at all.
#
# Its limit, stated honestly: the TOC sits at the front, so a dump truncated at
# the END still lists clean. This catches the common failure (the dump never
# really started) and not the rare one (it died three-quarters through). The
# real end-to-end proof is scripts/db-restore.sh, which restores and counts rows
# — run it periodically; that is why it exists.
# shellcheck disable=SC2086
if ! docker compose $COMPOSE_FILES exec -T db pg_restore --list < "$partial" > /dev/null; then
  echo "db-backup: FAILED — archive did not verify" >&2
  exit 1
fi

mv "$partial" "$final"
trap - EXIT

echo "db-backup: wrote $(du -h "$final" | cut -f1) to $final"

remaining=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'mealbot-*.dump' | wc -l)
echo "db-backup: $remaining dump(s) retained in $BACKUP_DIR"
