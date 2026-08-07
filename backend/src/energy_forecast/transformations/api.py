"""REST endpoint for immutable asynchronous transformations."""

from __future__ import annotations

from http import HTTPStatus
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem
from energy_forecast.transformations.models import (
    DuplicatePolicy,
    SourceVersionNotReadyError,
    TransformationPolicy,
)
from energy_forecast.transformations.service import TransformationService


class TransformationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short_gap_limit_minutes: int = Field(default=5, ge=0, le=5)
    minimum_hour_coverage: float = Field(default=0.9, ge=0.8, le=1)
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.REJECT


class TransformationAccepted(BaseModel):
    run_id: UUID
    job_id: UUID
    source_version_id: UUID
    target_version_id: UUID
    status: Literal["queued"] = "queued"


_PROBLEM_RESPONSE = {"model": Problem, "content": {PROBLEM_MEDIA_TYPE: {}}}


def create_transformation_router(service: TransformationService | None) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/dataset-versions/{versionId}/transformations",
        tags=["Datasets"],
        operation_id="createTransformation",
        response_model=TransformationAccepted,
        status_code=HTTPStatus.ACCEPTED,
        responses={
            HTTPStatus.CONFLICT: _PROBLEM_RESPONSE,
            HTTPStatus.UNPROCESSABLE_ENTITY: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
    )
    async def create_transformation(
        versionId: UUID, request: TransformationCreate
    ) -> TransformationAccepted:
        try:
            staged = await _require_service(service).stage(
                versionId,
                TransformationPolicy(
                    short_gap_limit_minutes=request.short_gap_limit_minutes,
                    minimum_hour_coverage=request.minimum_hour_coverage,
                    duplicate_policy=request.duplicate_policy,
                ),
            )
        except SourceVersionNotReadyError as error:
            raise ApiProblem(
                status=HTTPStatus.CONFLICT,
                code="source_version_not_ready",
                title="Версія набору даних не готова",
                detail="Перед трансформацією імпортовані дані мають пройти перевірку якості.",
            ) from error
        return TransformationAccepted(
            run_id=staged.run_id,
            job_id=staged.job_id,
            source_version_id=staged.source_version_id,
            target_version_id=staged.target_version_id,
        )

    return router


def _require_service(service: TransformationService | None) -> TransformationService:
    if service is None:
        raise ApiProblem(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="transformation_service_unavailable",
            title="Сервіс трансформацій недоступний",
            detail="З'єднання з базою даних не налаштовано.",
        )
    return service
