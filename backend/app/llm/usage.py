"""Request-scoped capture of per-call LLM token usage.

The token counts live on the provider response, produced deep inside
``LLMClient``; but recording needs ``session`` + ``user_id`` + ``surface``,
which only the route layer has. Rather than thread a return value through every
service (and every mocked test), the client appends a normalized ``LlmCallUsage``
to a request-scoped ``ContextVar`` bucket, and the route drains + records it.

Contract:
* ``record_call_usage`` is a no-op when no bucket is active (calls outside a
  capture scope — background tasks, tests — never error).
* Extraction is best-effort and never raises: a provider whose response shape we
  don't recognise, or a missing usage field, yields ``None`` / zeros rather than
  breaking the (already-paid-for) LLM call.
* Buckets are per-task via ``ContextVar``; ``asyncio`` child tasks (e.g. a
  fan-out multi-day generation) inherit the same list reference, so their
  appends are visible to the draining parent.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)


class LlmCallUsage(BaseModel):
    """Normalized token usage for a single LLM call. Immutable."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# None = no active capture scope → record_call_usage is a no-op.
_usage_bucket: ContextVar[list[LlmCallUsage] | None] = ContextVar(
    "llm_usage_bucket", default=None
)


def record_call_usage(usage: LlmCallUsage) -> None:
    """Append a call's usage to the active bucket, if any. Never raises."""
    bucket = _usage_bucket.get()
    if bucket is not None:
        bucket.append(usage)


@contextmanager
def capture_llm_usage() -> Iterator[list[LlmCallUsage]]:
    """Scope a fresh usage bucket. Every non-mock LLM call inside the ``with``
    (including in inherited child tasks) appends to the yielded list."""
    bucket: list[LlmCallUsage] = []
    token = _usage_bucket.set(bucket)
    try:
        yield bucket
    finally:
        _usage_bucket.reset(token)


def usage_from_completion(
    provider: str, model: str, completion: object
) -> LlmCallUsage | None:
    """Normalize the raw provider completion into an ``LlmCallUsage``.

    Handles the two shapes we use:
    * google-genai: ``completion.usage_metadata.{prompt,candidates,total}_token_count``
    * OpenAI-compatible (OpenAI / DeepSeek): ``completion.usage.{prompt,completion,total}_tokens``

    Returns ``None`` (never raises) when the completion carries no usage we can
    read. ``total`` is taken verbatim from the provider — it may exceed
    prompt+completion (reasoning tokens) and is the billing-relevant number.
    """
    try:
        meta = getattr(completion, "usage_metadata", None)
        if meta is not None:  # google-genai
            return LlmCallUsage(
                provider=provider,
                model=model,
                prompt_tokens=_as_int(getattr(meta, "prompt_token_count", 0)),
                completion_tokens=_as_int(getattr(meta, "candidates_token_count", 0)),
                total_tokens=_as_int(getattr(meta, "total_token_count", 0)),
            )
        usage = getattr(completion, "usage", None)
        if usage is not None:  # OpenAI-compatible
            return LlmCallUsage(
                provider=provider,
                model=model,
                prompt_tokens=_as_int(getattr(usage, "prompt_tokens", 0)),
                completion_tokens=_as_int(getattr(usage, "completion_tokens", 0)),
                total_tokens=_as_int(getattr(usage, "total_tokens", 0)),
            )
        return None
    except Exception:
        logger.exception("Failed to extract LLM usage for %s/%s", provider, model)
        return None


# A single call's token count realistically stays well under a million (context
# windows cap ~1-2M). Clamp so a malformed/garbage provider value can't exceed
# the int32 LlmUsage columns and raise at flush — that would poison the caller's
# transaction, and on the plan/regenerate paths that commit is NOT guarded, so a
# flush error would 500 the user and lose the just-generated plan. These counts
# come from the provider response, not the server, so they are treated as
# untrusted. (Postgres promotes SUM(int) to bigint, so aggregates don't overflow.)
_MAX_TOKEN_COUNT = 2_000_000_000  # < int32 max (2_147_483_647)


def _as_int(value: object) -> int:
    """Coerce a provider token count (may be None/garbage) to a bounded
    non-negative int that always fits the int32 column."""
    if value is None:
        return 0
    try:
        return min(max(0, int(value)), _MAX_TOKEN_COUNT)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0
