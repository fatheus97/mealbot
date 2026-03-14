import re
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator
from datetime import date, datetime, timezone


class StockItemDTO(BaseModel):
    name: str
    quantity_grams: float
    need_to_use: bool = Field(default=False)
    expiration_date: date | None = None


class MealPlanRequest(BaseModel):
    """Request for planning meals (potentially multiple days, one day per LLM call)."""
    stock_items: List[StockItemDTO] = Field(
        default_factory=list,
        description="Current fridge/pantry state in grams per ingredient.",
    )
    taste_preferences: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="Tags like 'spicy', 'asian', 'comfort', 'light', 'vegetarian'.",
    )
    avoid_ingredients: List[str] = Field(
        default_factory=list,
        max_length=50,
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

    language: str = Field(
        default="English",
        description="Language for all LLM output (meal names, steps, ingredient names).",
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

    stock_only: bool = Field(
        default=False,
        description="When true, only fridge/pantry ingredients may be used — no shopping.",
    )

    @field_validator("taste_preferences", "avoid_ingredients", "past_meals", mode="before")
    @classmethod
    def sanitize_input(cls, v):
        # Handle cases where the input might be None
        if not v:
            return []

        cleaned_list = []
        for item in v:
            # Enforce length limit per tag (drop it if it's too long instead of crashing the whole request)
            if len(item) > 50:
                continue

                # Whitelist: Allow only alphanumeric, spaces, and hyphens.
            cleaned = re.sub(r'[^a-zA-Z0-9\s-]', '', item).strip()
            if cleaned:
                cleaned_list.append(cleaned)

        # Optional: Limit the total number of items to prevent prompt stuffing
        return cleaned_list[:20]


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

class FrozenMeal(BaseModel):
    """Identifies a meal the user wants to keep unchanged during regeneration."""
    day_index: int = Field(ge=0, description="0-based day index in the plan")
    meal_index: int = Field(ge=0, description="0-based meal index within the day")


class RegeneratePlanRequest(BaseModel):
    """Request to regenerate unfrozen meals in an existing plan."""
    frozen_meals: List[FrozenMeal] = Field(
        default_factory=list,
        description="Meals that should NOT be regenerated.",
    )


class ScannedReceiptItem(BaseModel):
    """Single item extracted from a receipt by the LLM."""
    name: str = Field(..., description="Canonical grocery item name, e.g. 'chicken breast'")
    quantity_grams: float = Field(..., description="Estimated weight in grams")
    item_type: Literal["ingredient", "ready_to_eat"] = Field(
        ...,
        description="'ingredient' for items you cook with, 'ready_to_eat' for snacks/desserts/drinks",
    )
    shelf_life_days: int = Field(
        ...,
        ge=0,
        le=730,
        description="Estimated days from purchase until typical expiration when stored properly",
    )

    @field_validator("quantity_grams")
    @classmethod
    def validate_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Quantity must be positive.")
        if v > 50_000:
            raise ValueError("Quantity unrealistically high (>50kg).")
        return v


class ReceiptScanResponse(BaseModel):
    """LLM response model for receipt extraction."""
    purchase_date: date | None = Field(
        default=None,
        description="Transaction date from the receipt (YYYY-MM-DD). None if not visible.",
    )
    items: List[ScannedReceiptItem]


class ScannedItemDTO(BaseModel):
    """Item returned to the frontend after receipt scan, before merge."""
    name: str
    quantity_grams: float
    need_to_use: bool = False
    item_type: Literal["ingredient", "ready_to_eat"]
    expiration_date: date | None = None


class NormalizedName(BaseModel):
    """Maps a scanned item name to its canonical normalized form."""
    original: str
    normalized: str


class NormalizationResponse(BaseModel):
    """LLM response model for ingredient name normalization."""
    items: List[NormalizedName]


class MealHistoryItem(BaseModel):
        meal_entry_id: int
        meal_plan_id: int
        day_index: int
        meal_index: int
        name: str
        meal_type: str
        created_at: datetime


class MealPlanSummary(BaseModel):
    """List item for the plan catalog."""
    id: int
    created_at: datetime
    days: int
    meals_per_day: int
    people_count: int
    status: Literal["planned", "active", "cooked", "finished"]
    total_meals: int
    cooked_meals: int
    finished_at: datetime | None = None

    @field_validator("created_at", "finished_at", mode="before")
    @classmethod
    def ensure_utc(cls, v: datetime | None) -> datetime | None:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class FinishPlanResponse(BaseModel):
    status: Literal["finished"]
    finished_at: datetime
    returned_meals: int

    @field_validator("finished_at", mode="before")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        """DB may return naive datetimes — attach UTC so serialization is consistent."""
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class RateMealRequest(BaseModel):
    """Request body for rating a meal (1-5 stars)."""
    rating: int = Field(ge=1, le=5)


class MealEntrySummary(BaseModel):
    """Single meal within a plan detail view."""
    id: int
    day_index: int
    meal_index: int
    name: str
    meal_type: str
    cooked_at: datetime | None
    rating: int | None = None
