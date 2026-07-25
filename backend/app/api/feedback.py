"""User feedback intake API — the public (authenticated) submit endpoint.

A logged-in, non-demo user posts a bug report / feature request. The request is
gated cheaply (junk rejected at the edge), throttled per user (route rate limit +
open-report cap + near-dup), stored, and — behind the triage kill switch — handed to
an ADVISORY background LLM triage. The moderation queue + any money/ticket action
live on the admin side; this endpoint never does either.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
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
_REJECT_MESSAGES: dict[FeedbackRejectReason, str] = {
    FeedbackRejectReason.TOO_SHORT: (
        f"Please add a little more detail (at least {MESSAGE_MIN_LEN} characters)."
    ),
    FeedbackRejectReason.NO_LETTERS: "Please describe the issue in words.",
    FeedbackRejectReason.LOW_VARIETY: (
        "That doesn't look like a real report — please describe the issue."
    ),
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback is not being accepted right now.",
        )
    if current_user.is_demo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo accounts can't submit feedback. Please create an account.",
        )
    assert current_user.id is not None  # get_current_user only returns persisted users

    gate = evaluate_feedback(body.message)
    if not gate.ok:
        assert gate.reason is not None  # ok=False always carries a reason
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=_REJECT_MESSAGES[gate.reason],
        )

    abuse = await feedback_intake.check_abuse(
        session, user_id=current_user.id, message=body.message
    )
    if not abuse.ok:
        if abuse.reason is FeedbackAbuse.DUPLICATE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You've already sent this — thanks, we have it.",
            )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You have several open reports already. Please wait for those "
            "to be reviewed before sending more.",
        )

    schedule_triage = settings.feedback_llm_triage_enabled
    report = FeedbackReport(
        user_id=current_user.id,
        kind=body.kind,
        message=body.message,
        page=body.page,
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
