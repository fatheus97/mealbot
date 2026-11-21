"""utc_timestamps_01 keeps every stored instant, in place, whatever the session zone.

The 36 naive columns hold UTC wall clock. Converting them casts each value in
the session TimeZone, so the migration pins its own transaction to UTC instead
of trusting the connection (alembic's env pins it too, but an offline ``--sql``
run or a hand-run upgrade does not). This test runs the revision in a session
set to America/New_York, where a missing pin would shift every value by 4 to 5
hours, and checks:

* each seeded instant reads back unchanged after upgrade, and again as the same
  naive value after downgrade;
* no table is rewritten (a rewrite rebuilds mealentry's HNSW index, which on a
  big table could run into the 30 s statement timeout);
* the household trigger stamps the real time, not UTC wall clock read as
  New York time.

The parity test (test_schema_matches_migrations) covers the other half: that
head's types equal the models'.
"""

import asyncio
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import URL, Connection, create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import _ensure_database
from tests.test_schema_matches_migrations import _alembic

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_NEW_YORK = {"options": "-c timezone=America/New_York"}


def _migration() -> ModuleType:
    path = _VERSIONS / "utc_timestamps_01_timestamptz_columns.py"
    spec = importlib.util.spec_from_file_location("utc_timestamps_01", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _filler(data_type: str) -> object:
    if data_type in ("text", "character varying"):
        return "x"
    if data_type == "boolean":
        return False
    if data_type in ("integer", "bigint", "smallint", "double precision", "numeric", "real"):
        return 0
    if data_type in ("json", "jsonb"):
        return "{}"
    if data_type == "date":
        return "2026-01-01"
    if data_type == "timestamp with time zone":
        return "2026-01-01 00:00:00+00"
    if data_type == "ARRAY":
        return []
    raise AssertionError(f"no filler for a required {data_type} column")


def _insert(conn: Connection, table: str, given: dict[str, object]) -> int:
    """Insert one row: the given values, plus a filler for every other NOT NULL
    column without a default. Returns its id (0 for a table keyed otherwise)."""
    required = conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = :t"
            " AND is_nullable = 'NO' AND column_default IS NULL"
            " AND is_identity = 'NO' AND column_name <> 'id'"
        ),
        {"t": table},
    ).all()
    values = dict(given)
    for name, data_type in required:
        if str(name) not in values:
            values[str(name)] = _filler(str(data_type))
    cols = ", ".join(f'"{c}"' for c in values)
    params = ", ".join(f":{c}" for c in values)
    has_id = conn.execute(
        text(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_schema = 'public' AND table_name = :t AND column_name = 'id'"
        ),
        {"t": table},
    ).scalar_one()
    returning = " RETURNING id" if has_id else ""
    row = conn.execute(text(f'INSERT INTO "{table}" ({cols}) VALUES ({params}){returning}'), values)
    return int(row.scalar_one()) if has_id else 0


def _seed_values(module: ModuleType) -> dict[tuple[str, str], datetime]:
    """A distinct naive UTC value per converted column, some near midnight so a
    shift would also move the date."""
    seeded: dict[tuple[str, str], datetime] = {}
    base = datetime(2026, 3, 29, 23, 30, 0, 123456)
    for i, (table, columns) in enumerate(module.NAIVE_COLUMNS.items()):
        for j, column in enumerate(columns):
            seeded[(table, column)] = base + timedelta(days=i, minutes=j)
    return seeded


# Seeding order and foreign keys: a row in every one of the 18 tables, so every
# converted column holds a value.
def _seed(conn: Connection, seeded: dict[tuple[str, str], datetime]) -> None:
    def cols(table: str) -> dict[str, object]:
        return {c: v for (t, c), v in seeded.items() if t == table}

    user_id = _insert(
        conn,
        "user",
        {
            # NULL so the BEFORE INSERT trigger gives the user a household.
            "household_id": None,
            "email": "tz@example.com",
            "normalized_email": "tz@example.com",
            **cols("user"),
        },
    )
    household_id = conn.execute(
        text('SELECT household_id FROM "user" WHERE id = :u'), {"u": user_id}
    ).scalar_one()
    conn.execute(
        text("UPDATE household SET created_at = :v WHERE id = :h"),
        {"v": seeded[("household", "created_at")], "h": household_id},
    )
    ids: dict[str, int] = {"user": user_id, "household": int(household_id)}
    ids["mealplan"] = _insert(
        conn, "mealplan", {**_foreign_keys(conn, "mealplan", ids), **cols("mealplan")}
    )
    # mealentry names its plan and household without a foreign key.
    loose = {"mealentry": {"meal_plan_id": ids["mealplan"], "household_id": household_id}}
    for table in seeded_tables(seeded):
        if table in ids:
            continue
        given = {**loose.get(table, {}), **_foreign_keys(conn, table, ids)}
        _insert(conn, table, {**given, **cols(table)})


def _foreign_keys(conn: Connection, table: str, ids: dict[str, int]) -> dict[str, object]:
    """Every foreign-key column of the table, pointed at the seeded row of the
    table it references."""
    rows = conn.execute(
        text(
            "SELECT a.attname, c.confrelid::regclass::text FROM pg_constraint c"
            " JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)"
            " WHERE c.contype = 'f' AND c.conrelid = CAST(:t AS regclass)"
        ),
        {"t": f'"{table}"'},
    ).all()
    out: dict[str, object] = {}
    for column, target in rows:
        name = str(target).strip('"')
        assert name in ids, f"{table}.{column} references {name}, which this test does not seed"
        out[str(column)] = ids[name]
    return out


def seeded_tables(seeded: dict[tuple[str, str], datetime]) -> list[str]:
    return list(dict.fromkeys(t for t, _ in seeded))


def _read(conn: Connection, seeded: dict[tuple[str, str], datetime], *, aware: bool) -> dict[tuple[str, str], Any]:
    out: dict[tuple[str, str], Any] = {}
    for table, column in seeded:
        expr = f"{column} AT TIME ZONE 'UTC'" if aware else column
        # One row per table at this point, so scalar_one() also checks that.
        out[(table, column)] = conn.execute(text(f'SELECT {expr} FROM "{table}"')).scalar_one()
    return out


def _types(conn: Connection, seeded: dict[tuple[str, str], datetime]) -> set[str]:
    rows = conn.execute(
        text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns"
            " WHERE table_schema = 'public'"
        )
    ).all()
    wanted = set(seeded)
    return {str(r[2]) for r in rows if (str(r[0]), str(r[1])) in wanted}


def _filenodes(conn: Connection, tables: list[str]) -> dict[str, int]:
    return {
        t: int(conn.execute(text("SELECT pg_relation_filenode(CAST(:t AS regclass))"), {"t": f'"{t}"'}).scalar_one())
        for t in tables
    }


def _run(conn: Connection, step: str, module: ModuleType) -> None:
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, step)()


def _exercise(url: URL) -> None:
    module = _migration()
    seeded = _seed_values(module)
    tables = seeded_tables(seeded)
    assert len(seeded) == 36 and len(tables) == 18

    engine = create_engine(url, connect_args=_NEW_YORK)
    try:
        with engine.begin() as conn:
            assert conn.execute(text("SHOW timezone")).scalar_one() == "America/New_York"
            _seed(conn, seeded)
            assert _types(conn, seeded) == {"timestamp without time zone"}
            before = _filenodes(conn, tables)

        with engine.begin() as conn:
            _run(conn, "upgrade", module)

        with engine.begin() as conn:
            assert _types(conn, seeded) == {"timestamp with time zone"}
            assert _read(conn, seeded, aware=True) == seeded
            # In place: no table got a new file.
            assert _filenodes(conn, tables) == before
            # The trigger stamps the real time in a New York session too.
            _insert(
                conn,
                "user",
                {
                    "household_id": None,
                    "email": "tz-trigger@example.com",
                    "normalized_email": "tz-trigger@example.com",
                },
            )
            gap = conn.execute(
                text(
                    "SELECT abs(extract(epoch FROM h.created_at - now())) FROM household h"
                    ' JOIN "user" u ON u.household_id = h.id WHERE u.email = :e'
                ),
                {"e": "tz-trigger@example.com"},
            ).scalar_one()
            assert gap < 60, f"trigger stamped a time {gap} s away from now()"
            conn.execute(text("DELETE FROM \"user\" WHERE email = 'tz-trigger@example.com'"))

        with engine.begin() as conn:
            _run(conn, "downgrade", module)

        with engine.begin() as conn:
            assert _types(conn, seeded) == {"timestamp without time zone"}
            assert _read(conn, seeded, aware=False) == seeded
            assert _filenodes(conn, tables) == before
            body = conn.execute(
                text("SELECT pg_get_functiondef(CAST('household_for_new_user' AS regproc))")
            ).scalar_one()
            assert "VALUES (timezone('utc', now()))" in body
    finally:
        engine.dispose()


async def test_utc_timestamps_01_keeps_instants_in_place(test_engine: AsyncEngine) -> None:
    url = test_engine.url.set(database=f"{test_engine.url.database}_tzmig")
    await _ensure_database(url, fresh=True)
    upgrade = _alembic("upgrade", "show_nutrition_01", url=url)
    assert upgrade.returncode == 0, upgrade.stderr[-4000:]
    await asyncio.to_thread(_exercise, url)
