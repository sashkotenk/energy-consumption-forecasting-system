"""Deterministic UTF-8 export serializers and download filename handling."""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import Enum
from io import StringIO
from typing import Any
from uuid import UUID

from energy_forecast.experiments.models import ExperimentRecord
from energy_forecast.forecasting.models import ForecastRecord

FORECAST_CSV_COLUMNS = (
    "forecast_id",
    "model_run_id",
    "dataset_version_id",
    "origin",
    "timezone",
    "algorithm",
    "feature_schema_version",
    "bundle_sha256",
    "total_energy_kwh",
    "horizon",
    "target_time",
    "predicted_energy_kwh",
    "actual_energy_kwh",
)

METRICS_CSV_COLUMNS = (
    "experiment_id",
    "model_run_id",
    "algorithm",
    "status",
    "is_recommended",
    "hyperparameters_json",
    "row_type",
    "fold_no",
    "evaluation_scope",
    "horizon",
    "evaluation_rows",
    "mae",
    "rmse",
    "smape",
    "mean_cv_mae",
    "std_cv_mae",
    "final_mae",
    "final_rmse",
    "final_smape",
    "predict_ms_median",
    "failure_code",
)

_FORMULA_PREFIXES = frozenset("=+-@")
_LEADING_WHITESPACE = " \t\r\n"
_SAFE_FILENAME_CHARACTER = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_DOWNLOAD_FILENAME = 120


def neutralize_csv_cell(value: object) -> object:
    """Prefix formula-like textual cells so spreadsheets treat them as literal text."""
    if not isinstance(value, str) or not value:
        return value
    trimmed = value.lstrip(_LEADING_WHITESPACE)
    if value[0] in "\t\r\n" or (trimmed and trimmed[0] in _FORMULA_PREFIXES):
        return f"'{value}"
    return value


def forecast_csv(record: ForecastRecord) -> bytes:
    """Serialize a forecast to UTF-8 CSV with a fixed, versioned column order."""
    rows = (
        {
            "forecast_id": record.id,
            "model_run_id": record.model_run_id,
            "dataset_version_id": record.dataset_version_id,
            "origin": record.origin,
            "timezone": record.timezone,
            "algorithm": record.algorithm,
            "feature_schema_version": record.feature_schema_version,
            "bundle_sha256": record.bundle_sha256,
            "total_energy_kwh": record.total_energy_kwh,
            "horizon": point.horizon,
            "target_time": point.target_time,
            "predicted_energy_kwh": point.predicted_energy_kwh,
            "actual_energy_kwh": point.actual_energy_kwh,
        }
        for point in record.points
    )
    return _csv_bytes(rows, FORECAST_CSV_COLUMNS)


def forecast_chart_json(record: ForecastRecord) -> bytes:
    """Serialize chart-ready forecast data without presentation-library coupling."""
    return json_bytes(
        {
            "schema": "forecast-chart-data/v1",
            "forecast_id": str(record.id),
            "origin": record.origin.isoformat(),
            "timezone": record.timezone,
            "unit": "kWh",
            "total_energy_kwh": record.total_energy_kwh,
            "series": [
                {
                    "horizon": point.horizon,
                    "timestamp": point.target_time.isoformat(),
                    "predicted_energy_kwh": point.predicted_energy_kwh,
                    "actual_energy_kwh": point.actual_energy_kwh,
                }
                for point in record.points
            ],
        }
    )


def experiment_metrics_csv(
    experiment: ExperimentRecord,
    comparison: tuple[dict[str, Any], ...],
) -> bytes:
    """Serialize summary, fold and horizon metrics into one normalized CSV table."""
    rows: list[dict[str, object]] = []
    for model in comparison:
        base = _metric_base(experiment, model)
        rows.append(
            {
                **base,
                "row_type": "summary",
                "mean_cv_mae": model.get("mean_cv_mae"),
                "std_cv_mae": model.get("std_cv_mae"),
                "final_mae": model.get("final_mae"),
                "final_rmse": model.get("final_rmse"),
                "final_smape": model.get("final_smape"),
                "predict_ms_median": model.get("predict_ms_median"),
            }
        )
        for fold in _mapping_items(model.get("fold_metrics")):
            rows.append(
                {
                    **base,
                    "row_type": "fold",
                    "fold_no": fold.get("fold_no"),
                    "evaluation_rows": fold.get("evaluation_rows"),
                    "mae": fold.get("mae"),
                    "rmse": fold.get("rmse"),
                    "smape": fold.get("smape"),
                }
            )
        for horizon in _mapping_items(model.get("horizon_metrics")):
            rows.append(
                {
                    **base,
                    "row_type": "horizon",
                    "evaluation_scope": horizon.get("evaluation_scope"),
                    "horizon": horizon.get("horizon"),
                    "mae": horizon.get("mae"),
                    "rmse": horizon.get("rmse"),
                    "smape": horizon.get("smape"),
                }
            )
    return _csv_bytes(rows, METRICS_CSV_COLUMNS)


def experiment_metrics_json(
    experiment: ExperimentRecord,
    comparison: tuple[dict[str, Any], ...],
) -> bytes:
    """Serialize complete persisted experiment comparison data as deterministic JSON."""
    return json_bytes(
        {
            "schema": "experiment-metrics-export/v1",
            "experiment": {
                "id": str(experiment.id),
                "dataset_version_id": str(experiment.dataset_version_id),
                "name": experiment.name,
                "status": experiment.status.value,
                "weather_mode": experiment.weather_mode.value,
                "sensitivity_mode": experiment.sensitivity_mode.value,
                "algorithms": [algorithm.value for algorithm in experiment.algorithms],
                "created_at": experiment.created_at.isoformat(),
                "started_at": _optional_datetime(experiment.started_at),
                "finished_at": _optional_datetime(experiment.finished_at),
            },
            "models": list(comparison),
        }
    )


def experiment_manifest_json(experiment: ExperimentRecord) -> bytes:
    """Serialize the canonical result manifest already persisted by experiment completion."""
    if experiment.result_manifest is None:
        raise ValueError("Completed experiment is missing its result manifest")
    return json_bytes(experiment.result_manifest)


def json_bytes(payload: object) -> bytes:
    """Encode JSON explicitly as UTF-8 with deterministic object-key ordering."""
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    )
    return f"{rendered}\n".encode("utf-8")


def safe_download_filename(original_name: str | None, *, fallback: str) -> str:
    """Return an ASCII attachment filename with no path or header-control semantics."""
    candidate = (original_name or fallback).replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    candidate = "".join(
        "_" if ord(character) < 32 or ord(character) == 127 else character
        for character in candidate
    )
    candidate = _SAFE_FILENAME_CHARACTER.sub("_", candidate).strip(" .")
    if not candidate or candidate in {".", ".."}:
        candidate = fallback
    candidate = candidate[:_MAX_DOWNLOAD_FILENAME].rstrip(" .")
    if not candidate:
        candidate = "export"
    return candidate


def content_disposition(filename: str) -> str:
    """Build a header value from an already sanitized ASCII filename."""
    safe = safe_download_filename(filename, fallback="export")
    return f'attachment; filename="{safe}"'


def _csv_bytes(rows: Iterable[Mapping[str, object]], fieldnames: tuple[str, ...]) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({name: _csv_value(row.get(name)) for name in fieldnames})
    return output.getvalue().encode("utf-8")


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return neutralize_csv_cell(str(value.value))
    if isinstance(value, bool):
        return "true" if value else "false"
    return neutralize_csv_cell(value)


def _metric_base(experiment: ExperimentRecord, model: Mapping[str, Any]) -> dict[str, object]:
    hyperparameters = json.dumps(
        model.get("hyperparameters", {}),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )
    return {
        "experiment_id": experiment.id,
        "model_run_id": model.get("model_run_id"),
        "algorithm": model.get("algorithm"),
        "status": model.get("status"),
        "is_recommended": model.get("is_recommended"),
        "hyperparameters_json": hyperparameters,
        "failure_code": model.get("failure_code"),
    }


def _mapping_items(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[Mapping[str, Any]] = []
    for item in value:
        if isinstance(item, Mapping):
            result.append(item)
    return tuple(result)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _optional_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
