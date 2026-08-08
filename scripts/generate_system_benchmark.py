#!/usr/bin/env python3
"""Measure database-backed release evidence omitted by the pure benchmark.

Run from ``backend`` after migrations have been applied:

``uv run --frozen python ../scripts/generate_system_benchmark.py --output ../build/system-benchmark.json``

The script uses deterministic synthetic rows only. It measures the application's real chunked
``RawMeasurement`` persistence adapter and a complete FastAPI -> PostgreSQL/TimescaleDB analytics
request with ``max_points`` downsampling. Measurements are engineering evidence, not scientific UCI
model-quality results.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import statistics
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from energy_forecast.api import create_app
from energy_forecast.config import Settings
from energy_forecast.database import create_database_engine, create_session_factory
from energy_forecast.database.import_repository import SqlAlchemyDatasetImportRepository
from energy_forecast.database.models import Dataset, DatasetVersion
from energy_forecast.database.session import AsyncSessionFactory, transactional_session
from energy_forecast.datasets.parsers import ParseBatch, ParsedMeasurement

START = datetime(2020, 1, 1, tzinfo=UTC)
BATCH_ROWS = 10_000
BATCH_SIZE = 1_000
ANALYTICS_HOURS = 20_000
ANALYTICS_MAX_POINTS = 200


class PassingReadinessCheck:
    async def check(self) -> None:
        return None


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, int(round(0.95 * len(ordered) + 0.5)) - 1))
    return ordered[index]


def _summary(samples_ms: list[float]) -> dict[str, float | int]:
    return {
        "repetitions": len(samples_ms),
        "median_ms": round(statistics.median(samples_ms), 6),
        "p95_ms": round(_p95(samples_ms), 6),
    }


def _database_url() -> str:
    value = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("TEST_DATABASE_URL or DATABASE_URL is required")
    return value


def _batches() -> tuple[ParseBatch, ...]:
    batches: list[ParseBatch] = []
    for batch_no in range(BATCH_ROWS // BATCH_SIZE):
        offset = batch_no * BATCH_SIZE
        measurements = tuple(
            ParsedMeasurement(
                source_row_number=offset + index + 1,
                observed_at=START + timedelta(minutes=offset + index),
                timestamp_original=(START + timedelta(minutes=offset + index)).isoformat(),
                timezone_context="UTC",
                interval_seconds=60,
                active_power_kw=1.0 + ((offset + index) % 60) / 1000.0,
                reactive_power_kw=0.2,
                voltage_v=230.0,
                current_a=4.0,
                sub_metering_1_wh=1.0,
                sub_metering_2_wh=2.0,
                sub_metering_3_wh=3.0,
            )
            for index in range(BATCH_SIZE)
        )
        batches.append(ParseBatch(measurements=measurements, issues=(), rows_read=offset + BATCH_SIZE))
    return tuple(batches)


async def _create_dataset(factory: AsyncSessionFactory, *, name: str) -> UUID:
    dataset_id = uuid4()
    async with transactional_session(factory) as session:
        session.add(Dataset(id=dataset_id, name=name))
    return dataset_id


async def _create_version(
    factory: AsyncSessionFactory,
    *,
    dataset_id: UUID,
    version_no: int,
    status: str,
) -> UUID:
    version_id = uuid4()
    async with transactional_session(factory) as session:
        session.add(
            DatasetVersion(
                id=version_id,
                dataset_id=dataset_id,
                version_no=version_no,
                status=status,
                timezone_context="UTC",
                interval_seconds=60 if status != "ready" else 3600,
                quality_policy={},
                transformation_manifest={},
            )
        )
    return version_id


async def _benchmark_batch_insert(
    factory: AsyncSessionFactory,
) -> dict[str, float | int]:
    dataset_id = await _create_dataset(factory, name="Batch insert benchmark")
    repository = SqlAlchemyDatasetImportRepository(factory)
    batches = _batches()

    async def run_once(version_no: int) -> float:
        version_id = await _create_version(
            factory,
            dataset_id=dataset_id,
            version_no=version_no,
            status="importing",
        )
        import_id = uuid4()
        started = time.perf_counter()
        for batch in batches:
            await repository.insert_batch(
                import_id=import_id,
                dataset_version_id=version_id,
                batch=batch,
            )
        return (time.perf_counter() - started) * 1000.0

    await run_once(1)
    samples = [await run_once(index) for index in range(2, 5)]
    result = _summary(samples)
    median_ms = float(result["median_ms"])
    result.update(
        {
            "rows_per_repetition": BATCH_ROWS,
            "batch_size": BATCH_SIZE,
            "transactions_per_repetition": BATCH_ROWS // BATCH_SIZE,
            "median_rows_per_second": round(BATCH_ROWS / (median_ms / 1000.0), 2),
            "adapter": "SqlAlchemyDatasetImportRepository.insert_batch",
        }
    )
    return result


async def _seed_analytics_fixture(factory: AsyncSessionFactory) -> UUID:
    dataset_id = await _create_dataset(factory, name="Analytics endpoint benchmark")
    version_id = await _create_version(
        factory,
        dataset_id=dataset_id,
        version_no=1,
        status="ready",
    )
    async with transactional_session(factory) as session:
        await session.execute(
            text(
                """
                INSERT INTO ts.hourly_observations (
                    dataset_version_id, hour_start, timezone_context, energy_kwh,
                    observed_samples, expected_samples, coverage_ratio, imputed_samples,
                    max_missing_run, quality_status, quality_flags
                )
                SELECT :version_id,
                       :start + value * INTERVAL '1 hour',
                       'UTC', 1.0 + (value % 24), 60, 60, 1.0, 0, 0, 'complete', '{}'::text[]
                FROM generate_series(0, :last_hour) AS value
                """
            ),
            {
                "version_id": version_id,
                "start": START,
                "last_hour": ANALYTICS_HOURS - 1,
            },
        )
    return version_id


async def _database_profile(factory: AsyncSessionFactory) -> dict[str, str]:
    async with transactional_session(factory) as session:
        postgres = str(await session.scalar(text("SELECT version()")))
        timescale = str(
            await session.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            )
        )
    return {"postgresql": postgres, "timescaledb": timescale}


def _app(database_url: str) -> FastAPI:
    artifact_root = Path(tempfile.mkdtemp(prefix="energyforecast-system-benchmark-")) / "artifacts"
    return create_app(
        Settings(
            database_url=SecretStr(database_url),
            artifact_root=artifact_root,
            log_level="WARNING",
        ),
        PassingReadinessCheck(),
    )


def _benchmark_analytics_endpoint(database_url: str, version_id: UUID) -> dict[str, Any]:
    app = _app(database_url)
    end = START + timedelta(hours=ANALYTICS_HOURS)
    params = {
        "from": START.isoformat().replace("+00:00", "Z"),
        "to": end.isoformat().replace("+00:00", "Z"),
        "resolution": "hour",
        "max_points": ANALYTICS_MAX_POINTS,
    }
    samples: list[float] = []
    response_points = 0
    bucket_seconds = 0
    with TestClient(app, raise_server_exceptions=False) as client:
        warmup = client.get(f"/dataset-versions/{version_id}/analytics/series", params=params)
        if warmup.status_code != 200:
            raise RuntimeError(f"analytics warmup failed: {warmup.status_code} {warmup.text}")
        for _ in range(20):
            started = time.perf_counter()
            response = client.get(f"/dataset-versions/{version_id}/analytics/series", params=params)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if response.status_code != 200:
                raise RuntimeError(f"analytics request failed: {response.status_code} {response.text}")
            payload = response.json()
            if not payload.get("downsampled"):
                raise RuntimeError("analytics benchmark expected a downsampled response")
            response_points = len(payload["points"])
            bucket_seconds = int(payload["bucket_seconds"])
            if response_points > ANALYTICS_MAX_POINTS:
                raise RuntimeError("analytics endpoint exceeded max_points")
            samples.append(elapsed_ms)
    result: dict[str, Any] = _summary(samples)
    result.update(
        {
            "stored_hours": ANALYTICS_HOURS,
            "max_points": ANALYTICS_MAX_POINTS,
            "response_points": response_points,
            "bucket_seconds": bucket_seconds,
            "path": "/dataset-versions/{versionId}/analytics/series",
            "stack": "FastAPI TestClient -> SQLAlchemy async -> PostgreSQL/TimescaleDB",
        }
    )
    return result


async def _prepare_database_measurements(database_url: str) -> tuple[dict[str, Any], UUID, dict[str, str]]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        profile = await _database_profile(factory)
        batch_insert = await _benchmark_batch_insert(factory)
        analytics_version_id = await _seed_analytics_fixture(factory)
        return batch_insert, analytics_version_id, profile
    finally:
        await engine.dispose()


def _build_evidence(database_url: str) -> dict[str, Any]:
    batch_insert, analytics_version_id, database = asyncio.run(
        _prepare_database_measurements(database_url)
    )
    analytics = _benchmark_analytics_endpoint(database_url, analytics_version_id)
    return {
        "schema": "energyforecast-system-benchmark/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "release_commit": os.environ.get("GITHUB_SHA") or os.environ.get("CODE_COMMIT") or "unknown",
        "profile": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu": platform.processor() or "unknown",
            "logical_cpus": os.cpu_count(),
        },
        "database": database,
        "dataset": {
            "kind": "deterministic synthetic database fixture",
            "uci_in_repository": False,
        },
        "measurements": {
            "raw_measurement_batch_insert": batch_insert,
            "analytics_series_endpoint_max_points": analytics,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = _build_evidence(_database_url())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
