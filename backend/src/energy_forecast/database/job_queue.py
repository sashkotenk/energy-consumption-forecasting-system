"""PostgreSQL-backed queue using short, transaction-scoped operations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from energy_forecast.database.models import Job, JobAttempt
from energy_forecast.database.session import AsyncSessionFactory, transactional_session
from energy_forecast.jobs.domain import (
    EnqueueJob,
    EnqueueResult,
    IdempotencyConflictError,
    InvalidJobTransitionError,
    JobAttemptRecord,
    JobNotFoundError,
    JobOwnershipError,
    JobRecord,
    JobStatus,
    JobType,
    RecoverySummary,
    validate_transition,
)


class SqlAlchemyJobQueue:
    """Persist jobs without keeping a claim transaction open during handler work."""

    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def enqueue(self, request: EnqueueJob) -> EnqueueResult:
        async with transactional_session(self._session_factory) as session:
            if request.idempotency_key is None:
                row = Job(**_enqueue_values(request))
                session.add(row)
                await session.flush()
                return EnqueueResult(await _to_record(session, row), created=True)

            statement = (
                postgresql_insert(Job)
                .values(**_enqueue_values(request))
                .on_conflict_do_nothing(
                    index_elements=[Job.idempotency_key],
                    index_where=Job.idempotency_key.is_not(None),
                )
                .returning(Job.id)
            )
            created_id = await session.scalar(statement)
            if created_id is not None:
                created_row = await session.get(Job, created_id)
                if created_row is None:  # pragma: no cover - guarded by INSERT RETURNING
                    raise RuntimeError("Inserted job could not be loaded")
                return EnqueueResult(await _to_record(session, created_row), created=True)

            existing_row = await session.scalar(
                select(Job).where(Job.idempotency_key == request.idempotency_key)
            )
            if existing_row is None:  # pragma: no cover - unique-conflict row must exist
                raise RuntimeError("Idempotent job could not be loaded")
            if not _same_enqueue_request(existing_row, request):
                raise IdempotencyConflictError(
                    "The idempotency key already identifies a different job request"
                )
            return EnqueueResult(await _to_record(session, existing_row), created=False)

    async def get(self, job_id: UUID) -> JobRecord | None:
        async with transactional_session(self._session_factory) as session:
            row = await session.get(Job, job_id)
            return None if row is None else await _to_record(session, row)

    async def request_cancel(self, job_id: UUID) -> JobRecord:
        async with transactional_session(self._session_factory) as session:
            row = await _locked_job(session, job_id)
            status = JobStatus(row.status)
            if status in {JobStatus.CANCEL_REQUESTED, JobStatus.CANCELLED}:
                return await _to_record(session, row)
            validate_transition(status, JobStatus.CANCEL_REQUESTED)
            now = _utcnow()
            row.status = JobStatus.CANCEL_REQUESTED.value
            row.cancel_requested_at = now
            row.updated_at = now
            await session.flush()
            return await _to_record(session, row)

    async def retry(self, job_id: UUID) -> JobRecord:
        async with transactional_session(self._session_factory) as session:
            row = await _locked_job(session, job_id)
            current = JobStatus(row.status)
            if current not in {JobStatus.FAILED, JobStatus.STALE}:
                raise InvalidJobTransitionError(current, JobStatus.QUEUED)
            if row.attempt >= row.max_attempts:
                raise InvalidJobTransitionError(current, JobStatus.QUEUED)
            validate_transition(current, JobStatus.QUEUED)
            now = _utcnow()
            row.status = JobStatus.QUEUED.value
            row.progress_pct = 0
            row.worker_id = None
            row.heartbeat_at = None
            row.cancel_requested_at = None
            row.started_at = None
            row.finished_at = None
            row.result = None
            row.updated_at = now
            await session.flush()
            return await _to_record(session, row)

    async def claim_next(
        self, worker_id: str, supported_types: frozenset[JobType]
    ) -> JobRecord | None:
        if not supported_types:
            return None
        async with transactional_session(self._session_factory) as session:
            statement = (
                select(Job)
                .where(
                    Job.status == JobStatus.QUEUED.value,
                    Job.job_type.in_([job_type.value for job_type in supported_types]),
                )
                .order_by(Job.priority.desc(), Job.created_at, Job.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = await session.scalar(statement)
            if row is None:
                return None

            validate_transition(JobStatus(row.status), JobStatus.RUNNING)
            now = _utcnow()
            row.status = JobStatus.RUNNING.value
            row.attempt += 1
            row.worker_id = worker_id
            row.heartbeat_at = now
            row.started_at = now
            row.finished_at = None
            row.cancel_requested_at = None
            row.progress_pct = 0
            row.error_code = None
            row.error_detail = None
            row.updated_at = now
            session.add(
                JobAttempt(
                    job_id=row.id,
                    attempt=row.attempt,
                    status=JobStatus.RUNNING.value,
                    worker_id=worker_id,
                    started_at=now,
                )
            )
            await session.flush()
            return await _to_record(session, row)

    async def heartbeat(
        self, job_id: UUID, worker_id: str, *, progress_pct: int | None = None
    ) -> JobStatus:
        async with transactional_session(self._session_factory) as session:
            row = await _owned_job(session, job_id, worker_id)
            status = JobStatus(row.status)
            if status not in {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED}:
                raise InvalidJobTransitionError(status, JobStatus.RUNNING)
            now = _utcnow()
            row.heartbeat_at = now
            row.updated_at = now
            if progress_pct is not None:
                if not 0 <= progress_pct <= 99:
                    raise ValueError("Running job progress must be between 0 and 99")
                row.progress_pct = max(row.progress_pct, progress_pct)
            await session.flush()
            return status

    async def succeed(self, job_id: UUID, worker_id: str, result: dict[str, Any]) -> JobRecord:
        async with transactional_session(self._session_factory) as session:
            row = await _owned_job(session, job_id, worker_id)
            if JobStatus(row.status) is JobStatus.CANCEL_REQUESTED:
                return await _finish_cancelled(session, row)
            validate_transition(JobStatus(row.status), JobStatus.SUCCEEDED)
            now = _utcnow()
            row.status = JobStatus.SUCCEEDED.value
            row.result = result
            row.progress_pct = 100
            row.finished_at = now
            row.heartbeat_at = now
            row.updated_at = now
            attempt = await _current_attempt(session, row)
            attempt.status = JobStatus.SUCCEEDED.value
            attempt.finished_at = now
            await session.flush()
            return await _to_record(session, row)

    async def fail(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        error_code: str,
        error_detail: str,
    ) -> JobRecord:
        async with transactional_session(self._session_factory) as session:
            row = await _owned_job(session, job_id, worker_id)
            if JobStatus(row.status) is JobStatus.CANCEL_REQUESTED:
                return await _finish_cancelled(session, row)
            validate_transition(JobStatus(row.status), JobStatus.FAILED)
            now = _utcnow()
            row.status = JobStatus.FAILED.value
            row.error_code = error_code
            row.error_detail = error_detail
            row.finished_at = now
            row.heartbeat_at = now
            row.updated_at = now
            attempt = await _current_attempt(session, row)
            attempt.status = JobStatus.FAILED.value
            attempt.finished_at = now
            attempt.error_code = error_code
            attempt.error_detail = error_detail
            await session.flush()
            return await _to_record(session, row)

    async def acknowledge_cancellation(self, job_id: UUID, worker_id: str) -> JobRecord:
        async with transactional_session(self._session_factory) as session:
            row = await _owned_job(session, job_id, worker_id)
            return await _finish_cancelled(session, row)

    async def acknowledge_unclaimed_cancellations(self, *, limit: int) -> int:
        async with transactional_session(self._session_factory) as session:
            rows = (
                await session.scalars(
                    select(Job)
                    .where(
                        Job.status == JobStatus.CANCEL_REQUESTED.value,
                        Job.worker_id.is_(None),
                    )
                    .order_by(Job.cancel_requested_at, Job.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            now = _utcnow()
            for row in rows:
                validate_transition(JobStatus(row.status), JobStatus.CANCELLED)
                row.status = JobStatus.CANCELLED.value
                row.finished_at = now
                row.updated_at = now
            await session.flush()
            return len(rows)

    async def recover_stale(self, *, stale_before: datetime, limit: int) -> RecoverySummary:
        async with transactional_session(self._session_factory) as session:
            rows = (
                await session.scalars(
                    select(Job)
                    .where(
                        Job.status.in_([JobStatus.RUNNING.value, JobStatus.CANCEL_REQUESTED.value]),
                        Job.worker_id.is_not(None),
                        or_(Job.heartbeat_at.is_(None), Job.heartbeat_at < stale_before),
                    )
                    .order_by(Job.heartbeat_at, Job.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            requeued = failed = cancelled = 0
            now = _utcnow()
            for row in rows:
                current = JobStatus(row.status)
                attempt = await _current_attempt(session, row)
                if current is JobStatus.CANCEL_REQUESTED:
                    validate_transition(current, JobStatus.CANCELLED)
                    row.status = JobStatus.CANCELLED.value
                    row.finished_at = now
                    attempt.status = JobStatus.CANCELLED.value
                    cancelled += 1
                else:
                    validate_transition(current, JobStatus.STALE)
                    row.status = JobStatus.STALE.value
                    row.error_code = "worker_heartbeat_timeout"
                    row.error_detail = "Worker heartbeat expired before the attempt completed"
                    attempt.status = JobStatus.STALE.value
                    attempt.error_code = row.error_code
                    attempt.error_detail = row.error_detail
                    if row.attempt < row.max_attempts:
                        validate_transition(JobStatus.STALE, JobStatus.QUEUED)
                        row.status = JobStatus.QUEUED.value
                        row.progress_pct = 0
                        row.worker_id = None
                        row.heartbeat_at = None
                        row.started_at = None
                        row.finished_at = None
                        requeued += 1
                    else:
                        validate_transition(JobStatus.STALE, JobStatus.FAILED)
                        row.status = JobStatus.FAILED.value
                        row.finished_at = now
                        failed += 1
                attempt.finished_at = now
                row.updated_at = now
            await session.flush()
            return RecoverySummary(requeued=requeued, failed=failed, cancelled=cancelled)


def _enqueue_values(request: EnqueueJob) -> dict[str, Any]:
    return {
        "job_type": request.job_type.value,
        "status": JobStatus.QUEUED.value,
        "priority": request.priority,
        "payload": request.payload,
        "max_attempts": request.max_attempts,
        "idempotency_key": request.idempotency_key,
    }


def _same_enqueue_request(row: Job, request: EnqueueJob) -> bool:
    return (
        row.job_type == request.job_type.value
        and row.payload == request.payload
        and row.priority == request.priority
        and row.max_attempts == request.max_attempts
    )


async def _locked_job(session: AsyncSession, job_id: UUID) -> Job:
    row = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if row is None:
        raise JobNotFoundError(f"Job {job_id} was not found")
    return row


async def _owned_job(session: AsyncSession, job_id: UUID, worker_id: str) -> Job:
    row = await _locked_job(session, job_id)
    if row.worker_id != worker_id:
        raise JobOwnershipError(f"Job {job_id} is not owned by worker {worker_id}")
    return row


async def _current_attempt(session: AsyncSession, row: Job) -> JobAttempt:
    attempt = await session.scalar(
        select(JobAttempt)
        .where(JobAttempt.job_id == row.id, JobAttempt.attempt == row.attempt)
        .with_for_update()
    )
    if attempt is None:  # pragma: no cover - queue invariants create it during claim
        raise RuntimeError("Current job attempt is missing")
    return attempt


async def _finish_cancelled(session: AsyncSession, row: Job) -> JobRecord:
    validate_transition(JobStatus(row.status), JobStatus.CANCELLED)
    now = _utcnow()
    row.status = JobStatus.CANCELLED.value
    row.finished_at = now
    row.heartbeat_at = now
    row.updated_at = now
    attempt = await _current_attempt(session, row)
    attempt.status = JobStatus.CANCELLED.value
    attempt.finished_at = now
    await session.flush()
    return await _to_record(session, row)


async def _to_record(session: AsyncSession, row: Job) -> JobRecord:
    attempt_rows = (
        await session.scalars(
            select(JobAttempt).where(JobAttempt.job_id == row.id).order_by(JobAttempt.attempt)
        )
    ).all()
    return JobRecord(
        id=row.id,
        job_type=JobType(row.job_type),
        status=JobStatus(row.status),
        priority=row.priority,
        payload=dict(row.payload),
        result=None if row.result is None else dict(row.result),
        progress_pct=row.progress_pct,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        idempotency_key=row.idempotency_key,
        worker_id=row.worker_id,
        heartbeat_at=row.heartbeat_at,
        cancel_requested_at=row.cancel_requested_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error_code=row.error_code,
        error_detail=row.error_detail,
        created_at=row.created_at,
        updated_at=row.updated_at,
        attempts=tuple(
            JobAttemptRecord(
                attempt=attempt.attempt,
                status=JobStatus(attempt.status),
                worker_id=attempt.worker_id,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                error_code=attempt.error_code,
                error_detail=attempt.error_detail,
            )
            for attempt in attempt_rows
        ),
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)
