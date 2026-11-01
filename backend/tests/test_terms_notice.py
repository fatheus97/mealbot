"""The in-app notice of a material change to the Terms / Privacy Policy.

Two halves: the profile tells the SPA when to show TermsUpdateBanner
(``UserRead.terms_update``), and ``POST /users/terms/accept`` records the click.
The record follows register_user's rule: server clock, server version, nothing
from the client except the version it SHOWED, which is only compared.
"""
from datetime import UTC, date, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import UI_LOCALES
from app.core.legal import (
    CHANGE_SUMMARY,
    MATERIAL_CHANGE_VERSION,
    TERMS_VERSION,
    terms_notice_due,
)
from app.models.db_models import User


def _naive(ts: datetime) -> datetime:
    return ts.replace(tzinfo=None) if ts.tzinfo else ts


class TestTermsNoticeDue:
    @pytest.mark.parametrize(
        ("recorded", "due"),
        [
            pytest.param(None, True, id="never-recorded"),
            pytest.param("2026-01-01", True, id="older"),
            pytest.param(MATERIAL_CHANGE_VERSION, False, id="same"),
            pytest.param("2999-01-01", False, id="newer"),
            pytest.param("July 2026", True, id="garbage"),
        ],
    )
    def test_due(self, recorded: str | None, due: bool) -> None:
        assert terms_notice_due(recorded) is due

    def test_material_version_is_published(self) -> None:
        # The notice names a version users can read. One newer than the
        # published pages would ask them to accept a text that does not exist.
        assert date.fromisoformat(MATERIAL_CHANGE_VERSION) <= date.fromisoformat(TERMS_VERSION)

    def test_summary_covers_every_locale(self) -> None:
        assert set(CHANGE_SUMMARY) == set(UI_LOCALES)
        assert all(text.strip() for text in CHANGE_SUMMARY.values())


class TestProfileCarriesTheNotice:
    async def test_shown_when_never_recorded(self, client: AsyncClient) -> None:
        # The conftest user has terms_version NULL, like every pre-checkbox and
        # operator-created account: there is no record they saw any version.
        resp = await client.get("/api/users")
        assert resp.status_code == 200
        notice = resp.json()["terms_update"]
        assert notice["version"] == MATERIAL_CHANGE_VERSION
        assert notice["summary"] == CHANGE_SUMMARY

    async def test_hidden_once_accepted(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.terms_version = TERMS_VERSION
        await db_session.flush()
        resp = await client.get("/api/users")
        assert resp.json()["terms_update"] is None

    async def test_hidden_for_demo(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.is_demo = True
        await db_session.flush()
        resp = await client.get("/api/users")
        assert resp.json()["terms_update"] is None


class TestAccept:
    async def test_stamps_server_clock_and_version(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        resp = await client.post(
            "/api/users/terms/accept",
            # The extra fields are the forgery attempt: they must be ignored.
            json={
                "version": MATERIAL_CHANGE_VERSION,
                "terms_version": "1999-01-01",
                "terms_accepted_at": "1999-01-01T00:00:00",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["terms_update"] is None

        await db_session.refresh(test_user)
        assert test_user.terms_version == TERMS_VERSION
        assert test_user.terms_accepted_at is not None
        now = datetime.now(UTC).replace(tzinfo=None)
        assert abs(_naive(test_user.terms_accepted_at) - now) < timedelta(minutes=1)

    async def test_stale_version_is_409_and_records_nothing(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # A tab opened before a deploy shows the previous change's summary; its
        # click must not be filed as agreement to the current text.
        resp = await client.post("/api/users/terms/accept", json={"version": "2026-01-01"})
        assert resp.status_code == 409
        assert "changed again" in resp.json()["detail"]
        await db_session.refresh(test_user)
        assert test_user.terms_version is None
        assert test_user.terms_accepted_at is None

    async def test_second_click_keeps_the_first_timestamp(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        first = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)
        test_user.terms_version = TERMS_VERSION
        test_user.terms_accepted_at = first
        await db_session.flush()

        resp = await client.post(
            "/api/users/terms/accept", json={"version": MATERIAL_CHANGE_VERSION}
        )
        assert resp.status_code == 200
        await db_session.refresh(test_user)
        assert test_user.terms_accepted_at is not None
        assert _naive(test_user.terms_accepted_at) == _naive(first)

    async def test_demo_records_nothing(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.is_demo = True
        await db_session.flush()
        resp = await client.post(
            "/api/users/terms/accept", json={"version": MATERIAL_CHANGE_VERSION}
        )
        assert resp.status_code == 200
        await db_session.refresh(test_user)
        assert test_user.terms_version is None

    async def test_requires_a_version(self, client: AsyncClient) -> None:
        resp = await client.post("/api/users/terms/accept", json={})
        assert resp.status_code == 422

    async def test_requires_login(self, unauthed_client: AsyncClient) -> None:
        resp = await unauthed_client.post(
            "/api/users/terms/accept", json={"version": MATERIAL_CHANGE_VERSION}
        )
        assert resp.status_code == 401
