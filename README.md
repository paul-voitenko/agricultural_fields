# Agricultural Fields API

A FastAPI + PostGIS service for storing agricultural fields (GeoJSON polygons) and finding the fields that contain a given point.

## Contents

- [Quick start](#quick-start)
  - [Compose services](#compose-services)
  - [Tests](#tests)
  - [Performance tests](#performance-tests)
  - [Local development without Docker for the app](#local-development-without-docker-for-the-app)
  - [Migrations](#migrations)
  - [Configuration](#configuration)
  - [Stop](#stop)
- [API endpoints](#api-endpoints)
  - [`POST /api/fields` — create a field](#post-apifields--create-a-field)
  - [`GET /api/fields` — list fields with filters](#get-apifields--list-fields-with-filters)
  - [`GET /api/fields/find-by-point` — fields containing a point](#get-apifieldsfind-by-point--fields-containing-a-point)
  - [`GET /api/fields/{id}` — field details with full geometry](#get-apifieldsid--field-details-with-full-geometry)
  - [`GET /health`](#get-health)
- [Архітектурні рішення](#архітектурні-рішення)
  - [Зберігання даних](#зберігання-даних)
  - [Пошук по точці: GiST-індекс + ST_Covers.](#пошук-по-точці-gist-індекс--st_covers)
  - [Похідні поля прораховуються заздалегідь.](#похідні-поля-прораховуються-заздалегідь)
  - [Валідація на стороні АПІ](#валідація-на-стороні-апі)
  - [Структура додатку](#структура-додатку)
  - [Тести](#тести)
- [Що б я покращив, маючи більше часу](#що-б-я-покращив-маючи-більше-часу)
  - [Загальне](#загальне)
  - [Scaling](#scaling)

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
  - Database call time as seen by the app (`query_time_ms`, see [find-by-point](#get-apifieldsfind-by-point--fields-containing-a-point)) p95 < 50 ms
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

Reference run (Apple Silicon, default limits, 50k fields): 145 req/s, **p95 5–7 ms** for find-by-point (`query_time_ms` p95 3 ms), 5 ms for get-by-id, 13–16 ms for list, 10–14 ms for create; 0 errors.

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
- **`query_time_ms`:** how long the database call took as seen by the app. That includes waiting for a free pooled connection, the network round trip, executing the SQL and building result objects, but not request parsing or response serialization. On an idle server it's close to the pure SQL time (~1 ms on 50k fields). Under load, waiting for a connection can dominate it.

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

## Архітектурні рішення

### Зберігання даних
`geometry(Polygon, 4326)`, вимірювання на еліпсоїді

- Колонка `geometry` має тип `geometry`, а не `geography`. Координати GeoJSON уже подані у WGS 84 (довгота/широта), тому під час запису та читання нічого не перепроєктовується. Функціїї типу `ST_Covers`, дешевші за свої аналоги для `geography`. Для поля завширшки кілька кілометрів різниця між прямим ребром у градусах і геодезичною лінією мала і нею можна знехтувати.
- Усе, що вимірюється в реальних одиницях, обчислюється на еліпсоїді WGS 84 через приведення до `geography`: `area_ha` (`ST_Area(geometry::geography) / 10000`) і `distance_to_center_m` (`ST_Distance` між значеннями `geography`). Якщо обчислювати їх на `geometry`, результат був би у квадратних градусах і градусах.

### Пошук по точці: GiST-індекс + ST_Covers.
GiST-індекс на geometry — це R-tree з bounding box-ів полігонів. Пошук іде у дві фази: індекс швидко знаходить поля, чий bounding box містить точку, а точна перевірка ST_Covers виконується тільки для цих кандидатів. ST_Covers, а не ST_Contains, бо точка на межі поля має вважатися всередині.

### Похідні поля прораховуються заздалегідь.
- `area_ha` використовується для фільтрації списку полів і має B-tree index, щоб `min_area/max_area` не сканували таблицю.
- `centroid` зберігаємо одразу в `geography` щоб не кастить кожен раз. Індекса нема, бо по ньому не шукаємо, тільки обраховуємо для рядків які уже відфільровані

### Валідація на стороні АПІ
- Валідність полігона (самоперетини, діри поза кільцем) перевіряю через Shapely(під капотом те ж що і у PostGIS). Можна за допомогою ST_IsValid в PostGIS
- Обрахунок мінімальної площі поля за допомогою pyproj(той же алгоритм що і у PostGIS). Можна за допомогою ST_Area(geography)

Основна ідея звісно в тому щоб зайвий раз не чіпати базу і не займати конекшени якщо точно не впевнені що готові робити вставку нового рядка. Також це пришвидшить відповідь АПІ і надасть чітку 422 помилку - що саме не так із запитом.

### Структура додатку
Загалом стандартна route(робота з http) -> service(логіка і мапінг даних) -> repo(SQL і доступ до бази). Зазвичай ще додаю щар use_case між сервісом і роутом, тоді сервіс має reusable логіку додатку, а юз кейс описує конкретний бізнес-процес, але в даному випадку логіки практично нема, тому вирішив не ускладнювати.

Також використав Dependency Injection - в основному для спрощення тестування. В тестах це зараз юзається тільки для бази, але загалом, як на мене, хороша практика щоб тримати код decoupled і мати зрозумілі інтерфейси для всіх сутностей коду (роутів, сервісів, репозиторіїв), так одразу видно що йому необхідно для роботи.

### Тести
ТЗ цього не вимагало, але додав інтеграційні тести як хорошу практику ну і звісно для власного спокою. Оскільки більша частина логіки відбувається всередині бази даних - тести її не мокають, а піднімають окремий PostGIS тестконтейнер.

Додав в репозиторій також перфоменс тести, які використовував для перевірок і оптимізацій швидкості роботи додатку.

## Що б я покращив, маючи більше часу
### Загальне
- Додав би constraints в базу на валідність геометрії і мінімальну площу. - наразі запис відбувається тільки з цього додатку, але на майбутнє краще закласти цю перевірку і в базу на випадок якщо будуть інші writers
- Інформацію про культури і власників можна зберігати в окремих таблицях
- Додав би логування/метрики

### Scaling
- АПІ stateless, тож її можна горизонтально скейлити. Основна операція - пошук по точці тільки читає, тож можна додавати рід репліки + PgBouncer
- Можна додати партиціювання, але треба дослідити реальні дані щоб правильно обрати правило для створення партиції (наприклад якщо всі поля в одній області, а ми партиціюємо по областях - все залетить в одну партицію і вийде тільки гірше)
