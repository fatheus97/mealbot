"""Tests for the admin role (Phase 2): is_admin flag, require_admin gate,
create_user --admin, and UserRead exposure."""

from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

import app.scripts.create_user as create_user_script
from app.api.deps import require_admin
from app.models.db_models import User
from app.models.user_schemas import user_to_read


class TestUserToReadMapper:
    """The shared User->UserRead mapper carries is_admin — login, demo, and
    GET /users all route through it, so this is the single guard against the
    per-response drift that dropped is_admin from the login response."""

    def test_maps_is_admin_true(self) -> None:
        admin = User(id=1, email="a@example.com", hashed_password="h", is_admin=True)
        assert user_to_read(admin).is_admin is True

    def test_maps_is_admin_false(self) -> None:
        plain = User(id=2, email="b@example.com", hashed_password="h", is_admin=False)
        assert user_to_read(plain).is_admin is False


class TestRequireAdmin:
    async def test_rejects_non_admin_with_403(self) -> None:
        user = User(email="plain@example.com", hashed_password="h", is_admin=False)
        with pytest.raises(HTTPException) as exc_info:
            await require_admin(user)
        assert exc_info.value.status_code == 403
        assert "Admin" in exc_info.value.detail

    async def test_allows_admin(self) -> None:
        user = User(email="admin@example.com", hashed_password="h", is_admin=True)
        assert await require_admin(user) is user


class TestIsAdminDefault:
    async def test_new_user_is_not_admin_by_default(
        self, db_session: AsyncSession
    ) -> None:
        user = User(email="default@example.com", hashed_password="h")
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)
        assert user.is_admin is False


class TestCreateUserCli:
    @staticmethod
    def _patch_factory(monkeypatch: pytest.MonkeyPatch, session: AsyncSession) -> None:
        @asynccontextmanager
        async def fake_factory():  # type: ignore[no-untyped-def]
            yield session

        monkeypatch.setattr(create_user_script, "async_session_factory", fake_factory)

    async def test_admin_flag_creates_admin(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_factory(monkeypatch, db_session)
        await create_user_script.create_user(
            "cliadmin@example.com", "AdminPass123", is_admin=True
        )
        user = (
            await db_session.execute(
                select(User).where(User.email == "cliadmin@example.com")
            )
        ).scalars().first()
        assert user is not None
        assert user.is_admin is True

    async def test_defaults_to_non_admin(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_factory(monkeypatch, db_session)
        await create_user_script.create_user("cliplain@example.com", "PlainPass123")
        user = (
            await db_session.execute(
                select(User).where(User.email == "cliplain@example.com")
            )
        ).scalars().first()
        assert user is not None
        assert user.is_admin is False
        assert user.is_comped is False

    async def test_comp_flag_creates_comped_user(
        self, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_factory(monkeypatch, db_session)
        await create_user_script.create_user(
            "clifriend@example.com", "FriendPass123", is_comped=True
        )
        user = (
            await db_session.execute(
                select(User).where(User.email == "clifriend@example.com")
            )
        ).scalars().first()
        assert user is not None
        assert user.is_comped is True
        assert user.is_admin is False


class TestUserReadExposesIsAdmin:
    async def test_profile_reports_is_admin_false_for_regular_user(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        resp = await client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is False

    async def test_profile_reports_is_admin_true_for_admin(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        db_session: AsyncSession,
        test_user: User,
    ) -> None:
        test_user.is_admin = True
        db_session.add(test_user)
        await db_session.flush()

        resp = await client.get("/api/users", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is True
