from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from energy_forecast.api import create_app
from energy_forecast.config import Settings
from energy_forecast.database import create_database_engine, create_session_factory
from energy_forecast.database.models import Dataset, DatasetVersion, HourlyObservation
from energy_forecast.database.session import transactional_session
from tests.integration.conftest import upgrade_database


class PassingReadinessCheck:
    async def check(self) -> None:
        return None


@pytest.mark.integration
def test_summary_profiles_distribution_and_range_contract(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    version_id = asyncio.run(_seed_known_fixture(temporary_database_url))
    app = _app(temporary_database_url, tmp_path)
    first_four = {
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-01-01T04:00:00Z",
    }
    full_range = {
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-01-11T00:00:00Z",
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        openapi = client.get("/openapi.json").json()
        analytics_paths = {
            f"/dataset-versions/{{versionId}}/analytics/{suffix}"
            for suffix in (
                "summary",
                "series",
                "hourly-profile",
                "weekday-profile",
                "heatmap",
                "distribution",
            )
        }
        assert analytics_paths <= set(openapi["paths"])
        series_parameters = openapi["paths"]["/dataset-versions/{versionId}/analytics/series"][
            "get"
        ]["parameters"]
        assert {item["name"] for item in series_parameters if item.get("required")} >= {
            "versionId",
            "from",
            "to",
        }
        assert (
            openapi["components"]["schemas"]["AnalyticsSummaryResponse"]["example"]["unit"] == "kWh"
        )

        summary = client.get(f"/dataset-versions/{version_id}/analytics/summary", params=first_four)
        assert summary.status_code == 200, summary.text
        payload = summary.json()
        assert payload == {
            "dataset_version_id": str(version_id),
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-01-01T04:00:00Z",
            "timezone": "Europe/Kyiv",
            "unit": "kWh",
            "expected_hours": 4,
            "stored_hours": 4,
            "energy_value_count": 3,
            "absent_hours": 0,
            "missing_energy_hours": 1,
            "mean_energy_kwh": pytest.approx(7 / 3),
            "median_energy_kwh": 2.0,
            "min_energy_kwh": 1.0,
            "max_energy_kwh": 4.0,
            "total_energy_kwh": 7.0,
            "mean_coverage_ratio": 0.875,
            "status_counts": {"complete": 3, "invalid_missing": 1},
        }

        hourly = client.get(
            f"/dataset-versions/{version_id}/analytics/hourly-profile", params=full_range
        )
        weekday = client.get(
            f"/dataset-versions/{version_id}/analytics/weekday-profile", params=full_range
        )
        heatmap = client.get(f"/dataset-versions/{version_id}/analytics/heatmap", params=full_range)
        distribution = client.get(
            f"/dataset-versions/{version_id}/analytics/distribution",
            params={**full_range, "bins": 5},
        )
        assert hourly.status_code == weekday.status_code == heatmap.status_code == 200
        assert distribution.status_code == 200, distribution.text
        assert [point["key"] for point in hourly.json()["points"]] == list(range(24))
        assert [point["key"] for point in weekday.json()["points"]] == list(range(1, 8))
        cells = heatmap.json()["points"]
        assert [(cell["iso_weekday"], cell["hour"]) for cell in cells] == sorted(
            (cell["iso_weekday"], cell["hour"]) for cell in cells
        )
        bins = distribution.json()["bins"]
        assert len(bins) <= 5
        assert sum(item["sample_count"] for item in bins) == 239

        empty = client.get(
            f"/dataset-versions/{version_id}/analytics/summary",
            params={"from": "2027-01-01T00:00:00Z", "to": "2027-01-02T00:00:00Z"},
        )
        assert empty.status_code == 200
        assert empty.json()["stored_hours"] == 0
        assert empty.json()["missing_energy_hours"] == 24
        assert empty.json()["mean_energy_kwh"] is None

        invalid = client.get(
            f"/dataset-versions/{version_id}/analytics/summary",
            params={"from": first_four["to"], "to": first_four["from"]},
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "analytics_range_invalid"

        unknown = client.get(f"/dataset-versions/{uuid4()}/analytics/summary", params=first_four)
        assert unknown.status_code == 404
        assert unknown.json()["code"] == "dataset_version_not_found"


@pytest.mark.integration
def test_series_enforces_max_points_and_range_query_uses_index(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    version_id = asyncio.run(_seed_known_fixture(temporary_database_url))
    app = _app(temporary_database_url, tmp_path)
    parameters: dict[str, str | int] = {
        "from": "2026-01-01T00:00:00Z",
        "to": "2026-01-11T00:00:00Z",
        "resolution": "hour",
        "max_points": 100,
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(f"/dataset-versions/{version_id}/analytics/series", params=parameters)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["downsampled"] is True
        assert payload["bucket_seconds"] == 10_800
        assert len(payload["points"]) == 80
        assert payload["points"][0]["energy_kwh"] == 3.0
        assert payload["points"][0]["quality_status"] == "mixed"
        assert [point["timestamp"] for point in payload["points"]] == sorted(
            point["timestamp"] for point in payload["points"]
        )

        too_small = client.get(
            f"/dataset-versions/{version_id}/analytics/series",
            params={**parameters, "max_points": 99},
        )
        assert too_small.status_code == 422

    plan = asyncio.run(_range_query_plan(temporary_database_url, version_id))
    assert "ix_hourly_version_time" in plan


@pytest.mark.integration
@pytest.mark.performance
def test_series_query_performance_smoke_is_bounded(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    version_id = asyncio.run(_seed_large_fixture(temporary_database_url, hours=20_000))
    app = _app(temporary_database_url, tmp_path)
    started = time.perf_counter()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            f"/dataset-versions/{version_id}/analytics/series",
            params={
                "from": "2020-01-01T00:00:00Z",
                "to": "2022-04-13T08:00:00Z",
                "resolution": "hour",
                "max_points": 200,
            },
        )
    elapsed = time.perf_counter() - started

    assert response.status_code == 200, response.text
    assert len(response.json()["points"]) <= 200
    assert response.json()["downsampled"] is True
    assert elapsed < 3.0


def _app(database_url: str, tmp_path: Path) -> FastAPI:
    return create_app(
        Settings(
            database_url=SecretStr(database_url),
            artifact_root=tmp_path / "artifacts",
        ),
        PassingReadinessCheck(),
    )


async def _seed_known_fixture(database_url: str) -> UUID:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    dataset_id, version_id = uuid4(), uuid4()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        async with transactional_session(factory) as session:
            session.add(Dataset(id=dataset_id, name="Analytics fixture"))
            session.add(
                DatasetVersion(
                    id=version_id,
                    dataset_id=dataset_id,
                    version_no=1,
                    status="ready",
                    timezone_context="Europe/Kyiv",
                    interval_seconds=3600,
                    quality_policy={},
                    transformation_manifest={},
                )
            )
            await session.flush()
            session.add_all(
                HourlyObservation(
                    dataset_version_id=version_id,
                    hour_start=start + timedelta(hours=hour),
                    timezone_context="Europe/Kyiv",
                    energy_kwh=None if hour == 2 else float(hour % 24 + 1),
                    observed_samples=30 if hour == 2 else 60,
                    expected_samples=60,
                    coverage_ratio=0.5 if hour == 2 else 1.0,
                    imputed_samples=0,
                    max_missing_run=30 if hour == 2 else 0,
                    quality_status="invalid_missing" if hour == 2 else "complete",
                    quality_flags=["missing_samples"] if hour == 2 else [],
                )
                for hour in range(240)
            )
        return version_id
    finally:
        await engine.dispose()


async def _range_query_plan(database_url: str, version_id: UUID) -> str:
    engine = create_database_engine(database_url)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET enable_seqscan = off"))
            rows = await connection.execute(
                text(
                    "EXPLAIN (FORMAT TEXT) SELECT hour_start, energy_kwh "
                    "FROM ts.hourly_observations "
                    "WHERE dataset_version_id = :version_id "
                    "AND hour_start >= :start AND hour_start < :end "
                    "ORDER BY hour_start"
                ),
                {
                    "version_id": version_id,
                    "start": datetime(2026, 1, 1, tzinfo=UTC),
                    "end": datetime(2026, 1, 11, tzinfo=UTC),
                },
            )
            return "\n".join(str(row[0]) for row in rows)
    finally:
        await engine.dispose()


async def _seed_large_fixture(database_url: str, *, hours: int) -> UUID:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    dataset_id, version_id = uuid4(), uuid4()
    try:
        async with transactional_session(factory) as session:
            session.add(Dataset(id=dataset_id, name="Analytics performance fixture"))
            session.add(
                DatasetVersion(
                    id=version_id,
                    dataset_id=dataset_id,
                    version_no=1,
                    status="ready",
                    timezone_context="UTC",
                    interval_seconds=3600,
                    quality_policy={},
                    transformation_manifest={},
                )
            )
            await session.flush()
            await session.execute(
                text(
                    """
                    INSERT INTO ts.hourly_observations (
                        dataset_version_id, hour_start, timezone_context, energy_kwh,
                        observed_samples, expected_samples, coverage_ratio, imputed_samples,
                        max_missing_run, quality_status, quality_flags
                    )
                    SELECT :version_id,
                           TIMESTAMPTZ '2020-01-01 00:00:00+00' + value * INTERVAL '1 hour',
                           'UTC', 1.0 + (value % 24), 60, 60, 1.0, 0, 0, 'complete', '{}'::text[]
                    FROM generate_series(0, :last_hour) AS value
                    """
                ),
                {"version_id": version_id, "last_hour": hours - 1},
            )
        return version_id
    finally:
        await engine.dispose()
