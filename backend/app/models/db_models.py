from datetime import datetime, timezone
from typing import Optional, List

from sqlmodel import SQLModel, Field, Relationship, Column, String
from sqlalchemy.dialects.sqlite import BLOB


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Used for ingredient availability + local recipes
    country: str | None = Field(default=None, index=True)

    # "none" | "metric" | "imperial"
    measurement_system: str = Field(default="metric")

    # "traditional" | "experimental"
    variability: str = Field(default="traditional")

    # include spices in shopping list + stock
    include_spices: bool = Field(default=True)

    # if false, frontend shows onboarding popup
    onboarding_completed: bool = Field(default=False, index=True)

    fridge_items: List["StockItem"] = Relationship(back_populates="user")
    meal_plans: List["MealPlan"] = Relationship(back_populates="user")
    meal_entries: List["MealEntry"] = Relationship(back_populates="user")


class StockItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(index=True)
    quantity_grams: float = Field(ge=0)
    need_to_use: bool = Field(default=False, index=True)

    user: "User" = Relationship(back_populates="fridge_items")


class MealPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    days: int
    meals_per_day: int
    people_count: int

    # For simplicity, we persist the raw request/response as JSON blobs.
    request_json: str  # store MealPlanRequest.model_dump_json()
    response_json: str  # store MealPlanResponse.model_dump_json()
    confirmed_at: datetime | None = Field(default=None)
    stock_after_json: str | None = Field(default=None)

    user: "User" = Relationship(back_populates="meal_plans")
    meal_entries: List["MealEntry"] = Relationship(back_populates="meal_plan")

class MealEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    meal_plan_id: int = Field(foreign_key="mealplan.id", index=True)
    day_index: int = Field(description="Which day of the plan this meal belongs to (1-based).")
    meal_index: int = Field(description="Index of the meal within the day (1-based).")
    name: str = Field(index=True)
    meal_type: str = Field(index=True)  # "breakfast", "lunch", ...
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # Keep details as JSON for now (ingredients, steps, etc.)
    meal_json: str = Field(
        description="Full PlannedMeal JSON (ingredients, steps, etc.)."
    )

    user: "User" = Relationship(back_populates="meal_entries")
    meal_plan: "MealPlan" = Relationship(back_populates="meal_entries")


class RecipeRow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    ingredients_text: str  # "chicken breast; rice; spinach"
    steps_text: str
    cuisine: Optional[str] = Field(default=None, index=True)
    tags_text: str = Field(default="")  # "asian; spicy"

    # embedding uložíme jako binární blob (np.ndarray.tobytes())
    embedding: bytes = Field(sa_column=Column(BLOB))