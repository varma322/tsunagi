import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a session that rolls back on error."""
    async with get_session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def create_schema() -> None:
    async with get_engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


MANAGED_TABLES = {"devices", "messages", "api_keys", "enrolment_tokens"}


async def _run_alembic(action: str, revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # alembic/env.py calls asyncio.run(), which cannot run inside this event
    # loop, so the whole command goes to a worker thread.
    await asyncio.to_thread(getattr(command, action), config, revision)


async def ensure_schema() -> None:
    """Bring the database up to the current revision.

    A fresh database is created directly and stamped, which keeps startup (and
    the test suite) fast. An already-tracked database is migrated.

    The third case is the one that matters: a database created by an older
    build's `create_all` has application tables but no `alembic_version`.
    `create_all` never alters existing tables, so such a database silently
    misses every column added since, and fails at runtime rather than startup.
    Refuse loudly instead of guessing which revision it resembles.
    """
    async with get_engine().connect() as connection:
        tables = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )

    if "alembic_version" in tables:
        await _run_alembic("upgrade", "head")
        return

    if not tables & MANAGED_TABLES:
        await create_schema()
        await _run_alembic("stamp", "head")
        return

    raise RuntimeError(
        "This database has Tsunagi tables but no alembic_version, so it was "
        "created by an older build and cannot be migrated safely. Back it up, "
        "then reconcile it:\n"
        "  1. alembic stamp <the revision its schema matches, e.g. 0001>\n"
        "  2. alembic upgrade head\n"
        "Drop any table a later migration creates before step 2, or that "
        "migration will fail because the table already exists."
    )


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
