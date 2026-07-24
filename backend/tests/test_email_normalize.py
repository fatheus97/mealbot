"""Tests for email normalization (anti-abuse uniqueness key).

Covers the normalize_email primitive, the frozen copy embedded in the backfill
migration (must stay identical to the live function), and the end-to-end
registration/login behavior: dot/+tag variants of one inbox collapse to a single
account, while a +tag on a non-subaddressing provider stays distinct.
"""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email_normalize import normalize_email
from app.models.db_models import User


# --------------------------------------------------------------------------- #
# normalize_email primitive
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("john.doe@gmail.com", "johndoe@gmail.com"),
        ("johndoe+beta@gmail.com", "johndoe@gmail.com"),
        ("John.Doe+Newsletter@Gmail.com", "johndoe@gmail.com"),
        ("a.b.c@googlemail.com", "abc@gmail.com"),  # googlemail alias + dot-strip
        ("user+tag@outlook.com", "user@outlook.com"),
        ("User@Hotmail.com", "user@hotmail.com"),
        ("person+x@icloud.com", "person@icloud.com"),
        ("a+b@proton.me", "a@proton.me"),
        ("x+y@fastmail.com", "x@fastmail.com"),
        ("a@me.com", "a@icloud.com"),  # Apple aliases canonicalized to icloud.com
        ("a@mac.com", "a@icloud.com"),
        ("Person+x@ME.com", "person@icloud.com"),
        ("user+promo@yahoo.com", "user+promo@yahoo.com"),  # not allowlisted → + kept
        ("john.doe@outlook.com", "john.doe@outlook.com"),  # non-gmail → dots kept
        ("MiXeD@EXAMPLE.com", "mixed@example.com"),  # generic lowercasing
        ("+tag@gmail.com", "+tag@gmail.com"),  # empty-local guard
        (".@gmail.com", ".@gmail.com"),  # empty-local guard (all-dots)
    ],
)
def test_normalize_email(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


def test_normalize_never_yields_empty_local() -> None:
    for raw in ["+tag@gmail.com", ".@gmail.com", "...@gmail.com", "+@gmail.com"]:
        assert normalize_email(raw).split("@", 1)[0] != ""


# --------------------------------------------------------------------------- #
# Migration frozen-copy parity — the backfill embeds a FROZEN copy of
# normalize_email; if the live one changes without updating the migration, this
# fails loudly rather than silently backfilling with stale logic.
# --------------------------------------------------------------------------- #
def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "b4c5d6e7f8a9_add_normalized_email_to_user.py"
    )
    spec = importlib.util.spec_from_file_location("_mig_b4c5d6e7f8a9", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_frozen_normalize_matches_live() -> None:
    frozen = _load_migration()._normalize_email
    samples = [
        "John.Doe@gmail.com",
        "johndoe+beta@gmail.com",
        "a.b.c@googlemail.com",
        "USER+x@outlook.com",
        "person.name@icloud.com",
        "alias@me.com",
        "alias@mac.com",
        "u+t@yahoo.com",
        "john.doe@outlook.com",
        "+tag@gmail.com",
        ".@gmail.com",
        "MixedCase@Example.COM",
        "a.b.c+z@proton.me",
        "plain@fastmail.com",
    ]
    for s in samples:
        assert frozen(s) == normalize_email(s), s


def test_migration_backfill_grandfathers_duplicates() -> None:
    resolve = _load_migration()._resolve_backfill_keys
    rows = [
        (1, "john.doe@gmail.com"),
        (2, "johndoe+x@gmail.com"),  # same inbox as #1 → loser
        (3, "someone@example.com"),
        (4, "a@me.com"),
        (5, "a@icloud.com"),  # same Apple inbox as #4 → loser
    ]
    keys, collisions = resolve(rows)
    assert keys[1] == "johndoe@gmail.com"  # earliest id wins the true key
    assert keys[2] == "johndoe+x@gmail.com+dup2"  # collision-free loser key
    assert keys[3] == "someone@example.com"
    assert keys[4] == "a@icloud.com"
    assert keys[5] == "a@icloud.com+dup5"
    assert collisions == 2
    # Every key is unique → the follow-up UNIQUE add can never fail.
    assert len(set(keys.values())) == len(keys)


def test_migration_backfill_no_collisions_happy_path() -> None:
    resolve = _load_migration()._resolve_backfill_keys
    keys, collisions = resolve([(1, "alice@gmail.com"), (2, "bob@outlook.com")])
    assert collisions == 0
    assert keys == {1: "alice@gmail.com", 2: "bob@outlook.com"}


async def test_column_default_derives_normalized_email(
    db_session: AsyncSession,
) -> None:
    # A bare insert (no explicit normalized_email) must auto-derive it from email
    # via the SQLAlchemy insert-time default — and derive it CORRECTLY (dot/+tag
    # stripped), not merely non-null.
    u = User(email="John.Doe+x@gmail.com", hashed_password="h")
    db_session.add(u)
    await db_session.flush()
    assert u.normalized_email == "johndoe@gmail.com"


# --------------------------------------------------------------------------- #
# End-to-end registration / login flows
# --------------------------------------------------------------------------- #
async def test_registration_rejects_gmail_dot_variant(
    unauthed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "registration_enabled", True)
    r1 = await unauthed_client.post(
        "/api/users/register",
        json={"email": "johndoe@gmail.com", "password": "TestPassword123"},
    )
    assert r1.status_code == 201
    r2 = await unauthed_client.post(
        "/api/users/register",
        json={"email": "john.doe@gmail.com", "password": "TestPassword123"},
    )
    assert r2.status_code == 409  # same inbox → normalized_email collision


async def test_registration_allows_distinct_non_subaddressing_plus(
    unauthed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Yahoo is NOT on the plus allowlist, so "+tag" is a distinct real mailbox —
    # both must register (guard against a false merge).
    monkeypatch.setattr(settings, "registration_enabled", True)
    r1 = await unauthed_client.post(
        "/api/users/register",
        json={"email": "user@yahoo.com", "password": "TestPassword123"},
    )
    assert r1.status_code == 201
    r2 = await unauthed_client.post(
        "/api/users/register",
        json={"email": "user+promo@yahoo.com", "password": "TestPassword123"},
    )
    assert r2.status_code == 201


async def test_login_succeeds_with_gmail_dot_variant(
    unauthed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "registration_enabled", True)
    reg = await unauthed_client.post(
        "/api/users/register",
        json={"email": "John.Doe@gmail.com", "password": "TestPassword123"},
    )
    assert reg.status_code == 201
    # Log in with a different dot/case variant of the SAME inbox.
    login = await unauthed_client.post(
        "/api/auth/login",
        json={"email": "johndoe@gmail.com", "password": "TestPassword123"},
    )
    assert login.status_code == 200


async def test_login_wrong_password_still_401(
    unauthed_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "registration_enabled", True)
    reg = await unauthed_client.post(
        "/api/users/register",
        json={"email": "someone@gmail.com", "password": "TestPassword123"},
    )
    assert reg.status_code == 201
    bad = await unauthed_client.post(
        "/api/auth/login",
        json={"email": "some.one@gmail.com", "password": "WrongPassword123"},
    )
    assert bad.status_code == 401
