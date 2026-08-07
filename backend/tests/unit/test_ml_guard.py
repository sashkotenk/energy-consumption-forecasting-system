from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Self

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from energy_forecast.ml.features import (
    CALENDAR_FEATURES,
    LAG_FEATURES,
    QUALITY_FEATURES,
    ROLLING_FEATURES,
    FeaturePipeline,
    FeaturePipelineConfig,
    FeatureSchema,
)
from energy_forecast.ml.splits import (
    FINAL_TEST_START,
    VALIDATION_PERIODS,
    ChronologicalSplitProtocol,
    prepare_fold,
)

pytestmark = pytest.mark.ml_guard


def test_feature_schema_has_deterministic_names_order_version_and_hash() -> None:
    first = FeatureSchema.create(include_quality_features=False)
    second = FeatureSchema.create(include_quality_features=False)

    assert first.version == "base_v1"
    assert first.names == (*LAG_FEATURES, *ROLLING_FEATURES, *CALENDAR_FEATURES)
    assert first.dtypes == tuple("float64" for _ in first.names)
    assert first.forecast_horizon == 24
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64


def test_quality_feature_schema_is_explicitly_versioned() -> None:
    base = FeatureSchema.create(include_quality_features=False)
    quality = FeatureSchema.create(include_quality_features=True)

    assert quality.version == "base_quality_v1"
    assert quality.names == (*base.names, *QUALITY_FEATURES)
    assert quality.sha256 != base.sha256


def test_first_168_hours_are_excluded_until_all_lags_exist() -> None:
    hourly = _hourly(periods=220)

    rows = FeaturePipeline().build_features(hourly)

    assert rows.origins[0] == hourly.index[168].to_pydatetime()
    assert rows.values.shape == (220 - 168, len(rows.schema.names))
    assert rows.values[0, rows.schema.names.index("lag_168")] == 0.0


def test_direct_targets_have_24_columns_in_chronological_order() -> None:
    hourly = _hourly(periods=220)

    matrix = FeaturePipeline().build_supervised(hourly)

    assert matrix.targets.shape == (220 - 168 - 24, 24)
    origin_position = 168
    assert matrix.targets[0].tolist() == pytest.approx(
        hourly["energy_kwh"].iloc[origin_position + 1 : origin_position + 25].tolist()
    )


def test_shifted_rolling_mean_does_not_include_forecast_origin() -> None:
    hourly = _hourly(periods=220)
    pipeline = FeaturePipeline()

    rows = pipeline.build_features(hourly)
    first = rows.values[0]

    expected = np.mean(np.arange(144, 168, dtype=np.float64))
    assert first[rows.schema.names.index("rolling_mean_24")] == pytest.approx(expected)
    assert first[rows.schema.names.index("lag_1")] == 167.0


def test_mutating_future_target_cannot_change_features_at_origin() -> None:
    hourly = _hourly(periods=240)
    pipeline = FeaturePipeline()
    before = pipeline.build_supervised(hourly)
    origin = before.origins[5]
    origin_position = hourly.index.get_loc(pd.Timestamp(origin))

    changed = hourly.copy()
    changed.iloc[origin_position + 1, changed.columns.get_loc("energy_kwh")] += 100_000
    after = pipeline.build_supervised(changed)

    before_row = before.features[before.origins.index(origin)]
    after_row = after.features[after.origins.index(origin)]
    assert after_row == pytest.approx(before_row)
    assert (
        after.targets[after.origins.index(origin), 0]
        != before.targets[before.origins.index(origin), 0]
    )


def test_missing_hour_is_not_silently_filled_for_lag_features() -> None:
    hourly = _hourly(periods=240)
    missing_timestamp = hourly.index[180]
    hourly = hourly.drop(index=missing_timestamp)

    rows = FeaturePipeline().build_features(hourly)

    assert (missing_timestamp + pd.Timedelta(hours=1)).to_pydatetime() not in rows.origins


def test_calendar_features_use_configured_local_timezone_and_cycles() -> None:
    hourly = _hourly(start="2025-01-01T00:00:00Z", periods=220)
    pipeline = FeaturePipeline(FeaturePipelineConfig(timezone="Europe/Kyiv"))

    rows = pipeline.build_features(hourly)
    first_origin = rows.origins[0]
    first = rows.values[0]
    local_hour = pd.Timestamp(first_origin).tz_convert("Europe/Kyiv").hour

    assert first[rows.schema.names.index("hour")] == local_hour
    assert first[rows.schema.names.index("hour_sin")] == pytest.approx(
        np.sin(2 * np.pi * local_hour / 24)
    )
    assert first[rows.schema.names.index("hour_cos")] == pytest.approx(
        np.cos(2 * np.pi * local_hour / 24)
    )


def test_quality_features_only_summarize_past_rows() -> None:
    hourly = _hourly(periods=240, with_quality=True)
    pipeline = FeaturePipeline(FeaturePipelineConfig(include_quality_features=True))
    before = pipeline.build_features(hourly)
    origin = before.origins[0]
    origin_position = hourly.index.get_loc(pd.Timestamp(origin))

    changed = hourly.copy()
    changed.iloc[origin_position + 1, changed.columns.get_loc("coverage_ratio")] = 0.0
    changed.iloc[origin_position + 1, changed.columns.get_loc("quality_status")] = (
        "imputed_short_gap"
    )
    after = pipeline.build_features(changed)

    assert after.values[after.origins.index(origin)] == pytest.approx(
        before.values[before.origins.index(origin)]
    )


@pytest.mark.parametrize(
    ("fold_index", "validation_start", "validation_end"),
    [(index, start, end) for index, (start, end) in enumerate(VALIDATION_PERIODS)],
)
def test_expanding_fold_boundaries_and_24_hour_purge(
    fold_index: int, validation_start: datetime, validation_end: datetime
) -> None:
    origins = _protocol_origins()

    fold = ChronologicalSplitProtocol().cross_validation_folds(origins)[fold_index]

    assert origins[int(fold.validation_indices[0])] == validation_start
    assert origins[int(fold.validation_indices[-1])] == validation_end - timedelta(hours=1)
    assert fold.train_end + timedelta(hours=24) < validation_start
    assert fold.train_end == validation_start - timedelta(hours=25)
    assert (
        fold.train_indices.size
        < (ChronologicalSplitProtocol().cross_validation_folds(origins)[-1].train_indices.size)
        or fold_index == len(VALIDATION_PERIODS) - 1
    )


def test_cross_validation_api_never_returns_final_test_rows() -> None:
    origins = _protocol_origins()
    protocol = ChronologicalSplitProtocol()

    folds = protocol.cross_validation_folds(origins)
    final_indices = protocol.final_test_indices(origins)

    assert final_indices.size > 0
    assert origins[int(final_indices[0])] == FINAL_TEST_START
    assert all(
        origins[int(index)] < FINAL_TEST_START
        for fold in folds
        for index in (*fold.train_indices, *fold.validation_indices)
    )


def test_preprocessing_is_fitted_only_on_each_fold_training_rows() -> None:
    origins = _protocol_origins()
    fold = ChronologicalSplitProtocol().cross_validation_folds(origins)[0]
    features = np.arange(len(origins) * 2, dtype=np.float64).reshape(len(origins), 2)
    targets = np.zeros((len(origins), 24), dtype=np.float64)
    created: list[_RecordingTransformer] = []

    def factory() -> _RecordingTransformer:
        transformer = _RecordingTransformer()
        created.append(transformer)
        return transformer

    prepared = prepare_fold(features, targets, fold, factory)

    assert len(created) == 1
    assert created[0].fitted_values == pytest.approx(features[fold.train_indices])
    assert created[0].fitted_values.shape[0] == fold.train_indices.size
    assert prepared.validation_features.shape[0] == fold.validation_indices.size
    assert not np.isin(fold.validation_indices, fold.train_indices).any()


class _RecordingTransformer:
    def __init__(self) -> None:
        self.fitted_values = np.empty((0, 0), dtype=np.float64)
        self._mean = np.empty((0,), dtype=np.float64)

    def fit(self, values: NDArray[np.float64]) -> Self:
        self.fitted_values = values.copy()
        self._mean = values.mean(axis=0)
        return self

    def transform(self, values: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.asarray(values - self._mean, dtype=np.float64)


def _hourly(
    *,
    start: str = "2008-01-01T00:00:00Z",
    periods: int,
    with_quality: bool = False,
) -> pd.DataFrame:
    index = pd.date_range(start=start, periods=periods, freq="h")
    frame = pd.DataFrame({"energy_kwh": np.arange(periods, dtype=np.float64)}, index=index)
    if with_quality:
        frame["coverage_ratio"] = 1.0
        frame["quality_status"] = "complete"
    return frame


def _protocol_origins() -> tuple[datetime, ...]:
    origins = {
        datetime(2008, 1, 1, tzinfo=UTC),
        FINAL_TEST_START,
        FINAL_TEST_START + timedelta(hours=1),
    }
    for start, end in VALIDATION_PERIODS:
        origins.update(
            {
                start - timedelta(hours=25),
                start - timedelta(hours=24),
                start - timedelta(hours=1),
                start,
                end - timedelta(hours=1),
            }
        )
    return tuple(sorted(origins))
