"""REST polling and control endpoints for persistent jobs."""

from __future__ import annotations

from datetime import datetime
from http import HTTPStatus
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field

from energy_forecast.errors import PROBLEM_MEDIA_TYPE, ApiProblem, Problem
from energy_forecast.jobs.domain import (
    EnqueueJob,
    IdempotencyConflictError,
    InvalidJobTransitionError,
    JobAttemptRecord,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    JobType,
)
from energy_forecast.jobs.ports import JobQueue

Priority = Annotated[int, Field(ge=-100, le=100)]
MaxAttempts = Annotated[int, Field(ge=1, le=5)]


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: JobType
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: Priority = 0
    max_attempts: MaxAttempts = 3
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )


class JobAttemptResponse(BaseModel):
    attempt: int
    status: JobStatus
    worker_id: str
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_detail: str | None


class JobResponse(BaseModel):
    id: UUID
    job_type: JobType
    status: JobStatus
    progress_pct: int
    attempt: int
    max_attempts: int
    result: dict[str, Any] | None
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    cancel_requested_at: datetime | None
    attempts: tuple[JobAttemptResponse, ...]


_PROBLEM_RESPONSE = {
    "model": Problem,
    "content": {PROBLEM_MEDIA_TYPE: {}},
}


def create_job_router(queue: JobQueue | None) -> APIRouter:
    router = APIRouter(prefix="/jobs", tags=["Jobs"])

    @router.post(
        "",
        operation_id="enqueueJob",
        response_model=JobResponse,
        status_code=HTTPStatus.ACCEPTED,
        responses={
            HTTPStatus.OK: {"description": "Idempotent replay of the original request"},
            HTTPStatus.CONFLICT: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
        summary="Enqueue persistent work",
    )
    async def enqueue_job(request: JobCreate, response: Response) -> JobResponse:
        job_queue = _require_queue(queue)
        try:
            result = await job_queue.enqueue(
                EnqueueJob(
                    job_type=request.job_type,
                    payload=request.payload,
                    priority=request.priority,
                    max_attempts=request.max_attempts,
                    idempotency_key=request.idempotency_key,
                )
            )
        except IdempotencyConflictError as exc:
            raise _conflict("idempotency_conflict", str(exc)) from exc
        if not result.created:
            response.status_code = HTTPStatus.OK
        return _to_response(result.job)

    @router.get(
        "/{jobId}",
        operation_id="getJob",
        response_model=JobResponse,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
        summary="Poll job state",
    )
    async def get_job(jobId: UUID) -> JobResponse:
        job = await _require_queue(queue).get(jobId)
        if job is None:
            raise _not_found()
        return _to_response(job)

    @router.post(
        "/{jobId}/cancel",
        operation_id="cancelJob",
        response_model=JobResponse,
        status_code=HTTPStatus.ACCEPTED,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM_RESPONSE,
            HTTPStatus.CONFLICT: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
        summary="Request cooperative cancellation",
    )
    async def cancel_job(jobId: UUID) -> JobResponse:
        try:
            job = await _require_queue(queue).request_cancel(jobId)
        except JobNotFoundError as exc:
            raise _not_found() from exc
        except InvalidJobTransitionError as exc:
            raise _transition_conflict(exc) from exc
        return _to_response(job)

    @router.post(
        "/{jobId}/retry",
        operation_id="retryJob",
        response_model=JobResponse,
        status_code=HTTPStatus.ACCEPTED,
        responses={
            HTTPStatus.NOT_FOUND: _PROBLEM_RESPONSE,
            HTTPStatus.CONFLICT: _PROBLEM_RESPONSE,
            HTTPStatus.SERVICE_UNAVAILABLE: _PROBLEM_RESPONSE,
        },
        summary="Requeue an eligible failed job",
    )
    async def retry_job(jobId: UUID) -> JobResponse:
        try:
            job = await _require_queue(queue).retry(jobId)
        except JobNotFoundError as exc:
            raise _not_found() from exc
        except InvalidJobTransitionError as exc:
            raise _transition_conflict(exc) from exc
        return _to_response(job)

    return router


def _require_queue(queue: JobQueue | None) -> JobQueue:
    if queue is None:
        raise ApiProblem(
            status=HTTPStatus.SERVICE_UNAVAILABLE,
            code="job_queue_unavailable",
            title="Черга завдань недоступна",
            detail="З'єднання з базою даних для черги завдань не налаштовано.",
        )
    return queue


def _not_found() -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.NOT_FOUND,
        code="job_not_found",
        title="Завдання не знайдено",
        detail="Запитане фонове завдання не існує.",
    )


def _conflict(code: str, detail: str) -> ApiProblem:
    return ApiProblem(
        status=HTTPStatus.CONFLICT,
        code=code,
        title="Конфлікт стану завдання",
        detail=detail,
    )


def _transition_conflict(exc: InvalidJobTransitionError) -> ApiProblem:
    return _conflict(
        "invalid_job_transition",
        f"Перехід зі стану '{exc.current.value}' до '{exc.target.value}' заборонено.",
    )


def _to_response(job: JobRecord) -> JobResponse:
    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        progress_pct=job.progress_pct,
        attempt=job.attempt,
        max_attempts=job.max_attempts,
        result=job.result,
        error_code=job.error_code,
        error_detail=job.error_detail,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        heartbeat_at=job.heartbeat_at,
        cancel_requested_at=job.cancel_requested_at,
        attempts=tuple(_to_attempt_response(attempt) for attempt in job.attempts),
    )


def _to_attempt_response(attempt: JobAttemptRecord) -> JobAttemptResponse:
    return JobAttemptResponse(
        attempt=attempt.attempt,
        status=attempt.status,
        worker_id=attempt.worker_id,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        error_code=attempt.error_code,
        error_detail=attempt.error_detail,
    )
