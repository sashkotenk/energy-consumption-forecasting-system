"""Pure deterministic recommendation rule applied before final-test access."""

from __future__ import annotations

from dataclasses import dataclass

from energy_forecast.ml.registry import AlgorithmType

_SIMPLICITY = {
    AlgorithmType.SEASONAL_NAIVE_24: 0,
    AlgorithmType.SEASONAL_NAIVE_168: 1,
    AlgorithmType.RIDGE: 2,
    AlgorithmType.HIST_GRADIENT_BOOSTING: 3,
    AlgorithmType.RANDOM_FOREST: 4,
}


@dataclass(frozen=True, slots=True)
class SelectionCandidate:
    algorithm: AlgorithmType
    model_run_id: object
    mean_cv_mae: float
    std_cv_mae: float
    predict_ms_median: float


def select_recommended(candidates: tuple[SelectionCandidate, ...]) -> SelectionCandidate:
    """Apply 1% MAE, 5% standard-deviation, time, then simplicity tie-breaks."""
    if not candidates:
        raise ValueError("at least one successful candidate is required")
    if any(
        value < 0
        for candidate in candidates
        for value in (candidate.mean_cv_mae, candidate.std_cv_mae, candidate.predict_ms_median)
    ):
        raise ValueError("selection metrics must be non-negative")
    best_mae = min(candidate.mean_cv_mae for candidate in candidates)
    mae_pool = tuple(
        candidate for candidate in candidates if candidate.mean_cv_mae <= best_mae * 1.01
    )
    best_std = min(candidate.std_cv_mae for candidate in mae_pool)
    std_pool = tuple(candidate for candidate in mae_pool if candidate.std_cv_mae <= best_std * 1.05)
    return min(
        std_pool,
        key=lambda candidate: (
            candidate.predict_ms_median,
            _SIMPLICITY[candidate.algorithm],
            candidate.algorithm.value,
        ),
    )
