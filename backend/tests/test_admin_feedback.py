"""Admin feedback moderation endpoints: list / detail / moderate / retriage.

Covers the require_admin gate, the queue projection (preview + advisory triage), the
moderation status transitions + audit trail, that "accepted" is refused at the schema
layer (it's the money-moving 6b action), and on-demand retriage.
"""

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
