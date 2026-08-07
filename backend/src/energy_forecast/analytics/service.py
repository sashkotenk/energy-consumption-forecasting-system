"""Validation and deterministic bucketing for bounded analytics queries."""

from __future__ import annotations

import math
from datetime import datetime
from uuid import UUID

from energy_forecast.analytics.models import (
    AnalyticsContext,
    AnalyticsRange,
    AnalyticsVersionNotFoundError,
    AnalyticsVersionNotReadyError,
    DistributionBin,
    HeatmapPoint,
    ProfilePoint,
    SeriesPoint,
    SeriesResolution,
    SummaryValues,
)
from energy_forecast.analytics.ports import AnalyticsRepository

_BASE_BUCKET_SECONDS = {
    SeriesResolution.HOUR: 3600,
    SeriesResolution.DAY: 86400,
    SeriesResolution.WEEK: 604800,
}
_BUCKET_ORIGIN_TIMESTAMP = 4 * 86400  # 1970-01-05T00:00:00Z, a Monday


class AnalyticsService:
    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository

    async def summary(
        self, version_id: UUID, start: datetime, end: datetime
    ) -> tuple[AnalyticsContext, AnalyticsRange, SummaryValues]:
        context = await self._ready_context(version_id)
        time_range = AnalyticsRange(start, end)
        return context, time_range, await self._repository.summary(version_id, time_range)

    async def series(
        self,
        version_id: UUID,
        start: datetime,
        end: datetime,
        *,
        resolution: SeriesResolution,
        max_points: int,
    ) -> tuple[AnalyticsContext, AnalyticsRange, int, tuple[SeriesPoint, ...]]:
        context = await self._ready_context(version_id)
        time_range = AnalyticsRange(start, end)
        bucket_seconds = _bounded_bucket_seconds(
            time_range, _BASE_BUCKET_SECONDS[resolution], max_points
        )
        points = await self._repository.series(
            version_id,
            time_range,
            bucket_seconds=bucket_seconds,
            max_points=max_points,
        )
        return context, time_range, bucket_seconds, points

    async def hourly_profile(
        self, version_id: UUID, start: datetime, end: datetime
    ) -> tuple[AnalyticsContext, AnalyticsRange, tuple[ProfilePoint, ...]]:
        context = await self._ready_context(version_id)
        time_range = AnalyticsRange(start, end)
        return (
            context,
            time_range,
            await self._repository.hourly_profile(version_id, time_range, context.timezone),
        )

    async def weekday_profile(
        self, version_id: UUID, start: datetime, end: datetime
    ) -> tuple[AnalyticsContext, AnalyticsRange, tuple[ProfilePoint, ...]]:
        context = await self._ready_context(version_id)
        time_range = AnalyticsRange(start, end)
        return (
            context,
            time_range,
            await self._repository.weekday_profile(version_id, time_range, context.timezone),
        )

    async def heatmap(
        self, version_id: UUID, start: datetime, end: datetime
    ) -> tuple[AnalyticsContext, AnalyticsRange, tuple[HeatmapPoint, ...]]:
        context = await self._ready_context(version_id)
        time_range = AnalyticsRange(start, end)
        return (
            context,
            time_range,
            await self._repository.heatmap(version_id, time_range, context.timezone),
        )

    async def distribution(
        self, version_id: UUID, start: datetime, end: datetime, *, bins: int
    ) -> tuple[AnalyticsContext, AnalyticsRange, tuple[DistributionBin, ...]]:
        context = await self._ready_context(version_id)
        time_range = AnalyticsRange(start, end)
        return (
            context,
            time_range,
            await self._repository.distribution(version_id, time_range, bins=bins),
        )

    async def _ready_context(self, version_id: UUID) -> AnalyticsContext:
        stored = await self._repository.get_context(version_id)
        if stored is None:
            raise AnalyticsVersionNotFoundError("Dataset version was not found")
        context, status = stored
        if status != "ready":
            raise AnalyticsVersionNotReadyError("Dataset version has no ready hourly facts")
        return context


def _bounded_bucket_seconds(time_range: AnalyticsRange, base_seconds: int, max_points: int) -> int:
    duration = (time_range.end - time_range.start).total_seconds()
    multiplier = max(1, math.ceil(duration / (max_points * base_seconds)))
    while True:
        bucket_seconds = multiplier * base_seconds
        first = math.floor(
            (time_range.start.timestamp() - _BUCKET_ORIGIN_TIMESTAMP) / bucket_seconds
        )
        last = math.floor(
            (time_range.end.timestamp() - 0.000001 - _BUCKET_ORIGIN_TIMESTAMP) / bucket_seconds
        )
        if last - first + 1 <= max_points:
            return bucket_seconds
        multiplier += 1
