from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models import Base


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
