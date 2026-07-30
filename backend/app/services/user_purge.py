"""The single list of user-owned rows the database will not clean up for us.

Both hard-delete paths — the admin ``DELETE /api/admin/users/{id}`` and the lazy
demo-user sweep in ``services.demo_user`` — route through here.

They used to keep two hand-maintained lists, and the lists drifted: ``PantryStaple``
was added to the admin path only, so an expired demo user who had saved a staple
(``PUT /api/staples`` has no demo guard) made the sweep's final ``delete(User)``
raise IntegrityError. That wedges demo session creation for *every* later visitor,
because the sweep is the first thing ``POST /api/auth/demo`` does. One list means a
future user-owned table can only be forgotten in both places or neither.

Membership rule: a table belongs here **iff** its ``user_id`` FK declares no
``ondelete``. Tables the DB handles on the final user delete must NOT be listed —
``ondelete="CASCADE"`` (MachineGeneration, MachineCorrection, LlmUsage,
EmailVerificationToken, FeedbackReport) and ``ondelete="SET NULL"`` (SaleRecord,
InviteToken — ledger and audit rows that deliberately outlive the account).

Core ``delete()`` statements, not ORM ``session.delete``, so ORM relationship
handling can't null-update the NOT NULL child FKs.
"""
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete

from app.models.db_models import (
    AuthSession,
    MealEntry,
    MealPlan,
    PantryStaple,
    PasswordResetToken,
    StockItem,
)


async def purge_user_owned_rows(
    session: AsyncSession, user_ids: Sequence[int]
) -> None:
    """Delete every non-cascading owned row for ``user_ids``.

    Children before parents (**MealEntry before MealPlan** — ``MealEntry.meal_plan_id``
    FK). Does NOT delete the ``User`` rows themselves: the callers differ there (the
    admin path audits first, the sweep deletes in bulk) and the DB-level CASCADE /
    SET NULL must fire on that statement. Caller commits.
    """
    if not user_ids:
        return
    await session.execute(delete(MealEntry).where(col(MealEntry.user_id).in_(user_ids)))
    await session.execute(delete(MealPlan).where(col(MealPlan.user_id).in_(user_ids)))
    await session.execute(delete(StockItem).where(col(StockItem.user_id).in_(user_ids)))
    await session.execute(
        delete(PantryStaple).where(col(PantryStaple.user_id).in_(user_ids))
    )
    await session.execute(
        delete(AuthSession).where(col(AuthSession.user_id).in_(user_ids))
    )
    await session.execute(
        delete(PasswordResetToken).where(col(PasswordResetToken.user_id).in_(user_ids))
    )
