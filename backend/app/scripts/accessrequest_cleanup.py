"""Scheduled job: delete access requests that were handled or dismissed more
than 30 days ago (services/access_request.CLOSED_RETENTION_DAYS, owner Q51).
Each row holds a stranger's email, message and campaign tags, and the privacy
policy promises this retention. Idempotent (a second run finds nothing left to
delete), so it is safe to run daily and to catch up after a missed day.

Usage (wire to a systemd timer / the host scheduler):

    docker compose exec backend python -m app.scripts.accessrequest_cleanup
"""

import asyncio
import logging
from datetime import UTC, datetime

from app.db import async_session_factory
from app.services.access_request import sweep_closed_access_requests


async def main() -> None:
    async with async_session_factory() as session:
        deleted = await sweep_closed_access_requests(session, datetime.now(UTC))
        await session.commit()
    print(f"accessrequest_cleanup: deleted {deleted} closed access request(s)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
