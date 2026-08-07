from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from energy_forecast.api import create_app
from energy_forecast.artifacts import (
    ArtifactPurpose,
    ArtifactService,
    LocalArtifactStore,
)
from energy_forecast.config import Settings
from energy_forecast.database import (
    SqlAlchemyArtifactMetadataRepository,
    create_database_engine,
    create_session_factory,
    transactional_session,
)
from energy_forecast.database.models import Artifact
from energy_forecast.experiments.models import (
    ExperimentNotFoundError,
    ExperimentRecord,
    ExperimentStatus,
    SensitivityMode,
    WeatherMode,
)
from energy_forecast.experiments.service import ExperimentService
from energy_forecast.forecasting.models import (
    ForecastNotFoundError,
    ForecastPoint,
    ForecastRecord,
)
from energy_forecast.forecasting.service import ForecastService
from energy_forecast.ml.registry import AlgorithmType
from tests.integration.conftest import upgrade_database

pytestmark = pytest.mark.integration

_FORECAST_ID = UUID("11111111-1111-4111-8111-111111111111")
_MODEL_RUN_ID = UUID("22222222-2222-4222-8222-222222222222")
_DATASET_VERSION_ID = UUID("33333333-3333-4333-8333-333333333333")
_MODEL_ARTIFACT_ID = UUID("44444444-4444-4444-8444-444444444444")
_EXPERIMENT_ID = UUID("55555555-5555-4555-8555-555555555555")
_FAILED_EXPERIMENT_ID = UUID("77777777-7777-4777-8777-777777777777")
_ORIGIN = datetime(2026, 1, 2, 0, tzinfo=UTC)


class _Ready:
    async def check(self) -> None:
        return None


class _ForecastSource:
    def __init__(self, record: ForecastRecord) -> None:
        self._record = record

    async def get(self, forecast_id: UUID) -> ForecastRecord:
        if forecast_id != self._record.id:
            raise ForecastNotFoundError("Forecast was not found")
        return self._record


class _ExperimentSource:
    def __init__(self, records: dict[UUID, ExperimentRecord]) -> None:
        self._records = records

    async def get(self, experiment_id: UUID) -> ExperimentRecord:
        try:
            return self._records[experiment_id]
        except KeyError as error:
            raise ExperimentNotFoundError("Experiment was not found") from error

    async def comparison(self, experiment_id: UUID) -> tuple[dict[str, object], ...]:
        if experiment_id not in self._records:
            raise ExperimentNotFoundError("Experiment was not found")
        return (
            {
                "model_run_id": str(_MODEL_RUN_ID),
                "algorithm": "ridge",
                "status": "completed",
                "hyperparameters": {"alpha": 1.0},
                "mean_cv_mae": 0.2,
                "std_cv_mae": 0.01,
                "final_mae": 0.21,
                "final_rmse": 0.3,
                "final_smape": 9.0,
                "predict_ms_median": 2.0,
                "is_recommended": True,
                "failure_code": None,
                "fold_metrics": [
                    {
                        "fold_no": 1,
                        "evaluation_rows": 10,
                        "mae": 0.2,
                        "rmse": 0.3,
                        "smape": 8.0,
                    }
                ],
                "horizon_metrics": [
                    {
                        "evaluation_scope": "final_test",
                        "horizon": 1,
                        "mae": 0.1,
                        "rmse": 0.2,
                        "smape": 7.0,
                    }
                ],
            },
        )


def _forecast() -> ForecastRecord:
    points = tuple(
        ForecastPoint(
            horizon=horizon,
            target_time=_ORIGIN + timedelta(hours=horizon),
            predicted_energy_kwh=float(horizon) / 10,
            actual_energy_kwh=None,
        )
        for horizon in range(1, 25)
    )
    return ForecastRecord(
        id=_FORECAST_ID,
        model_run_id=_MODEL_RUN_ID,
        dataset_version_id=_DATASET_VERSION_ID,
        artifact_id=_MODEL_ARTIFACT_ID,
        bundle_sha256="b" * 64,
        algorithm=AlgorithmType.RIDGE,
        feature_schema_version="base_v1",
        origin=_ORIGIN,
        timezone="Europe/Kyiv",
        status="completed",
        total_energy_kwh=sum(point.predicted_energy_kwh for point in points),
        points=points,
        created_at=_ORIGIN,
        completed_at=_ORIGIN + timedelta(seconds=1),
    )


def _experiment(experiment_id: UUID, status: ExperimentStatus) -> ExperimentRecord:
    completed = status is ExperimentStatus.COMPLETED
    return ExperimentRecord(
        id=experiment_id,
        dataset_version_id=_DATASET_VERSION_ID,
        job_id=uuid4(),
        name="Export integration",
        status=status,
        weather_mode=WeatherMode.WITHOUT_WEATHER,
        sensitivity_mode=SensitivityMode.COMPLETE_ONLY,
        algorithms=(AlgorithmType.RIDGE,),
        result_manifest=(
            {
                "schema": "experiment-result/v1",
                "experiment_id": str(experiment_id),
                "status": "completed",
            }
            if completed
            else None
        ),
        failure_code=None if completed else "training_failed",
        failure_detail=None if completed else "synthetic failure",
        created_at=_ORIGIN,
        started_at=_ORIGIN,
        finished_at=_ORIGIN + timedelta(minutes=1),
    )


def _settings(database_url: str, artifact_root: Path) -> Settings:
    return Settings(database_url=SecretStr(database_url), artifact_root=artifact_root)


def _app(database_url: str, artifact_root: Path) -> FastAPI:
    experiments = {
        _EXPERIMENT_ID: _experiment(_EXPERIMENT_ID, ExperimentStatus.COMPLETED),
        _FAILED_EXPERIMENT_ID: _experiment(_FAILED_EXPERIMENT_ID, ExperimentStatus.FAILED),
    }
    return create_app(
        _settings(database_url, artifact_root),
        readiness_check=_Ready(),
        forecast_service=cast(ForecastService, _ForecastSource(_forecast())),
        experiment_service=cast(ExperimentService, _ExperimentSource(experiments)),
    )


async def _read_artifacts(database_url: str) -> tuple[tuple[UUID, str, int, str], ...]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with transactional_session(factory) as session:
            rows = (
                await session.scalars(select(Artifact).order_by(Artifact.created_at, Artifact.id))
            ).all()
            return tuple((row.id, row.sha256, row.size_bytes, row.kind) for row in rows)
    finally:
        await engine.dispose()


async def _seed_download_artifacts(
    database_url: str,
    artifact_root: Path,
) -> dict[str, UUID]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    service = ArtifactService(
        LocalArtifactStore(artifact_root),
        SqlAlchemyArtifactMetadataRepository(factory),
    )
    try:
        malicious = await service.create(
            BytesIO(b"safe export bytes\n"),
            purpose=ArtifactPurpose.FORECAST_EXPORT,
            media_type="text/csv; charset=utf-8",
            suffix=".csv",
            original_name="../../private\\evil\r\nSet-Cookie: session=x.csv",
        )
        forbidden = await service.create(
            BytesIO(b"raw dataset"),
            purpose=ArtifactPurpose.RAW_DATASET,
            media_type="text/csv; charset=utf-8",
            suffix=".csv",
            original_name="raw.csv",
        )
        deleted = await service.create(
            BytesIO(b"deleted"),
            purpose=ArtifactPurpose.METRICS,
            media_type="application/json",
            suffix=".json",
            original_name="deleted.json",
        )
        await service.delete(deleted.id)
        unavailable = await service.create(
            BytesIO(b"missing bytes"),
            purpose=ArtifactPurpose.MANIFEST,
            media_type="application/json",
            suffix=".json",
            original_name="missing.json",
        )
        (artifact_root / unavailable.storage_key).unlink()
        return {
            "malicious": malicious.id,
            "forbidden": forbidden.id,
            "deleted": deleted.id,
            "unavailable": unavailable.id,
        }
    finally:
        await engine.dispose()


def test_all_task16_exports_persist_checksum_and_download(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    artifact_root = tmp_path / "artifacts"
    app = _app(temporary_database_url, artifact_root)
    created: list[tuple[str, bytes, str]] = []

    with TestClient(app) as client:
        requests = (
            (f"/forecasts/{_FORECAST_ID}/exports", {"format": "csv"}),
            (f"/forecasts/{_FORECAST_ID}/exports", {"format": "chart_json"}),
            (f"/experiments/{_EXPERIMENT_ID}/exports", {"format": "metrics_csv"}),
            (f"/experiments/{_EXPERIMENT_ID}/exports", {"format": "metrics_json"}),
            (f"/experiments/{_EXPERIMENT_ID}/exports", {"format": "manifest_json"}),
        )
        for url, body in requests:
            response = client.post(url, json=body)
            assert response.status_code == 201, response.text
            metadata = response.json()
            assert "storage_key" not in metadata
            assert len(metadata["sha256"]) == 64
            assert metadata["download_url"] == f"/artifacts/{metadata['id']}/download"

            download = client.get(metadata["download_url"])
            assert download.status_code == 200
            assert download.headers["x-content-sha256"] == metadata["sha256"]
            assert int(download.headers["content-length"]) == metadata["size_bytes"]
            assert sha256(download.content).hexdigest() == metadata["sha256"]
            assert str(artifact_root.resolve()) not in download.headers["content-disposition"]
            created.append((metadata["id"], download.content, metadata["purpose"]))

    rows = asyncio.run(_read_artifacts(temporary_database_url))
    persisted = {
        str(row_id): (checksum, size_bytes, kind) for row_id, checksum, size_bytes, kind in rows
    }
    assert len(created) == 5
    for artifact_id, content, purpose in created:
        checksum, size_bytes, kind = persisted[artifact_id]
        assert checksum == sha256(content).hexdigest()
        assert size_bytes == len(content)
        assert kind == purpose


def test_download_security_and_problem_details_for_deleted_failed_or_wrong_purpose(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    artifact_root = tmp_path / "artifacts"
    seeded = asyncio.run(_seed_download_artifacts(temporary_database_url, artifact_root))
    app = _app(temporary_database_url, artifact_root)

    with TestClient(app, raise_server_exceptions=False) as client:
        malicious = client.get(f"/artifacts/{seeded['malicious']}/download")
        forbidden = client.get(f"/artifacts/{seeded['forbidden']}/download")
        deleted = client.get(f"/artifacts/{seeded['deleted']}/download")
        unavailable = client.get(f"/artifacts/{seeded['unavailable']}/download")
        missing = client.get(f"/artifacts/{uuid4()}/download")
        failed_source = client.post(
            f"/experiments/{_FAILED_EXPERIMENT_ID}/exports",
            json={"format": "manifest_json"},
        )

    disposition = malicious.headers["content-disposition"]
    assert malicious.status_code == 200
    assert malicious.content == b"safe export bytes\n"
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "/" not in disposition.split("filename=", maxsplit=1)[1]
    assert "\\" not in disposition
    assert "Set-Cookie:" not in disposition
    assert str(artifact_root.resolve()) not in disposition

    assert forbidden.status_code == 403
    assert forbidden.headers["content-type"].startswith("application/problem+json")
    assert forbidden.json()["code"] == "export_artifact_forbidden"

    assert deleted.status_code == 404
    assert deleted.json()["code"] == "export_artifact_not_found"
    assert missing.status_code == 404
    assert missing.json()["code"] == "export_artifact_not_found"

    assert unavailable.status_code == 410
    assert unavailable.json()["code"] == "export_artifact_unavailable"
    assert str(artifact_root.resolve()) not in unavailable.text

    assert failed_source.status_code == 409
    assert failed_source.json()["code"] == "export_source_failed"
