#!/usr/bin/env bash
set -Eeuo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

project="energyforecast-smoke-${GITHUB_RUN_ID:-$$}-${GITHUB_RUN_ATTEMPT:-1}"
export APP_VERSION="${APP_VERSION:-0.1.0}"
export CODE_COMMIT="${CODE_COMMIT:-smoke}"
export POSTGRES_DB="${POSTGRES_DB:-energyforecast}"
export POSTGRES_USER="${POSTGRES_USER:-energyforecast}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-energyforecast}"
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}}"
export APP_HTTP_PORT="${APP_HTTP_PORT:-18080}"
export DB_PORT="${DB_PORT:-15432}"

compose=(docker compose -p "$project" -f docker-compose.yml -f docker-compose.override.yml)
cleanup() {
  "${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

cleanup
"${compose[@]}" config >/dev/null
"${compose[@]}" up -d --build --wait --wait-timeout 240

curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 1 \
  "http://127.0.0.1:${APP_HTTP_PORT}/" >/dev/null
curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 1 \
  "http://127.0.0.1:${APP_HTTP_PORT}/api/v1/health/ready" >/tmp/energyforecast-ready.json

grep -q '"status":"ok"' /tmp/energyforecast-ready.json
migrate_id="$("${compose[@]}" ps -aq migrate)"
test -n "$migrate_id"
test "$(docker inspect --format '{{.State.ExitCode}}' "$migrate_id")" = "0"

"${compose[@]}" ps
