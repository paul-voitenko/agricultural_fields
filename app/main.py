from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.routes import fields, health
from app.core.config import settings
from app.core.db import create_db_engine
from app.core.errors import NotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict]:
    engine = create_db_engine(settings.database_url)
    yield {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    await engine.dispose()


app = FastAPI(title="Agricultural Fields", lifespan=lifespan)
app.include_router(health.router)
app.include_router(fields.router)


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, error: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(error)})
