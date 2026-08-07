"""REST contract for experiment staging, inspection, comparison, and cancellation."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem
from energy_forecast.experiments.models import (
    DatasetVersionNotTrainableError,
    ExperimentConfigurationError,
    ExperimentDefinition,
    ExperimentNotCancellableError,
    ExperimentNotFoundError,
    ExperimentRecord,
    ExperimentStatus,
    SensitivityMode,
    WeatherMode,
)
from energy_forecast.experiments.service import ExperimentService
from energy_forecast.ml.registry import AlgorithmRegistry, AlgorithmType

PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
_PROBLEM = {"model": Problem, "content": {PROBLEM_MEDIA_TYPE: {}}}


class AlgorithmResponse(BaseModel):
    algorithm: AlgorithmType
    display_name: str
    implementation_version: str
    supports_weather: bool
    default_search_space: dict[str, tuple[Any, ...]]


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_version_id: UUID
    name: str = Field(min_length=1, max_length=160)
    algorithms: tuple[AlgorithmType, ...] = Field(min_length=1)
    weather_mode: WeatherMode = WeatherMode.WITHOUT_WEATHER
    sensitivity_mode: SensitivityMode = SensitivityMode.COMPLETE_ONLY

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Experiment name cannot be blank")
        return normalized

    @field_validator("algorithms")
    @classmethod
    def unique_algorithms(cls, value: tuple[AlgorithmType, ...]) -> tuple[AlgorithmType, ...]:
        if len(set(value)) != len(value):
            raise ValueError("Algorithms must be unique")
        return value


class ExperimentAccepted(BaseModel):
    experiment_id: UUID
    job_id: UUID
    status: ExperimentStatus


class ExperimentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_version_id: UUID
    job_id: UUID
    name: str
    status: ExperimentStatus
    weather_mode: WeatherMode
    sensitivity_mode: SensitivityMode
    algorithms: tuple[AlgorithmType, ...]
    result_manifest: dict[str, Any] | None
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ExperimentPageResponse(BaseModel):
    items: tuple[ExperimentResponse, ...]
    page: int
    page_size: int
    total: int


class ComparisonResponse(BaseModel):
    experiment_id: UUID
    models: tuple[dict[str, Any], ...]


def create_experiment_router(service: ExperimentService | None) -> APIRouter:
    router = APIRouter()

    @router.get("/algorithms", tags=["Experiments"], response_model=tuple[AlgorithmResponse, ...])
    async def list_algorithms() -> tuple[AlgorithmResponse, ...]:
        return tuple(
            AlgorithmResponse(
                algorithm=item.algorithm,
                display_name=item.display_name,
                implementation_version=item.implementation_version,
                supports_weather=item.supports_weather,
                default_search_space=dict(item.default_search_space),
            )
            for item in AlgorithmRegistry().list()
        )

    @router.post(
        "/experiments",
        tags=["Experiments"],
        status_code=HTTPStatus.ACCEPTED,
        response_model=ExperimentAccepted,
        responses={
            HTTPStatus.CONFLICT: _PROBLEM,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM,
        },
    )
    async def create_experiment(request: ExperimentCreate) -> ExperimentAccepted:
        try:
            staged = await _require(service).stage(
                ExperimentDefinition(
                    dataset_version_id=request.dataset_version_id,
                    name=request.name,
                    algorithms=request.algorithms,
                    weather_mode=request.weather_mode,
                    sensitivity_mode=request.sensitivity_mode,
                )
            )
        except DatasetVersionNotTrainableError as error:
            raise _conflict(
                "dataset_version_not_trainable",
                "Версія набору даних ще не готова для навчання.",
            ) from error
        except ExperimentConfigurationError as error:
            raise _conflict(
                "experiment_mode_unavailable",
                "Режим W1 потребує погодних даних і поки недоступний для запуску.",
            ) from error
        return ExperimentAccepted(
            experiment_id=staged.experiment_id, job_id=staged.job_id, status=staged.status
        )

    @router.get("/experiments", tags=["Experiments"], response_model=ExperimentPageResponse)
    async def list_experiments(
        page: PageNumber = 1, page_size: PageSize = 20
    ) -> ExperimentPageResponse:
        result = await _require(service).list(page=page, page_size=page_size)
        return ExperimentPageResponse(
            items=tuple(_response(item) for item in result.items),
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        )

    @router.get(
        "/experiments/{experimentId}",
        tags=["Experiments"],
        response_model=ExperimentResponse,
        responses={HTTPStatus.NOT_FOUND: _PROBLEM},
    )
    async def get_experiment(experimentId: UUID) -> ExperimentResponse:
        try:
            return _response(await _require(service).get(experimentId))
        except ExperimentNotFoundError as error:
            raise _not_found() from error

    @router.get(
        "/experiments/{experimentId}/comparison",
        tags=["Experiments"],
        response_model=ComparisonResponse,
        responses={HTTPStatus.NOT_FOUND: _PROBLEM},
    )
    async def compare_experiment(experimentId: UUID) -> ComparisonResponse:
        try:
            models = await _require(service).comparison(experimentId)
        except ExperimentNotFoundError as error:
            raise _not_found() from error
        return ComparisonResponse(experiment_id=experimentId, models=models)

    @router.post(
        "/experiments/{experimentId}/cancel",
        tags=["Experiments"],
        response_model=ExperimentResponse,
        responses={HTTPStatus.NOT_FOUND: _PROBLEM, HTTPStatus.CONFLICT: _PROBLEM},
    )
    async def cancel_experiment(experimentId: UUID) -> ExperimentResponse:
        try:
            return _response(await _require(service).cancel(experimentId))
        except ExperimentNotFoundError as error:
            raise _not_found() from error
        except ExperimentNotCancellableError as error:
            raise _conflict(
                "experiment_not_cancellable",
                "Експеримент уже завершився або не може бути скасований.",
            ) from error

    return router


def _response(record: ExperimentRecord) -> ExperimentResponse:
    return ExperimentResponse.model_validate(record)


def _require(service: ExperimentService | None) -> ExperimentService:
    if service is None:
        raise ApiProblem(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="experiments_unavailable",
            title="Сервіс експериментів недоступний",
            detail="Налаштуйте підключення до бази даних.",
        )
    return service


def _not_found() -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.NOT_FOUND,
        code="experiment_not_found",
        title="Експеримент не знайдено",
        detail="Запитаний експеримент не існує.",
    )


def _conflict(code: str, detail: str) -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.CONFLICT,
        code=code,
        title="Експеримент не можна запустити",
        detail=detail,
    )
