from app.schemas.field import FieldListQuery, FieldListResponse
from app.services.field_service import FieldService


class ListFieldsUseCase:
    def __init__(self, field_service: FieldService) -> None:
        self._field_service = field_service

    async def execute(self, query: FieldListQuery) -> FieldListResponse:
        return await self._field_service.list_fields(query)
