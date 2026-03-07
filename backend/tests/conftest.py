import os
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
    AsyncConnection,
)
from sqlalchemy import event, text
from sqlmodel import SQLModel

from app.models.db_models import User
from app.core.security import get_password_hash, create_access_token
from app.db import get_session
from app.api.deps import get_current_user

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://testuser:testpassword@test-db:5432/mealbot_test",
)

TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "TestPassword123"


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Each test gets a session inside a top-level transaction that is always
    rolled back. Endpoint code that calls session.commit() actually commits
    a SAVEPOINT, not the real transaction, so test isolation is preserved.
    """
    async with test_engine.connect() as conn:
        # Start a real transaction that we will roll back at the end
        await conn.begin()

        # Create a session bound to this connection
        session = AsyncSession(bind=conn, expire_on_commit=False)

        # When the session calls commit(), redirect it to a nested SAVEPOINT
        # so the outer transaction stays open for rollback.
        @event.listens_for(session.sync_session, "after_transaction_end")
        def restart_savepoint(sync_session, transaction):
            if transaction.nested and not transaction._parent.nested:
                sync_session.begin_nested()

        # Start the initial SAVEPOINT
        await session.begin_nested()

        yield session

        await session.close()
        await conn.rollback()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        email=TEST_EMAIL,
        hashed_password=get_password_hash(TEST_PASSWORD),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token(subject=test_user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client(
    db_session: AsyncSession, test_user: User
) -> AsyncGenerator[AsyncClient, None]:
    from app.main import app

    async def override_get_session():
        yield db_session

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def unauthed_client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    from app.main import app

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
