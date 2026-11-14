"""Rank the ingredient keys the nutrition table lacks, by grams over stored plans.

Read-only; the input to the next round of reviewed alias rows
(docs/nutrition-design.md, "Growth after launch"):

    docker compose exec backend python -m app.scripts.nutrition_gaps [--top 100]

It prints keys, counts and grams only, and only for keys seen in plans of at
least MIN_HOUSEHOLDS different households. Ingredient lists can reveal diets,
and the session that turns these keys into alias rows runs on Claude, which the
privacy policy does not name as a processor, so one household's free text and
diet hints never leave the server through this report.

Only meals stamped with grams_basis count: older meals never get a figure, and
their spellings predate the weight rule.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col, select

from app.core.nutrition_reference import Lang, NutritionReference, nutrition_reference
from app.db import async_session_factory
from app.models.db_models import MealPlan
from app.models.plan_models import MealPlanResponse
from app.services.nutrition import missing_key

MIN_HOUSEHOLDS = 3


@dataclass
class Gap:
    lang: Lang
    key: str
    grams: float = 0.0
    count: int = 0
    households: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class StoredPlan:
    household_id: int
    request_json: str
    response_json: str


def rank_gaps(plans: Iterable[StoredPlan], ref: NutritionReference) -> tuple[list[Gap], int]:
    """Gaps seen in at least MIN_HOUSEHOLDS households, most grams first, and
    the number of plans that could not be read."""
    gaps: dict[tuple[Lang, str], Gap] = {}
    unreadable = 0
    for plan in plans:
        try:
            language = json.loads(plan.request_json).get("language")
            days = MealPlanResponse.model_validate_json(plan.response_json).days
        except (ValueError, ValidationError, AttributeError):
            unreadable += 1
            continue
        for meal in (m for day in days for m in day.meals):
            if meal.grams_basis is None:
                continue
            for ing in meal.ingredients:
                key = missing_key(ing, language if isinstance(language, str) else None, ref)
                if key is None:
                    continue
                gap = gaps.setdefault(key, Gap(lang=key[0], key=key[1]))
                gap.grams += ing.quantity_grams
                gap.count += 1
                gap.households.add(plan.household_id)
    shared = [g for g in gaps.values() if len(g.households) >= MIN_HOUSEHOLDS]
    return sorted(shared, key=lambda g: (-g.grams, g.lang, g.key)), unreadable


async def _stored_plans() -> list[StoredPlan]:
    # ponytail: every planned plan in memory at once; stream with yield_per
    # once the table holds more than a few thousand plans.
    async with async_session_factory() as session:
        rows = await session.execute(
            select(MealPlan.household_id, MealPlan.request_json, MealPlan.response_json)
            .where(col(MealPlan.kind) == "planned")
        )
        return [StoredPlan(household_id=h, request_json=q, response_json=r) for h, q, r in rows.all()]


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Rank unmapped nutrition keys by grams.")
    parser.add_argument("--top", type=int, default=100, help="rows to print (default 100)")
    args = parser.parse_args(argv)
    try:
        plans = asyncio.run(_stored_plans())
    except (SQLAlchemyError, OSError) as exc:
        # The driver's own error, not SQLAlchemy's str(), which appends the
        # statement and its parameters. A refused connect is a bare OSError.
        cause = getattr(exc, "orig", None) or exc
        raise SystemExit(f"could not read the stored plans: {type(exc).__name__}: {cause}") from exc
    ranked, unreadable = rank_gaps(plans, nutrition_reference())
    print(f"{len(ranked)} keys missing in at least {MIN_HOUSEHOLDS} households; "
          f"{unreadable} plans could not be read")
    print("lang\tkey\tcount\tgrams")
    for gap in ranked[: args.top]:
        print(f"{gap.lang}\t{gap.key}\t{gap.count}\t{gap.grams:.0f}")


if __name__ == "__main__":
    main()
