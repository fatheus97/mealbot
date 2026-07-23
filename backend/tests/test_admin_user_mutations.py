"""Admin user-management mutations (Slice 3): create / PATCH flags /
reset-onboarding / force-logout. Covers the require_admin gate, the guards
(self-sabotage, demo, not-found, no-op), the deactivate side-effect
(session revocation + token_version bump), and that every mutation is audited.
"""
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.security import get_password_hash
from app.models.db_models import AdminAuditLog, AuthSession, User


async def _make_admin(db_session: AsyncSession, test_user: User) -> None:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()


async def _seed(db_session: AsyncSession, email: str, **kw: object) -> User:
    u = User(email=email, hashed_password=get_password_hash("Whatever123"), **kw)  # type: ignore[arg-type]
    db_session.add(u)
    await db_session.flush()
    return u


async def _live_session(db_session: AsyncSession, user_id: int, tag: str) -> AuthSession:
    s = AuthSession(
        user_id=user_id,
        refresh_token_hash=(tag * 64)[:64],
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db_session.add(s)
    await db_session.flush()
    return s


async def _actions_for(db_session: AsyncSession, target_id: int) -> list[str]:
    rows = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.target_user_id == target_id)
        )
    ).scalars().all()
    return [r.action for r in rows]


class TestCreateUser:
    async def test_non_admin_gets_403(self, client: AsyncClient, test_user: User) -> None:
        resp = await client.post(
            "/api/admin/users", json={"email": "x@example.com", "password": "GoodPass123"}
        )
        assert resp.status_code == 403

    async def test_creates_user_hashes_password_and_audits_without_password(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.post(
            "/api/admin/users",
            json={"email": "new@example.com", "password": "NewPass123", "is_admin": True},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["email"] == "new@example.com"
        assert body["is_admin"] is True
        assert "hashed_password" not in body

        created = (
            await db_session.execute(select(User).where(User.email == "new@example.com"))
        ).scalars().first()
        assert created is not None
        assert created.hashed_password != "NewPass123"  # stored hashed

        rows = (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.target_user_id == created.id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].action == "user.create"
        assert rows[0].actor_user_id == test_user.id
        # The password must never reach the audit log.
        assert "NewPass123" not in str(rows[0].detail)

    async def test_duplicate_email_409(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "dup@example.com")
        resp = await client.post(
            "/api/admin/users", json={"email": "dup@example.com", "password": "GoodPass123"}
        )
        assert resp.status_code == 409

    async def test_weak_password_422(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.post(
            "/api/admin/users", json={"email": "weak@example.com", "password": "alllowercase"}
        )
        assert resp.status_code == 422


class TestUpdateUserFlags:
    async def test_deactivate_revokes_sessions_and_bumps_token_version(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed(db_session, "target@example.com")
        sess = await _live_session(db_session, target.id, "a")  # type: ignore[arg-type]
        old_tv = target.token_version

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        await db_session.refresh(target)
        await db_session.refresh(sess)
        assert target.token_version == old_tv + 1  # in-flight access tokens die
        assert sess.revoked_at is not None  # refresh sessions revoked
        assert _has(await _actions_for(db_session, target.id), "user.deactivate")  # type: ignore[arg-type]

    async def test_reactivate_audits_without_touching_sessions(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed(db_session, "react@example.com", is_active=False)
        sess = await _live_session(db_session, target.id, "c")  # type: ignore[arg-type]
        old_tv = target.token_version

        resp = await client.patch(f"/api/admin/users/{target.id}", json={"is_active": True})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True
        await db_session.refresh(target)
        await db_session.refresh(sess)
        assert target.token_version == old_tv  # reactivate doesn't bump
        assert sess.revoked_at is None  # reactivate must NOT revoke sessions
        assert _has(await _actions_for(db_session, target.id), "user.reactivate")  # type: ignore[arg-type]

    async def test_grant_and_revoke_admin_and_comp_audit(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed(db_session, "flags@example.com")

        r1 = await client.patch(f"/api/admin/users/{target.id}", json={"is_admin": True, "is_comped": True})
        assert r1.status_code == 200
        assert r1.json()["is_admin"] is True and r1.json()["is_comped"] is True
        actions = await _actions_for(db_session, target.id)  # type: ignore[arg-type]
        assert "user.grant_admin" in actions and "user.grant_comp" in actions

        r2 = await client.patch(f"/api/admin/users/{target.id}", json={"is_admin": False, "is_comped": False})
        assert r2.status_code == 200
        actions = await _actions_for(db_session, target.id)  # type: ignore[arg-type]
        assert "user.revoke_admin" in actions and "user.revoke_comp" in actions

    async def test_noop_returns_400(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed(db_session, "noop@example.com")
        # Empty body → all None → nothing changes.
        assert (await client.patch(f"/api/admin/users/{target.id}", json={})).status_code == 400
        # A value equal to the current one is also a no-op (target is not admin).
        assert (
            await client.patch(f"/api/admin/users/{target.id}", json={"is_admin": False})
        ).status_code == 400

    async def test_not_found_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        assert (
            await client.patch("/api/admin/users/999999", json={"is_active": False})
        ).status_code == 404

    async def test_demo_user_cannot_be_modified(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        demo = await _seed(db_session, "demo@example.com", is_demo=True)
        assert (
            await client.patch(f"/api/admin/users/{demo.id}", json={"is_admin": True})
        ).status_code == 400


class TestLastAdminInvariant:
    """The atomic 'never leave zero active admins' guard. When the sole active
    admin is the target, the count guard rejects with 'last active admin' — the
    same guard that (via the FOR UPDATE lock) closes the concurrent write-skew.
    (The concurrent race itself isn't reproducible in the single-connection test
    harness, same as the with_for_update in password_reset.)"""

    async def test_sole_admin_cannot_disable_self(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.patch(f"/api/admin/users/{test_user.id}", json={"is_active": False})
        assert resp.status_code == 409
        assert "last active admin" in resp.json()["detail"].lower()

    async def test_sole_admin_cannot_revoke_own_admin(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.patch(f"/api/admin/users/{test_user.id}", json={"is_admin": False})
        assert resp.status_code == 409
        assert "last active admin" in resp.json()["detail"].lower()

    async def test_can_demote_a_different_admin_when_actor_remains(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        # The count guard runs (target is an active admin) but passes — the actor
        # remains an active admin, so >=1 is satisfied.
        await _make_admin(db_session, test_user)
        other = await _seed(db_session, "other-admin@example.com", is_admin=True)
        resp = await client.patch(f"/api/admin/users/{other.id}", json={"is_admin": False})
        assert resp.status_code == 200
        assert resp.json()["is_admin"] is False

    async def test_can_disable_a_different_admin_when_actor_remains(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        other = await _seed(db_session, "other-admin2@example.com", is_admin=True)
        resp = await client.patch(f"/api/admin/users/{other.id}", json={"is_active": False})
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False


class TestSelfGuard:
    """A footgun guard distinct from the last-admin invariant: an admin can't
    disable/de-admin their OWN account, and it fires even when other admins
    exist (so it's not the count guard talking)."""

    async def test_self_disable_blocked_even_with_another_admin(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "admin2@example.com", is_admin=True)
        resp = await client.patch(f"/api/admin/users/{test_user.id}", json={"is_active": False})
        assert resp.status_code == 409
        assert "your own" in resp.json()["detail"].lower()

    async def test_self_demote_blocked_even_with_another_admin(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "admin3@example.com", is_admin=True)
        resp = await client.patch(f"/api/admin/users/{test_user.id}", json={"is_admin": False})
        assert resp.status_code == 409
        assert "your own" in resp.json()["detail"].lower()


class TestResetOnboarding:
    async def test_resets_flag_and_audits(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed(db_session, "onb@example.com", onboarding_completed=True)
        resp = await client.post(f"/api/admin/users/{target.id}/reset-onboarding")
        assert resp.status_code == 200
        assert resp.json()["onboarding_completed"] is False
        assert _has(await _actions_for(db_session, target.id), "user.reset_onboarding")  # type: ignore[arg-type]

    async def test_idempotent_when_already_reset_no_audit(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed(db_session, "onb2@example.com", onboarding_completed=False)
        resp = await client.post(f"/api/admin/users/{target.id}/reset-onboarding")
        assert resp.status_code == 200
        assert await _actions_for(db_session, target.id) == []  # type: ignore[arg-type]

    async def test_not_found_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        assert (
            await client.post("/api/admin/users/999999/reset-onboarding")
        ).status_code == 404

    async def test_demo_user_cannot_be_reset(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        demo = await _seed(db_session, "demo-onb@example.com", is_demo=True, onboarding_completed=True)
        resp = await client.post(f"/api/admin/users/{demo.id}/reset-onboarding")
        assert resp.status_code == 400
        await db_session.refresh(demo)
        assert demo.onboarding_completed is True  # unchanged
        assert await _actions_for(db_session, demo.id) == []  # type: ignore[arg-type]


class TestForceLogout:
    async def test_revokes_sessions_bumps_tv_and_audits(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        target = await _seed(db_session, "fl@example.com")
        sess = await _live_session(db_session, target.id, "b")  # type: ignore[arg-type]
        old_tv = target.token_version

        resp = await client.post(f"/api/admin/users/{target.id}/logout")
        assert resp.status_code == 204

        await db_session.refresh(target)
        await db_session.refresh(sess)
        assert target.token_version == old_tv + 1
        assert sess.revoked_at is not None
        # Account is NOT disabled — force-logout is not deactivation.
        assert target.is_active is True
        assert _has(await _actions_for(db_session, target.id), "user.force_logout")  # type: ignore[arg-type]

    async def test_not_found_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        assert (await client.post("/api/admin/users/999999/logout")).status_code == 404


def _has(actions: list[str], action: str) -> bool:
    return action in actions
