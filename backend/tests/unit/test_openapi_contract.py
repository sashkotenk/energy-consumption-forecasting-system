"""Contract guards for the authoritative runtime OpenAPI document."""

from __future__ import annotations

from typing import Any

from energy_forecast.api import create_app
from energy_forecast.config import Service, Settings

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
_EXPECTED_OPERATION_IDS = {
    "getLiveness",
    "getReadiness",
    "enqueueJob",
    "getJob",
    "cancelJob",
    "retryJob",
    "listDatasets",
    "createDataset",
    "getDataset",
    "updateDataset",
    "deleteDataset",
    "createDatasetImport",
    "getDatasetImport",
    "getDataQualityReport",
    "createTransformation",
    "getAnalyticsSummary",
    "getEnergySeries",
    "getHourlyProfile",
    "getWeekdayProfile",
    "getEnergyHeatmap",
    "getEnergyDistribution",
    "listAlgorithms",
    "createExperiment",
    "listExperiments",
    "getExperiment",
    "compareExperiment",
    "cancelExperiment",
    "createForecast",
    "listForecasts",
    "getForecast",
    "createForecastExport",
    "createExperimentExport",
    "downloadExportArtifact",
}


def _schema() -> dict[str, Any]:
    return create_app(settings=Settings(service=Service.API, database_url=None)).openapi()


def _operations(schema: dict[str, Any]) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method in _HTTP_METHODS:
                operations.append(operation)
    return operations


def test_runtime_openapi_is_31_with_stable_unique_operation_ids() -> None:
    schema = _schema()
    assert schema["openapi"] == "3.1.0"

    operation_ids = [operation.get("operationId") for operation in _operations(schema)]
    assert all(isinstance(operation_id, str) and operation_id for operation_id in operation_ids)
    assert len(operation_ids) == len(set(operation_ids))
    assert set(operation_ids) == _EXPECTED_OPERATION_IDS


def test_problem_details_and_job_enums_are_typed() -> None:
    components = _schema()["components"]["schemas"]

    problem = components["Problem"]
    assert set(problem["required"]) == {"type", "title", "status", "code", "request_id"}
    assert problem["properties"]["detail"]["anyOf"][1]["type"] == "null"
    assert problem["properties"]["instance"]["anyOf"][1]["type"] == "null"

    assert set(components["JobStatus"]["enum"]) == {
        "queued",
        "running",
        "cancel_requested",
        "cancelled",
        "succeeded",
        "failed",
        "stale",
    }
    assert set(components["JobType"]["enum"]) == {
        "dataset_import",
        "data_validation",
        "data_transformation",
        "weather_import",
        "experiment",
        "forecast",
        "export",
    }


def test_problem_responses_use_problem_json_media_type() -> None:
    schema = _schema()
    inspected = 0
    for path_item in schema["paths"].values():
        for method, operation in path_item.items():
            if method not in _HTTP_METHODS:
                continue
            for status, response in operation.get("responses", {}).items():
                if not str(status).startswith(("4", "5")):
                    continue
                content = response.get("content", {})
                if "application/problem+json" in content:
                    inspected += 1
                    reference = content["application/problem+json"].get("schema", {}).get("$ref")
                    assert reference == "#/components/schemas/Problem"
    assert inspected > 0
