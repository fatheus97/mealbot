# systemd timers (production VPS)

Version-controlled systemd units for mealbot's scheduled maintenance jobs, so
the schedules survive a box rebuild. They are **not** installed automatically by
`scripts/deploy.sh` (which only builds/migrates/swaps containers) — installing
each timer is a one-time manual step (below).

All jobs are **idempotent**. The two app-database jobs run as a one-off container
(`docker compose run --rm --no-deps -T backend ...`), so they keep working even
during the brief window when the backend container is restarting mid-deploy; the
Docker-cleanup job instead shells out to `docker` directly on the host (it prunes
the daemon's build cache / images, so it has no reason to enter a container).

| Timer | Runs | Schedule | Needs env vars? |
|---|---|---|---|
| `mealbot-billing-alerts` | `app.scripts.billing_alerts` — VAT-threshold + monthly filing-reminder emails (#202) | daily 08:00 | **Yes** (`RESEND_API_KEY`, `ALERT_EMAIL_TO`) |
| `mealbot-authsession-cleanup` | `app.scripts.authsession_cleanup` — delete long-expired `authsession` rows so the table doesn't grow unbounded | daily 03:30 | No |
| `mealbot-docker-cleanup` | `docker builder prune -af` + `docker image prune -af` — cap the ever-growing BuildKit build cache / unused images so the disk doesn't fill | **weekly** Sun 04:30 | No |

The schedules are staggered (Sun 04:30 vs daily 03:30 vs daily 08:00) so they
never contend for the small Hetzner box at once.

---

## 1. Billing / VAT alerts (`mealbot-billing-alerts`)

Runs the VAT-threshold / billing alert job once a day. The job:

- emails the operator at **80%** and **100%** of the EU-OSS (€10k) and
  CZ-domestic (2M CZK) VAT thresholds, and
- sends a monthly *identifikovaná osoba* filing reminder (days 1–25, ahead of
  the FÚ 25th deadline).

Every alert is deduped via the `BillingAlert` table, so running it twice, or
missing a day and catching up, never double-sends.

### Prerequisite: alert env vars

The job **no-ops until** both of these are set in `/opt/mealbot/.env`:

```
RESEND_API_KEY=re_...
ALERT_EMAIL_TO=you@example.com
```

Get a key from https://resend.com (free tier is fine; the default
`onboarding@resend.dev` sender works without domain verification). Until they're
set, the timer still runs harmlessly and logs `Alert email not configured … skipping.`

### Install (one-time, on the VPS)

The units assume the repo lives at `/opt/mealbot` and that the job runs as a
non-root **`deploy`** user in the `docker` group (the same restricted user
`scripts/deploy.sh` runs under — not root). If your checkout path or deploy
user differ, edit `WorkingDirectory=` / `User=` in the `.service` first. If you
have no dedicated docker-group user, either create one or remove the `User=`
line to fall back to root (less ideal — see the comment in the unit).

```bash
# from your host, SSH into the box:
ssh <deploy-user>@<your-server>

# on the VPS — make sure the unit files are present (they arrive with any
# normal deploy; or pull manually):
cd /opt/mealbot && git pull

# install + enable:
sudo cp deploy/systemd/mealbot-billing-alerts.service /etc/systemd/system/
sudo cp deploy/systemd/mealbot-billing-alerts.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mealbot-billing-alerts.timer
```

### Verify

```bash
# next scheduled run:
systemctl list-timers mealbot-billing-alerts.timer

# run it once right now (doesn't wait for 08:00):
sudo systemctl start mealbot-billing-alerts.service

# check the result:
journalctl -u mealbot-billing-alerts.service -n 30 --no-pager
```

Expected log line: `billing_alerts: sent N alert(s): [...]` once the env vars
are set, or `Alert email not configured … skipping.` before then.

---

## 2. Expired-auth-session cleanup (`mealbot-authsession-cleanup`)

Every login and refresh inserts an `authsession` row; rotation/logout only mark
rows revoked, never delete them, so the table grows monotonically. Nothing
reads a session past its `expires_at` (`/auth/refresh` rejects expired
sessions), so this job deletes rows expired more than **7 days** ago. No env
vars required — it only touches the database the app already connects to.

### Install (one-time, on the VPS)

Same assumptions as above (`/opt/mealbot`, non-root `deploy` user). Edit
`WorkingDirectory=` / `User=` in the `.service` first if yours differ.

```bash
sudo cp deploy/systemd/mealbot-authsession-cleanup.service /etc/systemd/system/
sudo cp deploy/systemd/mealbot-authsession-cleanup.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mealbot-authsession-cleanup.timer
```

### Verify

```bash
# next scheduled run:
systemctl list-timers mealbot-authsession-cleanup.timer

# run it once right now (doesn't wait for 03:30):
sudo systemctl start mealbot-authsession-cleanup.service

# check the result:
journalctl -u mealbot-authsession-cleanup.service -n 30 --no-pager
```

Expected log line: `authsession_cleanup: deleted N session row(s) expired > 7d ago`.

---

## 3. Docker disk reclamation (`mealbot-docker-cleanup`)

Every deploy runs `docker compose up -d --build` (`scripts/deploy.sh`), so the
BuildKit **build cache grows without bound**. On 2026-07-21 the box reached
~22 GB of reclaimable build cache and 81% disk, and a half-up stack took prod
offline (recovery was `up -d` + `docker builder prune -af`, which freed ~19 GB).
This job caps that automatically. Once a week it runs, in order:

- `docker builder prune -af` — remove **all** build cache (the unbounded
  grower). Costs one cache-cold rebuild on the next deploy; that is the intended
  trade for bounded disk on a small box.
- `docker image prune -af` — remove every image not referenced by a container.
  The running stack keeps its own images, and `deploy.sh` rebuilds fresh, so
  nothing in use is touched.

It **never** touches volumes — no `docker system prune --volumes`, so the
Postgres and Caddy data volumes are safe. No env vars required.

> **Runs as `deploy`, not root.** Both prunes reach the daemon over the docker
> socket, so **docker-group membership is sufficient** — the very same access
> the `deploy` user already uses to run `docker compose` in the two jobs above.
> No root needed; least privilege, consistent with the rest of the pipeline.

### Install (one-time, on the VPS)

Same assumptions as above (`/opt/mealbot`, non-root `deploy` user **in the
`docker` group**). Edit `WorkingDirectory=` / `User=` in the `.service` first if
yours differ.

```bash
sudo cp deploy/systemd/mealbot-docker-cleanup.service /etc/systemd/system/
sudo cp deploy/systemd/mealbot-docker-cleanup.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mealbot-docker-cleanup.timer
```

### Verify

```bash
# next scheduled run:
systemctl list-timers mealbot-docker-cleanup.timer

# run it once right now (doesn't wait for Sunday 04:30):
sudo systemctl start mealbot-docker-cleanup.service

# check the result — the prune summaries incl. "Total reclaimed space":
journalctl -u mealbot-docker-cleanup.service -n 40 --no-pager
```

Expected output: the two prune commands' summaries, each ending in a
`Total reclaimed space: …` line. A `docker system df` before/after confirms the
build-cache figure dropped.

---

## Change a schedule

Edit `OnCalendar=` in the relevant `.timer` (systemd calendar syntax), then:

```bash
sudo cp deploy/systemd/<unit>.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart <unit>.timer
```

## Uninstall

```bash
sudo systemctl disable --now <unit>.timer
sudo rm /etc/systemd/system/<unit>.{service,timer}
sudo systemctl daemon-reload
```
