"""Chronological evaluation protocol with purge and train-only preprocessing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Protocol, Self

import numpy as np
from numpy.typing import NDArray

SPLIT_DEFINITION_V1 = "uci_2009_quarters_2010_test_v1"
FORECAST_HORIZON = timedelta(hours=24)
FINAL_TEST_START = datetime(2010, 1, 1, tzinfo=UTC)

VALIDATION_PERIODS = (
    (datetime(2009, 1, 1, tzinfo=UTC), datetime(2009, 4, 1, tzinfo=UTC)),
    (datetime(2009, 4, 1, tzinfo=UTC), datetime(2009, 7, 1, tzinfo=UTC)),
    (datetime(2009, 7, 1, tzinfo=UTC), datetime(2009, 10, 1, tzinfo=UTC)),
    (datetime(2009, 10, 1, tzinfo=UTC), FINAL_TEST_START),
)


@dataclass(frozen=True, slots=True)
class TemporalFold:
    fold_no: int
    train_indices: NDArray[np.int64]
    validation_indices: NDArray[np.int64]
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime


@dataclass(frozen=True, slots=True)
class FoldData:
    fold: TemporalFold
    train_features: NDArray[np.float64]
    train_targets: NDArray[np.float64]
    validation_features: NDArray[np.float64]
    validation_targets: NDArray[np.float64]
    transformer: TrainFittableTransformer


class TrainFittableTransformer(Protocol):
    def fit(self, values: NDArray[np.float64]) -> Self: ...

    def transform(self, values: NDArray[np.float64]) -> NDArray[np.float64]: ...


class ChronologicalSplitProtocol:
    """Expose CV and final-test indexes through deliberately separate methods."""

    definition = SPLIT_DEFINITION_V1

    def cross_validation_folds(self, origins: tuple[datetime, ...]) -> tuple[TemporalFold, ...]:
        normalized = _normalized_origins(origins)
        folds: list[TemporalFold] = []
        for fold_no, (validation_start, validation_end) in enumerate(VALIDATION_PERIODS, start=1):
            train_indices = np.asarray(
                [
                    index
                    for index, origin in enumerate(normalized)
                    if origin + FORECAST_HORIZON < validation_start
                ],
                dtype=np.int64,
            )
            validation_indices = np.asarray(
                [
                    index
                    for index, origin in enumerate(normalized)
                    if validation_start <= origin < validation_end
                ],
                dtype=np.int64,
            )
            if train_indices.size == 0 or validation_indices.size == 0:
                raise ValueError(f"fold {fold_no} has no eligible train or validation origins")
            folds.append(
                TemporalFold(
                    fold_no=fold_no,
                    train_indices=train_indices,
                    validation_indices=validation_indices,
                    train_start=normalized[int(train_indices[0])],
                    train_end=normalized[int(train_indices[-1])],
                    validation_start=validation_start,
                    validation_end=validation_end,
                )
            )
        return tuple(folds)

    def final_test_indices(self, origins: tuple[datetime, ...]) -> NDArray[np.int64]:
        normalized = _normalized_origins(origins)
        return np.asarray(
            [index for index, origin in enumerate(normalized) if origin >= FINAL_TEST_START],
            dtype=np.int64,
        )


def prepare_fold(
    features: NDArray[np.float64],
    targets: NDArray[np.float64],
    fold: TemporalFold,
    transformer_factory: Callable[[], TrainFittableTransformer],
) -> FoldData:
    """Fit a fresh transformer on a fold's training rows and transform both partitions."""
    if features.ndim != 2 or targets.ndim != 2 or features.shape[0] != targets.shape[0]:
        raise ValueError("features and targets must be aligned two-dimensional matrices")
    transformer = transformer_factory()
    train_features = np.asarray(features[fold.train_indices], dtype=np.float64)
    validation_features = np.asarray(features[fold.validation_indices], dtype=np.float64)
    transformer.fit(train_features)
    return FoldData(
        fold=fold,
        train_features=np.asarray(transformer.transform(train_features), dtype=np.float64),
        train_targets=np.asarray(targets[fold.train_indices], dtype=np.float64),
        validation_features=np.asarray(
            transformer.transform(validation_features), dtype=np.float64
        ),
        validation_targets=np.asarray(targets[fold.validation_indices], dtype=np.float64),
        transformer=transformer,
    )


def _normalized_origins(origins: tuple[datetime, ...]) -> tuple[datetime, ...]:
    if not origins:
        raise ValueError("origins cannot be empty")
    if any(origin.tzinfo is None for origin in origins):
        raise ValueError("origins must be timezone-aware")
    normalized = tuple(origin.astimezone(UTC) for origin in origins)
    if any(left >= right for left, right in pairwise(normalized)):
        raise ValueError("origins must be strictly increasing and unique")
    return normalized
