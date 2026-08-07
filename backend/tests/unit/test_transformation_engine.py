from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from energy_forecast.transformations.engine import TransformationEngine
from energy_forecast.transformations.models import (
    DuplicatePolicy,
    HourQualityStatus,
    SourceMeasurement,
    TransformationPolicy,
    TransformationResult,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def test_sixty_one_kw_samples_integrate_to_one_kwh() -> None:
    result = _transform(_power_rows())

    assert len(result.rows) == 1
    assert result.rows[0].energy_kwh == pytest.approx(1.0)
    assert result.rows[0].quality_status is HourQualityStatus.COMPLETE
    assert result.rows[0].observed_samples == 60


def test_five_minute_bounded_gap_is_interpolated() -> None:
    result = _transform(_power_rows(missing=set(range(20, 25))))

    hour = result.rows[0]
    assert hour.energy_kwh == pytest.approx(1.0)
    assert hour.observed_samples == 55
    assert hour.imputed_samples == 5
    assert hour.max_missing_run == 5
    assert hour.quality_status is HourQualityStatus.IMPUTED_SHORT_GAP


def test_six_minute_gap_is_not_interpolated_or_scaled() -> None:
    result = _transform(_power_rows(power=2.0, missing=set(range(20, 26))))

    hour = result.rows[0]
    assert hour.energy_kwh == pytest.approx(1.8)
    assert hour.imputed_samples == 0
    assert hour.max_missing_run == 6
    assert hour.quality_status is HourQualityStatus.VALID_PARTIAL


def test_dataset_boundary_gap_is_not_interpolated() -> None:
    result = _transform(_power_rows(missing=set(range(5))))

    assert result.rows[0].imputed_samples == 0
    assert result.rows[0].quality_status is HourQualityStatus.VALID_PARTIAL


def test_conflicting_duplicate_is_explicitly_rejected() -> None:
    rows = (*_power_rows(), _row(10, power=2.0, source_row=100))
    result = _transform(rows, duplicate_policy=DuplicatePolicy.REJECT)

    assert result.rows[0].quality_status is HourQualityStatus.INVALID_CONFLICT
    assert "conflicting_duplicate" in result.rows[0].quality_flags


def test_energy_samples_are_summed_without_power_integration() -> None:
    rows = tuple(
        SourceMeasurement(
            observed_at=START + timedelta(minutes=minute),
            source_row_number=minute + 1,
            interval_seconds=60,
            energy_kwh=0.02,
            active_power_kw=None,
        )
        for minute in range(60)
    )

    assert _transform(rows).rows[0].energy_kwh == pytest.approx(1.2)


def test_physically_invalid_secondary_value_is_excluded_and_marks_hour() -> None:
    rows = list(_power_rows())
    rows[10] = SourceMeasurement(
        observed_at=rows[10].observed_at,
        source_row_number=rows[10].source_row_number,
        interval_seconds=60,
        energy_kwh=None,
        active_power_kw=1.0,
        current_a=-1.0,
    )

    hour = _transform(tuple(rows)).rows[0]
    assert hour.quality_status is HourQualityStatus.INVALID_VALUE
    assert hour.mean_current_a == pytest.approx(4.0)


def test_parse_invalid_target_is_not_treated_as_observed() -> None:
    rows = list(_power_rows())
    rows[10] = SourceMeasurement(
        observed_at=rows[10].observed_at,
        source_row_number=rows[10].source_row_number,
        interval_seconds=60,
        energy_kwh=None,
        active_power_kw=1.0,
        parse_status="invalid",
    )

    hour = _transform(tuple(rows)).rows[0]
    assert hour.observed_samples == 59
    assert hour.quality_status is HourQualityStatus.INVALID_VALUE


def _power_rows(
    *, power: float = 1.0, missing: set[int] | None = None
) -> tuple[SourceMeasurement, ...]:
    excluded = missing or set()
    return tuple(_row(minute, power=power) for minute in range(60) if minute not in excluded)


def _row(minute: int, *, power: float, source_row: int | None = None) -> SourceMeasurement:
    return SourceMeasurement(
        observed_at=START + timedelta(minutes=minute),
        source_row_number=source_row or minute + 1,
        interval_seconds=60,
        energy_kwh=None,
        active_power_kw=power,
        reactive_power_kw=0.2,
        voltage_v=230.0,
        current_a=4.0,
    )


def _transform(
    rows: tuple[SourceMeasurement, ...],
    *,
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.REJECT,
) -> TransformationResult:
    return TransformationEngine().transform(
        rows,
        interval_seconds=60,
        timezone_context="UTC",
        policy=TransformationPolicy(duplicate_policy=duplicate_policy),
    )
