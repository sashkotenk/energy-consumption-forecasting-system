"""Async engine and transaction-scoped session construction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

type AsyncSessionFactory = async_sessionmaker[AsyncSession]


def create_database_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Create the process-owned engine; sessions remain operation-scoped."""
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> AsyncSessionFactory:
    """Build a factory that creates one session for each request or worker step."""
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transactional_session(factory: AsyncSessionFactory) -> AsyncIterator[AsyncSession]:
    """Provide one session with an explicit commit-or-rollback transaction boundary."""
    async with factory() as session, session.begin():
        yield session
