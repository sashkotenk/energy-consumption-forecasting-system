"""Persistence port owned by the data-quality application boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from energy_forecast.quality.models import (
    EvaluatedQualityReport,
    QualityMeasurement,
    QualityReportPage,
    StoredQualityReport,
)


class QualityRepository(Protocol):
    async def load_measurements(
        self, dataset_version_id: UUID
    ) -> tuple[QualityMeasurement, ...]: ...

    async def save_report(
        self, dataset_version_id: UUID, report: EvaluatedQualityReport
    ) -> StoredQualityReport: ...

    async def get_report_page(
        self,
        dataset_version_id: UUID,
        *,
        report_version: int | None,
        page: int,
        page_size: int,
    ) -> QualityReportPage | None: ...
