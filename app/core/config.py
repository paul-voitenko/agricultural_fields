from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/agricultural_fields"
    # Fixed-size pool: under load, requests wait for a free connection instead of opening short-lived extra ones,
    # which cost PostgreSQL a new backend process each and made latency spiral under bursts.
    # Keep db_pool_size * workers * instances below PostgreSQL's max_connections (100 by default).
    db_pool_size: int = 20
    db_max_overflow: int = 0
    db_pool_timeout_seconds: float = 30


settings = Settings()
