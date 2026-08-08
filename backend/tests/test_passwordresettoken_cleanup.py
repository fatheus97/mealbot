"""Unit tests for the expired-PasswordResetToken cleanup sweep.

Drives the pure service (app.services.passwordresettoken_cleanup) directly
against the DB session — no scheduler, no clock. Covers the retention boundary,
that redemption state is irrelevant (only expires_at matters — the bug a
used_at-based cutoff would have), idempotence, and the argument guard.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import func, select

from app.models.db_models import PasswordResetToken, User
from app.services.passwordresettoken_cleanup import (
    DEFAULT_RETENTION_DAYS,
    sweep_expired_reset_tokens,
)

# A fixed "now" so the retention boundary is deterministic regardless of when
# the suite runs. Aware UTC — expires_at is TIMESTAMPTZ.
NOW = datetime(2026, 8, 8, 12, 0, 0, tzinfo=UTC)

# Sentinel for "stamp this row used" without every call site restating a time.
# A distinct value rather than None, because None is meaningful here (see
# _add_token) and a `used_at: datetime | None = None` default would silently
# make every fixture an unstamped row.
_USED = datetime(2026, 1, 1, tzinfo=UTC)


async def _add_token(
    session: AsyncSession,
    user: User,
    *,
    expires_at: datetime,
    used_at: datetime | None = _USED,
) -> PasswordResetToken:
    """Insert a reset token with a unique hash and flush to get its id.

    ``used_at`` defaults to STAMPED, which is what accumulates in production and
    is also what the schema permits: `uq_passwordresettoken_one_live_per_user` is
    partial on ``used_at IS NULL``, NOT on expiry, so a user can hold at most one
    unstamped row *ever* — expired or not. A test wanting the unstamped one
    passes ``used_at=None``, and may do so once per user.

    That is not a test-fixture quirk; it is the shape of the table. Requesting a
    second reset does not delete the first row, it *stamps* it
    (``password_reset.void_outstanding_tokens`` → ``.values(used_at=now)``), so the
    rows this job sweeps are overwhelmingly stamped ones. An earlier draft of
    these tests created several unstamped rows per user and every one of them
    died on that index — which is how the constraint's real predicate got read
    rather than assumed.
    """
    seq = (
        await session.execute(select(func.count()).select_from(PasswordResetToken))
    ).scalar_one()
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=f"{seq:064x}",
        created_at=expires_at - timedelta(minutes=30),
        expires_at=expires_at,
        used_at=used_at,
    )
    session.add(row)
    await session.flush()
    return row


async def _count(session: AsyncSession, user: User) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(PasswordResetToken)
            .where(PasswordResetToken.user_id == user.id)
        )
    ).scalar_one()


async def test_deletes_rows_expired_beyond_retention(
    db_session: AsyncSession, test_user: User
) -> None:
    await _add_token(db_session, test_user, expires_at=NOW - timedelta(days=31))
    await _add_token(db_session, test_user, expires_at=NOW - timedelta(days=400))
    assert await _count(db_session, test_user) == 2

    deleted = await sweep_expired_reset_tokens(db_session, NOW, DEFAULT_RETENTION_DAYS)

    assert deleted == 2
    assert await _count(db_session, test_user) == 0


async def test_keeps_rows_inside_the_retention_window(
    db_session: AsyncSession, test_user: User
) -> None:
    """The boundary is a cutoff, not a truncation: a row that expired yesterday
    is still within 30 days of retention and must survive."""
    await _add_token(db_session, test_user, expires_at=NOW - timedelta(days=1))
    await _add_token(db_session, test_user, expires_at=NOW - timedelta(days=29))

    deleted = await sweep_expired_reset_tokens(db_session, NOW, DEFAULT_RETENTION_DAYS)

    assert deleted == 0
    assert await _count(db_session, test_user) == 2


async def test_keeps_a_token_that_has_not_expired_at_all(
    db_session: AsyncSession, test_user: User
) -> None:
    """A LIVE reset link must never be swept — deleting one turns a working
    email into a dead link with no way for the user to tell why."""
    await _add_token(db_session, test_user, expires_at=NOW + timedelta(minutes=30))

    deleted = await sweep_expired_reset_tokens(db_session, NOW, DEFAULT_RETENTION_DAYS)

    assert deleted == 0
    assert await _count(db_session, test_user) == 1


async def test_redemption_state_is_irrelevant_only_expiry_matters(
    db_session: AsyncSession, test_user: User
) -> None:
    """A stamped row and the one unstamped row are both swept once expired.

    Keying the sweep on ``used_at`` instead would be the bug: an abandoned reset
    link keeps ``used_at IS NULL`` forever, so a redemption-based cutoff would
    retain the request nobody acted on and prune only the ones that worked —
    precisely backwards. Expiry is the property every row eventually acquires.
    """
    await _add_token(db_session, test_user, expires_at=NOW - timedelta(days=31))
    await _add_token(
        db_session, test_user, expires_at=NOW - timedelta(days=31), used_at=None
    )

    deleted = await sweep_expired_reset_tokens(db_session, NOW, DEFAULT_RETENTION_DAYS)

    assert deleted == 2
    assert await _count(db_session, test_user) == 0


async def test_one_unstamped_row_per_user_is_all_the_schema_allows(
    db_session: AsyncSession, test_user: User
) -> None:
    """Documents WHY the fixtures above stamp by default, so nobody 'simplifies'
    them back and rediscovers this the hard way.

    `uq_passwordresettoken_one_live_per_user` is partial on ``used_at IS NULL``
    and says nothing about expiry, so a second unstamped row for the same user
    is a UniqueViolation even when the first expired a year ago. Production
    never hits it because minting SUPERSEDES by stamping the old row rather than
    inserting alongside it — which is exactly why this table accumulates stamped
    rows and needs the sweep.
    """
    await _add_token(
        db_session, test_user, expires_at=NOW - timedelta(days=400), used_at=None
    )
    with pytest.raises(IntegrityError):
        await _add_token(
            db_session, test_user, expires_at=NOW + timedelta(minutes=30), used_at=None
        )
    await db_session.rollback()


async def test_is_idempotent(db_session: AsyncSession, test_user: User) -> None:
    """A second run finds nothing left — what makes a daily timer with
    Persistent=true catch-up safe to fire twice."""
    await _add_token(db_session, test_user, expires_at=NOW - timedelta(days=31))

    assert await sweep_expired_reset_tokens(db_session, NOW, DEFAULT_RETENTION_DAYS) == 1
    assert await sweep_expired_reset_tokens(db_session, NOW, DEFAULT_RETENTION_DAYS) == 0


async def test_zero_retention_deletes_everything_already_expired(
    db_session: AsyncSession, test_user: User
) -> None:
    """Retention 0 means "the cutoff is now" — every expired row goes, the live
    one stays. Guards the boundary arithmetic against an off-by-one that would
    make 0 a no-op."""
    await _add_token(db_session, test_user, expires_at=NOW - timedelta(seconds=1))
    await _add_token(db_session, test_user, expires_at=NOW + timedelta(minutes=30))

    deleted = await sweep_expired_reset_tokens(db_session, NOW, retention_days=0)

    assert deleted == 1
    assert await _count(db_session, test_user) == 1


async def test_negative_retention_is_rejected(
    db_session: AsyncSession, test_user: User
) -> None:
    """A negative window would push the cutoff into the FUTURE and delete live
    tokens. Fail loudly rather than quietly invalidating everyone's reset link."""
    await _add_token(db_session, test_user, expires_at=NOW + timedelta(minutes=30))

    with pytest.raises(ValueError, match="non-negative"):
        await sweep_expired_reset_tokens(db_session, NOW, retention_days=-1)

    assert await _count(db_session, test_user) == 1


async def test_leaves_another_users_tokens_alone_is_not_a_thing_it_promises(
    db_session: AsyncSession, test_user: User
) -> None:
    """Deliberate non-guarantee, asserted so nobody 'fixes' it later.

    The sweep is GLOBAL — it deletes across all users in one statement, which is
    what makes it index-servable by ``ix_passwordresettoken_expires_at`` (the
    other index is user_id-leading and cannot serve a bare cutoff filter). This
    test documents that a second user's expired rows go too; that is the point,
    not a leak.
    """
    other = User(email="other-sweep@x.com", hashed_password="x")
    db_session.add(other)
    await db_session.flush()

    await _add_token(db_session, test_user, expires_at=NOW - timedelta(days=31))
    await _add_token(db_session, other, expires_at=NOW - timedelta(days=31))

    deleted = await sweep_expired_reset_tokens(db_session, NOW, DEFAULT_RETENTION_DAYS)

    assert deleted == 2
    assert await _count(db_session, test_user) == 0
    assert await _count(db_session, other) == 0
