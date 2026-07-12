"""Best-effort persistence of per-call LLM token usage.

Pairs with app.llm.usage: the client captures each call's ``LlmCallUsage`` into a
request-scoped bucket; the route drains that bucket and calls
``record_llm_usage`` next to its ``record_generation`` call, so the usage rows
ride the same transaction (recorded iff the user action commits).

Same contract as app.services.telemetry — never raises, values are all
server-controlled, ``surface`` is a server-side constant.
"""

import logging
from collections.abc import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.usage import LlmCallUsage
from app.models.db_models import LlmUsage

logger = logging.getLogger(__name__)

# Surfaces that produce billable LLM calls. Mirrors telemetry.GENERATION_SURFACES;
# kept as its own set so a usage-only surface (should one appear) needn't be a
# generation surface. Checked so a typo'd surface is logged-and-skipped.
USAGE_SURFACES = frozenset(
    {"meal_plan", "single_recipe", "receipt_scan", "regenerate"}
)


def record_llm_usage(
    session: AsyncSession,
    *,
    user_id: int,
    surface: str,
    usages: Iterable[LlmCallUsage],
    meal_plan_id: int | None = None,
) -> None:
    """Stage one LlmUsage row per captured call on ``session`` (committed by the
    caller). No-op for an empty ``usages``. Never raises.

    Rides the caller's transaction, so if the request raises before it commits,
    the whole request's usage is dropped — including earlier calls that already
    succeeded (a multi-day plan batches all days into one bucket). See LlmUsage
    for the full billing-scope caveat.
    """
    try:
        if surface not in USAGE_SURFACES:
            raise ValueError(f"unknown usage surface {surface!r}")
        for usage in usages:
            session.add(
                LlmUsage(
                    user_id=user_id,
                    surface=surface,
                    provider=usage.provider,
                    model=usage.model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    meal_plan_id=meal_plan_id,
                )
            )
    except Exception:
        logger.exception("Failed to record LLM usage (surface=%s)", surface)
