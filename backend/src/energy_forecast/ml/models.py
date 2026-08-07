"""Direct 24-regressor implementations for the required ML algorithms."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

import numpy as np
from joblib import Parallel, delayed
from numpy.typing import NDArray
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from energy_forecast.ml.registry import AlgorithmRegistry, AlgorithmType

FORECAST_HORIZON = 24


class ExecutionProfile(StrEnum):
    BENCHMARK = "benchmark"
    PRODUCTION = "production"


@dataclass(frozen=True, slots=True)
class ModelRuntime:
    profile: ExecutionProfile = ExecutionProfile.BENCHMARK
    random_seed: int = 42
    production_n_jobs: int = -1

    def __post_init__(self) -> None:
        if self.production_n_jobs == 0:
            raise ValueError("production_n_jobs cannot be zero")

    @property
    def n_jobs(self) -> int:
        return 1 if self.profile is ExecutionProfile.BENCHMARK else self.production_n_jobs


class DirectRegressionModel:
    """Fit one independent estimator for every forecast horizon."""

    def __init__(
        self,
        algorithm: AlgorithmType,
        parameters: dict[str, Any],
        runtime: ModelRuntime,
    ) -> None:
        if algorithm not in {
            AlgorithmType.RIDGE,
            AlgorithmType.RANDOM_FOREST,
            AlgorithmType.HIST_GRADIENT_BOOSTING,
        }:
            raise ValueError(f"algorithm does not use direct regressors: {algorithm}")
        self.algorithm = algorithm
        self.parameters = _validated_parameters(algorithm, parameters, runtime)
        self.runtime = runtime
        self.scaler: StandardScaler | None = None
        self.estimators: list[Any] = []

    def fit(
        self,
        features: NDArray[np.float64],
        targets: NDArray[np.float64],
    ) -> Self:
        feature_values, target_values = _validated_training_data(features, targets)
        if self.algorithm is AlgorithmType.RIDGE:
            self.scaler = StandardScaler().fit(feature_values)
            model_features = np.asarray(self.scaler.transform(feature_values), dtype=np.float64)
        else:
            self.scaler = None
            model_features = feature_values

        context = (
            threadpool_limits(limits=1)
            if self.runtime.profile is ExecutionProfile.BENCHMARK
            else nullcontext()
        )
        with context:
            if self.runtime.n_jobs == 1:
                estimators = [
                    _fit_estimator(
                        self.algorithm,
                        self.parameters,
                        self.runtime.random_seed,
                        model_features,
                        target_values[:, horizon],
                    )
                    for horizon in range(FORECAST_HORIZON)
                ]
            else:
                estimators = Parallel(n_jobs=self.runtime.n_jobs)(
                    delayed(_fit_estimator)(
                        self.algorithm,
                        self.parameters,
                        self.runtime.random_seed,
                        model_features,
                        target_values[:, horizon],
                    )
                    for horizon in range(FORECAST_HORIZON)
                )
        self.estimators = list(estimators)
        return self

    def predict(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        if len(self.estimators) != FORECAST_HORIZON:
            raise ModelNotFittedError("direct model must be fitted before prediction")
        feature_values = _validated_features(features)
        if self.scaler is not None:
            feature_values = np.asarray(self.scaler.transform(feature_values), dtype=np.float64)
        context = (
            threadpool_limits(limits=1)
            if self.runtime.profile is ExecutionProfile.BENCHMARK
            else nullcontext()
        )
        with context:
            if self.runtime.n_jobs == 1:
                predictions = [estimator.predict(feature_values) for estimator in self.estimators]
            else:
                predictions = Parallel(n_jobs=self.runtime.n_jobs)(
                    delayed(_predict_estimator)(estimator, feature_values)
                    for estimator in self.estimators
                )
        return np.asarray(np.column_stack(predictions), dtype=np.float64)


class ModelNotFittedError(RuntimeError):
    """Raised when prediction is attempted before all 24 estimators exist."""


def create_model(
    algorithm: AlgorithmType,
    *,
    parameters: dict[str, Any] | None = None,
    runtime: ModelRuntime | None = None,
) -> DirectRegressionModel:
    configured_runtime = runtime or ModelRuntime()
    configured_parameters = _default_parameters(algorithm, configured_runtime.random_seed)
    if parameters:
        configured_parameters.update(parameters)
    return DirectRegressionModel(algorithm, configured_parameters, configured_runtime)


def _default_parameters(algorithm: AlgorithmType, random_seed: int) -> dict[str, Any]:
    if algorithm is AlgorithmType.RIDGE:
        return {"alpha": 1.0}
    if algorithm is AlgorithmType.RANDOM_FOREST:
        return {
            "n_estimators": 300,
            "max_depth": 12,
            "min_samples_leaf": 1,
            "max_features": "sqrt",
            "max_samples": None,
            "bootstrap": True,
            "random_state": random_seed,
        }
    if algorithm is AlgorithmType.HIST_GRADIENT_BOOSTING:
        return {
            "learning_rate": 0.05,
            "max_iter": 200,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 20,
            "l2_regularization": 0.0,
            "loss": "squared_error",
            "early_stopping": False,
            "random_state": random_seed,
        }
    raise ValueError(f"algorithm does not use direct regressors: {algorithm}")


def _validated_parameters(
    algorithm: AlgorithmType,
    parameters: dict[str, Any],
    runtime: ModelRuntime,
) -> dict[str, Any]:
    descriptor = AlgorithmRegistry().get(algorithm)
    expected = set(descriptor.default_search_space)
    if set(parameters) != expected:
        raise ValueError(
            f"parameters for {algorithm} must be exactly: {', '.join(sorted(expected))}"
        )
    if parameters.get("early_stopping") is not None and parameters["early_stopping"] is not False:
        raise ValueError("random internal early stopping is forbidden")
    for name, value in parameters.items():
        if name == "random_state":
            if value != runtime.random_seed:
                raise ValueError("random_state must match the configured runtime seed")
            continue
        if value not in descriptor.default_search_space[name]:
            raise ValueError(f"unsupported {algorithm} parameter {name}={value!r}")
    return dict(parameters)


def _fit_estimator(
    algorithm: AlgorithmType,
    parameters: dict[str, Any],
    random_seed: int,
    features: NDArray[np.float64],
    target: NDArray[np.float64],
) -> Any:
    configured = dict(parameters)
    if algorithm is AlgorithmType.RIDGE:
        estimator = Ridge(**configured)
    elif algorithm is AlgorithmType.RANDOM_FOREST:
        configured["random_state"] = random_seed
        estimator = RandomForestRegressor(**configured, n_jobs=1)
    else:
        configured["random_state"] = random_seed
        configured["early_stopping"] = False
        estimator = HistGradientBoostingRegressor(**configured)
    return estimator.fit(features, target)


def _predict_estimator(estimator: Any, features: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.asarray(estimator.predict(features), dtype=np.float64)


def _validated_training_data(
    features: NDArray[np.float64], targets: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    feature_values = _validated_features(features)
    target_values = np.asarray(targets, dtype=np.float64)
    if target_values.ndim != 2 or target_values.shape != (feature_values.shape[0], 24):
        raise ValueError("targets must have shape (n_origins, 24)")
    if not np.isfinite(target_values).all():
        raise ValueError("targets must contain only finite values")
    return feature_values, target_values


def _validated_features(features: NDArray[np.float64]) -> NDArray[np.float64]:
    values = np.asarray(features, dtype=np.float64)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError("features must be a non-empty two-dimensional matrix")
    if not np.isfinite(values).all():
        raise ValueError("features must contain only finite values")
    return values
