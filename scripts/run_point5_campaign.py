#!/usr/bin/env python3
"""Execute the final Point-5 scientific campaign on a prepared full UCI version.

The campaign is intentionally separate from the normal product UI because W1 uses
future ERA5-Land reanalysis and is therefore an idealized research ablation rather
than an operational weather-forecast feature.  All W0 feature construction, split
logic, metrics, model registry/search spaces and selection rules reuse the shipped
EnergyForecast implementation.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import importlib.metadata
import io
import json
import math
import os
import platform
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, cast
from uuid import UUID

import joblib
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.database import (
    SqlAlchemyArtifactMetadataRepository,
    SqlAlchemyExperimentRepository,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.experiments.selection import SelectionCandidate, select_recommended
from energy_forecast.forecasting.engine import ForecastEngine
from energy_forecast.ml.baselines import SeasonalNaive
from energy_forecast.ml.bundles import (
    BundleCompatibilityPolicy,
    BundleManifestInput,
    ModelBundleService,
)
from energy_forecast.ml.features import FeatureMatrix, FeaturePipeline, FeaturePipelineConfig
from energy_forecast.ml.metrics import MetricSet, evaluate, improvement_percent
from energy_forecast.ml.models import ExecutionProfile, ModelRuntime, create_model
from energy_forecast.ml.ports import Predictor
from energy_forecast.ml.registry import AlgorithmRegistry, AlgorithmType
from energy_forecast.ml.search import candidate_configurations
from energy_forecast.ml.splits import FINAL_TEST_START, SPLIT_DEFINITION_V1, ChronologicalSplitProtocol

WEATHER_COLUMNS = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation",
    "wind_speed_10m",
)
MAIN_ELIGIBLE = frozenset({"complete", "imputed_short_gap"})
SAFE_PARTIAL = frozenset({"complete", "imputed_short_gap", "valid_partial", "invalid_missing"})
TREE_ALGORITHMS = frozenset({AlgorithmType.RANDOM_FOREST, AlgorithmType.HIST_GRADIENT_BOOSTING})
ML_ALGORITHMS = (
    AlgorithmType.RIDGE,
    AlgorithmType.RANDOM_FOREST,
    AlgorithmType.HIST_GRADIENT_BOOSTING,
)


@dataclass(frozen=True, slots=True)
class FoldResult:
    fold_no: int
    train_rows: int
    validation_rows: int
    mae: float
    rmse: float
    smape: float
    train_seconds: float
    predict_ms_per_origin: float


@dataclass(frozen=True, slots=True)
class CvResult:
    experiment_id: str
    algorithm: AlgorithmType
    weather_mode: str
    quality_profile: str
    parameters: dict[str, Any]
    folds: tuple[FoldResult, ...]
    actual: NDArray[np.float64]
    predicted: NDArray[np.float64]
    overall: MetricSet
    mean_cv_mae: float
    std_cv_mae: float
    train_seconds_median: float
    predict_ms_median: float


@dataclass(slots=True)
class WeatherDirectModel:
    algorithm: AlgorithmType
    parameters: dict[str, Any]
    estimators: list[Any]
    scalers: list[StandardScaler | None]

    def predict(
        self,
        base_features: NDArray[np.float64],
        weather_cube: NDArray[np.float64],
    ) -> NDArray[np.float64]:
        if len(self.estimators) != 24 or len(self.scalers) != 24:
            raise RuntimeError("Weather direct model is not fitted")
        rows = int(base_features.shape[0])
        result = np.empty((rows, 24), dtype=np.float64)
        with threadpool_limits(limits=1):
            for horizon in range(24):
                values = np.column_stack((base_features, weather_cube[:, horizon, :]))
                scaler = self.scalers[horizon]
                if scaler is not None:
                    values = np.asarray(scaler.transform(values), dtype=np.float64)
                result[:, horizon] = self.estimators[horizon].predict(values)
        return result


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, AlgorithmType):
        return value.value
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n").encode()
    with path.open("wb") as destination:
        destination.write(encoded)
        destination.flush()
        os.fsync(destination.fileno())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quality_view(hourly: pd.DataFrame, profile: str) -> pd.DataFrame:
    selected = hourly.copy()
    status = selected["quality_status"].astype(str)
    coverage = selected["coverage_ratio"].astype(float)
    finite = selected["energy_kwh"].notna()
    if profile == "main_90_complete_or_imputed":
        eligible = finite & coverage.ge(0.9) & status.isin(MAIN_ELIGIBLE)
    elif profile == "complete_only":
        eligible = finite & status.eq("complete")
    elif profile == "coverage_gte_80pct":
        eligible = finite & coverage.ge(0.8) & status.isin(SAFE_PARTIAL)
    else:
        raise ValueError(f"Unknown quality profile: {profile}")
    selected.loc[~eligible, "energy_kwh"] = np.nan
    return selected


def _slice_matrix(matrix: FeatureMatrix, indexes: NDArray[np.int64]) -> FeatureMatrix:
    return FeatureMatrix(
        origins=tuple(matrix.origins[int(index)] for index in indexes),
        features=np.asarray(matrix.features[indexes], dtype=np.float64),
        targets=np.asarray(matrix.targets[indexes], dtype=np.float64),
        schema=matrix.schema,
    )


def _baseline_history_indexes(
    matrix: FeatureMatrix, energy: pd.Series, period_hours: int
) -> NDArray[np.int64]:
    series = energy.copy()
    if not isinstance(series.index, pd.DatetimeIndex) or series.index.tz is None:
        raise ValueError("Hourly energy must be timezone-aware")
    series.index = series.index.tz_convert("UTC")
    valid: list[int] = []
    for index, origin in enumerate(matrix.origins):
        origin_utc = pd.Timestamp(origin).tz_convert("UTC")
        available = True
        for horizon in range(1, 25):
            timestamp = origin_utc + pd.Timedelta(hours=horizon - period_hours)
            if timestamp not in series.index or pd.isna(series.at[timestamp]):
                available = False
                break
        if available:
            valid.append(index)
    return np.asarray(valid, dtype=np.int64)


def _main_matrix(hourly: pd.DataFrame, timezone: str) -> tuple[pd.DataFrame, FeatureMatrix]:
    selected = _quality_view(hourly, "main_90_complete_or_imputed")
    matrix = FeaturePipeline(FeaturePipelineConfig(timezone=timezone)).build_supervised(selected)
    indexes = _baseline_history_indexes(matrix, selected["energy_kwh"], 24)
    if indexes.size == 0:
        raise ValueError("No common W0/Seasonal-24 forecast origins remain after quality filtering")
    return selected, _slice_matrix(matrix, indexes)


def _matrix_for_profile(
    hourly: pd.DataFrame, *, timezone: str, profile: str, require_daily_baseline: bool = True
) -> tuple[pd.DataFrame, FeatureMatrix]:
    selected = _quality_view(hourly, profile)
    matrix = FeaturePipeline(FeaturePipelineConfig(timezone=timezone)).build_supervised(selected)
    if require_daily_baseline:
        indexes = _baseline_history_indexes(matrix, selected["energy_kwh"], 24)
        matrix = _slice_matrix(matrix, indexes)
    return selected, matrix


def _candidate_parameters(algorithm: AlgorithmType, max_tree_candidates: int) -> tuple[dict[str, Any], ...]:
    if algorithm in {AlgorithmType.SEASONAL_NAIVE_24, AlgorithmType.SEASONAL_NAIVE_168}:
        return ({},)
    limit = max_tree_candidates if algorithm in TREE_ALGORITHMS else 20
    return candidate_configurations(algorithm, random_seed=42, max_candidates=limit)


def _predict_w0(
    algorithm: AlgorithmType,
    parameters: dict[str, Any],
    energy: pd.Series,
    matrix: FeatureMatrix,
    train_indexes: NDArray[np.int64],
    validation_indexes: NDArray[np.int64],
) -> tuple[NDArray[np.float64], float]:
    origins = tuple(matrix.origins[int(index)] for index in validation_indexes)
    started = time.perf_counter()
    if algorithm is AlgorithmType.SEASONAL_NAIVE_24:
        return SeasonalNaive(24).predict(energy, origins), 0.0
    if algorithm is AlgorithmType.SEASONAL_NAIVE_168:
        return SeasonalNaive(168).predict(energy, origins), 0.0
    model = create_model(
        algorithm,
        parameters=parameters,
        runtime=ModelRuntime(profile=ExecutionProfile.BENCHMARK, random_seed=42),
    )
    model.fit(matrix.features[train_indexes], matrix.targets[train_indexes])
    train_seconds = time.perf_counter() - started
    return model.predict(matrix.features[validation_indexes]), train_seconds


def _evaluate_w0_configuration(
    experiment_id: str,
    algorithm: AlgorithmType,
    parameters: dict[str, Any],
    energy: pd.Series,
    matrix: FeatureMatrix,
) -> CvResult:
    folds = ChronologicalSplitProtocol().cross_validation_folds(matrix.origins)
    fold_rows: list[FoldResult] = []
    actual_parts: list[NDArray[np.float64]] = []
    predicted_parts: list[NDArray[np.float64]] = []
    for fold in folds:
        predicted, train_seconds = _predict_w0(
            algorithm,
            parameters,
            energy,
            matrix,
            fold.train_indices,
            fold.validation_indices,
        )
        actual = matrix.targets[fold.validation_indices]
        timing_started = time.perf_counter()
        if algorithm is AlgorithmType.SEASONAL_NAIVE_24:
            SeasonalNaive(24).predict(
                energy, tuple(matrix.origins[int(i)] for i in fold.validation_indices)
            )
        elif algorithm is AlgorithmType.SEASONAL_NAIVE_168:
            SeasonalNaive(168).predict(
                energy, tuple(matrix.origins[int(i)] for i in fold.validation_indices)
            )
        else:
            timing_model = create_model(
                algorithm,
                parameters=parameters,
                runtime=ModelRuntime(profile=ExecutionProfile.BENCHMARK, random_seed=42),
            )
            timing_model.fit(matrix.features[fold.train_indices], matrix.targets[fold.train_indices])
            timing_started = time.perf_counter()
            timing_model.predict(matrix.features[fold.validation_indices])
        prediction_ms = (time.perf_counter() - timing_started) * 1000 / len(fold.validation_indices)
        metrics = evaluate(actual, predicted)
        fold_rows.append(
            FoldResult(
                fold_no=fold.fold_no,
                train_rows=len(fold.train_indices),
                validation_rows=len(fold.validation_indices),
                mae=metrics.mae,
                rmse=metrics.rmse,
                smape=metrics.smape,
                train_seconds=train_seconds,
                predict_ms_per_origin=prediction_ms,
            )
        )
        actual_parts.append(actual)
        predicted_parts.append(predicted)
    actual_all = np.vstack(actual_parts)
    predicted_all = np.vstack(predicted_parts)
    fold_mae = [row.mae for row in fold_rows]
    return CvResult(
        experiment_id=experiment_id,
        algorithm=algorithm,
        weather_mode="W0",
        quality_profile="main_90_complete_or_imputed",
        parameters=dict(parameters),
        folds=tuple(fold_rows),
        actual=actual_all,
        predicted=predicted_all,
        overall=evaluate(actual_all, predicted_all),
        mean_cv_mae=float(statistics.fmean(fold_mae)),
        std_cv_mae=float(np.std(np.asarray(fold_mae, dtype=np.float64), ddof=0)),
        train_seconds_median=float(statistics.median(row.train_seconds for row in fold_rows)),
        predict_ms_median=float(statistics.median(row.predict_ms_per_origin for row in fold_rows)),
    )


def _select_best_configuration(results: list[CvResult]) -> CvResult:
    return min(
        results,
        key=lambda result: (
            result.mean_cv_mae,
            result.std_cv_mae,
            json.dumps(result.parameters, sort_keys=True, default=_json_default),
        ),
    )


def _fit_weather_model(
    algorithm: AlgorithmType,
    parameters: dict[str, Any],
    base_features: NDArray[np.float64],
    weather_cube: NDArray[np.float64],
    targets: NDArray[np.float64],
) -> WeatherDirectModel:
    if algorithm not in ML_ALGORITHMS:
        raise ValueError("W1 is defined only for the three ML algorithms")
    estimators: list[Any] = []
    scalers: list[StandardScaler | None] = []
    with threadpool_limits(limits=1):
        for horizon in range(24):
            values = np.column_stack((base_features, weather_cube[:, horizon, :]))
            target = targets[:, horizon]
            if algorithm is AlgorithmType.RIDGE:
                scaler = StandardScaler().fit(values)
                transformed = np.asarray(scaler.transform(values), dtype=np.float64)
                estimator = Ridge(**parameters).fit(transformed, target)
            elif algorithm is AlgorithmType.RANDOM_FOREST:
                scaler = None
                estimator = RandomForestRegressor(**parameters, n_jobs=1).fit(values, target)
            else:
                scaler = None
                estimator = HistGradientBoostingRegressor(**parameters).fit(values, target)
            estimators.append(estimator)
            scalers.append(scaler)
    return WeatherDirectModel(algorithm, dict(parameters), estimators, scalers)


def _evaluate_w1_configuration(
    experiment_id: str,
    algorithm: AlgorithmType,
    parameters: dict[str, Any],
    matrix: FeatureMatrix,
    weather_cube: NDArray[np.float64],
) -> CvResult:
    folds = ChronologicalSplitProtocol().cross_validation_folds(matrix.origins)
    fold_rows: list[FoldResult] = []
    actual_parts: list[NDArray[np.float64]] = []
    predicted_parts: list[NDArray[np.float64]] = []
    for fold in folds:
        started = time.perf_counter()
        model = _fit_weather_model(
            algorithm,
            parameters,
            matrix.features[fold.train_indices],
            weather_cube[fold.train_indices],
            matrix.targets[fold.train_indices],
        )
        train_seconds = time.perf_counter() - started
        prediction_started = time.perf_counter()
        predicted = model.predict(
            matrix.features[fold.validation_indices], weather_cube[fold.validation_indices]
        )
        prediction_ms = (
            (time.perf_counter() - prediction_started) * 1000 / len(fold.validation_indices)
        )
        actual = matrix.targets[fold.validation_indices]
        metrics = evaluate(actual, predicted)
        fold_rows.append(
            FoldResult(
                fold_no=fold.fold_no,
                train_rows=len(fold.train_indices),
                validation_rows=len(fold.validation_indices),
                mae=metrics.mae,
                rmse=metrics.rmse,
                smape=metrics.smape,
                train_seconds=train_seconds,
                predict_ms_per_origin=prediction_ms,
            )
        )
        actual_parts.append(actual)
        predicted_parts.append(predicted)
    actual_all = np.vstack(actual_parts)
    predicted_all = np.vstack(predicted_parts)
    fold_mae = [row.mae for row in fold_rows]
    return CvResult(
        experiment_id=experiment_id,
        algorithm=algorithm,
        weather_mode="W1",
        quality_profile="main_90_complete_or_imputed",
        parameters=dict(parameters),
        folds=tuple(fold_rows),
        actual=actual_all,
        predicted=predicted_all,
        overall=evaluate(actual_all, predicted_all),
        mean_cv_mae=float(statistics.fmean(fold_mae)),
        std_cv_mae=float(np.std(np.asarray(fold_mae, dtype=np.float64), ddof=0)),
        train_seconds_median=float(statistics.median(row.train_seconds for row in fold_rows)),
        predict_ms_median=float(statistics.median(row.predict_ms_per_origin for row in fold_rows)),
    )


def _load_weather(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = {"timestamp", *WEATHER_COLUMNS}.difference(frame.columns)
    if missing:
        raise ValueError(f"Weather CSV is missing columns: {', '.join(sorted(missing))}")
    index = pd.to_datetime(frame.pop("timestamp"), utc=True, errors="raise")
    frame.index = pd.DatetimeIndex(index)
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("Weather timestamps must be unique and increasing")
    for column in WEATHER_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    values = frame.loc[:, WEATHER_COLUMNS].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("Weather input must contain only finite values")
    return frame.loc[:, WEATHER_COLUMNS]


def _weather_cube(matrix: FeatureMatrix, weather: pd.DataFrame) -> NDArray[np.float64]:
    timestamps = [
        pd.Timestamp(origin).tz_convert("UTC") + pd.Timedelta(hours=horizon)
        for origin in matrix.origins
        for horizon in range(1, 25)
    ]
    selected = weather.reindex(pd.DatetimeIndex(timestamps))
    if selected.isna().any(axis=None):
        missing = selected[selected.isna().any(axis=1)].index[:5]
        raise ValueError(f"W1 weather is incomplete at: {list(map(str, missing))}")
    return np.asarray(
        selected.to_numpy(dtype=np.float64).reshape(len(matrix.origins), 24, len(WEATHER_COLUMNS)),
        dtype=np.float64,
    )


def _horizon_metrics(actual: NDArray[np.float64], predicted: NDArray[np.float64]) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for horizon in range(24):
        actual_h = actual[:, horizon]
        predicted_h = predicted[:, horizon]
        absolute = np.abs(actual_h - predicted_h)
        denominator = np.abs(actual_h) + np.abs(predicted_h)
        smape = np.divide(
            2 * absolute,
            denominator,
            out=np.zeros_like(denominator),
            where=denominator != 0,
        )
        rows.append(
            {
                "horizon": float(horizon + 1),
                "mae": float(np.mean(absolute)),
                "rmse": float(np.sqrt(np.mean(np.square(actual_h - predicted_h)))),
                "smape": float(np.mean(smape) * 100),
            }
        )
    return rows


def _fit_final_w0(
    result: CvResult, matrix: FeatureMatrix, train_indexes: NDArray[np.int64]
) -> object:
    if result.algorithm is AlgorithmType.SEASONAL_NAIVE_24:
        return SeasonalNaive(24)
    if result.algorithm is AlgorithmType.SEASONAL_NAIVE_168:
        return SeasonalNaive(168)
    model = create_model(
        result.algorithm,
        parameters=result.parameters,
        runtime=ModelRuntime(profile=ExecutionProfile.BENCHMARK, random_seed=42),
    )
    model.fit(matrix.features[train_indexes], matrix.targets[train_indexes])
    return model


def _predict_final_w0(
    model: object,
    algorithm: AlgorithmType,
    energy: pd.Series,
    matrix: FeatureMatrix,
    indexes: NDArray[np.int64],
) -> NDArray[np.float64]:
    if algorithm is AlgorithmType.SEASONAL_NAIVE_24:
        return SeasonalNaive(24).predict(
            energy, tuple(matrix.origins[int(index)] for index in indexes)
        )
    if algorithm is AlgorithmType.SEASONAL_NAIVE_168:
        return SeasonalNaive(168).predict(
            energy, tuple(matrix.origins[int(index)] for index in indexes)
        )
    return cast(Predictor, model).predict(matrix.features[indexes])


def _paired_block_bootstrap(
    actual: NDArray[np.float64],
    candidate: NDArray[np.float64],
    baseline: NDArray[np.float64],
    *,
    block_size: int = 168,
    repeats: int = 2000,
) -> dict[str, Any]:
    difference = np.mean(np.abs(candidate - actual), axis=1) - np.mean(
        np.abs(baseline - actual), axis=1
    )
    n = difference.size
    if n == 0:
        raise ValueError("Bootstrap requires final-test origins")
    effective_block = min(block_size, n)
    rng = np.random.default_rng(42)
    draws = np.empty(repeats, dtype=np.float64)
    max_start = n - effective_block
    block_count = math.ceil(n / effective_block)
    for repeat in range(repeats):
        sampled: list[float] = []
        for _ in range(block_count):
            start = int(rng.integers(0, max_start + 1)) if max_start else 0
            sampled.extend(difference[start : start + effective_block].tolist())
        draws[repeat] = float(np.mean(np.asarray(sampled[:n], dtype=np.float64)))
    lower, upper = np.quantile(draws, [0.025, 0.975])
    return {
        "method": "paired_moving_block_bootstrap",
        "loss": "per-origin_mean_absolute_error",
        "block_size_origins": effective_block,
        "repeats": repeats,
        "random_seed": 42,
        "observed_mae_difference_candidate_minus_baseline": float(np.mean(difference)),
        "ci95_lower": float(lower),
        "ci95_upper": float(upper),
        "stable_improvement": bool(upper < 0),
    }


def _benchmark_selected(
    result: CvResult,
    energy: pd.Series,
    hourly: pd.DataFrame,
    matrix: FeatureMatrix,
    train_indexes: NDArray[np.int64],
    final_indexes: NDArray[np.int64],
    artifact_path: Path,
    timezone: str,
) -> tuple[dict[str, Any], object]:
    warm_model = _fit_final_w0(result, matrix, train_indexes)
    training_times: list[float] = []
    if result.algorithm in {AlgorithmType.SEASONAL_NAIVE_24, AlgorithmType.SEASONAL_NAIVE_168}:
        training_times = [0.0, 0.0, 0.0]
        final_model = warm_model
    else:
        final_model = warm_model
        for _ in range(3):
            started = time.perf_counter()
            final_model = _fit_final_w0(result, matrix, train_indexes)
            training_times.append(time.perf_counter() - started)

    probe_index = int(final_indexes[0])
    probe_origin = matrix.origins[probe_index]
    if result.algorithm is AlgorithmType.SEASONAL_NAIVE_24:
        predict_once: Callable[[], object] = lambda: SeasonalNaive(24).predict(energy, (probe_origin,))
    elif result.algorithm is AlgorithmType.SEASONAL_NAIVE_168:
        predict_once = lambda: SeasonalNaive(168).predict(energy, (probe_origin,))
    else:
        predict_once = lambda: cast(Predictor, final_model).predict(matrix.features[[probe_index]])
    predict_once()
    prediction_ms: list[float] = []
    for _ in range(30):
        started = time.perf_counter()
        predict_once()
        prediction_ms.append((time.perf_counter() - started) * 1000)

    pipeline = FeaturePipeline(FeaturePipelineConfig(timezone=timezone))
    pipeline.build_features(hourly)
    feature_times: list[float] = []
    for _ in range(3):
        started = time.perf_counter()
        pipeline.build_features(hourly)
        feature_times.append((time.perf_counter() - started) * 1000)

    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(final_model, artifact_path, compress=3)
    return (
        {
            "training": {
                "warmup_runs": 1,
                "measured_runs": 3,
                "seconds": training_times,
                "median_seconds": float(statistics.median(training_times)),
            },
            "prediction": {
                "warmup_runs": 1,
                "measured_runs": 30,
                "median_ms": float(statistics.median(prediction_ms)),
                "p95_ms": float(np.quantile(np.asarray(prediction_ms), 0.95)),
            },
            "feature_preparation": {
                "warmup_runs": 1,
                "measured_runs": 3,
                "median_ms_full_hourly_frame": float(statistics.median(feature_times)),
            },
            "serialized_joblib_bytes": artifact_path.stat().st_size,
            "parallelism": "n_jobs=1 and threadpool limit 1 for scientific benchmark",
        },
        final_model,
    )


def _library_versions() -> dict[str, str]:
    packages = ("numpy", "pandas", "scikit-learn", "joblib", "sqlalchemy", "asyncpg")
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def _svg_line_chart(
    path: Path,
    title: str,
    x_values: list[float],
    series: list[tuple[str, list[float]]],
    *,
    y_label: str,
) -> None:
    width, height = 960, 540
    left, right, top, bottom = 80, 30, 60, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    all_y = [value for _, values in series for value in values]
    y_min = min(0.0, min(all_y))
    y_max = max(all_y)
    if math.isclose(y_min, y_max):
        y_max = y_min + 1.0
    x_min, x_max = min(x_values), max(x_values)
    if math.isclose(x_min, x_max):
        x_max = x_min + 1.0

    def sx(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def sy(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    palette = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd")
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="32" text-anchor="middle" font-family="sans-serif" font-size="22">{title}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#222"/>',
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#222"/>',
        f'<text x="20" y="{top+plot_h/2}" transform="rotate(-90 20 {top+plot_h/2})" font-family="sans-serif" font-size="14">{y_label}</text>',
    ]
    for tick in range(6):
        value = y_min + (y_max - y_min) * tick / 5
        y = sy(value)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="#ddd"/>')
        parts.append(f'<text x="{left-10}" y="{y+5:.1f}" text-anchor="end" font-family="sans-serif" font-size="12">{value:.3f}</text>')
    for index, (label, values) in enumerate(series):
        points = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(x_values, values, strict=True))
        color = palette[index % len(palette)]
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{points}"/>')
        legend_x = left + index * 210
        parts.append(f'<line x1="{legend_x}" y1="{height-25}" x2="{legend_x+28}" y2="{height-25}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x+35}" y="{height-20}" font-family="sans-serif" font-size="13">{label}</text>')
    parts.append("</svg>\n")
    path.write_text("\n".join(parts), encoding="utf-8")


def _svg_bar_chart(path: Path, title: str, labels: list[str], values: list[float]) -> None:
    width, height = 960, 540
    left, right, top, bottom = 80, 30, 60, 100
    plot_w, plot_h = width - left - right, height - top - bottom
    maximum = max(values) * 1.1 if values else 1.0
    bar_w = plot_w / max(1, len(values)) * 0.65
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2}" y="32" text-anchor="middle" font-family="sans-serif" font-size="22">{title}</text>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#222"/>',
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#222"/>',
    ]
    palette = ("#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2", "#b279a2", "#ff9da6")
    slot = plot_w / max(1, len(values))
    for index, (label, value) in enumerate(zip(labels, values, strict=True)):
        x = left + index * slot + (slot - bar_w) / 2
        bar_h = value / maximum * plot_h if maximum else 0
        y = top + plot_h - bar_h
        color = palette[index % len(palette)]
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}"/>')
        parts.append(f'<text x="{x+bar_w/2:.1f}" y="{y-7:.1f}" text-anchor="middle" font-family="sans-serif" font-size="12">{value:.4f}</text>')
        parts.append(f'<text x="{x+bar_w/2:.1f}" y="{top+plot_h+25}" text-anchor="middle" font-family="sans-serif" font-size="12">{label}</text>')
    parts.append("</svg>\n")
    path.write_text("\n".join(parts), encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _experiment_id_for_w0(algorithm: AlgorithmType) -> str:
    return {
        AlgorithmType.SEASONAL_NAIVE_24: "E00",
        AlgorithmType.SEASONAL_NAIVE_168: "E01",
        AlgorithmType.RIDGE: "E10",
        AlgorithmType.RANDOM_FOREST: "E11",
        AlgorithmType.HIST_GRADIENT_BOOSTING: "E12",
    }[algorithm]


def _experiment_id_for_w1(algorithm: AlgorithmType) -> str:
    return {
        AlgorithmType.RIDGE: "E20",
        AlgorithmType.RANDOM_FOREST: "E21",
        AlgorithmType.HIST_GRADIENT_BOOSTING: "E22",
    }[algorithm]


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    preparation = json.loads(args.preparation_json.read_text(encoding="utf-8"))
    handoff = json.loads(args.handoff_json.read_text(encoding="utf-8"))
    weather_metadata = json.loads(args.weather_metadata.read_text(encoding="utf-8"))
    prepared_id = UUID(str(preparation["prepared_dataset_version_id"]))
    if handoff["dataset"]["binding_status"] != "bound_external_uci_profile":
        raise ValueError("Point-5 campaign requires a bound handoff")
    if handoff["dataset"]["prepared_dataset_version_id"] != str(prepared_id):
        raise ValueError("Bound handoff dataset UUID does not match prepared database version")
    if handoff["dataset"]["source_sha256"] != preparation["source_sha256"]:
        raise ValueError("Bound handoff SHA-256 does not match imported UCI source")

    engine = create_database_engine(args.database_url)
    session_factory = create_session_factory(engine)
    repository = SqlAlchemyExperimentRepository(session_factory)
    try:
        hourly = await repository.load_hourly(prepared_id)
        if hourly.empty:
            raise ValueError("Prepared dataset version has no hourly observations")
        hourly.index = hourly.index.tz_convert("UTC")
        timezone = "Europe/Paris"
        main_hourly, main_matrix = _main_matrix(hourly, timezone)
        protocol = ChronologicalSplitProtocol()
        main_folds = protocol.cross_validation_folds(main_matrix.origins)
        if len(main_folds) != 4:
            raise ValueError("Point-5 main matrix must expose exactly four validation folds")

        search_rows: list[dict[str, object]] = []
        best_w0: dict[AlgorithmType, CvResult] = {}
        algorithms_w0 = (
            AlgorithmType.SEASONAL_NAIVE_24,
            AlgorithmType.RIDGE,
            AlgorithmType.RANDOM_FOREST,
            AlgorithmType.HIST_GRADIENT_BOOSTING,
        )
        for algorithm in algorithms_w0:
            candidates: list[CvResult] = []
            for candidate_no, parameters in enumerate(
                _candidate_parameters(algorithm, args.max_tree_candidates), start=1
            ):
                result = _evaluate_w0_configuration(
                    _experiment_id_for_w0(algorithm),
                    algorithm,
                    parameters,
                    main_hourly["energy_kwh"],
                    main_matrix,
                )
                candidates.append(result)
                search_rows.append(
                    {
                        "experiment_id": result.experiment_id,
                        "algorithm": algorithm.value,
                        "weather_mode": "W0",
                        "candidate_no": candidate_no,
                        "parameters_json": json.dumps(parameters, sort_keys=True, default=_json_default),
                        "mean_cv_mae": result.mean_cv_mae,
                        "std_cv_mae": result.std_cv_mae,
                        "overall_cv_rmse": result.overall.rmse,
                        "overall_cv_smape": result.overall.smape,
                    }
                )
            best_w0[algorithm] = _select_best_configuration(candidates)

        # E01 is a diagnostic and is deliberately excluded from final recommendation.
        weekly_indexes = _baseline_history_indexes(main_matrix, main_hourly["energy_kwh"], 168)
        weekly_matrix = _slice_matrix(main_matrix, weekly_indexes)
        weekly_result = _evaluate_w0_configuration(
            "E01",
            AlgorithmType.SEASONAL_NAIVE_168,
            {},
            main_hourly["energy_kwh"],
            weekly_matrix,
        )
        best_w0[AlgorithmType.SEASONAL_NAIVE_168] = weekly_result
        search_rows.append(
            {
                "experiment_id": "E01",
                "algorithm": AlgorithmType.SEASONAL_NAIVE_168.value,
                "weather_mode": "W0",
                "candidate_no": 1,
                "parameters_json": "{}",
                "mean_cv_mae": weekly_result.mean_cv_mae,
                "std_cv_mae": weekly_result.std_cv_mae,
                "overall_cv_rmse": weekly_result.overall.rmse,
                "overall_cv_smape": weekly_result.overall.smape,
            }
        )

        weather = _load_weather(args.weather_csv.resolve())
        weather_cube = _weather_cube(main_matrix, weather)
        best_w1: dict[AlgorithmType, CvResult] = {}
        for algorithm in ML_ALGORITHMS:
            candidates = []
            for candidate_no, parameters in enumerate(
                _candidate_parameters(algorithm, args.max_tree_candidates), start=1
            ):
                result = _evaluate_w1_configuration(
                    _experiment_id_for_w1(algorithm),
                    algorithm,
                    parameters,
                    main_matrix,
                    weather_cube,
                )
                candidates.append(result)
                search_rows.append(
                    {
                        "experiment_id": result.experiment_id,
                        "algorithm": algorithm.value,
                        "weather_mode": "W1",
                        "candidate_no": candidate_no,
                        "parameters_json": json.dumps(parameters, sort_keys=True, default=_json_default),
                        "mean_cv_mae": result.mean_cv_mae,
                        "std_cv_mae": result.std_cv_mae,
                        "overall_cv_rmse": result.overall.rmse,
                        "overall_cv_smape": result.overall.smape,
                    }
                )
            best_w1[algorithm] = _select_best_configuration(candidates)

        selection = select_recommended(
            tuple(
                SelectionCandidate(
                    algorithm=result.algorithm,
                    model_run_id=result.experiment_id,
                    mean_cv_mae=result.mean_cv_mae,
                    std_cv_mae=result.std_cv_mae,
                    predict_ms_median=result.predict_ms_median,
                )
                for algorithm, result in best_w0.items()
                if algorithm is not AlgorithmType.SEASONAL_NAIVE_168
            )
        )
        selected_w0 = best_w0[selection.algorithm]
        selection_payload = {
            "schema": "energyforecast-point5-selection/v1",
            "persisted_at": datetime.now(UTC).isoformat(),
            "release_candidate_sha": args.release_candidate_sha,
            "dataset_sha256": preparation["source_sha256"],
            "prepared_dataset_version_id": str(prepared_id),
            "split_definition": SPLIT_DEFINITION_V1,
            "selection_rule": "cv-mae-1pct-std-5pct-time-simplicity/v1",
            "final_test_accessed_when_written": False,
            "selected_experiment_id": selected_w0.experiment_id,
            "selected_algorithm": selected_w0.algorithm.value,
            "selected_parameters": selected_w0.parameters,
            "mean_cv_mae": selected_w0.mean_cv_mae,
            "std_cv_mae": selected_w0.std_cv_mae,
            "predict_ms_median": selected_w0.predict_ms_median,
            "candidate_summary": [
                {
                    "experiment_id": result.experiment_id,
                    "algorithm": result.algorithm.value,
                    "mean_cv_mae": result.mean_cv_mae,
                    "std_cv_mae": result.std_cv_mae,
                    "predict_ms_median": result.predict_ms_median,
                }
                for algorithm, result in best_w0.items()
                if algorithm is not AlgorithmType.SEASONAL_NAIVE_168
            ],
        }
        selection_path = output_dir / "selection-decision.json"
        _write_json(selection_path, selection_payload)
        selection_sha = _sha256(selection_path)

        # The final 2010 indexes are requested only after the immutable selection file exists.
        if not selection_path.is_file() or selection_payload["final_test_accessed_when_written"]:
            raise RuntimeError("Selection evidence was not persisted before final-test access")
        final_indexes = protocol.final_test_indices(main_matrix.origins)
        if final_indexes.size == 0:
            raise ValueError("Final 2010 test contains no common eligible origins")
        train_cutoff = FINAL_TEST_START - timedelta(hours=24)
        train_indexes = np.asarray(
            [
                index
                for index, origin in enumerate(main_matrix.origins)
                if origin < train_cutoff
            ],
            dtype=np.int64,
        )
        if train_indexes.size == 0:
            raise ValueError("No final-training origins exist before 2010")

        benchmark, selected_model = _benchmark_selected(
            selected_w0,
            main_hourly["energy_kwh"],
            main_hourly,
            main_matrix,
            train_indexes,
            final_indexes,
            output_dir / "selected-model.joblib",
            timezone,
        )
        selected_predictions = _predict_final_w0(
            selected_model,
            selected_w0.algorithm,
            main_hourly["energy_kwh"],
            main_matrix,
            final_indexes,
        )
        actual_final = main_matrix.targets[final_indexes]
        selected_final_metrics = evaluate(actual_final, selected_predictions)
        baseline_predictions = SeasonalNaive(24).predict(
            main_hourly["energy_kwh"],
            tuple(main_matrix.origins[int(index)] for index in final_indexes),
        )
        baseline_final_metrics = evaluate(actual_final, baseline_predictions)
        improvement = improvement_percent(
            baseline_mae=baseline_final_metrics.mae,
            model_mae=selected_final_metrics.mae,
        )
        bootstrap = _paired_block_bootstrap(
            actual_final, selected_predictions, baseline_predictions, block_size=168, repeats=2000
        )

        selected_w1_result = best_w1.get(selected_w0.algorithm)
        selected_w1_predictions: NDArray[np.float64] | None = None
        selected_w1_metrics: MetricSet | None = None
        if selected_w1_result is not None:
            weather_model = _fit_weather_model(
                selected_w1_result.algorithm,
                selected_w1_result.parameters,
                main_matrix.features[train_indexes],
                weather_cube[train_indexes],
                main_matrix.targets[train_indexes],
            )
            selected_w1_predictions = weather_model.predict(
                main_matrix.features[final_indexes], weather_cube[final_indexes]
            )
            selected_w1_metrics = evaluate(actual_final, selected_w1_predictions)

        # E30/E31/E32 use the already-selected W0 configuration and never affect selection.
        complete_hourly, complete_matrix = _matrix_for_profile(
            hourly, timezone=timezone, profile="complete_only"
        )
        e30 = _evaluate_w0_configuration(
            "E30",
            selected_w0.algorithm,
            selected_w0.parameters,
            complete_hourly["energy_kwh"],
            complete_matrix,
        )
        coverage80_hourly, coverage80_matrix = _matrix_for_profile(
            hourly, timezone=timezone, profile="coverage_gte_80pct"
        )
        e31 = _evaluate_w0_configuration(
            "E31",
            selected_w0.algorithm,
            selected_w0.parameters,
            coverage80_hourly["energy_kwh"],
            coverage80_matrix,
        )
        e32 = CvResult(
            experiment_id="E32",
            algorithm=selected_w0.algorithm,
            weather_mode="W0",
            quality_profile="main_90_complete_or_imputed",
            parameters=dict(selected_w0.parameters),
            folds=selected_w0.folds,
            actual=selected_w0.actual,
            predicted=selected_w0.predicted,
            overall=selected_w0.overall,
            mean_cv_mae=selected_w0.mean_cv_mae,
            std_cv_mae=selected_w0.std_cv_mae,
            train_seconds_median=selected_w0.train_seconds_median,
            predict_ms_median=selected_w0.predict_ms_median,
        )

        # Save and checksum-verify the selected W0 model through the real artifact boundary,
        # then exercise the production ForecastEngine for a genuine 24-hour forecast.
        artifacts = ArtifactService(
            LocalArtifactStore(args.artifact_root.resolve()),
            SqlAlchemyArtifactMetadataRepository(session_factory),
        )
        bundle_service = ModelBundleService(artifacts)
        descriptor = AlgorithmRegistry().get(selected_w0.algorithm)
        bundle = await bundle_service.save(
            cast(Predictor, selected_model),
            BundleManifestInput(
                algorithm=selected_w0.algorithm,
                implementation_version=descriptor.implementation_version,
                feature_schema=main_matrix.schema,
                training_dataset_version_id=prepared_id,
                split_definition=SPLIT_DEFINITION_V1,
                code_commit=args.release_candidate_sha,
                model_parameters=selected_w0.parameters,
                quality_policy={
                    "sensitivity_mode": "coverage_90",
                    "scientific_training_filter": "complete_or_imputed_short_gap",
                },
                weather_mode="W0",
            ),
        )
        loaded = await bundle_service.load(
            bundle.artifact_id,
            BundleCompatibilityPolicy(
                feature_schema_version=main_matrix.schema.version,
                feature_schema_sha256=main_matrix.schema.sha256,
                training_dataset_version_id=prepared_id,
                algorithm=selected_w0.algorithm,
                implementation_version=descriptor.implementation_version,
            ),
        )
        feature_rows = FeaturePipeline(FeaturePipelineConfig(timezone=timezone)).build_features(
            main_hourly
        )
        eligible_forecast_origins = [
            origin
            for origin in feature_rows.origins
            if pd.notna(main_hourly.at[pd.Timestamp(origin), "energy_kwh"])
        ]
        if not eligible_forecast_origins:
            raise ValueError("No product forecast origin remains after final training")
        forecast_origin = eligible_forecast_origins[-1]
        forecast = ForecastEngine().create(
            hourly,
            origin=forecast_origin,
            predictor=loaded.predictor,
            manifest=loaded.manifest,
            timezone=timezone,
        )
        forecast_payload = {
            "schema": "energyforecast-point5-product-forecast/v1",
            "origin": forecast.origin.isoformat(),
            "algorithm": selected_w0.algorithm.value,
            "model_bundle_artifact_id": str(bundle.artifact_id),
            "model_bundle_sha256": bundle.bundle_sha256,
            "model_bundle_size_bytes": bundle.size_bytes,
            "total_energy_kwh": forecast.total_energy_kwh,
            "points": [
                {
                    "horizon": point.horizon,
                    "target_time": point.target_time.isoformat(),
                    "predicted_energy_kwh": point.predicted_energy_kwh,
                }
                for point in forecast.points
            ],
        }
        if len(forecast_payload["points"]) != 24:
            raise RuntimeError("Final product forecast does not contain exactly 24 points")
        _write_json(output_dir / "product-forecast.json", forecast_payload)

        benchmark.update(
            {
                "machine": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "processor": platform.processor(),
                    "logical_cpus": os.cpu_count(),
                },
                "library_versions": _library_versions(),
                "model_bundle_bytes": bundle.size_bytes,
            }
        )
        _write_json(output_dir / "benchmark.json", benchmark)
        _write_json(output_dir / "bootstrap.json", bootstrap)
        _write_json(output_dir / "dataset-preparation.json", preparation)
        _write_json(output_dir / "weather-metadata.json", weather_metadata)
        _write_json(output_dir / "point5-handoff.json", handoff)

        all_results = [
            best_w0[AlgorithmType.SEASONAL_NAIVE_24],
            best_w0[AlgorithmType.SEASONAL_NAIVE_168],
            best_w0[AlgorithmType.RIDGE],
            best_w0[AlgorithmType.RANDOM_FOREST],
            best_w0[AlgorithmType.HIST_GRADIENT_BOOSTING],
            best_w1[AlgorithmType.RIDGE],
            best_w1[AlgorithmType.RANDOM_FOREST],
            best_w1[AlgorithmType.HIST_GRADIENT_BOOSTING],
            e30,
            e31,
            e32,
        ]
        final_by_experiment: dict[str, tuple[MetricSet, NDArray[np.float64]]] = {
            "E00": (baseline_final_metrics, baseline_predictions),
            selected_w0.experiment_id: (selected_final_metrics, selected_predictions),
        }
        if selected_w1_result is not None and selected_w1_metrics is not None and selected_w1_predictions is not None:
            final_by_experiment[selected_w1_result.experiment_id] = (
                selected_w1_metrics,
                selected_w1_predictions,
            )

        final_rows: list[dict[str, object]] = []
        horizon_rows: list[dict[str, object]] = []
        fold_rows: list[dict[str, object]] = []
        for result in all_results:
            final_item = final_by_experiment.get(result.experiment_id)
            final_metric = final_item[0] if final_item else None
            is_recommended = result.experiment_id == selected_w0.experiment_id
            final_rows.append(
                {
                    "experiment_id": result.experiment_id,
                    "algorithm": result.algorithm.value,
                    "weather_mode": result.weather_mode,
                    "quality_profile": result.quality_profile,
                    "feature_schema_version": (
                        main_matrix.schema.version if result.weather_mode == "W0" else "base_v1+era5_land_horizon_v1"
                    ),
                    "split_definition": SPLIT_DEFINITION_V1,
                    "mean_cv_mae": result.mean_cv_mae,
                    "std_cv_mae": result.std_cv_mae,
                    "final_mae": "" if final_metric is None else final_metric.mae,
                    "final_rmse": "" if final_metric is None else final_metric.rmse,
                    "final_smape": "" if final_metric is None else final_metric.smape,
                    "train_time_seconds": (
                        benchmark["training"]["median_seconds"]
                        if is_recommended
                        else result.train_seconds_median
                    ),
                    "prediction_median_ms": (
                        benchmark["prediction"]["median_ms"]
                        if is_recommended
                        else result.predict_ms_median
                    ),
                    "prediction_p95_ms": (
                        benchmark["prediction"]["p95_ms"] if is_recommended else ""
                    ),
                    "artifact_size_bytes": (
                        benchmark["serialized_joblib_bytes"] if is_recommended else ""
                    ),
                    "recommended": str(is_recommended).lower(),
                    "notes": (
                        "selected before final test"
                        if is_recommended
                        else "W1 idealized reanalysis" if result.weather_mode == "W1" else ""
                    ),
                }
            )
            cv_horizon = _horizon_metrics(result.actual, result.predicted)
            final_horizon = (
                _horizon_metrics(actual_final, final_item[1]) if final_item is not None else None
            )
            for horizon in range(24):
                horizon_rows.append(
                    {
                        "experiment_id": result.experiment_id,
                        "algorithm": result.algorithm.value,
                        "horizon": horizon + 1,
                        "cv_mae": cv_horizon[horizon]["mae"],
                        "final_mae": "" if final_horizon is None else final_horizon[horizon]["mae"],
                        "final_rmse": "" if final_horizon is None else final_horizon[horizon]["rmse"],
                        "final_smape": "" if final_horizon is None else final_horizon[horizon]["smape"],
                        "notes": result.weather_mode,
                    }
                )
            for fold in result.folds:
                fold_rows.append(
                    {
                        "experiment_id": result.experiment_id,
                        "algorithm": result.algorithm.value,
                        "weather_mode": result.weather_mode,
                        "quality_profile": result.quality_profile,
                        "fold": fold.fold_no,
                        "train_rows": fold.train_rows,
                        "validation_rows": fold.validation_rows,
                        "mae": fold.mae,
                        "rmse": fold.rmse,
                        "smape": fold.smape,
                        "train_seconds": fold.train_seconds,
                        "predict_ms_per_origin": fold.predict_ms_per_origin,
                        "parameters_json": json.dumps(result.parameters, sort_keys=True, default=_json_default),
                    }
                )

        _write_csv(
            output_dir / "final-results.csv",
            [
                "experiment_id",
                "algorithm",
                "weather_mode",
                "quality_profile",
                "feature_schema_version",
                "split_definition",
                "mean_cv_mae",
                "std_cv_mae",
                "final_mae",
                "final_rmse",
                "final_smape",
                "train_time_seconds",
                "prediction_median_ms",
                "prediction_p95_ms",
                "artifact_size_bytes",
                "recommended",
                "notes",
            ],
            final_rows,
        )
        _write_csv(
            output_dir / "horizon-results.csv",
            [
                "experiment_id",
                "algorithm",
                "horizon",
                "cv_mae",
                "final_mae",
                "final_rmse",
                "final_smape",
                "notes",
            ],
            horizon_rows,
        )
        _write_csv(
            output_dir / "fold-results.csv",
            [
                "experiment_id",
                "algorithm",
                "weather_mode",
                "quality_profile",
                "fold",
                "train_rows",
                "validation_rows",
                "mae",
                "rmse",
                "smape",
                "train_seconds",
                "predict_ms_per_origin",
                "parameters_json",
            ],
            fold_rows,
        )
        _write_csv(
            output_dir / "search-results.csv",
            [
                "experiment_id",
                "algorithm",
                "weather_mode",
                "candidate_no",
                "parameters_json",
                "mean_cv_mae",
                "std_cv_mae",
                "overall_cv_rmse",
                "overall_cv_smape",
            ],
            search_rows,
        )

        prediction_rows: list[dict[str, object]] = []
        for row_no, matrix_index in enumerate(final_indexes):
            origin = main_matrix.origins[int(matrix_index)]
            for horizon in range(24):
                prediction_rows.append(
                    {
                        "origin": origin.isoformat(),
                        "horizon": horizon + 1,
                        "target_time": (origin + timedelta(hours=horizon + 1)).isoformat(),
                        "actual_kwh": actual_final[row_no, horizon],
                        "seasonal_naive_24_kwh": baseline_predictions[row_no, horizon],
                        "selected_w0_kwh": selected_predictions[row_no, horizon],
                        "selected_w1_kwh": (
                            ""
                            if selected_w1_predictions is None
                            else selected_w1_predictions[row_no, horizon]
                        ),
                    }
                )
        _write_csv(
            output_dir / "final-predictions.csv",
            [
                "origin",
                "horizon",
                "target_time",
                "actual_kwh",
                "seasonal_naive_24_kwh",
                "selected_w0_kwh",
                "selected_w1_kwh",
            ],
            prediction_rows,
        )

        selected_horizon = _horizon_metrics(actual_final, selected_predictions)
        baseline_horizon = _horizon_metrics(actual_final, baseline_predictions)
        chart_series = [
            ("Selected W0", [row["mae"] for row in selected_horizon]),
            ("Seasonal Naive-24", [row["mae"] for row in baseline_horizon]),
        ]
        if selected_w1_predictions is not None:
            w1_horizon = _horizon_metrics(actual_final, selected_w1_predictions)
            chart_series.append(("Selected-family W1", [row["mae"] for row in w1_horizon]))
        _svg_line_chart(
            output_dir / "mae-by-horizon.svg",
            "Final-test MAE by forecast horizon",
            [float(value) for value in range(1, 25)],
            chart_series,
            y_label="MAE, kWh",
        )
        representative = 0
        _svg_line_chart(
            output_dir / "actual-vs-forecast.svg",
            f"Actual vs forecast at {main_matrix.origins[int(final_indexes[representative])].isoformat()}",
            [float(value) for value in range(1, 25)],
            [
                ("Actual", actual_final[representative].tolist()),
                ("Selected W0", selected_predictions[representative].tolist()),
                ("Seasonal Naive-24", baseline_predictions[representative].tolist()),
                *(
                    [("Selected-family W1", selected_w1_predictions[representative].tolist())]
                    if selected_w1_predictions is not None
                    else []
                ),
            ],
            y_label="Energy, kWh",
        )
        comparison_results = [
            best_w0[AlgorithmType.SEASONAL_NAIVE_24],
            best_w0[AlgorithmType.RIDGE],
            best_w0[AlgorithmType.RANDOM_FOREST],
            best_w0[AlgorithmType.HIST_GRADIENT_BOOSTING],
            best_w1[AlgorithmType.RIDGE],
            best_w1[AlgorithmType.RANDOM_FOREST],
            best_w1[AlgorithmType.HIST_GRADIENT_BOOSTING],
        ]
        _svg_bar_chart(
            output_dir / "cv-model-comparison.svg",
            "Chronological CV mean MAE",
            [result.experiment_id for result in comparison_results],
            [result.mean_cv_mae for result in comparison_results],
        )

        w1_delta = None
        if selected_w1_metrics is not None:
            w1_delta = selected_final_metrics.mae - selected_w1_metrics.mae
        h1_supported = bool(
            selected_w0.algorithm is not AlgorithmType.SEASONAL_NAIVE_24
            and selected_final_metrics.mae < baseline_final_metrics.mae
            and bootstrap["stable_improvement"]
        )
        run_manifest = {
            "schema": "energyforecast-point5-results/v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "release_candidate_sha": args.release_candidate_sha,
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "dataset": {
                "source_sha256": preparation["source_sha256"],
                "prepared_dataset_version_id": str(prepared_id),
                "hourly_rows": preparation["hourly_rows"],
                "quality_status_counts": preparation["quality_status_counts"],
            },
            "weather": {
                "provider": weather_metadata["provider"],
                "reanalysis_model": weather_metadata["reanalysis_model"],
                "csv_sha256": weather_metadata["csv_sha256"],
                "location": weather_metadata["requested_location"],
                "operational_forecast_claim": False,
            },
            "protocol": {
                "split_definition": SPLIT_DEFINITION_V1,
                "forecast_horizon_hours": 24,
                "random_seed": 42,
                "max_tree_candidates_per_algorithm": args.max_tree_candidates,
                "selection_file_sha256": selection_sha,
                "selection_persisted_before_final_test": True,
                "final_test_start": FINAL_TEST_START.isoformat(),
                "w1_semantics": "idealized future ERA5-Land reanalysis at t+h",
            },
            "selection": selection_payload,
            "final_test": {
                "origins": int(final_indexes.size),
                "selected_mae": selected_final_metrics.mae,
                "selected_rmse": selected_final_metrics.rmse,
                "selected_smape": selected_final_metrics.smape,
                "baseline_mae": baseline_final_metrics.mae,
                "improvement_percent_vs_seasonal_naive_24": improvement,
                "bootstrap": bootstrap,
                "h1_supported_for_preselected_w0_candidate": h1_supported,
            },
            "weather_ablation_final": (
                None
                if selected_w1_metrics is None
                else {
                    "algorithm_family": selected_w0.algorithm.value,
                    "w0_mae": selected_final_metrics.mae,
                    "w1_mae": selected_w1_metrics.mae,
                    "w0_minus_w1_mae": w1_delta,
                    "interpretation": "idealized upper-bound reanalysis ablation only",
                }
            ),
            "product_integration": forecast_payload,
            "environment": benchmark["machine"],
            "library_versions": benchmark["library_versions"],
        }
        _write_json(output_dir / "run-manifest.json", run_manifest)

        README = f"""# Point 5 — final ML study evidence

This directory is generated from the full external UCI *Individual Household Electric Power Consumption* source and the frozen EnergyForecast release candidate `{args.release_candidate_sha}`.

## Dataset and protocol

- UCI SHA-256: `{preparation['source_sha256']}`
- prepared hourly dataset version: `{prepared_id}`
- hourly rows: {preparation['hourly_rows']}
- feature schema: `{main_matrix.schema.version}` / `{main_matrix.schema.sha256}`
- split: `{SPLIT_DEFINITION_V1}` with four chronological 2009 validation folds and a 24-hour purge
- final test: 2010, opened only after `selection-decision.json` was fsync-persisted
- tree-model search: {args.max_tree_candidates} deterministic sampled configurations per tree family; Ridge uses its complete six-alpha grid

## Selected W0 model

The formal pre-test rule selected **{selected_w0.algorithm.value}** ({selected_w0.experiment_id}) with mean CV MAE **{selected_w0.mean_cv_mae:.6f} kWh** and CV standard deviation **{selected_w0.std_cv_mae:.6f} kWh**.

On the isolated 2010 final test ({final_indexes.size} eligible hourly origins):

- selected W0 MAE: **{selected_final_metrics.mae:.6f} kWh**
- selected W0 RMSE: **{selected_final_metrics.rmse:.6f} kWh**
- selected W0 sMAPE: **{selected_final_metrics.smape:.3f}%**
- Seasonal Naive-24 MAE: **{baseline_final_metrics.mae:.6f} kWh**
- MAE improvement relative to Seasonal Naive-24: **{improvement:.3f}%**
- paired 168-origin moving-block bootstrap 95% interval for `MAE_selected - MAE_baseline`: **[{bootstrap['ci95_lower']:.6f}, {bootstrap['ci95_upper']:.6f}] kWh**
- stable improvement under the predefined bootstrap rule: **{bootstrap['stable_improvement']}**

The working ML-superiority hypothesis is **{'supported for the preselected W0 candidate' if h1_supported else 'not supported for the preselected W0 candidate'}**. No model, feature, threshold, or hyperparameter was changed after the 2010 indexes were opened.

## Weather ablation

W1 uses ERA5-Land reanalysis from Open-Meteo at the GeoNames centre of Sceaux (`48.776442, 2.290258`). Exact household coordinates are not published by UCI. W1 supplies the reanalysis value at `t+h` to the horizon-`h` regressor, so it is an **idealized upper-bound experiment**, not an operational weather forecast.

{('For the selected W0 algorithm family, final W1 MAE is **%.6f kWh** versus W0 **%.6f kWh**.' % (selected_w1_metrics.mae, selected_final_metrics.mae)) if selected_w1_metrics is not None else 'The selected W0 model is a seasonal baseline, so no like-for-like W1 final model exists; E20-E22 CV results are still reported.'}

## Computational evidence

- median final training time after one warm-up: **{benchmark['training']['median_seconds']:.3f} s**
- 24-hour prediction median / p95 over 30 measured runs: **{benchmark['prediction']['median_ms']:.3f} / {benchmark['prediction']['p95_ms']:.3f} ms**
- serialized selected `joblib`: **{benchmark['serialized_joblib_bytes']} bytes**
- verified internal model bundle: `{bundle.artifact_id}` / `{bundle.bundle_sha256}`
- final product-path forecast contains exactly 24 ordered points and total energy `{forecast.total_energy_kwh:.6f} kWh`

## Files

- `point5-handoff.json` — bound UCI SHA/UUID handoff;
- `dataset-preparation.json` — import/transformation and quality counts;
- `selection-decision.json` — immutable pre-final-test recommendation;
- `search-results.csv`, `fold-results.csv` — tuning and chronological validation evidence;
- `final-results.csv`, `horizon-results.csv`, `final-predictions.csv` — machine-readable scientific results;
- `bootstrap.json` — paired moving-block uncertainty;
- `benchmark.json` — training/prediction/feature timing and sizes;
- `weather-metadata.json` — W1 source, coordinates and checksum;
- `product-forecast.json` — verified-bundle 24-hour final scenario;
- `actual-vs-forecast.svg`, `mae-by-horizon.svg`, `cv-model-comparison.svg` — report-ready graphics;
- `run-manifest.json` — top-level provenance and conclusions.

## Threats to validity

1. The UCI household timezone is not formally published; EnergyForecast uses the predefined `Europe/Paris` interpretation and records DST/duplicate effects through the quality pipeline.
2. Exact household coordinates are unavailable; W1 uses the documented Sceaux city-centre proxy.
3. ERA5-Land is reanalysis. Future `t+h` weather is therefore privileged information and cannot be presented as operational forecast accuracy.
4. This is a single household, so external validity to other buildings or grids is limited.
5. Forecast origins overlap. The uncertainty analysis therefore resamples consecutive 168-origin blocks instead of treating hourly errors as independent.
6. Runtime measurements describe the recorded GitHub Actions runner and pinned single-thread scientific profile; they are not universal hardware benchmarks.
7. Tree-model search is deliberately bounded for CPU-only reproducibility; the exact sampled configurations are preserved in `search-results.csv`.
"""
        (output_dir / "README.md").write_text(README, encoding="utf-8")
        return run_manifest
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--preparation-json", type=Path, required=True)
    parser.add_argument("--handoff-json", type=Path, required=True)
    parser.add_argument("--weather-csv", type=Path, required=True)
    parser.add_argument("--weather-metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-candidate-sha", required=True)
    parser.add_argument("--max-tree-candidates", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.max_tree_candidates <= 20:
        raise SystemExit("--max-tree-candidates must be between 1 and 20")
    result = asyncio.run(_run(args))
    print(json.dumps(result, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
