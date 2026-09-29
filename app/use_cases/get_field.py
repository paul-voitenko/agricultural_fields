import uuid

from app.schemas.field import FieldResponse
from app.services.field_service import FieldService


class GetFieldUseCase:
    def __init__(self, field_service: FieldService) -> None:
        self._field_service = field_service

    async def execute(self, field_id: uuid.UUID) -> FieldResponse:
        return await self._field_service.get(field_id)
