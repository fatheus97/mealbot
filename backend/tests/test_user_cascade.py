"""The database owns "what happens to a user's rows when the user is deleted".

Root-cause guard for #337. Both hard-delete paths (admin ``DELETE
/api/admin/users/{id}`` and the lazy demo sweep) used to hand-delete every owned
table from a list in application code. The list drifted — ``PantryStaple`` was in
one path and not the other — and the resulting IntegrityError on ``delete(User)``
wedged ``POST /api/auth/demo`` in production for every visitor.

The list is gone; the FKs carry the rule. These two tests are what keeps it true:

* ``test_every_user_fk_declares_ondelete`` reads ``SQLModel.metadata`` and fails
  the moment a NEW table points at ``user.id`` without deciding what should
  happen — the exact omission that caused #337, caught at review instead of in
  prod. It needs no database.
* ``test_bare_user_delete_cascades`` proves the DDL actually does it: a raw
  ``DELETE FROM "user"`` with no application code in the path.
"""
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel, col, delete, select

from app.core.email_normalize import normalize_email
from app.core.security import get_password_hash
from app.models.db_models import (
    AuthSession,
    EmailVerificationToken,
    InviteToken,
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

# Rows that must OUTLIVE the account, anonymised rather than deleted: the VAT /
# revenue ledger, the invite audit trail, and a household's plan (it stays with
# the other members; the household's own delete takes it with the last one).
# Everything else user-owned CASCADEs.
_SET_NULL: set[tuple[str, str]] = {
    ("salerecord", "user_id"),
    ("invitetoken", "created_by_admin_id"),
    ("invitetoken", "redeemed_by_user_id"),
    ("mealplan", "created_by_user_id"),
}


def test_every_user_fk_declares_ondelete() -> None:
    """No FK into ``user.id`` may be left at Postgres NO ACTION.

    NO ACTION is not a decision, it is an omission — and it turns a hard-delete
    into an IntegrityError on a live endpoint (#337). Adding a user-owned table
    without an ``ondelete`` fails here.
    """
    offenders: list[str] = []
    for table in SQLModel.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name != "user" or fk.column.name != "id":
                continue
            key = (table.name, fk.parent.name)
            expected = "SET NULL" if key in _SET_NULL else "CASCADE"
            if (fk.ondelete or "").upper() != expected:
                offenders.append(
                    f"{table.name}.{fk.parent.name}: ondelete={fk.ondelete!r}, "
                    f"expected {expected!r}"
                )
    assert not offenders, (
        "Every FK to user.id must declare an ondelete — CASCADE for the user's "
        "own data, SET NULL for rows that must outlive the account. "
        + "; ".join(offenders)
    )


def test_mealentry_meal_plan_fk_cascades() -> None:
    """``mealentry.meal_plan_id`` must CASCADE, not NO ACTION.

    A household delete (the last member's, through the trigger) fires one
    cascade statement per referencing FK, ordered by constraint OID — so it
    differs between databases. With NO ACTION here, the ``mealplan`` cascade's
    end-of-statement RI check can run while the household's ``mealentry`` rows
    still exist and abort the delete. A green test on one DB
    would not prove anything about another; this asserts the DDL directly.
    """
    fk = next(
        fk
        for fk in MealEntry.__table__.foreign_keys  # type: ignore[attr-defined]
        if fk.parent.name == "meal_plan_id"
    )
    assert (fk.ondelete or "").upper() == "CASCADE"


async def _count(db_session: AsyncSession, model: type, uid: int) -> int:
    return int(
        (
            await db_session.execute(
                select(func.count()).select_from(model).where(col(model.user_id) == uid)  # type: ignore[attr-defined]
            )
        ).scalar_one()
    )


async def _count_kitchen(
    db_session: AsyncSession,
    model: type[MealEntry] | type[MealPlan] | type[StockItem] | type[PantryStaple],
    hid: int,
) -> int:
    return int(
        (
            await db_session.execute(
                select(func.count()).select_from(model).where(col(model.household_id) == hid)
            )
        ).scalar_one()
    )


async def test_bare_user_delete_cascades(db_session: AsyncSession) -> None:
    """A raw ``DELETE FROM "user"`` removes every owned row, no app code involved.

    This is the contract both hard-delete paths now rely on. The kitchen rows go
    with the household, which the trigger deletes when its only member goes. It
    also covers the two-table ordering hazard: the plan and its entry are removed
    by two separate cascade statements, and the delete must not depend on which
    fires first.
    """
    user = User(
        email="cascade@example.com",
        normalized_email=normalize_email("cascade@example.com"),
        hashed_password=get_password_hash("Whatever123"),
    )
    db_session.add(user)
    await db_session.flush()
    uid = user.id
    hid = user.household_id
    assert uid is not None
    assert hid is not None

    plan = MealPlan(
        household_id=hid, created_by_user_id=uid, days=1, meals_per_day=1,
        people_count=1, request_json="{}", response_json="{}",
    )
    db_session.add(plan)
    await db_session.flush()
    assert plan.id is not None
    db_session.add_all([
        MealEntry(
            household_id=hid, meal_plan_id=plan.id, day_index=1, meal_index=1,
            name="Soup", meal_type="main_course", meal_json="{}",
        ),
        StockItem(
            household_id=hid, name="egg", quantity_grams=100,
            expiration_date=date.today() + timedelta(days=3),
        ),
        PantryStaple(household_id=hid, name="olive oil"),
        AuthSession(
            user_id=uid, refresh_token_hash="a" * 64,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
        PasswordResetToken(
            user_id=uid, token_hash="b" * 64,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        ),
        EmailVerificationToken(
            user_id=uid, token_hash="c" * 64,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        ),
        MachineGeneration(user_id=uid, surface="meal_plan", output_json="{}"),
        MachineCorrection(user_id=uid, surface="meal_edit", after_json="{}"),
        LlmUsage(
            user_id=uid, surface="meal_plan", provider="gemini",
            model="gemini-2.5-flash", prompt_tokens=10, completion_tokens=5,
            total_tokens=100,
        ),
        SaleRecord(
            stripe_invoice_id="inv_cascade", user_id=uid, amount_cents=1000,
            currency="eur",
        ),
        InviteToken(
            token_hash="d" * 64, created_by_admin_id=uid,
            expires_at=datetime.now(UTC) + timedelta(days=2),
        ),
    ])
    await db_session.flush()

    # No purge helper, no ORM cascade — one statement, exactly what both delete
    # paths now issue.
    await db_session.execute(delete(User).where(col(User.id) == uid))
    await db_session.flush()
    db_session.expire_all()

    for kitchen_model in (MealEntry, MealPlan, StockItem, PantryStaple):
        assert await _count_kitchen(db_session, kitchen_model, hid) == 0, (
            f"{kitchen_model.__name__} not cascaded"
        )
    for model in (
        AuthSession, PasswordResetToken, EmailVerificationToken, MachineGeneration,
        MachineCorrection, LlmUsage,
    ):
        assert await _count(db_session, model, uid) == 0, f"{model.__name__} not cascaded"

    # The ledger and the invite audit trail survive, anonymised.
    sale = (
        await db_session.execute(
            select(SaleRecord).where(col(SaleRecord.stripe_invoice_id) == "inv_cascade")
        )
    ).scalars().first()
    assert sale is not None and sale.user_id is None
    assert sale.amount_cents == 1000

    invite = (
        await db_session.execute(
            select(InviteToken).where(col(InviteToken.token_hash) == "d" * 64)
        )
    ).scalars().first()
    assert invite is not None and invite.created_by_admin_id is None
