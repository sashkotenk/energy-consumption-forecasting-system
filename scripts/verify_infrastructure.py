#!/usr/bin/env python3
"""Validate the committed container/Compose hardening contract without starting the stack."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SERVICES = {"db", "migrate", "api", "worker", "web", "nginx"}
PRIVATE_PATH_PATTERN = re.compile(
    r"(^|/)(AGENTS\.md|prompts/|checklists?/|Пункт плану|План виконання|EnergyForecast-private)"
)


def run(*args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def compose_config(*files: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    args = ["docker", "compose"]
    for file in files:
        args.extend(["-f", file])
    args.extend(["config", "--format", "json"])
    return json.loads(run(*args, env=env))


def assert_named_volume_only(service: dict[str, Any], service_name: str) -> None:
    for volume in service.get("volumes", []):
        if volume.get("type") == "bind":
            raise AssertionError(f"{service_name} contains a production bind mount: {volume}")


def assert_pinned_image(service_name: str, service: dict[str, Any]) -> None:
    image = service.get("image")
    if not image or ":" not in image or image.endswith(":latest"):
        raise AssertionError(f"{service_name} must use an explicitly tagged image: {image!r}")


def main() -> int:
    dev = compose_config("docker-compose.yml", "docker-compose.override.yml")
    production_env = os.environ.copy()
    production_env.update(
        {
            "POSTGRES_PASSWORD": "verification-only",
            "DATABASE_URL": (
                "postgresql+asyncpg://energyforecast:verification-only@db:5432/energyforecast"
            ),
            "CODE_COMMIT": "verification",
        }
    )
    prod = compose_config("docker-compose.yml", "docker-compose.prod.yml", env=production_env)

    if set(dev["services"]) != EXPECTED_SERVICES or set(prod["services"]) != EXPECTED_SERVICES:
        raise AssertionError("Compose must resolve exactly db, migrate, api, worker, web and nginx")

    for name, service in prod["services"].items():
        assert_pinned_image(name, service)
        assert_named_volume_only(service, name)

    if prod["services"]["db"].get("ports"):
        raise AssertionError("Production-like database must not publish a host port")

    api_dependencies = prod["services"]["api"].get("depends_on", {})
    worker_dependencies = prod["services"]["worker"].get("depends_on", {})
    for service_name, dependencies in (("api", api_dependencies), ("worker", worker_dependencies)):
        if dependencies.get("migrate", {}).get("condition") != "service_completed_successfully":
            raise AssertionError(f"{service_name} must wait for successful migrations")
        if dependencies.get("db", {}).get("condition") != "service_healthy":
            raise AssertionError(f"{service_name} must wait for a healthy database")

    if "backend" not in prod["services"]["db"].get("networks", {}):
        raise AssertionError("Database must be isolated on the backend network")
    if "edge" in prod["services"]["db"].get("networks", {}):
        raise AssertionError("Database must not join the edge network")

    for service_name in ("migrate", "api", "worker", "web", "nginx"):
        if not prod["services"][service_name].get("read_only"):
            raise AssertionError(f"{service_name} must use a read-only root filesystem")

    nginx_config = (ROOT / "infrastructure/nginx/nginx.conf").read_text(encoding="utf-8")
    if "client_max_body_size 300m;" not in nginx_config:
        raise AssertionError("Nginx upload limit must remain aligned to the 300 MiB backend limit")
    if "location /api/v1/" not in nginx_config or "proxy_pass http://api_backend/;" not in nginx_config:
        raise AssertionError("Nginx must strip /api/v1 while proxying to FastAPI")
    if "Access-Control-Allow-Origin" in nginx_config:
        raise AssertionError("The edge proxy must not introduce a wildcard or synthetic CORS policy")
    if "location ^~ /artifacts/" not in nginx_config:
        raise AssertionError("The edge proxy must explicitly deny direct artifact paths")

    tracked = run("git", "ls-files").splitlines()
    leaked = [path for path in tracked if PRIVATE_PATH_PATTERN.search(path)]
    if leaked:
        raise AssertionError(f"Private planning/specification paths are tracked: {leaked}")

    print("Infrastructure contract verified")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Infrastructure verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
