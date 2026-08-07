from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from energy_forecast.artifacts.models import ArtifactMetadata, ArtifactPurpose
from energy_forecast.errors import install_exception_handlers
from energy_forecast.exports.api import create_export_router
from energy_forecast.exports.models import (
    ExperimentExportFormat,
    ExportArtifactNotFoundError,
    ExportArtifactPurposeError,
    ExportArtifactUnavailableError,
    ExportDownload,
    ExportSourceFailedError,
    ForecastExportFormat,
)
from energy_forecast.exports.service import ExportService

_ARTIFACT_ID = UUID("11111111-1111-4111-8111-111111111111")
_FORBIDDEN_ID = UUID("22222222-2222-4222-8222-222222222222")
_UNAVAILABLE_ID = UUID("33333333-3333-4333-8333-333333333333")
_MISSING_ID = UUID("44444444-4444-4444-8444-444444444444")
_FAILED_EXPERIMENT_ID = UUID("55555555-5555-4555-8555-555555555555")


def _metadata() -> ArtifactMetadata:
    return ArtifactMetadata(
        id=_ARTIFACT_ID,
        purpose=ArtifactPurpose.FORECAST_EXPORT,
        storage_key="a" * 32 + ".csv",
        original_name="forecast.csv",
        media_type="text/csv; charset=utf-8",
        size_bytes=8,
        sha256="f" * 64,
        created_at=datetime.now(UTC),
    )


class _Exports:
    async def export_forecast(
        self,
        forecast_id: UUID,
        export_format: ForecastExportFormat,
    ) -> ArtifactMetadata:
        del forecast_id, export_format
        return _metadata()

    async def export_experiment(
        self,
        experiment_id: UUID,
        export_format: ExperimentExportFormat,
    ) -> ArtifactMetadata:
        del export_format
        if experiment_id == _FAILED_EXPERIMENT_ID:
            raise ExportSourceFailedError("failed")
        return _metadata()

    async def open_download(self, artifact_id: UUID) -> ExportDownload:
        if artifact_id == _FORBIDDEN_ID:
            raise ExportArtifactPurposeError("forbidden")
        if artifact_id == _UNAVAILABLE_ID:
            raise ExportArtifactUnavailableError("unavailable")
        if artifact_id == _MISSING_ID:
            raise ExportArtifactNotFoundError("missing")
        return ExportDownload(
            metadata=_metadata(),
            filename="../../evil\r\nHeader: value.csv",
            stream=BytesIO(b"a,b\n1,2\n"),
        )


def _app() -> FastAPI:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(create_export_router(cast(ExportService, _Exports())))
    return app


def test_download_stream_uses_safe_headers_and_never_exposes_storage_key() -> None:
    with TestClient(_app()) as client:
        created = client.post(
            f"/forecasts/{UUID(int=1)}/exports",
            json={"format": "csv"},
        )
        download = client.get(f"/artifacts/{_ARTIFACT_ID}/download")

    assert created.status_code == 201
    assert "storage_key" not in created.json()
    assert created.json()["download_url"] == f"/artifacts/{_ARTIFACT_ID}/download"
    assert download.status_code == 200
    assert download.content == b"a,b\n1,2\n"
    disposition = download.headers["content-disposition"]
    assert "\r" not in disposition
    assert "\n" not in disposition
    assert "../" not in disposition
    assert "\\" not in disposition
    assert "Header:" not in disposition


def test_download_failures_and_failed_source_use_problem_details() -> None:
    with TestClient(_app(), raise_server_exceptions=False) as client:
        forbidden = client.get(f"/artifacts/{_FORBIDDEN_ID}/download")
        unavailable = client.get(f"/artifacts/{_UNAVAILABLE_ID}/download")
        missing = client.get(f"/artifacts/{_MISSING_ID}/download")
        failed = client.post(
            f"/experiments/{_FAILED_EXPERIMENT_ID}/exports",
            json={"format": "manifest_json"},
        )

    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "export_artifact_forbidden"
    assert forbidden.headers["content-type"].startswith("application/problem+json")
    assert unavailable.status_code == 410
    assert unavailable.json()["code"] == "export_artifact_unavailable"
    assert missing.status_code == 404
    assert missing.json()["code"] == "export_artifact_not_found"
    assert failed.status_code == 409
    assert failed.json()["code"] == "export_source_failed"
