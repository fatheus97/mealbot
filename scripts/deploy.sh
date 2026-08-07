#!/usr/bin/env bash
# Live-server deploy script — the part that changes.
#
# NOT the entry point. `.github/workflows/deploy.yml` SSHes to the box, which
# runs the forced command `/opt/mealbot/deploy.sh` — an installed copy of
# `scripts/deploy-shim.sh`. That shim pulls origin/main and `exec`s THIS file,
# so what you edit here is what runs on the next deploy, no reinstall needed.
# See deploy-shim.sh for why the split exists (short version: the installed copy
# silently drifted for months and a step added in #391 never executed once).
#
# The fetch below therefore repeats the shim's. Deliberate — it keeps this
# script correct when run by hand, and re-fetching costs about a second.
#
# Ordering is migrate-before-swap: if `alembic upgrade head` fails, the old
# containers keep serving traffic and this script exits non-zero, which shows
# up as a red deploy run in GitHub Actions.

set -euo pipefail

cd /opt/mealbot

echo "==> Fetching latest main"
git fetch --prune origin main
git reset --hard origin/main
echo "    now at $(git rev-parse --short HEAD) ($(git log -1 --pretty=%s))"

COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

echo "==> Building images"
$COMPOSE build backend frontend

echo "==> Running migrations (old stack still serving traffic)"
$COMPOSE run --rm backend alembic upgrade head

echo "==> Swapping containers"
$COMPOSE up -d --remove-orphans

# The Caddyfile is BIND-MOUNTED, not baked into an image, so editing it changes
# nothing about the caddy service definition — `up -d` leaves that container
# running untouched and Caddy keeps serving the config it parsed at startup. A
# proxy change merged to main would then sit on disk, inert, until someone
# restarted the container by hand (the same silent drift the systemd units have).
# `caddy reload` is a graceful in-process swap: no dropped connections, ~no cost
# when the config is unchanged, and it exits non-zero on a bad config — so under
# `set -e` a broken Caddyfile fails the deploy loudly instead of at 3am.
#
# The config is piped in on STDIN rather than read from the container's
# /etc/caddy/Caddyfile, and that is the whole point. A Linux bind mount of a
# single FILE pins the inode: `git reset --hard` above replaces the file (write
# + rename), so the mount keeps pointing at the ORIGINAL inode and the container
# still sees the pre-pull config. Reloading that path re-applies the old file and
# reports success — which is exactly what happened on the first deploy of #391.
# Reading it host-side sidesteps the mount entirely. (`--adapter caddyfile` is
# required with `-`; there is no filename left to infer it from. The exec still
# runs inside the container so $DOMAIN resolves from the compose environment.)
#
# The one thing stdin costs: with no config PATH, Caddy has nothing to anchor a
# relative path to, so a future directive that names a file (`import`, a TLS cert)
# would resolve against the caddy process's cwd in the container instead of the
# Caddyfile's own directory. Nothing in the Caddyfile does that today. If one
# ever does, give it an absolute container path rather than reverting this.
# -T because this runs over SSH with no TTY.
echo "==> Reloading Caddy (bind-mounted config; the swap above doesn't restart it)"
$COMPOSE exec -T caddy caddy reload --config - --adapter caddyfile < Caddyfile

echo "==> Pruning old images"
docker image prune -f

echo "==> Deploy complete"
