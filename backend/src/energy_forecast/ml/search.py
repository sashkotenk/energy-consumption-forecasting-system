"""Bounded and reproducible parameter candidates for model selection."""

from __future__ import annotations

from typing import Any

from sklearn.model_selection import ParameterGrid, ParameterSampler

from energy_forecast.ml.registry import AlgorithmRegistry, AlgorithmType

MAX_RANDOM_CANDIDATES = 20


def candidate_configurations(
    algorithm: AlgorithmType,
    *,
    random_seed: int = 42,
    max_candidates: int = MAX_RANDOM_CANDIDATES,
) -> tuple[dict[str, Any], ...]:
    if not 1 <= max_candidates <= MAX_RANDOM_CANDIDATES:
        raise ValueError("max_candidates must be between 1 and 20")
    descriptor = AlgorithmRegistry().get(algorithm)
    search_space = dict(descriptor.default_search_space)
    if not search_space:
        return ({},)
    if algorithm is AlgorithmType.RIDGE:
        candidates = list(ParameterGrid(search_space))
    else:
        total = 1
        for values in search_space.values():
            total *= len(values)
        candidates = list(
            ParameterSampler(
                search_space,
                n_iter=min(max_candidates, total),
                random_state=random_seed,
            )
        )
    return tuple(dict(candidate) for candidate in candidates)
