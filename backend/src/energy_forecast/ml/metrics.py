"""Deterministic metrics for direct multi-horizon forecasts."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class MetricSet:
    mae: float
    rmse: float
    smape: float
    mae_per_horizon: tuple[float, ...]


def evaluate(actual: NDArray[np.float64], predicted: NDArray[np.float64]) -> MetricSet:
    actual_values, predicted_values = _validated(actual, predicted)
    return MetricSet(
        mae=float(np.mean(np.abs(actual_values - predicted_values))),
        rmse=float(np.sqrt(np.mean(np.square(actual_values - predicted_values)))),
        smape=_smape_values(actual_values, predicted_values),
        mae_per_horizon=tuple(
            float(value) for value in np.mean(np.abs(actual_values - predicted_values), axis=0)
        ),
    )


def mae(actual: NDArray[np.float64], predicted: NDArray[np.float64]) -> float:
    return evaluate(actual, predicted).mae


def rmse(actual: NDArray[np.float64], predicted: NDArray[np.float64]) -> float:
    return evaluate(actual, predicted).rmse


def smape(actual: NDArray[np.float64], predicted: NDArray[np.float64]) -> float:
    actual_values, predicted_values = _validated(actual, predicted)
    return _smape_values(actual_values, predicted_values)


def mae_by_horizon(
    actual: NDArray[np.float64], predicted: NDArray[np.float64]
) -> tuple[float, ...]:
    return evaluate(actual, predicted).mae_per_horizon


def improvement_percent(*, baseline_mae: float, model_mae: float) -> float:
    if baseline_mae < 0 or model_mae < 0:
        raise ValueError("MAE values must be non-negative")
    if baseline_mae == 0:
        if model_mae == 0:
            return 0.0
        raise ValueError("Improvement is undefined when baseline MAE is zero")
    return (baseline_mae - model_mae) / baseline_mae * 100


def _validated(
    actual: NDArray[np.float64], predicted: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    actual_values = np.asarray(actual, dtype=np.float64)
    predicted_values = np.asarray(predicted, dtype=np.float64)
    if actual_values.ndim != 2 or predicted_values.ndim != 2:
        raise ValueError("metrics require two-dimensional matrices")
    if actual_values.shape != predicted_values.shape or actual_values.shape[1] != 24:
        raise ValueError("actual and predicted values must have matching (n_origins, 24) shapes")
    if actual_values.shape[0] == 0:
        raise ValueError("metrics require at least one forecast origin")
    if not np.isfinite(actual_values).all() or not np.isfinite(predicted_values).all():
        raise ValueError("metrics require finite values")
    return actual_values, predicted_values


def _smape_values(actual: NDArray[np.float64], predicted: NDArray[np.float64]) -> float:
    denominator = np.abs(actual) + np.abs(predicted)
    contribution = np.divide(
        2 * np.abs(actual - predicted),
        denominator,
        out=np.zeros_like(denominator),
        where=denominator != 0,
    )
    return float(np.mean(contribution) * 100)
