"""EUR cost estimation for LLM calls — the money side of the usage budget cap.

Turns LlmUsage token counts into an EUR figure so app.services.usage_budget can
enforce a per-user monthly budget by *spend* rather than by a raw request count
(a €0.009 single recipe and a €0.06 seven-day plan must not weigh the same).

Rates are provider list prices (USD) converted to EUR and rounded conceptually
UP via a conservative FX, so the estimate errs toward blocking a hair early rather
than overspending. They live in code, not env: provider/model are server-controlled
(from LLM_MODELS), change rarely, and co-locating them with the cost formula keeps
the thinking-token nuance in one place. This is a fuzzy safety valve, not an
invoice — exact FX and list-price drift are immaterial for a ~€2 cap, and
over-estimation fails safe.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.models.db_models import LlmUsage

# USD → EUR. A fuzzy cap doesn't need precision; over-estimation fails safe.
_USD_EUR = 0.92


@dataclass(frozen=True)
class ModelRate:
    """EUR cost per single token, input and output side."""

    input_eur_per_token: float
    output_eur_per_token: float


# Keyed on (provider, model). Derived from published USD per-1M-token pricing
# × _USD_EUR, expressed per single token. Gemini 2.5 Flash: $0.30/1M in, $2.50/1M
# out; Flash-Lite: $0.10/1M in, $0.40/1M out (ai.google.dev/gemini-api/docs/pricing).
MODEL_COST_RATES: dict[tuple[str, str], ModelRate] = {
    ("gemini", "gemini-2.5-flash"): ModelRate(
        0.30 * _USD_EUR / 1_000_000, 2.50 * _USD_EUR / 1_000_000
    ),
    ("gemini", "gemini-2.5-flash-lite"): ModelRate(
        0.10 * _USD_EUR / 1_000_000, 0.40 * _USD_EUR / 1_000_000
    ),
}

# Unknown (provider, model) → the MOST EXPENSIVE known rate, so a model swap or
# config drift never silently under-bills the cap (fail-safe on the cost side).
_FALLBACK_RATE = ModelRate(
    max(r.input_eur_per_token for r in MODEL_COST_RATES.values()),
    max(r.output_eur_per_token for r in MODEL_COST_RATES.values()),
)


def rate_for(provider: str, model: str) -> ModelRate:
    return MODEL_COST_RATES.get((provider, model), _FALLBACK_RATE)


def cost_of(prompt_tokens: int, total_tokens: int, provider: str, model: str) -> float:
    """EUR cost of one call.

    The output side is ``total − prompt``, NOT ``completion_tokens``: Gemini 2.5
    bills reasoning/"thinking" tokens at the output rate and excludes them from
    the completion count while including them in total (see the LlmUsage docstring:
    "total ≫ prompt+candidates"). Charging completion alone undercounts and lets
    the cap leak. A malformed row where total < prompt clamps the output side to 0.
    """
    rate = rate_for(provider, model)
    output_tokens = max(0, total_tokens - prompt_tokens)
    return (
        prompt_tokens * rate.input_eur_per_token
        + output_tokens * rate.output_eur_per_token
    )


async def compute_window_cost(
    session: AsyncSession, *, user_id: int, window_start: datetime
) -> float:
    """Sum the EUR cost of a user's LLM calls with ``created_at >= window_start``.

    One grouped query over (provider, model) folded through the rate map — exact
    (no counter drift) and index-served by ix_llmusage_user_created. Cheap at this
    scale; revisit with a materialized counter only at ~10^4–10^5 active users.
    ``window_start`` MUST be naive UTC to match the tz-naive created_at column.
    """
    result = await session.execute(
        select(
            col(LlmUsage.provider),
            col(LlmUsage.model),
            func.coalesce(func.sum(col(LlmUsage.prompt_tokens)), 0),
            func.coalesce(func.sum(col(LlmUsage.total_tokens)), 0),
        )
        .where(col(LlmUsage.user_id) == user_id)
        .where(col(LlmUsage.created_at) >= window_start)
        .group_by(col(LlmUsage.provider), col(LlmUsage.model))
    )
    total = 0.0
    for row in result.all():
        total += cost_of(int(row[2]), int(row[3]), str(row[0]), str(row[1]))
    return total
