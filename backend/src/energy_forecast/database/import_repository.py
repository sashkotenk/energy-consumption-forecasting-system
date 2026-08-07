"""Short-transaction persistence for chunked dataset imports."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, insert, select

from energy_forecast.database.models import (
    DatasetImport,
    DatasetImportError,
    DatasetVersion,
    RawMeasurement,
)
from energy_forecast.database.session import AsyncSessionFactory, transactional_session
from energy_forecast.datasets.importing import measurement_values
from energy_forecast.datasets.parsers import ParseBatch


class SqlAlchemyDatasetImportRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def prepare(self, *, import_id: UUID, dataset_version_id: UUID) -> None:
        async with transactional_session(self._session_factory) as session:
            import_row = await session.scalar(
                select(DatasetImport).where(DatasetImport.id == import_id).with_for_update()
            )
            version = await session.scalar(
                select(DatasetVersion)
                .where(DatasetVersion.id == dataset_version_id)
                .with_for_update()
            )
            if (
                import_row is None
                or version is None
                or import_row.dataset_version_id != dataset_version_id
            ):
                raise ValueError("Dataset import payload references inconsistent resources")
            await session.execute(
                delete(RawMeasurement).where(
                    RawMeasurement.dataset_version_id == dataset_version_id
                )
            )
            await session.execute(
                delete(DatasetImportError).where(DatasetImportError.import_id == import_id)
            )
            import_row.status = "running"
            import_row.import_report = None
            import_row.completed_at = None
            version.status = "importing"
            version.row_count = None
            version.valid_row_count = None
            version.min_timestamp = None
            version.max_timestamp = None

    async def insert_batch(
        self,
        *,
        import_id: UUID,
        dataset_version_id: UUID,
        batch: ParseBatch,
    ) -> None:
        async with transactional_session(self._session_factory) as session:
            if batch.measurements:
                await session.execute(
                    insert(RawMeasurement),
                    [measurement_values(row, dataset_version_id) for row in batch.measurements],
                )
            if batch.issues:
                await session.execute(
                    insert(DatasetImportError),
                    [
                        {
                            "import_id": import_id,
                            "source_row_number": issue.source_row_number,
                            "parse_status": "invalid",
                            "code": issue.code,
                            "column_name": issue.column_name,
                            "message": issue.message,
                            "evidence": {"raw_value": issue.raw_value}
                            if issue.raw_value is not None
                            else {},
                        }
                        for issue in batch.issues
                    ],
                )

    async def complete(
        self,
        *,
        import_id: UUID,
        dataset_version_id: UUID,
        report: dict[str, Any],
        interval_seconds: int | None,
        min_timestamp: datetime | None,
        max_timestamp: datetime | None,
    ) -> None:
        async with transactional_session(self._session_factory) as session:
            import_row = await session.get(DatasetImport, import_id)
            version = await session.get(DatasetVersion, dataset_version_id)
            if import_row is None or version is None:
                raise ValueError("Dataset import disappeared before completion")
            now = datetime.now(UTC)
            import_row.status = "completed"
            import_row.import_report = report
            import_row.completed_at = now
            version.status = "imported"
            version.interval_seconds = interval_seconds
            version.row_count = int(report["source_rows"])
            version.valid_row_count = int(report["valid_rows"])
            version.min_timestamp = min_timestamp
            version.max_timestamp = max_timestamp

    async def fail(self, *, import_id: UUID, dataset_version_id: UUID, cancelled: bool) -> None:
        async with transactional_session(self._session_factory) as session:
            import_row = await session.get(DatasetImport, import_id)
            version = await session.get(DatasetVersion, dataset_version_id)
            if import_row is not None:
                import_row.status = "cancelled" if cancelled else "failed"
                import_row.completed_at = datetime.now(UTC)
            if version is not None:
                version.status = "failed"
