import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient

from tests.integration.helpers import field_payload, square_ring

SPEC_RING = [[30.5234, 50.4501], [30.5334, 50.4501], [30.5334, 50.4601], [30.5234, 50.4601], [30.5234, 50.4501]]
SPEC_AREA_HECTARES = 78.9974


async def test_create_field_returns_saved_field(client: AsyncClient) -> None:
    payload = field_payload(SPEC_RING, name="Поле №1 - Пшениця")

    response = await client.post("/api/fields", json=payload)

    assert response.status_code == 201
    body = response.json()
    uuid.UUID(body["id"])
    assert body["name"] == "Поле №1 - Пшениця"
    assert body["crop"] == payload["crop"]
    assert body["owner"] == payload["owner"]
    assert body["geometry"] == payload["geometry"]
    assert body["area_ha"] == pytest.approx(SPEC_AREA_HECTARES, abs=0.001)
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None

    listed = (await client.get("/api/fields")).json()
    assert listed["total"] == 1
    assert listed["fields"][0]["id"] == body["id"]


async def test_create_field_strips_whitespace(client: AsyncClient) -> None:
    response = await client.post("/api/fields", json=field_payload(SPEC_RING, name="  Поле  ", crop=" Соя "))

    assert response.status_code == 201
    assert response.json()["name"] == "Поле"
    assert response.json()["crop"] == "Соя"


def _payload_with(**overrides: object) -> dict:
    return {**field_payload(SPEC_RING), **overrides}


def _polygon(*rings: list) -> dict:
    return {"type": "Polygon", "coordinates": list(rings)}


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        pytest.param(
            _payload_with(geometry=_polygon(SPEC_RING[:-1])), "is not closed", id="unclosed-ring"
        ),
        pytest.param(
            _payload_with(geometry=_polygon([[30.5, 50.4], [30.6, 50.5], [30.6, 50.4], [30.5, 50.5], [30.5, 50.4]])),
            "Self-intersection",
            id="self-intersection",
        ),
        pytest.param(
            _payload_with(geometry=_polygon(square_ring(30.5, 50.45, 20))),
            "below the minimum",
            id="below-min-area",
        ),
        pytest.param(
            _payload_with(geometry=_polygon(SPEC_RING, square_ring(31.5, 50.45, 50))),
            "Hole lies outside shell",
            id="hole-outside-shell",
        ),
        pytest.param(
            _payload_with(geometry=_polygon([[30.5, 50.4], [30.6, 50.4], [30.5, 50.4]])),
            "at least 4 items",
            id="too-few-positions",
        ),
        pytest.param(
            _payload_with(geometry={"type": "Point", "coordinates": [30.5, 50.4]}), "'Polygon'", id="not-polygon"
        ),
        pytest.param(
            _payload_with(geometry=_polygon([[30.5, 91], [30.6, 91], [30.6, 50.5], [30.5, 91]])),
            "less than or equal to 90",
            id="latitude-out-of-range",
        ),
        pytest.param(_payload_with(name="   "), "at least 1 character", id="blank-name"),
        pytest.param(
            {k: v for k, v in field_payload(SPEC_RING).items() if k != "owner"}, "Field required", id="no-owner"
        ),
    ],
)
async def test_create_field_rejects_invalid_input(client: AsyncClient, payload: dict, expected_message: str) -> None:
    response = await client.post("/api/fields", json=payload)

    assert response.status_code == 422
    assert expected_message in response.text
    assert (await client.get("/api/fields")).json()["total"] == 0


def _degree_square(lon: float, lat: float, side_degrees: float) -> list[list[float]]:
    return [
        [lon, lat],
        [lon + side_degrees, lat],
        [lon + side_degrees, lat + side_degrees],
        [lon, lat + side_degrees],
        [lon, lat],
    ]


async def test_min_area_is_checked_on_the_ellipsoid(client: AsyncClient) -> None:
    # ~0.09998 ha on the WGS 84 ellipsoid, but ~0.1004 ha on a sphere, which a spherical check would accept.
    response = await client.post("/api/fields", json=field_payload(_degree_square(0, 0, 0.000285)))

    assert response.status_code == 422
    assert "below the minimum" in response.text


async def test_accepted_field_is_never_stored_below_min_area(client: AsyncClient) -> None:
    response = await client.post("/api/fields", json=field_payload(_degree_square(0, 0, 0.000286)))

    assert response.status_code == 201
    assert 0.1 <= response.json()["area_ha"] < 0.101


async def test_hole_drawn_in_same_direction_is_subtracted(client: AsyncClient) -> None:
    # 0.15 ha exterior minus a 0.1 ha hole, both counter-clockwise: 0.05 ha net, below the minimum.
    exterior, hole = square_ring(30.5, 50.45, 38.73), square_ring(30.5, 50.45, 31.62)

    response = await client.post("/api/fields", json=field_payload(exterior, hole))

    assert response.status_code == 422
    assert "field area 0.05" in response.text
