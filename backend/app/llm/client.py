import asyncio
import base64
import logging
import random
from collections.abc import Callable
from typing import (  # Any: instructor kwargs are inherently untyped
    Any,
    TypeVar,
)

import instructor
from fastapi import HTTPException
from google import genai
from google.genai import types as genai_types
from google.genai.errors import APIError as GeminiAPIError
from google.genai.types import HttpOptionsDict
from openai import APIStatusError as OpenAIAPIStatusError
from openai import AsyncOpenAI
from openai import RateLimitError as OpenAIRateLimitError
from openai.types.chat import ChatCompletionSystemMessageParam
from pydantic import BaseModel

from app.core.config import LLMProvider, ModelEntry, settings
from app.llm.usage import record_call_usage, usage_from_completion

logger = logging.getLogger(__name__)

# Define a generic type variable bound to Pydantic models
T = TypeVar('T', bound=BaseModel)

MAX_LLM_RETRIES = 3

class LLMClient:
    """Thin wrapper utilising Instructor for strict JSON schema enforcement."""

    def __init__(self) -> None:
        self.openai_client: instructor.AsyncInstructor | None = None
        self.gemini_client: instructor.AsyncInstructor | None = None
        self.deepseek_client: instructor.AsyncInstructor | None = None

        if settings.openai_api_key:
            self.openai_client = instructor.from_openai(
                AsyncOpenAI(api_key=settings.openai_api_key, timeout=60.0)
            )
        if settings.deepseek_api_key:
            self.deepseek_client = instructor.from_openai(
                AsyncOpenAI(
                    api_key=settings.deepseek_api_key,
                    base_url="https://api.deepseek.com",
                    timeout=60.0,
                )
            )
        if settings.gemini_api_key:
            # Instructor seamlessly wraps the new google-genai client
            self.gemini_client = instructor.from_genai(
                genai.Client(
                    api_key=settings.gemini_api_key,
                    http_options=HttpOptionsDict(timeout=60_000),
                ),
                use_async=True,
                mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS,
            )

    def _get_client(self, provider: LLMProvider) -> instructor.AsyncInstructor:
        if provider == LLMProvider.GEMINI:
            if not self.gemini_client:
                raise HTTPException(500, "Gemini API key not configured")
            return self.gemini_client
        if provider == LLMProvider.OPENAI:
            if not self.openai_client:
                raise HTTPException(500, "OpenAI API key not configured")
            return self.openai_client
        if provider == LLMProvider.DEEPSEEK:
            if not self.deepseek_client:
                raise HTTPException(500, "DeepSeek API key not configured")
            return self.deepseek_client
        raise HTTPException(500, "Unsupported provider")

    # HTTP status codes that trigger chain fallback. Split by whether the
    # upstream is expected to recover on its own:
    #   - RETRYABLE: transient load / overload (429 quota, 503 overloaded).
    #     Worth a short backoff before the next provider to absorb a thundering
    #     herd — if every concurrent request tries the fallback instantly, the
    #     next provider's quota dies the same way.
    #   - TERMINAL: permanent for this model (402 billing, 404 model-not-found).
    #     No point sleeping — the config is wrong, move on immediately.
    _RETRYABLE_STATUS_CODES = {429, 503}
    _TERMINAL_FALLBACK_STATUS_CODES = {402, 404}
    _FALLBACK_STATUS_CODES = _RETRYABLE_STATUS_CODES | _TERMINAL_FALLBACK_STATUS_CODES

    # Backoff cap: one bad request shouldn't stall the whole chain for long.
    _BACKOFF_CAP_SECONDS = 10.0

    @staticmethod
    def _classify_error(exc: Exception) -> str | None:
        """Return 'retryable', 'terminal', or None (non-fallback) for an exception."""
        current: BaseException | None = exc
        while current is not None:
            code: int | None = None
            if isinstance(current, GeminiAPIError):
                code = getattr(current, "code", None)
            elif isinstance(current, OpenAIRateLimitError):
                return "retryable"
            elif isinstance(current, OpenAIAPIStatusError):
                code = current.status_code

            if code in LLMClient._RETRYABLE_STATUS_CODES:
                return "retryable"
            if code in LLMClient._TERMINAL_FALLBACK_STATUS_CODES:
                return "terminal"
            current = current.__cause__
        return None

    @staticmethod
    def _is_fallback_error(exc: Exception) -> bool:
        """Check if an exception (or its cause chain) should trigger chain fallback."""
        return LLMClient._classify_error(exc) is not None

    async def _call_with_fallback(
        self,
        build_kwargs: Callable[[ModelEntry], dict[str, Any]],
        response_model: type[T],
        error_context: str,
    ) -> T:
        """Try each model in settings.model_chain; fall back on retryable/terminal errors."""
        last_exc: Exception | None = None
        retryable_attempts = 0
        chain = settings.model_chain
        for i, entry in enumerate(chain):
            client = self._get_client(entry.provider)
            kwargs = build_kwargs(entry)
            try:
                logger.info(
                    "LLM call: provider=%s model=%s response_model=%s",
                    entry.provider.value,
                    entry.model,
                    response_model.__name__,
                )
                # create_with_completion also returns the raw provider response,
                # which carries the token-usage metadata. Capturing it here means
                # only the SUCCESSFUL attempt in the fallback chain is counted —
                # failed attempts raise before this point.
                result, completion = await client.chat.completions.create_with_completion(
                    model=entry.model,
                    response_model=response_model,
                    max_retries=MAX_LLM_RETRIES,
                    **kwargs,
                )
                usage = usage_from_completion(
                    entry.provider.value, entry.model, completion
                )
                if usage is not None:
                    record_call_usage(usage)
                logger.info(
                    "LLM call completed: provider=%s model=%s tokens(prompt/completion/total)=%s/%s/%s",
                    entry.provider.value,
                    entry.model,
                    usage.prompt_tokens if usage else "?",
                    usage.completion_tokens if usage else "?",
                    usage.total_tokens if usage else "?",
                )
                return result  # type: ignore[return-value]
            except Exception as e:
                last_exc = e
                classification = self._classify_error(e)
                is_last = i == len(chain) - 1
                if classification == "retryable":
                    retryable_attempts += 1
                    # Skip the sleep if there's no next provider to hand off to —
                    # we're about to raise 502 anyway, don't tack on ~10s of dead wait.
                    if is_last:
                        continue
                    delay = min(2 ** (retryable_attempts - 1), self._BACKOFF_CAP_SECONDS) + random.uniform(0, 0.5)
                    logger.warning(
                        "Retryable error on %s/%s, sleeping %.2fs before next provider: %s",
                        entry.provider.value,
                        entry.model,
                        delay,
                        e,
                    )
                    await asyncio.sleep(delay)
                    continue
                if classification == "terminal":
                    logger.warning(
                        "Terminal error on %s/%s (config issue), trying next immediately: %s",
                        entry.provider.value,
                        entry.model,
                        e,
                    )
                    continue
                logger.exception(
                    "LLM call failed on %s/%s with non-fallback error; aborting chain",
                    entry.provider.value,
                    entry.model,
                )
                break
        raise HTTPException(502, f"{error_context} is temporarily unavailable.") from last_exc

    async def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        mock_context: dict[str, Any] | None = None,
        mock: bool = False,
    ) -> T:
        """
        Forces the LLM to return data that perfectly validates against the injected Pydantic model.
        """
        if mock or settings.llm_mock:
            from app.models.plan_models import ReceiptScanResponse
            if response_model is ReceiptScanResponse:
                return self._mock_vision_response(response_model)
            return self._mock_response(response_model, mock_context)

        messages: list[object] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        def build_kwargs(entry: ModelEntry) -> dict[str, Any]:
            return {"messages": messages}

        return await self._call_with_fallback(build_kwargs, response_model, "Meal planning service")

    async def chat_vision_json(
        self,
        system_prompt: str,
        user_prompt: str,
        image_base64: str,
        image_media_type: str,
        response_model: type[T],
        mock: bool = False,
    ) -> T:
        """
        Sends an image + text prompt to the LLM and forces the response into a Pydantic model.
        Both GPT-4o-mini and Gemini 2.5 Flash support vision natively.
        """
        if mock or settings.llm_mock:
            return self._mock_vision_response(response_model)

        image_bytes = base64.b64decode(image_base64)

        def build_kwargs(entry: ModelEntry) -> dict[str, Any]:
            if entry.provider in (LLMProvider.OPENAI, LLMProvider.DEEPSEEK):
                return {
                    "messages": [
                        ChatCompletionSystemMessageParam(role="system", content=system_prompt),
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": user_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{image_media_type};base64,{image_base64}",
                                    },
                                },
                            ],
                        },
                    ],
                }
            # Gemini: native genai Content/Part objects for multimodal input
            return {
                "messages": [
                    ChatCompletionSystemMessageParam(role="system", content=system_prompt),
                    genai_types.Content(
                        role="user",
                        parts=[
                            genai_types.Part(text=user_prompt),
                            genai_types.Part(
                                inline_data=genai_types.Blob(
                                    mime_type=image_media_type,
                                    data=image_bytes,
                                )
                            ),
                        ],
                    ),
                ],
                # Intentional no-op: an EMPTY list means "no explicit override",
                # so Google's built-in safety filtering on the user-uploaded
                # image stays ACTIVE. This is NOT a BLOCK_NONE override — do not
                # populate this with BLOCK_NONE entries or you disable filtering.
                "safety_settings": [],
            }

        return await self._call_with_fallback(build_kwargs, response_model, "Receipt scanning service")

    # Three-day rotating meal templates using the seeded demo fridge.
    # Indexed by day_index % 3 → list of (name, meal_type, label, ingredients, steps).
    _MOCK_MEAL_TEMPLATES: list[list[dict[str, Any]]] = [
        [  # day_index % 3 == 1
            {
                "name": "Garlic Chicken with Spinach Rice",
                "meal_type": "breakfast",
                "meal_type_label": "Breakfast",
                "ingredients": [
                    {"name": "eggs", "quantity_grams": 120, "canonical_name": "egg"},
                    {"name": "greek yogurt", "quantity_grams": 150},
                    {"name": "lemons", "quantity_grams": 30, "canonical_name": "lemon"},
                ],
                "steps": [
                    "Whisk eggs and season with salt and pepper.",
                    "Cook in a non-stick pan over medium heat until set.",
                    "Serve with Greek yogurt and a squeeze of lemon.",
                ],
                "total_time_minutes": 10,
            },
            {
                "name": "Garlic Chicken with Spinach Rice",
                "meal_type": "lunch",
                "meal_type_label": "Lunch",
                "ingredients": [
                    {"name": "chicken breast", "quantity_grams": 200},
                    {"name": "rice", "quantity_grams": 150},
                    {"name": "baby spinach", "quantity_grams": 80},
                    {"name": "garlic", "quantity_grams": 10},
                    {"name": "olive oil", "quantity_grams": 20},
                ],
                "steps": [
                    "Cook rice according to package instructions.",
                    "Season chicken with garlic and a pinch of salt.",
                    "Sear chicken in olive oil for 6 minutes per side until golden.",
                    "Wilt spinach in the same pan for 2 minutes.",
                    "Serve chicken over spinach rice.",
                ],
                "total_time_minutes": 30,
            },
            {
                "name": "Cherry Tomato Pasta",
                "meal_type": "dinner",
                "meal_type_label": "Dinner",
                "ingredients": [
                    {"name": "pasta", "quantity_grams": 200},
                    {"name": "cherry tomatoes", "quantity_grams": 200},
                    {"name": "garlic", "quantity_grams": 10},
                    {"name": "olive oil", "quantity_grams": 30},
                    {"name": "cheddar cheese", "quantity_grams": 40},
                ],
                "steps": [
                    "Boil pasta in salted water until al dente.",
                    "Halve cherry tomatoes and sauté with garlic in olive oil for 5 minutes.",
                    "Toss pasta with the tomato sauce.",
                    "Finish with grated cheddar cheese.",
                ],
                "total_time_minutes": 20,
            },
            {
                "name": "Greek Yogurt with Lemon",
                "meal_type": "snack",
                "meal_type_label": "Snack",
                "ingredients": [
                    {"name": "greek yogurt", "quantity_grams": 150},
                    {"name": "lemons", "quantity_grams": 20, "canonical_name": "lemon"},
                ],
                "steps": ["Drizzle lemon juice over Greek yogurt and enjoy."],
                "total_time_minutes": 3,
            },
        ],
        [  # day_index % 3 == 2
            {
                "name": "Scrambled Eggs with Cheddar",
                "meal_type": "breakfast",
                "meal_type_label": "Breakfast",
                "ingredients": [
                    {"name": "eggs", "quantity_grams": 180, "canonical_name": "egg"},
                    {"name": "cheddar cheese", "quantity_grams": 50},
                    {"name": "olive oil", "quantity_grams": 10},
                ],
                "steps": [
                    "Beat eggs with salt and pepper.",
                    "Cook in olive oil over low heat, stirring gently.",
                    "Fold in cheddar cheese just before serving.",
                ],
                "total_time_minutes": 10,
            },
            {
                "name": "Spinach and Tomato Chicken Salad",
                "meal_type": "lunch",
                "meal_type_label": "Lunch",
                "ingredients": [
                    {"name": "baby spinach", "quantity_grams": 120},
                    {"name": "cherry tomatoes", "quantity_grams": 150},
                    {"name": "chicken breast", "quantity_grams": 150},
                    {"name": "olive oil", "quantity_grams": 20},
                    {"name": "lemons", "quantity_grams": 30, "canonical_name": "lemon"},
                ],
                "steps": [
                    "Grill or pan-fry chicken breast until cooked through, then slice.",
                    "Combine spinach, halved cherry tomatoes, and sliced chicken.",
                    "Dress with olive oil and lemon juice.",
                ],
                "total_time_minutes": 20,
            },
            {
                "name": "Baked Chicken with Onion and Rice",
                "meal_type": "dinner",
                "meal_type_label": "Dinner",
                "ingredients": [
                    {"name": "chicken breast", "quantity_grams": 250},
                    {"name": "rice", "quantity_grams": 180},
                    {"name": "onions", "quantity_grams": 120, "canonical_name": "onion"},
                    {"name": "olive oil", "quantity_grams": 20},
                    {"name": "garlic", "quantity_grams": 10},
                ],
                "steps": [
                    "Preheat oven to 200°C.",
                    "Slice onions and spread in a baking dish with olive oil and garlic.",
                    "Place chicken on top, season, and bake for 25 minutes.",
                    "Serve with steamed rice.",
                ],
                "total_time_minutes": 45,
            },
            {
                "name": "Cheddar Crackers",
                "meal_type": "snack",
                "meal_type_label": "Snack",
                "ingredients": [
                    {"name": "cheddar cheese", "quantity_grams": 60},
                ],
                "steps": ["Slice cheddar and serve as a snack."],
                "total_time_minutes": 2,
            },
        ],
        [  # day_index % 3 == 0
            {
                "name": "Eggs with Greek Yogurt",
                "meal_type": "breakfast",
                "meal_type_label": "Breakfast",
                "ingredients": [
                    {"name": "eggs", "quantity_grams": 180, "canonical_name": "egg"},
                    {"name": "greek yogurt", "quantity_grams": 100},
                    {"name": "olive oil", "quantity_grams": 10},
                ],
                "steps": [
                    "Fry eggs in olive oil over medium heat.",
                    "Serve with a side of Greek yogurt.",
                ],
                "total_time_minutes": 8,
            },
            {
                "name": "Cheesy Pasta with Spinach",
                "meal_type": "lunch",
                "meal_type_label": "Lunch",
                "ingredients": [
                    {"name": "pasta", "quantity_grams": 180},
                    {"name": "cheddar cheese", "quantity_grams": 80},
                    {"name": "baby spinach", "quantity_grams": 100},
                    {"name": "olive oil", "quantity_grams": 20},
                    {"name": "garlic", "quantity_grams": 10},
                ],
                "steps": [
                    "Boil pasta in salted water.",
                    "Sauté garlic in olive oil, add spinach and wilt for 2 minutes.",
                    "Toss pasta with spinach and stir in cheddar until melted.",
                ],
                "total_time_minutes": 20,
            },
            {
                "name": "Lemon Chicken with Cherry Tomatoes",
                "meal_type": "dinner",
                "meal_type_label": "Dinner",
                "ingredients": [
                    {"name": "chicken breast", "quantity_grams": 280},
                    {"name": "cherry tomatoes", "quantity_grams": 180},
                    {"name": "lemons", "quantity_grams": 50, "canonical_name": "lemon"},
                    {"name": "olive oil", "quantity_grams": 30},
                    {"name": "garlic", "quantity_grams": 10},
                ],
                "steps": [
                    "Marinate chicken in lemon juice, olive oil, and garlic for 10 minutes.",
                    "Sear in a hot pan for 6 minutes per side.",
                    "Add halved cherry tomatoes and cook 3 more minutes.",
                    "Serve with remaining lemon wedges.",
                ],
                "total_time_minutes": 30,
            },
            {
                "name": "Yogurt with Honey",
                "meal_type": "snack",
                "meal_type_label": "Snack",
                "ingredients": [
                    {"name": "greek yogurt", "quantity_grams": 150},
                ],
                "steps": ["Serve Greek yogurt chilled as an afternoon snack."],
                "total_time_minutes": 2,
            },
        ],
    ]

    # Meal types to assign for 1–5 meals per day
    _MOCK_MEAL_SLOTS = [
        [],                                             # 0 (unused)
        ["lunch"],                                      # 1
        ["breakfast", "dinner"],                        # 2
        ["breakfast", "lunch", "dinner"],               # 3
        ["breakfast", "lunch", "dinner", "snack"],      # 4
        ["breakfast", "lunch", "dinner", "snack", "snack"],  # 5
    ]

    @staticmethod
    def _mock_response(response_model: type[T], mock_context: dict[str, Any] | None = None) -> T:
        """Deterministic fridge-aware fake response used in demo/dev mode."""
        meals_per_day = 3
        day_index = 1

        if mock_context:
            meals_per_day = int(mock_context.get("meals_per_day", 3))
            day_index = int(mock_context.get("day_index", 1))

        meals_per_day = max(1, min(meals_per_day, 5))
        template_idx = day_index % 3
        templates = LLMClient._MOCK_MEAL_TEMPLATES[template_idx]
        slots = LLMClient._MOCK_MEAL_SLOTS[meals_per_day]

        # Match templates by meal_type slot; fall back to the template at that position.
        type_to_template: dict[str, dict[str, Any]] = {t["meal_type"]: t for t in templates}
        meals: list[dict[str, Any]] = []
        for slot in slots:
            meal = type_to_template.get(slot, templates[len(meals) % len(templates)])
            meals.append({**meal, "meal_type": slot})

        return response_model.model_validate({"meals": meals})

    @staticmethod
    def _mock_vision_response(response_model: type[T]) -> T:
        """Deterministic fake response for vision/receipt scanning in development."""
        return response_model.model_validate({
            "purchase_date": "2026-03-10",
            "items": [
                {"name": "chicken breast", "quantity_grams": 500, "item_type": "ingredient", "shelf_life_days": 3},
                {"name": "rice", "quantity_grams": 1000, "item_type": "ingredient", "shelf_life_days": 365},
                {"name": "olive oil", "quantity_grams": 500, "item_type": "ingredient", "shelf_life_days": 540},
                {"name": "chocolate bar", "quantity_grams": 100, "item_type": "ready_to_eat", "shelf_life_days": 180},
            ]
        })

# Maps each provider to the Settings attribute holding its (already
# placeholder-normalized) API key. Kept next to the check that consumes it.
_PROVIDER_KEY_ATTR: dict[LLMProvider, str] = {
    LLMProvider.GEMINI: "gemini_api_key",
    LLMProvider.OPENAI: "openai_api_key",
    LLMProvider.DEEPSEEK: "deepseek_api_key",
}


def check_model_chain_keys() -> None:
    """Log — at startup — whether every provider in the configured fallback chain
    actually has an API key. Deliberately never raises: a misconfigured *fallback*
    shouldn't block boot, but a keyless entry should be loud in the logs instead
    of silent until it's hit mid-incident (the worst time to discover it).

    - Keyless PRIMARY (head of chain) → ERROR: no LLM call can succeed.
    - Keyless FALLBACK entry → WARNING: works until that provider is reached,
      then the "fallback" is a no-op.
    - Fully-keyed but single-provider chain → INFO nudge: a provider-wide outage
      (this session's jsonref bug, a quota wall, a Google outage) has no escape
      hatch. Add a funded non-primary entry to LLM_MODELS for real resilience.
    """
    chain = settings.model_chain
    if not chain:
        logger.error("LLM model chain is empty — no LLM calls can be served.")
        return

    for position, entry in enumerate(chain):
        key_attr = _PROVIDER_KEY_ATTR.get(entry.provider)
        has_key = bool(getattr(settings, key_attr, None)) if key_attr else False
        if has_key:
            continue
        env_var = key_attr.upper() if key_attr else "the provider key"
        if position == 0:
            logger.error(
                "LLM primary provider '%s' (model=%s) has no API key — every LLM "
                "call will fail until %s is set.",
                entry.provider.value, entry.model, env_var,
            )
        else:
            logger.warning(
                "LLM fallback provider '%s' (model=%s, chain position %d) has no "
                "API key — fallback to it is a no-op. Set %s for cross-provider "
                "resilience.",
                entry.provider.value, entry.model, position, env_var,
            )

    if len({entry.provider for entry in chain}) == 1:
        only = chain[0].provider.value
        # Prod runs a single-provider Gemini chain, so this fires on EVERY boot.
        # Without the second sentence it would stand there recommending exactly
        # the change the disclosure tripwire below flags as a violation — two log
        # lines from one function arguing past each other. The advice is still
        # right; it is the ordering that matters.
        logger.info(
            "LLM model chain is single-provider (%s) — a provider-wide outage has "
            "no fallback. Adding a funded non-%s entry to LLM_MODELS improves "
            "resilience, but every entry receives user dietary data: disclose the "
            "provider in frontend/privacy.html and add it to DISCLOSED_PROVIDERS "
            "first, then change the chain.",
            only, only,
        )

    _warn_if_chain_contradicts_privacy_policy(chain)


#: Providers the published privacy policy names as recipients of user content.
#: frontend/privacy.html tells users their dietary restrictions and allergies —
#: health data, and for halal/kosher religious belief — go to Google and to
#: nobody else. That page is a public promise; this set is the code's copy of it.
DISCLOSED_PROVIDERS = frozenset({LLMProvider.GEMINI})


def _warn_if_chain_contradicts_privacy_policy(chain: list[ModelEntry]) -> None:
    """Shout if LLM_MODELS routes user content to a provider we never disclosed.

    **This is a compliance tripwire, not a resilience one.** Every entry in the
    chain receives the full generation prompt — declared allergens, diet types
    (including halal/kosher/diabetic/baby-food), the free-text avoid-list and the
    user's whole fridge. Adding a provider to LLM_MODELS therefore silently makes
    the published privacy policy false, and nothing else in the system would
    notice.

    The trap is concrete rather than hypothetical: `.env.example` once shipped
    `openai/gpt-4o-mini` as a fallback entry, so the single most natural ops move
    — copy the example into prod — would have started sending health data to an
    undisclosed processor. Flagged in review of the privacy-policy PR.

    Deliberately a log line, not a raise: refusing to boot over a *disclosure*
    mismatch would turn a paperwork problem into an outage, and the operator may
    genuinely intend the change and be about to update the policy. It is an
    ERROR (not a warning) because a silently-false privacy policy is a
    regulatory problem, not a tidiness one.
    """
    undisclosed = sorted(
        {e.provider.value for e in chain if e.provider not in DISCLOSED_PROVIDERS}
    )
    if not undisclosed:
        return
    logger.error(
        "LLM_MODELS routes user content to UNDISCLOSED provider(s): %s. "
        "frontend/privacy.html tells users their dietary restrictions and "
        "allergies go to Google only. Every chain entry receives that data, so "
        "the published policy is now inaccurate — update it (and this module's "
        "DISCLOSED_PROVIDERS) or remove the provider from LLM_MODELS.",
        ", ".join(undisclosed),
    )


llm_client = LLMClient()
