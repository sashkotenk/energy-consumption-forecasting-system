"""Framework-independent ports shared by forecasting algorithms."""

from __future__ import annotations

from typing import Protocol, Self

import numpy as np
from numpy.typing import NDArray


class Predictor(Protocol):
    def predict(self, features: NDArray[np.float64]) -> NDArray[np.float64]: ...


class Trainer(Protocol):
    def fit(
        self,
        features: NDArray[np.float64],
        targets: NDArray[np.float64],
    ) -> Self: ...

    def predict(self, features: NDArray[np.float64]) -> NDArray[np.float64]: ...
