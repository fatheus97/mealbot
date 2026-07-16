# Billing-alerts scheduler (systemd timer)

Runs the VAT-threshold / billing alert job (`app.scripts.billing_alerts`,
shipped in #202) once a day on the production VPS. The job:

- emails the operator at **80%** and **100%** of the EU-OSS (€10k) and
  CZ-domestic (2M CZK) VAT thresholds, and
- sends a monthly *identifikovaná osoba* filing reminder (days 1–25, ahead of
  the FÚ 25th deadline).

It is **idempotent** — every alert is deduped via the `BillingAlert` table — so
running it twice, or missing a day and catching up, never double-sends.

These unit files are version-controlled so the schedule survives a box rebuild.
They are **not** installed automatically by `scripts/deploy.sh` (which only
builds/migrates/swaps containers) — installing the timer is a one-time manual
step below.

---

## Prerequisite: alert env vars

The job **no-ops until** both of these are set in `/opt/mealbot/.env`:

```
RESEND_API_KEY=re_...
ALERT_EMAIL_TO=you@example.com
```

Get a key from https://resend.com (free tier is fine; the default
`onboarding@resend.dev` sender works without domain verification). Until they're
set, the timer still runs harmlessly and logs `Alert email not configured … skipping.`

## Install (one-time, on the VPS)

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

## Verify

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

## Change the schedule

Edit `OnCalendar=` in the `.timer` (systemd calendar syntax), then:

```bash
sudo cp deploy/systemd/mealbot-billing-alerts.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart mealbot-billing-alerts.timer
```

## Uninstall

```bash
sudo systemctl disable --now mealbot-billing-alerts.timer
sudo rm /etc/systemd/system/mealbot-billing-alerts.{service,timer}
sudo systemctl daemon-reload
```
