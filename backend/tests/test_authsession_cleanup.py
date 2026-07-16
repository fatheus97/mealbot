"""Unit tests for the expired-AuthSession cleanup sweep.

Drives the pure service (app.services.authsession_cleanup) directly against the
DB session — no scheduler, no clock. Covers the retention boundary, that
revoked/active state is irrelevant (only expires_at matters), and — the subtle
one — FK-safety over the replaced_by_id rotation chain.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.models.db_models import AuthSession, User
from app.services.authsession_cleanup import sweep_expired_auth_sessions

# A fixed "now" so the retention boundary is deterministic regardless of when
# the suite runs. Aware UTC — expires_at is TIMESTAMPTZ.
NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)


async def _add_session(
    session: AsyncSession,
    user: User,
    *,
    expires_at: datetime,
    revoked_at: datetime | None = None,
    replaced_by_id: int | None = None,
) -> AuthSession:
    """Insert an AuthSession with a unique refresh hash and flush to get its id."""
    # Unique 64-char hex hash per row (the column is a unique index).
    seq = (await session.execute(
        select(func.count()).select_from(AuthSession)
    )).scalar_one()
    row = AuthSession(
        user_id=user.id,  # type: ignore[arg-type]
        refresh_token_hash=f"{seq:064x}",
        created_at=NOW - timedelta(days=60),
        last_used_at=NOW - timedelta(days=60),
        expires_at=expires_at,
        revoked_at=revoked_at,
        replaced_by_id=replaced_by_id,
    )
    session.add(row)
    await session.flush()
    return row


async def _count(session: AsyncSession, user: User) -> int:
    return (await session.execute(
        select(func.count()).select_from(AuthSession).where(
            AuthSession.user_id == user.id
        )
    )).scalar_one()


async def test_deletes_rows_expired_beyond_retention(
    db_session: AsyncSession, test_user: User,
):
    await _add_session(db_session, test_user, expires_at=NOW - timedelta(days=8))
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 1
    assert await _count(db_session, test_user) == 0


async def test_keeps_rows_within_retention_grace(
    db_session: AsyncSession, test_user: User,
):
    # Expired, but only 3 days ago — inside the 7-day grace window, so kept.
    await _add_session(db_session, test_user, expires_at=NOW - timedelta(days=3))
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 0
    assert await _count(db_session, test_user) == 1


async def test_keeps_active_rows(db_session: AsyncSession, test_user: User):
    await _add_session(db_session, test_user, expires_at=NOW + timedelta(days=30))
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 0
    assert await _count(db_session, test_user) == 1


async def test_boundary_is_strict_less_than(
    db_session: AsyncSession, test_user: User,
):
    # Exactly on the cutoff (expires_at == now - retention) must NOT be deleted;
    # the sweep uses a strict `<`. One microsecond older must be.
    cutoff = NOW - timedelta(days=7)
    on_boundary = await _add_session(db_session, test_user, expires_at=cutoff)
    await _add_session(
        db_session, test_user, expires_at=cutoff - timedelta(microseconds=1)
    )
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 1
    remaining = (await db_session.execute(
        select(AuthSession.id).where(AuthSession.user_id == test_user.id)
    )).scalars().all()
    assert remaining == [on_boundary.id]


async def test_revoked_state_is_irrelevant_only_expiry_matters(
    db_session: AsyncSession, test_user: User,
):
    # A long-revoked row that is still within its (unexpired) window is KEPT;
    # an unrevoked-but-long-expired row is DELETED. Expiry is the sole criterion.
    revoked_but_unexpired = await _add_session(
        db_session, test_user,
        expires_at=NOW + timedelta(days=10),
        revoked_at=NOW - timedelta(days=20),
    )
    await _add_session(
        db_session, test_user,
        expires_at=NOW - timedelta(days=9),
        revoked_at=None,
    )
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 1
    remaining = (await db_session.execute(
        select(AuthSession.id).where(AuthSession.user_id == test_user.id)
    )).scalars().all()
    assert remaining == [revoked_but_unexpired.id]


async def test_fk_safe_when_whole_rotation_chain_expires(
    db_session: AsyncSession, test_user: User,
):
    """A rotated row A points at its successor B via replaced_by_id. When both
    cross the cutoff, deleting them in one sweep must not raise an FK error."""
    successor = await _add_session(
        db_session, test_user, expires_at=NOW - timedelta(days=8),
    )
    await _add_session(
        db_session, test_user,
        expires_at=NOW - timedelta(days=9),
        revoked_at=NOW - timedelta(days=9),
        replaced_by_id=successor.id,
    )
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 2
    assert await _count(db_session, test_user) == 0


async def test_fk_safe_deleting_referencing_row_while_successor_stays(
    db_session: AsyncSession, test_user: User,
):
    """The older (referencing) row A can cross the cutoff while its successor B
    is still active. Deleting A must not touch or break B."""
    active_successor = await _add_session(
        db_session, test_user, expires_at=NOW + timedelta(days=20),
    )
    await _add_session(
        db_session, test_user,
        expires_at=NOW - timedelta(days=9),
        revoked_at=NOW - timedelta(days=9),
        replaced_by_id=active_successor.id,
    )
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 1
    remaining = (await db_session.execute(
        select(AuthSession.id).where(AuthSession.user_id == test_user.id)
    )).scalars().all()
    assert remaining == [active_successor.id]


async def test_fk_safe_deleting_successor_while_referencing_row_survives(
    db_session: AsyncSession, test_user: User,
):
    """The subtle demo-user case: the successor (referenced) row can expire
    BEFORE the predecessor (referencing) that points at it — because
    _refresh_ttl_for_user truncates a demo rotation's TTL with int(). Here the
    successor crosses the cutoff while the predecessor doesn't. Pre-fix this
    would abort the whole DELETE with a NO ACTION FK violation; the sweep must
    instead delete the successor, keep the predecessor, and NULL its now-dangling
    replaced_by_id.
    """
    successor = await _add_session(
        db_session, test_user, expires_at=NOW - timedelta(days=8),  # doomed
    )
    predecessor = await _add_session(
        db_session, test_user,
        expires_at=NOW - timedelta(days=3),  # survives (within grace)
        revoked_at=NOW - timedelta(days=3),
        replaced_by_id=successor.id,
    )
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 1
    remaining = (await db_session.execute(
        select(AuthSession.id).where(AuthSession.user_id == test_user.id)
    )).scalars().all()
    assert remaining == [predecessor.id]
    # The dangling pointer was severed rather than left referencing a dead row.
    await db_session.refresh(predecessor)
    assert predecessor.replaced_by_id is None


async def test_no_matching_rows_returns_zero(
    db_session: AsyncSession, test_user: User,
):
    await _add_session(db_session, test_user, expires_at=NOW + timedelta(days=1))
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=7)
    await db_session.commit()
    assert deleted == 0


async def test_zero_retention_deletes_anything_already_expired(
    db_session: AsyncSession, test_user: User,
):
    await _add_session(
        db_session, test_user, expires_at=NOW - timedelta(seconds=1)
    )
    future = await _add_session(
        db_session, test_user, expires_at=NOW + timedelta(seconds=1)
    )
    deleted = await sweep_expired_auth_sessions(db_session, NOW, retention_days=0)
    await db_session.commit()
    assert deleted == 1
    remaining = (await db_session.execute(
        select(AuthSession.id).where(AuthSession.user_id == test_user.id)
    )).scalars().all()
    assert remaining == [future.id]


async def test_negative_retention_raises(
    db_session: AsyncSession, test_user: User,
):
    with pytest.raises(ValueError, match="non-negative"):
        await sweep_expired_auth_sessions(db_session, NOW, retention_days=-1)
