"""Best-effort capture of the machine-output → user-correction delta.

Every LLM/OCR generation is persisted (MachineGeneration) at generation time,
and every user edit/commit of that output is persisted (MachineCorrection),
linked back to the generation it derives from. Offline analysis diffs the two
to learn where the model is wrong and how users fix it.

Design contract — read before adding a call site:

* **Never break the user action.** These helpers swallow every exception and
  log it; a telemetry bug must not turn a successful cook/merge/edit into a
  500. They construct-and-``add`` a row to the *caller's* session, so the row
  is committed atomically with the user action — recorded iff the action
  commits (no phantom rows), rolled back with it otherwise.
* Because the row rides the caller's transaction, a *flush-time* failure (e.g.
  a NOT NULL violation) would still poison that transaction. The rows are
  therefore kept trivially valid — all values are server-controlled and the
  JSON is produced by ``model_dump_json()``, which cannot fail — and covered by
  tests. Do not add constraints (uniques, non-trivial checks) that could fail
  at flush against real user data.
* ``surface`` is always a server-side constant, never user input.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.db_models import MachineCorrection, MachineGeneration

logger = logging.getLogger(__name__)

# The known surfaces. Kept as plain sets (not enums) so a new call site is a
# one-line addition; asserted against so a typo'd surface fails loudly in tests
# rather than silently polluting the data.
GENERATION_SURFACES = frozenset(
    {"meal_plan", "single_recipe", "receipt_scan", "regenerate"}
)
CORRECTION_SURFACES = frozenset({"meal_edit", "recipe_cook", "receipt_merge"})


def record_generation(
    session: AsyncSession,
    *,
    user_id: int,
    surface: str,
    output_json: str,
    request_json: str | None = None,
    meal_plan_id: int | None = None,
) -> MachineGeneration | None:
    """Stage a MachineGeneration on ``session`` (committed by the caller).

    Returns the unflushed row so the caller can obtain its id after a flush and
    link corrections to it, or ``None`` if construction failed. Never raises.
    """
    try:
        assert surface in GENERATION_SURFACES, f"unknown generation surface {surface!r}"
        row = MachineGeneration(
            user_id=user_id,
            surface=surface,
            output_json=output_json,
            request_json=request_json,
            meal_plan_id=meal_plan_id,
        )
        session.add(row)
        return row
    except Exception:
        logger.exception("Failed to record machine generation (surface=%s)", surface)
        return None


def record_correction(
    session: AsyncSession,
    *,
    user_id: int,
    surface: str,
    after_json: str,
    before_json: str | None = None,
    generation_id: int | None = None,
    meal_plan_id: int | None = None,
    context: dict[str, int] | None = None,
) -> MachineCorrection | None:
    """Stage a MachineCorrection on ``session`` (committed by the caller).

    Callers should skip genuine no-ops (``before_json == after_json``) so the
    data reflects real edits only. Never raises.
    """
    try:
        assert surface in CORRECTION_SURFACES, f"unknown correction surface {surface!r}"
        row = MachineCorrection(
            user_id=user_id,
            surface=surface,
            after_json=after_json,
            before_json=before_json,
            generation_id=generation_id,
            meal_plan_id=meal_plan_id,
            context_json=context,
        )
        session.add(row)
        return row
    except Exception:
        logger.exception("Failed to record machine correction (surface=%s)", surface)
        return None


async def latest_generation_id(
    session: AsyncSession, meal_plan_id: int
) -> int | None:
    """Resolve the generation currently backing a plan's stored content.

    A plan can accrue several generations over its life (initial generate, then
    each regenerate); the most recent one backs its current ``response_json``.
    Ordered by ``id`` desc — monotonic and immune to same-timestamp ties.
    Returns ``None`` for plans generated before telemetry existed. Never raises.
    """
    try:
        result = await session.execute(
            select(MachineGeneration)
            .where(col(MachineGeneration.meal_plan_id) == meal_plan_id)
            .order_by(col(MachineGeneration.id).desc())
            .limit(1)
        )
        row = result.scalars().first()
        return row.id if row is not None else None
    except Exception:
        logger.exception(
            "Failed to resolve latest generation for plan %d", meal_plan_id
        )
        return None
