"""Transactional persistence for experiment configuration and results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import delete, func, select, update

from energy_forecast.database.models import (
    DatasetVersion,
    Experiment,
    FoldMetric,
    HorizonMetric,
    HourlyObservation,
    Job,
    ModelRun,
)
from energy_forecast.database.session import AsyncSessionFactory, transactional_session
from energy_forecast.experiments.models import (
    SELECTION_RULE_V1,
    DatasetVersionNotTrainableError,
    ExperimentDefinition,
    ExperimentNotCancellableError,
    ExperimentNotFoundError,
    ExperimentPage,
    ExperimentRecord,
    ExperimentStatus,
    ExperimentWork,
    SensitivityMode,
    StagedExperiment,
    WeatherMode,
)
from energy_forecast.ml.features import FEATURE_SCHEMA_BASE_V1
from energy_forecast.ml.metrics import MetricSet
from energy_forecast.ml.registry import AlgorithmType
from energy_forecast.ml.splits import SPLIT_DEFINITION_V1, TemporalFold


class SqlAlchemyExperimentRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def stage(
        self, definition: ExperimentDefinition, *, code_commit: str
    ) -> StagedExperiment:
        async with transactional_session(self._session_factory) as session:
            version = await session.scalar(
                select(DatasetVersion)
                .where(DatasetVersion.id == definition.dataset_version_id)
                .with_for_update()
            )
            if version is None or version.status != "ready" or version.interval_seconds != 3600:
                raise DatasetVersionNotTrainableError(
                    "Dataset version must be a ready hourly version"
                )
            experiment_id, job_id = uuid4(), uuid4()
            configuration = {
                "definition": SPLIT_DEFINITION_V1,
                "sensitivity_mode": definition.sensitivity_mode.value,
                "algorithms": [algorithm.value for algorithm in definition.algorithms],
            }
            job = Job(
                id=job_id,
                job_type="experiment",
                status="queued",
                priority=0,
                payload={"experiment_id": str(experiment_id)},
                progress_pct=0,
                attempt=0,
                max_attempts=3,
            )
            experiment = Experiment(
                id=experiment_id,
                dataset_version_id=definition.dataset_version_id,
                job_id=job_id,
                name=definition.name.strip(),
                status=ExperimentStatus.QUEUED.value,
                weather_mode=definition.weather_mode.value,
                forecast_horizon=24,
                feature_schema_version=FEATURE_SCHEMA_BASE_V1,
                split_definition=configuration,
                selection_rule_version=SELECTION_RULE_V1,
                code_commit=code_commit,
                environment_manifest={},
            )
            session.add(job)
            await session.flush()
            session.add(experiment)
            await session.flush()
            session.add_all(
                ModelRun(
                    id=uuid4(),
                    experiment_id=experiment_id,
                    algorithm=algorithm.value,
                    status="pending",
                    hyperparameters={},
                    random_seed=42,
                )
                for algorithm in definition.algorithms
            )
            await session.flush()
            return StagedExperiment(experiment_id, job_id, ExperimentStatus.QUEUED)

    async def list(self, *, page: int, page_size: int) -> ExperimentPage:
        async with transactional_session(self._session_factory) as session:
            total = int(await session.scalar(select(func.count()).select_from(Experiment)) or 0)
            rows = (
                await session.scalars(
                    select(Experiment)
                    .order_by(Experiment.created_at.desc(), Experiment.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            records = []
            for row in rows:
                records.append(await self._record(session, row))
            return ExperimentPage(tuple(records), page, page_size, total)

    async def get(self, experiment_id: UUID) -> ExperimentRecord:
        async with transactional_session(self._session_factory) as session:
            row = await session.get(Experiment, experiment_id)
            if row is None:
                raise ExperimentNotFoundError("Experiment was not found")
            return await self._record(session, row)

    async def comparison(self, experiment_id: UUID) -> tuple[dict[str, Any], ...]:
        async with transactional_session(self._session_factory) as session:
            exists = await session.get(Experiment, experiment_id)
            if exists is None:
                raise ExperimentNotFoundError("Experiment was not found")
            rows = (
                await session.scalars(
                    select(ModelRun)
                    .where(ModelRun.experiment_id == experiment_id)
                    .order_by(ModelRun.mean_cv_mae.nulls_last(), ModelRun.algorithm)
                )
            ).all()
            result = []
            for row in rows:
                folds = (
                    await session.scalars(
                        select(FoldMetric)
                        .where(FoldMetric.model_run_id == row.id)
                        .order_by(FoldMetric.fold_no)
                    )
                ).all()
                horizons = (
                    await session.scalars(
                        select(HorizonMetric)
                        .where(HorizonMetric.model_run_id == row.id)
                        .order_by(HorizonMetric.evaluation_scope, HorizonMetric.horizon)
                    )
                ).all()
                result.append(
                    {
                        "model_run_id": str(row.id),
                        "algorithm": row.algorithm,
                        "status": row.status,
                        "hyperparameters": row.hyperparameters,
                        "mean_cv_mae": row.mean_cv_mae,
                        "std_cv_mae": row.std_cv_mae,
                        "final_mae": row.final_mae,
                        "final_rmse": row.final_rmse,
                        "final_smape": row.final_smape,
                        "predict_ms_median": row.predict_ms_median,
                        "is_recommended": row.is_recommended,
                        "failure_code": row.failure_code,
                        "fold_metrics": [
                            {
                                "fold_no": fold.fold_no,
                                "evaluation_rows": fold.evaluation_rows,
                                "mae": fold.mae,
                                "rmse": fold.rmse,
                                "smape": fold.smape,
                            }
                            for fold in folds
                        ],
                        "horizon_metrics": [
                            {
                                "evaluation_scope": horizon.evaluation_scope,
                                "horizon": horizon.horizon,
                                "mae": horizon.mae,
                                "rmse": horizon.rmse,
                                "smape": horizon.smape,
                            }
                            for horizon in horizons
                        ],
                    }
                )
            return tuple(result)

    async def mark_cancelling(self, experiment_id: UUID) -> UUID:
        async with transactional_session(self._session_factory) as session:
            row = await session.scalar(
                select(Experiment).where(Experiment.id == experiment_id).with_for_update()
            )
            if row is None:
                raise ExperimentNotFoundError("Experiment was not found")
            if row.status not in {"queued", "running"} or row.job_id is None:
                raise ExperimentNotCancellableError("Experiment is not cancellable")
            row.status = ExperimentStatus.CANCELLING.value
            return row.job_id

    async def prepare(self, experiment_id: UUID, job_id: UUID) -> ExperimentWork:
        async with transactional_session(self._session_factory) as session:
            row = await session.scalar(
                select(Experiment).where(Experiment.id == experiment_id).with_for_update()
            )
            if row is None or row.job_id != job_id or row.status not in {"queued", "running"}:
                raise ValueError("Experiment payload references inconsistent resources")
            version = await session.get(DatasetVersion, row.dataset_version_id)
            if version is None:
                raise ValueError("Experiment dataset version disappeared")
            runs = (
                await session.scalars(
                    select(ModelRun).where(ModelRun.experiment_id == experiment_id)
                )
            ).all()
            row.status = ExperimentStatus.RUNNING.value
            row.started_at = row.started_at or datetime.now(UTC)
            row.failure_code = None
            row.failure_detail = None
            return ExperimentWork(
                experiment_id=row.id,
                job_id=job_id,
                dataset_version_id=row.dataset_version_id,
                algorithms=tuple(AlgorithmType(run.algorithm) for run in runs),
                model_run_ids={AlgorithmType(run.algorithm): run.id for run in runs},
                weather_mode=WeatherMode(row.weather_mode),
                sensitivity_mode=SensitivityMode(
                    str(row.split_definition.get("sensitivity_mode", "complete_only"))
                ),
                timezone=version.timezone_context or "UTC",
                code_commit=row.code_commit or "unknown",
            )

    async def load_hourly(self, dataset_version_id: UUID) -> pd.DataFrame:
        async with transactional_session(self._session_factory) as session:
            rows = (
                await session.scalars(
                    select(HourlyObservation)
                    .where(HourlyObservation.dataset_version_id == dataset_version_id)
                    .order_by(HourlyObservation.hour_start)
                )
            ).all()
        return pd.DataFrame(
            {
                "energy_kwh": [row.energy_kwh for row in rows],
                "coverage_ratio": [row.coverage_ratio for row in rows],
                "quality_status": [row.quality_status for row in rows],
            },
            index=pd.DatetimeIndex([row.hour_start for row in rows]),
        )

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
    ) -> None:
        async with transactional_session(self._session_factory) as session:
            run = await session.get(ModelRun, model_run_id)
            if run is None:
                raise ValueError("Model run disappeared")
            await session.execute(delete(FoldMetric).where(FoldMetric.model_run_id == model_run_id))
            await session.execute(
                delete(HorizonMetric).where(HorizonMetric.model_run_id == model_run_id)
            )
            run.status = "selected_parameters"
            run.hyperparameters = hyperparameters
            run.mean_cv_mae = mean_cv_mae
            run.std_cv_mae = std_cv_mae
            run.predict_ms_median = predict_ms_median
            run.failure_code = None
            run.failure_detail = None
            session.add_all(
                FoldMetric(
                    model_run_id=model_run_id,
                    fold_no=fold.fold_no,
                    train_start=fold.train_start,
                    train_end=fold.train_end,
                    validation_start=fold.validation_start,
                    validation_end=fold.validation_end,
                    evaluation_rows=len(fold.validation_indices),
                    mae=metrics.mae,
                    rmse=metrics.rmse,
                    smape=metrics.smape,
                    train_seconds=train_seconds,
                )
                for fold, metrics, train_seconds in folds
            )
            session.add_all(
                HorizonMetric(
                    model_run_id=model_run_id,
                    evaluation_scope="cv",
                    horizon=horizon,
                    mae=mae,
                    rmse=rmse,
                    smape=smape,
                )
                for horizon, mae, rmse, smape in horizons
            )

    async def fail_model(self, model_run_id: UUID, *, code: str, detail: str) -> None:
        async with transactional_session(self._session_factory) as session:
            run = await session.get(ModelRun, model_run_id)
            if run is not None:
                run.status = "failed"
                run.failure_code = code[:80]
                run.failure_detail = detail
                run.completed_at = datetime.now(UTC)

    async def open_final_test(self, experiment_id: UUID, model_run_id: UUID) -> None:
        async with transactional_session(self._session_factory) as session:
            experiment = await session.get(Experiment, experiment_id)
            run = await session.get(ModelRun, model_run_id)
            if experiment is None or run is None or run.mean_cv_mae is None:
                raise ValueError("Final test cannot be opened before CV selection")
            await session.execute(
                update(ModelRun)
                .where(
                    ModelRun.experiment_id == experiment_id,
                    ModelRun.status == "selected_parameters",
                )
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            experiment.final_test_opened_at = datetime.now(UTC)
            run.is_recommended = True
            run.status = "fitting_final"

    async def save_final_result(
        self,
        *,
        model_run_id: UUID,
        metrics: MetricSet,
        horizons: tuple[tuple[int, float, float, float], ...],
        artifact_id: UUID,
        artifact_size_bytes: int,
    ) -> None:
        async with transactional_session(self._session_factory) as session:
            run = await session.get(ModelRun, model_run_id)
            if run is None or not run.is_recommended:
                raise ValueError("Only the recommended model may receive final metrics")
            run.status = "completed"
            run.final_mae = metrics.mae
            run.final_rmse = metrics.rmse
            run.final_smape = metrics.smape
            run.artifact_id = artifact_id
            run.artifact_size_bytes = artifact_size_bytes
            run.completed_at = datetime.now(UTC)
            session.add_all(
                HorizonMetric(
                    model_run_id=model_run_id,
                    evaluation_scope="final_test",
                    horizon=horizon,
                    mae=mae,
                    rmse=rmse,
                    smape=smape,
                )
                for horizon, mae, rmse, smape in horizons
            )

    async def complete(self, experiment_id: UUID, manifest: dict[str, Any]) -> None:
        if not manifest:
            raise ValueError("Completed experiment requires a result manifest")
        async with transactional_session(self._session_factory) as session:
            row = await session.get(Experiment, experiment_id)
            if row is None or row.final_test_opened_at is None:
                raise ValueError("Experiment cannot complete before final evaluation")
            row.result_manifest = manifest
            row.status = ExperimentStatus.COMPLETED.value
            row.finished_at = datetime.now(UTC)

    async def fail_experiment(
        self, experiment_id: UUID, *, cancelled: bool, code: str, detail: str
    ) -> None:
        async with transactional_session(self._session_factory) as session:
            row = await session.get(Experiment, experiment_id)
            if row is not None and row.status != ExperimentStatus.COMPLETED.value:
                row.status = (
                    ExperimentStatus.CANCELLED.value if cancelled else ExperimentStatus.FAILED.value
                )
                row.failure_code = code[:80]
                row.failure_detail = detail
                row.finished_at = datetime.now(UTC)

    async def _record(self, session: Any, row: Experiment) -> ExperimentRecord:
        if row.job_id is None:
            raise ValueError("Persisted experiment is missing its job")
        algorithms = tuple(
            AlgorithmType(value)
            for value in (
                await session.scalars(
                    select(ModelRun.algorithm)
                    .where(ModelRun.experiment_id == row.id)
                    .order_by(ModelRun.created_at, ModelRun.algorithm)
                )
            ).all()
        )
        return ExperimentRecord(
            id=row.id,
            dataset_version_id=row.dataset_version_id,
            job_id=row.job_id,
            name=row.name,
            status=ExperimentStatus(row.status),
            weather_mode=WeatherMode(row.weather_mode),
            sensitivity_mode=SensitivityMode(
                str(row.split_definition.get("sensitivity_mode", "complete_only"))
            ),
            algorithms=algorithms,
            result_manifest=row.result_manifest,
            failure_code=row.failure_code,
            failure_detail=row.failure_detail,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
