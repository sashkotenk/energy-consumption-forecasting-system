from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest

from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.models import (
    ArtifactMetadata,
    ArtifactPurpose,
    StoredArtifact,
)
from energy_forecast.artifacts.ports import ArtifactMetadataRepository
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.experiments.models import (
    ExperimentNotFoundError,
    ExperimentRecord,
    ExperimentStatus,
    SensitivityMode,
    WeatherMode,
)
from energy_forecast.experiments.service import ExperimentService
from energy_forecast.exports.models import (
    ExperimentExportFormat,
    ExportArtifactNotFoundError,
    ExportArtifactPurposeError,
    ExportArtifactUnavailableError,
    ForecastExportFormat,
)
from energy_forecast.exports.service import ExportService
from energy_forecast.forecasting.models import (
    ForecastNotFoundError,
    ForecastPoint,
    ForecastRecord,
)
from energy_forecast.forecasting.service import ForecastService
from energy_forecast.ml.registry import AlgorithmType

_FORECAST_ID = UUID("11111111-1111-4111-8111-111111111111")
_EXPERIMENT_ID = UUID("22222222-2222-4222-8222-222222222222")
_DATASET_VERSION_ID = UUID("33333333-3333-4333-8333-333333333333")
_MODEL_RUN_ID = UUID("44444444-4444-4444-8444-444444444444")
_MODEL_ARTIFACT_ID = UUID("55555555-5555-4555-8555-555555555555")
_ORIGIN = datetime(2026, 1, 1, tzinfo=UTC)


class _MetadataRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, ArtifactMetadata] = {}

    async def add(
        self,
        stored: StoredArtifact,
        *,
        purpose: ArtifactPurpose,
        media_type: str,
        original_name: str | None,
    ) -> ArtifactMetadata:
        metadata = ArtifactMetadata(
            id=uuid4(),
            purpose=purpose,
            storage_key=stored.storage_key,
            original_name=original_name,
            media_type=media_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            created_at=datetime.now(UTC),
        )
        self.rows[metadata.id] = metadata
        return metadata

    async def get(self, artifact_id: UUID) -> ArtifactMetadata | None:
        return self.rows.get(artifact_id)

    async def find_by_sha256(self, checksum: str) -> Sequence[ArtifactMetadata]:
        return tuple(row for row in self.rows.values() if row.sha256 == checksum)

    async def delete_if_unreferenced(self, artifact_id: UUID) -> ArtifactMetadata | None:
        return self.rows.pop(artifact_id, None)


class _ForecastSource:
    async def get(self, forecast_id: UUID) -> ForecastRecord:
        if forecast_id != _FORECAST_ID:
            raise ForecastNotFoundError("missing")
        points = tuple(
            ForecastPoint(
                horizon=horizon,
                target_time=_ORIGIN + timedelta(hours=horizon),
                predicted_energy_kwh=float(horizon) / 10,
            )
            for horizon in range(1, 25)
        )
        return ForecastRecord(
            id=_FORECAST_ID,
            model_run_id=_MODEL_RUN_ID,
            dataset_version_id=_DATASET_VERSION_ID,
            artifact_id=_MODEL_ARTIFACT_ID,
            bundle_sha256="a" * 64,
            algorithm=AlgorithmType.RIDGE,
            feature_schema_version="base_v1",
            origin=_ORIGIN,
            timezone="UTC",
            status="completed",
            total_energy_kwh=sum(point.predicted_energy_kwh for point in points),
            points=points,
            created_at=_ORIGIN,
            completed_at=_ORIGIN,
        )


class _ExperimentSource:
    async def get(self, experiment_id: UUID) -> ExperimentRecord:
        if experiment_id != _EXPERIMENT_ID:
            raise ExperimentNotFoundError("missing")
        return ExperimentRecord(
            id=_EXPERIMENT_ID,
            dataset_version_id=_DATASET_VERSION_ID,
            job_id=uuid4(),
            name="Export test",
            status=ExperimentStatus.COMPLETED,
            weather_mode=WeatherMode.WITHOUT_WEATHER,
            sensitivity_mode=SensitivityMode.COMPLETE_ONLY,
            algorithms=(AlgorithmType.RIDGE,),
            result_manifest={"schema": "experiment-result/v1", "status": "completed"},
            failure_code=None,
            failure_detail=None,
            created_at=_ORIGIN,
            started_at=_ORIGIN,
            finished_at=_ORIGIN,
        )

    async def comparison(self, experiment_id: UUID) -> tuple[dict[str, object], ...]:
        if experiment_id != _EXPERIMENT_ID:
            raise ExperimentNotFoundError("missing")
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
                "fold_metrics": [],
                "horizon_metrics": [],
            },
        )


def _service(tmp_path: Path) -> tuple[ExportService, _MetadataRepository, Path]:
    root = tmp_path / "artifacts"
    metadata = _MetadataRepository()
    artifacts = ArtifactService(
        LocalArtifactStore(root),
        cast(ArtifactMetadataRepository, metadata),
    )
    service = ExportService(
        cast(ForecastService, _ForecastSource()),
        cast(ExperimentService, _ExperimentSource()),
        artifacts,
    )
    return service, metadata, root


def test_export_service_materializes_all_bounded_formats_with_checksums(tmp_path: Path) -> None:
    service, metadata, root = _service(tmp_path)

    async def exercise() -> list[ArtifactMetadata]:
        return [
            await service.export_forecast(_FORECAST_ID, ForecastExportFormat.CSV),
            await service.export_forecast(_FORECAST_ID, ForecastExportFormat.CHART_JSON),
            await service.export_experiment(_EXPERIMENT_ID, ExperimentExportFormat.METRICS_CSV),
            await service.export_experiment(_EXPERIMENT_ID, ExperimentExportFormat.METRICS_JSON),
            await service.export_experiment(_EXPERIMENT_ID, ExperimentExportFormat.MANIFEST_JSON),
        ]

    exports = asyncio.run(exercise())

    assert [artifact.purpose for artifact in exports] == [
        ArtifactPurpose.FORECAST_EXPORT,
        ArtifactPurpose.CHART,
        ArtifactPurpose.METRICS,
        ArtifactPurpose.METRICS,
        ArtifactPurpose.MANIFEST,
    ]
    assert len(metadata.rows) == 5
    for artifact in exports:
        path = root / artifact.storage_key
        assert path.is_file()
        assert path.stat().st_size == artifact.size_bytes
        assert len(artifact.sha256) == 64
        if artifact.original_name is not None:
            assert str(root.resolve()) not in artifact.original_name


def test_download_allowlist_rejects_non_export_and_missing_content(tmp_path: Path) -> None:
    service, metadata, root = _service(tmp_path)
    allowed = asyncio.run(service.export_forecast(_FORECAST_ID, ForecastExportFormat.CSV))

    forbidden = ArtifactMetadata(
        id=uuid4(),
        purpose=ArtifactPurpose.MODEL,
        storage_key=allowed.storage_key,
        original_name="model.joblib",
        media_type="application/octet-stream",
        size_bytes=allowed.size_bytes,
        sha256=allowed.sha256,
        created_at=datetime.now(UTC),
    )
    metadata.rows[forbidden.id] = forbidden

    with pytest.raises(ExportArtifactPurposeError):
        asyncio.run(service.open_download(forbidden.id))
    with pytest.raises(ExportArtifactNotFoundError):
        asyncio.run(service.open_download(uuid4()))

    (root / allowed.storage_key).unlink()
    with pytest.raises(ExportArtifactUnavailableError):
        asyncio.run(service.open_download(allowed.id))


def test_download_filename_is_sanitized_even_if_metadata_is_hostile(tmp_path: Path) -> None:
    service, metadata, _ = _service(tmp_path)
    artifact = asyncio.run(service.export_forecast(_FORECAST_ID, ForecastExportFormat.CSV))
    metadata.rows[artifact.id] = ArtifactMetadata(
        id=artifact.id,
        purpose=artifact.purpose,
        storage_key=artifact.storage_key,
        original_name="../../private\\evil\r\nHeader: value.csv",
        media_type=artifact.media_type,
        size_bytes=artifact.size_bytes,
        sha256=artifact.sha256,
        created_at=artifact.created_at,
    )

    download = asyncio.run(service.open_download(artifact.id))
    try:
        assert "/" not in download.filename
        assert "\\" not in download.filename
        assert "\r" not in download.filename
        assert "\n" not in download.filename
        assert ":" not in download.filename
    finally:
        download.stream.close()
