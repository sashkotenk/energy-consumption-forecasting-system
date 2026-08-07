"""Framework-independent transformation values and errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class DuplicatePolicy(StrEnum):
    REJECT = "reject"
    KEEP_FIRST = "keep_first"
    KEEP_LAST = "keep_last"
    MEAN = "mean"


class HourQualityStatus(StrEnum):
    COMPLETE = "complete"
    IMPUTED_SHORT_GAP = "imputed_short_gap"
    VALID_PARTIAL = "valid_partial"
    INVALID_MISSING = "invalid_missing"
    INVALID_CONFLICT = "invalid_conflict"
    INVALID_VALUE = "invalid_value"


TRAINING_READY_STATUSES = frozenset(
    {HourQualityStatus.COMPLETE, HourQualityStatus.IMPUTED_SHORT_GAP}
)


@dataclass(frozen=True, slots=True)
class TransformationPolicy:
    short_gap_limit_minutes: int = 5
    minimum_hour_coverage: float = 0.9
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.REJECT

    def __post_init__(self) -> None:
        if not 0 <= self.short_gap_limit_minutes <= 5:
            raise ValueError("short_gap_limit_minutes must be between 0 and 5")
        if not 0.8 <= self.minimum_hour_coverage <= 1:
            raise ValueError("minimum_hour_coverage must be between 0.8 and 1")

    def as_dict(self) -> dict[str, Any]:
        return {
            "short_gap_limit_minutes": self.short_gap_limit_minutes,
            "minimum_hour_coverage": self.minimum_hour_coverage,
            "duplicate_policy": self.duplicate_policy.value,
        }


@dataclass(frozen=True, slots=True)
class SourceMeasurement:
    observed_at: datetime
    source_row_number: int
    interval_seconds: int | None
    energy_kwh: float | None
    active_power_kw: float | None
    reactive_power_kw: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    parse_status: str = "valid"
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HourlyValue:
    hour_start: datetime
    timezone_context: str | None
    energy_kwh: float | None
    mean_active_power_kw: float | None
    mean_reactive_power_kw: float | None
    mean_voltage_v: float | None
    min_voltage_v: float | None
    max_voltage_v: float | None
    mean_current_a: float | None
    max_current_a: float | None
    observed_samples: int
    expected_samples: int
    coverage_ratio: float
    imputed_samples: int
    max_missing_run: int
    quality_status: HourQualityStatus
    quality_flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TransformationResult:
    rows: tuple[HourlyValue, ...]
    summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StagedTransformation:
    run_id: UUID
    job_id: UUID
    source_version_id: UUID
    target_version_id: UUID


class TransformationError(Exception):
    """Base class for expected transformation failures."""


class SourceVersionNotReadyError(TransformationError):
    """Raised when the source version cannot be transformed."""
