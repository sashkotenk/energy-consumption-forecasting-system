from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from energy_forecast.experiments.models import ExperimentDefinition
from energy_forecast.experiments.selection import SelectionCandidate, select_recommended
from energy_forecast.ml.registry import AlgorithmType


def _candidate(
    algorithm: AlgorithmType, mae: float, std: float, prediction_ms: float
) -> SelectionCandidate:
    return SelectionCandidate(algorithm, uuid4(), mae, std, prediction_ms)


def test_selection_includes_exact_one_percent_mae_boundary() -> None:
    best = _candidate(AlgorithmType.RANDOM_FOREST, 100.0, 10.0, 5.0)
    boundary = _candidate(AlgorithmType.RIDGE, 101.0, 9.0, 1.0)

    assert select_recommended((best, boundary)) is boundary


def test_selection_excludes_candidate_beyond_one_percent_mae_boundary() -> None:
    best = _candidate(AlgorithmType.RANDOM_FOREST, 100.0, 10.0, 5.0)
    outside = _candidate(AlgorithmType.RIDGE, 101.0001, 1.0, 0.1)

    assert select_recommended((best, outside)) is best


def test_selection_includes_exact_five_percent_std_boundary_then_uses_time() -> None:
    lowest_std = _candidate(AlgorithmType.RANDOM_FOREST, 100.0, 10.0, 9.0)
    boundary = _candidate(AlgorithmType.RIDGE, 100.5, 10.5, 1.0)

    assert select_recommended((lowest_std, boundary)) is boundary


def test_selection_uses_simplicity_for_an_exact_tie() -> None:
    forest = _candidate(AlgorithmType.RANDOM_FOREST, 10.0, 1.0, 2.0)
    ridge = _candidate(AlgorithmType.RIDGE, 10.0, 1.0, 2.0)

    assert select_recommended((forest, ridge)) is ridge


def test_selection_keeps_a_tied_seasonal_baseline_as_the_simplest_model() -> None:
    baseline = _candidate(AlgorithmType.SEASONAL_NAIVE_24, 10.0, 1.0, 2.0)
    ridge = _candidate(AlgorithmType.RIDGE, 10.0, 1.0, 2.0)

    assert select_recommended((ridge, baseline)) is baseline


def test_experiment_definition_is_immutable_after_creation() -> None:
    definition = ExperimentDefinition(
        dataset_version_id=uuid4(),
        name="Course comparison",
        algorithms=(AlgorithmType.RIDGE,),
    )

    with pytest.raises(FrozenInstanceError):
        definition.name = "changed"  # type: ignore[misc]
