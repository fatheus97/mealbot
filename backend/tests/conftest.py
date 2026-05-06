import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.db import get_session
from app.models.db_models import User

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


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """Disable rate limiting for all tests to prevent cross-test interference."""
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _disable_csrf(monkeypatch: pytest.MonkeyPatch):
    """Disable CSRF middleware for the default test client.

    The bulk of the test suite uses the dependency-overridden `client`
    fixture and never carries auth cookies; requiring CSRF would force
    every mutation test to plumb the X-CSRF-Token header. Tests that
    specifically exercise CSRF re-enable it locally.
    """
    monkeypatch.setattr(settings, "csrf_enabled", False)


@pytest.fixture(autouse=True)
def _disable_cookie_secure(monkeypatch: pytest.MonkeyPatch):
    """Tests use httpx ASGITransport over plain http://test, so cookies set
    with Secure would be silently dropped by the client and break every
    cookie-driven test. Production keeps cookie_secure=True (the default)."""
    monkeypatch.setattr(settings, "cookie_secure", False)


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
    """Decorative fixture, kept for test ergonomics.

    The `client` fixture below overrides get_current_user with a function
    that just returns test_user, so auth is not actually validated. We
    return an empty dict — tests that historically passed `headers=auth_headers`
    keep compiling and the override does the real work.
    """
    assert test_user.id is not None
    return {}


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
