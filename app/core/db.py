from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings


def create_db_engine(
    database_url: str,
    *,
    pool_size: int = settings.db_pool_size,
    max_overflow: int = settings.db_max_overflow,
    pool_timeout_seconds: float = settings.db_pool_timeout_seconds,
) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout_seconds,
    )


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory: async_sessionmaker[AsyncSession] = request.state.session_factory
    async with session_factory() as session:
        yield session
