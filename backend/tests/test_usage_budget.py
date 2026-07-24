"""Tests for the per-user monthly LLM-cost budget cap.

Covers the cost formula (thinking tokens billed at the output rate), tier/window
resolution, the require_generation_budget enforcement dependency, and the
/usage/me budget block. Enforcement is asserted at the dependency boundary — an
over-budget request is rejected before any generation runs. Ordering (402 before
429) is covered by the existing gating tests in test_billing.py, which now flow
through require_generation_budget.
"""

from datetime import datetime

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_generation_budget
from app.core.config import settings
from app.models.db_models import LlmUsage, User
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
    session: AsyncSession, user_id: int, total_tokens: int, *, prompt: int = 0
) -> None:
    session.add(
        LlmUsage(
            user_id=user_id,
            surface="meal_plan",
            provider="gemini",
            model="gemini-2.5-flash",
            prompt_tokens=prompt,
            completion_tokens=0,
            total_tokens=total_tokens,
        )
    )
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


def test_resolve_budget_trial_window_is_whole_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "usage_cap_trial_eur", 0.75)
    created = datetime(2026, 7, 12, 12, 0, 0)
    trial_end = datetime(2026, 7, 22, 12, 0, 0)
    u = _user(subscription_status="trialing", current_period_end=trial_end)
    u.created_at = created
    b = usage_budget.resolve_budget(u)
    assert b.tier == usage_budget.TIER_TRIAL
    assert b.cap_eur == 0.75
    assert b.window_start == created  # whole membership, not back-computed
    assert b.reset_at == trial_end


def test_resolve_budget_trial_window_immune_to_trial_length_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Grandfathered-trial regression (the #269 review finding): a real 14-day
    # trial while the setting now reads 10 must count from created_at, NOT
    # trial_end − 10d — which would silently drop the first 4 days and let the
    # €0.75 trial cap be spent twice.
    monkeypatch.setattr(settings, "trial_period_days", 10)
    created = datetime(2026, 7, 6, 12, 0, 0)
    trial_end = datetime(2026, 7, 20, 12, 0, 0)  # created + 14d (grandfathered)
    u = _user(subscription_status="trialing", current_period_end=trial_end)
    u.created_at = created
    b = usage_budget.resolve_budget(u)
    assert b.window_start == created  # not created + 4d


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
