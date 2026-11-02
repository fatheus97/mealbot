"""Scheduled job: embed every cookbook favourite that has no vector, so it
reaches RAG (see app.services.embedding_backfill). Idempotent, so it is safe to
run daily and to catch up after a missed day.

Usage (systemd timer mealbot-embedding-backfill, or by hand):

    docker compose exec backend python -m app.scripts.backfill_meal_embeddings

Exits 1 when any embed or write failed, so the unit's OnFailure alert fires.
"""

import asyncio
import logging

from app.db import async_session_factory
from app.services.embedding_backfill import backfill_missing_embeddings


async def main() -> int:
    async with async_session_factory() as session:
        counts = await backfill_missing_embeddings(session)
    print(
        f"backfill_meal_embeddings: embedded {counts.embedded}, "
        f"unreadable {counts.unreadable}, failed {counts.failed}"
    )
    return 1 if counts.failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(asyncio.run(main()))
