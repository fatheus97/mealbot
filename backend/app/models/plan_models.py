from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.json_schema import JsonDict

from app.core.dietary import Allergen, DietType
from app.core.meal_types import LEGACY_MEAL_TYPE_MAP, MealType

if TYPE_CHECKING:
    from app.models.db_models import MealEntry


def _normalize_canonical_key(v: object) -> object:
    """Normalize a ``canonical_name`` lookup key (mode="before").

    Shared by every model carrying the field so they cannot drift apart. It is a
    LOOKUP KEY, not display text, so case and surrounding whitespace are noise:
    fold them, and collapse an empty result to None so "" and "absent" don't
    become two states the lookup has to handle separately.

    Fence-stripped like the free-text names: the field is reachable from
    CLIENT-submitted PlannedMeals (Cook Now, edit, favorite), not only from LLM
    output, so it gets the same treatment as any other untrusted string.
    """
    if not isinstance(v, str):
        return v
    # _strip_prompt_fence_tags returns a str for a str input.
    cleaned = str(_strip_prompt_fence_tags(v)).strip().lower()
    return cleaned or None


def _strip_prompt_fence_tags(v: object) -> object:
    """Remove < and > from a free-text name (mode="before", so length checks
    apply to the cleaned value).

    These names are templated into LLM prompts wrapped in <user_content> … tags.
    No real food/meal name contains angle brackets, but a value carrying a
    literal </user_content> could forge a break-out of the fence and inject
    instructions. Unlike the sanitize_input fields (whitelist-stripped), these
    have NO character whitelist, so the fence is their only defense — its
    delimiter must be un-forgeable. Names that are only brackets collapse to ""
    and then fail min_length.
    """
    if isinstance(v, str):
        return v.replace("<", "").replace(">", "")
    return v


def _hide_array_bounds(schema: JsonDict) -> None:
    """Keep ``maxItems``/``minItems`` out of the EMITTED JSON schema. Pydantic
    still enforces the bound — only what we hand the LLM changes.

    Gemini compiles ``response_schema`` into a constrained decoder. An array
    length limit on a list of OBJECTS multiplies out against every bound inside
    those objects, and past some threshold the whole request is rejected with
    400 INVALID_ARGUMENT / "The specified schema produces a constraint that has
    too many states for serving". That is a SERVING-SIDE limit: on 2026-08-02 it
    took out every generation path in prod (/api/plan and /api/recipe/generate,
    both models in the chain) with no deploy of ours — Google tightened it under
    a schema that had been working. Measured against the live API, dropping just
    these two keys is what brings the schema back under the limit; the string
    and integer bounds are affordable and stay visible.

    The bounds exist for the CLIENT-write paths (Cook Now posts a whole
    PlannedMeal — see IngredientAmount), and validation there is untouched. LLM
    output never came near 40 ingredients / 50 steps, so nothing is lost by not
    stating them in the prompt schema.

    Apply to every bounded list on a model that can be an LLM ``response_model``
    — ``test_llm_schemas.py`` fails the build if one is missed.
    """
    schema.pop("maxItems", None)
    schema.pop("minItems", None)


# Calendar scheduling bounds. A plan can be dated a little into the past (you can
# backfill a plan you already started cooking) or the future, but a start_date
# outside a wide, sane window is a typo / overflow / abuse that would junk the
# calendar view — reject it at the API boundary.
_MIN_PLAN_YEAR = 2020
_MAX_PLAN_YEARS_AHEAD = 5


def validate_plan_start_date(v: date | None) -> date | None:
    """Reject clearly-bogus plan start dates. Leap-safe (compares the year, not a
    year-shifted date). ``None`` is always allowed — it means "unscheduled"."""
    if v is None:
        return None
    max_year = date.today().year + _MAX_PLAN_YEARS_AHEAD
    if not (_MIN_PLAN_YEAR <= v.year <= max_year):
        raise ValueError(
            f"start_date year must be between {_MIN_PLAN_YEAR} and {max_year}"
        )
    return v


# --- Dietary restrictions & allergens (slice 1: schema + backward-compat) ---
#
# A user can legitimately stack several dietary patterns and declare all 14 EU
# allergens, but an unbounded list is hostile input (each value is persisted and,
# in later slices, rendered into the prompt) — so bound both at the API boundary.
# The diet cap is the FULL offered vocabulary (every enum member), so selecting
# every diet the multi-select UI renders always validates; it is derived, not a
# magic number, so it can never drift below the vocabulary and 422 a legal combo.
# max_length is checked pre-dedup, so a duplicate-spam list (["vegan"] * 1000)
# still exceeds it and is rejected — the list stays bounded.
_MAX_DIET_TYPES = len(DietType)
_MAX_ALLERGENS = 20  # EU-14 is the real ceiling; small headroom, still bounded.


def _dedup_preserve_order[T](values: list[T]) -> list[T]:
    """De-duplicate keeping first-seen order (StrEnum members are hashable)."""
    seen: set[T] = set()
    out: list[T] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _reconcile_diet_fields(
    diet_type: DietType | None, diet_types: list[DietType],
) -> tuple[DietType | None, list[DietType]]:
    """Bridge the legacy single ``diet_type`` and the combinable ``diet_types``.

    The canonical field going forward is the *set* ``diet_types``; the prompt
    template still reads a single ``diet_type`` (the prompt redesign is a later
    slice), so the two must stay consistent:

    - A legacy request / stored blob carrying only ``diet_type`` (no
      ``diet_types``) is widened to ``diet_types=[diet_type]`` — degrade-on-read,
      the same shape leftovers uses for ``response_json``.
    - When ``diet_types`` is supplied it is AUTHORITATIVE (a client sending both
      keeps ``diet_types`` and has ``diet_type`` overwritten to match):
      order-preserving de-dup, then ``diet_type`` is mirrored to its first
      element so the unchanged template renders exactly what it did before.
    """
    if not diet_types and diet_type is not None:
        diet_types = [diet_type]
    else:
        diet_types = _dedup_preserve_order(diet_types)
    return (diet_types[0] if diet_types else None), diet_types


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

    @field_validator("name", mode="before")
    @classmethod
    def _strip_fence_tags(cls, v: object) -> object:
        return _strip_prompt_fence_tags(v)


class PantryStapleDTO(BaseModel):
    """A single "always have" pantry-staple name (salt, oil, flour…).

    Client-controlled on PUT /staples. Bounded + fence-stripped like the other
    user-authored name paths (StockItemDTO/IngredientAmount): a staple name isn't
    templated into a prompt today, but it is stored user input, so it gets the
    same defensive treatment rather than trusting it by omission. Name-only — the
    quantity/expiry that make a fridge item are meaningless for a staple.
    """
    name: str = Field(..., min_length=1, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_fence_tags(cls, v: object) -> object:
        return _strip_prompt_fence_tags(v)


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
    # Legacy single-select diet — KEPT as a backward-compat mirror of
    # diet_types[0] (see _reconcile_diet). It is still what the current frontend
    # sends and what old request_json blobs carry; as of the slice-3 prompt
    # redesign, generation reads the combinable diet_types / allergens via the
    # reference layer, NOT this mirror. Widened from the original 6-value Literal
    # to the full DietType set — a superset, so every stored value still validates.
    diet_type: DietType | None = None
    # Combinable dietary patterns — the canonical field going forward. Empty by
    # default; a legacy diet_type is folded in here by _reconcile_diet.
    diet_types: list[DietType] = Field(
        default_factory=list,
        max_length=_MAX_DIET_TYPES,
        description="Combinable dietary patterns (e.g. vegan, gluten_free, keto).",
    )
    # Structured, safety-critical allergen declarations — DELIBERATELY distinct
    # from the free-text taste `avoid_ingredients` list (an allergy is a hard
    # constraint, not a preference). Persisted now; the prompt + deterministic
    # output screen that consume it are later slices — nothing filters on it yet.
    allergens: list[Allergen] = Field(
        default_factory=list,
        max_length=_MAX_ALLERGENS,
        description="EU-14 major allergens the user must avoid (hard constraint).",
    )
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
    # "auto" lets the server link a later light meal to an earlier batch-friendly
    # one ("cook a bigger dinner, eat it as tomorrow's lunch").
    #
    # This model is bound straight from the public POST /api/plan body, so the
    # value a client sends here is NOT trusted: the endpoint overwrites it from
    # settings.leftovers_enabled, the same way it overwrites include_spices and
    # the locale fields. That is what makes the rollout gate real rather than
    # advisory — otherwise anyone reading the auto-generated schema could opt
    # into the feature before it is finished.
    #
    # The LLM never sees this and never authors a link (see
    # app/services/leftovers.py).
    leftover_policy: Literal["none", "auto"] = Field(
        default="none",
        description="Whether the server may plan leftover meals for this plan.",
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
    def sanitize_input(cls, v: object) -> list[str]:
        # A mode="before" validator receives the raw request body value, so it
        # must not assume a list. Iterating blind raised TypeError on a scalar,
        # and pydantic converts only ValueError/AssertionError into a 422 —
        # TypeError escaped as a 500. A bare string IS iterable, so it never
        # crashed; it silently became one entry per character.
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("must be a list of strings")

        cleaned_list: list[str] = []
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

    @model_validator(mode="after")
    def _reconcile_diet(self) -> MealPlanRequest:
        # Keep the legacy single `diet_type` and the combinable `diet_types` in
        # sync, and de-dup the allergen set. See _reconcile_diet_fields.
        self.diet_type, self.diet_types = _reconcile_diet_fields(
            self.diet_type, self.diet_types,
        )
        self.allergens = _dedup_preserve_order(self.allergens)
        return self


class IngredientAmount(BaseModel):
    """Amount of a single ingredient, expressed in grams."""
    # Bounds: Cook Now (Phase 4+) accepts PlannedMeal from the client. These
    # caps prevent a crafted request from stuffing the indexed MealEntry.name
    # column or meal_json blob with unbounded data.
    name: str = Field(..., max_length=100,
                      description="The canonical name of the ingredient (e.g., 'chicken breast').")
    # allow_inf_nan=False, matching StockItemDTO/ScannedItemDTO above. Without it
    # NaN passes validate_realistic_amount outright — NaN <= 0 and NaN > 30000
    # are BOTH False — and then poisons the FIFO debit: allocate_fifo computes
    # min(NaN, batch) = NaN, and flatten_fridge_batches' `> 0` filter drops the
    # whole batch, silently deleting the user's stock with a 200 response.
    # Verified reachable: json.loads (Starlette's body parser) accepts a bare NaN
    # literal, so any client-write path carrying an IngredientAmount could send
    # one — MealEditRequest, CookRecipeRequest.recipe, FavoriteRecipeRequest.recipe.
    quantity_grams: float = Field(..., allow_inf_nan=False,
                                  description="The weight in grams. If the recipe uses volume (cups), estimate the weight.")
    is_spice: bool = Field(default=False, description="True for spices/herbs/seasonings when include_spices is off.")
    # Lookup key for the frontend's piece-weight table, so a countable
    # ingredient can be shown as "2 pcs" instead of "120 g".
    #
    # It exists because `name` is written in the USER'S language (see the
    # meal-plan prompt's "ALL output text ... in {{ language }}" rule), so a
    # table keyed on names would only ever work for English speakers. This is a
    # stable ENGLISH key the model supplies alongside the localized name.
    #
    # The model proposes a NAME, never a count: the count is derived
    # deterministically from `quantity_grams` and a curated, sourced weight
    # table, and an unrecognised key simply falls back to grams. That keeps a
    # hallucinated value from ever becoming a number the user reads.
    #
    # Optional and nullable: plans generated before this field existed replay
    # from `response_json` without it and degrade to grams.
    canonical_name: str | None = Field(
        default=None,
        max_length=60,
        description=(
            "Lowercase SINGULAR English name for countable whole items only "
            "(e.g. 'egg', 'onion', 'lemon'). Omit for anything not counted in "
            "whole units (flour, milk, rice, minced meat)."
        ),
    )

    # English name of the ingredient, for the ALLERGEN SCREEN — nothing else.
    #
    # Deliberately separate from `canonical_name` even though both are English.
    # They have opposite scopes and merging them breaks one of the two:
    #   - `canonical_name` is a piece-weight lookup key, emitted ONLY for
    #     countable whole items and omitted for flour/milk/minced meat. Widening
    #     it to everything would make the model emit "sausage" for sausage meat
    #     and the UI would show "3 pcs" of it.
    #   - `name_en` must cover EVERY ingredient, and the ones it matters most for
    #     are exactly the bulk ones canonical_name omits — milk, flour, cheese.
    #
    # Why it exists: `name` is written in the USER'S language (the prompt's "ALL
    # output text ... in {{ language }}" rule) while the allergen term lists in
    # dietary_reference.py are English. Without an English name the deterministic
    # screen matches nothing for a Czech or German user — it silently degrades to
    # prompt-only avoidance, and the fail-closed 422 can never fire. That was
    # live for every non-English account until this field landed.
    #
    # The model only ever TRANSLATES here; it never decides safety. A missing or
    # blank value on a non-English plan is treated as UNSCREENABLE and rejected
    # by the screen, so an omission fails closed rather than passing silently.
    name_en: str | None = Field(
        default=None,
        max_length=100,
        description=(
            "The ingredient's plain ENGLISH name, always lowercase, for every "
            "ingredient, whatever language the rest of the output is in "
            "(e.g. name='mléko' -> name_en='milk'). Never shown to the user."
        ),
    )

    @field_validator("name", mode="before")
    @classmethod
    def _strip_fence_tags(cls, v: object) -> object:
        # Ingredient names render into fenced LLM prompts (frozen_meals, stock).
        return _strip_prompt_fence_tags(v)

    @field_validator("canonical_name", "name_en", mode="before")
    @classmethod
    def _normalize_canonical(cls, v: object) -> object:
        # Same treatment for both: lookup keys, not display text — case-folded,
        # whitespace-trimmed, ""→None so "blank" and "absent" are one state, and
        # fence-stripped because client-write paths can reach these fields too.
        return _normalize_canonical_key(v)

    @field_validator("quantity_grams")
    @classmethod
    def validate_realistic_amount(cls, v):
        if v <= 0:
            raise ValueError("Quantity must be positive.")
        # Raised 10kg -> 30kg for batch cooking: a leftover means its source meal
        # is cooked at 2-3x portions, and 6 people x 3 portions of a staple
        # (potatoes, rice) clears 10kg per item easily. At the old cap that
        # 500'd the whole plan endpoint. The validator's real job is catching a
        # hallucinated `quantity_grams: 50000`, and 30kg still does that.
        if v > 30000:
            raise ValueError("Quantity is unrealistically high (>30kg). Verify units.")
        return v


class ShoppingListItem(BaseModel):
    """One line of a plan's shopping list: how much of an ingredient to BUY.

    Deliberately NOT IngredientAmount. This is an AGGREGATE — one ingredient
    summed across every meal in the plan, minus what the fridge already holds —
    so IngredientAmount's per-meal sanity cap does not apply. A legitimate
    multi-day plan can need more than 30kg of one staple, and batch cooking
    (what leftovers are for) makes that likelier.

    Applying the per-meal cap here isn't merely wrong, it's UNRECOVERABLE. The
    shopping list is serialized into MealPlan.response_json, and every read
    re-validates that blob from raw JSON — so a cap violation wouldn't fail at
    generation, it would make the stored plan permanently unopenable (500 from
    get_plan_detail, with no way to edit it back into range). That is precisely
    the failure mode the leftovers design avoids elsewhere by validating on
    write and degrading on read. Bypassing validation at construction time does
    NOT help: Pydantic only skips re-validation for live model instances, never
    for the JSON round-trip.

    Same call StockItemDTO already documents for itself, for the same reason.

    Still bounded where bounding matters: the name is length-capped and
    fence-stripped like every other LLM/client-facing string, and the quantity
    must be a positive real (allow_inf_nan=False keeps NaN out of the
    arithmetic — see IngredientAmount for what NaN does to the fridge).

    Wire-compatible with the old shape: blobs written when this was an
    IngredientAmount carry an extra `is_spice` key, which Pydantic ignores.
    """
    name: str = Field(..., max_length=100)
    quantity_grams: float = Field(..., gt=0, allow_inf_nan=False)
    # Carried through aggregation from the meals' IngredientAmounts so the
    # shopping list can read "8 eggs" instead of "480 g" — the surface where a
    # piece count is most useful. See IngredientAmount.canonical_name.
    canonical_name: str | None = Field(default=None, max_length=60)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_fence_tags(cls, v: object) -> object:
        return _strip_prompt_fence_tags(v)

    @field_validator("canonical_name", mode="before")
    @classmethod
    def _normalize_canonical(cls, v: object) -> object:
        return _normalize_canonical_key(v)


class ConsumedBatch(BaseModel):
    """A specific fridge batch (with its expiration + need_to_use) charged to a meal at confirm time."""
    name: str
    quantity_grams: float
    expiration_date: date | None = None
    need_to_use: bool = False


class LeftoverRef(BaseModel):
    """Pointer to the SOURCE meal a leftover was cooked as part of.

    Indices are **0-based**, matching FrozenMeal and the positions inside
    MealPlanResponse.days — NOT MealEntry.day_index/meal_index, which are
    1-based. Cross the two only via plan_service._ref_to_entry_coords so the
    conversion exists in exactly one place; an off-by-one here never 404s, it
    silently resolves to a real neighbouring meal.

    Intra-plan only, deliberately: there is no plan_id field. A cross-plan
    pointer would dangle the moment the source plan is deleted, and stable
    cross-plan meal identity doesn't exist (MealEntry rows are deleted and
    re-minted on unconfirm/re-confirm).
    """
    day_index: int = Field(ge=0, description="0-based day index within THIS plan.")
    meal_index: int = Field(ge=0, description="0-based meal index within that day.")


# NOTE: a model's docstring becomes the `description` of its JSON schema, and
# GeneratedMeal's schema is sent to the LLM verbatim as the structured-output
# contract. Keep that docstring SHORT and addressed to the model; internal
# rationale belongs in comments like this one, out of the prompt.
#
# GeneratedMeal exists so `leftover_of` can never appear in a structured-output
# schema. Generation runs one call per day and the prompt carries only bare meal
# *names* from prior days, so the model structurally cannot author a correct
# cross-day index — it would emit confident garbage (instructor/Gemini guarantee
# shape, never semantics). Links are assigned server-side instead; see
# app/services/leftovers.py.
#
# Keeping LeftoverRef out of the LLM schema also avoids introducing a new
# $defs/$ref shape into Gemini structured output — the exact surface that broke
# every generation call in prod when jsonref was dropped (#169/#182), which
# mocked-LLM CI could not catch.
class GeneratedMeal(BaseModel):
    """A single meal in a day's plan."""
    # Bounds apply to the client-write path (Cook Now /recipe/cook) — the LLM
    # output path doesn't reach these limits in practice, but sizing them here
    # rather than at the API layer keeps all PlannedMeal use-sites protected.
    name: str = Field(..., max_length=200)
    meal_type: MealType
    meal_type_label: str = Field(default="", max_length=100)
    # json_schema_extra: enforced here, hidden from the LLM schema — see
    # _hide_array_bounds (a serving-side Gemini limit, not a style choice).
    ingredients: list[IngredientAmount] = Field(
        ..., max_length=40, json_schema_extra=_hide_array_bounds,
    )
    steps: list[str] = Field(..., max_length=50, json_schema_extra=_hide_array_bounds)
    # Optional so legacy meal_json rows (pre-feature) still parse during RAG retrieval.
    # New generations are instructed by the prompt to always populate it.
    total_time_minutes: int | None = Field(
        default=None,
        ge=1,
        le=600,
        description="Total time from prep start to finish, including cook and rest, in minutes.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def _strip_fence_tags(cls, v: object) -> object:
        # Meal names render into fenced LLM prompts (regenerate frozen_meals) and
        # are client-controlled on /recipe/cook (see its trust-boundary comment).
        return _strip_prompt_fence_tags(v)

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


class PlannedMeal(GeneratedMeal):
    """A meal as stored and served: the generated content plus server-assigned
    fields the LLM never produces.

    Subclasses GeneratedMeal so the field list exists once and can't drift.
    """
    # Set only by the server (app/services/leftovers.py). None = an ordinary
    # meal. Optional so legacy meal_json / response_json blobs written before
    # this feature still parse — same rationale as total_time_minutes.
    #
    # Client-write paths strip this rather than honouring it: /recipe/cook and
    # /recipe/favorite build 1-day/1-meal plans where a link is nonsense by
    # construction, and MealEditRequest deliberately doesn't carry the field
    # (same reason it omits meal_type — an edit must not smuggle in data a
    # freshly-generated meal couldn't hold).
    leftover_of: LeftoverRef | None = Field(
        default=None,
        description=(
            "If set, this meal is a reheat of an earlier meal in the same plan "
            "and consumes no additional ingredients."
        ),
    )

    @property
    def is_leftover(self) -> bool:
        """Read this at every summation/debit site rather than testing
        `ingredients == []` — an ordinary meal could legitimately end up with
        an empty ingredient list, and conflating the two would silently skip
        its fridge debit."""
        return self.leftover_of is not None

    @model_validator(mode="after")
    def _leftover_carries_no_ingredients(self) -> PlannedMeal:
        # A leftover's ingredients were bought and debited with its source, so
        # carrying them here would double-count in three places at once: the
        # shopping list, the day-to-day fridge simulation during generation,
        # and the FIFO debit at confirm. allocate_fifo never raises on
        # shortage, so that double-debit would return 200 and stay invisible
        # until the fridge is diffed by hand.
        #
        # This is the innermost of two belts; the summation sites also skip on
        # is_leftover explicitly. Correctness must not rest on the list merely
        # happening to be empty.
        if self.leftover_of is not None and self.ingredients:
            raise ValueError(
                "a leftover meal must carry no ingredients "
                "(they belong to its source meal)"
            )
        return self


class AllergenWarning(BaseModel):
    """One allergen the user's own edit reintroduced into a meal.

    A WARNING, never a rejection. When generation produces something we cannot
    verify we withhold it — that is our output. An edit is the user's own recipe
    and their own declared allergy: hard-blocking it would be patronising, is
    trivially worked around, and would push people to keep a "real" copy
    somewhere we cannot check at all. So the edit saves and the UI says loudly
    what it found.
    """

    allergen: str = Field(..., description="Allergen enum value, e.g. 'milk'.")
    label: str = Field(..., description="Human label for the UI, e.g. 'Milk'.")
    ingredient: str = Field(
        ..., description="The ingredient name, or the step text for a step hit."
    )
    source: str = Field(..., description="'ingredient' or 'step'.")


class MealEditResponse(PlannedMeal):
    """The saved meal, plus anything the allergen screen found in it.

    SUBCLASSES PlannedMeal deliberately: the JSON keeps every key the endpoint
    already returned and adds one optional array, so a client that knows nothing
    about warnings keeps working unchanged. Returning a wrapper
    ({meal, warnings}) would have been a breaking change for no benefit.
    """

    allergen_warnings: list[AllergenWarning] = Field(default_factory=list)


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


# The structured-output schema handed to the LLM for one day. Built on
# GeneratedMeal, not PlannedMeal, so leftover_of stays out of the model's schema
# entirely. Convert to SingleDayResponse via to_planned_day right after the call.
# (Docstring stays short — it is sent to the model; see GeneratedMeal.)
class LlmDayResponse(BaseModel):
    """One day of a meal plan."""
    meals: list[GeneratedMeal]

    def to_planned_day(self) -> SingleDayResponse:
        """Widen raw model output into stored meals (leftover_of defaults None)."""
        return SingleDayResponse(
            meals=[PlannedMeal.model_validate(m.model_dump()) for m in self.meals]
        )


class SingleDayResponse(BaseModel):
    """A single day of a plan as stored and served."""
    meals: list[PlannedMeal]


class MealPlanResponse(BaseModel):
    """Multi-day plan returned by the /plan endpoint."""
    plan_id: int | None
    # Real-world date of Day 1 (None = unscheduled). Stamped from the MealPlan
    # column on every read (the same pattern as plan_id): the copy serialized
    # into response_json is an inert placeholder that reads always overwrite, so
    # the column stays authoritative and there's no second copy to drift.
    start_date: date | None = None
    days: list[SingleDayResponse]
    shopping_list: list[ShoppingListItem]


class ConfirmPlanRequest(BaseModel):
    """Optional body for POST /plan/{id}/confirm — lets the user pin (or
    override) the plan's calendar start date at confirm time. The whole body is
    optional: a client that doesn't schedule POSTs nothing and keeps whatever
    date was set at generation (or NULL).

    NOTE null-semantics: here a null (or absent) start_date is a NO-OP that keeps
    the existing date. This is the OPPOSITE of PlanScheduleUpdate (PATCH), where
    null CLEARS the schedule — same field name, opposite meaning. To unschedule,
    use PATCH /plan/{id}, not confirm."""
    start_date: date | None = None

    @field_validator("start_date")
    @classmethod
    def _bound_start_date(cls, v: date | None) -> date | None:
        return validate_plan_start_date(v)


class PlanScheduleUpdate(BaseModel):
    """Body for PATCH /plan/{id} — reschedule a plan.

    NOTE null-semantics: reschedule_plan writes start_date UNCONDITIONALLY, so a
    null (or absent → `{}`) start_date CLEARS the schedule (back to
    "unscheduled"). This is the OPPOSITE of ConfirmPlanRequest, where null is a
    no-op that keeps the existing date. Send null here only when you actually
    intend to unschedule — do not `PATCH {}` expecting a "leave it alone" no-op."""
    start_date: date | None = None

    @field_validator("start_date")
    @classmethod
    def _bound_start_date(cls, v: date | None) -> date | None:
        return validate_plan_start_date(v)


class PlanScheduleResponse(BaseModel):
    """Result of a reschedule — the plan id and its new (possibly null) date."""
    plan_id: int
    start_date: date | None = None


class CalendarMeal(BaseModel):
    """One meal on a calendar day.

    Widened from a bare name string so the grid can mark leftovers and show
    where the food came from.

    `source_date` is resolved SERVER-side. The client cannot derive it: the
    source day may fall outside the month currently rendered, and the calendar
    payload only carries the days in the requested window. Nullable — a link
    whose source can't be resolved degrades to an unadorned "leftovers" marker
    rather than failing the whole calendar.
    """
    name: str
    is_leftover: bool = False
    source_date: date | None = None
    source_name: str | None = None


class CalendarDay(BaseModel):
    """One real-world day of a scheduled plan, for the calendar grid."""
    date: date
    day_index: int  # 1-based day within the plan
    meals: list[CalendarMeal]  # meals on this day, in slot order (may be empty)


class CalendarPlanEntry(BaseModel):
    """A scheduled plan expanded across its real-world dates for the calendar."""
    plan_id: int
    start_date: date
    status: Literal["planned", "active", "cooked", "finished"]
    days: list[CalendarDay]


class CalendarResponse(BaseModel):
    """GET /plan/calendar — the user's scheduled plans overlapping a date window,
    each expanded into per-day cells the frontend places on the grid."""
    plans: list[CalendarPlanEntry]


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

    @field_validator("name", mode="before")
    @classmethod
    def _strip_fence_tags(cls, v: object) -> object:
        # A crafted receipt could make the LLM emit a name carrying </user_content>;
        # it renders into the fenced normalize prompt, so neutralize the delimiter.
        return _strip_prompt_fence_tags(v)

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
    # Same legacy-mirror + combinable-set shape as MealPlanRequest (Cook Now
    # carries the user's diet the same way). See _reconcile_diet_fields; the
    # mapping into MealPlanRequest (recipe.py) forwards diet_types + allergens.
    diet_type: DietType | None = None
    diet_types: list[DietType] = Field(
        default_factory=list,
        max_length=_MAX_DIET_TYPES,
        description="Combinable dietary patterns (e.g. vegan, gluten_free, keto).",
    )
    allergens: list[Allergen] = Field(
        default_factory=list,
        max_length=_MAX_ALLERGENS,
        description="EU-14 major allergens the user must avoid (hard constraint).",
    )
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
    def sanitize_input(cls, v: object) -> list[str]:
        # Same unicode-aware whitelist and the same non-list guard as
        # MealPlanRequest (see there for why TypeError became a 500).
        # Duplicated rather than imported to keep model-layer cross-references
        # minimal — so a fix to one is only half a fix.
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("must be a list of strings")
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

    @model_validator(mode="after")
    def _reconcile_diet(self) -> SingleRecipeRequest:
        # Mirror MealPlanRequest — duplicated (not shared) to keep the model
        # layer free of cross-references, matching the sanitize_input pattern.
        self.diet_type, self.diet_types = _reconcile_diet_fields(
            self.diet_type, self.diet_types,
        )
        self.allergens = _dedup_preserve_order(self.allergens)
        return self


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
    # Real-world date of Day 1 (None = unscheduled). Powers date labels on the
    # catalog cards and the calendar view's plan placement.
    start_date: date | None = None
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

    @classmethod
    def from_entry(cls, entry: MealEntry) -> MealEntrySummary:
        """Build a summary from a persisted MealEntry. Centralizes the field
        mapping and the entry.id not-None narrowing (the DB PK is int | None
        while this schema requires int) that were hand-written at 7 call sites."""
        assert entry.id is not None, "MealEntry must be flushed (id populated) before summarizing"
        return cls(
            id=entry.id,
            day_index=entry.day_index,
            meal_index=entry.meal_index,
            name=entry.name,
            meal_type=entry.meal_type,
            cooked_at=entry.cooked_at,
            is_favorite=entry.is_favorite,
        )


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
