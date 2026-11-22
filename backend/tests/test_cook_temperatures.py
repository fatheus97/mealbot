"""POST /api/plan/cook-temperatures (docs/food-storage-design.md, slice 7):
ingredients go through the nutrition resolver, then map.csv, then rules.csv;
the names the resolver never finds go through cook_keys.csv, a Czech one on a
Czech recipe before the resolver."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.nutrition_reference import load_reference
from app.core.security import get_password_hash
from app.core.storage_reference import (
    COOK_KEY_COLUMNS,
    MAP_COLUMNS,
    RULE_COLUMNS,
    load_storage,
    storage_reference,
)
from app.models.db_models import MealEntry, MealPlan, User
from app.models.plan_models import IngredientAmount, MealPlanRequest
from app.services import nutrition
from app.services.nutrition import _Language, recipe_key
from tests.conftest import TEST_PASSWORD

URL = "/api/plan/cook-temperatures"
REF = load_reference()


def _ing(name: str, name_en: str | None = None, *, grams: float = 200, spice: bool = False) -> dict[str, object]:
    return {"name": name, "name_en": name_en, "quantity_grams": grams, "is_spice": spice}


async def _lines(
    client: AsyncClient, *ings: dict[str, object], entry: int | None = None,
) -> list[dict[str, object]]:
    resp = await client.post(URL, json={"ingredients": list(ings), "meal_entry_id": entry})
    assert resp.status_code == 200, resp.text
    lines: list[dict[str, object]] = resp.json()["lines"]
    return lines


async def _speak(session: AsyncSession, user: User, language: str) -> None:
    user.language = language
    await session.flush()


async def _meal(session: AsyncSession, owner: User, *, language: str, kind: str = "planned") -> int:
    """A stored meal in owner's kitchen, from a plan written in `language`."""
    assert owner.id is not None and owner.household_id is not None
    plan = MealPlan(
        household_id=owner.household_id, created_by_user_id=owner.id, days=1, meals_per_day=1,
        people_count=2, kind=kind, request_json=MealPlanRequest(language=language).model_dump_json(),
        response_json="{}",
    )
    session.add(plan)
    await session.flush()
    assert plan.id is not None
    entry = MealEntry(
        household_id=owner.household_id, meal_plan_id=plan.id, day_index=0, meal_index=0,
        name="Chicken", meal_type="lunch", meal_json="{}",
    )
    session.add(entry)
    await session.flush()
    assert entry.id is not None
    return entry.id


KILL = {"core_c": 75, "hold_c": 70, "hold_min": 2, "us_only": False}


class TestShippedTable:
    async def test_an_english_dish_gets_one_line_per_category_in_file_order(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        await _speak(db_session, test_user, "English")
        lines = await _lines(
            client, _ing("eggs", grams=100), _ing("chicken breasts"), _ing("ground beef"), _ing("chicken thigh"),
        )
        assert [line["category"] for line in lines] == ["poultry", "minced", "egg"]
        assert all({k: line[k] for k in KILL} == KILL for line in lines)
        assert [line["sources"] for line in lines] == [["szu", "fsa", "efsa"], ["szu", "fsa"], ["szu", "fsa"]]

    async def test_fish_is_us_guidance_with_no_hold(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        await _speak(db_session, test_user, "English")
        assert await _lines(client, _ing("salmon fillet")) == [{
            "category": "fish", "core_c": 63, "hold_c": None, "hold_min": None, "us_only": True, "sources": ["usda"],
        }]

    async def test_whole_cuts_cooked_food_and_vegetables_give_no_line(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        await _speak(db_session, test_user, "English")
        assert await _lines(
            client, _ing("beef steak"), _ing("cooked chicken breast"), _ing("carrot"), _ing("unknown thing"),
        ) == []

    async def test_a_czech_name_matches_without_name_en(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        await _speak(db_session, test_user, "Czech")
        lines = await _lines(client, _ing("kuřecí prsa"), _ing("grilovaná kuřecí prsa"))
        assert [line["category"] for line in lines] == ["poultry"]
        # The Czech name decides: name_en saying "chicken breast" on a cooked
        # Czech name does not add a cook line the nutrition panel would not see.
        assert await _lines(client, _ing("grilovaná kuřecí prsa", "chicken breast")) == []

    async def test_another_language_matches_only_through_name_en(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        await _speak(db_session, test_user, "Slovak")
        assert [line["category"] for line in await _lines(client, _ing("kuracie prsia", "chicken breast"))] == [
            "poultry"
        ]
        assert await _lines(client, _ing("kuracie prsia")) == []

    async def test_a_planned_meal_matches_in_its_plans_language(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        # A Czech member cooks an English plan: English plans carry no
        # name_en, and the Czech index does not know "chicken breast".
        await _speak(db_session, test_user, "Czech")
        entry = await _meal(db_session, test_user, language="English")
        assert await _lines(client, _ing("chicken breast")) == []
        assert [line["category"] for line in await _lines(client, _ing("chicken breast"), entry=entry)] == [
            "poultry"
        ]

    async def test_a_cook_now_plan_uses_the_users_language(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        await _speak(db_session, test_user, "Czech")
        entry = await _meal(db_session, test_user, language="English", kind="cook_now")
        assert [line["category"] for line in await _lines(client, _ing("kuřecí prsa"), entry=entry)] == [
            "poultry"
        ]

    async def test_a_legacy_language_reads_as_english_like_generation(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        await _speak(db_session, test_user, "cs")
        assert [line["category"] for line in await _lines(client, _ing("chicken breast"))] == ["poultry"]

    async def test_a_meal_outside_the_kitchen_is_not_found(
        self, client: AsyncClient, db_session: AsyncSession,
    ) -> None:
        stranger = User(
            email="stranger@example.com", normalized_email="stranger@example.com",
            hashed_password=get_password_hash(TEST_PASSWORD),
        )
        db_session.add(stranger)
        await db_session.flush()
        await db_session.refresh(stranger)  # the insert trigger gives it a household of its own
        theirs = await _meal(db_session, stranger, language="English")
        resp = await client.post(URL, json={"ingredients": [_ing("egg")], "meal_entry_id": theirs})
        assert resp.status_code == 404
        resp = await client.post(URL, json={"ingredients": [_ing("egg")], "meal_entry_id": theirs + 1000})
        assert resp.status_code == 404

    async def test_a_whole_bird_or_a_bone_in_piece_gets_its_line(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        # Nutrition counts none of these (its waste gate), so cook_keys.csv
        # carries them, read in the singular like the nutrition index.
        await _speak(db_session, test_user, "English")
        for name in (
            "whole chicken", "Whole Chickens", "chicken thighs (bone-in, skin-on)", "bone-in, skin-on chicken thighs",
            "whole duck",
        ):
            assert [line["category"] for line in await _lines(client, _ing(name))] == ["poultry"], name
        assert [line["category"] for line in await _lines(client, _ing("whole fish"))] == ["fish"]
        assert await _lines(client, _ing("beef bones")) == []  # not a cook key: bones go into stock

    async def test_a_czech_whole_bird_matches_with_or_without_name_en(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User,
    ) -> None:
        await _speak(db_session, test_user, "Czech")
        # A generated Czech line always carries name_en, and it can drop the
        # bone: the Czech name decides, as it does for nutrition.
        for ing in (
            _ing("celé kuře"), _ing("celé kuře", "whole chicken"), _ing("celé kuře", "chicken"),
            _ing("Celá kachna", "duck"), _ing("kuřecí stehna s kostí a kůží", "chicken thighs with bone and skin"),
        ):
            assert [line["category"] for line in await _lines(client, ing)] == ["poultry"], ing
        # Another language reaches the list through name_en only.
        await _speak(db_session, test_user, "Slovak")
        assert [line["category"] for line in await _lines(client, _ing("celé kura", "whole chicken"))] == [
            "poultry"
        ]
        assert await _lines(client, _ing("celé kuře")) == []
        assert await _lines(client, _ing("celé kuře", "chicken")) == []  # the Czech list is for Czech plans

    async def test_an_empty_dish_gives_no_line(self, client: AsyncClient) -> None:
        assert await _lines(client) == []


class TestRequest:
    async def test_more_than_forty_ingredients_is_refused(self, client: AsyncClient) -> None:
        resp = await client.post(URL, json={"ingredients": [_ing(f"item {i}") for i in range(41)]})
        assert resp.status_code == 422

    async def test_a_zero_amount_is_refused_like_any_ingredient(self, client: AsyncClient) -> None:
        resp = await client.post(URL, json={"ingredients": [_ing("egg", grams=0)]})
        assert resp.status_code == 422

    async def test_needs_a_session(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(URL, json={"ingredients": [_ing("egg")]})
        assert resp.status_code == 401


@pytest.fixture
def odd_figures(tmp_path: Path) -> Iterator[None]:
    """A table whose numbers no source prints, so a line can only carry them
    if the endpoint passes rules.csv through untouched."""
    rows = [
        "poultry,81,77,3,0,fsa,https://example.org/a,quote 81 77 3,2026-11-22,verified,",
        "poultry,81,77,3,0,szu,https://example.org/b,quote 81 77 3,2026-11-22,verified,",
        "fish,59,,,1,usda,https://example.org/c,quote 59,2026-11-22,sourced,",
        "whole_cut,,,,0,fsa,https://example.org/d,a quote with no number,2026-11-22,verified,",
    ]
    foods = ["36017,,,poultry,curated,", "26036,,,fish,curated,", "6111,,,whole_cut,curated,"]
    (tmp_path / "rules.csv").write_text("\n".join([",".join(RULE_COLUMNS), *rows]) + "\n", encoding="utf-8")
    (tmp_path / "map.csv").write_text("\n".join([",".join(MAP_COLUMNS), *foods]) + "\n", encoding="utf-8")
    keys = [",".join(COOK_KEY_COLUMNS), "en,whole duck,poultry"]
    (tmp_path / "cook_keys.csv").write_text("\n".join(keys) + "\n", encoding="utf-8")
    table = load_storage(tmp_path)
    from app.main import app
    app.dependency_overrides[storage_reference] = lambda: table
    yield
    app.dependency_overrides.pop(storage_reference, None)


@pytest.mark.usefixtures("odd_figures")
async def test_every_number_comes_from_the_table(
    client: AsyncClient, db_session: AsyncSession, test_user: User,
) -> None:
    await _speak(db_session, test_user, "English")
    lines = await _lines(client, _ing("salmon fillet"), _ing("beef steak"), _ing("chicken breast"))
    assert await _lines(client, _ing("whole duck")) == lines[:1]
    assert await _lines(client, _ing("whole chicken")) == []  # the shipped cook_keys.csv is not read
    assert lines == [
        {"category": "poultry", "core_c": 81, "hold_c": 77, "hold_min": 3, "us_only": False, "sources": ["fsa", "szu"]},
        {"category": "fish", "core_c": 59, "hold_c": None, "hold_min": None, "us_only": True, "sources": ["usda"]},
    ]


class TestOneResolver:
    """recipe_key keys an ingredient exactly as the nutrition figures do."""

    @pytest.mark.parametrize(("language", "ing"), [
        ("English", IngredientAmount(name="chicken breasts", quantity_grams=200)),
        ("English", IngredientAmount(name="potatoes", quantity_grams=200)),
        ("Czech", IngredientAmount(name="vařené bílé fazole", name_en="white beans", quantity_grams=200)),
        ("Czech", IngredientAmount(name="paprika", name_en="paprika", quantity_grams=1, is_spice=True)),
        ("Czech", IngredientAmount(name="něco neznámého", name_en="chicken breast", quantity_grams=200)),
        ("Slovak", IngredientAmount(name="kuracie prsia", quantity_grams=200)),
    ])
    def test_recipe_key_agrees_with_the_nutrition_row(self, language: str, ing: IngredientAmount) -> None:
        row = nutrition._ingredient(ing, servings=2, lang=_Language.of(language), ref=REF)
        key = recipe_key(ing, language, REF)
        hit = REF.lookup(*key) if key is not None else None
        expected = row.off_id or (str(row.alim_code) if row.alim_code is not None else None)
        assert (hit[1].id if hit is not None else None) == expected
