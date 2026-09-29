import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.schemas.geometry import Latitude, Longitude, Polygon
from app.utils.geo import polygon_area_hectares

MIN_FIELD_AREA_HECTARES = 0.1
AREA_DECIMAL_PLACES = 4
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
DISTANCE_DECIMAL_PLACES = 1
QUERY_TIME_DECIMAL_PLACES = 2

NonEmptyString = Annotated[str, Field(min_length=1, max_length=255)]


class FieldCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: NonEmptyString
    geometry: Polygon
    crop: NonEmptyString
    owner: NonEmptyString

    @field_validator("geometry")
    @classmethod
    def validate_min_area(cls, geometry: Polygon) -> Polygon:
        area_hectares = polygon_area_hectares(geometry.coordinates)
        if area_hectares < MIN_FIELD_AREA_HECTARES:
            raise ValueError(
                f"field area {area_hectares:.4f} ha is below the minimum of {MIN_FIELD_AREA_HECTARES} ha"
            )
        return geometry


class FieldResponse(BaseModel):
    id: uuid.UUID
    name: str
    geometry: Polygon
    area_ha: float
    crop: str
    owner: str
    created_at: datetime

    @field_serializer("area_ha")
    def round_area(self, area_ha: float) -> float:
        return round(area_ha, AREA_DECIMAL_PLACES)


class FieldListQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    crop: NonEmptyString | None = None
    owner: NonEmptyString | None = None
    min_area: Annotated[float, Field(ge=0)] | None = None
    max_area: Annotated[float, Field(ge=0)] | None = None
    limit: Annotated[int, Field(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT
    offset: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def validate_area_range(self) -> "FieldListQuery":
        if self.min_area is not None and self.max_area is not None and self.min_area > self.max_area:
            raise ValueError("min_area must be less than or equal to max_area")
        return self


class FieldListItem(BaseModel):
    id: uuid.UUID
    name: str
    area_ha: float
    crop: str
    owner: str

    @field_serializer("area_ha")
    def round_area(self, area_ha: float) -> float:
        return round(area_ha, AREA_DECIMAL_PLACES)


class FieldListResponse(BaseModel):
    total: int
    fields: list[FieldListItem]


class Point(BaseModel):
    lon: Longitude
    lat: Latitude


class FindByPointQuery(Point):
    model_config = ConfigDict(extra="forbid")


class FieldWithDistance(FieldListItem):
    distance_to_center_m: float

    @field_serializer("distance_to_center_m")
    def round_distance(self, distance_to_center_m: float) -> float:
        return round(distance_to_center_m, DISTANCE_DECIMAL_PLACES)


class FindByPointResponse(BaseModel):
    query_point: Point
    fields: list[FieldWithDistance]
    query_time_ms: float

    @field_serializer("query_time_ms")
    def round_query_time(self, query_time_ms: float) -> float:
        return round(query_time_ms, QUERY_TIME_DECIMAL_PLACES)
