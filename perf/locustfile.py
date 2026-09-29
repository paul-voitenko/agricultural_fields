"""Locust load test: find-by-point, list, get-by-id and create run in parallel, each at a fixed target rate.

Each scenario gets as many users as its target requests per second, and every user makes at most one request per
second on its own schedule, phase-shifted by a random offset, so requests arrive evenly spread over each second
instead of in one synchronized burst. If the server can't keep up, the achieved rate drops below target, and that
fails the run just like a latency threshold does. Thresholds are checked when the run ends, and the process
exits non-zero if any fails.

Runs inside the `locustio/locust` image (see docker-compose.perf.yml), so it only depends on Locust itself.
"""

import json
import math
import os
import random
import time
import uuid

import gevent
import requests
from locust import FastHttpUser, LoadTestShape, events, task
from locust.env import Environment

FIND_RATE = int(os.environ.get("FIND_RATE", "100"))
LIST_RATE = int(os.environ.get("LIST_RATE", "20"))
CREATE_RATE = int(os.environ.get("CREATE_RATE", "5"))
GET_RATE = int(os.environ.get("GET_RATE", "20"))
RESULTS_DIR = os.environ.get("RESULTS_DIR")  # summary.json is written here when set
DURATION = os.environ.get("DURATION", "30s")

FIND_BY_POINT = "GET /api/fields/find-by-point"
LIST_FIELDS = "GET /api/fields"
CREATE_FIELD = "POST /api/fields"
GET_FIELD = "GET /api/fields/{id}"
DB_QUERY_TIME = "find-by-point query_time_ms"

# name -> (method, target rps, p95 threshold in ms); the DB metric has no target rate.
THRESHOLDS = {
    FIND_BY_POINT: ("GET", FIND_RATE, 100),
    LIST_FIELDS: ("GET", LIST_RATE, 200),
    CREATE_FIELD: ("POST", CREATE_RATE, 300),
    GET_FIELD: ("GET", GET_RATE, 100),
    DB_QUERY_TIME: ("DB", None, 50),
}
MAX_FAILURE_RATIO = 0.01
MIN_ACHIEVED_RATE_RATIO = 0.95

# Same regions as scripts/seed_fields.py (lat, lon), so most random points land among seeded fields.
REGION_CENTERS = [
    (50.20, 30.60), (50.25, 28.66), (49.23, 28.47), (49.42, 26.99), (49.55, 25.59), (49.44, 32.06), (49.59, 34.55),
    (48.51, 32.26), (48.46, 35.04), (49.70, 36.00), (50.75, 34.40), (51.20, 31.60), (47.40, 31.90), (47.00, 30.20),
]
REGION_SPREAD_DEGREES = 0.35
CROPS = ["Пшениця озима", "Кукурудза", "Соняшник", "Ячмінь", "Соя", "Ріпак"]
METERS_PER_DEGREE_LATITUDE = 111_320

ID_SAMPLE_PAGES = 10
ID_SAMPLE_PAGE_SIZE = 100
UNKNOWN_ID_PROBABILITY = 0.05

fields_found: list[int] = []
known_field_ids: list[str] = []


@events.test_start.add_listener
def load_field_ids(environment: Environment, **_: object) -> None:
    """Sample existing ids from random pages of the list endpoint, so get-by-id hits real fields."""
    list_url = f"{environment.host}/api/fields"
    total = requests.get(list_url, params={"limit": 1}, timeout=10).json()["total"]
    possible_offsets = range(max(total - ID_SAMPLE_PAGE_SIZE, 0) + 1)
    offsets = random.sample(possible_offsets, min(ID_SAMPLE_PAGES, len(possible_offsets)))
    for offset in offsets:
        page = requests.get(list_url, params={"limit": ID_SAMPLE_PAGE_SIZE, "offset": offset}, timeout=10).json()
        known_field_ids.extend(field["id"] for field in page["fields"])
    if not known_field_ids:
        raise RuntimeError("no fields in the database; seed it before running the get-by-id scenario")
    print(f"get-by-id: sampled {len(known_field_ids)} existing field ids")


def parse_duration_seconds(duration: str) -> int:
    units = {"s": 1, "m": 60, "h": 3600}
    if duration[-1] in units:
        return int(duration[:-1]) * units[duration[-1]]
    return int(duration)


def random_point() -> tuple[float, float]:
    lat, lon = random.choice(REGION_CENTERS)
    return (
        lon + random.uniform(-REGION_SPREAD_DEGREES, REGION_SPREAD_DEGREES),
        lat + random.uniform(-REGION_SPREAD_DEGREES, REGION_SPREAD_DEGREES),
    )


class FixedRateUser(FastHttpUser):
    """One request per second per user, on its own schedule: offset + 0 s, offset + 1 s, offset + 2 s, ...

    Locust's constant_throughput counts from user creation, and all users are created at once, so every user
    would fire in the same instant each second. A random per-user offset spreads requests evenly instead.
    """

    abstract = True

    def on_start(self) -> None:
        self._next_request_at = time.monotonic() + random.random()
        gevent.sleep(self._next_request_at - time.monotonic())

    def wait_time(self) -> float:
        self._next_request_at += 1
        return max(0.0, self._next_request_at - time.monotonic())


class FindByPointUser(FixedRateUser):
    fixed_count = FIND_RATE

    @task
    def find_by_point(self) -> None:
        lon, lat = random_point()
        with self.client.get(
            f"/api/fields/find-by-point?lon={lon}&lat={lat}", name=FIND_BY_POINT, catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"status {response.status_code}")
                return
            body = response.json()
            fields_found.append(len(body["fields"]))
            events.request.fire(
                request_type="DB",
                name=DB_QUERY_TIME,
                response_time=body["query_time_ms"],
                response_length=0,
                exception=None,
                context={},
            )


class ListFieldsUser(FixedRateUser):
    fixed_count = LIST_RATE

    @task
    def list_fields(self) -> None:
        params = {"limit": 20, "offset": random.randrange(500)}
        if random.random() < 0.7:
            params["crop"] = random.choice(CROPS)
        if random.random() < 0.5:
            params["min_area"] = random.randrange(100)
        self.client.get("/api/fields", params=params, name=LIST_FIELDS)


class GetFieldUser(FixedRateUser):
    fixed_count = GET_RATE

    @task
    def get_field(self) -> None:
        # Mostly real ids, plus a few unknown ones so the 404 path is exercised too.
        if random.random() < UNKNOWN_ID_PROBABILITY:
            field_id, expected_status = str(uuid.uuid4()), 404
        else:
            field_id, expected_status = random.choice(known_field_ids), 200
        with self.client.get(f"/api/fields/{field_id}", name=GET_FIELD, catch_response=True) as response:
            if response.status_code != expected_status:
                response.failure(f"expected {expected_status}, got {response.status_code}")
            elif expected_status == 200 and response.json()["geometry"]["type"] != "Polygon":
                response.failure("response has no polygon geometry")
            else:
                response.success()


class CreateFieldUser(FixedRateUser):
    fixed_count = CREATE_RATE

    @task
    def create_field(self) -> None:
        lon, lat = random_point()
        half_side_meters = random.uniform(150, 500)  # ~9–100 ha squares
        d_lat = half_side_meters / METERS_PER_DEGREE_LATITUDE
        d_lon = half_side_meters / (METERS_PER_DEGREE_LATITUDE * math.cos(math.radians(lat)))
        ring = [
            [lon - d_lon, lat - d_lat],
            [lon + d_lon, lat - d_lat],
            [lon + d_lon, lat + d_lat],
            [lon - d_lon, lat + d_lat],
            [lon - d_lon, lat - d_lat],
        ]
        payload = {
            "name": f"Perf {random.getrandbits(32):08x}",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "crop": random.choice(CROPS),
            "owner": "Perf Test",
        }
        self.client.post(
            "/api/fields",
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            name=CREATE_FIELD,
        )


class FixedRateShape(LoadTestShape):
    """Start every user at once, hold for DURATION, then stop."""

    total_users = FIND_RATE + LIST_RATE + GET_RATE + CREATE_RATE
    duration_seconds = parse_duration_seconds(DURATION)

    def tick(self) -> tuple[int, float] | None:
        if self.get_run_time() >= self.duration_seconds:
            return None
        return self.total_users, self.total_users


@events.quitting.add_listener
def check_thresholds(environment: Environment, **_: object) -> None:
    stats = environment.stats
    elapsed_seconds = max(stats.last_request_timestamp - stats.start_time, 1)
    failures: list[str] = []
    scenarios: list[dict] = []

    print(f"\n{'threshold check':<32} {'requests':>8} {'rps':>7} {'target':>7} {'p50':>8} {'p95':>8} {'max p95':>8}")
    for name, (method, target_rate, max_p95_ms) in THRESHOLDS.items():
        entry = stats.get(name, method)
        rps = entry.num_requests / elapsed_seconds
        p50, p95 = entry.get_response_time_percentile(0.5), entry.get_response_time_percentile(0.95)
        target = f"{target_rate:>7}" if target_rate else f"{'-':>7}"
        print(f"{name:<32} {entry.num_requests:>8} {rps:>7.1f} {target} {p50:>7.1f}ms {p95:>7.1f}ms {max_p95_ms:>6}ms")
        latency_ok = p95 <= max_p95_ms
        rate_ok = not target_rate or rps >= target_rate * MIN_ACHIEVED_RATE_RATIO
        if not latency_ok:
            failures.append(f"{name}: p95 {p95:.1f} ms > {max_p95_ms} ms")
        if not rate_ok:
            failures.append(f"{name}: achieved {rps:.1f} rps < {MIN_ACHIEVED_RATE_RATIO:.0%} of target {target_rate}")
        scenarios.append(
            {
                "name": name,
                "requests": entry.num_requests,
                "failures": entry.num_failures,
                "rps": round(rps, 2),
                "target_rps": target_rate,
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": entry.get_response_time_percentile(0.99),
                "max_ms": round(entry.max_response_time, 2),
                "max_p95_ms": max_p95_ms,
                "passed": latency_ok and rate_ok,
            }
        )

    # Only real HTTP requests: the DB timing entries never fail and would dilute the ratio.
    http_entries = [stats.get(name, method) for name, (method, _, _) in THRESHOLDS.items() if method != "DB"]
    http_requests = sum(entry.num_requests for entry in http_entries)
    failure_ratio = sum(entry.num_failures for entry in http_entries) / http_requests if http_requests else 0.0
    if failure_ratio > MAX_FAILURE_RATIO:
        failures.append(f"failed requests {failure_ratio:.2%} > {MAX_FAILURE_RATIO:.0%}")
    if fields_found:
        print(f"\nfind-by-point: {sum(fields_found) / len(fields_found):.2f} fields per point on average")
    print(f"failed requests: {failure_ratio:.2%}")

    if failures:
        print("\nTHRESHOLDS FAILED:\n  " + "\n  ".join(failures))
        environment.process_exit_code = 1
    else:
        print("\nall thresholds passed")
        environment.process_exit_code = 0

    if RESULTS_DIR:
        summary = {
            "passed": not failures,
            "threshold_failures": failures,
            "duration_seconds": round(elapsed_seconds, 1),
            "failure_ratio": failure_ratio,
            "find_by_point_fields_per_point": round(sum(fields_found) / len(fields_found), 3) if fields_found else None,
            "scenarios": scenarios,
        }
        with open(os.path.join(RESULTS_DIR, "summary.json"), "w", encoding="utf-8") as file:
            json.dump(summary, file, ensure_ascii=False, indent=2)
