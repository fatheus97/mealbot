"""CLI script to create alpha users manually.

Usage:
    docker compose exec backend python -m app.scripts.create_user \
        --email user@example.com --password '<their-password>'
"""
import argparse
import asyncio
import sys

from pydantic import ValidationError
from sqlmodel import select

from app.core.security import get_password_hash
from app.db import async_session_factory
from app.models.db_models import User
from app.models.user_schemas import UserCreate


async def create_user(email: str, password: str) -> None:
    # Validate email + password rules via the existing schema
    try:
        UserCreate(email=email, password=password)
    except ValidationError as exc:
        print(f"Validation error:\n{exc}", file=sys.stderr)
        sys.exit(1)

    async with async_session_factory() as session:
        result = await session.execute(select(User).where(User.email == email))
        if result.scalars().first():
            print(f"Error: user with email '{email}' already exists.", file=sys.stderr)
            sys.exit(1)

        user = User(email=email, hashed_password=get_password_hash(password))
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"Created user id={user.id} email={user.email}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an alpha user")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument("--password", required=True, help="User password (min 8 chars, upper+lower+digit)")
    args = parser.parse_args()
    asyncio.run(create_user(args.email, args.password))


if __name__ == "__main__":
    main()
