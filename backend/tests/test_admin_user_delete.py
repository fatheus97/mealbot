"""Guarded hard-delete: DELETE /admin/users/{id} (admin user management, Slice 5).

The most destructive admin action. Covers the require_admin gate, the guards
(404 / demo / self / last-admin), and — the load-bearing behaviour — that the
delete purges the user's owned data, CASCADEs telemetry, **anonymises rather
than deletes the SaleRecord revenue ledger**, and leaves the audit row behind.
"""
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.core.security import get_password_hash
from app.models.db_models import (
    AdminAuditLog,
    AuthSession,
    LlmUsage,
    MachineCorrection,
    MachineGeneration,
    MealEntry,
    MealPlan,
    PantryStaple,
    PasswordResetToken,
    SaleRecord,
    StockItem,
    User,
)


async def _make_admin(db_session: AsyncSession, test_user: User) -> None:
    test_user.is_admin = True
    db_session.add(test_user)
    await db_session.flush()


async def _seed(db_session: AsyncSession, email: str, **kw: object) -> User:
    u = User(email=email, hashed_password=get_password_hash("Whatever123"), **kw)  # type: ignore[arg-type]
    db_session.add(u)
    await db_session.flush()
    return u


async def _count(db_session: AsyncSession, model: type, uid: int) -> int:
    return int(
        (
            await db_session.execute(
                select(func.count()).select_from(model).where(col(model.user_id) == uid)  # type: ignore[attr-defined]
            )
        ).scalar_one()
    )


class TestDeleteGate:
    async def test_non_admin_gets_403(self, client: AsyncClient, test_user: User) -> None:
        assert (await client.delete("/api/admin/users/1")).status_code == 403

    async def test_not_found_404(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        assert (await client.delete("/api/admin/users/999999")).status_code == 404

    async def test_demo_user_400(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        demo = await _seed(db_session, "demo@example.com", is_demo=True)
        assert (await client.delete(f"/api/admin/users/{demo.id}")).status_code == 400

    async def test_sole_admin_cannot_delete_self(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        resp = await client.delete(f"/api/admin/users/{test_user.id}")
        assert resp.status_code == 409
        assert "last active admin" in resp.json()["detail"].lower()

    async def test_self_delete_blocked_when_other_admin_exists(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        await _seed(db_session, "admin2@example.com", is_admin=True)
        resp = await client.delete(f"/api/admin/users/{test_user.id}")
        assert resp.status_code == 409
        assert "your own" in resp.json()["detail"].lower()

    async def test_can_delete_a_different_non_last_admin(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        other = await _seed(db_session, "other-admin@example.com", is_admin=True)
        resp = await client.delete(f"/api/admin/users/{other.id}")
        assert resp.status_code == 204


class TestDeletePurgesDataAndPreservesLedger:
    async def test_full_delete(
        self, client: AsyncClient, test_user: User, db_session: AsyncSession,
    ) -> None:
        await _make_admin(db_session, test_user)
        admin_id = test_user.id  # capture before expire_all() below invalidates it
        victim = await _seed(db_session, "victim@example.com")
        vid = victim.id
        assert vid is not None

        # A representative slice of everything a user owns.
        plan = MealPlan(
            user_id=vid, days=1, meals_per_day=1, people_count=1,
            request_json="{}", response_json="{}",
        )
        db_session.add(plan)
        await db_session.flush()
        db_session.add_all([
            MealEntry(
                user_id=vid, meal_plan_id=plan.id, day_index=1, meal_index=1,
                name="Soup", meal_type="main_course", meal_json="{}",
            ),
            StockItem(user_id=vid, name="egg", quantity_grams=100),
            PantryStaple(user_id=vid, name="olive oil"),
            AuthSession(
                user_id=vid, refresh_token_hash="d" * 64,
                expires_at=datetime.now(UTC) + timedelta(days=1),
            ),
            PasswordResetToken(
                user_id=vid, token_hash="e" * 64,
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            ),
            MachineGeneration(user_id=vid, surface="meal_plan", output_json="{}"),
            LlmUsage(
                user_id=vid, surface="meal_plan", provider="gemini",
                model="gemini-2.5-flash", prompt_tokens=10, completion_tokens=5,
                total_tokens=100,
            ),
            MachineCorrection(user_id=vid, surface="meal_edit", after_json="{}"),
            SaleRecord(
                stripe_invoice_id="inv_del", user_id=vid, amount_cents=1000, currency="eur",
            ),
        ])
        await db_session.flush()

        resp = await client.delete(f"/api/admin/users/{vid}")
        assert resp.status_code == 204

        # Drop cached ORM state so the assertions read the committed DB rows
        # (the endpoint used Core deletes, which bypass the identity map).
        db_session.expire_all()

        # The user and every owned table are gone.
        assert (await db_session.execute(select(User).where(col(User.id) == vid))).scalars().first() is None
        assert await _count(db_session, MealEntry, vid) == 0
        assert await _count(db_session, MealPlan, vid) == 0
        assert await _count(db_session, StockItem, vid) == 0
        assert await _count(db_session, PantryStaple, vid) == 0
        assert await _count(db_session, AuthSession, vid) == 0
        assert await _count(db_session, PasswordResetToken, vid) == 0
        assert await _count(db_session, MachineGeneration, vid) == 0  # ON DELETE CASCADE
        assert await _count(db_session, LlmUsage, vid) == 0  # ON DELETE CASCADE
        assert await _count(db_session, MachineCorrection, vid) == 0  # ON DELETE CASCADE

        # The revenue ledger row SURVIVES, anonymised (user_id → NULL).
        sale = (
            await db_session.execute(
                select(SaleRecord).where(col(SaleRecord.stripe_invoice_id) == "inv_del")
            )
        ).scalars().first()
        assert sale is not None, "SaleRecord must NOT be deleted — VAT/tax record"
        assert sale.user_id is None, "SaleRecord must be anonymised, not attributed"
        assert sale.amount_cents == 1000  # the revenue figure is intact

        # The audit row survives the delete (no FK) with the email snapshot.
        audit = (
            await db_session.execute(
                select(AdminAuditLog).where(
                    col(AdminAuditLog.action) == "user.delete",
                    col(AdminAuditLog.target_user_id) == vid,
                )
            )
        ).scalars().all()
        assert len(audit) == 1
        assert audit[0].target_email == "victim@example.com"
        assert audit[0].actor_user_id == admin_id
