"""The schema the suite runs on must be the schema prod runs on.

conftest builds the test database with ``SQLModel.metadata.create_all``; prod is
built by ``alembic upgrade head``. Nothing tied the two together, and by
2026-11 they disagreed on 13 columns: seven timestamps were TIMESTAMPTZ in prod
but naive in tests (so the suite read naive datetimes where prod reads aware
ones), one column was TEXT against VARCHAR, and five user columns had a server
default only in prod. authsession also had an index and a constraint that only
the migration created.

Prod is the truth: when this fails, fix the model, unless the migration is
clearly wrong (then write a new migration).
"""

import os
import subprocess
from pathlib import Path

from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from tests.conftest import _ensure_database

_BACKEND_ROOT = Path(__file__).resolve().parents[1]

# One row per schema object, compared as text. Names are part of each row:
# they don't change behaviour, but a name that differs makes autogenerate emit
# a drop and an add.
_CATALOG = {
    "column": """
        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod),
               a.attnotnull::text, coalesce(pg_get_expr(d.adbin, d.adrelid), '')
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'
          AND a.attnum > 0 AND NOT a.attisdropped
    """,
    "index": "SELECT tablename, indexdef FROM pg_indexes WHERE schemaname = 'public'",
    "constraint": """
        SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
        FROM pg_constraint WHERE connamespace = 'public'::regnamespace
    """,
    # The household triggers are hand-mirrored (HOUSEHOLD_TRIGGERS_SQL vs a
    # frozen copy in household_01), so their functions are compared too.
    "trigger": """
        SELECT tgrelid::regclass::text, pg_get_triggerdef(oid), pg_get_functiondef(tgfoid)
        FROM pg_trigger WHERE NOT tgisinternal
    """,
}


async def _snapshot(conn: AsyncConnection) -> set[tuple[str, ...]]:
    rows: set[tuple[str, ...]] = set()
    for kind, sql in _CATALOG.items():
        for row in (await conn.execute(text(sql))).all():
            table = str(row[0])
            if table != "alembic_version":
                rows.add((kind, table, *(str(v) for v in row[1:])))
    return rows


def _alembic(*args: str, url: URL) -> subprocess.CompletedProcess[str]:
    # A subprocess, not alembic.command: env.py calls asyncio.run(), which
    # cannot run inside this test's event loop.
    return subprocess.run(
        ["alembic", *args],
        cwd=_BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": url.render_as_string(hide_password=False)},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


async def test_create_all_schema_matches_migrations(test_engine: AsyncEngine) -> None:
    migrated_url = test_engine.url.set(database=f"{test_engine.url.database}_migrated")
    await _ensure_database(migrated_url, fresh=True)

    upgrade = _alembic("upgrade", "head", url=migrated_url)
    assert upgrade.returncode == 0, upgrade.stderr[-4000:]

    migrated_engine = create_async_engine(migrated_url)
    try:
        async with migrated_engine.connect() as conn:
            migrated = await _snapshot(conn)
    finally:
        await migrated_engine.dispose()
    async with test_engine.connect() as conn:
        created = await _snapshot(conn)

    only_prod = sorted(migrated - created)
    only_tests = sorted(created - migrated)
    assert not only_prod and not only_tests, "\n".join(
        [
            "Models and migrations build different schemas.",
            "Only after `alembic upgrade head` (prod):",
            *(f"  {r}" for r in only_prod),
            "Only after create_all (the test suite):",
            *(f"  {r}" for r in only_tests),
        ]
    )

    # The catalogs match, so autogenerate must see nothing to do. It fails when
    # env.py stops importing the models: every table then reads as removed.
    check = _alembic("check", url=migrated_url)
    assert check.returncode == 0, check.stdout[-2000:] + check.stderr[-4000:]
