from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from shapely.geometry import shape
from shapely.validation import explain_validity

MIN_RING_POSITIONS = 4

Longitude = Annotated[float, Field(ge=-180, le=180)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Position = tuple[Longitude, Latitude]
LinearRing = Annotated[list[Position], Field(min_length=MIN_RING_POSITIONS)]


class Polygon(BaseModel):
    """GeoJSON Polygon (RFC 7946): first ring is the exterior, the rest are holes."""

    type: Literal["Polygon"]
    coordinates: Annotated[list[LinearRing], Field(min_length=1)]

    @field_validator("coordinates")
    @classmethod
    def validate_rings_closed(cls, coordinates: list[list[Position]]) -> list[list[Position]]:
        for index, ring in enumerate(coordinates):
            if ring[0] != ring[-1]:
                raise ValueError(f"ring {index} is not closed: first and last positions must be equal")
        return coordinates

    @model_validator(mode="after")
    def validate_topology(self) -> "Polygon":
        geometry = shape(self.model_dump())
        if not geometry.is_valid:
            raise ValueError(f"invalid polygon geometry: {explain_validity(geometry)}")
        return self
