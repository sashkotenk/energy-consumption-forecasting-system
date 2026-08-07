"""REST endpoints for dataset metadata and upload staging."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from energy_forecast.datasets.models import (
    DatasetChanges,
    DatasetImportRecord,
    DatasetInUseError,
    DatasetNotFoundError,
    DatasetPage,
    DatasetRecord,
    DatasetSourceConflictError,
    DatasetUploadError,
    ImportProfile,
    UploadTooLargeError,
)
from energy_forecast.datasets.service import DatasetService
from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem

PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _safe_text(value, field="name", allow_empty=False)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value, field="description", allow_empty=True)


class DatasetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_change(self) -> DatasetUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Dataset name cannot be null")
        return self

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value, field="name", allow_empty=False)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return None if value is None else _safe_text(value, field="description", allow_empty=True)


class DatasetResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    version_count: int
    created_at: datetime
    updated_at: datetime


class DatasetPageResponse(BaseModel):
    items: tuple[DatasetResponse, ...]
    page: int
    page_size: int
    total: int


class DatasetImportAccepted(BaseModel):
    import_id: UUID
    job_id: UUID
    status: Literal["queued"]


class DatasetImportResponse(BaseModel):
    id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    job_id: UUID
    import_profile: ImportProfile
    status: str
    import_options: dict[str, Any]
    detected_format: dict[str, Any]
    created_at: datetime


_PROBLEM_RESPONSE = {
    "model": Problem,
    "content": {PROBLEM_MEDIA_TYPE: {}},
}


def create_dataset_router(service: DatasetService | None) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/datasets",
        tags=["Datasets"],
        operation_id="listDatasets",
        response_model=DatasetPageResponse,
        responses={HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE},
    )
    async def list_datasets(page: PageNumber = 1, page_size: PageSize = 20) -> DatasetPageResponse:
        result = await _require_service(service).list(page=page, page_size=page_size)
        return _to_page_response(result)

    @router.post(
        "/datasets",
        tags=["Datasets"],
        operation_id="createDataset",
        response_model=DatasetResponse,
        status_code=HTTPStatus.CREATED,
        responses={HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE},
    )
    async def create_dataset(request: DatasetCreate) -> DatasetResponse:
        dataset = await _require_service(service).create(
            name=request.name,
            description=request.description,
        )
        return _to_dataset_response(dataset)

    @router.get(
        "/datasets/{datasetId}",
        tags=["Datasets"],
        operation_id="getDataset",
        response_model=DatasetResponse,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
    )
    async def get_dataset(datasetId: UUID) -> DatasetResponse:
        try:
            dataset = await _require_service(service).get(datasetId)
        except DatasetNotFoundError as error:
            raise _not_found("dataset_not_found", "Набір даних не знайдено.") from error
        return _to_dataset_response(dataset)

    @router.patch(
        "/datasets/{datasetId}",
        tags=["Datasets"],
        operation_id="updateDataset",
        response_model=DatasetResponse,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
    )
    async def update_dataset(datasetId: UUID, request: DatasetUpdate) -> DatasetResponse:
        changes = DatasetChanges(
            set_name="name" in request.model_fields_set,
            name=request.name,
            set_description="description" in request.model_fields_set,
            description=request.description,
        )
        try:
            dataset = await _require_service(service).update(datasetId, changes)
        except DatasetNotFoundError as error:
            raise _not_found("dataset_not_found", "Набір даних не знайдено.") from error
        return _to_dataset_response(dataset)

    @router.delete(
        "/datasets/{datasetId}",
        tags=["Datasets"],
        operation_id="deleteDataset",
        status_code=HTTPStatus.NO_CONTENT,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM_RESPONSE,
            HTTPStatus.CONFLICT: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
    )
    async def delete_dataset(datasetId: UUID) -> Response:
        try:
            await _require_service(service).delete(datasetId)
        except DatasetNotFoundError as error:
            raise _not_found("dataset_not_found", "Набір даних не знайдено.") from error
        except DatasetInUseError as error:
            raise _conflict(
                "dataset_in_use",
                "Набір даних має незмінні імпорти або версії та не може бути видалений.",
            ) from error
        return Response(status_code=HTTPStatus.NO_CONTENT)

    @router.post(
        "/datasets/{datasetId}/imports",
        tags=["Imports"],
        operation_id="createDatasetImport",
        response_model=DatasetImportAccepted,
        status_code=HTTPStatus.ACCEPTED,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM_RESPONSE,
            HTTPStatus.CONFLICT: _PROBLEM_RESPONSE,
            HTTPStatus.REQUEST_ENTITY_TOO_LARGE: _PROBLEM_RESPONSE,
            HTTPStatus.UNPROCESSABLE_ENTITY: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
    )
    async def create_dataset_import(
        datasetId: UUID,
        file: Annotated[UploadFile, File()],
        import_profile: Annotated[ImportProfile, Form()],
        delimiter: Annotated[str | None, Form(min_length=1, max_length=1)] = None,
        decimal_separator: Annotated[Literal[".", ","] | None, Form()] = None,
        timestamp_column: Annotated[str | None, Form(max_length=160)] = None,
        timestamp_format: Annotated[str | None, Form(max_length=160)] = None,
        timestamp_semantics: Annotated[
            Literal["interval_start", "interval_end"] | None, Form()
        ] = None,
        timezone: Annotated[str | None, Form(max_length=80)] = None,
        energy_column: Annotated[str | None, Form(max_length=160)] = None,
        power_column: Annotated[str | None, Form(max_length=160)] = None,
        unit: Annotated[Literal["kwh", "wh", "kw", "w"] | None, Form()] = None,
        duplicate_policy: Annotated[
            Literal["reject", "keep_first", "keep_last", "mean"] | None, Form()
        ] = None,
    ) -> DatasetImportAccepted:
        options = {
            key: value
            for key, value in {
                "delimiter": delimiter,
                "decimal_separator": decimal_separator,
                "timestamp_column": timestamp_column,
                "timestamp_format": timestamp_format,
                "timestamp_semantics": timestamp_semantics,
                "timezone": timezone,
                "energy_column": energy_column,
                "power_column": power_column,
                "unit": unit,
                "duplicate_policy": duplicate_policy,
            }.items()
            if value is not None
        }
        try:
            staged = await _require_service(service).stage_import(
                dataset_id=datasetId,
                stream=file.file,
                original_name=file.filename,
                import_profile=import_profile,
                import_options=options,
            )
        except DatasetNotFoundError as error:
            raise _not_found("dataset_not_found", "Набір даних не знайдено.") from error
        except DatasetSourceConflictError as error:
            raise _conflict(
                "dataset_source_conflict",
                "Цей сирий файл уже завантажено до набору даних.",
            ) from error
        except UploadTooLargeError as error:
            raise ApiProblem(
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                code=error.code,
                title="Файл завеликий",
                detail=error.detail,
            ) from error
        except DatasetUploadError as error:
            raise ApiProblem(
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
                code=error.code,
                title="Неприпустимий файл даних",
                detail=error.detail,
            ) from error
        finally:
            await file.close()
        return DatasetImportAccepted(
            import_id=staged.import_record.id,
            job_id=staged.import_record.job_id,
            status="queued",
        )

    @router.get(
        "/dataset-imports/{importId}",
        tags=["Imports"],
        operation_id="getDatasetImport",
        response_model=DatasetImportResponse,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
    )
    async def get_dataset_import(importId: UUID) -> DatasetImportResponse:
        try:
            import_record = await _require_service(service).get_import(importId)
        except DatasetNotFoundError as error:
            raise _not_found(
                "dataset_import_not_found", "Імпорт набору даних не знайдено."
            ) from error
        return _to_import_response(import_record)

    return router


def _require_service(service: DatasetService | None) -> DatasetService:
    if service is None:
        raise ApiProblem(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="dataset_service_unavailable",
            title="Сервіс наборів даних недоступний",
            detail="З'єднання з базою даних або сховищем артефактів не налаштовано.",
        )
    return service


def _safe_text(value: str, *, field: str, allow_empty: bool) -> str:
    normalized = value.strip()
    if any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{field} contains control characters")
    if not normalized and not allow_empty:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _not_found(code: str, detail: str) -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.NOT_FOUND,
        code=code,
        title="Ресурс не знайдено",
        detail=detail,
    )


def _conflict(code: str, detail: str) -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.CONFLICT,
        code=code,
        title="Конфлікт стану набору даних",
        detail=detail,
    )


def _to_dataset_response(dataset: DatasetRecord) -> DatasetResponse:
    return DatasetResponse(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        version_count=dataset.version_count,
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


def _to_page_response(page: DatasetPage) -> DatasetPageResponse:
    return DatasetPageResponse(
        items=tuple(_to_dataset_response(item) for item in page.items),
        page=page.page,
        page_size=page.page_size,
        total=page.total,
    )


def _to_import_response(import_record: DatasetImportRecord) -> DatasetImportResponse:
    return DatasetImportResponse(
        id=import_record.id,
        dataset_id=import_record.dataset_id,
        dataset_version_id=import_record.dataset_version_id,
        job_id=import_record.job_id,
        import_profile=import_record.import_profile,
        status=import_record.status.value,
        import_options=import_record.import_options,
        detected_format=import_record.detected_format,
        created_at=import_record.created_at,
    )
