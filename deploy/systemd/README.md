# systemd timers (production VPS)

Version-controlled systemd units for mealbot's scheduled maintenance jobs, so
the schedules survive a box rebuild.

**These install themselves — once `mealbot-unit-sync.timer` is on the box (§7).**
It reconciles `/etc/systemd/system/` with this directory every ten minutes, so a
unit merged to `main` reaches the box on its own, and an edited one actually
takes effect. The per-timer install steps below are then only needed for a fresh
box or a manual install of a single unit; §7 is the one you have to run by hand,
and only ever once.

> **Before §7 existed this was the bug, not the docs.** `/etc/systemd/system/`
> holds independent copies and `scripts/deploy.sh` never touched them, so a unit
> merged to main simply wasn't on the box — `mealbot-docker-cleanup.timer` read
> `not-found` for nine days after #259 while the build cache it caps climbed back
> to 5 GB. An *edited* unit failed worse: `daemon-reload` re-reads the installed
> copy, so it looks applied and isn't. If you find yourself hand-copying a unit,
> check §7 is alive first — that is the symptom.

All jobs are **idempotent**. The two app-database jobs run as a one-off container
(`docker compose run --rm --no-deps -T backend ...`), so they keep working even
during the brief window when the backend container is restarting mid-deploy; the
Docker-cleanup job instead shells out to `docker` directly on the host (it prunes
the daemon's build cache / images, so it has no reason to enter a container).

| Timer | Runs | Schedule | Needs env vars? |
|---|---|---|---|
| `mealbot-unit-sync` | `scripts/sync-systemd-units.sh` — install units from the git checkout, so this table's other rows can't drift (§7) | **every 10 min** | No (`ALERT_*` only for failure mail) |
| `mealbot-disk-alert` | `scripts/disk-alert.sh` — warn by email before the disk fills | **hourly** | **Yes** (`RESEND_API_KEY`, `ALERT_EMAIL_TO`) |
| `mealbot-db-backup` | `scripts/db-backup.sh` — nightly `pg_dump` of the live database | daily 02:30 | No (`ALERT_*` only for failure mail) |
| `mealbot-offsite-backup` | `scripts/offsite-backup.sh` — encrypt the newest dump and copy it to Backblaze B2 | daily 03:00 | **PARKED** — inert until `OFFSITE_BACKUP_ENABLED=true` (§6) |
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

## 5. Disk-usage alert (`mealbot-disk-alert`)

The weekly `mealbot-docker-cleanup` timer PREVENTS one known cause of a full
disk — BuildKit cache, the 2026-07-21 outage. This DETECTS every other cause
(backups, logs, a runaway upload) while there is still room to act. A full disk
stops Postgres accepting writes and stops Caddy renewing certificates.

Runs hourly, not daily: a disk can go from comfortable to full inside a day, and
a daily check can report the problem after the outage it was meant to prevent.
Below the threshold the run is one `df` and an exit — no container is started.

**It does not spam.** Escalation bands mean 86% warns once, then stays quiet
until it crosses 90%, then 95%. A new day re-arms it. Dropping back below the
threshold clears the state, so a later crossing warns again.

The measurement happens on the HOST (a container sees its own overlay
filesystem, not the host's); the email is sent from the backend container, where
the Resend credentials already are. `scripts/disk-alert.sh` is deliberately thin
— `df`, the state file, and the below-threshold exit. The band/throttle decision
lives in `app/scripts/disk_alert.py` because this repo has no shell test harness
and that is the logic worth testing.

**A disk it cannot read is a failure, not a quiet 0.** If `df` breaks, the unit
exits non-zero and `OnFailure=` mails you — rather than reporting an empty
percentage, which is what it did before #351 review.

### Tuning

Read from the environment, all optional:

```
DISK_ALERT_THRESHOLD=85          # percent
DISK_ALERT_MOUNT=/
DISK_ALERT_STATE=/opt/mealbot/.disk-alert-state
```

### Install (one-time, on the VPS)

```bash
sudo cp /opt/mealbot/deploy/systemd/mealbot-*.service /etc/systemd/system/
sudo cp /opt/mealbot/deploy/systemd/mealbot-*.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mealbot-disk-alert.timer
```

### Verify

```bash
systemctl list-timers mealbot-disk-alert.timer
sudo systemctl start mealbot-disk-alert.service
journalctl -u mealbot-disk-alert.service -n 20 --no-pager
```

Expected on a healthy box: `disk-alert: 34% used, below 85% — nothing to do`.

To prove the mail path end to end without filling the disk, force a reading:

```bash
cd /opt/mealbot && sudo -u deploy DISK_ALERT_FAKE_PCT=91 ./scripts/disk-alert.sh
```

That sends a real alert. Delete `/opt/mealbot/.disk-alert-state` afterwards so
the day's genuine alert is not suppressed.

---

## 6. Off-site backup copy (`mealbot-offsite-backup`) — **PARKED**

`db-backup` writes to `/opt/mealbot/backups`, on the **same disk as the database
it protects**. That covers the losses that happen weekly (a bad migration, an
accidental DELETE, a botched admin action) and covers nothing about losing the
box: a dead disk takes the database and every backup of it together, which is
the exact scenario backups exist for.

This unit encrypts the newest dump and copies it to Backblaze B2.

**It ships inert.** With `OFFSITE_BACKUP_ENABLED` unset the script logs one line
and exits 0, so the unit is safe to install and enable today with no bucket, no
credentials and no bill. Activation is §6.2 and takes about fifteen minutes.

### 6.1 The design decision worth knowing

Encryption is **gpg public key**, not a passphrase and not rclone's `crypt`
remote. Both of those put the decryption secret on the box — so whoever owns the
box owns every historical backup too, including the attacker whose ransomware is
the reason you wanted off-site copies in the first place. Here the box holds
only the *public* half: it can write backups it cannot read.

> ⚠️ **The private key is the only way back.** Lose it and the off-site copies
> are cryptographically unrecoverable — B2 cannot help, and neither can I. Keep
> it in your password manager AND on something physical that is not this laptop.
> Test the restore (§6.4) before you rely on it.

### 6.2 Activation

**a) Generate the keypair — on your LAPTOP, never on the server.**

```bash
gpg --quick-generate-key "mealbot-backup <info@trymealbot.com>" default default never
gpg --armor --export mealbot-backup > mealbot-backup.pub
gpg --armor --export-secret-keys mealbot-backup > mealbot-backup.key   # into the password manager, then shred
```

**b) Import ONLY the public key on the box.**

```bash
scp mealbot-backup.pub root@<your-server>:/tmp/
ssh root@<your-server> 'sudo -u deploy gpg --import /tmp/mealbot-backup.pub && rm /tmp/mealbot-backup.pub'
```

**c) Create the B2 bucket and an application key.** In the Backblaze console:
a **private** bucket (e.g. `mealbot-backups`), then an application key scoped to
that bucket alone with `listFiles`, `readFiles`, `writeFiles`, `deleteFiles`.
Do not use the master key.

Turn on **Object Lock** if offered. Encryption stops an attacker *reading* the
backups; object lock is what stops them *deleting* them.

**d) Install rclone and configure the remote as `deploy`.**

```bash
ssh root@<your-server> 'curl -fsSL https://rclone.org/install.sh | bash'
ssh root@<your-server> 'sudo -u deploy rclone config'   # n) new → name: b2 → storage: b2 → key id + app key
```

**e) Write the credentials file.** Deliberately *not* `/opt/mealbot/.env` — that
file is read by the container stack and by anyone who can `exec` into a
container. The B2 key only needs to be visible to this one unit.

```bash
ssh root@<your-server> 'mkdir -p /etc/mealbot && cat > /etc/mealbot/offsite-backup.env <<EOF
OFFSITE_BACKUP_ENABLED=true
OFFSITE_RCLONE_REMOTE=b2:mealbot-backups/prod
OFFSITE_GPG_RECIPIENT=mealbot-backup
OFFSITE_RETENTION_DAYS=90
EOF
chown root:deploy /etc/mealbot/offsite-backup.env && chmod 640 /etc/mealbot/offsite-backup.env'
```

**f) Install the units and run it once by hand.**

```bash
sudo cp /opt/mealbot/deploy/systemd/mealbot-*.service /etc/systemd/system/
sudo cp /opt/mealbot/deploy/systemd/mealbot-*.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mealbot-offsite-backup.timer
sudo systemctl start mealbot-offsite-backup.service
journalctl -u mealbot-offsite-backup.service -n 20 --no-pager
```

**g) Update the privacy policy — this is not optional.** Backblaze becomes a
processor holding (encrypted) personal data, and `frontend/privacy.html` names
its recipients explicitly. Add Backblaze to that list, with the storage region,
in the same change that flips this on. Shipping the backup without the
disclosure makes a published page inaccurate.

### 6.3 Verify

```bash
systemctl list-timers mealbot-offsite-backup.timer
sudo -u deploy rclone ls b2:mealbot-backups/prod
```

Expected while parked: `offsite-backup: not enabled (OFFSITE_BACKUP_ENABLED !=
true) — nothing to do`. Expected once live: an `...dump.gpg` per day.

### 6.4 Restore — rehearse this, don't assume it

On your laptop, where the private key lives:

```bash
rclone copy b2:mealbot-backups/prod/mealbot-2026-08-02T023007Z.dump.gpg .
gpg --output restored.dump --decrypt mealbot-2026-08-02T023007Z.dump.gpg
# then feed restored.dump to scripts/db-restore.sh (it defaults to a scratch DB)
```

A backup you have never restored is a hypothesis. `scripts/db-restore.sh`
restores into a throwaway database and counts rows precisely so this can be
rehearsed without touching production.

---

## 7. Unit sync (`mealbot-unit-sync`) — install this one first

Reconciles `/etc/systemd/system/` with `deploy/systemd/` every ten minutes: any
unit whose installed copy differs from the repo is reinstalled, `daemon-reload`
runs if anything changed, a timer whose file was **absent** is enabled and
started, and an edited timer that is **already running** is restarted.

That last one is not redundant with `daemon-reload`: the reload refreshes
systemd's cached unit definition, but a timer's next elapse is *runtime* state,
recomputed only when it re-enters the waiting state. Without the restart, editing
`OnCalendar=` on the nightly backup would look applied — file installed, reload
done — and keep firing on the old schedule until it next ran. A stopped timer is
deliberately left stopped (a restart would start it).

This is the unit that makes every other section here self-applying. It is also
the last thing in the deployment that needs a manual install — the other two
copies that used to drift are fixed in the repo (`scripts/deploy-shim.sh` for
the deploy script, the stdin `caddy reload` in `scripts/deploy.sh` for the
bind-mounted Caddyfile).

### What it will not do

- **Never removes** a unit that is installed but absent from the repo. Delete
  those by hand (see Uninstall).
- **Never re-enables or starts** a timer you disabled. A timer is enabled only
  the first time its file lands, so `systemctl disable mealbot-foo.timer` sticks
  instead of coming back ten minutes later. Editing a unit reinstalls it and
  restarts it *only if it was already running*, so its enabled/disabled state
  stays exactly as you set it.
- **Never restarts a `.service`.** They are all `Type=oneshot`, so a restart
  would *run* the backup or the prune as a side effect of editing a comment in
  the unit. Only timers are restarted.

### Root, and why that is not a new grant

It runs as **root** — writing `/etc/systemd/system/` and calling `daemon-reload`
admit no lesser privilege, and it is the only unit here that isn't the `deploy`
user. That does not widen anything: `deploy` is in the `docker` group, and the
docker socket is root by construction, so merge access to `main` already implied
root on this box. The trust boundary is branch protection, where it already was.

### Install (one-time, on the VPS)

```bash
sudo cp deploy/systemd/mealbot-unit-sync.service /etc/systemd/system/
sudo cp deploy/systemd/mealbot-unit-sync.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mealbot-unit-sync.timer
```

### Verify

```bash
# run it once now rather than waiting up to ten minutes:
sudo systemctl start mealbot-unit-sync.service

# what it did — one "installed <unit>" line per unit that was missing or stale,
# and nothing at all once the box is reconciled:
journalctl -u mealbot-unit-sync.service -n 40 --no-pager

# the real proof — every timer in the table above is now listed:
systemctl list-timers 'mealbot-*' --all --no-pager
```

A second `systemctl start` should print **nothing** beyond systemd's own
start/finish lines: a silent run means the box matches the repo, which is the
steady state. The first run on a box that has drifted is the noisy one.

To confirm it truly closes the loop, edit a `.timer`'s `OnCalendar=` on `main`
and watch `systemctl list-timers` change within ten minutes without touching the
box.

---

## Change a schedule

Edit `OnCalendar=` in the relevant `.timer` (systemd calendar syntax) and merge
it. With §7 installed that is the whole procedure — the sync installs it,
reloads, and restarts the timer within ten minutes, which is what actually
reschedules it (`daemon-reload` alone would not; see §7).

To apply it immediately, or on a box without §7:

```bash
sudo cp deploy/systemd/<unit>.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart <unit>.timer
```

## Stop a job

```bash
sudo systemctl disable --now <unit>.timer
```

That is enough, and it sticks: the sync (§7) reinstalls a unit's *file* when it
differs from the repo but never re-enables a timer that already exists, so a
disabled timer stays disabled.

## Uninstall

**Delete it from `deploy/systemd/` and merge that first.** The sync treats an
absent installed file as a brand-new unit, so removing one on the box while it
is still in the repo brings it back within ten minutes — enabled and running,
because "the file wasn't there" is exactly how a new timer is recognised.

With the unit gone from `main`:

```bash
sudo systemctl disable --now <unit>.timer
sudo rm /etc/systemd/system/<unit>.{service,timer}
sudo systemctl daemon-reload
```

(The sync never deletes anything, so this last part stays manual by design.)
