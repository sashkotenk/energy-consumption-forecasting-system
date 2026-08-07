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
    SqlAlchemyQualityRepository,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.database.models import (
    DataQualityIssue,
    DataQualityReport,
    Dataset,
    DatasetVersion,
    RawMeasurement,
)
from energy_forecast.database.session import transactional_session
from energy_forecast.quality.service import QualityService
from tests.integration.conftest import upgrade_database


class PassingReadinessCheck:
    async def check(self) -> None:
        return None


@pytest.mark.integration
def test_quality_reports_are_versioned_persisted_and_paginated(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    version_id = asyncio.run(_seed_fixture(temporary_database_url))
    first, second, persisted = asyncio.run(_evaluate_twice(temporary_database_url, version_id))

    assert first == 1
    assert second == 2
    assert persisted["report_count"] == 2
    issue_count = persisted["issue_count"]
    assert isinstance(issue_count, int)
    assert issue_count > 1
    assert persisted["version_status"] == "ready_for_transformation"
    assert persisted["negative_current"] == -1.0

    app = create_app(
        Settings(
            database_url=SecretStr(temporary_database_url),
            artifact_root=tmp_path / "artifacts",
        ),
        PassingReadinessCheck(),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        latest = client.get(
            f"/dataset-versions/{version_id}/quality",
            params={"page": 1, "page_size": 1},
        )
        assert latest.status_code == 200
        payload = latest.json()
        assert payload["report_version"] == 2
        assert payload["summary"]["total_rows"] == 8
        assert payload["summary"]["exact_duplicates"] == 1
        assert payload["summary"]["conflicting_duplicates"] == 2
        assert payload["summary"]["gap_count"] == 1
        assert payload["page_size"] == 1
        assert len(payload["items"]) == 1
        assert payload["total"] > 1

        historical = client.get(
            f"/dataset-versions/{version_id}/quality",
            params={"report_version": 1, "page": 1, "page_size": 100},
        )
        assert historical.status_code == 200
        assert historical.json()["report_version"] == 1

        missing = client.get(f"/dataset-versions/{uuid4()}/quality")
        assert missing.status_code == 409
        assert missing.json()["code"] == "quality_report_not_ready"


async def _seed_fixture(database_url: str) -> UUID:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    dataset_id = uuid4()
    version_id = uuid4()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    points = (
        (1, 0, 1.0, 4.0),
        (2, 1, 1.1, 4.0),
        (3, 1, 1.1, 4.0),
        (4, 2, 1.2, 4.0),
        (5, 2, 2.0, 4.0),
        (6, 3, None, 4.0),
        (7, 5, 1.3, -1.0),
        (8, 6, 50.0, 4.0),
    )
    try:
        async with transactional_session(factory) as session:
            session.add(Dataset(id=dataset_id, name="Quality fixture", source_type="uploaded"))
            session.add(
                DatasetVersion(
                    id=version_id,
                    dataset_id=dataset_id,
                    version_no=1,
                    status="imported",
                    quality_policy={},
                    transformation_manifest={},
                )
            )
            await session.flush()
            session.add_all(
                RawMeasurement(
                    dataset_version_id=version_id,
                    observed_at=start + timedelta(minutes=minute),
                    source_row_number=number,
                    interval_seconds=60,
                    active_power_kw=power,
                    reactive_power_kw=0.2,
                    voltage_v=230.0,
                    current_a=current,
                    sub_metering_1_wh=1.0,
                    sub_metering_2_wh=2.0,
                    sub_metering_3_wh=3.0,
                    parse_status="valid",
                    quality_flags=[],
                )
                for number, minute, power, current in points
            )
        return version_id
    finally:
        await engine.dispose()


async def _evaluate_twice(
    database_url: str, version_id: UUID
) -> tuple[int, int, dict[str, object]]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    service = QualityService(SqlAlchemyQualityRepository(factory))
    try:
        first = await service.evaluate(version_id)
        second = await service.evaluate(version_id)
        async with factory() as session:
            report_count = int(
                await session.scalar(select(func.count()).select_from(DataQualityReport)) or 0
            )
            issue_count = int(
                await session.scalar(
                    select(func.count(DataQualityIssue.id)).where(
                        DataQualityIssue.report_id == second.id
                    )
                )
                or 0
            )
            version = await session.get(DatasetVersion, version_id)
            assert version is not None
            negative_current = await session.scalar(
                select(RawMeasurement.current_a).where(
                    RawMeasurement.dataset_version_id == version_id,
                    RawMeasurement.source_row_number == 7,
                )
            )
            return (
                first.report_version,
                second.report_version,
                {
                    "report_count": report_count,
                    "issue_count": issue_count,
                    "version_status": version.status,
                    "negative_current": negative_current,
                },
            )
    finally:
        await engine.dispose()
