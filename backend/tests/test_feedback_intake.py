"""DB-backed feedback abuse checks: the per-user open-report cap and near-dup guard.

These are keyed to the user (not IP), so the tests assert they count only the right
user's OPEN reports and match a resubmission modulo case/whitespace within the window.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash
from app.models.db_models import FeedbackReport, User
from app.services.feedback_intake import FeedbackAbuse, check_abuse

_NOW = datetime(2026, 7, 24, 12, 0, 0)  # naive UTC, matches the stored column frame


async def _add_report(
    session: AsyncSession,
    *,
    user_id: int,
    message: str,
    status: str = "new",
    created_at: datetime | None = None,
) -> FeedbackReport:
    report = FeedbackReport(
        user_id=user_id,
        kind="bug",
        message=message,
        status=status,
        created_at=created_at or _NOW,
    )
    session.add(report)
    await session.flush()
    return report


async def _make_user(session: AsyncSession, email: str) -> User:
    user = User(email=email, hashed_password=get_password_hash("x"))
    session.add(user)
    await session.flush()
    assert user.id is not None
    return user


class TestOpenReportCap:
    async def test_ok_when_under_cap(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.id is not None
        result = await check_abuse(
            db_session, user_id=test_user.id, message="A brand new report.", now=_NOW
        )
        assert result.ok

    async def test_blocks_at_cap(
        self, db_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "feedback_max_open_per_user", 2)
        assert test_user.id is not None
        await _add_report(db_session, user_id=test_user.id, message="first open report")
        await _add_report(db_session, user_id=test_user.id, message="second open report")
        result = await check_abuse(
            db_session, user_id=test_user.id, message="one too many please", now=_NOW
        )
        assert not result.ok
        assert result.reason is FeedbackAbuse.TOO_MANY_OPEN

    async def test_closed_reports_do_not_count(
        self, db_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # cap=2, but rejected/spam/accepted don't occupy the queue — only the one
        # "new" is open, so a new submission is under the cap.
        monkeypatch.setattr(settings, "feedback_max_open_per_user", 2)
        assert test_user.id is not None
        await _add_report(db_session, user_id=test_user.id, message="an open one", status="new")
        await _add_report(db_session, user_id=test_user.id, message="a rejected one", status="rejected")
        await _add_report(db_session, user_id=test_user.id, message="a spam one", status="spam")
        await _add_report(db_session, user_id=test_user.id, message="an accepted one", status="accepted")
        result = await check_abuse(
            db_session, user_id=test_user.id, message="still allowed to send", now=_NOW
        )
        assert result.ok


class TestNearDuplicate:
    async def test_duplicate_modulo_case_and_whitespace(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        assert test_user.id is not None
        await _add_report(db_session, user_id=test_user.id, message="Login is broken")
        result = await check_abuse(
            db_session, user_id=test_user.id, message="  login   IS broken  ", now=_NOW
        )
        assert not result.ok
        assert result.reason is FeedbackAbuse.DUPLICATE

    async def test_not_duplicate_outside_window(
        self, db_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "feedback_dedup_window_hours", 24)
        assert test_user.id is not None
        await _add_report(
            db_session,
            user_id=test_user.id,
            message="Login is broken",
            created_at=_NOW - timedelta(hours=48),  # older than the 24h window
        )
        result = await check_abuse(
            db_session, user_id=test_user.id, message="Login is broken", now=_NOW
        )
        assert result.ok

    async def test_only_same_user_dedupes(
        self, db_session: AsyncSession, test_user: User
    ) -> None:
        other = await _make_user(db_session, "other@example.com")
        assert other.id is not None and test_user.id is not None
        # Another user reported the same thing — must NOT block this user.
        await _add_report(db_session, user_id=other.id, message="Login is broken")
        result = await check_abuse(
            db_session, user_id=test_user.id, message="Login is broken", now=_NOW
        )
        assert result.ok


async def test_now_defaults_to_real_clock(
    db_session: AsyncSession, test_user: User
) -> None:
    # Smoke: omitting `now` uses the real clock and still returns a clean result —
    # and a report just added "now" dedupes against a submission of the same text.
    assert test_user.id is not None
    await _add_report(
        db_session,
        user_id=test_user.id,
        message="A fresh, unique report body.",
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    result = await check_abuse(
        db_session, user_id=test_user.id, message="A fresh, unique report body."
    )
    assert not result.ok
    assert result.reason is FeedbackAbuse.DUPLICATE
