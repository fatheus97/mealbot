"""Scheduled job: delete long-expired AuthSession rows so the table doesn't grow
unbounded. Idempotent (a second run finds nothing left to delete), so it's safe
to run daily and to catch up after a missed day.

Usage (wire to a systemd timer / the host scheduler):

    docker compose exec backend python -m app.scripts.authsession_cleanup
"""

import asyncio
import logging
from datetime import UTC, datetime

from app.db import async_session_factory
from app.services.authsession_cleanup import (
    DEFAULT_RETENTION_DAYS,
    sweep_expired_auth_sessions,
)

logger = logging.getLogger(__name__)


async def main() -> None:
    now = datetime.now(UTC)
    async with async_session_factory() as session:
        deleted = await sweep_expired_auth_sessions(session, now, DEFAULT_RETENTION_DAYS)
        await session.commit()
    print(
        f"authsession_cleanup: deleted {deleted} session row(s) expired "
        f"> {DEFAULT_RETENTION_DAYS}d ago"
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
