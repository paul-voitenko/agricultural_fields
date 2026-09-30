import asyncio

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings
from app.db.models import Base

EMPTY_DATABASE = "without_postgis"


def _include_object(object_, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "table" and reflected and compare_to is None)


async def test_migrations_match_models(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        diff = await connection.run_sync(
            lambda sync_connection: compare_metadata(
                MigrationContext.configure(sync_connection, opts={"include_object": _include_object}),
                Base.metadata,
            )
        )

    assert diff == []


async def test_health_reports_postgis(client) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["postgis"].startswith("3.")


async def _recreate_empty_database(admin_url: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as connection:
        await connection.execute(text(f"DROP DATABASE IF EXISTS {EMPTY_DATABASE}"))
        await connection.execute(text(f"CREATE DATABASE {EMPTY_DATABASE} TEMPLATE template0"))
    await engine.dispose()


async def _installed_extensions(url: str) -> set[str]:
    engine = create_async_engine(url)
    async with engine.connect() as connection:
        extensions = set((await connection.execute(text("SELECT extname FROM pg_extension"))).scalars())
    await engine.dispose()
    return extensions


def test_migrations_create_postgis_extension(database_url: str) -> None:
    """Migrations must work on a plain database (RDS, Cloud SQL...).

    Not only on one where the Docker image pre-installed PostGIS.
    """
    empty_url = make_url(database_url).set(database=EMPTY_DATABASE).render_as_string(hide_password=False)
    asyncio.run(_recreate_empty_database(database_url))
    assert "postgis" not in asyncio.run(_installed_extensions(empty_url))

    original_url = settings.database_url
    settings.database_url = empty_url
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        settings.database_url = original_url

    assert "postgis" in asyncio.run(_installed_extensions(empty_url))
