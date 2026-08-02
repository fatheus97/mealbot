#!/usr/bin/env bash
#
# mealbot — copy the newest nightly dump off the box, encrypted.
#
# Run by mealbot-offsite-backup.timer (daily, after db-backup). Safe by hand:
#
#     cd /opt/mealbot && ./scripts/offsite-backup.sh
#
# ─── Why this exists ─────────────────────────────────────────────────────────
# db-backup.sh writes to /opt/mealbot/backups — the SAME DISK as the database it
# protects. That covers the losses that actually happen weekly (a bad migration,
# an accidental DELETE, a botched admin action) and covers nothing about losing
# the box. A dead disk loses the database and every backup of it in one go,
# which is the exact scenario backups exist for.
#
# ─── PARKED BY DEFAULT ───────────────────────────────────────────────────────
# Ships inert. With OFFSITE_BACKUP_ENABLED unset this logs one line and exits 0,
# so the unit can be installed and left enabled with no destination, no
# credentials and no bill. Everything below activates by setting four variables
# — see deploy/systemd/README.md §6.
#
# ─── The box can WRITE backups it cannot READ ────────────────────────────────
# Encryption is gpg PUBLIC KEY, not a passphrase and not rclone's `crypt`
# remote. Both of those would put the decryption secret on the box, so anyone
# who owned the box would own every historical backup too — including the
# attacker whose ransomware is the reason you wanted off-site copies. Here the
# box holds only the public half; the private key lives offline with the owner.
# The cost is real and worth stating: LOSE THAT PRIVATE KEY AND THE BACKUPS ARE
# UNRECOVERABLE. The README says so twice.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/opt/mealbot/backups}"
# Days of history to keep at the destination. Longer than the local 14 because
# off-site storage is the copy that survives a compromise noticed late, and at
# ~170 KB a dump this costs nothing.
OFFSITE_RETENTION_DAYS="${OFFSITE_RETENTION_DAYS:-90}"

if [ "${OFFSITE_BACKUP_ENABLED:-false}" != "true" ]; then
  echo "offsite-backup: not enabled (OFFSITE_BACKUP_ENABLED != true) — nothing to do"
  exit 0
fi

# From here on the operator has declared this configured, so every problem is a
# real failure: exit non-zero and let OnFailure= mail it. A backup job that
# quietly does nothing is the worst possible failure mode, because you find out
# at the moment you need it.
missing=""
[ -n "${OFFSITE_RCLONE_REMOTE:-}" ] || missing="$missing OFFSITE_RCLONE_REMOTE"
[ -n "${OFFSITE_GPG_RECIPIENT:-}" ] || missing="$missing OFFSITE_GPG_RECIPIENT"
if [ -n "$missing" ]; then
  echo "offsite-backup: FAILED — enabled but unconfigured:$missing" >&2
  exit 1
fi

# ORDER MATTERS, for two reasons.
#
# "Is there a good backup to ship?" is checked BEFORE "can I ship it?". On a
# real box the dump problems are both likelier and more urgent — a wedged
# db-backup is a worse fact than a missing binary — so they should be what the
# alert mail says. And it keeps those guards reachable in CI without
# provisioning a gpg key and an rclone install just to get past a prerequisite
# check: an earlier draft put the tooling checks first, and the CI cases for the
# dump guards passed on the KEYRING error instead. They would have passed with
# the dump guards deleted.

# Newest COMPLETED dump. `.partial` files are excluded by the glob on purpose:
# db-backup.sh renames only after the archive verifies, so a .partial is a
# failed run, and shipping one off-site would create a remote file that looks
# like a backup and is not.
newest="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'mealbot-*.dump' \
  -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)"
if [ -z "$newest" ]; then
  echo "offsite-backup: FAILED — no completed dump found in $BACKUP_DIR" >&2
  exit 1
fi

# Refuse a stale dump rather than uploading yesterday's again and reporting
# success. db-backup runs daily at 02:30 and this runs after it, so anything
# older than ~2 days means db-backup is broken — and THAT is the failure worth
# an alert. Without this check a wedged db-backup would be masked by a
# permanently green off-site job.
if [ -n "$(find "$newest" -mtime +1)" ]; then
  echo "offsite-backup: FAILED — newest dump $newest is more than 1 day old;" \
       "db-backup is probably broken" >&2
  exit 1
fi

# Tooling and key checks, now that we know there is something worth shipping.
for bin in rclone gpg; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "offsite-backup: FAILED — $bin is not installed (see README §6)" >&2
    exit 1
  fi
done

# Prove the recipient key is in the keyring BEFORE encrypting. Without this, gpg
# fails per-file with a less obvious message and a typo'd recipient reads as
# "encryption broke" rather than "that key was never imported".
if ! gpg --list-keys "$OFFSITE_GPG_RECIPIENT" >/dev/null 2>&1; then
  echo "offsite-backup: FAILED — no public key for '$OFFSITE_GPG_RECIPIENT' in the keyring" >&2
  exit 1
fi

remote_name="$(basename "$newest").gpg"
target="${OFFSITE_RCLONE_REMOTE%/}/$remote_name"

# Skip if it is already there. gpg output is non-deterministic (fresh session
# key every run), so re-encrypting the same dump produces a byte-different file
# and rclone would upload it again on every run — one redundant copy per day,
# forever.
if rclone lsf "$target" >/dev/null 2>&1 && [ -n "$(rclone lsf "$target" 2>/dev/null)" ]; then
  echo "offsite-backup: $remote_name already at the destination — nothing to upload"
else
  tmp="$(mktemp -t mealbot-offsite.XXXXXX)"
  # TERM/INT as well as EXIT: bash's default SIGTERM disposition skips the EXIT
  # trap, which would strand a plaintext-sized encrypted dump in /tmp.
  trap 'rm -f "$tmp"' EXIT TERM INT

  # --trust-model always: the operator imported this key deliberately and we do
  # not maintain a web of trust on a server. Without it gpg refuses to encrypt
  # to an unsigned key non-interactively.
  echo "offsite-backup: encrypting $(basename "$newest") for $OFFSITE_GPG_RECIPIENT"
  gpg --batch --yes --trust-model always \
    --recipient "$OFFSITE_GPG_RECIPIENT" \
    --output "$tmp" --encrypt "$newest"

  if [ ! -s "$tmp" ]; then
    echo "offsite-backup: FAILED — encrypted file is empty" >&2
    exit 1
  fi

  echo "offsite-backup: uploading $remote_name ($(du -h "$tmp" | cut -f1))"
  rclone copyto "$tmp" "$target"

  # Verify at the DESTINATION, not from rclone's exit code alone. The point of
  # this job is that a copy exists somewhere else; asserting the remote can be
  # listed and is non-empty is the cheapest evidence of that.
  remote_size="$(rclone size --json "$target" 2>/dev/null | sed -n 's/.*"bytes":\([0-9]*\).*/\1/p')"
  if [ -z "$remote_size" ] || [ "$remote_size" -eq 0 ]; then
    echo "offsite-backup: FAILED — $remote_name is missing or empty at the destination" >&2
    exit 1
  fi
  echo "offsite-backup: verified $remote_size bytes at $target"

  rm -f "$tmp"
  trap - EXIT TERM INT
fi

# Prune AFTER a successful upload, never before: a retention sweep that runs on
# a night the upload fails would delete history while adding nothing. (The local
# db-backup.sh prunes first for the opposite reason — there, a failed dump must
# not let old files accumulate forever. Different risk, different order.)
#
# --include is not decoration. Without it this deletes ANYTHING at the
# destination older than the retention window, and the only thing standing
# between that and someone else's data is the README saying "use a dedicated
# bucket". A prune that can only ever remove files this script wrote does not
# depend on that assumption holding a year from now.
echo "offsite-backup: pruning remote copies older than ${OFFSITE_RETENTION_DAYS}d"
rclone delete --min-age "${OFFSITE_RETENTION_DAYS}d" \
  --include '/mealbot-*.dump.gpg' "${OFFSITE_RCLONE_REMOTE%/}/"

remaining="$(rclone lsf "${OFFSITE_RCLONE_REMOTE%/}/" 2>/dev/null | grep -c '\.dump\.gpg$' || true)"
echo "offsite-backup: ${remaining:-0} encrypted dump(s) retained off-site"
