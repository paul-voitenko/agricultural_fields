from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.db.repositories.field_repository import FieldRepository
from app.services.field_service import FieldService


def get_field_service(session: Annotated[AsyncSession, Depends(get_session)]) -> FieldService:
    return FieldService(FieldRepository(session))
