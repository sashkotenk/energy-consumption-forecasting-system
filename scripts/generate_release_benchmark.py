#!/usr/bin/env python3
"""Generate reproducible release-readiness performance evidence.

Run from ``backend`` through the locked environment:
``uv run --frozen python ../scripts/generate_release_benchmark.py --output ../build/release-benchmark.json``.
The benchmark uses deterministic synthetic data only; it does not download or embed UCI data.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import numpy as np
from fastapi.testclient import TestClient

from energy_forecast.analytics.models import AnalyticsRange, SeriesResolution
from energy_forecast.analytics.service import _bounded_bucket_seconds
from energy_forecast.api import create_app
from energy_forecast.config import Environment, Settings
from energy_forecast.datasets.parsers import UciDatasetParser
from energy_forecast.ml.benchmark import benchmark_model
from energy_forecast.ml.models import create_model
from energy_forecast.ml.registry import AlgorithmType
from energy_forecast.quality.engine import DataQualityEngine
from energy_forecast.quality.models import QualityMeasurement
from energy_forecast.transformations.engine import TransformationEngine
from energy_forecast.transformations.models import SourceMeasurement, TransformationPolicy

START = datetime(2026, 1, 1, tzinfo=UTC)


def _measure(call: Callable[[], Any], repetitions: int) -> dict[str, float | int]:
    call()
    samples: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        call()
        samples.append((time.perf_counter() - started) * 1000.0)
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, max(0, int(round(0.95 * len(ordered) + 0.5)) - 1))
    return {
        "repetitions": repetitions,
        "median_ms": round(statistics.median(samples), 6),
        "p95_ms": round(ordered[p95_index], 6),
    }


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown"


def _memory_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def _parser_source(rows: int = 50_000) -> bytes:
    header = (
        b"Date;Time;Global_active_power;Global_reactive_power;Voltage;Global_intensity;"
        b"Sub_metering_1;Sub_metering_2;Sub_metering_3\n"
    )
    row = b"16/12/2006;17:24:00;4.216;0.418;234.840;18.400;0;1;17\n"
    return header + row * rows


def _quality_rows(rows: int = 10_000) -> tuple[QualityMeasurement, ...]:
    return tuple(
        QualityMeasurement(
            source_row_number=index + 1,
            observed_at=START + timedelta(minutes=index),
            energy_kwh=None,
            active_power_kw=1.0 + (index % 24) / 100.0,
            reactive_power_kw=0.2,
            voltage_v=230.0,
            current_a=4.0,
            sub_metering_1_wh=1.0,
            sub_metering_2_wh=2.0,
            sub_metering_3_wh=3.0,
            parse_status="valid",
            quality_flags=(),
        )
        for index in range(rows)
    )


def _transformation_rows(hours: int = 24) -> tuple[SourceMeasurement, ...]:
    return tuple(
        SourceMeasurement(
            observed_at=START + timedelta(minutes=index),
            source_row_number=index + 1,
            interval_seconds=60,
            energy_kwh=None,
            active_power_kw=1.0 + (index % 60) / 1000.0,
            reactive_power_kw=0.2,
            voltage_v=230.0,
            current_a=4.0,
        )
        for index in range(hours * 60)
    )


def _ml_fixture() -> tuple[np.ndarray, np.ndarray]:
    random = np.random.default_rng(42)
    features = random.normal(size=(96, 5))
    coefficients = random.normal(scale=0.4, size=(5, 24))
    horizons = np.arange(1, 25, dtype=np.float64) * 0.05
    targets = 5.0 + features @ coefficients + horizons
    return np.asarray(features, dtype=np.float64), np.asarray(targets, dtype=np.float64)


def _build_evidence() -> dict[str, Any]:
    parser_bytes = _parser_source()
    parser = UciDatasetParser()

    def parse() -> int:
        return sum(
            len(batch.measurements)
            for batch in parser.parse_batches(BytesIO(parser_bytes), batch_size=1_000)
        )

    quality_rows = _quality_rows()
    quality = DataQualityEngine()

    transformation_rows = _transformation_rows()
    transformation = TransformationEngine()
    policy = TransformationPolicy()

    analytics_range = AnalyticsRange(START, START + timedelta(days=365))

    app = create_app(Settings(environment=Environment.TEST, database_url=None, log_level="WARNING"))
    client = TestClient(app)

    def live_request() -> int:
        response = client.get("/health/live")
        if response.status_code != 200:
            raise RuntimeError(f"unexpected liveness status: {response.status_code}")
        return response.status_code

    features, targets = _ml_fixture()
    model_result = benchmark_model(
        lambda: create_model(AlgorithmType.RIDGE),
        features,
        targets,
        features[:1],
        training_repetitions=3,
        prediction_repetitions=30,
    )

    parser_timing = _measure(parse, 3)
    parser_timing["rows"] = 50_000
    parser_timing["median_rows_per_second"] = round(
        50_000 / (float(parser_timing["median_ms"]) / 1000.0), 2
    )

    return {
        "schema": "energyforecast-release-benchmark/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "release_commit": os.environ.get("GITHUB_SHA") or os.environ.get("CODE_COMMIT") or "unknown",
        "profile": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu": _cpu_model(),
            "logical_cpus": os.cpu_count(),
            "memory_bytes": _memory_bytes(),
            "random_seed": 42,
            "parallelism": "benchmark ML profile uses n_jobs=1",
        },
        "dataset": {
            "kind": "deterministic synthetic",
            "uci_in_repository": False,
            "note": "The full UCI profile is a separate external-source check.",
        },
        "measurements": {
            "parser_50k_rows": parser_timing,
            "quality_10k_rows": _measure(lambda: quality.evaluate(quality_rows), 3),
            "transformation_24h_minutes": _measure(
                lambda: transformation.transform(
                    transformation_rows,
                    interval_seconds=60,
                    timezone_context="UTC",
                    policy=policy,
                ),
                5,
            ),
            "analytics_bucket_selection": _measure(
                lambda: _bounded_bucket_seconds(
                    analytics_range,
                    3600 if SeriesResolution.HOUR else 3600,
                    500,
                ),
                1_000,
            ),
            "api_liveness": _measure(live_request, 100),
            "ridge_direct_24": {
                "training_repetitions": model_result.training_repetitions,
                "train_seconds_median": round(model_result.train_seconds_median, 6),
                "prediction_repetitions": model_result.prediction_repetitions,
                "prediction_ms_median": round(model_result.prediction_ms_median, 6),
                "prediction_ms_p95": round(model_result.prediction_ms_p95, 6),
                "artifact_size_bytes": model_result.artifact_size_bytes,
                "training_rows": int(features.shape[0]),
                "feature_count": int(features.shape[1]),
                "horizon": int(targets.shape[1]),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = _build_evidence()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
