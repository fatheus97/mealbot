import re
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator
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

    @field_validator("taste_preferences", check_fields=False)
    def sanitize_input(self, v):
        cleaned_list = []
        for item in v:
            # Enforce length limit per tag
            if len(item) > 50:
                raise ValueError("Preference tag too long")

            # Whitelist: Allow only alphanumeric, spaces, and hyphens.
            # Remove any special characters that could be used for injection syntax.
            cleaned = re.sub(r'[^a-zA-Z0-9\s-]', '', item).strip()
            if cleaned:
                cleaned_list.append(cleaned)
        return cleaned_list


class IngredientAmount(BaseModel):
    """Amount of a single ingredient, expressed in grams."""
    name: str = Field(..., description="The canonical name of the ingredient (e.g., 'chicken breast').")
    quantity_grams: float = Field(...,
                                  description="The weight in grams. If the recipe uses volume (cups), estimate the weight.")

    @field_validator("quantity_grams")
    @classmethod
    def validate_realistic_amount(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be positive.")
        if v > 10000:
            raise ValueError("Quantity is unrealistically high (>10kg). Verify units.")
        return v


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
