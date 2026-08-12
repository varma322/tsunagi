"""Schema bootstrapping.

Regression cover for a database created by an older build's `create_all`:
`create_all` never alters an existing table, so such a database silently misses
every column added since and blows up at request time instead of startup.
"""

import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _with_database(path: Path, coro_factory):
    """Run a coroutine against a specific database file.

    The engine and settings are module-level singletons, so they are swapped out
    and restored around the call.
    """
    from app import db
    from app.config import get_settings

    settings = get_settings()
    original_url = settings.database_url
    settings.database_url = _sqlite_url(path)
    db._engine = None
    db._session_factory = None

    try:
        return asyncio.run(coro_factory())
    finally:
        asyncio.run(db.dispose_engine())
        settings.database_url = original_url
        db._engine = None
        db._session_factory = None


def test_a_fresh_database_is_created_and_stamped():
    from app.db import ensure_schema

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "fresh.db"
        _with_database(path, ensure_schema)

        con = sqlite3.connect(path)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"devices", "messages", "api_keys", "enrolment_tokens"} <= tables
        assert "disabled_at" in {r[1] for r in con.execute("PRAGMA table_info(devices)")}

        version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        assert version == "0003", "a fresh database must be stamped at head"
        con.close()


def test_an_untracked_populated_database_is_refused():
    from app.db import ensure_schema

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "legacy.db"
        # An old create_all database: application tables, no alembic_version,
        # and devices missing every column added after 0001.
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT)")
        con.commit()
        con.close()

        with pytest.raises(RuntimeError, match="no alembic_version"):
            _with_database(path, ensure_schema)


def test_a_tracked_database_is_migrated_forward():
    from app.db import _run_alembic, ensure_schema

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "tracked.db"

        async def at_0001():
            await _run_alembic("upgrade", "0001")

        _with_database(path, at_0001)

        con = sqlite3.connect(path)
        assert "disabled_at" not in {r[1] for r in con.execute("PRAGMA table_info(devices)")}
        con.close()

        _with_database(path, ensure_schema)

        con = sqlite3.connect(path)
        assert "disabled_at" in {r[1] for r in con.execute("PRAGMA table_info(devices)")}
        assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0003"
        con.close()
