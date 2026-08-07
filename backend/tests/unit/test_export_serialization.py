from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import UUID

from energy_forecast.experiments.models import (
    ExperimentRecord,
    ExperimentStatus,
    SensitivityMode,
    WeatherMode,
)
from energy_forecast.exports.serialization import (
    FORECAST_CSV_COLUMNS,
    METRICS_CSV_COLUMNS,
    content_disposition,
    experiment_manifest_json,
    experiment_metrics_csv,
    experiment_metrics_json,
    forecast_chart_json,
    forecast_csv,
    neutralize_csv_cell,
    safe_download_filename,
)
from energy_forecast.forecasting.models import ForecastPoint, ForecastRecord
from energy_forecast.ml.registry import AlgorithmType

_FORECAST_ID = UUID("11111111-1111-4111-8111-111111111111")
_MODEL_RUN_ID = UUID("22222222-2222-4222-8222-222222222222")
_DATASET_VERSION_ID = UUID("33333333-3333-4333-8333-333333333333")
_ARTIFACT_ID = UUID("44444444-4444-4444-8444-444444444444")
_EXPERIMENT_ID = UUID("55555555-5555-4555-8555-555555555555")
_JOB_ID = UUID("66666666-6666-4666-8666-666666666666")
_ORIGIN = datetime(2026, 1, 2, 0, tzinfo=UTC)


def _forecast() -> ForecastRecord:
    points = tuple(
        ForecastPoint(
            horizon=horizon,
            target_time=_ORIGIN + timedelta(hours=horizon),
            predicted_energy_kwh=0.25 * horizon,
            actual_energy_kwh=None if horizon == 24 else 0.2 * horizon,
        )
        for horizon in range(1, 25)
    )
    return ForecastRecord(
        id=_FORECAST_ID,
        model_run_id=_MODEL_RUN_ID,
        dataset_version_id=_DATASET_VERSION_ID,
        artifact_id=_ARTIFACT_ID,
        bundle_sha256="a" * 64,
        algorithm=AlgorithmType.RIDGE,
        feature_schema_version="base_v1",
        origin=_ORIGIN,
        timezone="Europe/Kyiv",
        status="completed",
        total_energy_kwh=sum(point.predicted_energy_kwh for point in points),
        points=points,
        created_at=_ORIGIN,
        completed_at=_ORIGIN + timedelta(seconds=1),
    )


def _experiment(*, manifest: dict[str, object] | None = None) -> ExperimentRecord:
    return ExperimentRecord(
        id=_EXPERIMENT_ID,
        dataset_version_id=_DATASET_VERSION_ID,
        job_id=_JOB_ID,
        name="Експеримент формул",
        status=ExperimentStatus.COMPLETED,
        weather_mode=WeatherMode.WITHOUT_WEATHER,
        sensitivity_mode=SensitivityMode.COMPLETE_ONLY,
        algorithms=(AlgorithmType.RIDGE,),
        result_manifest=manifest or {"schema": "experiment-result/v1", "status": "completed"},
        failure_code=None,
        failure_detail=None,
        created_at=_ORIGIN,
        started_at=_ORIGIN,
        finished_at=_ORIGIN + timedelta(minutes=1),
    )


def test_forecast_csv_is_utf8_and_has_stable_column_order() -> None:
    payload = forecast_csv(_forecast())
    text = payload.decode("utf-8")
    rows = list(csv.reader(StringIO(text)))

    assert tuple(rows[0]) == FORECAST_CSV_COLUMNS
    assert len(rows) == 25
    assert rows[1][0] == str(_FORECAST_ID)
    assert rows[1][9] == "1"
    assert rows[-1][9] == "24"


def test_formula_prefixes_are_neutralized_only_for_text_cells() -> None:
    assert neutralize_csv_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
    assert neutralize_csv_cell(" +cmd") == "' +cmd"
    assert neutralize_csv_cell("-danger") == "'-danger"
    assert neutralize_csv_cell("@formula") == "'@formula"
    assert neutralize_csv_cell("\t=hidden") == "'\t=hidden"
    assert neutralize_csv_cell("plain text") == "plain text"
    assert neutralize_csv_cell(-1.5) == -1.5


def test_metrics_csv_is_normalized_stable_and_formula_safe() -> None:
    comparison = (
        {
            "model_run_id": str(_MODEL_RUN_ID),
            "algorithm": "=HYPERLINK(\"https://example.invalid\")",
            "status": "completed",
            "hyperparameters": {"alpha": "+1"},
            "mean_cv_mae": 0.2,
            "std_cv_mae": 0.01,
            "final_mae": 0.21,
            "final_rmse": 0.3,
            "final_smape": 9.0,
            "predict_ms_median": 2.0,
            "is_recommended": True,
            "failure_code": None,
            "fold_metrics": [
                {"fold_no": 1, "evaluation_rows": 10, "mae": 0.2, "rmse": 0.3, "smape": 8.0}
            ],
            "horizon_metrics": [
                {
                    "evaluation_scope": "final_test",
                    "horizon": 1,
                    "mae": 0.1,
                    "rmse": 0.2,
                    "smape": 7.0,
                }
            ],
        },
    )

    rows = list(
        csv.reader(StringIO(experiment_metrics_csv(_experiment(), comparison).decode("utf-8")))
    )

    assert tuple(rows[0]) == METRICS_CSV_COLUMNS
    assert [row[6] for row in rows[1:]] == ["summary", "fold", "horizon"]
    assert all(row[2].startswith("'=") for row in rows[1:])
    assert "\"alpha\":\"+1\"" in rows[1][5]


def test_json_exports_are_utf8_and_chart_ready() -> None:
    metrics = experiment_metrics_json(_experiment(), ()).decode("utf-8")
    chart = json.loads(forecast_chart_json(_forecast()).decode("utf-8"))
    manifest = json.loads(experiment_manifest_json(_experiment()).decode("utf-8"))

    assert "Експеримент формул" in metrics
    assert chart["schema"] == "forecast-chart-data/v1"
    assert chart["unit"] == "kWh"
    assert len(chart["series"]) == 24
    assert chart["series"][0]["horizon"] == 1
    assert manifest == {"schema": "experiment-result/v1", "status": "completed"}


def test_content_disposition_filename_removes_paths_and_header_controls() -> None:
    unsafe = "../../private\\folder/evil\r\nSet-Cookie: session=x.csv"
    filename = safe_download_filename(unsafe, fallback="export.csv")
    header = content_disposition(filename)

    assert "/" not in filename
    assert "\\" not in filename
    assert "\r" not in filename
    assert "\n" not in filename
    assert '"' not in filename
    assert "../" not in header
    assert "Set-Cookie:" not in header
    assert header.startswith('attachment; filename="')
