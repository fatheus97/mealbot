#!/usr/bin/env bash
#
# mealbot — warn before the disk fills, not after.
#
# Run by mealbot-disk-alert.timer (hourly). Safe to run by hand:
#
#     cd /opt/mealbot && ./scripts/disk-alert.sh
#
# The weekly docker-cleanup timer caps BuildKit cache, which was the 2026-07-21
# outage. This is the general case: anything can fill a disk — backups, logs, a
# runaway upload — and a full disk stops Postgres accepting writes and stops
# Caddy renewing certificates. The cleanup job is prevention for one known
# cause; this is detection for every cause.
#
# This script does I/O only: read the disk, read/write the state file, and stop
# early when there is nothing to report. Every DECISION — escalation band, daily
# throttle — lives in app/scripts/disk_alert.py, where pytest can reach it; this
# repo has no shell test harness, and untested escalation logic is how you find
# out at 95% that the alert only ever fired once.
#
# Measurement has to happen HERE, on the host: a container sees its own overlay
# filesystem, not the host's. Sending happens in the backend container, which is
# where the Resend credentials already live.

set -euo pipefail

THRESHOLD="${DISK_ALERT_THRESHOLD:-85}"
MOUNT="${DISK_ALERT_MOUNT:-/}"
STATE_FILE="${DISK_ALERT_STATE:-/opt/mealbot/.disk-alert-state}"
COMPOSE_FILES="${COMPOSE_FILES:--f docker-compose.yml -f docker-compose.prod.yml}"

# -P forces POSIX single-line output, so a long device name cannot wrap onto a
# second line and shift the columns.
#
# Fields are counted from the END, not the start: the layout is
# `<device> <blocks> <used> <avail> <capacity%> <mount>`, and a device name
# containing spaces silently shifts every positional index. That is not
# hypothetical — it is exactly what happens under Git Bash on the dev machine,
# where the device is "C:/Program Files/Git" and a $5 read yields a nonsense
# 273277228%. The prod device is /dev/sda1 so $5 would work there, but reading
# from the end costs nothing and makes the script runnable locally.
#
# `|| true` because this is an assignment: under `set -e` a failing command
# substitution on the right-hand side does NOT abort the script, so the errexit
# people expect here was never real. The numeric guard below is what actually
# catches a broken read — without it an empty `used_pct` sails through the
# comparisons (a `[ "" -lt 85 ]` error is treated as false) and mails
# "[mealbot] disk % full" while still exiting 0, so OnFailure= never fires:
# a detection failure that looks like a successful detection.
df_line="$(df -Ph "$MOUNT" | awk 'NR==2 {gsub(/%/,"",$(NF-1)); print $(NF-1), $(NF-2)}')" || true

# DISK_ALERT_FAKE_PCT drives a real end-to-end run at a chosen percentage.
used_pct="${DISK_ALERT_FAKE_PCT:-${df_line%% *}}"
avail_human="${df_line##* }"

case "$used_pct" in
  ''|*[!0-9]*)
    echo "disk-alert: could not read disk usage for ${MOUNT} (df failed?)" >&2
    exit 1
    ;;
esac

if [ "$used_pct" -lt "$THRESHOLD" ]; then
  # Below the line: forget any previous alert so a later crossing warns again
  # rather than being suppressed by a stale "already told you" record. Kept in
  # the shell so an ordinary hourly run costs one `df` and never starts a
  # container.
  rm -f "$STATE_FILE"
  echo "disk-alert: ${used_pct}% used, below ${THRESHOLD}% — nothing to do"
  exit 0
fi

last_day=""
last_band=0
if [ -f "$STATE_FILE" ]; then
  read -r last_day last_band < "$STATE_FILE" || true
  last_day="${last_day:-}"
  last_band="${last_band:-0}"
fi

# STDOUT is the machine channel: the new state line on a successful send, empty
# otherwise. Human output goes to stderr. Written as an `if !` rather than a
# bare assignment for the same reason as the `df` line above — an assignment
# swallows the exit status that `set -e` is assumed to be watching.
# shellcheck disable=SC2086  # COMPOSE_FILES is a deliberate multi-flag string
if ! new_state="$(docker compose $COMPOSE_FILES run --rm --no-deps -T backend \
      python -m app.scripts.disk_alert \
      "$used_pct" "$avail_human" "$THRESHOLD" "$last_day" "$last_band")"; then
  echo "disk-alert: alert delivery failed at ${used_pct}% used" >&2
  exit 1
fi

# Only a well-formed `YYYY-MM-DD <band>` line becomes state. `docker compose`
# is entitled to put its own chatter on stdout, and a garbled state file would
# suppress tomorrow's alert rather than fail visibly.
if [[ "$new_state" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]+$ ]]; then
  printf '%s\n' "$new_state" > "$STATE_FILE"
fi
