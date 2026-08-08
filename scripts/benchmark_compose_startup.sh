#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

output="${1:-release-evidence/compose-startup.json}"
project="energyforecast-startup-${GITHUB_RUN_ID:-$$}-${GITHUB_RUN_ATTEMPT:-1}"
export APP_VERSION="${APP_VERSION:-0.1.0}"
export CODE_COMMIT="${CODE_COMMIT:-${GITHUB_SHA:-startup-benchmark}}"
export POSTGRES_DB="${POSTGRES_DB:-energyforecast}"
export POSTGRES_USER="${POSTGRES_USER:-energyforecast}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-energyforecast}"
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}}"
export APP_HTTP_PORT="${APP_HTTP_PORT:-18081}"
export DB_PORT="${DB_PORT:-15433}"

compose=(docker compose -p "$project" -f docker-compose.yml -f docker-compose.override.yml)

cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    echo "Compose startup benchmark failed; dumping service state and logs." >&2
    "${compose[@]}" ps -a >&2 || true
    "${compose[@]}" logs --no-color >&2 || true
  fi
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

now_ns() {
  python3 - <<'PY'
import time
print(time.monotonic_ns())
PY
}

assert_ready() {
  curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 1 \
    "http://127.0.0.1:${APP_HTTP_PORT}/" >/dev/null
  curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 1 \
    "http://127.0.0.1:${APP_HTTP_PORT}/api/v1/health/ready" >/tmp/energyforecast-startup-ready.json
  grep -q '"status":"ok"' /tmp/energyforecast-startup-ready.json
  migrate_id="$("${compose[@]}" ps -aq migrate)"
  test -n "$migrate_id"
  test "$(docker inspect --format '{{.State.ExitCode}}' "$migrate_id")" = "0"
}

measure_up_ms() {
  local started finished
  started="$(now_ns)"
  "${compose[@]}" up -d --no-build --wait --wait-timeout 240 >/dev/null
  assert_ready
  finished="$(now_ns)"
  python3 - "$started" "$finished" <<'PY'
import sys
started, finished = map(int, sys.argv[1:])
print(round((finished - started) / 1_000_000, 3))
PY
}

"${compose[@]}" config >/dev/null
# Image build time is intentionally excluded: this benchmark measures service startup/readiness only.
"${compose[@]}" build >/dev/null

# Cold startup: no project containers, networks, database volume or artifact volume exist.
"${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
cold_ms="$(measure_up_ms)"

# Warm startup: keep initialized volumes, remove containers/networks, then recreate the stack.
"${compose[@]}" down --remove-orphans >/dev/null
warm_ms="$(measure_up_ms)"

docker_version="$(docker version --format '{{.Server.Version}}')"
compose_version="$(docker compose version --short)"
mkdir -p "$(dirname "$output")"
python3 - "$output" "$cold_ms" "$warm_ms" "$docker_version" "$compose_version" "$project" <<'PY'
from __future__ import annotations

import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

output, cold_ms, warm_ms, docker_version, compose_version, project = sys.argv[1:]
payload = {
    "schema": "energyforecast-compose-startup-benchmark/v1",
    "generated_at": datetime.now(UTC).isoformat(),
    "release_commit": os.environ.get("GITHUB_SHA") or os.environ.get("CODE_COMMIT") or "unknown",
    "profile": {
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
        "docker_server": docker_version,
        "docker_compose": compose_version,
        "project": project,
    },
    "semantics": {
        "images_prebuilt": True,
        "readiness": "docker compose up --wait plus HTTP readiness and migration exit-code checks",
        "cold": "no project volumes/containers/networks; includes PostgreSQL initialization and migrations",
        "warm": "initialized PostgreSQL/artifact volumes preserved; containers/networks recreated",
        "build_time_included": False,
        "fixed_sleep_used": False,
    },
    "measurements": {
        "cold_startup_ms": float(cold_ms),
        "warm_startup_ms": float(warm_ms),
    },
}
path = Path(output)
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2, sort_keys=True))
PY
