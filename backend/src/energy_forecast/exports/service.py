"""Create bounded export artifacts and authorize controlled downloads."""

from __future__ import annotations

from io import BytesIO
from uuid import UUID

from energy_forecast.artifacts.models import (
    ArtifactContentMissingError,
    ArtifactMetadata,
    ArtifactNotFoundError,
    ArtifactPurpose,
)
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.experiments.models import (
    ExperimentNotFoundError,
    ExperimentStatus,
)
from energy_forecast.experiments.service import ExperimentService
from energy_forecast.exports.models import (
    ExperimentExportFormat,
    ExportArtifactNotFoundError,
    ExportArtifactPurposeError,
    ExportArtifactUnavailableError,
    ExportDownload,
    ExportSourceFailedError,
    ExportSourceNotFoundError,
    ExportSourceUnavailableError,
    ForecastExportFormat,
)
from energy_forecast.exports.serialization import (
    experiment_manifest_json,
    experiment_metrics_csv,
    experiment_metrics_json,
    forecast_chart_json,
    forecast_csv,
    safe_download_filename,
)
from energy_forecast.forecasting.models import ForecastNotFoundError
from energy_forecast.forecasting.service import ForecastService

_DOWNLOADABLE_PURPOSES = frozenset(
    {
        ArtifactPurpose.FORECAST_EXPORT,
        ArtifactPurpose.METRICS,
        ArtifactPurpose.CHART,
        ArtifactPurpose.MANIFEST,
    }
)


class ExportService:
    """Materialize bounded exports through the existing artifact and domain services."""

    def __init__(
        self,
        forecasts: ForecastService,
        experiments: ExperimentService,
        artifacts: ArtifactService,
    ) -> None:
        self._forecasts = forecasts
        self._experiments = experiments
        self._artifacts = artifacts

    async def export_forecast(
        self,
        forecast_id: UUID,
        export_format: ForecastExportFormat,
    ) -> ArtifactMetadata:
        try:
            record = await self._forecasts.get(forecast_id)
        except ForecastNotFoundError as error:
            raise ExportSourceNotFoundError("Forecast was not found") from error
        if record.status != "completed":
            raise ExportSourceUnavailableError("Forecast is not completed")

        if export_format is ForecastExportFormat.CSV:
            return await self._create_artifact(
                forecast_csv(record),
                purpose=ArtifactPurpose.FORECAST_EXPORT,
                media_type="text/csv; charset=utf-8",
                suffix=".csv",
                original_name=f"forecast-{record.id}.csv",
            )
        return await self._create_artifact(
            forecast_chart_json(record),
            purpose=ArtifactPurpose.CHART,
            media_type="application/json",
            suffix=".json",
            original_name=f"forecast-{record.id}-chart-data.json",
        )

    async def export_experiment(
        self,
        experiment_id: UUID,
        export_format: ExperimentExportFormat,
    ) -> ArtifactMetadata:
        try:
            experiment = await self._experiments.get(experiment_id)
        except ExperimentNotFoundError as error:
            raise ExportSourceNotFoundError("Experiment was not found") from error
        if experiment.status is ExperimentStatus.FAILED:
            raise ExportSourceFailedError("Failed experiment has no successful export result")
        if experiment.status is not ExperimentStatus.COMPLETED:
            raise ExportSourceUnavailableError("Experiment is not completed")

        if export_format is ExperimentExportFormat.MANIFEST_JSON:
            if experiment.result_manifest is None:
                raise ExportSourceUnavailableError("Completed experiment is missing its manifest")
            payload = experiment_manifest_json(experiment)
            return await self._create_artifact(
                payload,
                purpose=ArtifactPurpose.MANIFEST,
                media_type="application/json",
                suffix=".json",
                original_name=f"experiment-{experiment.id}-manifest.json",
            )

        try:
            comparison = await self._experiments.comparison(experiment_id)
        except ExperimentNotFoundError as error:
            raise ExportSourceNotFoundError("Experiment was not found") from error
        if export_format is ExperimentExportFormat.METRICS_CSV:
            return await self._create_artifact(
                experiment_metrics_csv(experiment, comparison),
                purpose=ArtifactPurpose.METRICS,
                media_type="text/csv; charset=utf-8",
                suffix=".csv",
                original_name=f"experiment-{experiment.id}-metrics.csv",
            )
        return await self._create_artifact(
            experiment_metrics_json(experiment, comparison),
            purpose=ArtifactPurpose.METRICS,
            media_type="application/json",
            suffix=".json",
            original_name=f"experiment-{experiment.id}-metrics.json",
        )

    async def open_download(self, artifact_id: UUID) -> ExportDownload:
        try:
            metadata = await self._artifacts.get_metadata(artifact_id)
        except ArtifactNotFoundError as error:
            raise ExportArtifactNotFoundError("Export artifact was not found") from error
        if metadata.purpose not in _DOWNLOADABLE_PURPOSES:
            raise ExportArtifactPurposeError("Artifact purpose is not downloadable")
        try:
            stream = await self._artifacts.open(artifact_id)
        except ArtifactNotFoundError as error:
            raise ExportArtifactNotFoundError("Export artifact was not found") from error
        except ArtifactContentMissingError as error:
            raise ExportArtifactUnavailableError(
                "Export artifact content is unavailable"
            ) from error

        fallback = f"export-{metadata.id}"
        filename = safe_download_filename(metadata.original_name, fallback=fallback)
        return ExportDownload(metadata=metadata, filename=filename, stream=stream)

    async def _create_artifact(
        self,
        payload: bytes,
        *,
        purpose: ArtifactPurpose,
        media_type: str,
        suffix: str,
        original_name: str,
    ) -> ArtifactMetadata:
        return await self._artifacts.create(
            BytesIO(payload),
            purpose=purpose,
            media_type=media_type,
            suffix=suffix,
            original_name=original_name,
        )
