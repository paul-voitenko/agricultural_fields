import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient

from tests.integration.helpers import square_ring

LON, LAT = 30.5, 50.45


async def test_get_field_returns_full_details(client: AsyncClient, create_field: Callable) -> None:
    created = await create_field(square_ring(LON, LAT, 1000), square_ring(LON, LAT, 200), name="Зі ставком")
    await create_field(square_ring(LON + 0.1, LAT, 500), name="Інше")

    response = await client.get(f"/api/fields/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_get_field_returns_geometry_with_holes(client: AsyncClient, create_field: Callable) -> None:
    exterior, hole = square_ring(LON, LAT, 1000), square_ring(LON, LAT, 200)
    created = await create_field(exterior, hole)

    geometry = (await client.get(f"/api/fields/{created['id']}")).json()["geometry"]

    assert geometry == {"type": "Polygon", "coordinates": [exterior, hole]}


async def test_get_field_unknown_id_returns_404(client: AsyncClient) -> None:
    field_id = uuid.uuid4()

    response = await client.get(f"/api/fields/{field_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": f"field {field_id} not found"}


@pytest.mark.parametrize("field_id", ["not-a-uuid", "123", "0c6e688a-2878-4754-abe1"])
async def test_get_field_invalid_id_returns_422(client: AsyncClient, field_id: str) -> None:
    response = await client.get(f"/api/fields/{field_id}")

    assert response.status_code == 422


async def test_find_by_point_is_not_treated_as_id(client: AsyncClient, create_field: Callable) -> None:
    await create_field(square_ring(LON, LAT, 500))

    response = await client.get("/api/fields/find-by-point", params={"lon": LON, "lat": LAT})

    assert response.status_code == 200
    assert len(response.json()["fields"]) == 1
