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


async def create_user(
    email: str, password: str, is_admin: bool = False, is_comped: bool = False
) -> None:
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

        user = User(
            email=email,
            hashed_password=get_password_hash(password),
            is_admin=is_admin,
            is_comped=is_comped,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(
            f"Created user id={user.id} email={user.email} "
            f"is_admin={user.is_admin} is_comped={user.is_comped}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an alpha user")
    parser.add_argument("--email", required=True, help="User email address")
    parser.add_argument("--password", required=True, help="User password (min 8 chars, upper+lower+digit)")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Grant admin access (admin API). Off by default.",
    )
    parser.add_argument(
        "--comp",
        action="store_true",
        help="Grant complimentary ('friendlist') access — bypasses the paywall. "
        "Off by default.",
    )
    args = parser.parse_args()
    asyncio.run(
        create_user(args.email, args.password, is_admin=args.admin, is_comped=args.comp)
    )


if __name__ == "__main__":
    main()
