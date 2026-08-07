"""Restart-safe dataset import orchestration for the background worker."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.datasets.models import ImportProfile
from energy_forecast.datasets.parsers import ParseBatch, ParsedMeasurement, create_parser
from energy_forecast.jobs.domain import JobCancellationRequested
from energy_forecast.jobs.worker import JobExecutionContext
from energy_forecast.quality.models import StoredQualityReport


class DatasetImportRepository(Protocol):
    async def prepare(self, *, import_id: UUID, dataset_version_id: UUID) -> None: ...

    async def insert_batch(
        self,
        *,
        import_id: UUID,
        dataset_version_id: UUID,
        batch: ParseBatch,
    ) -> None: ...

    async def complete(
        self,
        *,
        import_id: UUID,
        dataset_version_id: UUID,
        report: dict[str, Any],
        interval_seconds: int | None,
        min_timestamp: datetime | None,
        max_timestamp: datetime | None,
    ) -> None: ...

    async def fail(self, *, import_id: UUID, dataset_version_id: UUID, cancelled: bool) -> None: ...


class QualityEvaluator(Protocol):
    async def evaluate(self, dataset_version_id: UUID) -> StoredQualityReport: ...


class DatasetImportHandler:
    """Read one immutable artifact in bounded chunks and persist each batch transactionally."""

    def __init__(
        self,
        repository: DatasetImportRepository,
        artifacts: ArtifactService,
        *,
        batch_size: int = 5_000,
        quality_evaluator: QualityEvaluator | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._repository = repository
        self._artifacts = artifacts
        self._batch_size = batch_size
        self._quality_evaluator = quality_evaluator

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        payload = context.payload
        import_id = UUID(_required_payload(payload, "import_id"))
        version_id = UUID(_required_payload(payload, "dataset_version_id"))
        artifact_id = UUID(_required_payload(payload, "artifact_id"))
        profile = ImportProfile(_required_payload(payload, "import_profile"))
        raw_options = payload.get("import_options")
        options = raw_options if isinstance(raw_options, dict) else {}
        detected = payload.get("detected_format")
        detected_delimiter = detected.get("delimiter") if isinstance(detected, dict) else None
        parser = create_parser(profile, options, detected_delimiter=detected_delimiter)
        await self._repository.prepare(import_id=import_id, dataset_version_id=version_id)

        total_rows = 0
        stored_rows = 0
        valid_rows = 0
        issue_count = 0
        min_timestamp: datetime | None = None
        max_timestamp: datetime | None = None
        interval_seconds: int | None = 60 if profile is ImportProfile.UCI else None
        stream = await self._artifacts.open(artifact_id)
        try:
            for batch in parser.parse_batches(stream, batch_size=self._batch_size):
                context.raise_if_cancel_requested()
                await self._repository.insert_batch(
                    import_id=import_id,
                    dataset_version_id=version_id,
                    batch=batch,
                )
                total_rows = batch.rows_read
                stored_rows += len(batch.measurements)
                valid_rows += sum(
                    measurement.parse_status != "invalid" for measurement in batch.measurements
                )
                issue_count += len(batch.issues)
                for measurement in batch.measurements:
                    min_timestamp = (
                        measurement.observed_at
                        if min_timestamp is None
                        else min(min_timestamp, measurement.observed_at)
                    )
                    max_timestamp = (
                        measurement.observed_at
                        if max_timestamp is None
                        else max(max_timestamp, measurement.observed_at)
                    )
                    interval_seconds = interval_seconds or measurement.interval_seconds
                await context.report_progress(min(95, max(1, total_rows // self._batch_size)))
        except JobCancellationRequested:
            await self._repository.fail(
                import_id=import_id, dataset_version_id=version_id, cancelled=True
            )
            raise
        except BaseException:
            await self._repository.fail(
                import_id=import_id, dataset_version_id=version_id, cancelled=False
            )
            raise
        finally:
            stream.close()

        report = {
            "schema_version": "dataset-import-report/v1",
            "profile": profile.value,
            "source_rows": total_rows,
            "stored_rows": stored_rows,
            "valid_rows": valid_rows,
            "invalid_or_skipped_rows": total_rows - valid_rows,
            "parse_issue_count": issue_count,
            "batch_size": self._batch_size,
            "missing_tokens_preserved_as_null": True,
        }
        await self._repository.complete(
            import_id=import_id,
            dataset_version_id=version_id,
            report=report,
            interval_seconds=interval_seconds,
            min_timestamp=min_timestamp,
            max_timestamp=max_timestamp,
        )
        if self._quality_evaluator is not None:
            try:
                quality_report = await self._quality_evaluator.evaluate(version_id)
            except BaseException:
                await self._repository.fail(
                    import_id=import_id, dataset_version_id=version_id, cancelled=False
                )
                raise
            report["quality_report_version"] = quality_report.report_version
        await context.report_progress(99)
        return report


def measurement_values(measurement: ParsedMeasurement, dataset_version_id: UUID) -> dict[str, Any]:
    values = asdict(measurement)
    values["dataset_version_id"] = dataset_version_id
    values["parse_status"] = measurement.parse_status.value
    values["quality_flags"] = list(measurement.quality_flags)
    return values


def _required_payload(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Dataset import payload is missing {key}")
    return value
