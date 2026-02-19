from collections import defaultdict
from datetime import datetime
from typing import List, Dict, cast, Literal
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.api.fridge import get_fridge_items, replace_fridge_items
from app.models.db_models import User, StockItem, MealPlan, MealEntry
from app.models.plan_models import MealPlanRequest, MealPlanResponse, SingleDayResponse, StockItemDTO, IngredientAmount
from app.services.meal_planner import generate_single_day
from app.utils import subtract_used_from_fridge, compute_shopping_list_from_plan
from app.db import get_session

router = APIRouter()
MeasurementSystem = Literal["none", "metric", "imperial"]
Variability = Literal["traditional", "experimental"]


@router.post("/users/{user_id}/plan", response_model=MealPlanResponse)
async def plan_meals_for_user(
    user_id: int,
    days: int,
    payload: MealPlanRequest,
    session: Session = Depends(get_session),
) -> MealPlanResponse:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    payload.country = user.country

    ms_raw = (user.measurement_system or "metric").strip().lower()
    if ms_raw not in ("none", "metric", "imperial"):
        ms_raw = "metric"
    payload.measurement_system = cast(MeasurementSystem, ms_raw)

    var_raw = (user.variability or "traditional").strip().lower()
    if var_raw not in ("traditional", "experimental"):
        var_raw = "traditional"
    payload.variability = cast(Variability, var_raw)

    payload.include_spices = bool(user.include_spices)

    # Load fridge from DB
    db_items = session.exec(
        select(StockItem).where(StockItem.user_id == user_id)
    ).all()
    remaining_ingredients: List[StockItemDTO] = [
        StockItemDTO(name=item.name, quantity_grams=item.quantity_grams, need_to_use=item.need_to_use)
        for item in db_items
    ]

    initial_fridge: List[StockItemDTO] = [
        ing.model_copy() for ing in remaining_ingredients
    ]

    past_meals: List[str] = list(payload.past_meals)
    meal_plan: List[SingleDayResponse] = []

    for day_index in range(1, days + 1):
        day_req = payload.model_copy()
        day_req.stock_items = remaining_ingredients
        day_req.past_meals = past_meals

        single_day = await generate_single_day(day_req)
        meal_plan.append(single_day)

        remaining_ingredients = subtract_used_from_fridge(remaining_ingredients, single_day.meals)
        past_meals.extend(m.name for m in single_day.meals)

    shopping_items: List[IngredientAmount] = compute_shopping_list_from_plan(meal_plan, initial_fridge)

    response_obj = MealPlanResponse(
        plan_id=None,
        days=meal_plan,
        shopping_list=shopping_items,
    )

    # Save MealPlan to DB
    plan = MealPlan(
        user_id=user_id,
        days=days,
        meals_per_day=payload.meals_per_day,
        people_count=payload.people_count,
        request_json=payload.model_dump_json(),
        response_json=response_obj.model_dump_json(),
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)
    response_obj.plan_id = plan.id

    return response_obj

@router.post("/users/{user_id}/plans/{plan_id}/confirm", response_model=List[StockItemDTO])
def confirm_plan(
    user_id: int,
    plan_id: int,
    session: Session = Depends(get_session),
) -> List[StockItemDTO]:
    # 1) Validate user
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 2) Load plan & ownership check
    plan = session.get(MealPlan, plan_id)
    if not plan or plan.user_id != user_id:
        raise HTTPException(status_code=404, detail="Plan not found")

    # 3) Idempotence guard (do not subtract twice)
    if hasattr(plan, "confirmed_at") and getattr(plan, "confirmed_at"):
        # Do nothing, just return current fridge
        return get_fridge_items(session, user_id)

    # 4) Parse stored plan response
    try:
        plan_obj = MealPlanResponse.model_validate_json(plan.response_json)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Plan response_json is not valid for MealPlanResponse: {e}",
        )

    needed = _extract_needed_grams(plan_obj)

    # 5) Load current fridge and subtract
    fridge = get_fridge_items(session, user_id)
    by_name: Dict[str, StockItemDTO] = {_norm(x.name): x for x in fridge if _norm(x.name)}

    for ing_name, need_qty in needed.items():
        item = by_name.get(ing_name)
        if not item:
            continue  # ingredient not in fridge => nothing to subtract
        have = float(item.quantity_grams or 0.0)
        item.quantity_grams = max(0.0, have - need_qty)

    # Remove depleted items
    updated_fridge = [x for x in fridge if float(x.quantity_grams or 0.0) > 0.0]

    # 6) Persist fridge via shared helper
    updated_fridge = replace_fridge_items(session, user_id, updated_fridge)

    # 7) Persist meal history entries (one row per meal)
    _persist_meal_entries(session, user_id=user_id, plan_id=plan_id, plan_obj=plan_obj)

    plan.confirmed_at = datetime.now()

    session.add(plan)
    session.commit()

    return updated_fridge

def _norm(name: str) -> str:
    return " ".join((name or "").strip().lower().split())


def _extract_needed_grams(plan: MealPlanResponse) -> Dict[str, float]:
    """
    Sum ingredient usage across all days/meals.
    Assumes each meal has ingredients: List[{name, quantity_grams}].
    """
    totals: Dict[str, float] = defaultdict(float)

    for day in plan.days:
        for meal in day.meals:
            for ing in meal.ingredients:
                key = _norm(ing.name)
                qty = float(getattr(ing, "quantity_grams", 0.0) or 0.0)
                if key and qty > 0:
                    totals[key] += qty

    return dict(totals)

def _persist_meal_entries(
    session: Session,
    user_id: int,
    plan_id: int,
    plan_obj: MealPlanResponse,
) -> None:
    entries: List[MealEntry] = []

    for day_index, day in enumerate(plan_obj.days, start=1):
        for meal_index, meal in enumerate(day.meals, start=1):
            entries.append(
                MealEntry(
                    user_id=user_id,
                    meal_plan_id=plan_id,
                    day_index=day_index,
                    meal_index=meal_index,
                    name=meal.name,
                    meal_type=meal.meal_type,
                    meal_json=meal.model_dump_json(),  # full PlannedMeal JSON
                )
            )

    if entries:
        session.add_all(entries)
