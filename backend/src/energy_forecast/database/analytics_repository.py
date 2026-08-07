"""Indexed PostgreSQL/TimescaleDB analytics queries."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from energy_forecast.analytics.models import (
    AnalyticsContext,
    AnalyticsRange,
    DistributionBin,
    HeatmapPoint,
    ProfilePoint,
    SeriesPoint,
    SummaryValues,
)
from energy_forecast.database.models import DatasetVersion
from energy_forecast.database.session import AsyncSessionFactory, transactional_session

_RANGE = "dataset_version_id = :version_id AND hour_start >= :start AND hour_start < :end"


class SqlAlchemyAnalyticsRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def get_context(self, version_id: UUID) -> tuple[AnalyticsContext, str] | None:
        async with transactional_session(self._session_factory) as session:
            row = await session.execute(
                select(
                    DatasetVersion.id,
                    DatasetVersion.status,
                    DatasetVersion.timezone_context,
                ).where(DatasetVersion.id == version_id)
            )
            stored = row.one_or_none()
            if stored is None:
                return None
            return (
                AnalyticsContext(stored.id, stored.timezone_context or "UTC"),
                str(stored.status),
            )

    async def summary(self, version_id: UUID, time_range: AnalyticsRange) -> SummaryValues:
        parameters = _range_parameters(version_id, time_range)
        async with transactional_session(self._session_factory) as session:
            aggregate = (
                await session.execute(
                    text(
                        f"""
                        SELECT count(*) AS stored_hours,
                               count(energy_kwh) AS energy_value_count,
                               avg(energy_kwh) AS mean_energy_kwh,
                               percentile_cont(0.5) WITHIN GROUP (ORDER BY energy_kwh)
                                   FILTER (WHERE energy_kwh IS NOT NULL) AS median_energy_kwh,
                               min(energy_kwh) AS min_energy_kwh,
                               max(energy_kwh) AS max_energy_kwh,
                               sum(energy_kwh) AS total_energy_kwh,
                               avg(coverage_ratio) AS mean_coverage_ratio
                        FROM ts.hourly_observations
                        WHERE {_RANGE}
                        """
                    ),
                    parameters,
                )
            ).one()
            statuses = await session.execute(
                text(
                    f"""
                    SELECT quality_status, count(*) AS sample_count
                    FROM ts.hourly_observations
                    WHERE {_RANGE}
                    GROUP BY quality_status
                    ORDER BY quality_status
                    """
                ),
                parameters,
            )
            return SummaryValues(
                stored_hours=int(aggregate.stored_hours),
                energy_value_count=int(aggregate.energy_value_count),
                mean_energy_kwh=_optional_float(aggregate.mean_energy_kwh),
                median_energy_kwh=_optional_float(aggregate.median_energy_kwh),
                min_energy_kwh=_optional_float(aggregate.min_energy_kwh),
                max_energy_kwh=_optional_float(aggregate.max_energy_kwh),
                total_energy_kwh=_optional_float(aggregate.total_energy_kwh),
                mean_coverage_ratio=_optional_float(aggregate.mean_coverage_ratio),
                status_counts={str(row.quality_status): int(row.sample_count) for row in statuses},
            )

    async def series(
        self,
        version_id: UUID,
        time_range: AnalyticsRange,
        *,
        bucket_seconds: int,
        max_points: int,
    ) -> tuple[SeriesPoint, ...]:
        parameters = {
            **_range_parameters(version_id, time_range),
            "bucket_interval": timedelta(seconds=bucket_seconds),
            "max_points": max_points,
        }
        async with transactional_session(self._session_factory) as session:
            rows = await session.execute(
                text(
                    f"""
                    SELECT date_bin(
                               CAST(:bucket_interval AS interval),
                               hour_start,
                               TIMESTAMPTZ '1970-01-05 00:00:00+00'
                           ) AS bucket_start,
                           sum(energy_kwh) AS energy_kwh,
                           avg(coverage_ratio) AS mean_coverage_ratio,
                           CASE WHEN count(DISTINCT quality_status) = 1
                                THEN min(quality_status) ELSE 'mixed' END AS quality_status,
                           count(*) AS sample_count
                    FROM ts.hourly_observations
                    WHERE {_RANGE}
                    GROUP BY bucket_start
                    ORDER BY bucket_start
                    LIMIT :max_points
                    """
                ),
                parameters,
            )
            return tuple(
                SeriesPoint(
                    timestamp=row.bucket_start,
                    energy_kwh=_optional_float(row.energy_kwh),
                    mean_coverage_ratio=float(row.mean_coverage_ratio),
                    quality_status=str(row.quality_status),
                    sample_count=int(row.sample_count),
                )
                for row in rows
            )

    async def hourly_profile(
        self, version_id: UUID, time_range: AnalyticsRange, timezone: str
    ) -> tuple[ProfilePoint, ...]:
        return await self._profile(
            version_id,
            time_range,
            timezone=timezone,
            key_expression="EXTRACT(HOUR FROM hour_start AT TIME ZONE :timezone)::integer",
        )

    async def weekday_profile(
        self, version_id: UUID, time_range: AnalyticsRange, timezone: str
    ) -> tuple[ProfilePoint, ...]:
        return await self._profile(
            version_id,
            time_range,
            timezone=timezone,
            key_expression="EXTRACT(ISODOW FROM hour_start AT TIME ZONE :timezone)::integer",
        )

    async def _profile(
        self,
        version_id: UUID,
        time_range: AnalyticsRange,
        *,
        timezone: str,
        key_expression: str,
    ) -> tuple[ProfilePoint, ...]:
        parameters = {**_range_parameters(version_id, time_range), "timezone": timezone}
        async with transactional_session(self._session_factory) as session:
            rows = await session.execute(
                text(
                    f"""
                    SELECT {key_expression} AS profile_key,
                           avg(energy_kwh) AS mean_energy_kwh,
                           sum(energy_kwh) AS total_energy_kwh,
                           avg(coverage_ratio) AS mean_coverage_ratio,
                           count(*) AS sample_count
                    FROM ts.hourly_observations
                    WHERE {_RANGE} AND energy_kwh IS NOT NULL
                    GROUP BY profile_key
                    ORDER BY profile_key
                    """
                ),
                parameters,
            )
            return tuple(
                ProfilePoint(
                    key=int(row.profile_key),
                    mean_energy_kwh=float(row.mean_energy_kwh),
                    total_energy_kwh=float(row.total_energy_kwh),
                    mean_coverage_ratio=float(row.mean_coverage_ratio),
                    sample_count=int(row.sample_count),
                )
                for row in rows
            )

    async def heatmap(
        self, version_id: UUID, time_range: AnalyticsRange, timezone: str
    ) -> tuple[HeatmapPoint, ...]:
        parameters = {**_range_parameters(version_id, time_range), "timezone": timezone}
        async with transactional_session(self._session_factory) as session:
            rows = await session.execute(
                text(
                    f"""
                    SELECT EXTRACT(ISODOW FROM hour_start AT TIME ZONE :timezone)::integer
                               AS iso_weekday,
                           EXTRACT(HOUR FROM hour_start AT TIME ZONE :timezone)::integer
                               AS hour_of_day,
                           avg(energy_kwh) AS mean_energy_kwh,
                           avg(coverage_ratio) AS mean_coverage_ratio,
                           count(*) AS sample_count
                    FROM ts.hourly_observations
                    WHERE {_RANGE} AND energy_kwh IS NOT NULL
                    GROUP BY iso_weekday, hour_of_day
                    ORDER BY iso_weekday, hour_of_day
                    """
                ),
                parameters,
            )
            return tuple(
                HeatmapPoint(
                    iso_weekday=int(row.iso_weekday),
                    hour=int(row.hour_of_day),
                    mean_energy_kwh=float(row.mean_energy_kwh),
                    mean_coverage_ratio=float(row.mean_coverage_ratio),
                    sample_count=int(row.sample_count),
                )
                for row in rows
            )

    async def distribution(
        self, version_id: UUID, time_range: AnalyticsRange, *, bins: int
    ) -> tuple[DistributionBin, ...]:
        parameters = {**_range_parameters(version_id, time_range), "bins": bins}
        async with transactional_session(self._session_factory) as session:
            rows = await session.execute(
                text(
                    f"""
                    WITH source AS (
                        SELECT energy_kwh
                        FROM ts.hourly_observations
                        WHERE {_RANGE} AND energy_kwh IS NOT NULL
                    ), stats AS (
                        SELECT min(energy_kwh) AS minimum, max(energy_kwh) AS maximum
                        FROM source
                    ), bucketed AS (
                        SELECT CASE WHEN stats.minimum = stats.maximum THEN 1
                                    ELSE LEAST(
                                        :bins,
                                        width_bucket(
                                            source.energy_kwh,
                                            stats.minimum,
                                            stats.maximum,
                                            :bins
                                        )
                                    ) END AS bin_index,
                               stats.minimum,
                               stats.maximum
                        FROM source CROSS JOIN stats
                    )
                    SELECT bin_index,
                           CASE WHEN minimum = maximum THEN minimum
                                ELSE minimum + (bin_index - 1) * (maximum - minimum) / :bins
                           END AS lower_kwh,
                           CASE WHEN minimum = maximum THEN maximum
                                ELSE minimum + bin_index * (maximum - minimum) / :bins
                           END AS upper_kwh,
                           count(*) AS sample_count
                    FROM bucketed
                    GROUP BY bin_index, minimum, maximum
                    ORDER BY bin_index
                    """
                ),
                parameters,
            )
            return tuple(
                DistributionBin(
                    bin_index=int(row.bin_index),
                    lower_kwh=float(row.lower_kwh),
                    upper_kwh=float(row.upper_kwh),
                    sample_count=int(row.sample_count),
                )
                for row in rows
            )


def _range_parameters(version_id: UUID, time_range: AnalyticsRange) -> dict[str, Any]:
    return {"version_id": version_id, "start": time_range.start, "end": time_range.end}


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]
