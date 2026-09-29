#!/usr/bin/env bash
# Build and start the isolated perf stack, seed it, run Locust, report container resource usage, tear everything down.
# Results go to perf/results/<UTC timestamp>/ (perf/results/latest points to the newest run).
# Exit code is Locust's: non-zero when any threshold in perf/locustfile.py fails.
set -euo pipefail
cd "$(dirname "$0")/.."

compose=(docker compose -f docker-compose.perf.yml)
trap '"${compose[@]}" down -v --remove-orphans >/dev/null 2>&1' EXIT

export PERF_RUN_ID="${PERF_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
results_dir="perf/results/$PERF_RUN_ID"
mkdir -p "$results_dir"

db_cpus=${PERF_DB_CPUS:-1} db_memory=${PERF_DB_MEMORY:-1G}
app_cpus=${PERF_APP_CPUS:-1} app_memory=${PERF_APP_MEMORY:-512M} app_workers=${PERF_APP_WORKERS:-1}
fields=${PERF_FIELDS:-50000} db_image=${PERF_POSTGIS_IMAGE:-imresamu/postgis:16-3.4}
echo "limits: db $db_cpus CPU / $db_memory, app $app_cpus CPU / $app_memory ($app_workers worker)," \
  "$fields fields, db image $db_image"

# Prints "<cpu usage usec> <throttled usec> <memory current bytes> <memory peak bytes>" from the container's cgroup (v2).
cgroup_stats() {
  "${compose[@]}" exec -T "$1" sh -c '
    awk "/^usage_usec/ {u=\$2} /^throttled_usec/ {t=\$2} END {printf \"%s %s \", u, t}" /sys/fs/cgroup/cpu.stat
    echo "$(cat /sys/fs/cgroup/memory.current) $(cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo 0)"'
}

"${compose[@]}" build --quiet
"${compose[@]}" up -d --wait app  # starts db -> migrate -> seed -> app
"${compose[@]}" logs seed | grep -E "created|overlapping" || true

read -r db_cpu_before db_throttled_before _ _ <<< "$(cgroup_stats db)"
read -r app_cpu_before app_throttled_before _ _ <<< "$(cgroup_stats app)"

status=0
"${compose[@]}" run --rm locust 2>&1 | tee "$results_dir/console.log" || status=$?

echo
echo "resource usage during the load test only:"
usage_json=""
for service in db app; do
  cpu_before_var="${service}_cpu_before" throttled_before_var="${service}_throttled_before"
  read -r cpu throttled memory peak <<< "$(cgroup_stats "$service")"
  cpu_ms=$(( (cpu - ${!cpu_before_var}) / 1000 )) throttled_ms=$(( (throttled - ${!throttled_before_var}) / 1000 ))
  memory_mib=$((memory / 1048576)) peak_mib=$((peak / 1048576))
  echo "  $service: CPU used $cpu_ms ms, throttled $throttled_ms ms;" \
    "memory now $memory_mib MiB, peak since start $peak_mib MiB"
  usage_json+="${usage_json:+,}\"$service\": {\"cpu_used_ms\": $cpu_ms, \"cpu_throttled_ms\": $throttled_ms,"
  usage_json+=" \"memory_now_mib\": $memory_mib, \"memory_peak_mib\": $peak_mib}"
done

cat > "$results_dir/resources.json" <<JSON
{
  "limits": {
    "db": {"cpus": "$db_cpus", "memory": "$db_memory", "image": "$db_image"},
    "app": {"cpus": "$app_cpus", "memory": "$app_memory", "workers": $app_workers}
  },
  "fields": $fields,
  "usage_during_load": {$usage_json}
}
JSON

ln -sfn "$PERF_RUN_ID" perf/results/latest
echo
echo "results: $results_dir (summary.json, resources.json, report.html, locust_*.csv, console.log)"

exit "$status"
