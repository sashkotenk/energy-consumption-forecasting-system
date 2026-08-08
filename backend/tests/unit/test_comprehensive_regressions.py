from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest

from energy_forecast.datasets.parsers import GenericCsvMapping, GenericCsvParser, UciDatasetParser
from energy_forecast.exports.serialization import neutralize_csv_cell
from energy_forecast.ml.baselines import SeasonalNaive
from energy_forecast.ml.metrics import evaluate
from energy_forecast.quality.engine import DataQualityEngine
from energy_forecast.transformations.engine import TransformationEngine
from energy_forecast.transformations.models import HourQualityStatus, TransformationPolicy
from tests.fixtures.synthetic import (
    csv_formula_prefixes,
    daily_seasonal_series,
    dst_like_duplicate_hour_csv,
    duplicate_conflict_measurements,
    invalid_timestamp_uci,
    power_rows_with_gap,
    zero_demand_targets,
)


def test_invalid_timestamp_fixture_is_rejected_with_source_evidence() -> None:
    batch = next(UciDatasetParser().parse_batches(BytesIO(invalid_timestamp_uci()), batch_size=10))

    assert batch.measurements == ()
    assert [(issue.source_row_number, issue.code) for issue in batch.issues] == [
        (2, "timestamp_invalid")
    ]


def test_duplicate_conflict_fixture_remains_explicit() -> None:
    report = DataQualityEngine().evaluate(duplicate_conflict_measurements())

    assert report.summary["conflicting_duplicates"] == 2
    conflicts = [issue for issue in report.issues if issue.issue_type == "conflicting_duplicate"]
    assert len(conflicts) == 1
    assert conflicts[0].occurrence_count == 2


@pytest.mark.parametrize(
    ("gap_minutes", "expected_status", "expected_imputed"),
    [
        (5, HourQualityStatus.IMPUTED_SHORT_GAP, 5),
        (6, HourQualityStatus.VALID_PARTIAL, 0),
    ],
)
def test_five_and_six_minute_gap_boundary_is_locked(
    gap_minutes: int,
    expected_status: HourQualityStatus,
    expected_imputed: int,
) -> None:
    result = TransformationEngine().transform(
        power_rows_with_gap(gap_minutes),
        interval_seconds=60,
        timezone_context="UTC",
        policy=TransformationPolicy(),
    )

    assert len(result.rows) == 1
    assert result.rows[0].quality_status is expected_status
    assert result.rows[0].imputed_samples == expected_imputed
    if gap_minutes == 5:
        assert result.rows[0].energy_kwh == pytest.approx(1.0)
    else:
        assert result.rows[0].energy_kwh == pytest.approx(0.9)


def test_zero_demand_fixture_has_finite_zero_metrics() -> None:
    actual, predicted = zero_demand_targets()

    metrics = evaluate(actual, predicted)

    assert metrics.mae == 0.0
    assert metrics.rmse == 0.0
    assert metrics.smape == 0.0
    assert np.isfinite(metrics.mae_per_horizon).all()


def test_daily_seasonality_fixture_is_exact_for_seasonal_naive_24() -> None:
    series = daily_seasonal_series()
    origins = tuple(series.index[24 * 7 : 24 * 8].to_pydatetime())
    actual = np.asarray(
        [
            [
                series.at[origin + np.timedelta64(horizon, "h")]
                for horizon in range(1, 25)
            ]
            for origin in origins
        ],
        dtype=np.float64,
    )

    predicted = SeasonalNaive(24).predict(series, origins)

    assert predicted.shape == (24, 24)
    assert evaluate(actual, predicted).mae == 0.0


def test_dst_like_duplicate_local_hour_maps_to_same_instant_for_conflict_detection() -> None:
    mapping = GenericCsvMapping.from_options(
        {
            "timestamp_column": "timestamp",
            "energy_column": "energy_kwh",
            "unit": "kwh",
            "timezone": "Europe/Paris",
            "interval_seconds": "3600",
        },
        detected_delimiter=",",
    )
    batch = next(
        GenericCsvParser(mapping).parse_batches(BytesIO(dst_like_duplicate_hour_csv()), batch_size=10)
    )

    assert len(batch.measurements) == 3
    assert batch.measurements[0].observed_at == batch.measurements[1].observed_at
    assert batch.measurements[0].energy_kwh != batch.measurements[1].energy_kwh


def test_all_csv_formula_prefix_fixtures_are_neutralized_without_touching_plain_text() -> None:
    for value in csv_formula_prefixes():
        assert str(neutralize_csv_cell(value)).startswith("'")
    assert neutralize_csv_cell("plain text") == "plain text"
