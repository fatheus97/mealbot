"""Tests for the per-user monthly LLM-cost budget cap.

Covers the cost formula (thinking tokens billed at the output rate), tier/window
resolution, the require_generation_budget enforcement dependency, and the
/usage/me budget block. Enforcement is asserted at the dependency boundary — an
over-budget request is rejected before any generation runs. Ordering (402 before
429) is covered by the existing gating tests in test_billing.py, which now flow
through require_generation_budget.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_generation_budget
from app.core.config import settings
from app.models.db_models import LlmUsage, User
from app.models.usage_schemas import BudgetStatus
from app.services import llm_cost, usage_budget


def _user(**kwargs) -> User:
    base = dict(
        email="e@example.com",
        hashed_password="x",
        is_admin=False,
        is_demo=False,
        subscription_status="none",
    )
    base.update(kwargs)
    u = User(**base)
    if u.id is None:
        u.id = 1
    return u


async def _seed(
    session: AsyncSession,
    user_id: int,
    total_tokens: int,
    *,
    prompt: int = 0,
    created_at: datetime | None = None,
) -> None:
    row = LlmUsage(
        user_id=user_id,
        surface="meal_plan",
        provider="gemini",
        model="gemini-2.5-flash",
        prompt_tokens=prompt,
        completion_tokens=0,
        total_tokens=total_tokens,
    )
    if created_at is not None:
        row.created_at = created_at
    session.add(row)
    await session.flush()


# --------------------------------------------------------------------------- #
# Cost formula
# --------------------------------------------------------------------------- #
def test_cost_bills_thinking_tokens_at_output_rate() -> None:
    # prompt=4000, completion=1500, total=7500 → 2000 "thinking" tokens are hidden
    # in total. The output side must be (total − prompt)=3500, NOT completion.
    rate = llm_cost.rate_for("gemini", "gemini-2.5-flash")
    cost = llm_cost.cost_of(4000, 7500, "gemini", "gemini-2.5-flash")
    expected = 4000 * rate.input_eur_per_token + 3500 * rate.output_eur_per_token
    assert cost == pytest.approx(expected)
    # Charging completion (1500) alone would undercount — regression guard.
    undercount = 4000 * rate.input_eur_per_token + 1500 * rate.output_eur_per_token
    assert cost > undercount


def test_cost_unknown_model_falls_back_to_max_rate() -> None:
    known_max_out = max(
        r.output_eur_per_token for r in llm_cost.MODEL_COST_RATES.values()
    )
    cost = llm_cost.cost_of(0, 1_000_000, "acme", "mystery-model")
    assert cost == pytest.approx(1_000_000 * known_max_out)
    assert cost > 0.0  # never free on config drift


def test_cost_negative_output_clamped_to_zero() -> None:
    rate = llm_cost.rate_for("gemini", "gemini-2.5-flash")
    cost = llm_cost.cost_of(1000, 500, "gemini", "gemini-2.5-flash")
    assert cost == pytest.approx(1000 * rate.input_eur_per_token)


# --------------------------------------------------------------------------- #
# Tier / window resolution
# --------------------------------------------------------------------------- #
def test_resolve_budget_admin_and_demo_unlimited() -> None:
    assert (
        usage_budget.resolve_budget(_user(is_admin=True)).tier
        == usage_budget.TIER_UNLIMITED
    )
    assert (
        usage_budget.resolve_budget(_user(is_demo=True)).tier
        == usage_budget.TIER_UNLIMITED
    )


def test_resolve_budget_comped_gets_paid_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "usage_cap_paid_eur", 2.0)
    b = usage_budget.resolve_budget(_user(is_comped=True))
    assert b.tier == usage_budget.TIER_PAID
    assert b.cap_eur == 2.0


def test_resolve_budget_none_status_falls_through_to_paid() -> None:
    # Today's prod population: status "none", billing off. Must still be capped.
    assert (
        usage_budget.resolve_budget(_user(subscription_status="none")).tier
        == usage_budget.TIER_PAID
    )


def test_resolve_budget_trial_window_excludes_pre_trial_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An existing (months-old) billing-off user who converts to trialing must NOT
    # have their whole history counted — the window starts at the trial grant
    # (trial_end − trial_period_days ≈ checkout), not created_at. Regression guard
    # for the overcount that would 429 a converting user on their first request.
    monkeypatch.setattr(settings, "trial_period_days", 10)
    monkeypatch.setattr(settings, "usage_cap_trial_eur", 0.75)
    created = datetime(2026, 1, 1, 12, 0, 0)  # account is months old
    trial_end = datetime(2026, 7, 20, 12, 0, 0)  # fresh 10-day trial grant
    u = _user(subscription_status="trialing", current_period_end=trial_end)
    u.created_at = created
    b = usage_budget.resolve_budget(u)
    assert b.tier == usage_budget.TIER_TRIAL
    assert b.cap_eur == 0.75
    # trial_end − 10d, NOT created_at (which would drag in months of history).
    assert b.window_start == datetime(2026, 7, 10, 12, 0, 0)
    assert b.reset_at == trial_end


def test_resolve_budget_trial_window_clamps_to_created_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A brand-new user whose (trial_end − trial_period_days) would predate their
    # account clamps to created_at so the window never precedes the account.
    monkeypatch.setattr(settings, "trial_period_days", 14)
    created = datetime(2026, 7, 18, 12, 0, 0)
    trial_end = datetime(2026, 7, 20, 12, 0, 0)  # − 14d predates created_at
    u = _user(subscription_status="trialing", current_period_end=trial_end)
    u.created_at = created
    b = usage_budget.resolve_budget(u)
    assert b.window_start == created


# --------------------------------------------------------------------------- #
# get_budget_status + enforcement dependency
# --------------------------------------------------------------------------- #
async def test_get_budget_status_sums_spend_and_soft_warns(
    test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "usage_cap_paid_eur", 2.0)
    monkeypatch.setattr(settings, "usage_soft_warn_ratio", 0.8)
    test_user.subscription_status = "none"
    assert test_user.id is not None
    rate = llm_cost.rate_for("gemini", "gemini-2.5-flash")
    tokens = int(1.7 / rate.output_eur_per_token)  # ~85% of €2
    await _seed(db_session, test_user.id, tokens)
    st = await usage_budget.get_budget_status(db_session, test_user)
    assert st.tier == "paid"
    assert st.cap_eur == 2.0
    assert st.used_eur == pytest.approx(1.7, rel=1e-3)
    assert st.remaining_eur == pytest.approx(0.3, abs=0.02)
    assert st.soft_warn is True
    assert usage_budget.is_over_budget(st) is False


async def test_trial_window_excludes_usage_before_window_start(
    test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proves the fix at the compute_window_cost seam (not just window resolution):
    # a converting user's pre-trial usage must NOT count toward the trial cap.
    monkeypatch.setattr(settings, "trial_period_days", 10)
    monkeypatch.setattr(settings, "usage_cap_trial_eur", 0.75)
    now = datetime.now(UTC).replace(tzinfo=None)
    test_user.subscription_status = "trialing"
    test_user.current_period_end = now + timedelta(days=5)  # trial start ≈ now − 5d
    test_user.created_at = now - timedelta(days=90)  # account 90 days old
    assert test_user.id is not None
    rate = llm_cost.rate_for("gemini", "gemini-2.5-flash")
    await _seed(  # 60 days ago — OUTSIDE the trial window, must not count
        db_session,
        test_user.id,
        int(0.5 / rate.output_eur_per_token),
        created_at=now - timedelta(days=60),
    )
    await _seed(  # today — inside the window, counts
        db_session,
        test_user.id,
        int(0.2 / rate.output_eur_per_token),
        created_at=now,
    )
    st = await usage_budget.get_budget_status(db_session, test_user)
    assert st.tier == "trial"
    assert st.used_eur == pytest.approx(0.2, rel=2e-2)  # only the in-window row


async def test_require_generation_budget_blocks_over_cap(
    test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "usage_cap_enabled", True)
    monkeypatch.setattr(settings, "usage_cap_paid_eur", 2.0)
    test_user.subscription_status = "none"
    assert test_user.id is not None
    rate = llm_cost.rate_for("gemini", "gemini-2.5-flash")
    await _seed(db_session, test_user.id, int(2.5 / rate.output_eur_per_token))
    with pytest.raises(HTTPException) as exc:
        await require_generation_budget(current_user=test_user, session=db_session)
    assert exc.value.status_code == 429
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["code"] == "usage_cap_reached"
    assert exc.value.headers is not None
    assert exc.value.headers["Retry-After"].isdigit()
    # The dict was ALL there was until #352, and the frontend only understood a
    # string detail — so the one error where retrying can never work was the one
    # rendered as "Plan generation failed. Please try again.", for up to a month.
    assert isinstance(exc.value.detail["user_detail"], str)
    assert "€2.00" in exc.value.detail["user_detail"]


async def test_require_generation_budget_allows_under_cap(
    test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "usage_cap_enabled", True)
    monkeypatch.setattr(settings, "usage_cap_paid_eur", 2.0)
    test_user.subscription_status = "none"
    result = await require_generation_budget(current_user=test_user, session=db_session)
    assert result is test_user


async def test_require_generation_budget_kill_switch_bypasses(
    test_user: User, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "usage_cap_enabled", False)
    monkeypatch.setattr(settings, "usage_cap_paid_eur", 2.0)
    assert test_user.id is not None
    rate = llm_cost.rate_for("gemini", "gemini-2.5-flash")
    await _seed(db_session, test_user.id, int(10 / rate.output_eur_per_token))
    result = await require_generation_budget(current_user=test_user, session=db_session)
    assert result is test_user


async def test_require_generation_budget_admin_bypasses(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "usage_cap_enabled", True)
    admin = _user(is_admin=True, id=4242)
    result = await require_generation_budget(current_user=admin, session=db_session)
    assert result is admin


async def test_usage_me_exposes_budget_block(
    client: AsyncClient, auth_headers: dict[str, str], test_user: User
) -> None:
    resp = await client.get("/api/usage/me", headers=auth_headers)
    assert resp.status_code == 200
    budget = resp.json()["budget"]
    assert budget["tier"] in {"paid", "trial", "unlimited"}
    assert "reset_at" in budget
    assert "used_eur" in budget


class TestCapReachedMessage:
    """The sentence a capped user reads. Wording is load-bearing: this error is
    the only one where the app's usual advice — try again — is guaranteed wrong.
    """

    def _status(self, **kwargs: object) -> BudgetStatus:
        base: dict[str, object] = dict(
            tier="paid",
            cap_eur=2.0,
            used_eur=2.0,
            remaining_eur=0.0,
            reset_at=datetime(2026, 9, 1),
            soft_warn=True,
        )
        base.update(kwargs)
        return BudgetStatus(**base)  # type: ignore[arg-type]

    def test_paid_names_the_amount_and_the_reset_date(self) -> None:
        msg = usage_budget.cap_reached_message(self._status())
        assert "€2.00" in msg
        assert "1 September 2026" in msg
        assert "resets" in msg

    def test_trial_does_not_claim_a_reset(self) -> None:
        # For TIER_TRIAL, reset_at is trial_end — nothing resets on that date.
        # Trial users are precisely the ones deciding whether to pay, so a
        # convenient half-truth here is the most expensive place to put one.
        msg = usage_budget.cap_reached_message(
            self._status(tier="trial", cap_eur=0.75, used_eur=0.75)
        )
        assert "resets" not in msg
        assert "free trial" in msg
        assert "€0.75" in msg

    def test_promises_nothing_about_the_post_trial_allowance(self) -> None:
        # Both caps are env-configurable, so "you'll get more room after the
        # trial" is only true under today's settings.
        msg = usage_budget.cap_reached_message(self._status(tier="trial", cap_eur=0.75))
        assert "more" not in msg.lower()

    def test_says_retrying_will_not_help(self) -> None:
        # Without this the user retries for a month. "Paused until then" is the
        # whole point of the message.
        assert "paused until then" in usage_budget.cap_reached_message(self._status())

    def test_names_every_gated_surface(self) -> None:
        # require_generation_budget gates plan create, plan regenerate, single
        # recipe AND receipt scan. Naming only some of them sends the user off to
        # the one it did not mention, to find that dead too.
        msg = usage_budget.cap_reached_message(self._status())
        assert "plans" in msg and "recipes" in msg and "receipt scanning" in msg

    def test_says_saved_work_is_safe(self) -> None:
        # A hard stop on generation reads as a total outage otherwise.
        assert "unaffected" in usage_budget.cap_reached_message(self._status())

    def test_survives_a_null_cap(self) -> None:
        # Unreachable via is_over_budget (null cap is never over), but the
        # function must not raise if a caller ever gets that wrong.
        msg = usage_budget.cap_reached_message(
            self._status(tier="unlimited", cap_eur=None, remaining_eur=None)
        )
        assert "€" in msg


async def test_capped_generation_returns_a_readable_detail(
    client: AsyncClient,
    auth_headers: dict[str, str],
    test_user: User,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end over HTTP: the JSON the browser actually receives.

    The dependency-level test above asserts the dict; this asserts it survives
    FastAPI serialization, because that JSON is what extractErrorDetail reads.
    """
    monkeypatch.setattr(settings, "usage_cap_enabled", True)
    monkeypatch.setattr(settings, "usage_cap_paid_eur", 2.0)
    assert test_user.id is not None
    rate = llm_cost.rate_for("gemini", "gemini-2.5-flash")
    await _seed(db_session, test_user.id, int(2.5 / rate.output_eur_per_token))
    await db_session.commit()

    resp = await client.post(
        "/api/plan?days=1",
        headers=auth_headers,
        json={"days": 1, "meals_per_day": 1},
    )
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "usage_cap_reached"
    assert "€2.00" in detail["user_detail"]
    assert "paused until then" in detail["user_detail"]
