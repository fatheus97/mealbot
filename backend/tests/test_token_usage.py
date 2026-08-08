"""Tests for LLM token-usage capture (app.llm.usage) and best-effort
persistence (app.services.token_usage)."""

from types import SimpleNamespace

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.llm.usage import (
    _MAX_TOKEN_COUNT,
    LlmCallUsage,
    _as_int,
    capture_llm_usage,
    record_call_usage,
    usage_from_completion,
)
from app.models.db_models import LlmUsage, User
from app.services.token_usage import record_llm_usage


def _u(prompt: int = 1, completion: int = 1, total: int = 2) -> LlmCallUsage:
    return LlmCallUsage(
        provider="gemini",
        model="gemini-2.5-flash",
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )


class TestTokenCountCoercion:
    """`_as_int` bounds a provider-supplied token count. The counts are
    untrusted (they come from the provider response) and they feed the per-user
    LLM cost cap, so a value that escapes coercion costs a whole unrecorded
    call."""

    def test_infinity_does_not_escape(self) -> None:
        """int(float("inf")) raises OverflowError, which was NOT in the except
        clause — nan raised ValueError and was caught, inf and -inf propagated
        into usage_from_completion's outer `except Exception` and dropped the
        whole record. Neither provider shape can produce inf today, so this is
        a boundary guard, not a fixed incident."""
        assert _as_int(float("inf")) == 0
        assert _as_int(float("-inf")) == 0

    def test_nan_and_junk_coerce_to_zero(self) -> None:
        assert _as_int(float("nan")) == 0
        assert _as_int(None) == 0
        assert _as_int("not a number") == 0
        assert _as_int({"tokens": 5}) == 0

    def test_ordinary_counts_survive(self) -> None:
        assert _as_int(42) == 42
        assert _as_int("42") == 42
        assert _as_int(7.9) == 7
        assert _as_int(-5) == 0  # clamped non-negative

    def test_coercible_non_builtin_types_still_work(self) -> None:
        """Guards the shape of the fix: an isinstance gate listing int/float/str
        would silently zero these. int() accepts anything with __int__ or
        __index__, and so must this."""
        from decimal import Decimal
        from fractions import Fraction

        class _Countish:
            def __int__(self) -> int:
                return 7

        assert _as_int(Decimal("42")) == 42
        assert _as_int(Fraction(84, 2)) == 42
        assert _as_int(b"42") == 42
        assert _as_int(_Countish()) == 7

    def test_absurd_count_clamps_to_int32_safe_bound(self) -> None:
        assert _as_int(10**12) == _MAX_TOKEN_COUNT


class TestUsageExtraction:
    def test_gemini_shape(self) -> None:
        completion = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=6, candidates_token_count=5, total_token_count=79
            )
        )
        usage = usage_from_completion("gemini", "gemini-2.5-flash", completion)
        assert usage == LlmCallUsage(
            provider="gemini",
            model="gemini-2.5-flash",
            prompt_tokens=6,
            completion_tokens=5,
            total_tokens=79,
        )

    def test_total_is_not_derived_from_prompt_plus_completion(self) -> None:
        # Gemini 2.5 counts reasoning tokens in total only — total (79) must be
        # taken verbatim, not recomputed as prompt+completion (11).
        completion = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=6, candidates_token_count=5, total_token_count=79
            )
        )
        usage = usage_from_completion("gemini", "m", completion)
        assert usage is not None
        assert usage.total_tokens == 79
        assert usage.total_tokens != usage.prompt_tokens + usage.completion_tokens

    def test_openai_shape(self) -> None:
        completion = SimpleNamespace(
            usage=SimpleNamespace(
                prompt_tokens=10, completion_tokens=20, total_tokens=30
            )
        )
        usage = usage_from_completion("openai", "gpt-4o-mini", completion)
        assert usage is not None
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (
            10,
            20,
            30,
        )

    def test_missing_usage_returns_none(self) -> None:
        assert usage_from_completion("gemini", "m", SimpleNamespace()) is None
        assert usage_from_completion("gemini", "m", None) is None

    def test_none_token_fields_coerce_to_zero(self) -> None:
        completion = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count=None,
                candidates_token_count=None,
                total_token_count=None,
            )
        )
        usage = usage_from_completion("gemini", "m", completion)
        assert usage is not None
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (
            0,
            0,
            0,
        )

    def test_garbage_token_field_does_not_raise(self) -> None:
        completion = SimpleNamespace(
            usage_metadata=SimpleNamespace(
                prompt_token_count="oops",
                candidates_token_count=5,
                total_token_count=10,
            )
        )
        usage = usage_from_completion("gemini", "m", completion)
        assert usage is not None
        assert usage.prompt_tokens == 0  # unparseable → 0
        assert usage.total_tokens == 10


class TestCaptureScope:
    def test_record_outside_scope_is_noop(self) -> None:
        # No active bucket → no error, nothing captured.
        record_call_usage(_u())

    def test_capture_collects_calls(self) -> None:
        with capture_llm_usage() as bucket:
            record_call_usage(_u(total=3))
            record_call_usage(_u(total=9))
        assert [u.total_tokens for u in bucket] == [3, 9]

    def test_scopes_are_isolated(self) -> None:
        with capture_llm_usage() as first:
            record_call_usage(_u())
        with capture_llm_usage() as second:
            pass
        assert len(first) == 1
        assert len(second) == 0

    def test_nested_scope_restores_outer(self) -> None:
        with capture_llm_usage() as outer:
            record_call_usage(_u(total=2))
            with capture_llm_usage() as inner:
                record_call_usage(_u(total=6))
            assert len(inner) == 1
            record_call_usage(_u(total=10))  # outer active again
        assert len(outer) == 2


class TestRecordLlmUsage:
    @staticmethod
    async def _rows(session: AsyncSession, user_id: int) -> list[LlmUsage]:
        result = await session.execute(
            select(LlmUsage).where(LlmUsage.user_id == user_id)
        )
        return list(result.scalars().all())

    async def test_records_one_row_per_call(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        uid = test_user.id
        assert uid is not None
        record_llm_usage(
            db_session,
            user_id=uid,
            surface="meal_plan",
            usages=[_u(total=79), _u(total=20)],
        )
        await db_session.flush()
        rows = await self._rows(db_session, uid)
        assert len(rows) == 2
        assert {r.total_tokens for r in rows} == {79, 20}
        assert all(r.surface == "meal_plan" for r in rows)

    async def test_empty_usages_is_noop(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        uid = test_user.id
        assert uid is not None
        record_llm_usage(db_session, user_id=uid, surface="meal_plan", usages=[])
        await db_session.flush()
        assert await self._rows(db_session, uid) == []

    async def test_unknown_surface_is_skipped_not_raised(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        uid = test_user.id
        assert uid is not None
        # Must neither raise nor write a row.
        record_llm_usage(
            db_session,
            user_id=uid,
            surface="not_a_surface",
            usages=[_u()],
        )
        await db_session.flush()
        assert await self._rows(db_session, uid) == []
