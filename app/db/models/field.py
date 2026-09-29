import uuid
from datetime import datetime

from geoalchemy2 import Geography, Geometry, WKBElement
from sqlalchemy import Computed, DateTime, Double, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base

WGS84_SRID = 4326


class Field(Base):
    __tablename__ = "field"
    __table_args__ = (Index("idx_field__geometry", "geometry", postgresql_using="gist"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=WGS84_SRID, spatial_index=False)
    )
    area_ha: Mapped[float] = mapped_column(
        Double, Computed("ST_Area(geometry::geography) / 10000", persisted=True), index=True
    )
    centroid: Mapped[WKBElement] = mapped_column(
        Geography(geometry_type="POINT", srid=WGS84_SRID, spatial_index=False),
        Computed("ST_Centroid(geometry)::geography", persisted=True),
    )
    crop: Mapped[str] = mapped_column(String(255), index=True)
    owner: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
