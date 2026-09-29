import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    get_create_field_use_case,
    get_find_fields_by_point_use_case,
    get_get_field_use_case,
    get_list_fields_use_case,
)
from app.schemas.field import (
    FieldCreate,
    FieldListQuery,
    FieldListResponse,
    FieldResponse,
    FindByPointQuery,
    FindByPointResponse,
)
from app.use_cases.create_field import CreateFieldUseCase
from app.use_cases.find_fields_by_point import FindFieldsByPointUseCase
from app.use_cases.get_field import GetFieldUseCase
from app.use_cases.list_fields import ListFieldsUseCase

router = APIRouter(prefix="/api/fields", tags=["fields"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_field(
    field: FieldCreate,
    use_case: Annotated[CreateFieldUseCase, Depends(get_create_field_use_case)],
) -> FieldResponse:
    return await use_case.execute(field)


@router.get("")
async def list_fields(
    query: Annotated[FieldListQuery, Query()],
    use_case: Annotated[ListFieldsUseCase, Depends(get_list_fields_use_case)],
) -> FieldListResponse:
    return await use_case.execute(query)


@router.get("/find-by-point")
async def find_fields_by_point(
    query: Annotated[FindByPointQuery, Query()],
    use_case: Annotated[FindFieldsByPointUseCase, Depends(get_find_fields_by_point_use_case)],
) -> FindByPointResponse:
    return await use_case.execute(query)


# Must stay after the static /find-by-point route, which would otherwise be parsed as an id.
@router.get("/{field_id}", responses={status.HTTP_404_NOT_FOUND: {"description": "Field not found"}})
async def get_field(
    field_id: uuid.UUID,
    use_case: Annotated[GetFieldUseCase, Depends(get_get_field_use_case)],
) -> FieldResponse:
    return await use_case.execute(field_id)
