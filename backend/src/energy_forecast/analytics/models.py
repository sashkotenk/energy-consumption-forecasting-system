"""Framework-independent analytics query values and results."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

MAX_ANALYTICS_RANGE = timedelta(days=366 * 5)


class SeriesResolution(StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"


@dataclass(frozen=True, slots=True)
class AnalyticsRange:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise AnalyticsRangeError("Analytics timestamps must include a UTC offset")
        start = self.start.astimezone(UTC)
        end = self.end.astimezone(UTC)
        if start >= end:
            raise AnalyticsRangeError("Analytics range start must be before its end")
        if end - start > MAX_ANALYTICS_RANGE:
            raise AnalyticsRangeError("Analytics range cannot exceed five years")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def expected_hours(self) -> int:
        return math.ceil((self.end - self.start).total_seconds() / 3600)


@dataclass(frozen=True, slots=True)
class AnalyticsContext:
    dataset_version_id: UUID
    timezone: str


@dataclass(frozen=True, slots=True)
class SummaryValues:
    stored_hours: int
    energy_value_count: int
    mean_energy_kwh: float | None
    median_energy_kwh: float | None
    min_energy_kwh: float | None
    max_energy_kwh: float | None
    total_energy_kwh: float | None
    mean_coverage_ratio: float | None
    status_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    timestamp: datetime
    energy_kwh: float | None
    mean_coverage_ratio: float
    quality_status: str
    sample_count: int


@dataclass(frozen=True, slots=True)
class ProfilePoint:
    key: int
    mean_energy_kwh: float
    total_energy_kwh: float
    mean_coverage_ratio: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class HeatmapPoint:
    iso_weekday: int
    hour: int
    mean_energy_kwh: float
    mean_coverage_ratio: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class DistributionBin:
    bin_index: int
    lower_kwh: float
    upper_kwh: float
    sample_count: int


class AnalyticsError(Exception):
    """Base class for controlled analytics failures."""


class AnalyticsRangeError(AnalyticsError, ValueError):
    """Raised for reversed, naive, or unbounded ranges."""


class AnalyticsVersionNotFoundError(AnalyticsError):
    """Raised when a dataset version does not exist."""


class AnalyticsVersionNotReadyError(AnalyticsError):
    """Raised when hourly facts are not materialized yet."""
