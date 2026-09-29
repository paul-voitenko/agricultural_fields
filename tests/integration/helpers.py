import math

METERS_PER_DEGREE_LATITUDE = 111_320

Position = list[float]
Ring = list[Position]


def square_ring(lon: float, lat: float, side_meters: float) -> Ring:
    """Closed square ring centered on (lon, lat) with the given side length."""
    half_lat = side_meters / 2 / METERS_PER_DEGREE_LATITUDE
    half_lon = side_meters / 2 / (METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(lat)))
    return [
        [lon - half_lon, lat - half_lat],
        [lon + half_lon, lat - half_lat],
        [lon + half_lon, lat + half_lat],
        [lon - half_lon, lat + half_lat],
        [lon - half_lon, lat - half_lat],
    ]


def field_payload(
    *rings: Ring, name: str = "Поле №1", crop: str = "Пшениця", owner: str = "Іванов І.І."
) -> dict:
    return {"name": name, "geometry": {"type": "Polygon", "coordinates": list(rings)}, "crop": crop, "owner": owner}
