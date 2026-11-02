"""The policy-change notice email: who gets it, at most once, inside the quota.

Resend is mocked (``send_transactional``); the background run is pointed at the
test session the same way test_password_reset does it, so its commits land in
the rolled-back test transaction instead of a real connection.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import Enum
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.core.email_copy import COPY
from app.core.email_normalize import normalize_email
from app.core.legal import CHANGE_SUMMARY, MATERIAL_CHANGE_VERSION
from app.core.security import get_password_hash
from app.models.db_models import AdminAuditLog, EmailCampaignSend, User
from app.scripts import send_policy_notice as cli
from app.services import policy_notice
from tests.conftest import TEST_PASSWORD

CAMPAIGN = f"policy-{MATERIAL_CHANGE_VERSION}"


@pytest.fixture
def mail(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> AsyncMock:
    """Capture outbound mail, configure Resend, drop the pacing, and bind the
    run's own session to the test transaction."""
    mock = AsyncMock(return_value="sent")
    monkeypatch.setattr(policy_notice, "send_campaign_email", mock)
    monkeypatch.setattr(policy_notice, "transactional_configured", lambda: True)
    monkeypatch.setattr(policy_notice, "PACE_SECONDS", 0.0)

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        yield db_session  # the db_session fixture owns its lifecycle

    monkeypatch.setattr(policy_notice, "session_factory", _factory)
    monkeypatch.setattr(cli, "async_session_factory", _factory)
    return mock


class _Default(Enum):
    NOW = "now"  # "verified just now", so None can still mean unverified


async def _user(
    db_session: AsyncSession,
    email: str,
    *,
    email_verified_at: datetime | None | Literal[_Default.NOW] = _Default.NOW,
    terms_version: str | None = None,
    is_active: bool = True,
    is_demo: bool = False,
    language: str = "English",
) -> User:
    user = User(
        email=email,
        normalized_email=normalize_email(email),
        hashed_password=get_password_hash(TEST_PASSWORD),
        email_verified_at=(
            datetime.now(UTC) if email_verified_at is _Default.NOW else email_verified_at
        ),
        terms_version=terms_version,
        is_active=is_active,
        is_demo=is_demo,
        language=language,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def _rows(db_session: AsyncSession) -> list[EmailCampaignSend]:
    return list(
        (await db_session.execute(select(EmailCampaignSend))).scalars().all()
    )


def _recipients(mail: AsyncMock) -> list[str]:
    return [call.args[0] for call in mail.await_args_list]


class TestPreview:
    async def test_counts_every_kind_of_account(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        await _user(db_session, "due@example.com")
        await _user(db_session, "agreed@example.com", terms_version=MATERIAL_CHANGE_VERSION)
        await _user(db_session, "unverified@example.com", email_verified_at=None)
        await _user(db_session, "inactive@example.com", is_active=False)
        await _user(db_session, "demo@example.com", is_demo=True)
        sent = await _user(db_session, "sent@example.com")
        lost = await _user(db_session, "lost@example.com")
        assert sent.id is not None and lost.id is not None
        db_session.add(
            EmailCampaignSend(campaign=CAMPAIGN, user_id=sent.id, sent_at=datetime.now(UTC))
        )
        db_session.add(EmailCampaignSend(campaign=CAMPAIGN, user_id=lost.id))
        # A row for an OLDER campaign does not count as sent for this one.
        db_session.add(EmailCampaignSend(campaign="policy-2026-01-01", user_id=lost.id))
        await db_session.flush()

        result = await policy_notice.preview(db_session)

        assert result.campaign == CAMPAIGN
        assert result.counts.model_dump() == {
            "eligible": 1,
            "sent": 1,
            "unconfirmed": 1,
            "accepted_in_app": 1,
            "excluded": 2,  # unverified + inactive; demo is not counted at all
        }
        assert result.daily_limit == settings.campaign_daily_send_limit
        assert result.email_configured is True
        mail.assert_not_awaited()

    async def test_renders_each_locale_with_its_own_links(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        previews = {p.locale: p for p in (await policy_notice.preview(db_session)).previews}
        assert set(previews) == {"en", "cs"}

        en, cs = previews["en"], previews["cs"]
        assert en.subject == COPY["en"]["policy_notice_subject"]
        assert cs.subject == COPY["cs"]["policy_notice_subject"]
        assert f'href="{settings.frontend_base_url}/privacy"' in en.html
        assert f'href="{settings.frontend_base_url}/terms"' in en.html
        assert f'href="{settings.frontend_base_url}/cs/privacy"' in cs.html
        assert f'href="{settings.frontend_base_url}/cs/terms"' in cs.html
        # Escaped on the way in (the summary has an apostrophe in English).
        assert CHANGE_SUMMARY["cs"] in cs.html
        assert "Google&#x27;s" in en.html
        assert "$" not in en.html + cs.html  # every placeholder substituted

    async def test_writes_nothing(self, db_session: AsyncSession, mail: AsyncMock) -> None:
        await _user(db_session, "due@example.com")
        await policy_notice.preview(db_session)
        assert await _rows(db_session) == []


class TestCheckSend:
    async def test_refuses_a_changed_count(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        await _user(db_session, "a@example.com")
        with pytest.raises(policy_notice.SendRefused, match="changed from 2 to 1"):
            await policy_notice.check_send(db_session, 2)

    async def test_refuses_when_nobody_is_eligible(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        with pytest.raises(policy_notice.SendRefused, match="Nobody"):
            await policy_notice.check_send(db_session, 1)

    async def test_refuses_without_resend(
        self, db_session: AsyncSession, mail: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _user(db_session, "a@example.com")
        monkeypatch.setattr(policy_notice, "transactional_configured", lambda: False)
        with pytest.raises(policy_notice.SendRefused, match="RESEND_API_KEY"):
            await policy_notice.check_send(db_session, 1)

    async def test_caps_at_the_daily_quota(
        self, db_session: AsyncSession, mail: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first = await _user(db_session, "a@example.com")
        await _user(db_session, "b@example.com")
        monkeypatch.setattr(settings, "campaign_daily_send_limit", 1)

        assert await policy_notice.check_send(db_session, 2) == [first.id]

    async def test_refuses_when_the_quota_is_spent(
        self, db_session: AsyncSession, mail: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _user(db_session, "a@example.com")
        other = await _user(db_session, "b@example.com")
        assert other.id is not None
        # Any campaign's claim in the last 24h uses quota.
        db_session.add(EmailCampaignSend(campaign="policy-2026-01-01", user_id=other.id))
        await db_session.flush()
        monkeypatch.setattr(settings, "campaign_daily_send_limit", 1)

        with pytest.raises(policy_notice.SendRefused, match="quota"):
            await policy_notice.check_send(db_session, 2)


class TestRunSend:
    async def test_sends_in_each_users_locale_and_records_it(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        en = await _user(db_session, "en@example.com")
        cs = await _user(db_session, "cs@example.com", language="Czech")

        ids = await policy_notice.check_send(db_session, 2)
        result = await policy_notice.run_send(ids)

        assert result.model_dump() == {"sent": 2, "failed": 0, "unconfirmed": 0, "skipped": 0}
        subjects = {call.args[0]: call.args[1] for call in mail.await_args_list}
        assert subjects == {
            en.email: COPY["en"]["policy_notice_subject"],
            cs.email: COPY["cs"]["policy_notice_subject"],
        }
        rows = await _rows(db_session)
        assert {r.user_id for r in rows} == {en.id, cs.id}
        assert all(r.campaign == CAMPAIGN and r.sent_at is not None for r in rows)

    async def test_a_rerun_never_sends_twice(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        await _user(db_session, "a@example.com")
        ids = await policy_notice.check_send(db_session, 1)
        await policy_notice.run_send(ids)

        # The same ids again (a double-clicked button, the CLI racing the admin
        # tab): every claim already exists, so nothing goes out.
        again = await policy_notice.run_send(ids)
        assert again.model_dump() == {"sent": 0, "failed": 0, "unconfirmed": 0, "skipped": 1}
        # (The address is a literal: the losing claim's rollback expires `user`.
        # That rollback also unwinds this harness's savepoints, so the DB state
        # after it says nothing; the mail mock is the evidence.)
        assert _recipients(mail) == ["a@example.com"]

    async def test_a_rejected_send_releases_its_claim(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        await _user(db_session, "a@example.com")
        mail.return_value = "rejected"
        ids = await policy_notice.check_send(db_session, 1)

        result = await policy_notice.run_send(ids)
        assert result.failed == 1
        assert await _rows(db_session) == []

        # ...so the next run retries the same user.
        mail.return_value = "sent"
        retry = await policy_notice.run_send(await policy_notice.check_send(db_session, 1))
        assert retry.sent == 1

    async def test_a_maybe_delivered_send_keeps_its_claim(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        # A timeout or 5xx can arrive after Resend accepted the mail. Releasing
        # the claim would let the next run send a second copy.
        user = await _user(db_session, "a@example.com")
        user_id = user.id
        mail.return_value = "unknown"
        result = await policy_notice.run_send(await policy_notice.check_send(db_session, 1))

        assert result.unconfirmed == 1
        rows = await _rows(db_session)
        assert [(r.user_id, r.sent_at) for r in rows] == [(user_id, None)]
        assert (await policy_notice.preview(db_session)).counts.unconfirmed == 1
        with pytest.raises(policy_notice.SendRefused, match="Nobody"):
            await policy_notice.check_send(db_session, 1)

    async def test_a_lost_confirmation_does_not_stop_the_run(
        self, db_session: AsyncSession, mail: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Resend took the first mail but recording sent_at failed. That user is
        # unconfirmed (true, never retried) and the run goes on to the next one.
        await _user(db_session, "a@example.com")
        await _user(db_session, "b@example.com")
        ids = await policy_notice.check_send(db_session, 2)

        real_commit = db_session.commit
        calls = 0

        async def _commit() -> None:
            nonlocal calls
            calls += 1
            if calls == 2:  # 1 = first claim, 2 = its sent_at
                raise RuntimeError("database blip")
            await real_commit()

        monkeypatch.setattr(db_session, "commit", _commit)
        # The fake failure never touched the real transaction, so there is
        # nothing to roll back (and this harness's rollback would unwind setup).
        monkeypatch.setattr(db_session, "rollback", AsyncMock())

        result = await policy_notice.run_send(ids)
        assert result.model_dump() == {"sent": 1, "failed": 0, "unconfirmed": 1, "skipped": 0}
        assert mail.await_count == 2

    async def test_sends_an_idempotency_key_per_campaign_and_user(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        user = await _user(db_session, "a@example.com")
        user_id = user.id
        await policy_notice.run_send(await policy_notice.check_send(db_session, 1))
        assert mail.await_args is not None
        assert mail.await_args.kwargs["idempotency_key"] == f"{CAMPAIGN}/{user_id}"

    async def test_a_failure_before_sending_releases_the_claim(
        self, db_session: AsyncSession, mail: AsyncMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Nothing went out, so the user must not be stranded as "unconfirmed".
        await _user(db_session, "a@example.com")
        ids = await policy_notice.check_send(db_session, 1)

        def _boom(locale: object) -> object:
            raise RuntimeError("render failed")

        monkeypatch.setattr(policy_notice, "render_notice", _boom)
        result = await policy_notice.run_send(ids)

        assert result.sent == 0
        mail.assert_not_awaited()
        assert await _rows(db_session) == []

    async def test_skips_who_accepted_in_the_app_meanwhile(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        user = await _user(db_session, "a@example.com")
        ids = await policy_notice.check_send(db_session, 1)
        user.terms_version = MATERIAL_CHANGE_VERSION
        await db_session.flush()

        result = await policy_notice.run_send(ids)
        assert result.skipped == 1
        mail.assert_not_awaited()
        assert await _rows(db_session) == []

    async def test_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        @asynccontextmanager
        async def _broken() -> AsyncIterator[AsyncSession]:
            raise RuntimeError("database is down")
            yield  # pragma: no cover

        monkeypatch.setattr(policy_notice, "session_factory", _broken)
        assert (await policy_notice.run_send([1])).sent == 0


class TestAdminEndpoints:
    async def _admin(self, db_session: AsyncSession, test_user: User) -> None:
        test_user.is_admin = True
        await db_session.flush()

    async def test_non_admin_is_403(self, client: AsyncClient, mail: AsyncMock) -> None:
        assert (await client.get("/api/admin/policy-notice")).status_code == 403
        resp = await client.post(
            "/api/admin/policy-notice/send", json={"confirm_recipients": 1}
        )
        assert resp.status_code == 403
        mail.assert_not_awaited()

    async def test_preview(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        await self._admin(db_session, test_user)
        resp = await client.get("/api/admin/policy-notice")
        assert resp.status_code == 200
        body = resp.json()
        # The admin's own account is a real, verified account with no record.
        assert body["counts"]["eligible"] == 1
        assert len(body["previews"]) == 2

    async def test_wrong_count_is_409_and_sends_nothing(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        await self._admin(db_session, test_user)
        resp = await client.post(
            "/api/admin/policy-notice/send", json={"confirm_recipients": 5}
        )
        assert resp.status_code == 409
        assert "Review the preview" in resp.json()["detail"]
        mail.assert_not_awaited()

    async def test_send_queues_audits_and_mails(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        await self._admin(db_session, test_user)
        other = await _user(db_session, "other@example.com")

        resp = await client.post(
            "/api/admin/policy-notice/send", json={"confirm_recipients": 2}
        )
        assert resp.status_code == 202
        assert resp.json() == {"campaign": CAMPAIGN, "queued": 2}
        # Starlette runs background tasks before the ASGI call returns.
        assert sorted(_recipients(mail)) == sorted([test_user.email, other.email])

        audit = (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "policy_notice.send")
            )
        ).scalars().all()
        assert len(audit) == 1
        assert audit[0].detail == {"campaign": CAMPAIGN, "queued": "2"}

    @pytest.mark.parametrize("count", [0, -1])
    async def test_confirmation_must_be_positive(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession, count: int
    ) -> None:
        await self._admin(db_session, test_user)
        resp = await client.post(
            "/api/admin/policy-notice/send", json={"confirm_recipients": count}
        )
        assert resp.status_code == 422


class TestCli:
    async def test_dry_run_prints_the_confirm_command(
        self, db_session: AsyncSession, mail: AsyncMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        await _user(db_session, "a@example.com")
        await cli.dry_run()
        out = capsys.readouterr().out
        assert "--send --confirm 1" in out
        assert COPY["cs"]["policy_notice_subject"] in out
        mail.assert_not_awaited()

    async def test_send_refused_exits_1(
        self, db_session: AsyncSession, mail: AsyncMock
    ) -> None:
        await _user(db_session, "a@example.com")
        assert await cli.send(3) == 1
        mail.assert_not_awaited()

    async def test_send_exits_0(self, db_session: AsyncSession, mail: AsyncMock) -> None:
        user = await _user(db_session, "a@example.com")
        assert await cli.send(1) == 0
        assert _recipients(mail) == [user.email]
