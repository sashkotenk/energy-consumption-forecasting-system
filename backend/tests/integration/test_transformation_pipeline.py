from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from energy_forecast.api import create_app
from energy_forecast.config import Settings
from energy_forecast.database import (
    SqlAlchemyJobQueue,
    SqlAlchemyTransformationRepository,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.database.models import (
    Dataset,
    DatasetVersion,
    HourlyObservation,
    RawMeasurement,
    TransformationRun,
)
from energy_forecast.database.session import transactional_session
from energy_forecast.jobs.domain import JobStatus, JobType
from energy_forecast.jobs.worker import JobHandlerRegistry, JobWorker
from energy_forecast.transformations.service import TransformationHandler
from tests.integration.conftest import upgrade_database


class PassingReadinessCheck:
    async def check(self) -> None:
        return None


@pytest.mark.integration
def test_api_job_worker_persists_immutable_hourly_version_in_timescaledb(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    source_id = asyncio.run(_seed_source(temporary_database_url))
    app = create_app(
        Settings(
            database_url=SecretStr(temporary_database_url),
            artifact_root=tmp_path / "artifacts",
        ),
        PassingReadinessCheck(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/dataset-versions/{source_id}/transformations",
            json={
                "short_gap_limit_minutes": 5,
                "minimum_hour_coverage": 0.9,
                "duplicate_policy": "reject",
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()

    state = asyncio.run(
        _execute_transformation(
            temporary_database_url,
            job_id=UUID(accepted["job_id"]),
            run_id=UUID(accepted["run_id"]),
            source_id=source_id,
            target_id=UUID(accepted["target_version_id"]),
        )
    )

    assert state == {
        "executed": True,
        "job_status": JobStatus.SUCCEEDED,
        "run_status": "completed",
        "target_status": "ready",
        "source_raw_count": 60,
        "target_raw_count": 0,
        "hourly_count": 1,
        "energy_kwh": pytest.approx(1.0),
        "quality_status": "complete",
        "parent_version_id": source_id,
    }


@pytest.mark.integration
def test_transformation_infers_hourly_cadence_when_import_metadata_is_missing(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    source_id = asyncio.run(_seed_hourly_source_without_interval(temporary_database_url))
    app = create_app(
        Settings(
            database_url=SecretStr(temporary_database_url),
            artifact_root=tmp_path / "artifacts",
        ),
        PassingReadinessCheck(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/dataset-versions/{source_id}/transformations",
            json={
                "short_gap_limit_minutes": 5,
                "minimum_hour_coverage": 0.9,
                "duplicate_policy": "reject",
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()

    state = asyncio.run(
        _execute_transformation(
            temporary_database_url,
            job_id=UUID(accepted["job_id"]),
            run_id=UUID(accepted["run_id"]),
            source_id=source_id,
            target_id=UUID(accepted["target_version_id"]),
        )
    )

    assert state == {
        "executed": True,
        "job_status": JobStatus.SUCCEEDED,
        "run_status": "completed",
        "target_status": "ready",
        "source_raw_count": 24,
        "target_raw_count": 0,
        "hourly_count": 24,
        "energy_kwh": pytest.approx(1.25),
        "quality_status": "complete",
        "parent_version_id": source_id,
    }


async def _seed_source(database_url: str) -> UUID:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    dataset_id, source_id = uuid4(), uuid4()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        async with transactional_session(factory) as session:
            session.add(Dataset(id=dataset_id, name="Transformation fixture"))
            session.add(
                DatasetVersion(
                    id=source_id,
                    dataset_id=dataset_id,
                    version_no=1,
                    status="ready_for_transformation",
                    timezone_context="UTC",
                    interval_seconds=60,
                    row_count=60,
                    valid_row_count=60,
                    min_timestamp=start,
                    max_timestamp=start + timedelta(minutes=59),
                    quality_policy={"report_version": 1},
                    transformation_manifest={},
                )
            )
            await session.flush()
            session.add_all(
                RawMeasurement(
                    dataset_version_id=source_id,
                    observed_at=start + timedelta(minutes=minute),
                    source_row_number=minute + 1,
                    timezone_context="UTC",
                    interval_seconds=60,
                    active_power_kw=1.0,
                    reactive_power_kw=0.2,
                    voltage_v=230.0,
                    current_a=4.0,
                    parse_status="valid",
                    quality_flags=[],
                )
                for minute in range(60)
            )
        return source_id
    finally:
        await engine.dispose()


async def _seed_hourly_source_without_interval(database_url: str) -> UUID:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    dataset_id, source_id = uuid4(), uuid4()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    try:
        async with transactional_session(factory) as session:
            session.add(Dataset(id=dataset_id, name="Generic hourly fixture"))
            session.add(
                DatasetVersion(
                    id=source_id,
                    dataset_id=dataset_id,
                    version_no=1,
                    status="ready_for_transformation",
                    timezone_context="UTC",
                    interval_seconds=None,
                    row_count=24,
                    valid_row_count=24,
                    min_timestamp=start,
                    max_timestamp=start + timedelta(hours=23),
                    quality_policy={"report_version": 1},
                    transformation_manifest={},
                )
            )
            await session.flush()
            session.add_all(
                RawMeasurement(
                    dataset_version_id=source_id,
                    observed_at=start + timedelta(hours=hour),
                    source_row_number=hour + 1,
                    timezone_context="UTC",
                    interval_seconds=None,
                    energy_kwh=1.25,
                    parse_status="valid",
                    quality_flags=[],
                )
                for hour in range(24)
            )
        return source_id
    finally:
        await engine.dispose()


async def _execute_transformation(
    database_url: str,
    *,
    job_id: UUID,
    run_id: UUID,
    source_id: UUID,
    target_id: UUID,
) -> dict[str, object]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    queue = SqlAlchemyJobQueue(factory)
    registry = JobHandlerRegistry()
    registry.register(
        JobType.DATA_TRANSFORMATION,
        TransformationHandler(SqlAlchemyTransformationRepository(factory), batch_size=1),
    )
    worker = JobWorker(
        queue,
        registry,
        worker_id="transformation-test-worker",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=1,
        stale_after_seconds=30,
        recovery_batch_size=10,
    )
    try:
        executed = await worker.run_once()
        job = await queue.get(job_id)
        async with factory() as session:
            run = await session.get(TransformationRun, run_id)
            target = await session.get(DatasetVersion, target_id)
            hourly = await session.get(
                HourlyObservation, (target_id, datetime(2026, 1, 1, tzinfo=UTC))
            )
            if hourly is None:
                hourly = await session.scalar(
                    select(HourlyObservation)
                    .where(HourlyObservation.dataset_version_id == target_id)
                    .order_by(HourlyObservation.hour_start)
                    .limit(1)
                )
            source_raw_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(RawMeasurement)
                    .where(RawMeasurement.dataset_version_id == source_id)
                )
                or 0
            )
            target_raw_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(RawMeasurement)
                    .where(RawMeasurement.dataset_version_id == target_id)
                )
                or 0
            )
            hourly_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(HourlyObservation)
                    .where(HourlyObservation.dataset_version_id == target_id)
                )
                or 0
            )
            assert job is not None and run is not None and target is not None and hourly is not None
            return {
                "executed": executed,
                "job_status": job.status,
                "run_status": run.status,
                "target_status": target.status,
                "source_raw_count": source_raw_count,
                "target_raw_count": target_raw_count,
                "hourly_count": hourly_count,
                "energy_kwh": hourly.energy_kwh,
                "quality_status": hourly.quality_status,
                "parent_version_id": target.parent_version_id,
            }
    finally:
        await engine.dispose()
