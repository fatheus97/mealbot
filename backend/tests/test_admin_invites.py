"""Admin invite-link endpoints: generate / list / revoke.

Covers the require_admin gate, the audit trail (and that the plaintext token
NEVER lands in it), comp/TTL baking, and the revoke guards (404 / already-used
409 / idempotent).
"""
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models.db_models import AdminAuditLog, InviteToken, User


async def _make_admin(db_session: AsyncSession, test_user: User) -> None:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()


def _token_from(url: str) -> str:
    return url.split("invite=", 1)[1]


class TestRequireAdminGate:
    async def test_generate_non_admin_403(self, client: AsyncClient, test_user: User) -> None:
        resp = await client.post("/api/admin/invites", json={})
        assert resp.status_code == 403

    async def test_list_non_admin_403(self, client: AsyncClient, test_user: User) -> None:
        resp = await client.get("/api/admin/invites")
        assert resp.status_code == 403

    async def test_revoke_non_admin_403(self, client: AsyncClient, test_user: User) -> None:
        resp = await client.post("/api/admin/invites/1/revoke")
        assert resp.status_code == 403


class TestGenerateInvite:
    async def test_generates_link_comped_by_default_and_audits_without_token(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.post("/api/admin/invites", json={"note": "for Alice"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["invite_url"].startswith(settings.frontend_base_url)
        assert "?invite=" in body["invite_url"]
        assert body["is_comped"] is True  # comped by default
        assert body["note"] == "for Alice"
        assert body["expires_at"]

        token = _token_from(body["invite_url"])
        rows = (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "invite.create")
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_user_id == test_user.id
        assert rows[0].target_user_id is None
        # The plaintext token is a real credential — never in the audit log.
        assert token not in str(rows[0].detail)

        # The stored row holds only the hash, never the plaintext.
        invites = (await db_session.execute(select(InviteToken))).scalars().all()
        assert len(invites) == 1
        assert invites[0].token_hash != token
        assert invites[0].is_comped is True

    async def test_comp_toggle_off(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.post("/api/admin/invites", json={"is_comped": False})
        assert resp.status_code == 201
        assert resp.json()["is_comped"] is False

    async def test_custom_expiry_hours(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        before = datetime.now(UTC)
        resp = await client.post("/api/admin/invites", json={"expires_in_hours": 1})
        assert resp.status_code == 201
        expires = datetime.fromisoformat(resp.json()["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        delta_h = (expires - before).total_seconds() / 3600
        assert 0.5 < delta_h < 2  # ~1h, well under the 48h default


class TestListInvites:
    async def test_lists_generated_invites_newest_first(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await client.post("/api/admin/invites", json={"note": "one"})
        await client.post("/api/admin/invites", json={"note": "two"})
        resp = await client.get("/api/admin/invites")
        assert resp.status_code == 200
        invites = resp.json()["invites"]
        assert len(invites) == 2
        assert invites[0]["note"] == "two"  # newest first
        assert all(i["status"] == "live" for i in invites)
        assert all(i["redeemed_by_email"] is None for i in invites)
        # The token/hash is never exposed in the list projection.
        assert all("token" not in i and "token_hash" not in i for i in invites)


class TestRevokeInvite:
    async def _generate(self, client: AsyncClient) -> int:
        resp = await client.post("/api/admin/invites", json={})
        return int(resp.json()["id"])

    async def test_revoke_marks_revoked_and_audits(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        invite_id = await self._generate(client)
        resp = await client.post(f"/api/admin/invites/{invite_id}/revoke")
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

        row = (
            await db_session.execute(select(InviteToken).where(InviteToken.id == invite_id))
        ).scalars().first()
        assert row is not None and row.revoked_at is not None
        actions = (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "invite.revoke")
            )
        ).scalars().all()
        assert len(actions) == 1

    async def test_revoke_missing_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.post("/api/admin/invites/999999/revoke")
        assert resp.status_code == 404

    async def test_revoke_idempotent(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        invite_id = await self._generate(client)
        first = await client.post(f"/api/admin/invites/{invite_id}/revoke")
        second = await client.post(f"/api/admin/invites/{invite_id}/revoke")
        assert first.status_code == second.status_code == 200
        assert second.json()["status"] == "revoked"
        actions = (
            await db_session.execute(
                select(AdminAuditLog).where(AdminAuditLog.action == "invite.revoke")
            )
        ).scalars().all()
        assert len(actions) == 1  # only the first revoke audits

    async def test_revoke_used_invite_409(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        invite_id = await self._generate(client)
        # Simulate redemption having already burned the invite.
        row = (
            await db_session.execute(select(InviteToken).where(InviteToken.id == invite_id))
        ).scalars().first()
        assert row is not None
        row.used_at = datetime.now(UTC)
        db_session.add(row)
        await db_session.flush()
        resp = await client.post(f"/api/admin/invites/{invite_id}/revoke")
        assert resp.status_code == 409
