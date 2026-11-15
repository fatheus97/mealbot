"""App sessions run in UTC even when the database's own default zone is not UTC.

Naive columns hold UTC and code binds aware datetimes to them, so Postgres
converts in the session TimeZone. app.db pins it; this proves the pin wins over
a database-level setting, which the server's Etc/UTC default would hide.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import make_engine
from tests.conftest import _ensure_database


async def test_app_sessions_are_utc_whatever_the_database_default(
    test_engine: AsyncEngine,
) -> None:
    url = test_engine.url.set(database=f"{test_engine.url.database}_tz")
    await _ensure_database(url, fresh=True)

    # NullPool: a database setting reaches only sessions started after it.
    unpinned = create_async_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    app_engine = make_engine(url)
    try:
        async with unpinned.connect() as conn:
            await conn.execute(
                text(f"ALTER DATABASE \"{url.database}\" SET timezone TO 'America/New_York'")
            )
        # The control: without the pin a new session takes the database's zone.
        async with unpinned.connect() as conn:
            assert await conn.scalar(text("SHOW timezone")) == "America/New_York"
        async with app_engine.connect() as conn:
            assert await conn.scalar(text("SHOW timezone")) == "UTC"
    finally:
        await unpinned.dispose()
        await app_engine.dispose()
