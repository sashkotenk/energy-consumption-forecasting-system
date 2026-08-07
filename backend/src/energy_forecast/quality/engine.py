"""Deterministic, reusable checks over normalized raw measurements."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime
from itertools import pairwise
from statistics import median
from typing import Any

from energy_forecast.quality.models import (
    EvaluatedQualityReport,
    QualityIssueResult,
    QualityMeasurement,
)

ENGINE_VERSION = "quality-engine/v1"
ROBUST_Z_THRESHOLD = 6.0
_EVIDENCE_LIMIT = 10
_NUMERIC_FIELDS = (
    "energy_kwh",
    "active_power_kw",
    "reactive_power_kw",
    "voltage_v",
    "current_a",
    "sub_metering_1_wh",
    "sub_metering_2_wh",
    "sub_metering_3_wh",
)
_NON_NEGATIVE_FIELDS = frozenset(
    {
        "energy_kwh",
        "active_power_kw",
        "reactive_power_kw",
        "current_a",
        "sub_metering_1_wh",
        "sub_metering_2_wh",
        "sub_metering_3_wh",
    }
)


class DataQualityEngine:
    """Produce deterministic aggregates without deleting or changing input observations."""

    def evaluate(self, measurements: Iterable[QualityMeasurement]) -> EvaluatedQualityReport:
        rows = tuple(measurements)
        expected_interval = _expected_interval_seconds(rows)
        issues: list[QualityIssueResult] = []
        issues.extend(_timestamp_order_issues(rows))
        issues.extend(_duplicate_issues(rows))
        issues.extend(_gap_issues(rows, expected_interval))
        issues.extend(_value_issues(rows))
        issues.extend(_parse_issues(rows))
        issues.extend(_anomaly_issues(rows))
        ordered = tuple(sorted(issues, key=_issue_sort_key))
        counts = Counter[str]()
        for issue in ordered:
            counts[issue.issue_type] += issue.occurrence_count
        summary: dict[str, Any] = {
            "schema_version": "data-quality-report/v1",
            "total_rows": len(rows),
            "expected_interval_seconds": expected_interval,
            "missing_values": counts["missing"],
            "non_finite_values": counts["non_finite"],
            "physical_invalid_values": counts["physical_invalidity"],
            "statistical_anomalies": counts["statistical_anomaly"],
            "exact_duplicates": counts["exact_duplicate"],
            "conflicting_duplicates": counts["conflicting_duplicate"],
            "gap_count": counts["time_gap"],
            "timestamp_order_violations": counts["timestamp_order"],
            "parse_errors": counts["parse_error"],
            "issue_group_count": len(ordered),
        }
        return EvaluatedQualityReport(
            engine_version=ENGINE_VERSION,
            total_rows=len(rows),
            expected_interval_seconds=expected_interval,
            summary=summary,
            issues=ordered,
        )


def _expected_interval_seconds(rows: Sequence[QualityMeasurement]) -> int | None:
    timestamps = sorted({row.observed_at for row in rows})
    differences = [
        int((later - earlier).total_seconds())
        for earlier, later in pairwise(timestamps)
        if later > earlier
    ]
    if not differences:
        return None
    frequencies = Counter(differences)
    return min(frequencies, key=lambda seconds: (-frequencies[seconds], seconds))


def _timestamp_order_issues(rows: Sequence[QualityMeasurement]) -> list[QualityIssueResult]:
    evidence: list[dict[str, Any]] = []
    times: list[datetime] = []
    for previous, current in pairwise(rows):
        if current.observed_at < previous.observed_at:
            times.append(current.observed_at)
            if len(evidence) < _EVIDENCE_LIMIT:
                evidence.append(
                    {
                        "previous_source_row": previous.source_row_number,
                        "source_row_number": current.source_row_number,
                        "previous_timestamp": previous.observed_at.isoformat(),
                        "timestamp": current.observed_at.isoformat(),
                    }
                )
    return _single_issue("timestamp_order", "warning", times, len(times), None, evidence)


def _duplicate_issues(rows: Sequence[QualityMeasurement]) -> list[QualityIssueResult]:
    groups: dict[datetime, list[QualityMeasurement]] = defaultdict(list)
    for row in rows:
        groups[row.observed_at].append(row)
    exact_times: list[datetime] = []
    conflict_times: list[datetime] = []
    exact_count = 0
    conflict_count = 0
    exact_evidence: list[dict[str, Any]] = []
    conflict_evidence: list[dict[str, Any]] = []
    for observed_at in sorted(groups):
        group = groups[observed_at]
        if len(group) < 2:
            continue
        signatures = {_measurement_signature(row) for row in group}
        evidence = {
            "timestamp": observed_at.isoformat(),
            "source_rows": sorted(row.source_row_number for row in group)[:_EVIDENCE_LIMIT],
        }
        exact_excess = len(group) - len(signatures)
        if exact_excess:
            exact_times.append(observed_at)
            exact_count += exact_excess
            if len(exact_evidence) < _EVIDENCE_LIMIT:
                exact_evidence.append(evidence)
        if len(signatures) > 1:
            conflict_times.append(observed_at)
            conflict_count += len(group)
            if len(conflict_evidence) < _EVIDENCE_LIMIT:
                conflict_evidence.append(evidence)
    return [
        *_single_issue(
            "exact_duplicate", "warning", exact_times, exact_count, None, exact_evidence
        ),
        *_single_issue(
            "conflicting_duplicate",
            "error",
            conflict_times,
            conflict_count,
            None,
            conflict_evidence,
        ),
    ]


def _gap_issues(
    rows: Sequence[QualityMeasurement], expected_interval: int | None
) -> list[QualityIssueResult]:
    if expected_interval is None:
        return []
    timestamps = sorted({row.observed_at for row in rows})
    evidence: list[dict[str, Any]] = []
    starts: list[datetime] = []
    ends: list[datetime] = []
    for earlier, later in pairwise(timestamps):
        delta = int((later - earlier).total_seconds())
        if delta <= 1.5 * expected_interval:
            continue
        starts.append(earlier)
        ends.append(later)
        if len(evidence) < _EVIDENCE_LIMIT:
            evidence.append(
                {
                    "start": earlier.isoformat(),
                    "end": later.isoformat(),
                    "delta_seconds": delta,
                    "estimated_missing_intervals": max(1, round(delta / expected_interval) - 1),
                }
            )
    if not starts:
        return []
    return [
        QualityIssueResult(
            issue_type="time_gap",
            severity="warning",
            range_start=min(starts),
            range_end=max(ends),
            occurrence_count=len(starts),
            column_name=None,
            evidence=tuple(evidence),
        )
    ]


def _value_issues(rows: Sequence[QualityMeasurement]) -> list[QualityIssueResult]:
    issues: list[QualityIssueResult] = []
    for field in _NUMERIC_FIELDS:
        missing_times: list[datetime] = []
        missing_evidence: list[dict[str, Any]] = []
        non_finite_times: list[datetime] = []
        non_finite_evidence: list[dict[str, Any]] = []
        invalid_times: list[datetime] = []
        invalid_evidence: list[dict[str, Any]] = []
        for row in rows:
            value = getattr(row, field)
            if value is None:
                missing_times.append(row.observed_at)
                _append_row_evidence(missing_evidence, row, value)
            elif not math.isfinite(value):
                non_finite_times.append(row.observed_at)
                _append_row_evidence(non_finite_evidence, row, str(value))
            elif (field in _NON_NEGATIVE_FIELDS and value < 0) or (
                field == "voltage_v" and value <= 0
            ):
                invalid_times.append(row.observed_at)
                _append_row_evidence(invalid_evidence, row, value)
        issues.extend(
            _single_issue(
                "missing", "warning", missing_times, len(missing_times), field, missing_evidence
            )
        )
        issues.extend(
            _single_issue(
                "non_finite",
                "error",
                non_finite_times,
                len(non_finite_times),
                field,
                non_finite_evidence,
            )
        )
        issues.extend(
            _single_issue(
                "physical_invalidity",
                "error",
                invalid_times,
                len(invalid_times),
                field,
                invalid_evidence,
            )
        )
    return issues


def _parse_issues(rows: Sequence[QualityMeasurement]) -> list[QualityIssueResult]:
    invalid = [row for row in rows if row.parse_status == "invalid"]
    return _single_issue(
        "parse_error",
        "error",
        [row.observed_at for row in invalid],
        len(invalid),
        None,
        [
            {"source_row_number": row.source_row_number, "flags": list(row.quality_flags)}
            for row in invalid[:_EVIDENCE_LIMIT]
        ],
    )


def _anomaly_issues(rows: Sequence[QualityMeasurement]) -> list[QualityIssueResult]:
    issues: list[QualityIssueResult] = []
    for field in _NUMERIC_FIELDS:
        finite = [
            (row, value)
            for row in rows
            if (value := getattr(row, field)) is not None and math.isfinite(value)
        ]
        if len(finite) < 3:
            continue
        center = median(value for _, value in finite)
        mad = median(abs(value - center) for _, value in finite)
        if mad == 0:
            continue
        anomaly_rows: list[QualityMeasurement] = []
        evidence: list[dict[str, Any]] = []
        for row, value in finite:
            robust_z = abs(value - center) / (1.4826 * mad)
            if robust_z <= ROBUST_Z_THRESHOLD:
                continue
            anomaly_rows.append(row)
            if len(evidence) < _EVIDENCE_LIMIT:
                evidence.append(
                    {
                        "source_row_number": row.source_row_number,
                        "value": value,
                        "robust_z": round(robust_z, 6),
                        "median": center,
                        "mad": mad,
                    }
                )
        issues.extend(
            _single_issue(
                "statistical_anomaly",
                "info",
                [row.observed_at for row in anomaly_rows],
                len(anomaly_rows),
                field,
                evidence,
            )
        )
    return issues


def _single_issue(
    issue_type: str,
    severity: str,
    times: Sequence[datetime],
    count: int,
    column_name: str | None,
    evidence: Sequence[dict[str, Any]],
) -> list[QualityIssueResult]:
    if count == 0:
        return []
    return [
        QualityIssueResult(
            issue_type=issue_type,
            severity=severity,
            range_start=min(times) if times else None,
            range_end=max(times) if times else None,
            occurrence_count=count,
            column_name=column_name,
            evidence=tuple(evidence[:_EVIDENCE_LIMIT]),
        )
    ]


def _append_row_evidence(
    evidence: list[dict[str, Any]], row: QualityMeasurement, value: object
) -> None:
    if len(evidence) < _EVIDENCE_LIMIT:
        evidence.append(
            {
                "source_row_number": row.source_row_number,
                "timestamp": row.observed_at.isoformat(),
                "value": value,
            }
        )


def _measurement_signature(row: QualityMeasurement) -> tuple[object, ...]:
    return (
        *(getattr(row, field) for field in _NUMERIC_FIELDS),
        row.parse_status,
        row.quality_flags,
    )


def _issue_sort_key(issue: QualityIssueResult) -> tuple[object, ...]:
    return (
        issue.issue_type,
        issue.column_name or "",
        issue.range_start.isoformat() if issue.range_start else "",
        issue.range_end.isoformat() if issue.range_end else "",
    )
