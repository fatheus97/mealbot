"""Tests for POST /api/plan/{id}/repeat — copy a plan forward to a new date.

No LLM is involved, so these drive the real endpoint end to end rather than
mocking a generator: everything the feature does is database and arithmetic.
"""
from datetime import UTC, date, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, func, select

from app.models.db_models import MealEntry, MealPlan, StockItem, User
from app.models.plan_models import MealPlanRequest, MealPlanResponse

ENDPOINT = "/api/plan/{}/repeat"


def _response_json(*, shopping: list[dict[str, object]] | None = None) -> str:
    """A minimal but REAL MealPlanResponse — validated by the same model the
    endpoint parses with, so a schema drift breaks these tests rather than
    letting them pass against a shape the app would reject."""
    return MealPlanResponse.model_validate(
        {
            "plan_id": None,
            "days": [
                {
                    "day_index": 1,
                    "meals": [
                        {
                            "meal_index": 1,
                            "meal_type": "hot_dinner",
                            "name": "Lentil stew",
                            "ingredients": [
                                {"name": "lentils", "quantity_grams": 300},
                                {"name": "carrot", "quantity_grams": 200},
                            ],
                            "steps": ["Simmer 300 g lentils with 200 g carrot."],
                        }
                    ],
                }
            ],
            "shopping_list": shopping
            if shopping is not None
            else [{"name": "lentils", "quantity_grams": 300}],
        }
    ).model_dump_json()


async def _plan(
    db_session: AsyncSession,
    user: User,
    *,
    start_date: date | None = date(2026, 8, 3),
    confirmed: bool = True,
    response_json: str | None = None,
    include_spices: bool = True,
) -> MealPlan:
    request = MealPlanRequest.model_validate(
        {"meals_per_day": 1, "people_count": 2, "include_spices": include_spices}
    )
    plan = MealPlan(
        user_id=user.id,
        days=1,
        meals_per_day=1,
        people_count=2,
        start_date=start_date,
        request_json=request.model_dump_json(),
        response_json=response_json if response_json is not None else _response_json(),
        confirmed_at=datetime.now(UTC) if confirmed else None,
        finished_at=datetime.now(UTC) if confirmed else None,
        stock_after_json="[]" if confirmed else None,
    )
    db_session.add(plan)
    await db_session.flush()
    return plan


async def _plan_count(session: AsyncSession, user_id: int) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(MealPlan)
            .where(col(MealPlan.user_id) == user_id)
        )
    ).scalar_one()


class TestRepeatGate:
    async def test_unauthenticated_is_rejected(
        self, unauthed_client: AsyncClient
    ) -> None:
        resp = await unauthed_client.post(ENDPOINT.format(1), json={})
        assert resp.status_code in (401, 403)

    async def test_another_users_plan_is_404_not_403(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """404, not 403 — a 403 would confirm the id exists, which is a plan-id
        oracle for someone else's account."""
        other = User(email="other-repeat@x.com", hashed_password="x")
        db_session.add(other)
        await db_session.flush()
        theirs = await _plan(db_session, other)

        resp = await client.post(
            ENDPOINT.format(theirs.id), json={}, headers=auth_headers
        )
        assert resp.status_code == 404


class TestRepeatCopies:
    async def test_copies_the_meals_to_a_new_date_as_a_new_plan(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        source = await _plan(db_session, test_user)
        await db_session.commit()
        uid = test_user.id
        assert uid is not None

        resp = await client.post(
            ENDPOINT.format(source.id),
            json={"start_date": "2026-08-17"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        assert body["plan_id"] != source.id
        assert body["start_date"] == "2026-08-17"
        assert body["days"][0]["meals"][0]["name"] == "Lentil stew"
        assert await _plan_count(db_session, uid) == 2

    async def test_the_source_plan_is_left_completely_alone(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Repeating must not quietly reschedule the plan you copied."""
        source = await _plan(db_session, test_user, start_date=date(2026, 8, 3))
        await db_session.commit()
        source_id = source.id

        await client.post(
            ENDPOINT.format(source_id),
            json={"start_date": "2026-08-17"},
            headers=auth_headers,
        )

        db_session.expire_all()
        again = await db_session.get(MealPlan, source_id)
        assert again is not None
        assert again.start_date == date(2026, 8, 3)
        assert again.confirmed_at is not None
        assert again.finished_at is not None

    async def test_the_copy_starts_unconfirmed_however_far_the_source_got(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """A copy is a plan you have not shopped for, cooked or finished. The
        source here is confirmed AND finished with a stock snapshot; none of
        that may come along, or the new week arrives already 'done'."""
        source = await _plan(db_session, test_user, confirmed=True)
        await db_session.commit()

        resp = await client.post(
            ENDPOINT.format(source.id), json={}, headers=auth_headers
        )
        assert resp.status_code == 200

        copy = await db_session.get(MealPlan, resp.json()["plan_id"])
        assert copy is not None
        assert copy.confirmed_at is None
        assert copy.finished_at is None
        assert copy.stock_after_json is None
        # MealEntry rows are created at CONFIRM, so a fresh plan has none and
        # the copy must have none either. Counted with a query rather than the
        # relationship: a lazy load on an async session raises MissingGreenlet.
        entries = (
            await db_session.execute(
                select(func.count())
                .select_from(MealEntry)
                .where(col(MealEntry.meal_plan_id) == copy.id)
            )
        ).scalar_one()
        assert entries == 0

    async def test_a_null_start_date_creates_an_unscheduled_copy(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        source = await _plan(db_session, test_user)
        await db_session.commit()

        resp = await client.post(
            ENDPOINT.format(source.id), json={}, headers=auth_headers
        )
        assert resp.status_code == 200
        assert resp.json()["start_date"] is None

    async def test_repeating_an_unconfirmed_plan_does_not_delete_the_source(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """THE trap this endpoint exists around.

        Plan CREATION calls clear_unconfirmed_plans, which deletes the user's
        unconfirmed plans before saving. Doing that here would delete the source
        out from under the copy whenever the source is itself unconfirmed — you
        would press Repeat and watch the plan you repeated disappear.
        """
        source = await _plan(db_session, test_user, confirmed=False)
        await db_session.commit()
        uid = test_user.id
        assert uid is not None
        source_id = source.id

        resp = await client.post(
            ENDPOINT.format(source_id), json={}, headers=auth_headers
        )
        assert resp.status_code == 200

        db_session.expire_all()
        assert await db_session.get(MealPlan, source_id) is not None
        assert await _plan_count(db_session, uid) == 2


class TestRepeatRecomputesTheShoppingList:
    async def test_ingredients_now_in_the_fridge_drop_off_the_list(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """The reason the list is recomputed rather than copied.

        The source's frozen list says "buy 300 g lentils" — computed against the
        fridge as it stood then. The user has since bought lentils. A verbatim
        copy would send them to the shop for something already in the cupboard.
        """
        source = await _plan(db_session, test_user)
        db_session.add(
            StockItem(user_id=test_user.id, name="lentils", quantity_grams=500)
        )
        await db_session.commit()

        resp = await client.post(
            ENDPOINT.format(source.id), json={}, headers=auth_headers
        )
        assert resp.status_code == 200

        names = [i["name"] for i in resp.json()["shopping_list"]]
        assert "lentils" not in names
        # And the source's own frozen list is untouched — plans are immutable
        # once written.
        original = MealPlanResponse.model_validate_json(
            (await db_session.get(MealPlan, source.id)).response_json  # type: ignore[union-attr]
        )
        assert [i.name for i in original.shopping_list] == ["lentils"]

    async def test_ingredients_since_used_up_reappear_on_the_list(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """The other direction, and the one a verbatim copy fails silently:
        the source was generated when the fridge already held the carrot, so its
        frozen list never mentioned it. The fridge is empty now, so the copy
        must."""
        source = await _plan(db_session, test_user, response_json=_response_json(shopping=[]))
        await db_session.commit()

        resp = await client.post(
            ENDPOINT.format(source.id), json={}, headers=auth_headers
        )
        assert resp.status_code == 200

        names = {i["name"] for i in resp.json()["shopping_list"]}
        assert {"lentils", "carrot"} <= names

    async def test_the_copied_request_carries_the_CURRENT_spice_preference(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """A later REGENERATE reads its options from the stored request and keys
        on the STORED include_spices. The list above was just computed with the
        LIVE preference, so the copy has to carry that same value or a
        regenerate would disagree with the list shown beside it."""
        source = await _plan(db_session, test_user, include_spices=True)
        test_user.include_spices = False
        db_session.add(test_user)
        await db_session.commit()

        resp = await client.post(
            ENDPOINT.format(source.id), json={}, headers=auth_headers
        )
        assert resp.status_code == 200

        copy = await db_session.get(MealPlan, resp.json()["plan_id"])
        assert copy is not None
        assert MealPlanRequest.model_validate_json(copy.request_json).include_spices is False


class TestRepeatUnreadableSource:
    async def test_a_plan_whose_json_no_longer_parses_is_422_not_500(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """The row is real and owned; its stored JSON just predates a schema
        change. That is a 422 with a sentence, not a stack trace."""
        source = await _plan(db_session, test_user, response_json="{not json")
        await db_session.commit()
        uid = test_user.id
        assert uid is not None

        resp = await client.post(
            ENDPOINT.format(source.id), json={}, headers=auth_headers
        )
        assert resp.status_code == 422
        # And nothing was created.
        assert await _plan_count(db_session, uid) == 1


class TestRepeatRefusesWhatIsNotAWeek:
    async def test_a_cook_now_plan_cannot_be_repeated(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Cook Now is a different lane, and a copy of one is unreachable.

        Those plans are auto-confirmed on creation, while a copy is deliberately
        created UNCONFIRMED — and both `list_plans` and `plan_calendar` filter on
        `kind == "planned"`. So the copy would fail both filters at once:
        invisible in the catalog, invisible on the calendar, swept by the next
        generation. Refused server-side rather than left to the UI, because the
        endpoint is reachable without it.
        """
        source = await _plan(db_session, test_user)
        source.kind = "cook_now"
        db_session.add(source)
        await db_session.commit()
        uid = test_user.id
        assert uid is not None

        resp = await client.post(
            ENDPOINT.format(source.id), json={}, headers=auth_headers
        )

        assert resp.status_code == 422
        assert await _plan_count(db_session, uid) == 1

    async def test_an_out_of_range_start_date_is_rejected(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        """Every other date-accepting model in plan_models runs start_date
        through `validate_plan_start_date`; this one skipped it, so the endpoint
        would happily persist year 9999 onto a real row and junk the calendar."""
        source = await _plan(db_session, test_user)
        await db_session.commit()
        uid = test_user.id
        assert uid is not None

        resp = await client.post(
            ENDPOINT.format(source.id),
            json={"start_date": "9999-12-31"},
            headers=auth_headers,
        )

        assert resp.status_code == 422
        assert await _plan_count(db_session, uid) == 1
