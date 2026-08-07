"""Bounded REST access to versioned data-quality reports."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel

from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem
from energy_forecast.quality.models import (
    QualityReportNotFoundError,
    QualityReportPage,
    StoredQualityIssue,
)
from energy_forecast.quality.service import QualityService

PageNumber = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(ge=1, le=100)]
ReportVersion = Annotated[int | None, Query(ge=1)]


class QualityIssueResponse(BaseModel):
    id: int
    issue_type: str
    severity: str
    range_start: datetime | None
    range_end: datetime | None
    occurrence_count: int
    column_name: str | None
    evidence: tuple[dict[str, Any], ...]


class DataQualityReportResponse(BaseModel):
    report_id: UUID
    dataset_version_id: UUID
    report_version: int
    engine_version: str
    expected_interval_seconds: int | None
    summary: dict[str, Any]
    items: tuple[QualityIssueResponse, ...]
    page: int
    page_size: int
    total: int
    created_at: datetime


_PROBLEM_RESPONSE = {"model": Problem, "content": {PROBLEM_MEDIA_TYPE: {}}}


def create_quality_router(service: QualityService | None) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/dataset-versions/{versionId}/quality",
        tags=["Datasets"],
        operation_id="getDataQualityReport",
        response_model=DataQualityReportResponse,
        responses={
            HTTPStatus.CONFLICT: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
    )
    async def get_quality_report(
        versionId: UUID,
        page: PageNumber = 1,
        page_size: PageSize = 20,
        report_version: ReportVersion = None,
    ) -> DataQualityReportResponse:
        try:
            result = await _require_service(service).get_report(
                versionId,
                report_version=report_version,
                page=page,
                page_size=page_size,
            )
        except QualityReportNotFoundError as error:
            raise ApiProblem(
                status=HTTPStatus.CONFLICT,
                code="quality_report_not_ready",
                title="Звіт про якість недоступний",
                detail="Для цієї версії набору даних звіт про якість ще не сформовано.",
            ) from error
        return _to_response(result)

    return router


def _require_service(service: QualityService | None) -> QualityService:
    if service is None:
        raise ApiProblem(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="quality_service_unavailable",
            title="Сервіс якості даних недоступний",
            detail="З'єднання з базою даних не налаштовано.",
        )
    return service


def _to_response(page: QualityReportPage) -> DataQualityReportResponse:
    report = page.report
    return DataQualityReportResponse(
        report_id=report.id,
        dataset_version_id=report.dataset_version_id,
        report_version=report.report_version,
        engine_version=report.engine_version,
        expected_interval_seconds=report.expected_interval_seconds,
        summary=report.summary,
        items=tuple(_to_issue_response(issue) for issue in page.items),
        page=page.page,
        page_size=page.page_size,
        total=page.total,
        created_at=report.created_at,
    )


def _to_issue_response(issue: StoredQualityIssue) -> QualityIssueResponse:
    return QualityIssueResponse(
        id=issue.id,
        issue_type=issue.issue_type,
        severity=issue.severity,
        range_start=issue.range_start,
        range_end=issue.range_end,
        occurrence_count=issue.occurrence_count,
        column_name=issue.column_name,
        evidence=issue.evidence,
    )
