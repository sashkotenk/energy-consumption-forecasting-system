"""REST endpoints for bounded export creation and controlled artifact downloads."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from http import HTTPStatus
from typing import BinaryIO
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from energy_forecast.artifacts.models import ArtifactMetadata, ArtifactPurpose
from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem
from energy_forecast.exports.models import (
    ExperimentExportFormat,
    ExportArtifactNotFoundError,
    ExportArtifactPurposeError,
    ExportArtifactUnavailableError,
    ExportSourceFailedError,
    ExportSourceNotFoundError,
    ExportSourceUnavailableError,
    ForecastExportFormat,
)
from energy_forecast.exports.serialization import content_disposition, safe_download_filename
from energy_forecast.exports.service import ExportService

_PROBLEM = {"model": Problem, "content": {PROBLEM_MEDIA_TYPE: {}}}
_DOWNLOAD_RESPONSE = {
    "description": "Controlled export artifact stream",
    "content": {
        "application/octet-stream": {
            "schema": {"type": "string", "format": "binary"},
        }
    },
}


class ForecastExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: ForecastExportFormat


class ExperimentExportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: ExperimentExportFormat


class ExportArtifactResponse(BaseModel):
    id: UUID
    purpose: ArtifactPurpose
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    created_at: datetime
    download_url: str


def create_export_router(service: ExportService | None) -> APIRouter:
    router = APIRouter(tags=["Exports"])

    @router.post(
        "/forecasts/{forecastId}/exports",
        status_code=HTTPStatus.CREATED,
        response_model=ExportArtifactResponse,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM,
            HTTPStatus.CONFLICT: _PROBLEM,
            HTTPStatus.UNPROCESSABLE_ENTITY: _PROBLEM,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM,
        },
    )
    async def create_forecast_export(
        forecastId: UUID,
        request: ForecastExportCreate,
    ) -> ExportArtifactResponse:
        try:
            metadata = await _require(service).export_forecast(forecastId, request.format)
        except ExportSourceNotFoundError as error:
            raise _source_not_found() from error
        except ExportSourceUnavailableError as error:
            raise _source_not_ready() from error
        return _artifact_response(metadata)

    @router.post(
        "/experiments/{experimentId}/exports",
        status_code=HTTPStatus.CREATED,
        response_model=ExportArtifactResponse,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM,
            HTTPStatus.CONFLICT: _PROBLEM,
            HTTPStatus.UNPROCESSABLE_ENTITY: _PROBLEM,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM,
        },
    )
    async def create_experiment_export(
        experimentId: UUID,
        request: ExperimentExportCreate,
    ) -> ExportArtifactResponse:
        try:
            metadata = await _require(service).export_experiment(experimentId, request.format)
        except ExportSourceNotFoundError as error:
            raise _source_not_found() from error
        except ExportSourceFailedError as error:
            raise ApiProblem(
                status=HTTPStatus.CONFLICT,
                code="export_source_failed",
                title="Результат експорту недоступний",
                detail=(
                    "Експеримент завершився помилкою і не має "
                    "успішного результату для експорту."
                ),
            ) from error
        except ExportSourceUnavailableError as error:
            raise _source_not_ready() from error
        return _artifact_response(metadata)

    @router.get(
        "/artifacts/{artifactId}/download",
        response_class=StreamingResponse,
        responses={
            HTTPStatus.OK: _DOWNLOAD_RESPONSE,
            HTTPStatus.FORBIDDEN: _PROBLEM,
            HTTPStatus.NOT_FOUND: _PROBLEM,
            HTTPStatus.GONE: _PROBLEM,
            HTTPStatus.UNPROCESSABLE_ENTITY: _PROBLEM,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM,
        },
    )
    async def download_export(artifactId: UUID) -> StreamingResponse:
        try:
            download = await _require(service).open_download(artifactId)
        except ExportArtifactNotFoundError as error:
            raise ApiProblem(
                status=HTTPStatus.NOT_FOUND,
                code="export_artifact_not_found",
                title="Файл експорту не знайдено",
                detail=(
                    "Запитаний файл експорту не існує "
                    "або вже видалений."
                ),
            ) from error
        except ExportArtifactPurposeError as error:
            raise ApiProblem(
                status=HTTPStatus.FORBIDDEN,
                code="export_artifact_forbidden",
                title="Завантаження артефакту заборонено",
                detail=(
                    "Цей тип артефакту не призначений для "
                    "завантаження через endpoint експорту."
                ),
            ) from error
        except ExportArtifactUnavailableError as error:
            raise ApiProblem(
                status=HTTPStatus.GONE,
                code="export_artifact_unavailable",
                title="Файл експорту недоступний",
                detail=(
                    "Метадані експорту існують, але збережений "
                    "файл відсутній або недоступний."
                ),
            ) from error

        metadata = download.metadata
        return StreamingResponse(
            _stream_and_close(download.stream),
            media_type=metadata.media_type,
            headers={
                "Content-Disposition": content_disposition(download.filename),
                "Content-Length": str(metadata.size_bytes),
                "X-Content-SHA256": metadata.sha256,
            },
        )

    return router


def _artifact_response(metadata: ArtifactMetadata) -> ExportArtifactResponse:
    filename = safe_download_filename(
        metadata.original_name,
        fallback=f"export-{metadata.id}",
    )
    return ExportArtifactResponse(
        id=metadata.id,
        purpose=metadata.purpose,
        filename=filename,
        media_type=metadata.media_type,
        size_bytes=metadata.size_bytes,
        sha256=metadata.sha256,
        created_at=metadata.created_at,
        download_url=f"/artifacts/{metadata.id}/download",
    )


def _stream_and_close(stream: BinaryIO) -> Iterator[bytes]:
    try:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                return
            yield chunk
    finally:
        stream.close()


def _require(service: ExportService | None) -> ExportService:
    if service is None:
        raise ApiProblem(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="exports_unavailable",
            title="Сервіс експорту недоступний",
            detail=(
                "Налаштуйте підключення до бази даних і "
                "сховища артефактів."
            ),
        )
    return service


def _source_not_found() -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.NOT_FOUND,
        code="export_source_not_found",
        title="Джерело експорту не знайдено",
        detail="Запитаний прогноз або експеримент не існує.",
    )


def _source_not_ready() -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.CONFLICT,
        code="export_source_not_ready",
        title="Результат експорту ще недоступний",
        detail=(
            "Експорт можна створити лише з успішно "
            "завершеного ресурсу."
        ),
    )
