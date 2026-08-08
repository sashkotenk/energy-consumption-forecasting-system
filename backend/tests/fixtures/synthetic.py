from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from energy_forecast.quality.models import QualityMeasurement
from energy_forecast.transformations.models import SourceMeasurement

START = datetime(2026, 1, 1, tzinfo=UTC)
UCI_HEADER = (
    b"Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity;"
    b"Sub_metering_1;Sub_metering_2;Sub_metering_3\n"
)


def invalid_timestamp_uci() -> bytes:
    return UCI_HEADER + b"not-a-date;17:24:00;1.0;0.2;230;4;0;0;0\n"


def duplicate_conflict_measurements() -> tuple[QualityMeasurement, ...]:
    return (
        _quality_row(1, minute=0, active_power_kw=1.0),
        _quality_row(2, minute=0, active_power_kw=2.0),
        _quality_row(3, minute=1, active_power_kw=1.0),
    )


def power_rows_with_gap(gap_minutes: int) -> tuple[SourceMeasurement, ...]:
    missing = set(range(20, 20 + gap_minutes))
    return tuple(
        SourceMeasurement(
            observed_at=START + timedelta(minutes=minute),
            source_row_number=minute + 1,
            interval_seconds=60,
            energy_kwh=None,
            active_power_kw=1.0,
            reactive_power_kw=0.2,
            voltage_v=230.0,
            current_a=4.0,
        )
        for minute in range(60)
        if minute not in missing
    )


def zero_demand_targets(rows: int = 4) -> tuple[np.ndarray, np.ndarray]:
    actual = np.zeros((rows, 24), dtype=np.float64)
    predicted = np.zeros((rows, 24), dtype=np.float64)
    return actual, predicted


def daily_seasonal_series(days: int = 16) -> pd.Series:
    index = pd.date_range("2008-01-01T00:00:00Z", periods=24 * days, freq="h")
    values = np.asarray(index.hour, dtype=np.float64) / 10.0
    return pd.Series(values, index=index, name="energy_kwh")


def dst_like_duplicate_hour_csv() -> bytes:
    return (
        b"timestamp,energy_kwh\n"
        b"2025-10-26 02:30:00,0.45\n"
        b"2025-10-26 02:30:00,0.75\n"
        b"2025-10-26 03:30:00,0.55\n"
    )


def csv_formula_prefixes() -> tuple[str, ...]:
    return (
        "=SUM(A1:A2)",
        "+cmd|' /C calc'!A0",
        "-danger",
        "@HYPERLINK(\"https://example.invalid\")",
        "\t=hidden",
    )


def _quality_row(
    source_row_number: int,
    *,
    minute: int,
    active_power_kw: float,
) -> QualityMeasurement:
    return QualityMeasurement(
        source_row_number=source_row_number,
        observed_at=START + timedelta(minutes=minute),
        energy_kwh=None,
        active_power_kw=active_power_kw,
        reactive_power_kw=0.2,
        voltage_v=230.0,
        current_a=4.0,
        sub_metering_1_wh=0.0,
        sub_metering_2_wh=0.0,
        sub_metering_3_wh=0.0,
        parse_status="valid",
        quality_flags=(),
    )
