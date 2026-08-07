"""AdminAuditLog + record_admin_action (admin user management, Slice 2).

The audit log is append-only and intentionally NOT FK-linked to ``user``, so it
outlives the users it describes. These tests pin the write helper's shape and
that decoupling.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.db_models import AdminAuditLog, User
from app.services.admin_audit import record_admin_action


async def _persist_user(db_session: AsyncSession, email: str, **kw: object) -> User:
    u = User(email=email, hashed_password="h", **kw)
    db_session.add(u)
    await db_session.flush()
    return u


class TestRecordAdminAction:
    async def test_records_actor_target_and_detail(self, db_session: AsyncSession) -> None:
        actor = await _persist_user(db_session, "admin@example.com", is_admin=True)
        target = await _persist_user(db_session, "victim@example.com")

        row = record_admin_action(
            db_session,
            actor=actor,
            action="user.deactivate",
            target=target,
            detail={"reason": "spam"},
        )
        await db_session.flush()

        assert row.id is not None
        assert row.actor_user_id == actor.id
        assert row.actor_email == "admin@example.com"
        assert row.action == "user.deactivate"
        assert row.target_user_id == target.id
        assert row.target_email == "victim@example.com"
        assert row.detail == {"reason": "spam"}

    async def test_target_and_detail_are_optional(self, db_session: AsyncSession) -> None:
        actor = await _persist_user(db_session, "admin2@example.com", is_admin=True)
        row = record_admin_action(db_session, actor=actor, action="user.noop")
        await db_session.flush()
        assert row.target_user_id is None
        assert row.target_email is None
        assert row.detail is None

    async def test_row_survives_target_deletion(self, db_session: AsyncSession) -> None:
        # No FK to user, so hard-deleting the target leaves the audit row (and its
        # email snapshot) intact — the whole point of the log.
        actor = await _persist_user(db_session, "admin3@example.com", is_admin=True)
        target = await _persist_user(db_session, "gone@example.com")
        target_id = target.id

        record_admin_action(db_session, actor=actor, action="user.delete", target=target)
        await db_session.flush()

        await db_session.delete(target)
        await db_session.flush()

        rows = (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.target_user_id == target_id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].target_email == "gone@example.com"
        assert await db_session.get(User, target_id) is None

    async def test_rejects_unpersisted_actor(self, db_session: AsyncSession) -> None:
        actor = User(email="nopersist@example.com", hashed_password="h")  # no id yet
        with pytest.raises(ValueError):
            record_admin_action(db_session, actor=actor, action="user.x")
