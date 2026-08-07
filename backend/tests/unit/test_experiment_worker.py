from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import numpy as np
import pandas as pd

from energy_forecast.experiments.handler import ExperimentHandler
from energy_forecast.experiments.models import (
    ExperimentWork,
    SensitivityMode,
    WeatherMode,
)
from energy_forecast.experiments.ports import ExperimentRepository
from energy_forecast.jobs.worker import JobExecutionContext
from energy_forecast.ml.bundles import ModelBundleService
from energy_forecast.ml.registry import AlgorithmType


@dataclass
class _BundleResult:
    artifact_id: UUID
    size_bytes: int


class _Bundles:
    async def save(self, model: object, details: object) -> _BundleResult:
        return _BundleResult(uuid4(), 512)


class _Context:
    def __init__(self, job_id: UUID, experiment_id: UUID) -> None:
        self.job_id = job_id
        self.payload = {"experiment_id": str(experiment_id)}
        self.progress: list[int] = []

    def raise_if_cancel_requested(self) -> None:
        return None

    async def report_progress(self, progress_pct: int) -> None:
        self.progress.append(progress_pct)


class _Repository:
    def __init__(
        self, work: ExperimentWork, hourly: pd.DataFrame, *, reject_run_id: UUID | None = None
    ) -> None:
        self.work = work
        self.hourly = hourly
        self.fold_count = 0
        self.cv_horizon_count = 0
        self.final_horizon_count = 0
        self.final_opened = False
        self.completed_manifest: dict[str, Any] | None = None
        self.failed = False
        self.rejected_run_id = reject_run_id
        self.failed_model_ids: list[UUID] = []

    async def prepare(self, experiment_id: UUID, job_id: UUID) -> ExperimentWork:
        assert experiment_id == self.work.experiment_id
        assert job_id == self.work.job_id
        return self.work

    async def load_hourly(self, dataset_version_id: UUID) -> pd.DataFrame:
        assert dataset_version_id == self.work.dataset_version_id
        return self.hourly

    async def save_cv_result(self, **values: Any) -> None:
        if values["model_run_id"] == self.rejected_run_id:
            raise RuntimeError("synthetic candidate failure")
        self.fold_count = len(values["folds"])
        self.cv_horizon_count = len(values["horizons"])

    async def fail_model(self, model_run_id: UUID, *, code: str, detail: str) -> None:
        self.failed_model_ids.append(model_run_id)

    async def open_final_test(self, experiment_id: UUID, model_run_id: UUID) -> None:
        assert self.fold_count == 4
        self.final_opened = True

    async def save_final_result(self, **values: Any) -> None:
        assert self.final_opened
        self.final_horizon_count = len(values["horizons"])

    async def complete(self, experiment_id: UUID, manifest: dict[str, Any]) -> None:
        assert self.final_horizon_count == 24
        self.completed_manifest = manifest

    async def fail_experiment(
        self, experiment_id: UUID, *, cancelled: bool, code: str, detail: str
    ) -> None:
        self.failed = True


def test_small_worker_experiment_persists_four_folds_horizons_and_manifest() -> None:
    asyncio.run(_run_small_worker_experiment())


async def _run_small_worker_experiment() -> None:
    experiment_id, job_id, version_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    work = ExperimentWork(
        experiment_id=experiment_id,
        job_id=job_id,
        dataset_version_id=version_id,
        algorithms=(AlgorithmType.SEASONAL_NAIVE_24,),
        model_run_ids={AlgorithmType.SEASONAL_NAIVE_24: run_id},
        weather_mode=WeatherMode.WITHOUT_WEATHER,
        sensitivity_mode=SensitivityMode.COMPLETE_ONLY,
        timezone="UTC",
        code_commit="abcdef1",
    )
    hourly = _hourly_fixture()
    repository = _Repository(work, hourly)
    context = _Context(job_id, experiment_id)
    handler = ExperimentHandler(
        cast(ExperimentRepository, repository),
        cast(ModelBundleService, _Bundles()),
    )

    result = await handler(cast(JobExecutionContext, context))

    assert repository.failed is False
    assert repository.fold_count == 4
    assert repository.cv_horizon_count == 24
    assert repository.final_horizon_count == 24
    assert repository.completed_manifest == result
    assert result["recommended_algorithm"] == "seasonal_naive_24"
    assert context.progress[-1] == 100


def test_failed_model_does_not_remove_successful_run_or_block_completion() -> None:
    asyncio.run(_run_partial_failure_experiment())


async def _run_partial_failure_experiment() -> None:
    experiment_id, job_id, version_id = uuid4(), uuid4(), uuid4()
    failed_run, successful_run = uuid4(), uuid4()
    work = ExperimentWork(
        experiment_id=experiment_id,
        job_id=job_id,
        dataset_version_id=version_id,
        algorithms=(
            AlgorithmType.SEASONAL_NAIVE_24,
            AlgorithmType.SEASONAL_NAIVE_168,
        ),
        model_run_ids={
            AlgorithmType.SEASONAL_NAIVE_24: failed_run,
            AlgorithmType.SEASONAL_NAIVE_168: successful_run,
        },
        weather_mode=WeatherMode.WITHOUT_WEATHER,
        sensitivity_mode=SensitivityMode.COMPLETE_ONLY,
        timezone="UTC",
        code_commit="abcdef1",
    )
    repository = _Repository(work, _hourly_fixture(), reject_run_id=failed_run)
    handler = ExperimentHandler(
        cast(ExperimentRepository, repository),
        cast(ModelBundleService, _Bundles()),
    )

    result = await handler(cast(JobExecutionContext, _Context(job_id, experiment_id)))

    assert repository.failed_model_ids == [failed_run]
    assert repository.completed_manifest == result
    assert result["recommended_algorithm"] == "seasonal_naive_168"


def _hourly_fixture() -> pd.DataFrame:
    index = pd.date_range("2008-01-01", "2010-02-01", freq="h", tz="UTC")
    energy = 1.0 + np.asarray(index.hour, dtype=np.float64)
    return pd.DataFrame(
        {
            "energy_kwh": energy,
            "coverage_ratio": np.ones(len(index)),
            "quality_status": ["complete"] * len(index),
        },
        index=index,
    )
