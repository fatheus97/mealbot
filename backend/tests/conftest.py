import os
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import URL, event, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlmodel import SQLModel

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.db import get_session
from app.models.db_models import User

_BASE_TEST_DATABASE_URL = make_url(
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://testuser:testpassword@test-db:5432/mealbot_test",
    )
)

# Arbitrary stable bigint used to serialise CREATE DATABASE across xdist workers
# (see _ensure_database): every CREATE DATABASE clones template1, and concurrent
# clones error with "source database template1 is being accessed by other users".
_CREATE_DB_LOCK_KEY = 8_472_913

TEST_EMAIL = "test@example.com"
TEST_PASSWORD = "TestPassword123"


def _worker_database_url() -> URL:
    """Give each xdist worker its own database.

    pytest-xdist runs each worker in its own process, so the session-scoped
    ``test_engine`` fixture runs once per worker. Pointed at one shared database
    the workers would race on the drop_all/create_all below and corrupt each
    other's schema mid-run, so each worker gets its own DB (mealbot_test_gw0,
    _gw1, …) keyed off ``PYTEST_XDIST_WORKER``. Without xdist the variable is
    unset and we return the base URL unchanged — byte-for-byte the previous
    single-database behaviour.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return _BASE_TEST_DATABASE_URL
    return _BASE_TEST_DATABASE_URL.set(
        database=f"{_BASE_TEST_DATABASE_URL.database}_{worker}"
    )


async def _ensure_database(url: URL) -> None:
    """Create the per-worker database if it does not exist yet.

    Connects to the always-present base test database as a maintenance DB and
    issues CREATE DATABASE, serialised cluster-wide with a Postgres advisory
    lock — every CREATE DATABASE clones template1, and concurrent clones from
    parallel workers error with "template1 is being accessed by other users".
    CREATE DATABASE cannot run inside a transaction block, hence AUTOCOMMIT.
    """
    admin_engine = create_async_engine(
        _BASE_TEST_DATABASE_URL, isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text("SELECT pg_advisory_lock(:k)"), {"k": _CREATE_DB_LOCK_KEY}
            )
            try:
                already_exists = await conn.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": url.database},
                )
                if not already_exists:
                    # url.database is derived from PYTEST_XDIST_WORKER (gw0, gw1,
                    # …), never user input, so interpolating it as a quoted
                    # identifier is safe — and CREATE DATABASE can't be bound.
                    await conn.execute(text(f'CREATE DATABASE "{url.database}"'))
            finally:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _CREATE_DB_LOCK_KEY}
                )
    finally:
        await admin_engine.dispose()


@pytest.fixture(scope="session")
async def test_engine():
    db_url = _worker_database_url()
    if os.environ.get("PYTEST_XDIST_WORKER"):
        await _ensure_database(db_url)

    engine = create_async_engine(db_url, echo=False)

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
def _reset_parse_executor_latch():
    """The parse executor (app.core.executors) is a process-global singleton with
    a _shutting_down latch. Any test that runs the app lifespan (e.g. the
    embedding-model init test does `async with lifespan(app)`) trips the latch on
    lifespan shutdown, after which every later test that embeds/parses would hit
    the refuse-to-resurrect RuntimeError. Clear the latch after each test so the
    next lazy caller starts cleanly. The pool itself (pool is None ⇒ lazy-start)
    is self-healing, so we only reset the latch, not the whole pool."""
    yield
    from app.core import executors

    executors._shutting_down = False


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


@pytest.fixture(autouse=True)
def _billing_disabled_by_default(monkeypatch: pytest.MonkeyPatch):
    """Force the paygate OFF for every test by default, so the suite is
    deterministic regardless of the ambient BILLING_ENABLED (a developer's local
    .env may have it on for manual Stripe testing). Without this, every gated
    generation endpoint would 402 whenever billing happens to be enabled in the
    environment. Billing tests that exercise the paywall re-enable it locally via
    ``monkeypatch.setattr(settings, "billing_enabled", True)``."""
    monkeypatch.setattr(settings, "billing_enabled", False)


@pytest.fixture(autouse=True)
def _fast_bcrypt_rounds(monkeypatch: pytest.MonkeyPatch):
    """Hash test passwords at bcrypt's minimum work factor.

    The ``test_user``/``client`` fixtures plus the auth-flow tests hash a
    throwaway password for essentially every test in the suite; at the
    production cost factor (12, ~250 ms/hash) bcrypt alone dominates CI
    wall-clock for zero security value. Dropping to bcrypt's 4 floor makes each
    hash ~2 ms. Verifying still works — ``bcrypt.checkpw`` reads the cost from
    the stored hash, so a cost-4 hash round-trips fine, as does a cost-12
    ``DUMMY_PASSWORD_HASH`` (computed once at import). Prod is untouched:
    Settings defaults to 12 and only this test process mutates the value.
    """
    monkeypatch.setattr(settings, "bcrypt_rounds", 4)


@pytest.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession]:
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
) -> AsyncGenerator[AsyncClient]:
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
) -> AsyncGenerator[AsyncClient]:
    from app.main import app

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
