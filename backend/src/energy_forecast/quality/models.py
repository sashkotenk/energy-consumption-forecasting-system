"""Framework-independent data-quality values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class QualityMeasurement:
    source_row_number: int
    observed_at: datetime
    energy_kwh: float | None = None
    active_power_kw: float | None = None
    reactive_power_kw: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    sub_metering_1_wh: float | None = None
    sub_metering_2_wh: float | None = None
    sub_metering_3_wh: float | None = None
    parse_status: str = "valid"
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QualityIssueResult:
    issue_type: str
    severity: str
    range_start: datetime | None
    range_end: datetime | None
    occurrence_count: int
    column_name: str | None
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class EvaluatedQualityReport:
    engine_version: str
    total_rows: int
    expected_interval_seconds: int | None
    summary: dict[str, Any]
    issues: tuple[QualityIssueResult, ...]


@dataclass(frozen=True, slots=True)
class StoredQualityReport:
    id: UUID
    dataset_version_id: UUID
    report_version: int
    engine_version: str
    expected_interval_seconds: int | None
    summary: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StoredQualityIssue:
    id: int
    issue_type: str
    severity: str
    range_start: datetime | None
    range_end: datetime | None
    occurrence_count: int
    column_name: str | None
    evidence: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class QualityReportPage:
    report: StoredQualityReport
    items: tuple[StoredQualityIssue, ...]
    page: int
    page_size: int
    total: int


class QualityReportNotFoundError(LookupError):
    """The version or requested report does not exist."""
