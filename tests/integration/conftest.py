from collections.abc import AsyncIterator, Callable, Iterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from app.core.config import settings
from app.core.db import get_session
from app.main import app
from tests.integration.helpers import Ring, field_payload

POSTGIS_IMAGE = "postgis/postgis:16-3.4"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    with PostgresContainer(POSTGIS_IMAGE, driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session", autouse=True)
def migrated_database(database_url: str) -> None:
    """Apply the real migrations, including a full downgrade/upgrade round-trip."""
    original_url = settings.database_url
    settings.database_url = database_url  # read by migrations/env.py
    try:
        alembic_config = Config("alembic.ini")
        command.upgrade(alembic_config, "head")
        command.downgrade(alembic_config, "base")
        command.upgrade(alembic_config, "head")
    finally:
        settings.database_url = original_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE field"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def create_field(client: AsyncClient) -> Callable:
    async def create(*rings: Ring, **fields: str) -> dict:
        response = await client.post("/api/fields", json=field_payload(*rings, **fields))
        assert response.status_code == 201, response.text
        return response.json()

    return create
