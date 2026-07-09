import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.meal_types import LEGACY_MEAL_TYPE_MAP, MealType


class StockItemDTO(BaseModel):
    # Client-controlled on PUT /fridge and POST /fridge/merge, and each name is
    # templated into the LLM system prompt — so bound it like the other hostile-
    # input string paths (IngredientAmount/PlannedMeal). `ge=0` + allow_inf_nan
    # reject negative / NaN / inf (NaN would otherwise slip past the `qty <= 0`
    # persist filter). Deliberately NO upper cap: this DTO is also reconstructed
    # internally from summed quantities (merge, restore) which can legitimately
    # exceed any single-value cap — a cap there would 500 an ordinary merge.
    name: str = Field(..., min_length=1, max_length=100)
    quantity_grams: float = Field(..., ge=0, allow_inf_nan=False)
    need_to_use: bool = Field(default=False)
    expiration_date: date | None = None


class MealPlanRequest(BaseModel):
    """Request for planning meals (potentially multiple days, one day per LLM call)."""
    stock_items: list[StockItemDTO] = Field(
        default_factory=list,
        description="Current fridge/pantry state in grams per ingredient.",
    )
    taste_preferences: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Tags like 'spicy', 'asian', 'comfort', 'light', 'vegetarian'.",
    )
    avoid_ingredients: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="Ingredients that must not be used (allergies, dislikes).",
    )
    ingredients_to_use: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Priority ingredients the user wants used in this plan run; treated with urgency.",
    )
    diet_type: Literal["balanced", "high_protein", "low_carb", "vegetarian", "vegan", "baby_food"] | None = None
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
    past_meals: list[str] = Field(
        default_factory=list,
        description="Meal names eaten recently (to avoid similar dishes).",
    )

    language: str = Field(
        default="English",
        description="Language for all LLM output (meal names, steps, ingredient names).",
    )

    country: str | None = Field(
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

    # Per-day meal-slot override. Outer list = one entry per day; inner list =
    # the ordered MealType slots for that day (1-8 entries). When supplied it
    # takes precedence over both the user's saved default_day_layout and the
    # legacy meals_per_day counter. Outer-list length is reconciled against the
    # `days` query param at the endpoint layer.
    day_layouts: list[list[MealType]] | None = Field(
        default=None,
        max_length=7,
    )

    @field_validator("day_layouts")
    @classmethod
    def validate_day_layouts(
        cls, v: list[list[MealType]] | None,
    ) -> list[list[MealType]] | None:
        if v is None:
            return None
        for i, day in enumerate(v):
            if not 1 <= len(day) <= 8:
                raise ValueError(
                    f"day_layouts[{i}] must have between 1 and 8 slots, got {len(day)}",
                )
        return v

    @field_validator(
        "taste_preferences",
        "avoid_ingredients",
        "ingredients_to_use",
        "past_meals",
        mode="before",
    )
    @classmethod
    def sanitize_input(cls, v):
        if not v:
            return []

        cleaned_list = []
        for item in v:
            if not isinstance(item, str):
                continue
            if len(item) > 50:
                continue
            # Unicode-aware whitelist: keep letters (incl. Czech/European diacritics),
            # digits, spaces, and a small set of harmless punctuation. Still blocks
            # prompt-injection vectors like { } < > | ` $ \ / etc.
            cleaned = re.sub(r"[^\w\s\-,.]", "", item, flags=re.UNICODE).strip()
            if cleaned:
                cleaned_list.append(cleaned)

        return cleaned_list[:20]


class IngredientAmount(BaseModel):
    """Amount of a single ingredient, expressed in grams."""
    # Bounds: Cook Now (Phase 4+) accepts PlannedMeal from the client. These
    # caps prevent a crafted request from stuffing the indexed MealEntry.name
    # column or meal_json blob with unbounded data.
    name: str = Field(..., max_length=100,
                      description="The canonical name of the ingredient (e.g., 'chicken breast').")
    quantity_grams: float = Field(...,
                                  description="The weight in grams. If the recipe uses volume (cups), estimate the weight.")
    is_spice: bool = Field(default=False, description="True for spices/herbs/seasonings when include_spices is off.")

    @field_validator("quantity_grams")
    @classmethod
    def validate_realistic_amount(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be positive.")
        if v > 10000:
            raise ValueError("Quantity is unrealistically high (>10kg). Verify units.")
        return v


class ConsumedBatch(BaseModel):
    """A specific fridge batch (with its expiration + need_to_use) charged to a meal at confirm time."""
    name: str
    quantity_grams: float
    expiration_date: date | None = None
    need_to_use: bool = False


class PlannedMeal(BaseModel):
    # Bounds apply to the client-write path (Cook Now /recipe/cook) — the LLM
    # output path doesn't reach these limits in practice, but sizing them here
    # rather than at the API layer keeps all PlannedMeal use-sites protected.
    name: str = Field(..., max_length=200)
    meal_type: MealType
    meal_type_label: str = Field(default="", max_length=100)
    ingredients: list[IngredientAmount] = Field(..., max_length=40)
    steps: list[str] = Field(..., max_length=50)
    # Optional so legacy meal_json rows (pre-feature) still parse during RAG retrieval.
    # New generations are instructed by the prompt to always populate it.
    total_time_minutes: int | None = Field(
        default=None,
        ge=1,
        le=600,
        description="Total time from prep start to finish, including cook and rest, in minutes.",
    )

    @field_validator("meal_type", mode="before")
    @classmethod
    def translate_legacy_meal_type(cls, v: object) -> object:
        # Pre-taxonomy meal_json rows stored "breakfast"/"lunch"/"dinner"/"snack".
        # Map them onto the new enum so DB reads (RAG, history) still deserialize.
        if isinstance(v, str) and v in LEGACY_MEAL_TYPE_MAP:
            return LEGACY_MEAL_TYPE_MAP[v]
        return v

    @field_validator("steps")
    @classmethod
    def cap_step_length(cls, v: list[str]) -> list[str]:
        # Per-item cap the list-level `max_length=50` can't express. Keeps
        # the client-write path (Cook Now) from storing a 10 MB "step" in
        # meal_json. 1000 chars is well above realistic recipe step length.
        for i, step in enumerate(v):
            if len(step) > 1000:
                raise ValueError(f"steps[{i}] exceeds 1000 characters")
        return v


class MealEditRequest(BaseModel):
    """User-edited content for a single meal (name, ingredients, steps, time).

    meal_type / meal_type_label are intentionally absent: editing a meal's slot
    would desync the plan's day layout and the RAG taxonomy, so the edit
    endpoint preserves the existing slot and only rewrites content. Bounds
    mirror PlannedMeal so an edit can't smuggle in data a freshly-generated
    meal couldn't hold (this is a client-write path — treat input as hostile).
    """
    name: str = Field(..., min_length=1, max_length=200)
    ingredients: list[IngredientAmount] = Field(..., max_length=40)
    steps: list[str] = Field(..., max_length=50)
    total_time_minutes: int | None = Field(default=None, ge=1, le=600)

    @field_validator("steps")
    @classmethod
    def cap_step_length(cls, v: list[str]) -> list[str]:
        # Same per-item cap as PlannedMeal.steps — duplicated (not shared) to
        # keep the model layer free of cross-references, matching the
        # sanitize_input duplication in SingleRecipeRequest.
        for i, step in enumerate(v):
            if len(step) > 1000:
                raise ValueError(f"steps[{i}] exceeds 1000 characters")
        return v


class SingleDayResponse(BaseModel):
    """LLM response for a single day (raw output from the model)."""
    meals: list[PlannedMeal]


class MealPlanResponse(BaseModel):
    """Multi-day plan returned by the /plan endpoint."""
    plan_id: int | None
    days: list[SingleDayResponse]
    shopping_list: list[IngredientAmount]

class FrozenMeal(BaseModel):
    """Identifies a meal the user wants to keep unchanged during regeneration."""
    day_index: int = Field(ge=0, description="0-based day index in the plan")
    meal_index: int = Field(ge=0, description="0-based meal index within the day")


class RegeneratePlanRequest(BaseModel):
    """Request to regenerate unfrozen meals in an existing plan."""
    frozen_meals: list[FrozenMeal] = Field(
        default_factory=list,
        description="Meals that should NOT be regenerated.",
    )


class ScannedReceiptItem(BaseModel):
    """Single item extracted from a receipt by the LLM."""
    # Cap the LLM-produced name at the source: instructor retries to conform, and
    # it guarantees the downstream ScannedItemDTO (max_length=100) never fails
    # construction on a crafted-receipt long name (which would 500 the scan).
    name: str = Field(
        ..., min_length=1, max_length=100,
        description="Canonical grocery item name, e.g. 'chicken breast'",
    )
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
    items: list[ScannedReceiptItem]


class ScannedItemDTO(BaseModel):
    """Item returned to the frontend after receipt scan, before merge."""
    # Same hostile-input bounds as StockItemDTO (this rides the same fridge path).
    name: str = Field(..., min_length=1, max_length=100)
    quantity_grams: float = Field(..., ge=0, allow_inf_nan=False)
    need_to_use: bool = False
    item_type: Literal["ingredient", "ready_to_eat"]
    expiration_date: date | None = None


class ScannedItemsResponse(BaseModel):
    """Result of POST /api/fridge/scan — the parsed receipt items plus the id of
    the persisted receipt_scan generation.

    ``generation_id`` is echoed back on /fridge/merge (as a query param) so the
    server can capture the user's corrections to the scan. NULL when the
    telemetry write was skipped (best-effort) or on the demo path (no /scan
    call).
    """
    items: list[ScannedItemDTO]
    generation_id: int | None = None


class NormalizedName(BaseModel):
    """Maps a scanned item name to its canonical normalized form."""
    original: str
    # Bound the LLM-produced normalized name: normalize_item_names splices it
    # into a fresh ScannedReceiptItem (name max_length=100), so an unbounded
    # hallucinated value would raise ValidationError → 500 on the scan. Capping
    # here makes instructor retry to conform. min_length=1 avoids an empty name.
    normalized: str = Field(..., min_length=1, max_length=100)


class NormalizationResponse(BaseModel):
    """LLM response model for ingredient name normalization."""
    items: list[NormalizedName]


class SingleRecipeRequest(BaseModel):
    """Cook Now: generate one recipe the user is about to make right now.

    Distinct from MealPlanRequest because it deliberately has no multi-day
    semantics, no shopping list, and a required user-chosen meal_type. The
    `note` field is a free-text hint ("pasta-based", "use up the cilantro")
    that gets templated into the LLM prompt as taste preference.
    """

    meal_type: MealType
    diet_type: Literal[
        "balanced", "high_protein", "low_carb", "vegetarian", "vegan", "baby_food"
    ] | None = None
    people_count: int = Field(ge=1, le=10, default=2)
    taste_preferences: list[str] = Field(default_factory=list, max_length=20)
    avoid_ingredients: list[str] = Field(default_factory=list, max_length=50)
    ingredients_to_use: list[str] = Field(default_factory=list, max_length=20)
    stock_only: bool = False
    note: str | None = Field(default=None, max_length=200)

    @field_validator(
        "taste_preferences",
        "avoid_ingredients",
        "ingredients_to_use",
        mode="before",
    )
    @classmethod
    def sanitize_input(cls, v):
        # Same unicode-aware whitelist as MealPlanRequest. Duplicated rather
        # than imported to keep model-layer cross-references minimal.
        if not v:
            return []
        cleaned: list[str] = []
        for item in v:
            if not isinstance(item, str):
                continue
            if len(item) > 50:
                continue
            clean = re.sub(r"[^\w\s\-,.]", "", item, flags=re.UNICODE).strip()
            if clean:
                cleaned.append(clean)
        return cleaned[:20]

    @field_validator("note", mode="before")
    @classmethod
    def sanitize_note(cls, v):
        if v is None or not isinstance(v, str):
            return None
        clean = re.sub(r"[^\w\s\-,.!?()'\"/]", "", v, flags=re.UNICODE).strip()
        return clean or None


class SingleRecipeResponse(BaseModel):
    """Result of POST /api/recipe/generate — a single PlannedMeal.

    ``generation_id`` identifies the persisted machine_generation row for this
    output; the client echoes it back on cook/favorite so the server can link
    any edits the user made to the recipe they were shown. NULL only if the
    telemetry write was skipped (best-effort).
    """
    recipe: PlannedMeal
    generation_id: int | None = None


class CookRecipeRequest(SingleRecipeRequest):
    """Submit a previously-generated recipe for persistence + fridge debit.

    Extends SingleRecipeRequest (same user-supplied context) with the
    PlannedMeal the server returned, so the cook endpoint doesn't re-invoke
    the LLM — it just persists + debits + marks cooked.

    ``generation_id`` is the id from the /generate response; it's used only to
    link telemetry (owner-checked server-side) and never trusted for logic.
    """
    recipe: PlannedMeal
    generation_id: int | None = None


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
            return v.replace(tzinfo=UTC)
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
            return v.replace(tzinfo=UTC)
        return v


class FavoriteToggleRequest(BaseModel):
    """Request body for toggling a meal's cookbook membership."""
    is_favorite: bool


class MealEntrySummary(BaseModel):
    """Single meal within a plan detail view."""
    id: int
    day_index: int
    meal_index: int
    name: str
    meal_type: str
    cooked_at: datetime | None
    is_favorite: bool = False


class FavoriteRecipeRequest(BaseModel):
    """Persist a Cook Now recipe directly into the user's cookbook.

    Distinct from CookRecipeRequest because the user is starring without
    cooking — fridge stays untouched, cooked_at stays NULL. The PlannedMeal
    arrives client-controlled; the same trust-boundary caveats as /recipe/cook
    apply (see cook_recipe docstring).
    """
    meal_type: MealType
    people_count: int = Field(ge=1, le=10, default=2)
    recipe: PlannedMeal
    # id from the /generate response; used only for owner-checked telemetry
    # linkage, never trusted for logic. See CookRecipeRequest.generation_id.
    generation_id: int | None = None


class CookbookItem(BaseModel):
    """Single recipe in the user's cookbook (full details for the spread view).

    Returned by GET /api/cookbook so the frontend can render the open-book
    spread (ingredients + steps) without a second fetch per recipe.
    """
    meal_entry_id: int
    name: str
    meal_type: str
    meal_type_label: str = ""
    total_time_minutes: int | None = None
    ingredients: list[IngredientAmount]
    steps: list[str]
    created_at: datetime
    cooked_at: datetime | None = None


class CookbookListResponse(BaseModel):
    total: int
    items: list[CookbookItem]


class CookbookCountResponse(BaseModel):
    count: int
