"""Read-only persistence port for analytics queries."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from energy_forecast.analytics.models import (
    AnalyticsContext,
    AnalyticsRange,
    DistributionBin,
    HeatmapPoint,
    ProfilePoint,
    SeriesPoint,
    SummaryValues,
)


class AnalyticsRepository(Protocol):
    async def get_context(self, version_id: UUID) -> tuple[AnalyticsContext, str] | None: ...

    async def summary(self, version_id: UUID, time_range: AnalyticsRange) -> SummaryValues: ...

    async def series(
        self,
        version_id: UUID,
        time_range: AnalyticsRange,
        *,
        bucket_seconds: int,
        max_points: int,
    ) -> tuple[SeriesPoint, ...]: ...

    async def hourly_profile(
        self, version_id: UUID, time_range: AnalyticsRange, timezone: str
    ) -> tuple[ProfilePoint, ...]: ...

    async def weekday_profile(
        self, version_id: UUID, time_range: AnalyticsRange, timezone: str
    ) -> tuple[ProfilePoint, ...]: ...

    async def heatmap(
        self, version_id: UUID, time_range: AnalyticsRange, timezone: str
    ) -> tuple[HeatmapPoint, ...]: ...

    async def distribution(
        self, version_id: UUID, time_range: AnalyticsRange, *, bins: int
    ) -> tuple[DistributionBin, ...]: ...
