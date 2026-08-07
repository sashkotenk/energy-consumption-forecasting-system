from __future__ import annotations

import io

import joblib
import numpy as np
import pytest

from energy_forecast.ml.benchmark import benchmark_model
from energy_forecast.ml.metrics import evaluate
from energy_forecast.ml.models import ExecutionProfile, ModelRuntime, create_model
from energy_forecast.ml.registry import AlgorithmType
from energy_forecast.ml.search import MAX_RANDOM_CANDIDATES, candidate_configurations


@pytest.mark.parametrize(
    ("algorithm", "mae_tolerance"),
    [
        (AlgorithmType.RIDGE, 0.1),
        (AlgorithmType.RANDOM_FOREST, 1.5),
        (AlgorithmType.HIST_GRADIENT_BOOSTING, 2.5),
    ],
)
def test_required_models_fit_direct_24_outputs_on_synthetic_regression(
    algorithm: AlgorithmType,
    mae_tolerance: float,
) -> None:
    features, targets = _regression_fixture()
    model = create_model(algorithm)

    predictions = model.fit(features, targets).predict(features)

    assert predictions.shape == (features.shape[0], 24)
    assert np.isfinite(predictions).all()
    assert evaluate(targets, predictions).mae < mae_tolerance
    assert len(model.estimators) == 24


def test_ridge_scaler_is_fitted_only_from_explicit_fold_training_rows() -> None:
    features, targets = _regression_fixture()
    train_features = features[:64]
    validation_features = features[64:]

    model = create_model(AlgorithmType.RIDGE).fit(train_features, targets[:64])

    assert model.scaler is not None
    assert model.scaler.mean_ == pytest.approx(train_features.mean(axis=0))
    assert model.scaler.mean_ != pytest.approx(
        np.concatenate((train_features, validation_features)).mean(axis=0)
    )
    assert model.predict(validation_features).shape == (32, 24)


def test_tree_models_disable_nested_or_random_internal_parallel_validation() -> None:
    features, targets = _regression_fixture()

    forest = create_model(AlgorithmType.RANDOM_FOREST).fit(features, targets)
    boosting = create_model(AlgorithmType.HIST_GRADIENT_BOOSTING).fit(features, targets)

    assert all(estimator.n_jobs == 1 for estimator in forest.estimators)
    assert all(estimator.early_stopping is False for estimator in boosting.estimators)


def test_seed_42_reproduces_random_forest_predictions() -> None:
    features, targets = _regression_fixture()

    first = create_model(AlgorithmType.RANDOM_FOREST).fit(features, targets)
    second = create_model(AlgorithmType.RANDOM_FOREST).fit(features, targets)

    assert first.predict(features[:8]) == pytest.approx(second.predict(features[:8]))


def test_parameter_candidates_are_bounded_and_reproducible() -> None:
    first = candidate_configurations(AlgorithmType.RANDOM_FOREST)
    second = candidate_configurations(AlgorithmType.RANDOM_FOREST)
    boosting = candidate_configurations(AlgorithmType.HIST_GRADIENT_BOOSTING)

    assert first == second
    assert len(first) == len(boosting) == MAX_RANDOM_CANDIDATES
    assert all(candidate["random_state"] == 42 for candidate in (*first, *boosting))
    assert len(candidate_configurations(AlgorithmType.RIDGE)) == 6


def test_model_parameters_cannot_escape_protocol_bounds() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        create_model(AlgorithmType.RIDGE, parameters={"alpha": 0.5})
    with pytest.raises(ValueError, match="early stopping"):
        create_model(
            AlgorithmType.HIST_GRADIENT_BOOSTING,
            parameters={"early_stopping": True},
        )


def test_execution_profiles_separate_benchmark_and_production_parallelism() -> None:
    benchmark = ModelRuntime(profile=ExecutionProfile.BENCHMARK, production_n_jobs=8)
    production = ModelRuntime(profile=ExecutionProfile.PRODUCTION, production_n_jobs=4)

    assert benchmark.n_jobs == 1
    assert production.n_jobs == 4


def test_direct_model_joblib_round_trip_preserves_predictions() -> None:
    features, targets = _regression_fixture()
    model = create_model(AlgorithmType.RIDGE).fit(features, targets)
    expected = model.predict(features[:5])
    artifact = io.BytesIO()

    joblib.dump(model, artifact)
    artifact.seek(0)
    restored = joblib.load(artifact)

    assert restored.predict(features[:5]) == pytest.approx(expected)


def test_benchmark_measures_training_prediction_and_artifact_size() -> None:
    features, targets = _regression_fixture()

    result = benchmark_model(
        lambda: create_model(AlgorithmType.RIDGE),
        features,
        targets,
        features[:1],
    )

    assert result.training_repetitions == 3
    assert result.prediction_repetitions == 30
    assert result.train_seconds_median > 0
    assert result.prediction_ms_median > 0
    assert result.prediction_ms_p95 >= result.prediction_ms_median
    assert result.artifact_size_bytes > 0
    assert result.model.predict(features[:1]).shape == (1, 24)


def _regression_fixture() -> tuple[np.ndarray, np.ndarray]:
    random = np.random.default_rng(42)
    features = random.normal(size=(96, 5))
    coefficients = random.normal(scale=0.4, size=(5, 24))
    horizons = np.arange(1, 25, dtype=np.float64) * 0.05
    targets = 5.0 + features @ coefficients + horizons
    return np.asarray(features, dtype=np.float64), np.asarray(targets, dtype=np.float64)
