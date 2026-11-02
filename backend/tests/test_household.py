"""Every account is in exactly one household, and the database keeps it so.

docs/household-design.md, PR 1. The rules under test live in two triggers on
"user" (app.models.db_models.HOUSEHOLD_TRIGGERS_SQL), not in app code, because
three delete paths are a bare ``DELETE FROM "user"``:

* a user inserted without a household gets a new one, whatever inserted it;
* a household left without a member is deleted, and one that still has a
  member is not, even when its last two members are deleted at the same time.
"""
import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from sqlalchemy import func, insert, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlmodel import col, delete, select

from app.core.email_normalize import normalize_email
from app.core.security import get_password_hash
from app.models.db_models import HOUSEHOLD_TRIGGERS_SQL, Household, User
from app.services.demo_user import cleanup_expired_demo_users
from tests.conftest import TEST_PASSWORD

_HASH = get_password_hash(TEST_PASSWORD)


def _user(email: str, household_id: int | None = None) -> User:
    return User(
        email=email,
        normalized_email=normalize_email(email),
        hashed_password=_HASH,
        household_id=household_id,
    )


async def _orphans(session: AsyncSession) -> int:
    """Households no user points at. Must always be zero."""
    count: int = (
        await session.execute(
            text(
                'SELECT count(*) FROM household h WHERE NOT EXISTS '
                '(SELECT 1 FROM "user" u WHERE u.household_id = h.id)'
            )
        )
    ).scalar_one()
    return count


async def _household_exists(session: AsyncSession, household_id: int) -> bool:
    found = await session.execute(select(Household.id).where(col(Household.id) == household_id))
    return found.first() is not None


class TestEveryUserGetsOne:
    async def test_the_fixture_user_has_one_and_the_orm_reads_it_back(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        # FetchedValue: the ORM leaves the column out of the INSERT and reads
        # the trigger's value back, so no refresh is needed.
        assert test_user.household_id is not None
        assert await _household_exists(db_session, test_user.household_id)

    async def test_household_ids_start_far_from_user_ids(self, test_user: User) -> None:
        # conftest restarts the sequence so a swapped user/household id cannot
        # pass by coincidence. If this fails, that guard is gone.
        assert test_user.household_id is not None
        assert test_user.household_id >= 1_000_001
        assert test_user.id is not None
        assert test_user.id < 1_000_001

    async def test_a_core_insert_gets_one_too(self, db_session: AsyncSession) -> None:
        email = "core-insert@example.com"
        await db_session.execute(
            insert(User).values(
                email=email, normalized_email=normalize_email(email), hashed_password=_HASH
            )
        )
        household_id = (
            await db_session.execute(select(User.household_id).where(col(User.email) == email))
        ).scalar_one()
        assert household_id is not None
        assert await _household_exists(db_session, household_id)

    async def test_two_new_users_get_two_households(self, db_session: AsyncSession) -> None:
        a, b = _user("one@example.com"), _user("two@example.com")
        db_session.add_all([a, b])
        await db_session.flush()
        assert a.household_id is not None and b.household_id is not None
        assert a.household_id != b.household_id

    async def test_an_explicit_household_is_kept(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        partner = _user("partner@example.com", household_id=test_user.household_id)
        db_session.add(partner)
        await db_session.flush()
        # Read from the row: the ORM sent the value as a literal and never
        # reads it back, so the attribute would match even if the trigger had
        # replaced it.
        stored = (
            await db_session.execute(select(User.household_id).where(col(User.id) == partner.id))
        ).scalar_one()
        assert stored == test_user.household_id


class TestTheLastMemberTakesItAlong:
    async def test_deleting_the_only_member_deletes_the_household(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        household_id = test_user.household_id
        assert household_id is not None
        await db_session.execute(delete(User).where(col(User.id) == test_user.id))
        assert not await _household_exists(db_session, household_id)

    async def test_deleting_one_of_two_keeps_it(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        household_id = test_user.household_id
        assert household_id is not None
        db_session.add(_user("partner@example.com", household_id=household_id))
        await db_session.flush()
        await db_session.execute(delete(User).where(col(User.id) == test_user.id))
        assert await _household_exists(db_session, household_id)
        assert await _orphans(db_session) == 0

    async def test_one_statement_deleting_both_members_deletes_it(
        self, test_user: User, db_session: AsyncSession
    ) -> None:
        household_id = test_user.household_id
        assert household_id is not None
        db_session.add(_user("partner@example.com", household_id=household_id))
        await db_session.flush()
        await db_session.execute(delete(User).where(col(User.household_id) == household_id))
        assert not await _household_exists(db_session, household_id)

    async def test_the_demo_sweep_leaves_no_household_behind(
        self, db_session: AsyncSession
    ) -> None:
        old = datetime.now(UTC) - timedelta(minutes=5)
        for n in range(3):
            demo = _user(f"demo-sweep-{n}@example.com")
            demo.is_demo = True
            demo.created_at = old
            db_session.add(demo)
        await db_session.flush()
        assert await cleanup_expired_demo_users(db_session, 0) == 3
        assert await _orphans(db_session) == 0


class TestConcurrentLastMembers:
    """Each delete on its own connection with real commits: the shared-session
    harness cannot show a race, since there every statement shares one
    connection."""

    async def test_two_last_members_deleted_at_once_leave_no_household(
        self, test_engine: AsyncEngine
    ) -> None:
        async with AsyncSession(test_engine, expire_on_commit=False) as s:
            a = _user("race-a@example.com")
            s.add(a)
            await s.flush()
            b = _user("race-b@example.com", household_id=a.household_id)
            s.add(b)
            await s.commit()
        household_id = a.household_id
        assert household_id is not None

        async with (
            AsyncSession(test_engine) as first,
            AsyncSession(test_engine) as second,
            AsyncSession(test_engine) as observer,
        ):
            second_pid = (await second.execute(text("SELECT pg_backend_pid()"))).scalar_one()
            # First deletes A and holds its transaction open: B is still there,
            # so the household stays, and its row is locked until commit.
            await first.execute(delete(User).where(col(User.id) == a.id))
            # Second deletes B. With the lock it waits for the first to commit
            # and then sees A gone; without it, it would still see A (the
            # delete is uncommitted) and keep the household too.
            other = asyncio.create_task(
                second.execute(delete(User).where(col(User.id) == b.id))
            )
            # Commit the first only once Postgres reports the second blocked
            # behind it, so the test can never pass without the lock being
            # taken. Without the lock it never blocks, and this fails.
            for _ in range(100):
                blocked = (
                    await observer.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": second_pid},
                    )
                ).scalar_one()
                if blocked:
                    break
                await asyncio.sleep(0.05)
            assert blocked, "the second delete never waited for the first"
            assert not other.done()
            await first.commit()
            await asyncio.wait_for(other, 10)
            await second.commit()

        async with AsyncSession(test_engine) as s:
            assert not await _household_exists(s, household_id)
            assert await _orphans(s) == 0
            # Nothing else to clean: both users and the household are gone.
            remaining = await s.execute(
                select(func.count()).select_from(User).where(col(User.id).in_([a.id, b.id]))
            )
            assert remaining.scalar_one() == 0


def _migration() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "household_01_give_every_account_a_household.py"
    )
    spec = importlib.util.spec_from_file_location("household_01", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_installs_the_same_triggers_as_the_test_schema() -> None:
    """The migration keeps a frozen copy, as migrations must; until a later
    migration changes the triggers, prod and the test schema run the same SQL."""
    assert _migration().TRIGGERS_SQL == HOUSEHOLD_TRIGGERS_SQL
