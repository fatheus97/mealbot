"""Admin feedback moderation endpoints: list / detail / moderate / retriage / accept.

Covers the require_admin gate, the queue projection (preview + advisory triage), the
moderation status transitions + audit trail, that "accepted" is refused at the PATCH
schema layer (it's the money-moving 6b action, done via the dedicated /accept endpoint),
on-demand retriage, and the Accept (credit + ticket) orchestration.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models.db_models import AdminAuditLog, FeedbackReport, User
from app.models.feedback_schemas import FeedbackTriage


async def _make_admin(db_session: AsyncSession, test_user: User) -> None:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()


async def _add_report(
    db_session: AsyncSession,
    user_id: int,
    *,
    kind: str = "bug",
    message: str = "Something is broken in the plan view.",
    status: str = "new",
    triage_json: str | None = None,
    triage_status: str | None = None,
    triage_type: str | None = None,
) -> FeedbackReport:
    report = FeedbackReport(
        user_id=user_id,
        kind=kind,
        message=message,
        status=status,
        triage_json=triage_json,
        triage_status=triage_status,
        triage_type=triage_type,
    )
    db_session.add(report)
    await db_session.flush()
    return report


def _triage_json() -> str:
    return FeedbackTriage(
        is_actionable=True,
        type="bug",
        severity="high",
        title="Plan view crash",
        summary="The plan view crashes on regenerate.",
        repro="Open a plan, click regenerate twice.",
        dedupe_hint="plan crash",
    ).model_dump_json()


class TestRequireAdminGate:
    async def test_list_non_admin_403(self, client: AsyncClient, test_user: User) -> None:
        assert (await client.get("/api/admin/feedback")).status_code == 403

    async def test_detail_non_admin_403(self, client: AsyncClient, test_user: User) -> None:
        assert (await client.get("/api/admin/feedback/1")).status_code == 403

    async def test_patch_non_admin_403(self, client: AsyncClient, test_user: User) -> None:
        resp = await client.patch("/api/admin/feedback/1", json={"status": "reviewing"})
        assert resp.status_code == 403

    async def test_retriage_non_admin_403(self, client: AsyncClient, test_user: User) -> None:
        assert (await client.post("/api/admin/feedback/1/retriage")).status_code == 403


class TestList:
    async def test_lists_newest_first_with_preview_and_triage(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        await _add_report(db_session, test_user.id, message="oldest")
        await _add_report(db_session, test_user.id, message="middle")
        newest = await _add_report(
            db_session,
            test_user.id,
            message="newest",
            triage_status="done",
            triage_type="bug",
            triage_json=_triage_json(),
        )

        resp = await client.get("/api/admin/feedback")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["items"][0]["id"] == newest.id
        assert body["items"][0]["preview"] == "newest"
        assert body["items"][0]["user_email"] == test_user.email
        assert body["items"][0]["triage_type"] == "bug"  # from denormalized column

    async def test_status_filter(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        await _add_report(db_session, test_user.id, status="new")
        await _add_report(db_session, test_user.id, status="spam")
        resp = await client.get("/api/admin/feedback?status=spam")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["status"] == "spam"

    async def test_preview_is_truncated(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        await _add_report(db_session, test_user.id, message="x" * 300)
        resp = await client.get("/api/admin/feedback")
        assert len(resp.json()["items"][0]["preview"]) == 140


class TestDetail:
    async def test_detail_parses_triage(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(
            db_session,
            test_user.id,
            message="Full verbatim body here.",
            triage_status="done",
            triage_json=_triage_json(),
        )
        resp = await client.get(f"/api/admin/feedback/{report.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "Full verbatim body here."
        assert body["user_email"] == test_user.email
        assert body["triage"]["title"] == "Plan view crash"
        assert body["triage"]["repro"]

    async def test_detail_triage_none_when_absent(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        resp = await client.get(f"/api/admin/feedback/{report.id}")
        assert resp.status_code == 200
        assert resp.json()["triage"] is None

    async def test_detail_bad_triage_json_is_none_not_500(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(
            db_session, test_user.id, triage_status="done", triage_json="{not valid json"
        )
        resp = await client.get(f"/api/admin/feedback/{report.id}")
        assert resp.status_code == 200
        assert resp.json()["triage"] is None

    async def test_detail_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert (await client.get("/api/admin/feedback/999999")).status_code == 404


class TestModerate:
    async def test_transition_sets_reviewer_and_audits(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)

        resp = await client.patch(
            f"/api/admin/feedback/{report.id}", json={"status": "reviewing"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "reviewing"
        assert body["reviewed_by_admin_id"] == test_user.id
        assert body["reviewed_at"] is not None

        audits = (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "feedback.review")
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].detail == {
            "feedback_id": str(report.id),
            "from": "new",
            "to": "reviewing",
        }

    async def test_idempotent_no_audit_on_same_status(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id, status="spam")
        resp = await client.patch(
            f"/api/admin/feedback/{report.id}", json={"status": "spam"}
        )
        assert resp.status_code == 200
        audits = (await db_session.execute(select(AdminAuditLog))).scalars().all()
        assert audits == []

    async def test_accepted_status_rejected_at_schema(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # "accepted" is the money-moving 6b action — not a valid 6a moderation status.
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        resp = await client.patch(
            f"/api/admin/feedback/{report.id}", json={"status": "accepted"}
        )
        assert resp.status_code == 422

    async def test_moderate_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.patch("/api/admin/feedback/999999", json={"status": "spam"})
        assert resp.status_code == 404


class TestRetriage:
    async def test_retriage_populates_triage(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id, triage_status="failed")

        triage = FeedbackTriage(
            is_actionable=True,
            type="feature",
            severity="low",
            title="Dark mode",
            summary="User wants a dark mode.",
            repro=None,
            dedupe_hint="dark mode",
        )
        with patch("app.services.feedback_triage.llm_client") as mock_llm:
            mock_llm.chat_json = AsyncMock(return_value=triage)
            resp = await client.post(f"/api/admin/feedback/{report.id}/retriage")

        assert resp.status_code == 200
        body = resp.json()
        assert body["triage_status"] == "done"
        assert body["triage"]["type"] == "feature"

        # Retriage is a mutation (rewrites triage_* + costs an LLM call) → audited.
        audits = (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "feedback.retriage")
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].actor_user_id == test_user.id
        assert audits[0].detail == {"feedback_id": str(report.id)}

    async def test_retriage_llm_failure_is_200_and_marks_failed(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # The retriage endpoint exists to recover from a failed auto-triage, so its
        # own LLM-failure path must be graceful: the request succeeds (200) and the
        # report is marked "failed" (not a 500) so the admin can retry again.
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id, triage_status="failed")
        with patch("app.services.feedback_triage.llm_client") as mock_llm:
            mock_llm.chat_json = AsyncMock(side_effect=RuntimeError("provider down"))
            resp = await client.post(f"/api/admin/feedback/{report.id}/retriage")
        assert resp.status_code == 200
        assert resp.json()["triage_status"] == "failed"

    async def test_retriage_disabled_503(
        self,
        client: AsyncClient,
        test_user: User,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        monkeypatch.setattr(settings, "feedback_llm_triage_enabled", False)
        resp = await client.post(f"/api/admin/feedback/{report.id}/retriage")
        assert resp.status_code == 503

    async def test_retriage_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.post("/api/admin/feedback/999999/retriage")
        assert resp.status_code == 404


async def _feedback_accept_audits(db_session: AsyncSession) -> list[AdminAuditLog]:
    return list(
        (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "feedback.accept")
            )
        ).scalars().all()
    )


class TestAccept:
    async def test_non_admin_403(self, client: AsyncClient, test_user: User) -> None:
        assert (await client.post("/api/admin/feedback/1/accept")).status_code == 403

    async def test_accept_new_report_sets_status_and_audits(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        with (
            patch("app.api.admin.feedback_credit.maybe_grant_credit", AsyncMock(return_value=False)),
            patch("app.api.admin.feedback_ticket.ticket_configured", return_value=False),
        ):
            resp = await client.post(f"/api/admin/feedback/{report.id}/accept")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["reviewed_by_admin_id"] == test_user.id
        assert body["reviewed_at"] is not None
        assert body["credit_cents"] is None
        audits = await _feedback_accept_audits(db_session)
        assert len(audits) == 1
        assert audits[0].detail == {"feedback_id": str(report.id), "credited": "False"}

    async def test_accept_grants_credit_and_records_it(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)

        async def _grant(session, r, reporter):
            r.credit_cents = 100
            r.credit_granted_at = datetime.now(UTC)
            return True

        with (
            patch("app.api.admin.feedback_credit.maybe_grant_credit", _grant),
            patch("app.api.admin.feedback_ticket.ticket_configured", return_value=False),
        ):
            resp = await client.post(f"/api/admin/feedback/{report.id}/accept")
        assert resp.status_code == 200
        assert resp.json()["credit_cents"] == 100
        audits = await _feedback_accept_audits(db_session)
        assert audits[0].detail is not None
        assert audits[0].detail["credited"] == "True"

    async def test_accept_creates_ticket_when_configured(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        with (
            patch("app.api.admin.feedback_credit.maybe_grant_credit", AsyncMock(return_value=False)),
            patch("app.api.admin.feedback_ticket.ticket_configured", return_value=True),
            patch(
                "app.api.admin.feedback_ticket.create_issue_for_report",
                AsyncMock(return_value="https://github.com/owner/tickets/issues/3"),
            ),
        ):
            resp = await client.post(f"/api/admin/feedback/{report.id}/accept")
        assert resp.status_code == 200
        assert resp.json()["ticket_url"] == "https://github.com/owner/tickets/issues/3"

    async def test_accept_rejected_report_409(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id, status="rejected")
        resp = await client.post(f"/api/admin/feedback/{report.id}/accept")
        assert resp.status_code == 409

    async def test_accept_is_idempotent_no_double_audit_but_retries_credit(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # Re-accepting an already-accepted report: no new audit, but the credit is
        # re-attempted (idempotency-keyed in the service, so never a double credit).
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id, status="accepted")
        grant = AsyncMock(return_value=False)
        with (
            patch("app.api.admin.feedback_credit.maybe_grant_credit", grant),
            patch("app.api.admin.feedback_ticket.ticket_configured", return_value=False),
        ):
            resp = await client.post(f"/api/admin/feedback/{report.id}/accept")
        assert resp.status_code == 200
        assert await _feedback_accept_audits(db_session) == []  # no audit on re-accept
        grant.assert_awaited_once()  # credit retried

    async def test_accept_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.post("/api/admin/feedback/999999/accept")
        assert resp.status_code == 404

    async def test_retry_accept_that_grants_credit_is_audited(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # A re-accept (status already "accepted") that GRANTS a credit the first Accept
        # missed must still be audited (money moved), with credited reflecting THIS call.
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id, status="accepted")

        async def _grant(session, r, reporter):
            r.credit_cents = 100
            r.credit_granted_at = datetime.now(UTC)
            return True

        with (
            patch("app.api.admin.feedback_credit.maybe_grant_credit", _grant),
            patch("app.api.admin.feedback_ticket.ticket_configured", return_value=False),
        ):
            resp = await client.post(f"/api/admin/feedback/{report.id}/accept")
        assert resp.status_code == 200
        audits = await _feedback_accept_audits(db_session)
        assert len(audits) == 1
        assert audits[0].detail is not None
        assert audits[0].detail["credited"] == "True"

    async def test_accept_emails_reporter_on_credit(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # When Accept actually grants a credit, the reporter is emailed (best-effort).
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)

        async def _grant(session, r, reporter):
            r.credit_cents = 100
            r.credit_granted_at = datetime.now(UTC)
            return True

        notify = AsyncMock()
        with (
            patch("app.api.admin.feedback_credit.maybe_grant_credit", _grant),
            patch("app.api.admin.feedback_ticket.ticket_configured", return_value=False),
            patch("app.api.admin.feedback_notify.notify_credit_granted", notify),
        ):
            resp = await client.post(f"/api/admin/feedback/{report.id}/accept")
        assert resp.status_code == 200
        notify.assert_awaited_once()
        assert notify.await_args is not None
        reporter_arg, cents_arg = notify.await_args.args
        assert reporter_arg.id == test_user.id
        assert cents_arg == 100

    async def test_accept_no_email_when_no_credit(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        # No credit granted (ineligible/disabled) → no email.
        await _make_admin(db_session, test_user)
        assert test_user.id is not None
        report = await _add_report(db_session, test_user.id)
        notify = AsyncMock()
        with (
            patch("app.api.admin.feedback_credit.maybe_grant_credit", AsyncMock(return_value=False)),
            patch("app.api.admin.feedback_ticket.ticket_configured", return_value=False),
            patch("app.api.admin.feedback_notify.notify_credit_granted", notify),
        ):
            resp = await client.post(f"/api/admin/feedback/{report.id}/accept")
        assert resp.status_code == 200
        notify.assert_not_awaited()
