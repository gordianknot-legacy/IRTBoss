"""Engine and session lifecycle.

The engine is built lazily on first use rather than at import time. v1 created
it as a module-level side effect, which meant importing anything under ``app.db``
opened a connection pool against whatever ``DATABASE_URL`` happened to be set —
including during test collection, and including in the worker where a *different*
(and undeclared) driver was expected (P5).

``create_all`` exists here only for tests. Production schema changes go through
Alembic; ARCHITECTURE §6 makes that a rule, and v1's total absence of migrations
is what it is reacting to.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

from .models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Process-wide async engine, created on first call."""

    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=settings.sql_echo,
            pool_pre_ping=True,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _sessionmaker


def set_engine(engine: AsyncEngine) -> None:
    """Install an engine explicitly.

    Used by tests and by the worker, both of which build their own engine and
    would otherwise race the lazy constructor.
    """

    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a session with commit-on-success semantics."""

    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all(engine: AsyncEngine) -> None:
    """Create the schema directly. Tests only — see the module docstring."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine) -> None:
    """Drop the schema. Tests only, and only against a disposable database."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
