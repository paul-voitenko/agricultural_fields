import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_field_service
from app.schemas.field import (
    FieldCreate,
    FieldListQuery,
    FieldListResponse,
    FieldResponse,
    FindByPointQuery,
    FindByPointResponse,
)
from app.services.field_service import FieldService

router = APIRouter(prefix="/api/fields", tags=["fields"])

FieldServiceDependency = Annotated[FieldService, Depends(get_field_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_field(field: FieldCreate, field_service: FieldServiceDependency) -> FieldResponse:
    return await field_service.create(field)


@router.get("")
async def list_fields(
    query: Annotated[FieldListQuery, Query()], field_service: FieldServiceDependency
) -> FieldListResponse:
    return await field_service.list_fields(query)


@router.get("/find-by-point")
async def find_fields_by_point(
    query: Annotated[FindByPointQuery, Query()], field_service: FieldServiceDependency
) -> FindByPointResponse:
    return await field_service.find_by_point(query)


# Must stay after the static /find-by-point route, which would otherwise be parsed as an id.
@router.get("/{field_id}", responses={status.HTTP_404_NOT_FOUND: {"description": "Field not found"}})
async def get_field(field_id: uuid.UUID, field_service: FieldServiceDependency) -> FieldResponse:
    return await field_service.get(field_id)
