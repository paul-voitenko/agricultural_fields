import uuid

from geoalchemy2 import Geography
from sqlalchemy import ColumnElement, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.db.models import Field
from app.db.models.field import WGS84_SRID


class FieldRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, field: Field) -> Field:
        self._session.add(field)
        await self._session.commit()
        await self._session.refresh(field)
        return field

    async def get(self, field_id: uuid.UUID) -> Field | None:
        return await self._session.get(Field, field_id)

    async def create_many(self, fields: list[Field]) -> int:
        self._session.add_all(fields)
        await self._session.commit()
        return len(fields)

    async def find_filtered(
        self,
        *,
        crop: str | None,
        owner: str | None,
        min_area: float | None,
        max_area: float | None,
        limit: int,
        offset: int,
    ) -> tuple[int, list[Field]]:
        conditions: list[ColumnElement[bool]] = []
        if crop is not None:
            conditions.append(Field.crop == crop)
        if owner is not None:
            conditions.append(Field.owner == owner)
        if min_area is not None:
            conditions.append(Field.area_ha >= min_area)
        if max_area is not None:
            conditions.append(Field.area_ha <= max_area)

        total = await self._session.scalar(select(func.count()).select_from(Field).where(*conditions))
        fields = await self._session.scalars(
            select(Field)
            .options(load_only(Field.id, Field.name, Field.area_ha, Field.crop, Field.owner))
            .where(*conditions)
            .order_by(Field.created_at.desc(), Field.id)
            .limit(limit)
            .offset(offset)
        )
        return total, list(fields)

    async def find_covering_point(self, *, lon: float, lat: float) -> list[tuple[Field, float]]:
        """Fields whose polygon covers the point (boundary included), nearest centroid first."""
        point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), WGS84_SRID)
        distance_to_center = func.ST_Distance(Field.centroid, cast(point, Geography)).label("distance_to_center_m")
        rows = await self._session.execute(
            select(Field, distance_to_center)
            .options(load_only(Field.id, Field.name, Field.area_ha, Field.crop, Field.owner))
            .where(func.ST_Covers(Field.geometry, point))
            .order_by(distance_to_center, Field.id)
        )
        return [(field, distance) for field, distance in rows]
