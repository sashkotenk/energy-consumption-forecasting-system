"""Persistence boundary used by the experiment API and worker."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

import pandas as pd

from energy_forecast.experiments.models import (
    ExperimentDefinition,
    ExperimentPage,
    ExperimentRecord,
    ExperimentWork,
    StagedExperiment,
)
from energy_forecast.ml.metrics import MetricSet
from energy_forecast.ml.splits import TemporalFold


class ExperimentRepository(Protocol):
    async def stage(
        self, definition: ExperimentDefinition, *, code_commit: str
    ) -> StagedExperiment: ...

    async def list(self, *, page: int, page_size: int) -> ExperimentPage: ...

    async def get(self, experiment_id: UUID) -> ExperimentRecord: ...

    async def comparison(self, experiment_id: UUID) -> tuple[dict[str, Any], ...]: ...

    async def mark_cancelling(self, experiment_id: UUID) -> UUID: ...

    async def prepare(self, experiment_id: UUID, job_id: UUID) -> ExperimentWork: ...

    async def load_hourly(self, dataset_version_id: UUID) -> pd.DataFrame: ...

    async def save_cv_result(
        self,
        *,
        model_run_id: UUID,
        hyperparameters: dict[str, Any],
        folds: tuple[tuple[TemporalFold, MetricSet, float], ...],
        horizons: tuple[tuple[int, float, float, float], ...],
        mean_cv_mae: float,
        std_cv_mae: float,
        predict_ms_median: float,
    ) -> None: ...

    async def fail_model(self, model_run_id: UUID, *, code: str, detail: str) -> None: ...

    async def open_final_test(self, experiment_id: UUID, model_run_id: UUID) -> None: ...

    async def save_final_result(
        self,
        *,
        model_run_id: UUID,
        metrics: MetricSet,
        horizons: tuple[tuple[int, float, float, float], ...],
        artifact_id: UUID,
        artifact_size_bytes: int,
    ) -> None: ...

    async def complete(self, experiment_id: UUID, manifest: dict[str, Any]) -> None: ...

    async def fail_experiment(
        self, experiment_id: UUID, *, cancelled: bool, code: str, detail: str
    ) -> None: ...
