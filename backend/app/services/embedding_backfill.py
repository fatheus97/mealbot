"""Give every cookbook favourite a vector: the daily job behind
mealbot-embedding-backfill.

A favourite reaches RAG only through its embedding. Starring and editing embed
after their commit, outside the kitchen lock, and a failed embed is logged and
otherwise ignored so the request still answers 200: ``favorite_meal`` leaves the
star without a vector, and ``edit_meal`` drops the old vector together with the
edit. This finds those favourites and embeds them. Idempotent: with nothing
missing it does nothing.

The read and every write are short transactions of their own; no transaction
stays open across an embed.
"""
import logging
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.db_models import MealEntry
from app.services.recipe_retriever import EmbedProbe, embed_meal_entry, store_embedding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillCounts:
    #: Embedded and handed to the guarded write. A meal that changed meanwhile
    #: is counted here too; store_embedding logs that its write was skipped.
    embedded: int
    #: Stored content that does not parse. Logged and skipped, not a failure:
    #: embedding it again would fail the same way every day.
    unreadable: int
    #: The embed or the write failed. The job exits non-zero for these, so the
    #: unit's OnFailure alert fires.
    failed: int


async def backfill_missing_embeddings(session: AsyncSession) -> BackfillCounts:
    """Embed every favourite that has no vector, oldest first."""
    rows = (
        await session.execute(
            select(col(MealEntry.id), col(MealEntry.name), col(MealEntry.meal_json))
            .where(
                col(MealEntry.is_favorite).is_(True),
                col(MealEntry.embedding).is_(None),
                # favorite_meal refuses to star a leftover (it has no
                # ingredients of its own), so none should be here; never put
                # one into the global RAG corpus if one is.
                col(MealEntry.leftover_of_day_index).is_(None),
            )
            .order_by(col(MealEntry.id))
        )
    ).all()
    await session.commit()  # end the read before the first embed

    embedded = unreadable = failed = 0
    for entry_id, name, meal_json in rows:
        probe = EmbedProbe(name=name, meal_json=meal_json)
        try:
            await embed_meal_entry(probe)
        except ValidationError:
            unreadable += 1
            logger.warning("Meal entry %d has unreadable meal_json; not embedded", entry_id)
            continue
        except Exception:
            failed += 1
            logger.exception("Failed to embed meal entry %d", entry_id)
            continue
        # Only onto the row as it was read: still a favourite, still without a
        # vector, same content.
        if await store_embedding(
            session,
            entry_id,
            probe,
            col(MealEntry.embedding).is_(None),
            col(MealEntry.meal_json) == meal_json,
        ):
            embedded += 1
        else:
            failed += 1
    return BackfillCounts(embedded=embedded, unreadable=unreadable, failed=failed)
