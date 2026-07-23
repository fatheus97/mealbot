"""Admin audit-log writer.

One place that appends an :class:`AdminAuditLog` row, so every admin mutation
records who did what to whom in a consistent shape. Snapshots the actor and
target email at write time so the entry stays meaningful even after either user
is later renamed or hard-deleted (the table is intentionally not FK-linked to
``user`` — see the model docstring).

The write path only; there is no update/delete API for audit rows by design.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import AdminAuditLog, User

logger = logging.getLogger(__name__)


def record_admin_action(
    session: AsyncSession,
    *,
    actor: User,
    action: str,
    target: User | None = None,
    detail: dict[str, str] | None = None,
) -> AdminAuditLog:
    """Append one audit row for ``actor`` performing ``action`` (on ``target``).

    Adds the row to ``session`` and returns it; the caller owns the commit so the
    audit write lands in the same transaction as the mutation it records — either
    both commit or neither does, so the log can't diverge from reality.

    ``action`` is a dotted verb, e.g. ``"user.deactivate"``. ``detail`` is an
    optional string→string map for structured context (a changed field's
    from/to, a reason, …).
    """
    if actor.id is None:
        # An unpersisted actor would write a NULL/garbage actor_user_id — refuse
        # rather than record an unattributable action.
        raise ValueError("audit actor must be a persisted user")

    row = AdminAuditLog(
        actor_user_id=actor.id,
        actor_email=actor.email,
        action=action,
        target_user_id=target.id if target is not None else None,
        target_email=target.email if target is not None else None,
        detail=detail,
    )
    session.add(row)
    logger.info(
        "admin_action actor_id=%s action=%s target_id=%s",
        actor.id,
        action,
        target.id if target is not None else None,
    )
    return row
