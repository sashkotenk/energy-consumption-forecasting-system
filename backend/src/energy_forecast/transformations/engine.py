"""Pure deterministic interpolation, integration, and hourly aggregation."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from statistics import fmean

from energy_forecast.transformations.models import (
    HourlyValue,
    HourQualityStatus,
    SourceMeasurement,
    TransformationPolicy,
    TransformationResult,
)

ENGINE_VERSION = "hourly-transform/v1"


class TransformationEngine:
    def transform(
        self,
        measurements: tuple[SourceMeasurement, ...],
        *,
        interval_seconds: int,
        timezone_context: str | None,
        policy: TransformationPolicy,
    ) -> TransformationResult:
        if interval_seconds <= 0 or 3600 % interval_seconds:
            raise ValueError("The source interval must divide one hour exactly")
        if not measurements:
            return TransformationResult((), _summary((), interval_seconds, "active_power"))
        if any(row.observed_at.tzinfo is None for row in measurements):
            raise ValueError("Source timestamps must be timezone-aware")

        semantic = _target_semantic(measurements)
        resolved, conflicts = _resolve_duplicates(measurements, policy)
        first = min(resolved).replace(minute=0, second=0, microsecond=0)
        last = max(resolved).replace(minute=0, second=0, microsecond=0)
        step = timedelta(seconds=interval_seconds)
        expected_per_hour = 3600 // interval_seconds
        all_timestamps = tuple(
            first + index * step
            for index in range(
                int((last - first).total_seconds() // interval_seconds) + expected_per_hour
            )
        )
        original_values = [
            _target_value(resolved[timestamp], semantic) if timestamp in resolved else None
            for timestamp in all_timestamps
        ]
        filled_values = list(original_values)
        imputed_indexes = _interpolate_short_gaps(
            filled_values, interval_seconds, policy.short_gap_limit_minutes
        )
        output: list[HourlyValue] = []
        for offset in range(0, len(all_timestamps), expected_per_hour):
            timestamps = all_timestamps[offset : offset + expected_per_hour]
            output.append(
                _aggregate_hour(
                    timestamps,
                    resolved,
                    conflicts,
                    original_values=original_values[offset : offset + expected_per_hour],
                    filled_values=filled_values[offset : offset + expected_per_hour],
                    imputed=sum(
                        index in imputed_indexes
                        for index in range(offset, offset + expected_per_hour)
                    ),
                    semantic=semantic,
                    interval_seconds=interval_seconds,
                    timezone_context=timezone_context,
                    policy=policy,
                )
            )
        rows = tuple(output)
        return TransformationResult(rows, _summary(rows, interval_seconds, semantic))


def _target_semantic(rows: tuple[SourceMeasurement, ...]) -> str:
    power = sum(_valid_number(row.active_power_kw) for row in rows)
    energy = sum(_valid_number(row.energy_kwh) for row in rows)
    return "energy" if energy and not power else "active_power"


def _resolve_duplicates(
    rows: tuple[SourceMeasurement, ...], policy: TransformationPolicy
) -> tuple[dict[datetime, SourceMeasurement], frozenset[datetime]]:
    grouped: dict[datetime, list[SourceMeasurement]] = defaultdict(list)
    for row in sorted(rows, key=lambda item: (item.observed_at, item.source_row_number)):
        grouped[row.observed_at].append(row)
    resolved: dict[datetime, SourceMeasurement] = {}
    conflicts: set[datetime] = set()
    for timestamp, group in grouped.items():
        signatures = {_measurement_signature(row) for row in group}
        if len(signatures) == 1 or len(group) == 1:
            resolved[timestamp] = group[0]
        elif policy.duplicate_policy.value == "reject":
            resolved[timestamp] = group[0]
            conflicts.add(timestamp)
        elif policy.duplicate_policy.value == "keep_last":
            resolved[timestamp] = group[-1]
        elif policy.duplicate_policy.value == "mean":
            resolved[timestamp] = _mean_measurement(group)
        else:
            resolved[timestamp] = group[0]
    return resolved, frozenset(conflicts)


def _measurement_signature(row: SourceMeasurement) -> tuple[object, ...]:
    return (
        row.energy_kwh,
        row.active_power_kw,
        row.reactive_power_kw,
        row.voltage_v,
        row.current_a,
        row.parse_status,
    )


def _mean_measurement(rows: list[SourceMeasurement]) -> SourceMeasurement:
    first = rows[0]
    return replace(
        first,
        energy_kwh=_mean_optional(row.energy_kwh for row in rows),
        active_power_kw=_mean_optional(row.active_power_kw for row in rows),
        reactive_power_kw=_mean_optional(row.reactive_power_kw for row in rows),
        voltage_v=_mean_optional(row.voltage_v for row in rows),
        current_a=_mean_optional(row.current_a for row in rows),
        quality_flags=tuple(sorted({flag for row in rows for flag in row.quality_flags})),
    )


def _aggregate_hour(
    timestamps: tuple[datetime, ...],
    resolved: dict[datetime, SourceMeasurement],
    conflicts: frozenset[datetime],
    *,
    original_values: list[float | None],
    filled_values: list[float | None],
    imputed: int,
    semantic: str,
    interval_seconds: int,
    timezone_context: str | None,
    policy: TransformationPolicy,
) -> HourlyValue:
    invalid_value = False
    for timestamp in timestamps:
        row = resolved.get(timestamp)
        value = None if row is None else _target_value(row, semantic)
        if row is not None:
            invalid_value = invalid_value or _has_invalid_numeric(row)
            if value is None and _raw_target(row, semantic) is not None:
                invalid_value = True
    observed = sum(value is not None for value in original_values)
    missing_runs = _missing_runs(original_values)
    max_missing = max((length for _, length in missing_runs), default=0)
    conflict = any(timestamp in conflicts for timestamp in timestamps)
    expected = len(timestamps)
    coverage = observed / expected
    threshold = math.ceil(policy.minimum_hour_coverage * expected)
    if conflict:
        status = HourQualityStatus.INVALID_CONFLICT
    elif invalid_value:
        status = HourQualityStatus.INVALID_VALUE
    elif observed == expected:
        status = HourQualityStatus.COMPLETE
    elif observed >= threshold and all(value is not None for value in filled_values):
        status = HourQualityStatus.IMPUTED_SHORT_GAP
    elif observed >= threshold:
        status = HourQualityStatus.VALID_PARTIAL
    else:
        status = HourQualityStatus.INVALID_MISSING
    flags: list[str] = []
    if conflict:
        flags.append("conflicting_duplicate")
    if invalid_value:
        flags.append("invalid_target_value")
    if observed < expected:
        flags.append("missing_samples")
    if imputed:
        flags.append("short_gap_interpolated")

    present = [value for value in filled_values if value is not None]
    energy = (
        (sum(present) if semantic == "energy" else sum(present) * interval_seconds / 3600)
        if present
        else None
    )
    source_rows = tuple(resolved.get(timestamp) for timestamp in timestamps)
    active_values = _field_values(source_rows, "active_power_kw")
    reactive_values = _field_values(source_rows, "reactive_power_kw")
    voltage_values = _field_values(source_rows, "voltage_v")
    current_values = _field_values(source_rows, "current_a")
    return HourlyValue(
        hour_start=timestamps[0],
        timezone_context=timezone_context,
        energy_kwh=energy,
        mean_active_power_kw=(
            _mean_optional(filled_values)
            if semantic == "active_power"
            else _mean_optional(active_values)
        ),
        mean_reactive_power_kw=_mean_optional(reactive_values),
        mean_voltage_v=_mean_optional(voltage_values),
        min_voltage_v=min(voltage_values, default=None),
        max_voltage_v=max(voltage_values, default=None),
        mean_current_a=_mean_optional(current_values),
        max_current_a=max(current_values, default=None),
        observed_samples=observed,
        expected_samples=expected,
        coverage_ratio=coverage,
        imputed_samples=imputed,
        max_missing_run=max_missing,
        quality_status=status,
        quality_flags=tuple(flags),
    )


def _raw_target(row: SourceMeasurement, semantic: str) -> float | None:
    return row.energy_kwh if semantic == "energy" else row.active_power_kw


def _target_value(row: SourceMeasurement, semantic: str) -> float | None:
    value = _raw_target(row, semantic)
    if row.parse_status == "invalid" or not _valid_number(value) or value is None or value < 0:
        return None
    return value


def _valid_number(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _field_values(rows: tuple[SourceMeasurement | None, ...], field: str) -> list[float]:
    values = [getattr(row, field) for row in rows if row is not None]
    return [
        value
        for value in values
        if _valid_number(value)
        and value is not None
        and (value > 0 if field == "voltage_v" else value >= 0)
    ]


def _has_invalid_numeric(row: SourceMeasurement) -> bool:
    non_negative = (
        row.energy_kwh,
        row.active_power_kw,
        row.reactive_power_kw,
        row.current_a,
    )
    return (
        row.parse_status == "invalid"
        or any(
            value is not None and (not math.isfinite(value) or value < 0) for value in non_negative
        )
        or (row.voltage_v is not None and (not math.isfinite(row.voltage_v) or row.voltage_v <= 0))
    )


def _mean_optional(values: Iterable[float | None]) -> float | None:
    finite = [value for value in values if value is not None and math.isfinite(value)]
    return fmean(finite) if finite else None


def _missing_runs(values: list[float | None]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(values):
        if values[index] is not None:
            index += 1
            continue
        start = index
        while index < len(values) and values[index] is None:
            index += 1
        runs.append((start, index - start))
    return runs


def _interpolate_short_gaps(
    values: list[float | None], interval_seconds: int, limit_minutes: int
) -> frozenset[int]:
    imputed: set[int] = set()
    for start, length in _missing_runs(values):
        end = start + length
        if (
            start == 0
            or end == len(values)
            or length * interval_seconds > limit_minutes * 60
            or values[start - 1] is None
            or values[end] is None
        ):
            continue
        before = values[start - 1]
        after = values[end]
        assert before is not None and after is not None
        for offset in range(1, length + 1):
            values[start + offset - 1] = before + (after - before) * offset / (length + 1)
            imputed.add(start + offset - 1)
    return frozenset(imputed)


def _summary(
    rows: tuple[HourlyValue, ...], interval_seconds: int, semantic: str
) -> dict[str, object]:
    statuses = Counter(row.quality_status.value for row in rows)
    return {
        "schema_version": "transformation-summary/v1",
        "engine_version": ENGINE_VERSION,
        "source_semantic": semantic,
        "interval_seconds": interval_seconds,
        "hour_count": len(rows),
        "training_ready_hours": sum(
            row.quality_status in {HourQualityStatus.COMPLETE, HourQualityStatus.IMPUTED_SHORT_GAP}
            for row in rows
        ),
        "status_counts": dict(sorted(statuses.items())),
        "energy_is_never_coverage_scaled": True,
    }
