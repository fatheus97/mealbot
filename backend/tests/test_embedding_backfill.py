"""The daily embedding backfill (app.services.embedding_backfill).

Real commits on their own connections, like the job in production: it reads,
then embeds and writes each meal in a short transaction of its own.
"""
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete

from app.core.email_normalize import normalize_email
from app.core.security import get_password_hash
from app.models.db_models import MealEntry, MealPlan, User
from app.scripts import backfill_meal_embeddings
from app.services.embedding_backfill import BackfillCounts, backfill_missing_embeddings
from app.services.recipe_retriever import EmbedProbe
from tests.conftest import TEST_PASSWORD

_VECTOR = [0.25] * 384

AddMeal = Callable[..., Awaitable[int]]


def _meal_json(name: str) -> str:
    return json.dumps({"name": name, "meal_type": "lunch", "ingredients": [], "steps": ["Eat"]})


@pytest.fixture
async def add_meal(
    test_engine: AsyncEngine, request: pytest.FixtureRequest
) -> AsyncGenerator[AddMeal]:
    """A committed user with one plan; add_meal(name, ...) commits a meal in it."""
    email = f"backfill-{abs(hash(request.node.name))}@example.com"
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        user = User(
            email=email,
            normalized_email=normalize_email(email),
            hashed_password=get_password_hash(TEST_PASSWORD),
            email_verified_at=datetime.now(UTC),
        )
        s.add(user)
        await s.flush()
        assert user.id is not None and user.household_id is not None
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            days=1,
            meals_per_day=1,
            people_count=1,
            request_json="{}",
            response_json="{}",
        )
        s.add(plan)
        await s.commit()
    slot = 0

    async def add(
        name: str,
        *,
        favorite: bool = True,
        embedding: list[float] | None = None,
        meal_json: str | None = None,
        leftover: bool = False,
    ) -> int:
        nonlocal slot
        slot += 1
        assert plan.id is not None and user.household_id is not None
        entry = MealEntry(
            household_id=user.household_id,
            meal_plan_id=plan.id,
            day_index=1,
            meal_index=slot,
            name=name,
            meal_type="lunch",
            meal_json=meal_json if meal_json is not None else _meal_json(name),
            is_favorite=favorite,
            embedding=embedding,
            leftover_of_day_index=1 if leftover else None,
            leftover_of_meal_index=1 if leftover else None,
        )
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            s.add(entry)
            await s.commit()
        assert entry.id is not None
        return entry.id

    try:
        yield add
    finally:
        # The household goes with its last member, and takes plan and meals.
        async with AsyncSession(test_engine) as s:
            await s.execute(delete(User).where(col(User.id) == user.id))
            await s.commit()


async def _embedding(test_engine: AsyncEngine, entry_id: int) -> list[float] | None:
    async with AsyncSession(test_engine) as s:
        entry = await s.get(MealEntry, entry_id)
    assert entry is not None
    return None if entry.embedding is None else [float(x) for x in entry.embedding]


async def _run(test_engine: AsyncEngine) -> BackfillCounts:
    async with AsyncSession(test_engine, expire_on_commit=False) as s:
        return await backfill_missing_embeddings(s)


async def _run_checking_no_transaction(
    test_engine: AsyncEngine, embed: Callable[[EmbedProbe], Awaitable[None]]
) -> BackfillCounts:
    """Run with ``embed``, asserting the job's session has no transaction open
    whenever it embeds: no read or write may stay open across one."""
    open_during_embed: list[bool] = []
    async with AsyncSession(test_engine, expire_on_commit=False) as s:

        async def checked(probe: EmbedProbe) -> None:
            open_during_embed.append(s.in_transaction())
            await embed(probe)

        with patch("app.services.embedding_backfill.embed_meal_entry", side_effect=checked):
            counts = await backfill_missing_embeddings(s)
    assert open_during_embed and not any(open_during_embed)
    return counts


async def _fake_embed(probe: EmbedProbe) -> None:
    probe.embedding = _VECTOR


async def test_it_embeds_only_favourites_without_a_vector(
    add_meal: AddMeal, test_engine: AsyncEngine
) -> None:
    missing = await add_meal("Lost star")
    has_one = await add_meal("Kept star", embedding=[0.9] * 384)
    not_starred = await add_meal("Plain meal", favorite=False)
    leftover = await add_meal("Reheat", leftover=True)
    embedded: list[str] = []

    async def embed(probe: EmbedProbe) -> None:
        embedded.append(probe.name)
        probe.embedding = _VECTOR

    with patch("app.services.embedding_backfill.embed_meal_entry", side_effect=embed):
        counts = await _run(test_engine)

    assert embedded == ["Lost star"]
    assert counts == BackfillCounts(embedded=1, unreadable=0, failed=0)
    assert await _embedding(test_engine, missing) == pytest.approx(_VECTOR)
    assert await _embedding(test_engine, has_one) == pytest.approx([0.9] * 384)
    assert await _embedding(test_engine, not_starred) is None
    assert await _embedding(test_engine, leftover) is None


async def test_a_second_run_finds_nothing(add_meal: AddMeal, test_engine: AsyncEngine) -> None:
    await add_meal("Lost star")
    with patch("app.services.embedding_backfill.embed_meal_entry", side_effect=_fake_embed):
        first = await _run(test_engine)
        second = await _run(test_engine)
    assert first.embedded == 1
    assert second == BackfillCounts(embedded=0, unreadable=0, failed=0)


async def test_unreadable_content_is_skipped_without_failing_the_run(
    add_meal: AddMeal, test_engine: AsyncEngine
) -> None:
    broken = await add_meal("Broken", meal_json='{"name": "Broken"}')
    fine = await add_meal("Fine")

    # The real embed parses meal_json first, so the broken row raises there
    # without the model being loaded; the fine row gets the fake.
    from app.services.recipe_retriever import embed_meal_entry as real_embed

    async def embed(probe: EmbedProbe) -> None:
        if probe.name == "Broken":
            await real_embed(probe)
        probe.embedding = _VECTOR

    counts = await _run_checking_no_transaction(test_engine, embed)

    assert counts == BackfillCounts(embedded=1, unreadable=1, failed=0)
    assert await _embedding(test_engine, broken) is None
    assert await _embedding(test_engine, fine) == pytest.approx(_VECTOR)


async def test_a_failed_embed_counts_as_failed_and_the_rest_still_run(
    add_meal: AddMeal, test_engine: AsyncEngine
) -> None:
    first = await add_meal("Times out")
    second = await add_meal("Fine")

    async def embed(probe: EmbedProbe) -> None:
        if probe.name == "Times out":
            raise TimeoutError
        probe.embedding = _VECTOR

    with patch("app.services.embedding_backfill.embed_meal_entry", side_effect=embed):
        counts = await _run(test_engine)

    assert counts == BackfillCounts(embedded=1, unreadable=0, failed=1)
    assert await _embedding(test_engine, first) is None
    assert await _embedding(test_engine, second) == pytest.approx(_VECTOR)


async def test_a_failed_write_counts_as_failed_and_the_rest_still_run(
    add_meal: AddMeal, test_engine: AsyncEngine
) -> None:
    """A failed write rolls its transaction back, so the next meal's write
    runs on a clean one rather than an aborted transaction."""
    rejected = await add_meal("Lost star")
    after = await add_meal("Next star")

    async def wrong_size_first(probe: EmbedProbe) -> None:
        # The column is vector(384): three numbers make the UPDATE fail.
        probe.embedding = [0.1] * 3 if probe.name == "Lost star" else _VECTOR

    counts = await _run_checking_no_transaction(test_engine, wrong_size_first)

    assert counts == BackfillCounts(embedded=1, unreadable=0, failed=1)
    assert await _embedding(test_engine, rejected) is None
    assert await _embedding(test_engine, after) == pytest.approx(_VECTOR)


@pytest.mark.parametrize(
    "change",
    [
        {"is_favorite": False},
        {"meal_json": _meal_json("Edited meanwhile")},
        {"embedding": [0.7] * 384},
    ],
    ids=["unstarred", "edited", "embedded-by-the-request"],
)
async def test_a_meal_that_changed_during_the_embed_keeps_its_state(
    add_meal: AddMeal, test_engine: AsyncEngine, change: dict[str, object]
) -> None:
    entry_id = await add_meal("Lost star")

    async def embed_while_the_user_acts(probe: EmbedProbe) -> None:
        async with AsyncSession(test_engine) as s:
            await s.execute(update(MealEntry).where(col(MealEntry.id) == entry_id).values(**change))
            await s.commit()
        probe.embedding = _VECTOR

    with patch(
        "app.services.embedding_backfill.embed_meal_entry", side_effect=embed_while_the_user_acts
    ):
        counts = await _run(test_engine)

    # A lost race is not a failure: it must not fire the daily alert.
    assert counts == BackfillCounts(embedded=1, unreadable=0, failed=0)
    expected = change.get("embedding")
    stored = await _embedding(test_engine, entry_id)
    if expected is None:
        assert stored is None
    else:
        assert stored == pytest.approx(expected)


@pytest.mark.parametrize(
    ("counts", "code"),
    [
        (BackfillCounts(embedded=3, unreadable=1, failed=0), 0),
        (BackfillCounts(embedded=0, unreadable=0, failed=1), 1),
    ],
)
async def test_the_script_fails_only_when_something_failed(
    counts: BackfillCounts, code: int
) -> None:
    with patch.object(
        backfill_meal_embeddings, "backfill_missing_embeddings", AsyncMock(return_value=counts)
    ):
        assert await backfill_meal_embeddings.main() == code
