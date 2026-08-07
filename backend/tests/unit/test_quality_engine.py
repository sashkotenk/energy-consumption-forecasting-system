from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from energy_forecast.quality.engine import DataQualityEngine
from energy_forecast.quality.models import (
    EvaluatedQualityReport,
    QualityIssueResult,
    QualityMeasurement,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _row(
    number: int,
    minute: int,
    *,
    energy_kwh: float | None = 0.1,
    active_power_kw: float | None = 1.0,
    voltage_v: float | None = 230.0,
    current_a: float | None = 4.0,
    parse_status: str = "valid",
    quality_flags: tuple[str, ...] = (),
) -> QualityMeasurement:
    return QualityMeasurement(
        source_row_number=number,
        observed_at=START + timedelta(minutes=minute),
        energy_kwh=energy_kwh,
        active_power_kw=active_power_kw,
        reactive_power_kw=0.2,
        voltage_v=voltage_v,
        current_a=current_a,
        sub_metering_1_wh=1.0,
        sub_metering_2_wh=2.0,
        sub_metering_3_wh=3.0,
        parse_status=parse_status,
        quality_flags=quality_flags,
    )


def _issues(report: EvaluatedQualityReport, issue_type: str) -> list[QualityIssueResult]:
    return [issue for issue in report.issues if issue.issue_type == issue_type]


def test_exact_and_conflicting_duplicates_are_distinct() -> None:
    first = _row(1, 0)
    exact = replace(first, source_row_number=2)
    conflict = replace(first, source_row_number=3, active_power_kw=2.0)
    later = _row(4, 1)

    exact_report = DataQualityEngine().evaluate((first, exact, later))
    conflict_report = DataQualityEngine().evaluate((first, exact, conflict, later))

    assert exact_report.summary["exact_duplicates"] == 1
    assert exact_report.summary["conflicting_duplicates"] == 0
    assert conflict_report.summary["exact_duplicates"] == 1
    assert conflict_report.summary["conflicting_duplicates"] == 3


def test_gap_uses_modal_positive_interval_and_timestamp_order_is_separate() -> None:
    rows = (_row(1, 0), _row(2, 1), _row(3, 2), _row(4, 6))
    report = DataQualityEngine().evaluate(rows)

    assert report.expected_interval_seconds == 60
    assert report.summary["gap_count"] == 1
    gap = _issues(report, "time_gap")[0]
    assert gap.evidence[0]["estimated_missing_intervals"] == 3

    unordered = DataQualityEngine().evaluate((_row(1, 0), _row(2, 2), _row(3, 1)))
    assert unordered.summary["timestamp_order_violations"] == 1


def test_missing_and_non_finite_values_are_never_counted_as_zero() -> None:
    report = DataQualityEngine().evaluate(
        (
            _row(1, 0, active_power_kw=None),
            _row(2, 1, active_power_kw=float("inf")),
            _row(3, 2, active_power_kw=0.0),
        )
    )

    assert report.summary["missing_values"] == 1
    assert report.summary["non_finite_values"] == 1
    assert report.summary["physical_invalid_values"] == 0


def test_negative_energy_power_current_and_non_positive_voltage_are_invalid() -> None:
    report = DataQualityEngine().evaluate(
        (
            _row(1, 0, energy_kwh=-0.1),
            _row(2, 1, active_power_kw=-1.0),
            _row(3, 2, current_a=-2.0),
            _row(4, 3, voltage_v=0.0),
        )
    )

    assert report.summary["physical_invalid_values"] == 4
    assert {issue.column_name for issue in _issues(report, "physical_invalidity")} == {
        "energy_kwh",
        "active_power_kw",
        "current_a",
        "voltage_v",
    }


def test_large_positive_outlier_is_flagged_but_retained() -> None:
    values = (10.0, 10.1, 9.9, 10.2, 1_000.0)
    rows = tuple(_row(index, index, active_power_kw=value) for index, value in enumerate(values, 1))

    report = DataQualityEngine().evaluate(rows)

    assert report.total_rows == 5
    assert report.summary["statistical_anomalies"] == 1
    anomaly = _issues(report, "statistical_anomaly")[0]
    assert anomaly.severity == "info"
    assert anomaly.evidence[0]["value"] == 1_000.0


def test_quality_report_is_deterministic_and_machine_readable() -> None:
    rows = (_row(1, 0), _row(2, 1, parse_status="invalid", quality_flags=("parse:x",)))
    engine = DataQualityEngine()

    first = engine.evaluate(rows)
    second = engine.evaluate(rows)

    assert first == second
    assert first.summary["schema_version"] == "data-quality-report/v1"
    assert first.summary["parse_errors"] == 1
