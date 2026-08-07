"""Reproducible training, prediction and serialized-size measurements."""

from __future__ import annotations

import io
import time
from collections.abc import Callable
from dataclasses import dataclass

import joblib
import numpy as np
from numpy.typing import NDArray

from energy_forecast.ml.models import DirectRegressionModel


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    model: DirectRegressionModel
    train_seconds_median: float
    prediction_ms_median: float
    prediction_ms_p95: float
    artifact_size_bytes: int
    training_repetitions: int
    prediction_repetitions: int


def benchmark_model(
    factory: Callable[[], DirectRegressionModel],
    train_features: NDArray[np.float64],
    train_targets: NDArray[np.float64],
    prediction_features: NDArray[np.float64],
    *,
    training_repetitions: int = 3,
    prediction_repetitions: int = 30,
) -> BenchmarkResult:
    if training_repetitions < 1 or prediction_repetitions < 1:
        raise ValueError("benchmark repetition counts must be positive")

    warmup = factory().fit(train_features, train_targets)
    warmup.predict(prediction_features)

    train_times: list[float] = []
    measured_model = warmup
    for _ in range(training_repetitions):
        measured_model = factory()
        started = time.perf_counter()
        measured_model.fit(train_features, train_targets)
        train_times.append(time.perf_counter() - started)

    measured_model.predict(prediction_features)
    prediction_times_ms: list[float] = []
    for _ in range(prediction_repetitions):
        started = time.perf_counter()
        measured_model.predict(prediction_features)
        prediction_times_ms.append((time.perf_counter() - started) * 1000)

    serialized = io.BytesIO()
    joblib.dump(measured_model, serialized, compress=3)
    return BenchmarkResult(
        model=measured_model,
        train_seconds_median=float(np.median(train_times)),
        prediction_ms_median=float(np.median(prediction_times_ms)),
        prediction_ms_p95=float(np.percentile(prediction_times_ms, 95)),
        artifact_size_bytes=len(serialized.getvalue()),
        training_repetitions=training_repetitions,
        prediction_repetitions=prediction_repetitions,
    )
