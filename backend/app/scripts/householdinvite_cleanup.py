"""Scheduled job: delete expired HouseholdInvite rows, each of which holds a third
party's address. Idempotent (a second run finds nothing left to delete), so it's
safe to run daily and to catch up after a missed day.

Usage (wire to a systemd timer / the host scheduler):

    docker compose exec backend python -m app.scripts.householdinvite_cleanup
"""

import asyncio
import logging
from datetime import UTC, datetime

from app.db import async_session_factory
from app.services.household import sweep_expired_invites


async def main() -> None:
    async with async_session_factory() as session:
        deleted = await sweep_expired_invites(session, datetime.now(UTC))
        await session.commit()
    print(f"householdinvite_cleanup: deleted {deleted} expired invite(s)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
