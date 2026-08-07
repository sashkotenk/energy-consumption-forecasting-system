"""Application service for evaluating and reading versioned quality reports."""

from __future__ import annotations

from uuid import UUID

from energy_forecast.quality.engine import DataQualityEngine
from energy_forecast.quality.models import (
    QualityReportNotFoundError,
    QualityReportPage,
    StoredQualityReport,
)
from energy_forecast.quality.ports import QualityRepository


class QualityService:
    def __init__(
        self, repository: QualityRepository, engine: DataQualityEngine | None = None
    ) -> None:
        self._repository = repository
        self._engine = engine or DataQualityEngine()

    async def evaluate(self, dataset_version_id: UUID) -> StoredQualityReport:
        rows = await self._repository.load_measurements(dataset_version_id)
        report = self._engine.evaluate(rows)
        return await self._repository.save_report(dataset_version_id, report)

    async def get_report(
        self,
        dataset_version_id: UUID,
        *,
        report_version: int | None,
        page: int,
        page_size: int,
    ) -> QualityReportPage:
        report = await self._repository.get_report_page(
            dataset_version_id,
            report_version=report_version,
            page=page,
            page_size=page_size,
        )
        if report is None:
            raise QualityReportNotFoundError("Quality report was not found")
        return report
