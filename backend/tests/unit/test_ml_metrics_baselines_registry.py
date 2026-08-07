from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from energy_forecast.ml.baselines import MissingBaselineHistoryError, SeasonalNaive
from energy_forecast.ml.metrics import evaluate, improvement_percent, smape
from energy_forecast.ml.registry import AlgorithmRegistry, AlgorithmType, UnknownAlgorithmError


def test_metrics_match_known_multi_horizon_values() -> None:
    actual = np.zeros((2, 24), dtype=np.float64)
    predicted = np.ones((2, 24), dtype=np.float64)

    metrics = evaluate(actual, predicted)

    assert metrics.mae == 1.0
    assert metrics.rmse == 1.0
    assert metrics.smape == 200.0
    assert metrics.mae_per_horizon == tuple(1.0 for _ in range(24))


def test_smape_treats_zero_zero_pair_as_zero_contribution() -> None:
    actual = np.zeros((1, 24), dtype=np.float64)
    predicted = np.zeros((1, 24), dtype=np.float64)
    predicted[0, 0] = 1.0

    assert smape(actual, predicted) == pytest.approx(200 / 24)


def test_metrics_reject_wrong_shapes_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="matching"):
        evaluate(np.zeros((2, 24)), np.zeros((2, 23)))
    with pytest.raises(ValueError, match="finite"):
        evaluate(np.zeros((1, 24)), np.full((1, 24), np.nan))


def test_improvement_handles_zero_baseline_explicitly() -> None:
    assert improvement_percent(baseline_mae=2.0, model_mae=1.5) == pytest.approx(25.0)
    assert improvement_percent(baseline_mae=0.0, model_mae=0.0) == 0.0
    with pytest.raises(ValueError, match="undefined"):
        improvement_percent(baseline_mae=0.0, model_mae=1.0)


def test_seasonal_naive_24_has_zero_error_on_exact_daily_fixture() -> None:
    series = _seasonal_series(period=24, days=12)
    origins = _origins(series.index, start=24 * 7, count=24)
    actual = _actual_targets(series, origins)

    predicted = SeasonalNaive(24).predict(series, origins)

    assert predicted.shape == (len(origins), 24)
    assert evaluate(actual, predicted).mae == 0.0


def test_seasonal_baselines_use_the_same_caller_supplied_origins() -> None:
    series = _seasonal_series(period=168, days=20)
    origins = _origins(series.index, start=168 + 24, count=12)

    daily = SeasonalNaive(24).predict(series, origins)
    weekly = SeasonalNaive(168).predict(series, origins)

    assert daily.shape == weekly.shape == (12, 24)


def test_seasonal_naive_refuses_missing_required_history() -> None:
    series = _seasonal_series(period=24, days=10)
    origin = series.index[24 * 5]
    missing_source = origin + pd.Timedelta(hours=1 - 24)
    series = series.drop(index=missing_source)

    with pytest.raises(MissingBaselineHistoryError, match="missing seasonal history"):
        SeasonalNaive(24).predict(series, (origin.to_pydatetime(),))


def test_algorithm_registry_exposes_bounded_reproducible_defaults() -> None:
    registry = AlgorithmRegistry()

    assert tuple(item.algorithm for item in registry.list()) == tuple(AlgorithmType)
    assert registry.get(AlgorithmType.RIDGE).default_search_space["alpha"] == (
        0.01,
        0.1,
        1.0,
        10.0,
        100.0,
        1000.0,
    )
    forest = registry.get(AlgorithmType.RANDOM_FOREST).default_search_space
    assert forest["random_state"] == (42,)
    assert forest["n_estimators"] == (300, 600)
    boosting = registry.get(AlgorithmType.HIST_GRADIENT_BOOSTING).default_search_space
    assert boosting["early_stopping"] == (False,)


def test_algorithm_registry_rejects_unknown_type() -> None:
    with pytest.raises(UnknownAlgorithmError, match="Unsupported"):
        AlgorithmRegistry().get("lstm")


def _seasonal_series(*, period: int, days: int) -> pd.Series:
    index = pd.date_range("2008-01-01T00:00:00Z", periods=24 * days, freq="h")
    values = np.arange(24 * days, dtype=np.float64) % period
    return pd.Series(values, index=index, name="energy_kwh")


def _origins(index: pd.DatetimeIndex, *, start: int, count: int) -> tuple[datetime, ...]:
    return tuple(index[start : start + count].to_pydatetime())


def _actual_targets(series: pd.Series, origins: tuple[datetime, ...]) -> np.ndarray:
    return np.asarray(
        [
            [
                series.at[pd.Timestamp(origin) + pd.Timedelta(hours=horizon)]
                for horizon in range(1, 25)
            ]
            for origin in origins
        ],
        dtype=np.float64,
    )
