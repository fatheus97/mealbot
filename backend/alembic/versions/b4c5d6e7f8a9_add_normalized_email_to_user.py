"""add nullable normalized_email to user + backfill

Anti-abuse uniqueness key: collapses Gmail dot/+tag and allowlisted-provider +tag
aliases so one real inbox can't register many accounts. This first migration adds
the column NULLABLE and backfills it (with a FROZEN copy of
app.core.email_normalize.normalize_email — Alembic must never import evolving app
code); the follow-up migration c5d6e7f8a9b0 tightens it to NOT NULL + UNIQUE.
Splitting the two de-risks the merge-is-deploy migration: the backfill commits
before the constraint is added.

Pre-existing duplicate inboxes (two accounts that normalize to the same key —
expected to be an EMPTY set in alpha) are GRANDFATHERED: the earliest row (min id)
keeps the true normalized key; each later row gets a collision-free-by-construction
key ("<raw>+dup<id>", whose embedded '@domain+dup<id>' can never equal a real
normalized value because a validated domain never contains '+'), so both rows
survive (no merge/delete; billing/SaleRecord linkage intact) and the UNIQUE add in
the next migration can never fail on the auto-deploy.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- FROZEN copy of app.core.email_normalize.normalize_email (keep in sync). A
# --- unit test (test_email_normalize) asserts this stays identical to the live one.
_PLUS_TAG_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "proton.me",
        "protonmail.com",
        "fastmail.com",
    }
)
_DOT_STRIP_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def _normalize_email(email: str) -> str:
    local, _, domain = email.strip().rpartition("@")
    if not local:
        return email.strip().lower()
    domain = domain.lower()
    if domain == "googlemail.com":
        domain = "gmail.com"
    elif domain in ("me.com", "mac.com"):
        domain = "icloud.com"
    original_local = local.lower()
    local = original_local
    if domain in _PLUS_TAG_DOMAINS:
        local = local.split("+", 1)[0]
    if domain in _DOT_STRIP_DOMAINS:
        local = local.replace(".", "")
    if not local:
        local = original_local
    return f"{local}@{domain}"


def _resolve_backfill_keys(rows: list[tuple[int, str]]) -> tuple[dict[int, str], int]:
    """Given (id, email) rows ORDERED BY id, return (id -> normalized_email key,
    collision_count). Earliest id keeps the true normalized key; each later
    duplicate gets a collision-free "<raw>+dup<id>" key (the embedded "@domain+
    dup<id>" can never equal a real normalized value — a validated domain has no
    '+'), so the UNIQUE add in c5d6e7f8a9b0 can never fail. Pure (no DB/op) so the
    risky winner/loser logic is directly unit-tested (test_email_normalize)."""
    seen: dict[str, int] = {}
    result: dict[int, str] = {}
    collisions = 0
    for uid, email in rows:
        key = _normalize_email(email)
        if key in seen:
            key = f"{email.strip().lower()}+dup{uid}"
            collisions += 1
        else:
            seen[key] = uid
        result[uid] = key
    return result, collisions


def upgrade() -> None:
    op.add_column("user", sa.Column("normalized_email", sa.String(), nullable=True))
    bind = op.get_bind()
    rows = [
        (int(r[0]), str(r[1]))
        for r in bind.execute(
            sa.text('SELECT id, email FROM "user" ORDER BY id')
        ).fetchall()
    ]
    keys, collisions = _resolve_backfill_keys(rows)
    for uid, key in keys.items():
        bind.execute(
            sa.text('UPDATE "user" SET normalized_email = :k WHERE id = :i'),
            {"k": key, "i": uid},
        )
    if collisions:
        # Visible in the deploy log; expected 0 in alpha. NOTE: a grandfathered
        # loser can no longer log in or self-reset (its raw address normalizes to
        # the WINNER's key), so handle any reported collisions manually.
        print(
            f"[migration b4c5d6e7f8a9] grandfathered {collisions} "
            f"duplicate-inbox account(s) with +dup keys"
        )


def downgrade() -> None:
    op.drop_column("user", "normalized_email")
