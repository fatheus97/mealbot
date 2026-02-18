from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class StockItemDTO(BaseModel):
    name: str
    quantity_grams: float
    need_to_use: bool = Field(default=False)


class MealPlanRequest(BaseModel):
    """Request for planning meals (potentially multiple days, one day per LLM call)."""
    stock_items: List[StockItemDTO] = Field(
        default_factory=list,
        description="Current fridge/pantry state in grams per ingredient.",
    )
    taste_preferences: List[str] = Field(
        default_factory=list,
        description="Tags like 'spicy', 'asian', 'comfort', 'light', 'vegetarian'.",
    )
    avoid_ingredients: List[str] = Field(
        default_factory=list,
        description="Ingredients that must not be used (allergies, dislikes).",
    )
    diet_type: Optional[
        Literal["balanced", "high_protein", "low_carb", "vegetarian", "vegan"]
    ] = None
    meals_per_day: int = Field(
        ge=1,
        le=6,
        default=3,
        description="Number of meals to plan per day.",
    )
    people_count: int = Field(
        ge=1,
        le=10,
        default=2,
        description="Number of people to plan the meals for.",
    )
    past_meals: List[str] = Field(
        default_factory=list,
        description="Meal names eaten recently (to avoid similar dishes).",
    )

    country: Optional[str] = Field(
        default=None,
        description="User country for ingredient availability and local recipes.",
    )

    measurement_system: Literal["none", "metric", "imperial"] = Field(
        default="metric",
        description="Preferred measurement system for step wording only. JSON quantities must stay grams.",
    )

    variability: Literal["traditional", "experimental"] = Field(
        default="traditional",
        description="Recipe style preference.",
    )

    include_spices: bool = Field(
        default=True,
        description="Whether spices/seasonings should appear in ingredients & shopping list.",
    )


class IngredientAmount(BaseModel):
    """Amount of a single ingredient, expressed in grams."""
    name: str = Field(description="Canonical ingredient name, e.g. 'chicken breast'.")
    quantity_grams: float = Field(
        ge=0,
        description="Amount in grams for this ingredient (total for all people).",
    )


class PlannedMeal(BaseModel):
    name: str
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    ingredients: List[IngredientAmount]
    steps: List[str]


class SingleDayResponse(BaseModel):
    """LLM response for a single day (raw output from the model)."""
    meals: List[PlannedMeal]


class MealPlanResponse(BaseModel):
    """Multi-day plan returned by the /plan endpoint."""
    plan_id: int | None
    days: List[SingleDayResponse]
    shopping_list: List[IngredientAmount]

class MealHistoryItem(BaseModel):
        meal_entry_id: int
        meal_plan_id: int
        day_index: int
        meal_index: int
        name: str
        meal_type: str
        created_at: datetime
