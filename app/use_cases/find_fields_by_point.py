from app.schemas.field import FindByPointQuery, FindByPointResponse
from app.services.field_service import FieldService


class FindFieldsByPointUseCase:
    def __init__(self, field_service: FieldService) -> None:
        self._field_service = field_service

    async def execute(self, query: FindByPointQuery) -> FindByPointResponse:
        return await self._field_service.find_by_point(query)
