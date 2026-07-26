"""Public access-request intake (unauthenticated).

The landing page's "Request access" form posts here while registration is
closed. Admin-side triage lives in ``api/admin.py``.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.db import get_session
from app.models.access_request_schemas import AccessRequestCreate
from app.models.user_schemas import MessageResponse
from app.services.access_request import (
    SubmitOutcome,
    notify_operator,
    submit_access_request,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/access-requests", tags=["access-requests"])

# Identical wording for every outcome — new request, duplicate of a pending
# one, or an address that already has an account. See services/access_request
# rule 2: this endpoint must not become an account-existence oracle.
_NEUTRAL_ACK = "Thanks — we've got your request and will be in touch by email."


@router.post("", status_code=201, response_model=MessageResponse)
@limiter.limit("5/minute")
async def create_access_request(
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    """Queue a request for access.

    Rate-limited per IP at the same 5/min as registration. Body is parsed
    manually (like ``register_user``) so the limiter decorator can see the
    raw ``Request``.
    """
    try:
        payload = await request.json()
    except ValueError as exc:
        # Malformed JSON on an unauthenticated endpoint must be a 422, not an
        # uncaught JSONDecodeError surfacing as a 500 with a traceback.
        raise RequestValidationError(
            [{"type": "json_invalid", "loc": ("body",), "msg": "Invalid JSON body", "input": None}]
        ) from exc
    try:
        body = AccessRequestCreate.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    try:
        outcome = await submit_access_request(session, email=body.email, message=body.message)
        await session.commit()
    except IntegrityError:
        # Lost the race to the partial unique index — a concurrent submit for
        # this address landed first. Same observable outcome as the service's
        # pre-check path: neutral ack, no alert.
        await session.rollback()
        outcome = SubmitOutcome(None, queue_was_empty=False)

    # Alert ONLY on the empty→non-empty transition, never per request — see
    # notify_operator's docstring: per-request alerts would let an anonymous
    # caller drain the Resend quota that password-reset mail shares.
    if outcome.stored is not None and outcome.queue_was_empty:
        background_tasks.add_task(notify_operator, body.email, body.message)

    return MessageResponse(message=_NEUTRAL_ACK)
