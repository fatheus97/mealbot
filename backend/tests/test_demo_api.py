"""Tests for POST /api/auth/demo — ephemeral user creation and expiry cleanup."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.cookies import ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME
from app.models.db_models import StockItem, User


class TestPublicConfig:
    async def test_config_reports_demo_mode_true(self, unauthed_client: AsyncClient) -> None:
        with (
            patch("app.core.config.settings.demo_mode", True),
            patch("app.core.config.settings.registration_enabled", False),
        ):
            resp = await unauthed_client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json() == {"demo_mode": True, "registration_enabled": False}

    async def test_config_reports_demo_mode_false(self, unauthed_client: AsyncClient) -> None:
        with (
            patch("app.core.config.settings.demo_mode", False),
            patch("app.core.config.settings.registration_enabled", False),
        ):
            resp = await unauthed_client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json() == {"demo_mode": False, "registration_enabled": False}

    async def test_config_reports_registration_enabled(
        self, unauthed_client: AsyncClient
    ) -> None:
        # Frontend gates the Register UI on this — a value change here is a
        # user-visible behavior change, so the shape is locked in tests.
        with (
            patch("app.core.config.settings.demo_mode", False),
            patch("app.core.config.settings.registration_enabled", True),
        ):
            resp = await unauthed_client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json() == {"demo_mode": False, "registration_enabled": True}


class TestCountriesEndpoint:
    async def test_countries_returns_sorted_canonical_list(
        self, unauthed_client: AsyncClient
    ) -> None:
        # Unauthenticated — the country list is public, same trust level as
        # /api/config. The frontend picker fetches this on mount so the
        # picker can never offer a value PATCH will reject.
        from app.core.country_whitelist import SUPPORTED_COUNTRIES

        resp = await unauthed_client.get("/api/countries")
        assert resp.status_code == 200
        body = resp.json()
        countries = body["countries"]
        assert isinstance(countries, list)
        # Must contain every canonical entry — the set is the source of truth.
        assert set(countries) == SUPPORTED_COUNTRIES
        # Sorted for deterministic UI rendering / caching.
        assert countries == sorted(countries)


class TestLanguagesEndpoint:
    async def test_languages_returns_sorted_canonical_list(
        self, unauthed_client: AsyncClient
    ) -> None:
        from app.core.language_whitelist import SUPPORTED_LANGUAGES

        resp = await unauthed_client.get("/api/languages")
        assert resp.status_code == 200
        body = resp.json()
        languages = body["languages"]
        assert isinstance(languages, list)
        assert set(languages) == SUPPORTED_LANGUAGES
        assert languages == sorted(languages)


class TestDemoSession:
    async def test_happy_path_creates_user_and_seeds_fridge(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch("app.core.config.settings.demo_mode", True):
            resp = await unauthed_client.post("/api/auth/demo")
        assert resp.status_code == 200
        body = resp.json()
        # Cookies set, not access_token in body.
        assert ACCESS_COOKIE_NAME in unauthed_client.cookies
        assert REFRESH_COOKIE_NAME in unauthed_client.cookies
        assert body["is_demo"] is True
        assert body["email"].startswith("demo+")

        result = await db_session.execute(select(User).where(User.is_demo == True))  # noqa: E712
        users = result.scalars().all()
        assert len(users) == 1

        stock = await db_session.execute(
            select(StockItem).where(StockItem.user_id == users[0].id)
        )
        assert len(stock.scalars().all()) > 0

    async def test_each_session_creates_distinct_user(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch("app.core.config.settings.demo_mode", True):
            r1 = await unauthed_client.post("/api/auth/demo")
            r2 = await unauthed_client.post("/api/auth/demo")
        assert r1.json()["email"] != r2.json()["email"]
        assert r1.json()["id"] != r2.json()["id"]

    async def test_demo_mode_disabled_returns_404(self, unauthed_client: AsyncClient) -> None:
        with patch("app.core.config.settings.demo_mode", False):
            resp = await unauthed_client.post("/api/auth/demo")
        assert resp.status_code == 404

    # Demo session refresh-row expiry is asserted in
    # tests/test_auth_api.py::TestDemoSession::test_demo_session_capped_at_demo_session_expire,
    # which goes through the cookie-aware AsyncClient. No duplicate here.

    async def test_expired_demo_users_cleaned_up_on_next_session(
        self, unauthed_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        with patch("app.core.config.settings.demo_mode", True):
            await unauthed_client.post("/api/auth/demo")

        # Back-date the existing demo user so it looks expired
        result = await db_session.execute(select(User).where(User.is_demo == True))  # noqa: E712
        old_user = result.scalars().first()
        assert old_user is not None
        old_id = old_user.id
        old_user.created_at = datetime.now(UTC) - timedelta(hours=3)
        db_session.add(old_user)
        await db_session.commit()

        # Next session call should sweep the old user and create a fresh one
        with patch("app.core.config.settings.demo_mode", True):
            resp = await unauthed_client.post("/api/auth/demo")
        assert resp.status_code == 200

        result2 = await db_session.execute(select(User).where(User.is_demo == True))  # noqa: E712
        remaining = result2.scalars().all()
        assert len(remaining) == 1
        assert remaining[0].id != old_id
