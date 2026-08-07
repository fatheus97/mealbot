"""POST /api/feedback — the authenticated submit endpoint.

Covers the full intake pipeline from the edge: kill switch, demo guard, the cheap
junk gate, the per-user abuse checks (duplicate / too-many-open), Pydantic body
validation, and that advisory triage is scheduled (only) when enabled.
"""

import base64
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models.db_models import FeedbackReport, User
from app.models.feedback_schemas import MAX_SCREENSHOT_BYTES
from app.services import feedback_triage

_GOOD = {"kind": "bug", "message": "The regenerate button crashes the plan view."}

# Content doesn't need to be a real PNG — the endpoint validates base64-ness,
# content-type whitelist, and decoded size, never magic bytes / image validity.
_SCREENSHOT_B64 = base64.b64encode(b"not a real png but that's fine").decode("ascii")


@pytest.fixture(autouse=True)
def _triage_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default the LLM triage OFF for these endpoint tests so a successful submit
    doesn't schedule a background task that would open a real session / LLM call.
    The scheduling test re-enables it and patches run_triage_bg."""
    monkeypatch.setattr(settings, "feedback_llm_triage_enabled", False)


class TestSubmitSuccess:
    async def test_stores_report_and_returns_ack(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        resp = await client.post("/api/feedback", json=_GOOD)
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "new"
        assert isinstance(body["id"], int)

        rows = (await db_session.execute(select(FeedbackReport))).scalars().all()
        assert len(rows) == 1
        assert rows[0].user_id == test_user.id
        assert rows[0].kind == "bug"
        assert rows[0].message == _GOOD["message"]
        assert rows[0].status == "new"
        assert rows[0].triage_status is None  # triage disabled → not scheduled

    async def test_strips_whitespace(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.post(
            "/api/feedback",
            json={"kind": "feature", "message": "   Please add a dark mode toggle.   "},
        )
        assert resp.status_code == 201
        row = (await db_session.execute(select(FeedbackReport))).scalars().one()
        assert row.message == "Please add a dark mode toggle."


class TestGuards:
    async def test_disabled_returns_503(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "feedback_enabled", False)
        resp = await client.post("/api/feedback", json=_GOOD)
        assert resp.status_code == 503

    async def test_demo_user_forbidden(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession
    ) -> None:
        test_user.is_demo = True
        db_session.add(test_user)
        await db_session.flush()
        resp = await client.post("/api/feedback", json=_GOOD)
        assert resp.status_code == 403


class TestCheapGate:
    async def test_too_short_rejected_422(self, client: AsyncClient) -> None:
        resp = await client.post("/api/feedback", json={"kind": "bug", "message": "bug"})
        assert resp.status_code == 422
        assert "at least" in resp.json()["detail"]

    async def test_no_letters_rejected_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/feedback", json={"kind": "bug", "message": "1234567890 !!!"}
        )
        assert resp.status_code == 422
        assert "words" in resp.json()["detail"]

    async def test_mash_rejected_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/feedback", json={"kind": "bug", "message": "aaaaaaaaaaaa"}
        )
        assert resp.status_code == 422


class TestBodyValidation:
    async def test_bad_kind_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/feedback", json={"kind": "rant", "message": "This is a valid body."}
        )
        assert resp.status_code == 422

    async def test_message_too_long_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/feedback", json={"kind": "bug", "message": "x" * 5000}
        )
        assert resp.status_code == 422


class TestScreenshotAttachment:
    async def test_stores_valid_screenshot(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.post(
            "/api/feedback",
            json={
                **_GOOD,
                "screenshot_base64": _SCREENSHOT_B64,
                "screenshot_content_type": "image/png",
            },
        )
        assert resp.status_code == 201
        row = (await db_session.execute(select(FeedbackReport))).scalars().one()
        assert row.screenshot_base64 == _SCREENSHOT_B64
        assert row.screenshot_content_type == "image/png"

    async def test_submit_without_screenshot_leaves_columns_null(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        resp = await client.post("/api/feedback", json=_GOOD)
        assert resp.status_code == 201
        row = (await db_session.execute(select(FeedbackReport))).scalars().one()
        assert row.screenshot_base64 is None
        assert row.screenshot_content_type is None

    async def test_content_type_without_data_rejected_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/feedback", json={**_GOOD, "screenshot_content_type": "image/png"}
        )
        assert resp.status_code == 422

    async def test_data_without_content_type_rejected_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/feedback", json={**_GOOD, "screenshot_base64": _SCREENSHOT_B64}
        )
        assert resp.status_code == 422

    async def test_disallowed_content_type_rejected_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/feedback",
            json={
                **_GOOD,
                "screenshot_base64": _SCREENSHOT_B64,
                "screenshot_content_type": "image/svg+xml",
            },
        )
        assert resp.status_code == 422

    async def test_malformed_base64_rejected_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/feedback",
            json={
                **_GOOD,
                "screenshot_base64": "not valid base64!!!",
                "screenshot_content_type": "image/png",
            },
        )
        assert resp.status_code == 422

    async def test_oversized_screenshot_rejected_422(self, client: AsyncClient) -> None:
        oversized = base64.b64encode(b"x" * (MAX_SCREENSHOT_BYTES + 1)).decode("ascii")
        resp = await client.post(
            "/api/feedback",
            json={
                **_GOOD,
                "screenshot_base64": oversized,
                "screenshot_content_type": "image/png",
            },
        )
        assert resp.status_code == 422

    async def test_at_size_limit_accepted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        at_limit = base64.b64encode(b"x" * MAX_SCREENSHOT_BYTES).decode("ascii")
        resp = await client.post(
            "/api/feedback",
            json={
                **_GOOD,
                "screenshot_base64": at_limit,
                "screenshot_content_type": "image/jpeg",
            },
        )
        assert resp.status_code == 201


class TestAbuseChecks:
    async def test_duplicate_returns_409(self, client: AsyncClient) -> None:
        first = await client.post("/api/feedback", json=_GOOD)
        assert first.status_code == 201
        second = await client.post("/api/feedback", json=_GOOD)
        assert second.status_code == 409

    async def test_too_many_open_returns_429(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "feedback_max_open_per_user", 1)
        first = await client.post(
            "/api/feedback", json={"kind": "bug", "message": "First distinct report body."}
        )
        assert first.status_code == 201
        # A DIFFERENT (non-duplicate) body, but the user is already at the open cap.
        second = await client.post(
            "/api/feedback", json={"kind": "bug", "message": "Second distinct report body."}
        )
        assert second.status_code == 429


class TestTriageScheduling:
    async def test_schedules_triage_when_enabled(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "feedback_llm_triage_enabled", True)
        bg = AsyncMock()
        monkeypatch.setattr(feedback_triage, "run_triage_bg", bg)

        resp = await client.post("/api/feedback", json=_GOOD)
        assert resp.status_code == 201
        report_id = resp.json()["id"]

        # The row is marked pending up front (observable even independent of the task).
        row = (await db_session.execute(select(FeedbackReport))).scalars().one()
        assert row.triage_status == "pending"
        # And the background task was scheduled with this report's id.
        bg.assert_awaited_once_with(report_id)
