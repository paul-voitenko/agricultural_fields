from collections.abc import Sequence

from pyproj import Geod

SQUARE_METERS_PER_HECTARE = 10_000

# Karney's geodesic algorithm on WGS 84, the same one PostGIS uses for ST_Area(geography).
WGS84_GEOD = Geod(ellps="WGS84")

Ring = Sequence[Sequence[float]]


def ring_area_square_meters(ring: Ring) -> float:
    """Unsigned geodesic area of a closed lon/lat ring on the WGS 84 ellipsoid."""
    longitudes, latitudes = zip(*ring)
    area, _ = WGS84_GEOD.polygon_area_perimeter(longitudes, latitudes)
    return abs(area)


def polygon_area_hectares(rings: Sequence[Ring]) -> float:
    """Area of a GeoJSON polygon's coordinates: exterior ring minus holes.

    Each ring's area is taken unsigned, so holes are subtracted whichever way they are drawn.
    Geod.geometry_area_perimeter sums signed ring areas instead, and would add a hole drawn in the same direction.
    """
    exterior, *holes = rings
    area = ring_area_square_meters(exterior) - sum(ring_area_square_meters(hole) for hole in holes)
    return area / SQUARE_METERS_PER_HECTARE
