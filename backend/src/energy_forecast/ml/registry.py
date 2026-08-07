"""Supported forecasting algorithm descriptors and bounded search spaces."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class AlgorithmType(StrEnum):
    SEASONAL_NAIVE_24 = "seasonal_naive_24"
    SEASONAL_NAIVE_168 = "seasonal_naive_168"
    RIDGE = "ridge"
    RANDOM_FOREST = "random_forest"
    HIST_GRADIENT_BOOSTING = "hist_gradient_boosting"


@dataclass(frozen=True, slots=True)
class AlgorithmDescriptor:
    algorithm: AlgorithmType
    display_name: str
    implementation_version: str
    supports_weather: bool
    default_search_space: Mapping[str, tuple[Any, ...]]


class AlgorithmRegistry:
    def __init__(self, descriptors: tuple[AlgorithmDescriptor, ...] | None = None) -> None:
        configured = descriptors or _default_descriptors()
        by_type = {descriptor.algorithm: descriptor for descriptor in configured}
        if len(by_type) != len(configured):
            raise ValueError("algorithm registry cannot contain duplicate types")
        self._descriptors = tuple(configured)
        self._by_type = MappingProxyType(by_type)

    def list(self) -> tuple[AlgorithmDescriptor, ...]:
        return self._descriptors

    def get(self, algorithm: AlgorithmType | str) -> AlgorithmDescriptor:
        try:
            normalized = AlgorithmType(algorithm)
            return self._by_type[normalized]
        except (KeyError, ValueError) as error:
            raise UnknownAlgorithmError(f"Unsupported algorithm: {algorithm}") from error


class UnknownAlgorithmError(ValueError):
    """Raised when an experiment requests an unregistered algorithm."""


def _default_descriptors() -> tuple[AlgorithmDescriptor, ...]:
    return (
        _descriptor(AlgorithmType.SEASONAL_NAIVE_24, "Seasonal Naive (24 h)", {}),
        _descriptor(AlgorithmType.SEASONAL_NAIVE_168, "Seasonal Naive (168 h)", {}),
        _descriptor(
            AlgorithmType.RIDGE,
            "Ridge",
            {"alpha": (0.01, 0.1, 1.0, 10.0, 100.0, 1000.0)},
        ),
        _descriptor(
            AlgorithmType.RANDOM_FOREST,
            "Random Forest",
            {
                "n_estimators": (300, 600),
                "max_depth": (12, 24, None),
                "min_samples_leaf": (1, 3, 6),
                "max_features": ("sqrt", 0.7),
                "max_samples": (None, 0.8),
                "bootstrap": (True,),
                "random_state": (42,),
            },
        ),
        _descriptor(
            AlgorithmType.HIST_GRADIENT_BOOSTING,
            "Histogram Gradient Boosting",
            {
                "learning_rate": (0.03, 0.05, 0.1),
                "max_iter": (200, 400),
                "max_leaf_nodes": (15, 31, 63),
                "min_samples_leaf": (20, 50, 100),
                "l2_regularization": (0.0, 0.1, 1.0),
                "loss": ("squared_error",),
                "early_stopping": (False,),
                "random_state": (42,),
            },
        ),
    )


def _descriptor(
    algorithm: AlgorithmType,
    display_name: str,
    search_space: dict[str, tuple[Any, ...]],
) -> AlgorithmDescriptor:
    return AlgorithmDescriptor(
        algorithm=algorithm,
        display_name=display_name,
        implementation_version="v1",
        supports_weather=algorithm
        not in {AlgorithmType.SEASONAL_NAIVE_24, AlgorithmType.SEASONAL_NAIVE_168},
        default_search_space=MappingProxyType(search_space),
    )
