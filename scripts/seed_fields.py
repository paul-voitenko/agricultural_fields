"""Seed the `field` table with synthetic but realistic agricultural fields across Ukraine.

Usage:
    docker compose run --rm seed [--count 1000] [--seed 42] [--reset]
    uv run python -m scripts.seed_fields [...]   # from the host, against localhost:5433
"""

import argparse
import asyncio
import math
import random
from dataclasses import dataclass

from pydantic import ValidationError
from shapely import affinity
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import mapping
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.core.db import create_db_engine
from app.db.models import Field
from app.db.repositories.field_repository import FieldRepository
from app.schemas.field import FieldCreate
from app.services.field_service import FieldService

METERS_PER_DEGREE_LATITUDE = 111_320
SQUARE_METERS_PER_HECTARE = 10_000
MEDIAN_FIELD_AREA_HECTARES = 40
MIN_SEED_AREA_HECTARES = 1
MAX_SEED_AREA_HECTARES = 400
REGION_SPREAD_DEGREES = 0.35
OVERLAP_PROBABILITY = 0.12
MAX_ATTEMPTS_PER_FIELD = 20
INSERT_BATCH_SIZE = 5000

# Agricultural hubs (lat, lon) away from borders and the coast, so scattered fields stay on land in Ukraine.
REGION_CENTERS = {
    "Київська": (50.20, 30.60),
    "Житомирська": (50.25, 28.66),
    "Вінницька": (49.23, 28.47),
    "Хмельницька": (49.42, 26.99),
    "Тернопільська": (49.55, 25.59),
    "Черкаська": (49.44, 32.06),
    "Полтавська": (49.59, 34.55),
    "Кіровоградська": (48.51, 32.26),
    "Дніпропетровська": (48.46, 35.04),
    "Харківська": (49.70, 36.00),
    "Сумська": (50.75, 34.40),
    "Чернігівська": (51.20, 31.60),
    "Миколаївська": (47.40, 31.90),
    "Одеська": (47.00, 30.20),
}

# Rough share of Ukrainian sown area.
CROP_WEIGHTS = {
    "Пшениця озима": 22,
    "Кукурудза": 18,
    "Соняшник": 20,
    "Ячмінь": 8,
    "Соя": 7,
    "Ріпак": 6,
    "Цукровий буряк": 3,
    "Овес": 2,
    "Жито": 2,
    "Гречка": 2,
    "Горох": 3,
}

LAST_NAMES = [
    "Іваненко", "Петренко", "Коваленко", "Бондаренко", "Шевченко", "Ткаченко", "Кравченко", "Олійник",
    "Мельник", "Шевчук", "Бойко", "Коваль", "Поліщук", "Лисенко", "Марченко", "Савченко", "Руденко",
    "Мороз", "Гончаренко", "Сидоренко",
]
INITIALS = "АБВГДЄІКЛМОПРСТЮЯ"
COMPANY_NAMES = [
    "Агро-Світанок", "Колос", "Золотий Лан", "Нива Поділля", "Степовик", "Зерноград", "Дніпро-Агро",
    "Врожай Плюс", "Слобожанщина", "Полісся Агро", "Чорнозем", "Хлібороб",
]
COMPANY_FORMS = ["ТОВ", "ФГ", "ПСП", "СТОВ"]


@dataclass(frozen=True)
class PlacedField:
    lat: float
    lon: float
    size_meters: float


def build_owners(rng: random.Random) -> list[str]:
    people = {f"{rng.choice(LAST_NAMES)} {rng.choice(INITIALS)}.{rng.choice(INITIALS)}." for _ in range(40)}
    companies = {f"{rng.choice(COMPANY_FORMS)} «{name}»" for name in COMPANY_NAMES}
    return sorted(people | companies)


def rectangle(rng: random.Random) -> ShapelyPolygon:
    aspect = rng.uniform(1, 4)
    return ShapelyPolygon([(0, 0), (aspect, 0), (aspect, 1), (0, 1)])


def trapezoid(rng: random.Random) -> ShapelyPolygon:
    top_shift, top_width = rng.uniform(-0.4, 0.4), rng.uniform(0.5, 1.2)
    return ShapelyPolygon([(0, 0), (1.5, 0), (top_shift + top_width, 1), (top_shift, 1)])


def irregular(rng: random.Random) -> ShapelyPolygon:
    vertex_count = rng.randint(5, 10)
    angles = sorted(rng.uniform(0, 2 * math.pi) for _ in range(vertex_count))
    return ShapelyPolygon([(math.cos(a) * rng.uniform(0.7, 1), math.sin(a) * rng.uniform(0.7, 1)) for a in angles])


def l_shape(rng: random.Random) -> ShapelyPolygon:
    width, height = rng.uniform(1.5, 3), rng.uniform(1.5, 3)
    cut_x, cut_y = rng.uniform(0.3, 0.7) * width, rng.uniform(0.3, 0.7) * height
    return ShapelyPolygon([(0, 0), (width, 0), (width, cut_y), (cut_x, cut_y), (cut_x, height), (0, height)])


def with_hole(rng: random.Random) -> ShapelyPolygon:
    """A field around a pond or tree belt."""
    outer = rectangle(rng)
    min_x, min_y, max_x, max_y = outer.bounds
    center_x, center_y = rng.uniform(0.35, 0.65) * max_x, rng.uniform(0.35, 0.65) * max_y
    radius = rng.uniform(0.08, 0.2) * min(max_x - min_x, max_y - min_y)
    angles = [i * math.pi / 6 for i in range(12)]
    hole = [(center_x + math.cos(a) * radius, center_y + math.sin(a) * radius) for a in angles]
    return ShapelyPolygon(outer.exterior.coords, [hole])


SHAPE_WEIGHTS = {rectangle: 40, trapezoid: 20, irregular: 25, l_shape: 10, with_hole: 5}


def to_lon_lat(polygon_meters: ShapelyPolygon, lat: float, lon: float) -> ShapelyPolygon:
    meters_per_degree_longitude = METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(lat))
    return affinity.affine_transform(
        polygon_meters, [1 / meters_per_degree_longitude, 0, 0, 1 / METERS_PER_DEGREE_LATITUDE, lon, lat]
    )


def pick_location(rng: random.Random, placed: list[PlacedField]) -> tuple[float, float]:
    if placed and rng.random() < OVERLAP_PROBABILITY:
        # Shift off an existing field's center by less than its size, so the two polygons overlap.
        anchor = rng.choice(placed)
        distance, bearing = rng.uniform(0.2, 0.5) * anchor.size_meters, rng.uniform(0, 2 * math.pi)
        lat = anchor.lat + distance * math.sin(bearing) / METERS_PER_DEGREE_LATITUDE
        lon = anchor.lon + distance * math.cos(bearing) / (METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(lat)))
        return lat, lon
    center_lat, center_lon = rng.choice(list(REGION_CENTERS.values()))
    return (
        center_lat + rng.uniform(-REGION_SPREAD_DEGREES, REGION_SPREAD_DEGREES),
        center_lon + rng.uniform(-REGION_SPREAD_DEGREES, REGION_SPREAD_DEGREES),
    )


def generate_field(rng: random.Random, number: int, owners: list[str], placed: list[PlacedField]) -> FieldCreate:
    for _ in range(MAX_ATTEMPTS_PER_FIELD):
        area_hectares = min(
            max(rng.lognormvariate(math.log(MEDIAN_FIELD_AREA_HECTARES), 0.9), MIN_SEED_AREA_HECTARES),
            MAX_SEED_AREA_HECTARES,
        )
        make_shape = rng.choices(list(SHAPE_WEIGHTS), weights=list(SHAPE_WEIGHTS.values()))[0]
        polygon = make_shape(rng)
        polygon = affinity.scale(polygon, *(2 * [math.sqrt(area_hectares * SQUARE_METERS_PER_HECTARE / polygon.area)]))
        polygon = affinity.rotate(polygon, rng.uniform(0, 180), origin="centroid")
        polygon = affinity.translate(polygon, -polygon.centroid.x, -polygon.centroid.y)

        lat, lon = pick_location(rng, placed)
        crop = rng.choices(list(CROP_WEIGHTS), weights=list(CROP_WEIGHTS.values()))[0]
        try:
            field = FieldCreate.model_validate(
                {
                    "name": f"Поле №{number} - {crop}",
                    "geometry": mapping(to_lon_lat(polygon, lat, lon)),
                    "crop": crop,
                    "owner": rng.choice(owners),
                }
            )
        except ValidationError:
            continue
        placed.append(PlacedField(lat=lat, lon=lon, size_meters=math.sqrt(polygon.area)))
        return field
    raise RuntimeError(f"could not generate a valid field #{number} in {MAX_ATTEMPTS_PER_FIELD} attempts")


async def delete_all_fields(session: AsyncSession) -> int:
    result = await session.execute(delete(Field))
    await session.commit()
    return result.rowcount


async def count_overlapping_pairs(session: AsyncSession) -> int:
    """Pairs of fields whose interiors overlap (touching edges only are not counted)."""
    other = aliased(Field)
    return await session.scalar(
        select(func.count())
        .select_from(Field)
        .join(other, Field.id < other.id)
        .where(func.ST_Overlaps(Field.geometry, other.geometry))
    )


async def analyze_fields(session: AsyncSession) -> None:
    """Refresh planner statistics after the bulk load, so the first queries already get good plans."""
    await session.execute(text("ANALYZE field"))
    await session.commit()


async def seed(count: int, seed_value: int, reset: bool) -> None:
    rng = random.Random(seed_value)
    owners = build_owners(rng)
    placed: list[PlacedField] = []

    engine = create_db_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            service = FieldService(FieldRepository(session))
            if reset:
                print(f"deleted {await delete_all_fields(session)} existing fields")
            created = 0
            for batch_start in range(1, count + 1, INSERT_BATCH_SIZE):
                batch_end = min(batch_start + INSERT_BATCH_SIZE, count + 1)
                batch = [generate_field(rng, number, owners, placed) for number in range(batch_start, batch_end)]
                created += await service.create_many(batch)
                session.expunge_all()
                if count > INSERT_BATCH_SIZE:
                    print(f"  inserted {created}/{count}")
            await analyze_fields(session)
            print(f"created {created} fields for {len(owners)} owners")
            print(f"overlapping field pairs in table: {await count_overlapping_pairs(session)}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42, help="random seed, same value -> same fields")
    parser.add_argument("--reset", action="store_true", help="delete ALL existing fields before seeding")
    args = parser.parse_args()
    asyncio.run(seed(args.count, args.seed, args.reset))


if __name__ == "__main__":
    main()
