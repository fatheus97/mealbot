"""Idempotent script to seed the demo user with realistic fridge data.

Usage:
    docker compose -f docker-compose.yml -f docker-compose.demo.yml exec backend \
        python -m app.scripts.seed_demo

Guards against running on production by checking DEMO_MODE=true.
"""
import asyncio
import sys
from datetime import date, timedelta

from sqlmodel import delete, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.db import async_session_factory
from app.models.db_models import StockItem, User

DEMO_EMAIL = "demo@trymealbot.com"

FRIDGE_SEED: list[tuple[str, float, int | None, bool]] = [
    # (name, grams, expiry_offset_days, need_to_use)
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


async def seed() -> None:
    if not settings.demo_mode:
        print("Error: DEMO_MODE is not enabled. Set DEMO_MODE=true before seeding.", file=sys.stderr)
        sys.exit(1)

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.is_demo == True))  # noqa: E712
        demo_user: User | None = result.scalars().first()

        if demo_user is None:
            demo_user = User(
                email=DEMO_EMAIL,
                hashed_password=get_password_hash("DemoMode1"),
                is_demo=True,
                onboarding_completed=True,
                country="US",
                language="English",
                measurement_system="metric",
                variability="traditional",
                include_spices=True,
                track_snacks=False,
            )
            session.add(demo_user)
            await session.commit()
            await session.refresh(demo_user)
            print(f"Created demo user id={demo_user.id} email={demo_user.email}")
        else:
            print(f"Demo user already exists id={demo_user.id} email={demo_user.email}")

        if demo_user.id is None:
            print("Error: demo user has no id after creation.", file=sys.stderr)
            sys.exit(1)

        # Replace fridge items
        await session.execute(delete(StockItem).where(StockItem.user_id == demo_user.id))  # type: ignore[arg-type]
        today = date.today()
        for name, grams, offset, need_to_use in FRIDGE_SEED:
            expiry = today + timedelta(days=offset) if offset is not None else None
            session.add(StockItem(
                user_id=demo_user.id,
                name=name,
                quantity_grams=grams,
                expiration_date=expiry,
                need_to_use=need_to_use,
            ))
        await session.commit()
        print(f"Seeded {len(FRIDGE_SEED)} fridge items for demo user.")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
