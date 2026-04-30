"""
One-time backfill: generate embeddings for favorited MealEntry rows that are
missing them.

Usage:
    docker compose exec backend python -m app.scripts.backfill_meal_embeddings
"""
from __future__ import annotations

import asyncio
import logging

from sqlmodel import select

from app.db import async_session_factory
from app.models.db_models import MealEntry
from app.services.recipe_retriever import embed_meal_entry

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 50


async def backfill() -> None:
    async with async_session_factory() as session:
        stmt = (
            select(MealEntry)
            .where(
                MealEntry.is_favorite.is_(True),  # type: ignore[attr-defined]
                MealEntry.embedding.is_(None),  # type: ignore[union-attr]
            )
        )
        result = await session.execute(stmt)
        entries = result.scalars().all()

        total = len(entries)
        if total == 0:
            logger.info("No entries to backfill.")
            return

        logger.info("Backfilling %d meal entries...", total)

        failures = 0
        for i, entry in enumerate(entries, 1):
            try:
                await embed_meal_entry(entry)
                session.add(entry)
            except Exception:
                failures += 1
                logger.exception("Failed to embed entry %d (id=%s)", i, entry.id)
                continue

            if i % BATCH_SIZE == 0:
                await session.commit()
                logger.info("Committed batch (%d/%d)", i, total)

        await session.commit()
        logger.info(
            "Backfill complete: %d/%d succeeded, %d failed.",
            total - failures, total, failures,
        )


def main() -> None:
    asyncio.run(backfill())


if __name__ == "__main__":
    main()
