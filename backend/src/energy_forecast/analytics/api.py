"""Bounded analytics REST endpoints with explicit units and timezone metadata."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from energy_forecast.analytics.models import (
    AnalyticsContext,
    AnalyticsError,
    AnalyticsRange,
    AnalyticsRangeError,
    AnalyticsVersionNotFoundError,
    AnalyticsVersionNotReadyError,
    DistributionBin,
    HeatmapPoint,
    ProfilePoint,
    SeriesPoint,
    SeriesResolution,
    SummaryValues,
)
from energy_forecast.analytics.service import AnalyticsService
from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem

RangeStart = Annotated[datetime, Query(alias="from")]
RangeEnd = Annotated[datetime, Query(alias="to")]
MaxPoints = Annotated[int, Query(ge=100, le=10_000)]
BinCount = Annotated[int, Query(ge=5, le=100)]


class AnalyticsResponseBase(BaseModel):
    dataset_version_id: UUID
    from_: datetime = Field(serialization_alias="from")
    to: datetime
    timezone: str
    unit: Literal["kWh"] = "kWh"


class AnalyticsSummaryResponse(AnalyticsResponseBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "dataset_version_id": "d8f732d9-cb6b-4f87-bb4e-c450f5953750",
                "from": "2026-01-01T00:00:00Z",
                "to": "2026-01-02T00:00:00Z",
                "timezone": "Europe/Kyiv",
                "unit": "kWh",
                "expected_hours": 24,
                "stored_hours": 24,
                "energy_value_count": 23,
                "absent_hours": 0,
                "missing_energy_hours": 1,
                "mean_energy_kwh": 1.2,
                "median_energy_kwh": 1.1,
                "min_energy_kwh": 0.4,
                "max_energy_kwh": 2.8,
                "total_energy_kwh": 27.6,
                "mean_coverage_ratio": 0.98,
                "status_counts": {"complete": 23, "invalid_missing": 1},
            }
        }
    )

    expected_hours: int
    stored_hours: int
    energy_value_count: int
    absent_hours: int
    missing_energy_hours: int
    mean_energy_kwh: float | None
    median_energy_kwh: float | None
    min_energy_kwh: float | None
    max_energy_kwh: float | None
    total_energy_kwh: float | None
    mean_coverage_ratio: float | None
    status_counts: dict[str, int]


class EnergyPointResponse(BaseModel):
    timestamp: datetime
    energy_kwh: float | None
    mean_coverage_ratio: float
    quality_status: str
    sample_count: int


class EnergySeriesResponse(AnalyticsResponseBase):
    requested_resolution: SeriesResolution
    bucket_seconds: int
    downsampled: bool
    max_points: int
    points: tuple[EnergyPointResponse, ...]


class ProfilePointResponse(BaseModel):
    key: int
    label: str
    mean_energy_kwh: float
    total_energy_kwh: float
    mean_coverage_ratio: float
    sample_count: int


class ProfileResponse(AnalyticsResponseBase):
    profile: Literal["hour_of_day", "iso_weekday"]
    points: tuple[ProfilePointResponse, ...]


class HeatmapPointResponse(BaseModel):
    iso_weekday: int
    hour: int
    mean_energy_kwh: float
    mean_coverage_ratio: float
    sample_count: int


class HeatmapResponse(AnalyticsResponseBase):
    dimensions: tuple[Literal["iso_weekday", "hour"], Literal["iso_weekday", "hour"]] = (
        "iso_weekday",
        "hour",
    )
    points: tuple[HeatmapPointResponse, ...]


class DistributionBinResponse(BaseModel):
    bin_index: int
    lower_kwh: float
    upper_kwh: float
    sample_count: int


class DistributionResponse(AnalyticsResponseBase):
    requested_bins: int
    bins: tuple[DistributionBinResponse, ...]


_PROBLEM_RESPONSE = {"model": Problem, "content": {PROBLEM_MEDIA_TYPE: {}}}
_WEEKDAY_LABELS = ("", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def create_analytics_router(service: AnalyticsService | None) -> APIRouter:
    router = APIRouter(prefix="/dataset-versions/{versionId}/analytics", tags=["Analytics"])

    @router.get(
        "/summary",
        operation_id="getAnalyticsSummary",
        response_model=AnalyticsSummaryResponse,
        response_model_by_alias=True,
        responses=_RESPONSES,
    )
    async def get_summary(
        versionId: UUID, from_: RangeStart, to: RangeEnd
    ) -> AnalyticsSummaryResponse:
        try:
            context, time_range, values = await _require_service(service).summary(
                versionId, from_, to
            )
        except AnalyticsError as error:
            _raise_problem(error)
        return _summary_response(context, time_range, values)

    @router.get(
        "/series",
        operation_id="getEnergySeries",
        response_model=EnergySeriesResponse,
        response_model_by_alias=True,
        responses=_RESPONSES,
    )
    async def get_series(
        versionId: UUID,
        from_: RangeStart,
        to: RangeEnd,
        resolution: SeriesResolution = SeriesResolution.HOUR,
        max_points: MaxPoints = 2_000,
    ) -> EnergySeriesResponse:
        try:
            context, time_range, bucket_seconds, points = await _require_service(service).series(
                versionId,
                from_,
                to,
                resolution=resolution,
                max_points=max_points,
            )
        except AnalyticsError as error:
            _raise_problem(error)
        return EnergySeriesResponse(
            **_metadata(context, time_range),
            requested_resolution=resolution,
            bucket_seconds=bucket_seconds,
            downsampled=bucket_seconds > _resolution_seconds(resolution),
            max_points=max_points,
            points=tuple(_series_point(point) for point in points),
        )

    @router.get(
        "/hourly-profile",
        operation_id="getHourlyProfile",
        response_model=ProfileResponse,
        response_model_by_alias=True,
        responses=_RESPONSES,
    )
    async def get_hourly_profile(
        versionId: UUID, from_: RangeStart, to: RangeEnd
    ) -> ProfileResponse:
        try:
            context, time_range, points = await _require_service(service).hourly_profile(
                versionId, from_, to
            )
        except AnalyticsError as error:
            _raise_problem(error)
        return ProfileResponse(
            **_metadata(context, time_range),
            profile="hour_of_day",
            points=tuple(_profile_point(point, str(point.key).zfill(2)) for point in points),
        )

    @router.get(
        "/weekday-profile",
        operation_id="getWeekdayProfile",
        response_model=ProfileResponse,
        response_model_by_alias=True,
        responses=_RESPONSES,
    )
    async def get_weekday_profile(
        versionId: UUID, from_: RangeStart, to: RangeEnd
    ) -> ProfileResponse:
        try:
            context, time_range, points = await _require_service(service).weekday_profile(
                versionId, from_, to
            )
        except AnalyticsError as error:
            _raise_problem(error)
        return ProfileResponse(
            **_metadata(context, time_range),
            profile="iso_weekday",
            points=tuple(_profile_point(point, _WEEKDAY_LABELS[point.key]) for point in points),
        )

    @router.get(
        "/heatmap",
        operation_id="getEnergyHeatmap",
        response_model=HeatmapResponse,
        response_model_by_alias=True,
        responses=_RESPONSES,
    )
    async def get_heatmap(versionId: UUID, from_: RangeStart, to: RangeEnd) -> HeatmapResponse:
        try:
            context, time_range, points = await _require_service(service).heatmap(
                versionId, from_, to
            )
        except AnalyticsError as error:
            _raise_problem(error)
        return HeatmapResponse(
            **_metadata(context, time_range),
            points=tuple(_heatmap_point(point) for point in points),
        )

    @router.get(
        "/distribution",
        operation_id="getEnergyDistribution",
        response_model=DistributionResponse,
        response_model_by_alias=True,
        responses=_RESPONSES,
    )
    async def get_distribution(
        versionId: UUID,
        from_: RangeStart,
        to: RangeEnd,
        bins: BinCount = 20,
    ) -> DistributionResponse:
        try:
            context, time_range, values = await _require_service(service).distribution(
                versionId, from_, to, bins=bins
            )
        except AnalyticsError as error:
            _raise_problem(error)
        return DistributionResponse(
            **_metadata(context, time_range),
            requested_bins=bins,
            bins=tuple(_distribution_bin(value) for value in values),
        )

    return router


_RESPONSES: dict[int | str, dict[str, Any]] = {
    int(HTTPStatus.NOT_FOUND): _PROBLEM_RESPONSE,
    int(HTTPStatus.CONFLICT): _PROBLEM_RESPONSE,
    int(HTTPStatus.UNPROCESSABLE_ENTITY): _PROBLEM_RESPONSE,
    int(HTTPStatus.SERVICE_UNAVAILABLE): _PROBLEM_RESPONSE,
}


def _require_service(service: AnalyticsService | None) -> AnalyticsService:
    if service is None:
        raise ApiProblem(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="analytics_service_unavailable",
            title="Сервіс аналітики недоступний",
            detail="З'єднання з базою даних не налаштовано.",
        )
    return service


def _raise_problem(error: AnalyticsError) -> None:
    if isinstance(error, AnalyticsVersionNotFoundError):
        raise ApiProblem(
            status=HTTPStatus.NOT_FOUND,
            code="dataset_version_not_found",
            title="Версію набору даних не знайдено",
            detail="Вказана версія набору даних не існує.",
        ) from error
    if isinstance(error, AnalyticsVersionNotReadyError):
        raise ApiProblem(
            status=HTTPStatus.CONFLICT,
            code="analytics_not_ready",
            title="Аналітика ще недоступна",
            detail="Для цієї версії ще не сформовано погодинні дані.",
        ) from error
    if isinstance(error, AnalyticsRangeError):
        raise ApiProblem(
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
            code="analytics_range_invalid",
            title="Некоректний часовий діапазон",
            detail="Початок має передувати завершенню, а період не може перевищувати п'ять років.",
        ) from error
    raise error


def _metadata(context: AnalyticsContext, time_range: AnalyticsRange) -> dict[str, Any]:
    return {
        "dataset_version_id": context.dataset_version_id,
        "from_": time_range.start,
        "to": time_range.end,
        "timezone": context.timezone,
        "unit": "kWh",
    }


def _summary_response(
    context: AnalyticsContext, time_range: AnalyticsRange, values: SummaryValues
) -> AnalyticsSummaryResponse:
    return AnalyticsSummaryResponse(
        **_metadata(context, time_range),
        expected_hours=time_range.expected_hours,
        stored_hours=values.stored_hours,
        energy_value_count=values.energy_value_count,
        absent_hours=max(0, time_range.expected_hours - values.stored_hours),
        missing_energy_hours=max(0, time_range.expected_hours - values.energy_value_count),
        mean_energy_kwh=values.mean_energy_kwh,
        median_energy_kwh=values.median_energy_kwh,
        min_energy_kwh=values.min_energy_kwh,
        max_energy_kwh=values.max_energy_kwh,
        total_energy_kwh=values.total_energy_kwh,
        mean_coverage_ratio=values.mean_coverage_ratio,
        status_counts=values.status_counts,
    )


def _series_point(point: SeriesPoint) -> EnergyPointResponse:
    return EnergyPointResponse(**asdict(point))


def _profile_point(point: ProfilePoint, label: str) -> ProfilePointResponse:
    return ProfilePointResponse(**asdict(point), label=label)


def _heatmap_point(point: HeatmapPoint) -> HeatmapPointResponse:
    return HeatmapPointResponse(**asdict(point))


def _distribution_bin(value: DistributionBin) -> DistributionBinResponse:
    return DistributionBinResponse(**asdict(value))


def _resolution_seconds(resolution: SeriesResolution) -> int:
    return {"hour": 3600, "day": 86400, "week": 604800}[resolution.value]
