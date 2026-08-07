from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from energy_forecast.api import create_app
from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.config import Settings
from energy_forecast.database import (
    SqlAlchemyArtifactMetadataRepository,
    SqlAlchemyDatasetImportRepository,
    SqlAlchemyJobQueue,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.database.models import (
    DatasetImport,
    DatasetImportError,
    DatasetVersion,
    RawMeasurement,
)
from energy_forecast.datasets.importing import DatasetImportHandler
from energy_forecast.jobs.domain import JobType
from energy_forecast.jobs.worker import JobHandlerRegistry, JobWorker
from tests.integration.conftest import upgrade_database


class PassingReadinessCheck:
    async def check(self) -> None:
        return None


@pytest.mark.integration
def test_import_worker_batch_inserts_rows_and_completes_restart_safe_version(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    artifact_root = tmp_path / "artifacts"
    settings = Settings(database_url=SecretStr(temporary_database_url), artifact_root=artifact_root)
    app = create_app(settings, PassingReadinessCheck())
    content = (
        b"Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity;"
        b"Sub_metering_1;Sub_metering_2;Sub_metering_3\n"
        b"16/12/2006;17:24:00;4.216;0.418;234.840;18.400;0;1;17\n"
        b"16/12/2006;17:25:00;bad;0.436;233.630;18.400;0;;16\n"
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        dataset_id = client.post("/datasets", json={"name": "UCI parser"}).json()["id"]
        accepted = client.post(
            f"/datasets/{dataset_id}/imports",
            data={"import_profile": "uci"},
            files={"file": ("uci.txt", content, "text/plain")},
        )
        assert accepted.status_code == 202
        import_id = UUID(accepted.json()["import_id"])

    state = asyncio.run(_execute_import(temporary_database_url, artifact_root, import_id))

    assert state["executed"] is True
    assert state["import_status"] == "completed"
    assert state["version_status"] == "imported"
    assert state["raw_count"] == 2
    assert state["error_count"] == 1
    assert state["row_count"] == 2
    assert state["valid_row_count"] == 1
    report = state["report"]
    assert isinstance(report, dict)
    assert report["missing_tokens_preserved_as_null"] is True


async def _execute_import(
    database_url: str, artifact_root: Path, import_id: UUID
) -> dict[str, object]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    queue = SqlAlchemyJobQueue(factory)
    artifacts = ArtifactService(
        LocalArtifactStore(artifact_root), SqlAlchemyArtifactMetadataRepository(factory)
    )
    registry = JobHandlerRegistry()
    registry.register(
        JobType.DATASET_IMPORT,
        DatasetImportHandler(SqlAlchemyDatasetImportRepository(factory), artifacts, batch_size=1),
    )
    worker = JobWorker(
        queue,
        registry,
        worker_id="import-test-worker",
        poll_interval_seconds=0.01,
        heartbeat_interval_seconds=1,
        stale_after_seconds=30,
        recovery_batch_size=10,
    )
    try:
        executed = await worker.run_once()
        async with factory() as session:
            import_row = await session.get(DatasetImport, import_id)
            assert import_row is not None
            version = await session.get(DatasetVersion, import_row.dataset_version_id)
            assert version is not None
            raw_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(RawMeasurement)
                    .where(RawMeasurement.dataset_version_id == version.id)
                )
                or 0
            )
            error_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(DatasetImportError)
                    .where(DatasetImportError.import_id == import_id)
                )
                or 0
            )
            return {
                "executed": executed,
                "import_status": import_row.status,
                "version_status": version.status,
                "raw_count": raw_count,
                "error_count": error_count,
                "row_count": version.row_count,
                "valid_row_count": version.valid_row_count,
                "report": dict(import_row.import_report or {}),
            }
    finally:
        await engine.dispose()
