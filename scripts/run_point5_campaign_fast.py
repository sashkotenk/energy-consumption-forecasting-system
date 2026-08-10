#!/usr/bin/env python3
"""Run the frozen Point-5 campaign with execution-only acceleration.

This wrapper keeps the scientific protocol unchanged while removing avoidable
re-training and parallelising the 24 independent direct forecast horizons during
cross-validation. Candidate grids, chronological folds, random seeds, metrics,
selection rules, final-test isolation and the final single-thread benchmark all
remain defined by ``run_point5_campaign.py``.

Hosted runners have limited RAM. All CV horizon parallelism in this wrapper uses
threads rather than joblib's process backend so the large feature matrices are
shared read-only instead of being duplicated into worker processes.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


def _load_campaign() -> Any:
    path = Path(__file__).with_name("run_point5_campaign.py")
    spec = importlib.util.spec_from_file_location("energyforecast_point5_campaign", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Point-5 campaign from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _progress(message: str) -> None:
    stamp = datetime.now(UTC).strftime("%H:%M:%S")
    print(f"[point5 {stamp}Z] {message}", flush=True)


def _install_acceleration(campaign: Any, fit_jobs: int) -> None:
    def fit_w0_horizon(
        algorithm: Any,
        parameters: dict[str, Any],
        features: Any,
        targets: Any,
        horizon: int,
    ) -> Any:
        with campaign.threadpool_limits(limits=1):
            target = targets[:, horizon]
            if algorithm is campaign.AlgorithmType.RIDGE:
                estimator = campaign.Ridge(**parameters).fit(features, target)
            elif algorithm is campaign.AlgorithmType.RANDOM_FOREST:
                estimator = campaign.RandomForestRegressor(
                    **parameters, n_jobs=1
                ).fit(features, target)
            else:
                estimator = campaign.HistGradientBoostingRegressor(**parameters).fit(
                    features, target
                )
        return estimator

    def fit_w0_model_threaded(
        algorithm: Any,
        parameters: dict[str, Any],
        features: Any,
        targets: Any,
    ) -> Any:
        model = campaign.create_model(
            algorithm,
            parameters=parameters,
            runtime=campaign.ModelRuntime(
                profile=campaign.ExecutionProfile.BENCHMARK,
                random_seed=42,
            ),
        )
        if algorithm is campaign.AlgorithmType.RIDGE:
            model.scaler = campaign.StandardScaler().fit(features)
            fit_features = np.asarray(model.scaler.transform(features), dtype=np.float64)
        else:
            model.scaler = None
            fit_features = features
        model.estimators = list(
            campaign.joblib.Parallel(n_jobs=fit_jobs, prefer="threads")(
                campaign.joblib.delayed(fit_w0_horizon)(
                    algorithm,
                    parameters,
                    fit_features,
                    targets,
                    horizon,
                )
                for horizon in range(24)
            )
        )
        return model

    def evaluate_w0_configuration(
        experiment_id: str,
        algorithm: Any,
        parameters: dict[str, Any],
        energy: Any,
        matrix: Any,
    ) -> Any:
        folds = campaign.ChronologicalSplitProtocol().cross_validation_folds(matrix.origins)
        fold_rows: list[Any] = []
        actual_parts: list[Any] = []
        predicted_parts: list[Any] = []
        _progress(
            f"{experiment_id} W0 {algorithm.value}: start {len(folds)} folds; "
            f"fit_jobs={fit_jobs}; params={json.dumps(parameters, sort_keys=True, default=campaign._json_default)}"
        )
        for fold in folds:
            origins = tuple(matrix.origins[int(index)] for index in fold.validation_indices)
            if algorithm is campaign.AlgorithmType.SEASONAL_NAIVE_24:
                train_seconds = 0.0
                prediction_started = time.perf_counter()
                predicted = campaign.SeasonalNaive(24).predict(energy, origins)
            elif algorithm is campaign.AlgorithmType.SEASONAL_NAIVE_168:
                train_seconds = 0.0
                prediction_started = time.perf_counter()
                predicted = campaign.SeasonalNaive(168).predict(energy, origins)
            else:
                training_started = time.perf_counter()
                model = fit_w0_model_threaded(
                    algorithm,
                    parameters,
                    matrix.features[fold.train_indices],
                    matrix.targets[fold.train_indices],
                )
                train_seconds = time.perf_counter() - training_started
                prediction_started = time.perf_counter()
                predicted = model.predict(matrix.features[fold.validation_indices])

            prediction_ms = (
                (time.perf_counter() - prediction_started)
                * 1000
                / len(fold.validation_indices)
            )
            actual = matrix.targets[fold.validation_indices]
            metrics = campaign.evaluate(actual, predicted)
            fold_rows.append(
                campaign.FoldResult(
                    fold_no=fold.fold_no,
                    train_rows=len(fold.train_indices),
                    validation_rows=len(fold.validation_indices),
                    mae=metrics.mae,
                    rmse=metrics.rmse,
                    smape=metrics.smape,
                    train_seconds=train_seconds,
                    predict_ms_per_origin=prediction_ms,
                )
            )
            actual_parts.append(actual)
            predicted_parts.append(predicted)
            _progress(
                f"{experiment_id} W0 fold {fold.fold_no}/4 complete: "
                f"MAE={metrics.mae:.6f}, train={train_seconds:.1f}s"
            )

        actual_all = np.vstack(actual_parts)
        predicted_all = np.vstack(predicted_parts)
        fold_mae = [row.mae for row in fold_rows]
        result = campaign.CvResult(
            experiment_id=experiment_id,
            algorithm=algorithm,
            weather_mode="W0",
            quality_profile="main_90_complete_or_imputed",
            parameters=dict(parameters),
            folds=tuple(fold_rows),
            actual=actual_all,
            predicted=predicted_all,
            overall=campaign.evaluate(actual_all, predicted_all),
            mean_cv_mae=float(statistics.fmean(fold_mae)),
            std_cv_mae=float(np.std(np.asarray(fold_mae, dtype=np.float64), ddof=0)),
            train_seconds_median=float(
                statistics.median(row.train_seconds for row in fold_rows)
            ),
            predict_ms_median=float(
                statistics.median(row.predict_ms_per_origin for row in fold_rows)
            ),
        )
        _progress(
            f"{experiment_id} W0 complete: mean CV MAE={result.mean_cv_mae:.6f}"
        )
        return result

    def fit_weather_horizon(
        algorithm: Any,
        parameters: dict[str, Any],
        base_features: Any,
        weather_cube: Any,
        targets: Any,
        horizon: int,
    ) -> tuple[Any, Any]:
        with campaign.threadpool_limits(limits=1):
            values = np.column_stack((base_features, weather_cube[:, horizon, :]))
            target = targets[:, horizon]
            if algorithm is campaign.AlgorithmType.RIDGE:
                scaler = campaign.StandardScaler().fit(values)
                transformed = np.asarray(scaler.transform(values), dtype=np.float64)
                estimator = campaign.Ridge(**parameters).fit(transformed, target)
            elif algorithm is campaign.AlgorithmType.RANDOM_FOREST:
                scaler = None
                estimator = campaign.RandomForestRegressor(
                    **parameters, n_jobs=1
                ).fit(values, target)
            else:
                scaler = None
                estimator = campaign.HistGradientBoostingRegressor(**parameters).fit(
                    values, target
                )
        return estimator, scaler

    def fit_weather_model(
        algorithm: Any,
        parameters: dict[str, Any],
        base_features: Any,
        weather_cube: Any,
        targets: Any,
    ) -> Any:
        if algorithm not in campaign.ML_ALGORITHMS:
            raise ValueError("W1 is defined only for the three ML algorithms")
        fitted = campaign.joblib.Parallel(n_jobs=fit_jobs, prefer="threads")(
            campaign.joblib.delayed(fit_weather_horizon)(
                algorithm,
                parameters,
                base_features,
                weather_cube,
                targets,
                horizon,
            )
            for horizon in range(24)
        )
        return campaign.WeatherDirectModel(
            algorithm,
            dict(parameters),
            [item[0] for item in fitted],
            [item[1] for item in fitted],
        )

    def evaluate_w1_configuration(
        experiment_id: str,
        algorithm: Any,
        parameters: dict[str, Any],
        matrix: Any,
        weather_cube: Any,
    ) -> Any:
        folds = campaign.ChronologicalSplitProtocol().cross_validation_folds(matrix.origins)
        fold_rows: list[Any] = []
        actual_parts: list[Any] = []
        predicted_parts: list[Any] = []
        _progress(
            f"{experiment_id} W1 {algorithm.value}: start {len(folds)} folds; "
            f"fit_jobs={fit_jobs}; params={json.dumps(parameters, sort_keys=True, default=campaign._json_default)}"
        )
        for fold in folds:
            started = time.perf_counter()
            model = fit_weather_model(
                algorithm,
                parameters,
                matrix.features[fold.train_indices],
                weather_cube[fold.train_indices],
                matrix.targets[fold.train_indices],
            )
            train_seconds = time.perf_counter() - started
            prediction_started = time.perf_counter()
            predicted = model.predict(
                matrix.features[fold.validation_indices],
                weather_cube[fold.validation_indices],
            )
            prediction_ms = (
                (time.perf_counter() - prediction_started)
                * 1000
                / len(fold.validation_indices)
            )
            actual = matrix.targets[fold.validation_indices]
            metrics = campaign.evaluate(actual, predicted)
            fold_rows.append(
                campaign.FoldResult(
                    fold_no=fold.fold_no,
                    train_rows=len(fold.train_indices),
                    validation_rows=len(fold.validation_indices),
                    mae=metrics.mae,
                    rmse=metrics.rmse,
                    smape=metrics.smape,
                    train_seconds=train_seconds,
                    predict_ms_per_origin=prediction_ms,
                )
            )
            actual_parts.append(actual)
            predicted_parts.append(predicted)
            _progress(
                f"{experiment_id} W1 fold {fold.fold_no}/4 complete: "
                f"MAE={metrics.mae:.6f}, train={train_seconds:.1f}s"
            )

        actual_all = np.vstack(actual_parts)
        predicted_all = np.vstack(predicted_parts)
        fold_mae = [row.mae for row in fold_rows]
        result = campaign.CvResult(
            experiment_id=experiment_id,
            algorithm=algorithm,
            weather_mode="W1",
            quality_profile="main_90_complete_or_imputed",
            parameters=dict(parameters),
            folds=tuple(fold_rows),
            actual=actual_all,
            predicted=predicted_all,
            overall=campaign.evaluate(actual_all, predicted_all),
            mean_cv_mae=float(statistics.fmean(fold_mae)),
            std_cv_mae=float(np.std(np.asarray(fold_mae, dtype=np.float64), ddof=0)),
            train_seconds_median=float(
                statistics.median(row.train_seconds for row in fold_rows)
            ),
            predict_ms_median=float(
                statistics.median(row.predict_ms_per_origin for row in fold_rows)
            ),
        )
        _progress(
            f"{experiment_id} W1 complete: mean CV MAE={result.mean_cv_mae:.6f}"
        )
        return result

    campaign._evaluate_w0_configuration = evaluate_w0_configuration
    campaign._fit_weather_model = fit_weather_model
    campaign._evaluate_w1_configuration = evaluate_w1_configuration


def _augment_runtime_evidence(campaign: Any, output_dir: Path, requested: int, effective: int) -> dict[str, Any]:
    manifest_path = output_dir / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["protocol"]["cv_fit_parallelism"] = {
        "requested_jobs": requested,
        "effective_jobs": effective,
        "backend": "shared-memory threads",
        "scope": "independent 24 direct horizons during CV and W1 final ablation only",
        "prediction_timing_profile": "single-thread benchmark",
        "final_benchmark_profile": "unchanged single-thread 3 measured training runs",
        "scientific_invariants": [
            "candidate configurations unchanged",
            "chronological folds and 24-hour purge unchanged",
            "random seed 42 unchanged",
            "targets, metrics and selection rule unchanged",
            "selection persisted before final-test access",
        ],
    }
    campaign._write_json(manifest_path, manifest)

    benchmark_path = output_dir / "benchmark.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark["cv_acceleration"] = manifest["protocol"]["cv_fit_parallelism"]
    campaign._write_json(benchmark_path, benchmark)

    readme_path = output_dir / "README.md"
    with readme_path.open("a", encoding="utf-8") as destination:
        destination.write(
            "\n## Execution acceleration\n\n"
            f"Cross-validation fitted the 24 independent direct horizons with **{effective} parallel jobs** "
            "using a shared-memory thread backend to stay within hosted-runner RAM limits. This changes "
            "execution scheduling only: candidate grids, chronological folds, purge, random seed, targets, "
            "metrics and the selection rule are unchanged. Prediction timing used for tie-breaking and the "
            "final three-repeat benchmark remain single-threaded.\n"
        )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--preparation-json", type=Path, required=True)
    parser.add_argument("--handoff-json", type=Path, required=True)
    parser.add_argument("--weather-csv", type=Path, required=True)
    parser.add_argument("--weather-metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-candidate-sha", required=True)
    parser.add_argument("--max-tree-candidates", type=int, default=4)
    parser.add_argument("--fit-jobs", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.max_tree_candidates <= 20:
        raise SystemExit("--max-tree-candidates must be between 1 and 20")
    if args.fit_jobs < 1:
        raise SystemExit("--fit-jobs must be at least 1")

    available = max(1, os.cpu_count() or 1)
    effective_jobs = min(args.fit_jobs, available)
    campaign = _load_campaign()
    _install_acceleration(campaign, effective_jobs)
    _progress(
        f"accelerated campaign start: requested_fit_jobs={args.fit_jobs}, "
        f"effective_fit_jobs={effective_jobs}, logical_cpus={available}"
    )
    asyncio.run(campaign._run(args))
    manifest = _augment_runtime_evidence(
        campaign, args.output_dir.resolve(), args.fit_jobs, effective_jobs
    )
    _progress("campaign complete; runtime evidence augmented")
    print(json.dumps(manifest, indent=2, sort_keys=True, default=campaign._json_default))


if __name__ == "__main__":
    main()
