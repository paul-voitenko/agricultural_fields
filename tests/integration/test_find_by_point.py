import math
from collections.abc import Callable

import pytest
from httpx import AsyncClient

from tests.integration.helpers import METERS_PER_DEGREE_LATITUDE, square_ring

LON, LAT = 30.5, 50.45
SHIFT_METERS = 300


def _meters_to_lon(meters: float, lat: float = LAT) -> float:
    return meters / (METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(lat)))


async def _find(client: AsyncClient, lon: float, lat: float) -> dict:
    response = await client.get("/api/fields/find-by-point", params={"lon": lon, "lat": lat})
    assert response.status_code == 200, response.text
    return response.json()


async def test_point_outside_all_fields(client: AsyncClient, create_field: Callable) -> None:
    await create_field(square_ring(LON, LAT, 500))

    body = await _find(client, 24.03, 49.84)

    assert body["fields"] == []
    assert body["query_point"] == {"lon": 24.03, "lat": 49.84}
    assert body["query_time_ms"] >= 0


async def test_point_in_single_field(client: AsyncClient, create_field: Callable) -> None:
    field = await create_field(square_ring(LON, LAT, 500), name="Одне")
    await create_field(square_ring(LON + 0.1, LAT, 500), name="Далеке")

    body = await _find(client, LON, LAT)

    assert [f["id"] for f in body["fields"]] == [field["id"]]
    found = body["fields"][0]
    assert set(found) == {"id", "name", "area_ha", "crop", "owner", "distance_to_center_m"}
    assert found["area_ha"] == pytest.approx(field["area_ha"], abs=0.0001)
    assert found["distance_to_center_m"] == pytest.approx(0, abs=0.5)


async def test_point_in_overlapping_fields_sorted_by_distance(client: AsyncClient, create_field: Callable) -> None:
    shifted = await create_field(square_ring(LON + _meters_to_lon(SHIFT_METERS), LAT, 1000), name="Зсунуте")
    centered = await create_field(square_ring(LON, LAT, 1000), name="Центральне")

    body = await _find(client, LON, LAT)

    assert [f["id"] for f in body["fields"]] == [centered["id"], shifted["id"]]
    assert body["fields"][0]["distance_to_center_m"] == pytest.approx(0, abs=0.5)
    assert body["fields"][1]["distance_to_center_m"] == pytest.approx(SHIFT_METERS, rel=0.01)


async def test_point_in_hole_is_not_in_field(client: AsyncClient, create_field: Callable) -> None:
    field = await create_field(square_ring(LON, LAT, 1000), square_ring(LON, LAT, 200), name="Зі ставком")

    in_hole = await _find(client, LON, LAT)
    beside_hole = await _find(client, LON + _meters_to_lon(300), LAT)

    assert in_hole["fields"] == []
    assert [f["id"] for f in beside_hole["fields"]] == [field["id"]]


async def test_point_on_boundary_is_in_field(client: AsyncClient, create_field: Callable) -> None:
    ring = square_ring(LON, LAT, 500)
    field = await create_field(ring)
    west_edge_lon = ring[0][0]

    body = await _find(client, west_edge_lon, LAT)

    assert [f["id"] for f in body["fields"]] == [field["id"]]


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"lon": LON}, id="missing-lat"),
        pytest.param({"lat": LAT}, id="missing-lon"),
        pytest.param({"lon": 181, "lat": LAT}, id="lon-out-of-range"),
        pytest.param({"lon": LON, "lat": -91}, id="lat-out-of-range"),
        pytest.param({"lon": "abc", "lat": LAT}, id="not-a-number"),
    ],
)
async def test_find_by_point_rejects_invalid_params(client: AsyncClient, params: dict) -> None:
    response = await client.get("/api/fields/find-by-point", params=params)

    assert response.status_code == 422
