from collections.abc import Callable

import pytest
from httpx import AsyncClient

from tests.integration.helpers import square_ring

# name -> (side in meters, crop, owner); areas are ~4, ~25, ~100 and ~400 ha.
FIELDS = {
    "Мале": (200, "Пшениця", "Іванов І.І."),
    "Середнє": (500, "Кукурудза", "Іванов І.І."),
    "Велике": (1000, "Пшениця", "ТОВ «Колос»"),
    "Величезне": (2000, "Соняшник", "ТОВ «Колос»"),
}


@pytest.fixture
async def fields(create_field: Callable) -> dict[str, dict]:
    created = {}
    for index, (name, (side_meters, crop, owner)) in enumerate(FIELDS.items()):
        ring = square_ring(30 + index * 0.1, 50, side_meters)
        created[name] = await create_field(ring, name=name, crop=crop, owner=owner)
    return created


def _names(body: dict) -> set[str]:
    return {field["name"] for field in body["fields"]}


@pytest.mark.parametrize(
    ("params", "expected_names"),
    [
        pytest.param({}, set(FIELDS), id="no-filters"),
        pytest.param({"crop": "Пшениця"}, {"Мале", "Велике"}, id="crop"),
        pytest.param({"owner": "ТОВ «Колос»"}, {"Велике", "Величезне"}, id="owner"),
        pytest.param({"min_area": 50}, {"Велике", "Величезне"}, id="min-area"),
        pytest.param({"max_area": 50}, {"Мале", "Середнє"}, id="max-area"),
        pytest.param({"min_area": 10, "max_area": 200}, {"Середнє", "Велике"}, id="area-range"),
        pytest.param({"crop": "Пшениця", "owner": "Іванов І.І."}, {"Мале"}, id="crop-and-owner"),
        pytest.param({"crop": "пшениця"}, set(), id="crop-is-case-sensitive"),
        pytest.param({"crop": "Ячмінь"}, set(), id="no-match"),
    ],
)
async def test_list_fields_filters(
    client: AsyncClient, fields: dict[str, dict], params: dict, expected_names: set[str]
) -> None:
    response = await client.get("/api/fields", params=params)

    assert response.status_code == 200
    body = response.json()
    assert _names(body) == expected_names
    assert body["total"] == len(expected_names)


async def test_list_fields_item_shape(client: AsyncClient, fields: dict[str, dict]) -> None:
    item = (await client.get("/api/fields", params={"crop": "Соняшник"})).json()["fields"][0]

    assert set(item) == {"id", "name", "area_ha", "crop", "owner"}
    assert item["id"] == fields["Величезне"]["id"]
    assert item["area_ha"] == pytest.approx(400, rel=0.01)


async def test_list_fields_paginates_newest_first(client: AsyncClient, fields: dict[str, dict]) -> None:
    newest_first = list(reversed(FIELDS))

    first_page = (await client.get("/api/fields", params={"limit": 2})).json()
    second_page = (await client.get("/api/fields", params={"limit": 2, "offset": 2})).json()
    past_end = (await client.get("/api/fields", params={"offset": 10})).json()

    assert [f["name"] for f in first_page["fields"]] == newest_first[:2]
    assert [f["name"] for f in second_page["fields"]] == newest_first[2:]
    assert first_page["total"] == second_page["total"] == past_end["total"] == 4
    assert past_end["fields"] == []


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"min_area": 10, "max_area": 5}, id="min-above-max"),
        pytest.param({"min_area": -1}, id="negative-area"),
        pytest.param({"limit": 0}, id="limit-zero"),
        pytest.param({"limit": 101}, id="limit-above-max"),
        pytest.param({"offset": -1}, id="negative-offset"),
        pytest.param({"min_aera": 10}, id="unknown-param"),
    ],
)
async def test_list_fields_rejects_invalid_params(client: AsyncClient, params: dict) -> None:
    response = await client.get("/api/fields", params=params)

    assert response.status_code == 422
