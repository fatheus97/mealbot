from datetime import UTC, date, datetime

from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import Boolean, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Column, Field, Relationship, SQLModel, String


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))

    hashed_password: str = Field(nullable=False)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # Whitelisted against app.core.country_whitelist at the API layer. Capped
    # at 60 chars to bound prompt-token use and match the longest canonical
    # name ("Saint Vincent and the Grenadines" is 32 chars — 60 is ample).
    country: str | None = Field(default=None, index=True, max_length=60)

    # "none" | "metric" | "imperial"
    measurement_system: str = Field(default="metric")

    # "traditional" | "experimental"
    variability: str = Field(default="traditional")

    # include spices in shopping list + stock
    include_spices: bool = Field(default=True)

    # preferred output language for LLM responses; whitelisted against
    # app.core.language_whitelist at the API layer. Capped at 50 chars to
    # bound prompt-token use and guard against pathological input.
    language: str = Field(default="English", max_length=50)

    # include snacks/ready-to-eat items from receipt scans
    track_snacks: bool = Field(default=True)

    # if false, frontend shows onboarding popup
    onboarding_completed: bool = Field(default=False, index=True)

    is_demo: bool = Field(default=False, index=True)

    # Preferred per-day meal-slot shape, e.g.
    #   ["sweet_breakfast", "snack", "main_course", "hot_dinner"]
    # NULL means the user hasn't set one — plan generation falls back to the
    # legacy meals_per_day counter. Values are validated against MealType at
    # the API layer; the column itself is a loose JSONB so historical or
    # migrated rows with legacy values don't break reads.
    default_day_layout: list[str] | None = Field(
        default=None,
        sa_column=Column(JSONB, nullable=True),
    )

    # Incremented on logout to revoke all outstanding JWTs for this user.
    # Tokens carry the version they were issued under ("tv" claim); requests
    # with a mismatched version are rejected in get_current_user.
    token_version: int = Field(default=0, sa_column_kwargs={"server_default": "0"}, nullable=False)

    fridge_items: list["StockItem"] = Relationship(back_populates="user")
    meal_plans: list["MealPlan"] = Relationship(back_populates="user")
    meal_entries: list["MealEntry"] = Relationship(back_populates="user")


class StockItem(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str = Field(index=True)
    quantity_grams: float = Field(ge=0)
    need_to_use: bool = Field(default=False, index=True)
    expiration_date: date | None = Field(default=None, index=True)

    user: "User" = Relationship(back_populates="fridge_items")


class MealPlan(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    days: int
    meals_per_day: int
    people_count: int

    # "planned" = the classic multi-day plan flow; "cook_now" = a one-shot
    # single-recipe cook (Phase 4). Kept as a plain str (not an enum column)
    # because future kinds are plausible and loose str avoids a migration
    # round-trip. The value is validated at the API layer.
    kind: str = Field(
        default="planned",
        sa_column_kwargs={"server_default": "planned"},
        nullable=False,
    )

    # For simplicity, we persist the raw request/response as JSON blobs.
    request_json: str  # store MealPlanRequest.model_dump_json()
    response_json: str  # store MealPlanResponse.model_dump_json()
    confirmed_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    stock_after_json: str | None = Field(default=None)

    user: "User" = Relationship(back_populates="meal_plans")
    meal_entries: list["MealEntry"] = Relationship(back_populates="meal_plan")

class MealEntry(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    meal_plan_id: int = Field(foreign_key="mealplan.id", index=True)
    day_index: int = Field(description="Which day of the plan this meal belongs to (1-based).")
    meal_index: int = Field(description="Index of the meal within the day (1-based).")
    name: str = Field(index=True)
    # Loose str at the DB layer. Current taxonomy values are validated via
    # PlannedMeal.meal_type (MealType enum); the column also holds legacy
    # "breakfast"/"lunch"/"dinner"/"snack" rows that PlannedMeal's pre-validator
    # translates on deserialization. Keeping this loose avoids a one-way
    # backfill and lets catalog/history endpoints return raw values the
    # frontend's mealTypeLabel() helper can render.
    meal_type: str = Field(index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    cooked_at: datetime | None = Field(default=None)
    # Cookbook membership: starring a meal sets this True and triggers embedding
    # generation; un-starring clears both. Replaces the legacy 1–5 rating column —
    # we lost the granularity intentionally to keep the cookbook UX a single bit.
    #
    # No standalone index here — the composite (user_id, is_favorite) index
    # created in migration o5p6q7r8s9t0 covers every hot path (cookbook list,
    # count, RAG threshold check). Keeping index=True would make Alembic
    # autogenerate add a redundant single-column index next time it runs.
    is_favorite: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    # Keep details as JSON for now (ingredients, steps, etc.)
    meal_json: str = Field(
        description="Full PlannedMeal JSON (ingredients, steps, etc.)."
    )

    # Per-meal snapshot of which fridge batches were debited at confirm time.
    # JSON list[ConsumedBatch]. NULL on legacy rows (pre-migration); finish_plan
    # falls back to a lossy name+grams restore via restore_consumed_batches for
    # those — expiration_date and need_to_use are not recoverable.
    consumed_snapshot_json: str | None = Field(default=None)

    # RAG embedding — 384d from all-MiniLM-L6-v2, generated when is_favorite=True
    embedding: list[float] | None = Field(
        default=None, sa_column=Column(Vector(384), nullable=True)
    )

    user: "User" = Relationship(back_populates="meal_entries")
    meal_plan: "MealPlan" = Relationship(back_populates="meal_entries")

    __table_args__ = (
        Index(
            "ix_mealentry_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
