"""User feedback intake API — the public (authenticated) submit endpoint.

A logged-in, non-demo user posts a bug report / feature request. The request is
gated cheaply (junk rejected at the edge), throttled per user (route rate limit +
open-report cap + near-dup), stored, and — behind the triage kill switch — handed to
an ADVISORY background LLM triage. The moderation queue + any money/ticket action
live on the admin side; this endpoint never does either.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.error_copy import ErrorKey
from app.core.errors import LocalizedHTTPException
from app.core.feedback_gate import (
    MESSAGE_MIN_LEN,
    FeedbackRejectReason,
    evaluate_feedback,
)
from app.core.rate_limit import limiter, user_id_key_func
from app.db import get_session
from app.models.db_models import FeedbackReport, User
from app.models.feedback_schemas import FeedbackCreate, FeedbackSubmitResponse
from app.services import feedback_intake, feedback_triage
from app.services.feedback_intake import FeedbackAbuse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Friendly, specific 422 copy per cheap-gate reject reason (the raw enum value never
# reaches the user).
#: The gate's reason, mapped to copy rather than carrying the sentence itself.
#: `min_len` is passed for every one of them and used by only one — `substitute`
#: ignores values a template does not name, which keeps the raise site from
#: having to know which reason it is about to report.
_REJECT_KEYS: dict[FeedbackRejectReason, ErrorKey] = {
    FeedbackRejectReason.TOO_SHORT: "feedback_too_short",
    FeedbackRejectReason.NO_LETTERS: "feedback_no_letters",
    FeedbackRejectReason.LOW_VARIETY: "feedback_low_variety",
}


@router.post("", response_model=FeedbackSubmitResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour", key_func=user_id_key_func)
async def submit_feedback(
    request: Request,
    background_tasks: BackgroundTasks,
    body: FeedbackCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FeedbackSubmitResponse:
    """Accept a bug report / feature request from a logged-in user.

    Pipeline: kill switch → demo guard → cheap junk gate (422) → per-user abuse
    checks (409 duplicate / 429 too-many-open) → store → schedule advisory triage.
    The per-user route rate limit (5/hour) is the hard throttle; the abuse checks are
    the softer queue-flood / double-submit guards on top of it.
    """
    if not settings.feedback_enabled:
        raise LocalizedHTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "feedback_disabled",
        )
    if current_user.is_demo:
        raise LocalizedHTTPException(status.HTTP_403_FORBIDDEN, "feedback_demo_blocked")
    assert current_user.id is not None  # get_current_user only returns persisted users

    gate = evaluate_feedback(body.message)
    if not gate.ok:
        assert gate.reason is not None  # ok=False always carries a reason
        raise LocalizedHTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            _REJECT_KEYS[gate.reason],
            min_len=str(MESSAGE_MIN_LEN),
        )

    abuse = await feedback_intake.check_abuse(
        session, user_id=current_user.id, message=body.message
    )
    if not abuse.ok:
        if abuse.reason is FeedbackAbuse.DUPLICATE:
            raise LocalizedHTTPException(status.HTTP_409_CONFLICT, "feedback_duplicate")
        raise LocalizedHTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "feedback_too_many_open"
        )

    schedule_triage = settings.feedback_llm_triage_enabled
    report = FeedbackReport(
        user_id=current_user.id,
        kind=body.kind,
        message=body.message,
        page=body.page,
        screenshot_base64=body.screenshot_base64,
        screenshot_content_type=body.screenshot_content_type,
        status="new",
        # Mark "pending" up front so the queue shows triage is coming even before the
        # background task lands; the task flips it to done/failed.
        triage_status="pending" if schedule_triage else None,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    assert report.id is not None  # populated by the commit above

    # Advisory triage runs AFTER the response (own session, best-effort) so LLM
    # latency/failure never touches the user's submit. Only scheduled when enabled.
    if schedule_triage:
        background_tasks.add_task(feedback_triage.run_triage_bg, report.id)

    logger.info(
        "feedback_submitted report_id=%s user_id=%s kind=%s",
        report.id, current_user.id, body.kind,
    )
    return FeedbackSubmitResponse(id=report.id, status=report.status)
