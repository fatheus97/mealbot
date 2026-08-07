#!/usr/bin/env bash
# Install the repo's systemd units onto the box — the third and last drift fix.
#
# `/etc/systemd/system/` holds INDEPENDENT COPIES of everything in
# `deploy/systemd/`. Nothing used to reconcile them, so a unit merged to main was
# simply not on the box: `mealbot-docker-cleanup.timer` read `not-found` for the
# nine days after #259 merged, while the build cache it exists to cap climbed
# back to 5 GB. An EDITED unit was worse than a missing one — `daemon-reload`
# re-reads the installed copy, so it looks like it applied and changes nothing.
# Neither CI nor the deploy said a word, because CI tests the repo and the deploy
# only ever touched containers.
#
# This runs as root from `mealbot-unit-sync.timer` every ten minutes, so a unit
# change reaches the box on its own. Sibling fixes, same class of bug:
# `deploy-shim.sh` (the deploy script was a stale copy) and the stdin `caddy
# reload` in `deploy.sh` (the bind-mounted Caddyfile was a stale inode).
#
# ─── Why root, when every other unit here runs as `deploy` ──────────────────
# Writing `/etc/systemd/system/` and calling `daemon-reload` require it; there is
# no lesser privilege that installs a unit. This does NOT widen the blast radius:
# `deploy` is in the `docker` group, and the docker socket is root by
# construction (`docker run -v /:/host`), so anyone who can merge to main could
# already reach root here. It does mean the trust boundary is branch protection
# on `main` — which is exactly where it already was.
#
# ─── What it deliberately does NOT do ───────────────────────────────────────
# * **Never removes** an installed unit missing from the repo. Deleting a unit
#   file to stop a job is a plausible operator action; silently undoing it from a
#   timer is not a risk worth a feature nobody asked for. Remove by hand.
# * **Never re-enables** a timer that is merely disabled. A timer is enabled only
#   the first time its file lands, so a new job gets scheduled without a manual
#   step, while `systemctl disable mealbot-foo.timer` stays disabled instead of
#   coming back ten minutes later. That distinction is the whole reason this
#   tracks "was the file already there" rather than just re-running `enable`.

set -euo pipefail

# Overridable only so the CI step can exercise this against temp dirs and a
# stub systemctl. In production all three take their defaults.
SRC_DIR=${MEALBOT_UNIT_SRC:-/opt/mealbot/deploy/systemd}
DST_DIR=${MEALBOT_UNIT_DST:-/etc/systemd/system}
SYSTEMCTL=${MEALBOT_SYSTEMCTL:-systemctl}

# A missing source directory means a broken checkout. Fail loudly: `nullglob`
# plus a silent `exit 0` would turn that into "synced nothing, all good" — the
# precise failure mode this script exists to end.
if [ ! -d "$SRC_DIR" ]; then
  echo "sync-systemd-units: source directory ${SRC_DIR} does not exist" >&2
  exit 1
fi

changed=0
new_timers=()
edited_timers=()

for src in "$SRC_DIR"/mealbot-*.service "$SRC_DIR"/mealbot-*.timer; do
  # The literal glob survives when a pattern matches nothing (no `nullglob`, on
  # purpose — see above), so skip anything that isn't a real file.
  [ -f "$src" ] || continue
  name=$(basename "$src")
  dst="$DST_DIR/$name"

  # Track absence BEFORE installing: "the file was not there" is what makes a
  # timer new, and it is unrecoverable once the copy lands.
  was_absent=0
  [ -e "$dst" ] || was_absent=1

  # `cmp -s` is silent and returns non-zero for a missing destination too, so
  # the same branch covers both "new" and "edited".
  if ! cmp -s "$src" "$dst"; then
    install -m 0644 "$src" "$dst"
    echo "sync-systemd-units: installed ${name}"
    changed=1
    if [ "${name##*.}" = "timer" ]; then
      if [ "$was_absent" -eq 1 ]; then
        new_timers+=("$name")
      else
        edited_timers+=("$name")
      fi
    fi
  fi
done

# Only on a real change: `daemon-reload` is cheap but not free, and this runs
# every ten minutes forever.
if [ "$changed" -eq 1 ]; then
  "$SYSTEMCTL" daemon-reload
fi

# `daemon-reload` alone does NOT reschedule a running timer. It refreshes
# systemd's cached unit definition, but the next elapse is RUNTIME state,
# recomputed only when the timer re-enters its waiting state — on restart, or
# after it next fires under the OLD schedule. So editing `OnCalendar=` on the
# nightly backup would look applied here (file installed, reload done, exit 0)
# and change nothing until the next 02:30 — the precise "looks applied, isn't"
# failure this script exists to end, reintroduced one layer up. The manual
# procedure in README §"Change a schedule" always said `restart` for this reason.
#
# Only when the timer is ACTIVE. `restart` would START a stopped one, which is
# how an operator's deliberate `systemctl disable --now` would come back to life
# ten minutes later — the invariant the enable branch above exists to protect.
#
# Timers only, never services: these are all Type=oneshot, so restarting a
# .service would RUN the job (a backup, a prune) as a side effect of editing a
# comment in it.
for timer in "${edited_timers[@]+"${edited_timers[@]}"}"; do
  if "$SYSTEMCTL" is-active --quiet "$timer"; then
    echo "sync-systemd-units: restarting ${timer} (schedule may have changed)"
    "$SYSTEMCTL" restart "$timer"
  fi
done

# `enable --now` both schedules the timer and starts it, so a new job does not
# wait for a reboot. Runs after daemon-reload, or systemd would enable a unit it
# has not re-read yet.
for timer in "${new_timers[@]+"${new_timers[@]}"}"; do
  echo "sync-systemd-units: enabling ${timer} (first install)"
  "$SYSTEMCTL" enable --now "$timer"
done

# Silence on a no-op run is deliberate: this fires 144 times a day and only the
# journal reads it. A change always prints; a failure exits non-zero and
# OnFailure= mails the operator.
exit 0
