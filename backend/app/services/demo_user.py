"""Ephemeral demo users.

Each /api/demo/session call creates a fresh isolated User so demo visitors
can cook, rate, and finish plans without colliding with each other. Expired
users (and their data) are swept lazily on the next session creation.
"""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, delete, select

from app.core.security import get_password_hash
from app.models.db_models import MealEntry, MealPlan, StockItem, User

# (name, grams, expiry_offset_days, need_to_use)
_FRIDGE_SEED: list[tuple[str, float, int | None, bool]] = [
    ("Chicken breast", 500, 3, False),
    ("Eggs", 360, 14, False),
    ("Pasta", 400, None, False),
    ("Rice", 800, None, False),
    ("Olive oil", 200, None, False),
    ("Cherry tomatoes", 450, 4, True),
    ("Baby spinach", 200, 2, True),
    ("Onions", 360, 21, False),
    ("Garlic", 50, 30, False),
    ("Cheddar cheese", 250, 10, False),
    ("Greek yogurt", 500, 5, False),
    ("Lemons", 200, 12, False),
]


async def create_ephemeral_demo_user(session: AsyncSession) -> User:
    """Create a fresh demo user with seeded fridge. Caller must commit."""
    suffix = uuid4().hex[:8]
    user = User(
        email=f"demo+{suffix}@trymealbot.com",
        # Random password — the demo user is only ever reachable via JWT issued
        # by /api/demo/session, never via /api/users/login.
        hashed_password=get_password_hash(uuid4().hex),
        is_demo=True,
        onboarding_completed=True,
        country="US",
        language="English",
        measurement_system="metric",
        variability="traditional",
        include_spices=True,
        track_snacks=False,
    )
    session.add(user)
    await session.flush()  # populate user.id

    today = date.today()
    for name, grams, offset, need_to_use in _FRIDGE_SEED:
        expiry = today + timedelta(days=offset) if offset is not None else None
        session.add(StockItem(
            user_id=user.id,  # type: ignore[arg-type]
            name=name,
            quantity_grams=grams,
            expiration_date=expiry,
            need_to_use=need_to_use,
        ))
    return user


async def cleanup_expired_demo_users(session: AsyncSession, ttl_minutes: int) -> int:
    """Delete demo users older than ttl_minutes plus all their owned data.

    SQLModel relationships have no DB-level cascade, so we delete children
    first (MealEntry → MealPlan → StockItem → User) inside a single
    transaction. Caller must commit.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)
    result = await session.execute(
        select(User.id).where(User.is_demo == True, User.created_at < cutoff)  # noqa: E712
    )
    expired_ids = [row for row in result.scalars().all()]
    if not expired_ids:
        return 0

    await session.execute(
        delete(MealEntry).where(col(MealEntry.user_id).in_(expired_ids))
    )
    await session.execute(
        delete(MealPlan).where(col(MealPlan.user_id).in_(expired_ids))
    )
    await session.execute(
        delete(StockItem).where(col(StockItem.user_id).in_(expired_ids))
    )
    await session.execute(
        delete(User).where(col(User.id).in_(expired_ids))
    )
    return len(expired_ids)
