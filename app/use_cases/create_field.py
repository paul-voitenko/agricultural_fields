from app.schemas.field import FieldCreate, FieldResponse
from app.services.field_service import FieldService


class CreateFieldUseCase:
    def __init__(self, field_service: FieldService) -> None:
        self._field_service = field_service

    async def execute(self, field_create: FieldCreate) -> FieldResponse:
        return await self._field_service.create(field_create)
