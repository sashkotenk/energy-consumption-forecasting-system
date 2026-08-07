"""REST endpoints for synchronous verified-bundle forecasts."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem
from energy_forecast.forecasting.models import (
    ForecastCompatibilityError,
    ForecastHistoryMissingError,
    ForecastModelUnavailableError,
    ForecastNotFoundError,
    ForecastOriginError,
    ForecastRequest,
)
from energy_forecast.forecasting.service import ForecastService
from energy_forecast.ml.registry import AlgorithmType

PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
_PROBLEM = {"model": Problem, "content": {PROBLEM_MEDIA_TYPE: {}}}


class ForecastCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_run_id: UUID
    dataset_version_id: UUID
    origin: datetime | None = None


class ForecastPointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    horizon: int
    target_time: datetime
    predicted_energy_kwh: float
    actual_energy_kwh: float | None


class ForecastResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_run_id: UUID
    dataset_version_id: UUID
    artifact_id: UUID
    bundle_sha256: str
    algorithm: AlgorithmType
    feature_schema_version: str
    origin: datetime
    timezone: str
    status: str
    total_energy_kwh: float
    points: tuple[ForecastPointResponse, ...]
    created_at: datetime
    completed_at: datetime


class ForecastPageResponse(BaseModel):
    items: tuple[ForecastResponse, ...]
    page: int
    page_size: int
    total: int


def create_forecast_router(service: ForecastService | None) -> APIRouter:
    router = APIRouter(prefix="/forecasts", tags=["Forecasts"])

    @router.post(
        "",
        status_code=HTTPStatus.CREATED,
        response_model=ForecastResponse,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM,
            HTTPStatus.CONFLICT: _PROBLEM,
            HTTPStatus.UNPROCESSABLE_ENTITY: _PROBLEM,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM,
        },
    )
    async def create_forecast(request: ForecastCreate) -> ForecastResponse:
        try:
            record = await _require(service).create(
                ForecastRequest(
                    model_run_id=request.model_run_id,
                    dataset_version_id=request.dataset_version_id,
                    origin=request.origin,
                )
            )
        except ForecastNotFoundError as error:
            raise _not_found("forecast_source_not_found") from error
        except ForecastModelUnavailableError as error:
            raise _problem(
                HTTPStatus.CONFLICT,
                "forecast_model_unavailable",
                "Модель або версія даних ще не готова для прогнозу.",
            ) from error
        except ForecastCompatibilityError as error:
            raise _problem(
                HTTPStatus.CONFLICT,
                "forecast_bundle_incompatible",
                "Модель несумісна з вибраною версією даних або схемою ознак.",
            ) from error
        except ForecastOriginError as error:
            raise _problem(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "forecast_origin_invalid",
                "Час прогнозу має бути межею збереженої завершеної години з часовим поясом.",
            ) from error
        except ForecastHistoryMissingError as error:
            raise _problem(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "forecast_history_missing",
                "Недостатньо безперервної історії для lag і rolling ознак. "
                "Перевірте щонайменше попередні 168 годин.",
            ) from error
        return ForecastResponse.model_validate(record)

    @router.get("", response_model=ForecastPageResponse)
    async def list_forecasts(
        page: PageNumber = 1, page_size: PageSize = 20
    ) -> ForecastPageResponse:
        result = await _require(service).list(page=page, page_size=page_size)
        return ForecastPageResponse(
            items=tuple(ForecastResponse.model_validate(item) for item in result.items),
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        )

    @router.get(
        "/{forecastId}",
        response_model=ForecastResponse,
        responses={HTTPStatus.NOT_FOUND: _PROBLEM},
    )
    async def get_forecast(forecastId: UUID) -> ForecastResponse:
        try:
            return ForecastResponse.model_validate(await _require(service).get(forecastId))
        except ForecastNotFoundError as error:
            raise _not_found("forecast_not_found") from error

    return router


def _require(service: ForecastService | None) -> ForecastService:
    if service is None:
        raise ApiProblem(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="forecasts_unavailable",
            title="Сервіс прогнозів недоступний",
            detail="Налаштуйте підключення до бази даних і сховища артефактів.",
        )
    return service


def _not_found(code: str) -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.NOT_FOUND,
        code=code,
        title="Дані для прогнозу не знайдено",
        detail="Запитаний прогноз, модель або версія набору даних не існує.",
    )


def _problem(status: int, code: str, detail: str) -> ApiProblem:
    return ApiProblem(
        status=status,
        code=code,
        title="Не вдалося створити прогноз",
        detail=detail,
    )
