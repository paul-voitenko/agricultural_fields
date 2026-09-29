import time
import uuid

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import mapping, shape

from app.core.errors import FieldNotFoundError
from app.db.models import Field
from app.db.models.field import WGS84_SRID
from app.db.repositories.field_repository import FieldRepository
from app.schemas.field import (
    FieldCreate,
    FieldListItem,
    FieldListQuery,
    FieldListResponse,
    FieldResponse,
    FieldWithDistance,
    FindByPointQuery,
    FindByPointResponse,
    Point,
)
from app.schemas.geometry import Polygon


class FieldService:
    def __init__(self, field_repository: FieldRepository) -> None:
        self._field_repository = field_repository

    async def create(self, field_create: FieldCreate) -> FieldResponse:
        field = await self._field_repository.create(self._to_model(field_create))
        return self._to_response(field)

    async def get(self, field_id: uuid.UUID) -> FieldResponse:
        field = await self._field_repository.get(field_id)
        if field is None:
            raise FieldNotFoundError(field_id)
        return self._to_response(field)

    async def create_many(self, field_creates: list[FieldCreate]) -> int:
        return await self._field_repository.create_many([self._to_model(f) for f in field_creates])

    async def list_fields(self, query: FieldListQuery) -> FieldListResponse:
        total, fields = await self._field_repository.find_filtered(
            crop=query.crop,
            owner=query.owner,
            min_area=query.min_area,
            max_area=query.max_area,
            limit=query.limit,
            offset=query.offset,
        )
        return FieldListResponse(
            total=total,
            fields=[
                FieldListItem(id=f.id, name=f.name, area_ha=f.area_ha, crop=f.crop, owner=f.owner) for f in fields
            ],
        )

    async def find_by_point(self, query: FindByPointQuery) -> FindByPointResponse:
        started_at = time.perf_counter()
        rows = await self._field_repository.find_covering_point(lon=query.lon, lat=query.lat)
        query_time_ms = (time.perf_counter() - started_at) * 1000
        return FindByPointResponse(
            query_point=Point(lon=query.lon, lat=query.lat),
            fields=[
                FieldWithDistance(
                    id=f.id,
                    name=f.name,
                    area_ha=f.area_ha,
                    crop=f.crop,
                    owner=f.owner,
                    distance_to_center_m=distance,
                )
                for f, distance in rows
            ],
            query_time_ms=query_time_ms,
        )

    @staticmethod
    def _to_model(field_create: FieldCreate) -> Field:
        return Field(
            name=field_create.name,
            geometry=from_shape(shape(field_create.geometry.model_dump()), srid=WGS84_SRID),
            crop=field_create.crop,
            owner=field_create.owner,
        )

    @staticmethod
    def _to_response(field: Field) -> FieldResponse:
        return FieldResponse(
            id=field.id,
            name=field.name,
            geometry=Polygon.model_validate(mapping(to_shape(field.geometry))),
            area_ha=field.area_ha,
            crop=field.crop,
            owner=field.owner,
            created_at=field.created_at,
        )
