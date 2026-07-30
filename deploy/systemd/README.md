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
| `mealbot-db-backup` | `scripts/db-backup.sh` — nightly `pg_dump` of the live database | daily 02:30 | No (`ALERT_*` only for failure mail) |
| `mealbot-billing-alerts` | `app.scripts.billing_alerts` — VAT-threshold + monthly filing-reminder emails (#202) | daily 08:00 | **Yes** (`RESEND_API_KEY`, `ALERT_EMAIL_TO`) |
| `mealbot-authsession-cleanup` | `app.scripts.authsession_cleanup` — delete long-expired `authsession` rows so the table doesn't grow unbounded | daily 03:30 | No |
| `mealbot-docker-cleanup` | `docker builder prune -af` + `docker image prune -af` — cap the ever-growing BuildKit build cache / unused images so the disk doesn't fill | **weekly** Sun 04:30 | No |

The schedules are staggered (02:30 vs 03:30 vs Sun 04:30 vs 08:00) so they never
contend for the small Hetzner box at once. The backup deliberately runs *before*
the session sweep: if that sweep ever deletes something it shouldn't, the
night's dump predates it.

## Failure alerting (`mealbot-alert@.service`)

Every job here is `Type=oneshot`, so before this existed a failure went to the
journal and **nowhere else**. That is the worst possible property for scheduled
work: a dead `mealbot-billing-alerts` unit is indistinguishable from *"no VAT
threshold was reached"* — a failure you learn about from the tax authority.
`Persistent=true` hides it further, because **missed** runs catch up after a
reboot while **failing** runs stay silent, so the timers look healthier than
they are.

Each `.service` therefore declares:

```ini
OnFailure=mealbot-alert@%n.service
```

`mealbot-alert@.service` is one template for all of them — systemd substitutes
the failing unit's own name, so a new job gets alerting by adding that single
line. It emails the operator via the existing Resend path
(`app.scripts.unit_failure_alert`) and **always exits 0**, including when the
send fails: it runs *as* the failure handler, so a non-zero exit would only
manufacture a second failed unit that nothing is watching.

It needs the same `RESEND_API_KEY` / `ALERT_EMAIL_TO` as the billing job. With
them unset it logs and exits cleanly rather than failing.

> CI (`deploy units`) fails if any `mealbot-*.service` is missing its
> `OnFailure=` line, so this can't silently regress.

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

## 4. Nightly database backup (`mealbot-db-backup`)

Runs `scripts/db-backup.sh`: one `pg_dump --format=custom` per night into
`/opt/mealbot/backups`, pruned to the last 14 days.

**What this covers, and what it does not.** The dump lands on the same box and
the same disk as the database. That covers the losses that actually happen — a
bad migration, an accidental `DELETE`, a botched admin action — but **not**
losing the box or the disk.

- Check the **Hetzner console** for VM snapshots. A snapshot is crash-consistent
  rather than a clean dump, but it is the difference between "lost a day" and
  "lost everything".
- An off-box copy (Hetzner Storage Box over sftp/rsync is the cheap fit) is the
  obvious next step and needs a destination + credentials decision.

The `SaleRecord` VAT/OSS ledger is why this isn't optional: it is deliberately
`ondelete=SET NULL` so it survives user deletion, you are legally required to
retain it, and nothing else in the system can reproduce it.

### Install (one-time, on the VPS)

```bash
sudo mkdir -p /opt/mealbot/backups
sudo chown deploy:deploy /opt/mealbot/backups

# Copy ALL units, not just the new ones — the three pre-existing .service files
# were modified to add OnFailure=, and /etc/systemd/system/ holds independent
# copies that `scripts/deploy.sh` never touches. Skip this and only the backup
# job is alerted; billing-alerts stays silent.
sudo cp /opt/mealbot/deploy/systemd/mealbot-*.service /etc/systemd/system/
sudo cp /opt/mealbot/deploy/systemd/mealbot-*.timer   /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now mealbot-db-backup.timer
```

The wildcard copy also installs `mealbot-alert@.service`, the shared handler all
four units reference. `daemon-reload` alone is **not** enough — it re-reads the
*installed* copies, so without the `cp` the existing units keep their old,
hookless definitions. Verify all four are actually wired:

```bash
systemctl show -p OnFailure \
  mealbot-db-backup.service mealbot-billing-alerts.service \
  mealbot-authsession-cleanup.service mealbot-docker-cleanup.service
```

Each line must show `OnFailure=mealbot-alert@<that-unit>.service`. An empty
`OnFailure=` means the box is still running a pre-alerting copy.

### Verify

```bash
# next scheduled run:
systemctl list-timers mealbot-db-backup.timer

# run it once right now (doesn't wait for 02:30):
sudo systemctl start mealbot-db-backup.service

# check the result:
journalctl -u mealbot-db-backup.service -n 20 --no-pager
ls -lh /opt/mealbot/backups
```

Expected output: `db-backup: wrote <size> to /opt/mealbot/backups/mealbot-….dump`
followed by the prune/retention counts.

### Rehearse the restore — do this, or you don't have backups

A dump nobody has ever restored is a guess. `scripts/db-restore.sh` restores
into a **scratch** database, counts the rows, and drops it again, so the
rehearsal cannot touch production:

```bash
cd /opt/mealbot && ./scripts/db-restore.sh
```

Expected output: `db-restore: restored N user row(s), M salerecord row(s)`
then `db-restore: scratch database dropped — rehearsal passed`. It exits
non-zero if the restored database has no users.

> **Real recovery is destructive and is not the default.** Restoring *over* the
> live database drops and recreates it, losing everything written since the
> dump. Stop the backend first, then name the target explicitly:
>
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.prod.yml stop backend
> TARGET_DB=live I_UNDERSTAND=yes ./scripts/db-restore.sh backups/mealbot-….dump
> ```

### Tuning

`BACKUP_DIR` and `BACKUP_RETENTION_DAYS` (default 14) are read from the
environment. Retention is what stops this job from becoming the thing that
fills the disk.

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
