from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.db.repositories.field_repository import FieldRepository
from app.services.field_service import FieldService
from app.use_cases.create_field import CreateFieldUseCase
from app.use_cases.find_fields_by_point import FindFieldsByPointUseCase
from app.use_cases.get_field import GetFieldUseCase
from app.use_cases.list_fields import ListFieldsUseCase


def get_field_service(session: Annotated[AsyncSession, Depends(get_session)]) -> FieldService:
    return FieldService(FieldRepository(session))


def get_create_field_use_case(
    field_service: Annotated[FieldService, Depends(get_field_service)],
) -> CreateFieldUseCase:
    return CreateFieldUseCase(field_service)


def get_list_fields_use_case(
    field_service: Annotated[FieldService, Depends(get_field_service)],
) -> ListFieldsUseCase:
    return ListFieldsUseCase(field_service)


def get_find_fields_by_point_use_case(
    field_service: Annotated[FieldService, Depends(get_field_service)],
) -> FindFieldsByPointUseCase:
    return FindFieldsByPointUseCase(field_service)


def get_get_field_use_case(
    field_service: Annotated[FieldService, Depends(get_field_service)],
) -> GetFieldUseCase:
    return GetFieldUseCase(field_service)
