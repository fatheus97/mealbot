"""CLI for the policy-change notice email (services/policy_notice).

Dry run (the default; sends nothing, writes nothing):
    docker compose exec backend python -m app.scripts.send_policy_notice

Send, confirming the eligible count the dry run printed:
    docker compose exec backend python -m app.scripts.send_policy_notice --send --confirm 2

Same rules as the admin "Notices" tab, because both call the same service: each
(campaign, user) is mailed at most once, the count must match, and the daily
quota applies. Unlike the admin button this runs in the foreground, so it takes
about a second per recipient. Exit codes: 0 done, 1 refused, 2 some sends failed
or are unconfirmed (Resend may have taken them; they are never retried).
"""
import argparse
import asyncio
import sys

from app.db import async_session_factory
from app.services import policy_notice


async def dry_run() -> None:
    async with async_session_factory() as session:
        result = await policy_notice.preview(session)
    counts = result.counts
    print(f"Campaign: {result.campaign}")
    print(
        f"Eligible: {counts.eligible}  sent: {counts.sent}  "
        f"unconfirmed: {counts.unconfirmed}  accepted in app: {counts.accepted_in_app}  "
        f"excluded: {counts.excluded}"
    )
    print(f"Quota: {result.sent_last_24h}/{result.daily_limit} used in the last 24 hours")
    if not result.email_configured:
        print("RESEND_API_KEY is not set: --send would be refused.")
    for email in result.previews:
        print(f"\n--- {email.locale} ---\nSubject: {email.subject}\n{email.html}")
    if counts.eligible:
        print(f"\nTo send: --send --confirm {counts.eligible}")


async def send(confirm: int) -> int:
    async with async_session_factory() as session:
        try:
            user_ids = await policy_notice.check_send(session, confirm)
        except policy_notice.SendRefused as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 1
    print(f"Sending to {len(user_ids)} users, one per {policy_notice.PACE_SECONDS:g}s...")
    result = await policy_notice.run_send(user_ids)
    print(
        f"Sent: {result.sent}  failed: {result.failed}  "
        f"unconfirmed: {result.unconfirmed}  skipped: {result.skipped}"
    )
    return 2 if result.failed or result.unconfirmed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send the policy-change notice email")
    parser.add_argument(
        "--send", action="store_true", help="Actually send. Without it, a dry run."
    )
    parser.add_argument(
        "--confirm",
        type=int,
        help="The eligible count the dry run printed. Required with --send.",
    )
    args = parser.parse_args()
    if not args.send:
        asyncio.run(dry_run())
        return
    if args.confirm is None:
        parser.error("--send needs --confirm <eligible count from the dry run>")
    sys.exit(asyncio.run(send(args.confirm)))


if __name__ == "__main__":
    main()
