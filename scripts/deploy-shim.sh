#!/usr/bin/env bash
# The deploy entry point — INSTALLED ON THE VPS, not run from the repo.
#
# Install once (as root on the box), then never again:
#
#     cp /opt/mealbot/scripts/deploy-shim.sh /opt/mealbot/deploy.sh
#
# `/opt/mealbot/deploy.sh` is the forced command pinned in
# ~deploy/.ssh/authorized_keys, so it is what every push to main actually
# executes. Confirm the path before installing — it is the one thing here that
# could be wrong:
#
#     sed "s/ ssh-.*//" ~deploy/.ssh/authorized_keys
#
# ─── Why this file exists ───────────────────────────────────────────────────
# It is a COPY. Copies drift, and this one drifted silently: the box ran a
# months-old `deploy.sh` while `scripts/deploy.sh` in git accumulated changes
# that never once executed. A step added in #391 merged, deployed green, and did
# nothing — the log simply lacked its `echo`. Nothing in CI can catch that,
# because CI tests the repo, and the repo is not what runs.
#
# So this shim holds the only thing that must live in the installed copy — pull,
# then hand off — and `scripts/deploy.sh` holds everything that changes. Edit
# that one freely; it is fetched fresh here on every deploy and reaches the box
# by itself. Reinstall this shim only if these four lines ever change, which is
# the point: they shouldn't.
#
# ─── Two things that look wrong and are not ─────────────────────────────────
# 1. `exec bash scripts/deploy.sh` rather than pointing authorized_keys straight
#    at `scripts/deploy.sh`. Bash reads a script INCREMENTALLY, by byte offset,
#    as it executes. Pointing the forced command at a tracked file means the
#    `git reset` below rewrites that file mid-execution and bash resumes at a
#    stale offset in new content — arbitrary behaviour, on the deploy path. The
#    handoff dodges it: the pull finishes, THEN bash opens the new file.
# 2. `/opt/mealbot/deploy.sh` is deliberately UNTRACKED, even though it sits in
#    the repo's working tree. That is what keeps `git reset --hard` from
#    touching it (reset leaves untracked files alone) and brings us back to (1).
#    Do not add a root-level `deploy.sh` to the repo.
#
# The redundant-looking fetch: `scripts/deploy.sh` pulls again on its own. Kept
# on purpose — that keeps it correct when run by hand, and the second fetch is a
# no-op costing about a second. The pull here is not for the app, it is for
# `scripts/deploy.sh` itself.

set -euo pipefail

cd /opt/mealbot

git fetch --prune origin main
git reset --hard origin/main

exec bash scripts/deploy.sh
