"""Framework-independent job states, records, and transition rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class JobType(StrEnum):
    DATASET_IMPORT = "dataset_import"
    DATA_VALIDATION = "data_validation"
    DATA_TRANSFORMATION = "data_transformation"
    WEATHER_IMPORT = "weather_import"
    EXPERIMENT = "experiment"
    FORECAST = "forecast"
    EXPORT = "export"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"


TERMINAL_JOB_STATUSES = frozenset({JobStatus.CANCELLED, JobStatus.SUCCEEDED, JobStatus.FAILED})

_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.CANCEL_REQUESTED,
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.STALE,
        }
    ),
    JobStatus.CANCEL_REQUESTED: frozenset({JobStatus.CANCELLED}),
    JobStatus.STALE: frozenset({JobStatus.QUEUED, JobStatus.FAILED}),
    JobStatus.FAILED: frozenset({JobStatus.QUEUED}),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.SUCCEEDED: frozenset(),
}


class JobError(Exception):
    """Base class for expected job application failures."""


class JobNotFoundError(JobError):
    """Raised when a requested job does not exist."""


class InvalidJobTransitionError(JobError):
    """Raised when a state transition violates the job lifecycle."""

    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"Job cannot transition from {current.value} to {target.value}")
        self.current = current
        self.target = target


class IdempotencyConflictError(JobError):
    """Raised when an idempotency key is reused for a different request."""


class JobOwnershipError(JobError):
    """Raised when a worker tries to mutate a job owned by another worker."""


class JobCancellationRequested(JobError):
    """Cooperative signal raised inside a handler at a cancellation checkpoint."""


def validate_transition(current: JobStatus, target: JobStatus) -> None:
    """Reject every state change not listed in the accepted lifecycle."""
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidJobTransitionError(current, target)


@dataclass(frozen=True, slots=True)
class EnqueueJob:
    job_type: JobType
    payload: dict[str, Any]
    priority: int = 0
    max_attempts: int = 3
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class JobAttemptRecord:
    attempt: int
    status: JobStatus
    worker_id: str
    started_at: datetime
    finished_at: datetime | None
    error_code: str | None
    error_detail: str | None


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: UUID
    job_type: JobType
    status: JobStatus
    priority: int
    payload: dict[str, Any]
    result: dict[str, Any] | None
    progress_pct: int
    attempt: int
    max_attempts: int
    idempotency_key: str | None
    worker_id: str | None
    heartbeat_at: datetime | None
    cancel_requested_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime
    attempts: tuple[JobAttemptRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    job: JobRecord
    created: bool


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    requeued: int = 0
    failed: int = 0
    cancelled: int = 0
