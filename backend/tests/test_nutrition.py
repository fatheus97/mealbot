"""Nutrition figures (docs/nutrition-design.md): the table loader, the per-meal
and per-day arithmetic, and GET /api/plan/{id}/nutrition.

Every rule here runs on a small synthetic table whose numbers are easy to
redo; the shipped Ciqual rows have their own gates in test_nutrition_reference.py.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dietary import DietType
from app.core.email_normalize import normalize_email
from app.core.nutrition_reference import (
    ALIAS_COLUMNS,
    DATA_DIR,
    FOOD_COLUMNS,
    Alias,
    Food,
    Lang,
    NutritionDataError,
    NutritionReference,
    load_reference,
    nutrition_reference,
)
from app.core.security import get_password_hash
from app.models.db_models import MealPlan, User
from app.models.plan_models import (
    GRAMS_BASIS,
    MealNutrition,
    MealPlanRequest,
    MealPlanResponse,
    SingleDayResponse,
)
from app.scripts import nutrition_gaps
from app.scripts.nutrition_gaps import MIN_HOUSEHOLDS, StoredPlan, rank_gaps
from app.services.nutrition import day_nutrition, plan_nutrition
from tests.conftest import TEST_PASSWORD


def _food(code: int, name: str, kcal: float, protein: float, fat: float, carb: float) -> Food:
    return Food(
        alim_code=code, name=name, kcal=kcal, kj=kcal * 4.184, protein=protein, fat=fat,
        carbohydrate=carb, polyols=None, fibre=None, sugars=None, alcohol=None,
        organic_acids=None, below_detection=False, confidence="A",
    )


FOODS = {
    1: _food(1, "Rice, white, raw", 350, 7, 1, 78),
    2: _food(2, "Chicken, breast, without skin, raw", 110, 23, 2, 0),
    3: _food(3, "Sweet pepper, raw", 30, 1, 0, 6),
    4: _food(4, "Paprika, powder", 300, 14, 13, 54),
    5: _food(5, "Black pepper, ground", 250, 10, 3, 64),
    6: _food(6, "Honey", 320, 0, 0, 80),
    7: _food(7, "Sunflower oil", 900, 0, 100, 0),
}


def _alias(lang: Lang, key: str, code: int, *, seasoning: bool = False) -> tuple[tuple[Lang, str], Alias]:
    return (lang, key), Alias(lang=lang, key=key, alim_code=code, state="raw",
                              seasoning=seasoning, override_note="")


REF = NutritionReference(
    foods=FOODS,
    aliases=dict([
        _alias("en", "rice", 1),
        _alias("en", "chicken breast", 2),
        _alias("en", "bell pepper", 3),
        _alias("en", "paprika", 4),
        _alias("en", "black pepper", 5, seasoning=True),
        _alias("en", "honey", 6),
        _alias("en", "sunflower oil", 7),
        _alias("cs", "paprika", 3),
        _alias("cs", "rýže", 1),
    ]),
)


def _meal(*ingredients: dict[str, object], basis: int | None = GRAMS_BASIS,
          leftover_of: dict[str, int] | None = None, name: str = "Dish") -> dict[str, object]:
    return {
        "name": name, "meal_type": "hot_dinner", "meal_type_label": "Hot dinner",
        "ingredients": list(ingredients), "steps": ["Cook"],
        "grams_basis": basis, "leftover_of": leftover_of,
    }


def _days(*days: list[dict[str, object]]) -> list[SingleDayResponse]:
    return [SingleDayResponse.model_validate({"meals": meals}) for meals in days]


def _first(days: list[SingleDayResponse], *, language: str = "English", people: int = 2) -> MealNutrition:
    return day_nutrition(days, language=language, people_count=people, ref=REF)[0].meals[0]


RICE = {"name": "rice", "quantity_grams": 200}
CHICKEN = {"name": "chicken breast", "quantity_grams": 300}


class TestKeys:
    def test_an_english_plan_keys_on_the_name(self) -> None:
        meal = _first(_days([_meal(RICE, CHICKEN)]))
        assert [i.status for i in meal.ingredients] == ["counted", "counted"]
        # (350 x 2 + 110 x 3) / 2 servings
        assert meal.per_serving is not None and meal.per_serving.kcal == pytest.approx(515)

    def test_a_czech_plan_keys_on_name_en(self) -> None:
        meal = _first(_days([_meal({"name": "kuřecí prsa", "name_en": "chicken breast", "quantity_grams": 300})]),
                      language="Czech")
        assert meal.ingredients[0].alim_code == 2

    @pytest.mark.parametrize("language", ["Czech", "czech", " CZECH "])
    def test_any_casing_of_czech_reads_the_czech_index(self, language: str) -> None:
        meal = _first(_days([_meal({"name": "rýže", "quantity_grams": 100})]), language=language)
        assert meal.ingredients[0].status == "counted"

    def test_a_czech_name_the_czech_index_knows_wins_over_name_en(self) -> None:
        # The translation can drop what the Czech name says; here the Czech
        # row (bell pepper) and the English one (the spice) differ.
        meal = _first(_days([_meal({"name": "paprika", "name_en": "paprika", "quantity_grams": 150})]),
                      language="Czech")
        assert meal.ingredients[0].alim_code == 3

    def test_a_czech_spice_line_keeps_name_en(self) -> None:
        meal = _first(_days([_meal(RICE, {"name": "paprika", "name_en": "paprika", "quantity_grams": 3,
                                          "is_spice": True})]), language="Czech")
        assert meal.ingredients[1].alim_code == 4

    def test_an_english_plan_never_reads_the_czech_index(self) -> None:
        meal = _first(_days([_meal({"name": "rýže", "name_en": "chicken breast", "quantity_grams": 150})]))
        assert meal.ingredients[0].alim_code == 2

    def test_a_czech_name_without_name_en_uses_the_czech_index(self) -> None:
        # An ingredient renamed in the editor has lost name_en; Czech "paprika"
        # is a bell pepper, never the spice the English key means.
        meal = _first(_days([_meal({"name": "paprika", "quantity_grams": 200})]), language="Czech")
        assert meal.ingredients[0].source_name == "Sweet pepper, raw"
        english = _first(_days([_meal({"name": "paprika", "quantity_grams": 200})]))
        assert english.ingredients[0].source_name == "Paprika, powder"

    def test_another_language_without_name_en_is_not_recognised(self) -> None:
        meal = _first(_days([_meal({"name": "Reis", "quantity_grams": 200})]), language="German")
        assert (meal.ingredients[0].status, meal.ingredients[0].reason) == ("not_counted", "not_recognised")

    def test_an_unknown_key_is_not_in_the_table(self) -> None:
        meal = _first(_days([_meal(RICE, {"name": "kohlrabi", "quantity_grams": 10})]))
        assert meal.ingredients[1].reason == "not_in_table"
        assert meal.complete is False and meal.per_serving is not None  # 200 of 210 g counted

    def test_keys_are_normalised(self) -> None:
        meal = _first(_days([_meal({"name": "  Chicken   Breast ", "quantity_grams": 300})]))
        assert meal.ingredients[0].status == "counted"


class TestSeasoningAndFat:
    def test_a_seasoning_placeholder_is_covered_at_zero(self) -> None:
        meal = _first(_days([_meal(RICE, {"name": "black pepper", "quantity_grams": 1, "is_spice": True})]))
        assert meal.ingredients[1].status == "seasoning"
        assert meal.complete is True
        assert meal.per_serving is not None and meal.per_serving.kcal == pytest.approx(350)

    def test_a_honey_placeholder_is_an_amount_not_given(self) -> None:
        meal = _first(_days([_meal(RICE, {"name": "honey", "quantity_grams": 1, "is_spice": True})]))
        assert meal.ingredients[1].reason == "amount_not_given"
        assert meal.complete is False
        assert meal.coverage == 1.0  # a placeholder weighs nothing in the ratio

    def test_a_real_weight_of_a_seasoning_is_counted(self) -> None:
        meal = _first(_days([_meal(RICE, {"name": "black pepper", "quantity_grams": 4, "is_spice": True})]))
        assert meal.ingredients[1].status == "counted"

    def test_frying_fat_over_the_limit_is_not_counted(self) -> None:
        meal = _first(_days([_meal({"name": "chicken breast", "quantity_grams": 1200},
                                   {"name": "sunflower oil", "quantity_grams": 240})]))
        assert meal.ingredients[1].reason == "frying_fat"  # 120 g per serving
        assert meal.per_serving is not None and meal.per_serving.fat == pytest.approx(12)

    def test_fat_at_the_limit_is_counted(self) -> None:
        meal = _first(_days([_meal({"name": "chicken breast", "quantity_grams": 1200},
                                   {"name": "sunflower oil", "quantity_grams": 100})]))
        assert meal.ingredients[1].status == "counted"

    @pytest.mark.parametrize("water", [
        "boiling water", "water for rice", "water for the pasta", "water (for the dough)",
    ])
    def test_water_is_left_out_of_the_ratio(self, water: str) -> None:
        meal = _first(_days([_meal(RICE, {"name": water, "quantity_grams": 800})]))
        assert meal.ingredients[1].status == "water"
        assert (meal.coverage, meal.complete) == (1.0, True)

    def test_czech_water_for_a_purpose_is_water(self) -> None:
        meal = _first(_days([_meal({"name": "rýže", "quantity_grams": 200},
                                   {"name": "voda na rýži", "quantity_grams": 400})]), language="Czech")
        assert [i.status for i in meal.ingredients] == ["counted", "water"]

    @pytest.mark.parametrize("name", ["water chestnuts", "coconut water", "water (or milk)"])
    def test_a_food_named_after_water_is_not_water(self, name: str) -> None:
        meal = _first(_days([_meal(RICE, {"name": name, "quantity_grams": 100})]))
        assert meal.ingredients[1].status == "not_counted"


class TestWithheld:
    def test_a_meal_from_before_the_weight_rule_has_no_figure(self) -> None:
        meal = _first(_days([_meal(RICE, basis=None)]))
        assert (meal.per_serving, meal.withheld_reason) == (None, "legacy")

    def test_coverage_below_the_floor_has_no_figure(self) -> None:
        meal = _first(_days([_meal(RICE, {"name": "kohlrabi", "quantity_grams": 60})]))
        assert meal.coverage == pytest.approx(200 / 260)
        assert (meal.per_serving, meal.withheld_reason) == (None, "coverage")

    def test_a_meal_of_only_water_and_placeholders_has_no_figure(self) -> None:
        meal = _first(_days([_meal({"name": "water", "quantity_grams": 500},
                                   {"name": "black pepper", "quantity_grams": 1, "is_spice": True})]))
        assert meal.withheld_reason == "coverage"


class TestLeftoversAndDays:
    def test_a_leftover_takes_its_source_per_serving(self) -> None:
        days = _days([_meal(RICE, CHICKEN, name="Batch")],
                     [_meal(name="Leftovers", leftover_of={"day_index": 0, "meal_index": 0})])
        result = day_nutrition(days, language="English", people_count=2, ref=REF)
        batch, leftover = result[0].meals[0], result[1].meals[0]
        assert batch.servings == 4  # 2 people, cooked for two meals
        assert batch.per_serving is not None and batch.per_serving.kcal == pytest.approx(257.5)
        assert leftover.per_serving == batch.per_serving
        assert (leftover.day_index, leftover.ingredients) == (1, [])
        assert result[1].per_person == batch.per_serving

    def test_an_unresolvable_leftover_has_no_figure_and_never_throws(self) -> None:
        days = _days([_meal(name="Leftovers", leftover_of={"day_index": 5, "meal_index": 0})])
        meal = _first(days)
        assert (meal.per_serving, meal.withheld_reason) == (None, "leftover_unresolved")

    def test_a_day_is_withheld_when_one_meal_has_no_figure(self) -> None:
        day = day_nutrition(_days([_meal(RICE), _meal(RICE, basis=None)]),
                            language="English", people_count=2, ref=REF)[0]
        assert day.per_person is None
        assert day.meals[0].per_serving is not None

    def test_a_day_sums_its_meals_and_says_when_one_is_partial(self) -> None:
        day = day_nutrition(_days([_meal(RICE), _meal(CHICKEN, {"name": "kohlrabi", "quantity_grams": 5})]),
                            language="English", people_count=2, ref=REF)[0]
        assert day.per_person is not None and day.per_person.kcal == pytest.approx(350 + 165)
        assert day.partial is True


class TestPlanAvailability:
    @pytest.mark.parametrize(("request_data", "reason"), [
        ({"diet_types": [DietType.BABY_FOOD]}, "infant"),
        ({"health_data_removed": True}, "health_data_removed"),
    ])
    def test_infant_and_removed_plans_get_nothing(self, request_data: dict[str, object], reason: str) -> None:
        result = plan_nutrition(MealPlanRequest.model_validate(request_data), _days([_meal(RICE)]),
                                people_count=2, ref=REF)
        assert (result.available, result.unavailable_reason, result.days) == (False, reason, [])
        assert result.source.doi == "10.57745/RDMHWY"


class TestLoader:
    def test_the_shipped_table_loads(self) -> None:
        ref = load_reference()
        assert set(ref.foods) >= {a.alim_code for a in ref.aliases.values()}

    def test_the_shipped_czech_row_beats_a_less_precise_name_en(self) -> None:
        # The eval answer that showed it: cooked beans translated as plain
        # "white beans", which the English index reads as dried (2.7x the energy).
        ref = load_reference()
        beans = {"name": "vařené bílé fazole", "name_en": "white beans", "quantity_grams": 240}
        [czech] = day_nutrition(_days([_meal(beans)]), language="Czech", people_count=2, ref=ref)
        assert czech.meals[0].ingredients[0].alim_code == 20502  # Haricot bean, boiled/cooked in water
        [english] = day_nutrition(_days([_meal({**beans, "name": "white beans"})]), language="English",
                                  people_count=2, ref=ref)
        assert english.meals[0].ingredients[0].alim_code == 20501  # Haricot bean, dried

    def _write(self, tmp_path: Path, foods: list[str], aliases: list[str]) -> Path:
        (tmp_path / "foods.csv").write_text("\n".join([",".join(FOOD_COLUMNS), *foods]) + "\n", encoding="utf-8")
        (tmp_path / "aliases.csv").write_text("\n".join([",".join(ALIAS_COLUMNS), *aliases]) + "\n",
                                              encoding="utf-8")
        return tmp_path

    GOOD_FOOD = "1,\"Rice, white, raw\",350,1464,7,1,78,,1.2,0.3,,,0,A"

    def test_a_good_table_loads(self, tmp_path: Path) -> None:
        ref = load_reference(self._write(tmp_path, [self.GOOD_FOOD], ["en,rice,1,raw,0,"]))
        hit = ref.lookup("en", " Rice ")
        assert hit is not None and hit[1].name == "Rice, white, raw" and hit[1].polyols is None

    def test_a_decomposed_name_finds_the_composed_alias(self, tmp_path: Path) -> None:
        ref = load_reference(self._write(tmp_path, [self.GOOD_FOOD], ["cs,r\u00fd\u017ee,1,raw,0,"]))
        assert ref.lookup("cs", "ry\u0301z\u030ce") is not None

    @pytest.mark.parametrize(("foods", "aliases"), [
        ([GOOD_FOOD], ["en,rice,2,raw,0,"]),                      # alias points at no food
        ([GOOD_FOOD], ["en,rice,1,raw,0,", "en,rice,1,raw,0,"]),  # duplicate key
        ([GOOD_FOOD], ["en,Rice,1,raw,0,"]),                      # key not normalised
        ([GOOD_FOOD], ["de,rice,1,raw,0,"]),                      # unknown language
        ([GOOD_FOOD], ["en,rice,1,raw,yes,"]),                    # flag not 0/1
        ([GOOD_FOOD.replace(",A", ",E")], []),                     # confidence outside A-D
        ([GOOD_FOOD.replace(",350,", ",,")], []),                 # energy missing
        ([GOOD_FOOD.replace(",350,", ",-5,")], []),               # negative value
        ([GOOD_FOOD.replace(",350,", ",3 50,")], []),             # not a number
        ([GOOD_FOOD.replace(",350,", ",nan,")], []),              # NaN parses as a float
        ([GOOD_FOOD.replace(",350,", ",inf,")], []),              # so does infinity
        ([GOOD_FOOD], ["en,rice,1,raw,0"]),                       # short row (no trailing field)
        ([GOOD_FOOD], ["en,rice,1,raw,0,,extra"]),                # extra field
        ([GOOD_FOOD.rsplit(",", 1)[0]], []),                      # short food row
        ([GOOD_FOOD, GOOD_FOOD], []),                             # duplicate food
    ])
    def test_a_defect_refuses_to_load(self, tmp_path: Path, foods: list[str], aliases: list[str]) -> None:
        with pytest.raises(NutritionDataError):
            load_reference(self._write(tmp_path, foods, aliases))

    def test_a_changed_header_refuses_to_load(self, tmp_path: Path) -> None:
        self._write(tmp_path, [], [])
        (tmp_path / "aliases.csv").write_text("lang,key,alim_code\n", encoding="utf-8")
        with pytest.raises(NutritionDataError):
            load_reference(tmp_path)

    def test_the_data_dir_is_the_backend_data_folder(self) -> None:
        assert DATA_DIR.parts[-2:] == ("data", "nutrition") and (DATA_DIR / "foods.csv").is_file()


# ── The endpoint ───────────────────────────────────────────────────────────────

def _response(*meals: dict[str, object]) -> str:
    return MealPlanResponse.model_validate(
        {"plan_id": None, "days": [{"meals": list(meals)}], "shopping_list": []}
    ).model_dump_json()


async def _plan(session: AsyncSession, user: User, *, request: MealPlanRequest | None = None,
                response: str | None = None, kind: str = "planned") -> MealPlan:
    assert user.household_id is not None
    plan = MealPlan(
        household_id=user.household_id, created_by_user_id=user.id, days=1, meals_per_day=1,
        people_count=2, kind=kind,
        request_json=(request or MealPlanRequest(language="English")).model_dump_json(),
        response_json=response or _response(_meal(RICE, CHICKEN)),
    )
    session.add(plan)
    await session.flush()
    return plan


@pytest.fixture
def synthetic_table() -> Iterator[None]:
    from app.main import app
    app.dependency_overrides[nutrition_reference] = lambda: REF
    yield
    app.dependency_overrides.pop(nutrition_reference, None)


@pytest.mark.usefixtures("synthetic_table")
class TestEndpoint:
    async def test_a_plan_gets_its_figures(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        plan = await _plan(db_session, test_user)
        resp = await client.get(f"/api/plan/{plan.id}/nutrition")
        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["days"][0]["meals"][0]["per_serving"]["kcal"] == pytest.approx(515)
        assert body["source"] == {"name": "Ciqual 2025", "publisher": "Anses",
                                  "published": "2025-11-19", "doi": "10.57745/RDMHWY"}

    async def test_a_draft_works_and_an_edit_shows_on_the_next_read(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        plan = await _plan(db_session, test_user)  # unconfirmed: a draft
        resp = await client.patch(
            f"/api/plan/{plan.id}/days/0/meals/0",
            json={"name": "Rice only", "ingredients": [RICE], "steps": ["Boil"], "total_time_minutes": 20},
        )
        assert resp.status_code == 200
        body = (await client.get(f"/api/plan/{plan.id}/nutrition")).json()
        assert body["days"][0]["meals"][0]["per_serving"]["kcal"] == pytest.approx(350)

    async def test_cook_now_plans_are_unavailable(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        # A Cook Now plan stores a recipe request, not a MealPlanRequest, and
        # records no language: it must not even be parsed as one.
        plan = await _plan(db_session, test_user, kind="cook_now")
        plan.request_json = json.dumps({"meal_type": "hot_dinner", "recipe": {}})
        await db_session.flush()
        body = (await client.get(f"/api/plan/{plan.id}/nutrition")).json()
        assert (body["available"], body["unavailable_reason"]) == (False, "cook_now")

    async def test_an_infant_plan_is_unavailable(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User
    ) -> None:
        plan = await _plan(db_session, test_user,
                           request=MealPlanRequest(language="English", diet_types=[DietType.BABY_FOOD]))
        body = (await client.get(f"/api/plan/{plan.id}/nutrition")).json()
        assert body["unavailable_reason"] == "infant"

    async def test_another_household_gets_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        stranger = User(email="stranger@example.com", normalized_email=normalize_email("stranger@example.com"),
                        hashed_password=get_password_hash(TEST_PASSWORD), email_verified_at=datetime.now(UTC))
        db_session.add(stranger)
        await db_session.flush()
        await db_session.refresh(stranger)
        plan = await _plan(db_session, stranger)
        assert (await client.get(f"/api/plan/{plan.id}/nutrition")).status_code == 404

    @pytest.mark.parametrize(("language", "rice", "chicken"), [
        ("English", "rice", "chicken breast"),
        ("Czech", "rýže", "kuřecí prsa"),  # no name_en: the Czech index
    ])
    async def test_the_shipped_table_counts_a_plain_meal(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
        language: str, rice: str, chicken: str,
    ) -> None:
        # The real Ciqual rows, end to end: raw white rice 9100 (350 kcal) and
        # raw skinless chicken breast 36017 (110 kcal) per 100 g.
        from app.main import app
        app.dependency_overrides.pop(nutrition_reference, None)
        plan = await _plan(
            db_session, test_user, request=MealPlanRequest(language=language),
            response=_response(_meal({**RICE, "name": rice}, {**CHICKEN, "name": chicken})),
        )
        meal = (await client.get(f"/api/plan/{plan.id}/nutrition")).json()["days"][0]["meals"][0]
        assert [i["alim_code"] for i in meal["ingredients"]] == [9100, 36017]
        # (200 g x 350 + 300 g x 110) / 100, split between 2 people.
        assert meal["per_serving"]["kcal"] == pytest.approx(515)
        assert meal["complete"] is True


class TestGaps:
    """app/scripts/nutrition_gaps.py: what the next mapping round works from."""

    @staticmethod
    def _stored(household: int, *ingredients: dict[str, object], language: str = "English",
                basis: int | None = GRAMS_BASIS) -> StoredPlan:
        return StoredPlan(household_id=household,
                          request_json=MealPlanRequest(language=language).model_dump_json(),
                          response_json=_response(_meal(*ingredients, basis=basis)))

    def test_ranks_missing_keys_by_grams_once_enough_households_share_them(self) -> None:
        plans = [
            *(self._stored(h, RICE, {"name": "Quinoa ", "quantity_grams": 80}) for h in range(MIN_HOUSEHOLDS)),
            *(self._stored(h, {"name": "kale", "quantity_grams": 300}) for h in range(MIN_HOUSEHOLDS)),
        ]
        ranked, unreadable = rank_gaps(plans, REF)
        assert [(g.lang, g.key, g.count, g.grams) for g in ranked] == [
            ("en", "kale", 3, 900), ("en", "quinoa", 3, 240),
        ]
        assert unreadable == 0

    def test_a_key_from_fewer_households_stays_on_the_server(self) -> None:
        # One household's free text (and the diet it hints at) is never printed,
        # however often that household used it.
        plans = [self._stored(h, {"name": "lion's mane", "quantity_grams": 200})
                 for h in (1, 1, 1, 2)]
        assert rank_gaps(plans, REF)[0] == []

    def test_skips_water_unstamped_meals_and_other_languages(self) -> None:
        plans = [self._stored(h, {"name": "water", "quantity_grams": 500}) for h in range(3)]
        plans += [self._stored(h, {"name": "kale", "quantity_grams": 300}, basis=None) for h in range(3)]
        plans += [self._stored(h, {"name": "Grünkohl", "quantity_grams": 300}, language="German")
                  for h in range(3)]
        assert rank_gaps(plans, REF)[0] == []

    def test_a_czech_plan_without_name_en_reports_the_czech_key(self) -> None:
        plans = [self._stored(h, {"name": "Kedlubna", "quantity_grams": 150}, language="Czech")
                 for h in range(3)]
        assert [(g.lang, g.key) for g in rank_gaps(plans, REF)[0]] == [("cs", "kedlubna")]

    def test_counts_an_unreadable_plan_instead_of_failing(self) -> None:
        broken = StoredPlan(household_id=1, request_json="{}", response_json="not json")
        assert rank_gaps([broken], REF) == ([], 1)

    def test_a_database_error_exits_with_a_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def unreachable() -> list[StoredPlan]:
            raise OperationalError("SELECT", {}, Exception("connection refused"))

        monkeypatch.setattr(nutrition_gaps, "_stored_plans", unreachable)
        with pytest.raises(SystemExit, match="could not read the stored plans: OperationalError"):
            nutrition_gaps.main([])
