"""Restart-safe worker handler for chronological model experiments."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from energy_forecast.experiments.models import ExperimentWork, SensitivityMode
from energy_forecast.experiments.ports import ExperimentRepository
from energy_forecast.experiments.selection import SelectionCandidate, select_recommended
from energy_forecast.jobs.domain import JobCancellationRequested
from energy_forecast.jobs.worker import JobExecutionContext
from energy_forecast.ml.baselines import SeasonalNaive
from energy_forecast.ml.bundles import BundleManifestInput, ModelBundleService
from energy_forecast.ml.features import FeatureMatrix, FeaturePipeline, FeaturePipelineConfig
from energy_forecast.ml.metrics import MetricSet, evaluate
from energy_forecast.ml.models import ExecutionProfile, ModelRuntime, create_model
from energy_forecast.ml.ports import Predictor
from energy_forecast.ml.registry import AlgorithmRegistry, AlgorithmType
from energy_forecast.ml.search import candidate_configurations
from energy_forecast.ml.splits import (
    FINAL_TEST_START,
    SPLIT_DEFINITION_V1,
    ChronologicalSplitProtocol,
    TemporalFold,
)


@dataclass(frozen=True, slots=True)
class _CvResult:
    parameters: dict[str, Any]
    folds: tuple[tuple[TemporalFold, MetricSet, float], ...]
    actual: NDArray[np.float64]
    predicted: NDArray[np.float64]
    mean_mae: float
    std_mae: float
    predict_ms_median: float


class ExperimentHandler:
    def __init__(
        self,
        repository: ExperimentRepository,
        bundles: ModelBundleService,
        *,
        max_candidates: int = 20,
    ) -> None:
        self._repository = repository
        self._bundles = bundles
        self._max_candidates = max_candidates

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        experiment_id = UUID(_required(context.payload, "experiment_id"))
        try:
            work = await self._repository.prepare(experiment_id, context.job_id)
            hourly = _quality_view(
                await self._repository.load_hourly(work.dataset_version_id),
                work.sensitivity_mode,
            )
            matrix = FeaturePipeline(
                FeaturePipelineConfig(timezone=work.timezone)
            ).build_supervised(hourly)
            protocol = ChronologicalSplitProtocol()
            folds = protocol.cross_validation_folds(matrix.origins)
            successful: list[tuple[SelectionCandidate, _CvResult]] = []
            for position, algorithm in enumerate(work.algorithms):
                context.raise_if_cancel_requested()
                run_id = work.model_run_ids[algorithm]
                try:
                    result = await asyncio.to_thread(
                        _cross_validate,
                        algorithm,
                        hourly["energy_kwh"],
                        matrix,
                        folds,
                        self._max_candidates,
                    )
                    await self._repository.save_cv_result(
                        model_run_id=run_id,
                        hyperparameters=result.parameters,
                        folds=result.folds,
                        horizons=_horizon_metrics(result.actual, result.predicted),
                        mean_cv_mae=result.mean_mae,
                        std_cv_mae=result.std_mae,
                        predict_ms_median=result.predict_ms_median,
                    )
                    successful.append(
                        (
                            SelectionCandidate(
                                algorithm,
                                run_id,
                                result.mean_mae,
                                result.std_mae,
                                result.predict_ms_median,
                            ),
                            result,
                        )
                    )
                except Exception as error:
                    await self._repository.fail_model(
                        run_id,
                        code="model_evaluation_failed",
                        detail=str(error) or type(error).__name__,
                    )
                await context.report_progress(int((position + 1) / len(work.algorithms) * 75))
            if not successful:
                raise RuntimeError("All configured model runs failed")

            recommended = select_recommended(tuple(candidate for candidate, _ in successful))
            selected_result = next(
                result
                for candidate, result in successful
                if candidate.model_run_id == recommended.model_run_id
            )
            context.raise_if_cancel_requested()
            model = await asyncio.to_thread(
                _fit_final_model,
                recommended.algorithm,
                selected_result.parameters,
                matrix,
            )
            await self._repository.open_final_test(
                experiment_id, UUID(str(recommended.model_run_id))
            )
            final_indices = protocol.final_test_indices(matrix.origins)
            if final_indices.size == 0:
                raise ValueError("Final test period has no eligible origins")
            final_predictions, final_metrics = await asyncio.to_thread(
                _evaluate_final,
                model,
                recommended.algorithm,
                hourly["energy_kwh"],
                matrix,
                final_indices,
            )
            descriptor = AlgorithmRegistry().get(recommended.algorithm)
            bundle = await self._bundles.save(
                cast(Predictor, model),
                BundleManifestInput(
                    algorithm=recommended.algorithm,
                    implementation_version=descriptor.implementation_version,
                    feature_schema=matrix.schema,
                    training_dataset_version_id=work.dataset_version_id,
                    split_definition=SPLIT_DEFINITION_V1,
                    code_commit=work.code_commit,
                    model_parameters=selected_result.parameters,
                    quality_policy={"sensitivity_mode": work.sensitivity_mode.value},
                    weather_mode=work.weather_mode.value,
                ),
            )
            await self._repository.save_final_result(
                model_run_id=UUID(str(recommended.model_run_id)),
                metrics=final_metrics,
                horizons=_horizon_metrics(matrix.targets[final_indices], final_predictions),
                artifact_id=bundle.artifact_id,
                artifact_size_bytes=bundle.size_bytes,
            )
            manifest = _result_manifest(work, matrix, recommended, bundle.artifact_id)
            await self._repository.complete(experiment_id, manifest)
            await context.report_progress(100)
            return manifest
        except JobCancellationRequested:
            await self._repository.fail_experiment(
                experiment_id,
                cancelled=True,
                code="experiment_cancelled",
                detail="Experiment execution was cancelled",
            )
            raise
        except BaseException as error:
            await self._repository.fail_experiment(
                experiment_id,
                cancelled=False,
                code="experiment_failed",
                detail=str(error) or type(error).__name__,
            )
            raise


def _cross_validate(
    algorithm: AlgorithmType,
    energy: pd.Series,
    matrix: FeatureMatrix,
    folds: tuple[TemporalFold, ...],
    max_candidates: int,
) -> _CvResult:
    candidates = candidate_configurations(algorithm, max_candidates=max_candidates)
    results = tuple(
        _evaluate_configuration(algorithm, parameters, energy, matrix, folds)
        for parameters in candidates
    )
    return min(
        results,
        key=lambda result: (
            result.mean_mae,
            result.std_mae,
            json.dumps(result.parameters, sort_keys=True, default=str),
        ),
    )


def _evaluate_configuration(
    algorithm: AlgorithmType,
    parameters: dict[str, Any],
    energy: pd.Series,
    matrix: FeatureMatrix,
    folds: tuple[TemporalFold, ...],
) -> _CvResult:
    fold_results: list[tuple[TemporalFold, MetricSet, float]] = []
    actual_parts: list[NDArray[np.float64]] = []
    predicted_parts: list[NDArray[np.float64]] = []
    prediction_timings: list[float] = []
    for fold in folds:
        origins = tuple(matrix.origins[index] for index in fold.validation_indices)
        started = time.perf_counter()
        if algorithm is AlgorithmType.SEASONAL_NAIVE_24:
            predictor = SeasonalNaive(24)
            train_seconds = 0.0
            prediction_started = time.perf_counter()
            predicted = predictor.predict(energy, origins)
        elif algorithm is AlgorithmType.SEASONAL_NAIVE_168:
            predictor = SeasonalNaive(168)
            train_seconds = 0.0
            prediction_started = time.perf_counter()
            predicted = predictor.predict(energy, origins)
        else:
            model = create_model(
                algorithm,
                parameters=parameters,
                runtime=ModelRuntime(profile=ExecutionProfile.BENCHMARK),
            )
            model.fit(matrix.features[fold.train_indices], matrix.targets[fold.train_indices])
            train_seconds = time.perf_counter() - started
            prediction_started = time.perf_counter()
            predicted = model.predict(matrix.features[fold.validation_indices])
        prediction_timings.append(
            (time.perf_counter() - prediction_started) * 1000 / len(fold.validation_indices)
        )
        actual = matrix.targets[fold.validation_indices]
        metrics = evaluate(actual, predicted)
        fold_results.append((fold, metrics, train_seconds))
        actual_parts.append(actual)
        predicted_parts.append(predicted)
    maes = np.asarray([metrics.mae for _, metrics, _ in fold_results], dtype=np.float64)
    return _CvResult(
        parameters=dict(parameters),
        folds=tuple(fold_results),
        actual=np.vstack(actual_parts),
        predicted=np.vstack(predicted_parts),
        mean_mae=float(np.mean(maes)),
        std_mae=float(np.std(maes, ddof=0)),
        predict_ms_median=float(np.median(prediction_timings)),
    )


def _fit_final_model(
    algorithm: AlgorithmType,
    parameters: dict[str, Any],
    matrix: FeatureMatrix,
) -> object:
    cutoff = FINAL_TEST_START - timedelta(hours=24)
    train_indices = np.asarray(
        [index for index, origin in enumerate(matrix.origins) if origin < cutoff], dtype=np.int64
    )
    if algorithm is AlgorithmType.SEASONAL_NAIVE_24:
        return SeasonalNaive(24)
    if algorithm is AlgorithmType.SEASONAL_NAIVE_168:
        return SeasonalNaive(168)
    model = create_model(
        algorithm,
        parameters=parameters,
        runtime=ModelRuntime(profile=ExecutionProfile.PRODUCTION),
    )
    model.fit(matrix.features[train_indices], matrix.targets[train_indices])
    return model


def _evaluate_final(
    model: object,
    algorithm: AlgorithmType,
    energy: pd.Series,
    matrix: FeatureMatrix,
    final_indices: NDArray[np.int64],
) -> tuple[NDArray[np.float64], MetricSet]:
    final_origins = tuple(matrix.origins[index] for index in final_indices)
    if algorithm in {
        AlgorithmType.SEASONAL_NAIVE_24,
        AlgorithmType.SEASONAL_NAIVE_168,
    }:
        baseline = cast(SeasonalNaive, model)
        predicted = baseline.predict(energy, final_origins)
    else:
        predictor = cast(Predictor, model)
        predicted = predictor.predict(matrix.features[final_indices])
    actual = matrix.targets[final_indices]
    return predicted, evaluate(actual, predicted)


def _quality_view(hourly: pd.DataFrame, mode: SensitivityMode) -> pd.DataFrame:
    selected = hourly.copy()
    if mode is SensitivityMode.COMPLETE_ONLY:
        eligible = selected["quality_status"].eq("complete")
    else:
        eligible = selected["coverage_ratio"].ge(0.9) & selected["quality_status"].isin(
            ("complete", "imputed_short_gap", "valid_partial")
        )
    selected.loc[~eligible, "energy_kwh"] = np.nan
    return selected


def _horizon_metrics(
    actual: NDArray[np.float64], predicted: NDArray[np.float64]
) -> tuple[tuple[int, float, float, float], ...]:
    result: list[tuple[int, float, float, float]] = []
    for index in range(24):
        actual_h = actual[:, index]
        predicted_h = predicted[:, index]
        absolute = np.abs(actual_h - predicted_h)
        denominator = np.abs(actual_h) + np.abs(predicted_h)
        smape = np.divide(
            2 * absolute,
            denominator,
            out=np.zeros_like(denominator),
            where=denominator != 0,
        )
        result.append(
            (
                index + 1,
                float(np.mean(absolute)),
                float(np.sqrt(np.mean(np.square(actual_h - predicted_h)))),
                float(np.mean(smape) * 100),
            )
        )
    return tuple(result)


def _result_manifest(
    work: ExperimentWork,
    matrix: FeatureMatrix,
    selected: SelectionCandidate,
    artifact_id: UUID,
) -> dict[str, Any]:
    origins = "\n".join(origin.isoformat() for origin in matrix.origins).encode()
    return {
        "schema_version": "experiment-result/v1",
        "experiment_id": str(work.experiment_id),
        "dataset_version_id": str(work.dataset_version_id),
        "split_definition": SPLIT_DEFINITION_V1,
        "feature_schema_version": matrix.schema.version,
        "feature_schema_sha256": matrix.schema.sha256,
        "eligible_origins_sha256": hashlib.sha256(origins).hexdigest(),
        "selection_rule": "cv-mae-1pct-std-5pct-time-simplicity/v1",
        "recommended_model_run_id": str(selected.model_run_id),
        "recommended_algorithm": selected.algorithm.value,
        "artifact_id": str(artifact_id),
        "weather_mode": work.weather_mode.value,
        "sensitivity_mode": work.sensitivity_mode.value,
        "code_commit": work.code_commit,
        "random_seed": 42,
    }


def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Experiment payload is missing {key}")
    return value
