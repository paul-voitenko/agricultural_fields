# Agricultural Fields API

A FastAPI + PostGIS service for storing agricultural fields (GeoJSON polygons) and finding the fields that contain a given point.

## Quick start

**Requirements:** Docker with Compose v2. To run the app or tests outside Docker, you also need [uv](https://docs.astral.sh/uv/).

```bash
# 1. Start PostGIS, apply migrations, start the API
docker compose up -d --build

# 2. Load 1000 realistic demo fields across Ukraine (deterministic, seed 42)
docker compose run --rm seed --reset

# 3. Try it
curl "http://localhost:8000/api/fields/find-by-point?lon=31.466513&lat=50.990566"
```

- API: <http://localhost:8000>, Swagger UI: <http://localhost:8000/docs>
- PostgreSQL: `localhost:5433`, user/password `postgres`/`postgres`, database `agricultural_fields`
- Ready-made requests with expected results: [`requests/find_by_point.http`](requests/find_by_point.http) (VS Code REST Client / JetBrains HTTP Client). They assume the default seed data.

### Compose services

| Service | Starts on `up` | Purpose |
|---|---|---|
| `db` | yes | PostGIS 16-3.4, data kept in the `db-data` volume |
| `migrate` | yes | Runs `alembic upgrade head` and exits; `app` starts only if it succeeds |
| `app` | yes | Uvicorn with `--reload`; `./app` is mounted, so code changes apply live |
| `seed` | no (profile `seed`) | `docker compose run --rm seed [--count N] [--seed N] [--reset]`. `--reset` deletes **all** fields first |
| `tests` | no (profile `test`) | `docker compose run --rm tests [pytest args]` |

Performance tests use a separate stack, see [Performance tests](#performance-tests).

### Tests

Integration tests start their own throwaway PostGIS container (testcontainers), so your dev database is never touched. Docker must be running.

```bash
docker compose run --rm tests          # inside Docker (mounts the Docker socket)
uv run pytest                          # or on the host
uv run pytest -k find_by_point -q      # any pytest arguments work
```

### Performance tests

A separate, isolated stack (`docker-compose.perf.yml`, project `agricultural-fields-perf`, own DB volume) seeds 50 000 fields, runs a [Locust](https://locust.io) load test (Python) against the app with **CPU/memory limits on `db` and `app`**, prints resource usage, and tears itself down. The dev database is never touched.

```bash
./perf/run.sh                                        # defaults below
PERF_DB_CPUS=0.5 PERF_APP_MEMORY=256M ./perf/run.sh  # tighter limits
PERF_FIND_RATE=300 PERF_DURATION=60s ./perf/run.sh   # more load
```

| Variable | Default | |
|---|---|---|
| `PERF_DB_CPUS` / `PERF_DB_MEMORY` | `1` / `1G` | `db` limits |
| `PERF_APP_CPUS` / `PERF_APP_MEMORY` | `1` / `512M` | `app` limits |
| `PERF_APP_WORKERS` | `1` | Uvicorn workers (no `--reload`) |
| `PERF_FIELDS` | `50000` | Seeded fields (deterministic) |
| `PERF_FIND_RATE` / `PERF_LIST_RATE` / `PERF_GET_RATE` / `PERF_CREATE_RATE` | `100` / `20` / `20` / `5` | Requests per second, run in parallel |
| `PERF_DURATION` | `30s` | |
| `PERF_POSTGIS_IMAGE` | `imresamu/postgis:16-3.4` | Multi-arch build of PostGIS 16-3.4 (see below) |

Scenarios and thresholds live in [`perf/locustfile.py`](perf/locustfile.py), which runs in the `locustio/locust` image, so there's nothing to install:
- **Scenarios:** find-by-point, list, get-by-id and create all run in parallel. Each gets one user per target request per second, and every user makes one request per second on its own schedule with a random offset, so the load arrives evenly rather than in bursts. Get-by-id samples 1,000 real ids from the list endpoint at startup and also requests unknown ids 5% of the time, which must return 404.
- **Thresholds, checked at the end:**
  - p95 < 100 ms for find-by-point and get-by-id, < 200 ms for list, < 300 ms for create
  - DB query time (`query_time_ms`) p95 < 50 ms
  - < 1 % failed requests
  - ≥ 95 % of the target rate achieved in every scenario (if the server can't keep up, throughput drops)
- **Exit code:** `./perf/run.sh` exits non-zero if any threshold fails, so it can run in CI.

**Results** are saved to `perf/results/<UTC timestamp>/`, and `perf/results/latest` always points to the newest run. The folder is git-ignored.

| File | Contents |
|---|---|
| `summary.json` | Pass/fail, failed thresholds, and per scenario: requests, achieved vs target rps, p50/p95/p99/max |
| `resources.json` | Limits used and CPU/throttling/memory for `db` and `app` during the load |
| `report.html` | Locust's HTML report with charts |
| `locust_stats.csv`, `locust_stats_history.csv`, `locust_failures.csv`, `locust_exceptions.csv` | Raw Locust stats; the history file has per-second values |
| `console.log` | Full Locust output |

Reference run (Apple Silicon, default limits, 50k fields): 145 req/s, **p95 5–7 ms** for find-by-point (DB query p95 3 ms), 5 ms for get-by-id, 13–16 ms for list, 10–14 ms for create; 0 errors.

> **Apple Silicon:** `postgis/postgis`, used by the dev stack and the tests, is amd64-only and runs emulated. With the same 1-CPU limit it used about 4.4× more DB CPU, and p95 rose to 2.3 s. That's why the perf stack defaults to a native multi-arch image.

### Local development without Docker for the app

```bash
uv sync
docker compose up -d db
uv run alembic upgrade head            # DATABASE_URL defaults to localhost:5433
uv run python -m scripts.seed_fields --reset   # optional: demo data
uv run uvicorn app.main:app --reload
```

### Migrations

```bash
uv run alembic revision --autogenerate -m "describe change"   # after changing models
docker compose run --rm migrate                                # apply
docker compose run --rm migrate alembic downgrade -1           # roll back one step
```

### Configuration

| Variable | Default |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5433/agricultural_fields` |
| `DB_POOL_SIZE` | `20` (connections per worker; keep `pool size × workers × instances` below PostgreSQL's `max_connections`) |
| `DB_MAX_OVERFLOW` | `0` |
| `DB_POOL_TIMEOUT_SECONDS` | `30` |

### Stop

```bash
docker compose down        # keep data
docker compose down -v     # also delete the database volume
```

## API endpoints

Coordinates are always `[longitude, latitude]` in WGS 84 (EPSG:4326), as GeoJSON ([RFC 7946](https://datatracker.ietf.org/doc/html/rfc7946)) requires. Areas are in hectares, distances in meters. Validation errors return **422** in FastAPI's standard format: `{"detail": [{"loc": [...], "msg": "...", ...}]}`.

### `POST /api/fields` — create a field

```json
{
  "name": "Поле №1 - Пшениця",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[[30.5234, 50.4501], [30.5334, 50.4501], [30.5334, 50.4601], [30.5234, 50.4601], [30.5234, 50.4501]]]
  },
  "crop": "Пшениця",
  "owner": "Іванов І.І."
}
```

**Validation rules:**
- `name`, `crop`, `owner`: required, 1–255 characters after trimming whitespace.
- `geometry.type` must be `"Polygon"`. The first ring is the outer boundary and any further rings are holes.
- Each ring has at least 4 positions and must be closed (first position = last position).
- Longitude must be in [-180, 180] and latitude in [-90, 90]. A third coordinate (altitude) is rejected.
- The polygon must be valid: no self-intersections, no holes outside the outer boundary, and so on. The error message says what's wrong and where, e.g. `Self-intersection[30.55 50.45]`.
- The area must be at least **0.1 ha**.

**201 Created:**

```json
{
  "id": "0c6e688a-2878-4754-abe1-193395b28ea4",
  "name": "Поле №1 - Пшениця",
  "geometry": {"type": "Polygon", "coordinates": [[[30.5234, 50.4501], "..."]]},
  "area_ha": 78.9974,
  "crop": "Пшениця",
  "owner": "Іванов І.І.",
  "created_at": "2026-09-29T18:57:58.181273Z"
}
```

`area_ha` is calculated by PostGIS on the WGS 84 ellipsoid and rounded to 4 decimal places.

### `GET /api/fields` — list fields with filters

| Param | Type | Default | Notes |
|---|---|---|---|
| `crop` | string | — | Exact match (case-sensitive) |
| `owner` | string | — | Exact match (case-sensitive) |
| `min_area`, `max_area` | float ≥ 0, ha | — | Inclusive; `min_area > max_area` → 422 |
| `limit` | int 1–100 | 20 | |
| `offset` | int ≥ 0 | 0 | |

Unknown parameters return 422, so a typo like `?min_aera=` doesn't silently return unfiltered data. Results are sorted newest first. `total` counts every field matching the filters, not just the current page. Geometry isn't included.

```json
{
  "total": 150,
  "fields": [
    {"id": "uuid", "name": "Поле №1", "area_ha": 45.2, "crop": "Пшениця", "owner": "Іванов І.І."}
  ]
}
```

### `GET /api/fields/find-by-point` — fields containing a point

| Param | Type | Notes |
|---|---|---|
| `lon` | float, required | [-180, 180] |
| `lat` | float, required | [-90, 90] |

```json
// GET /api/fields/find-by-point?lon=30.5250&lat=50.4550
{
  "query_point": {"lon": 30.525, "lat": 50.455},
  "fields": [
    {
      "id": "uuid",
      "name": "Поле №1 - Пшениця",
      "area_ha": 78.9974,
      "crop": "Пшениця",
      "owner": "Іванов І.І.",
      "distance_to_center_m": 241.7
    }
  ],
  "query_time_ms": 1.6
}
```

- **Overlaps:** a point can be in several fields if they overlap. All of them are returned, nearest centroid first.
- **Boundaries:** a point on a field's boundary counts as inside.
- **Holes:** a point inside a hole doesn't.
- **`distance_to_center_m`:** the distance on the WGS 84 ellipsoid from the point to the field's centroid, rounded to 0.1 m.
- **`query_time_ms`:** only the database query time, not the whole HTTP request.

### `GET /api/fields/{id}` — field details with full geometry

`id` is a UUID. Returns the same body as `POST /api/fields`, with the full polygon including holes:

```json
{
  "id": "0c6e688a-2878-4754-abe1-193395b28ea4",
  "name": "Поле №1 - Пшениця",
  "geometry": {"type": "Polygon", "coordinates": [[[30.5234, 50.4501], "..."]]},
  "area_ha": 78.9974,
  "crop": "Пшениця",
  "owner": "Іванов І.І.",
  "created_at": "2026-09-29T18:57:58.181273Z"
}
```

- **404** if no field has this id: `{"detail": "field <id> not found"}`.
- **422** if `id` isn't a valid UUID.

### `GET /health`

Checks the database connection and returns the PostGIS version: `{"status": "ok", "postgis": "3.4 USE_GEOS=1 ..."}`.
