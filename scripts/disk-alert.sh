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
# Measurement has to happen HERE, on the host: a container sees its own overlay
# filesystem, not the host's. Sending happens in the backend container, which is
# where the Resend credentials already live. This script decides; that script
# mails.

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
# from the end costs nothing and makes the script testable locally.
# DISK_ALERT_FAKE_PCT exists so the escalation ladder below is testable — real
# disk usage cannot be driven from a test, and untested escalation logic is how
# you find out at 95% that the alert only ever fired once.
used_pct="${DISK_ALERT_FAKE_PCT:-$(df -P "$MOUNT" | awk 'NR==2 {gsub(/%/,"",$(NF-1)); print $(NF-1)}')}"
avail_human="$(df -Ph "$MOUNT" | awk 'NR==2 {print $(NF-2)}')"

if [ "$used_pct" -lt "$THRESHOLD" ]; then
  # Below the line: forget any previous alert so a later crossing warns again
  # rather than being suppressed by a stale "already told you" record.
  rm -f "$STATE_FILE"
  echo "disk-alert: ${used_pct}% used, below ${THRESHOLD}% — nothing to do"
  exit 0
fi

# Escalation bands. A disk that goes 86% -> 91% is news even if we already
# warned today; a disk that sits at 86% all week is not. Without bands this
# either spams hourly or stays silent while the situation gets worse.
# The base band is 0, NOT $THRESHOLD: the band is persisted and compared across
# runs, so tying it to a configurable value makes a stored band meaningless the
# moment the threshold is retuned — lowering the threshold would read as a
# DE-escalation and suppress a warning that had actually got worse.
if   [ "$used_pct" -ge 95 ]; then band=95
elif [ "$used_pct" -ge 90 ]; then band=90
else                              band=0
fi

today="$(date -u +%F)"
last_day=""
last_band=0
if [ -f "$STATE_FILE" ]; then
  read -r last_day last_band < "$STATE_FILE" || true
  last_band="${last_band:-0}"
fi

if [ "$last_day" = "$today" ] && [ "$band" -le "$last_band" ]; then
  echo "disk-alert: ${used_pct}% used, already alerted today at band ${last_band}% — staying quiet"
  exit 0
fi

echo "disk-alert: ${used_pct}% used (>= ${THRESHOLD}%), ${avail_human} free — alerting"
# shellcheck disable=SC2086
docker compose $COMPOSE_FILES run --rm --no-deps -T backend \
  python -m app.scripts.disk_alert "$used_pct" "$avail_human" "$THRESHOLD"

# Recorded only AFTER a successful send, so a Resend outage does not silently
# consume the day's single alert.
printf '%s %s\n' "$today" "$band" > "$STATE_FILE"
