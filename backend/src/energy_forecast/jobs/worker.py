"""Handler registry and cooperative worker lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from energy_forecast.jobs.domain import (
    JobCancellationRequested,
    JobRecord,
    JobStatus,
    JobType,
)
from energy_forecast.jobs.ports import JobQueue

type JobHandler = Callable[["JobExecutionContext"], Awaitable[dict[str, Any]]]


class JobHandlerRegistry:
    """Map each executable job type to exactly one application handler."""

    def __init__(self) -> None:
        self._handlers: dict[JobType, JobHandler] = {}

    def register(self, job_type: JobType, handler: JobHandler) -> None:
        if job_type in self._handlers:
            raise ValueError(f"A handler is already registered for {job_type.value}")
        self._handlers[job_type] = handler

    @property
    def supported_types(self) -> frozenset[JobType]:
        return frozenset(self._handlers)

    def get(self, job_type: JobType) -> JobHandler:
        try:
            return self._handlers[job_type]
        except KeyError as exc:  # pragma: no cover - claim is filtered by supported types
            raise LookupError(f"No handler registered for {job_type.value}") from exc


class JobExecutionContext:
    """Give handlers explicit progress and cooperative-cancellation checkpoints."""

    def __init__(self, queue: JobQueue, job: JobRecord, worker_id: str) -> None:
        self._queue = queue
        self._job = job
        self._worker_id = worker_id
        self._cancel_requested = asyncio.Event()

    @property
    def job_id(self) -> UUID:
        return self._job.id

    @property
    def payload(self) -> dict[str, Any]:
        return dict(self._job.payload)

    @property
    def attempt(self) -> int:
        return self._job.attempt

    async def report_progress(self, progress_pct: int) -> None:
        status = await self._queue.heartbeat(
            self._job.id, self._worker_id, progress_pct=progress_pct
        )
        if status is JobStatus.CANCEL_REQUESTED:
            self._cancel_requested.set()
        self.raise_if_cancel_requested()

    def raise_if_cancel_requested(self) -> None:
        if self._cancel_requested.is_set():
            raise JobCancellationRequested("Job cancellation was requested")

    def _mark_cancel_requested(self) -> None:
        self._cancel_requested.set()


class JobWorker:
    """Poll, claim, execute, heartbeat, and recover jobs as separate transactions."""

    def __init__(
        self,
        queue: JobQueue,
        registry: JobHandlerRegistry,
        *,
        worker_id: str,
        poll_interval_seconds: float,
        heartbeat_interval_seconds: float,
        stale_after_seconds: float,
        recovery_batch_size: int,
    ) -> None:
        self._queue = queue
        self._registry = registry
        self._worker_id = worker_id
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._stale_after_seconds = stale_after_seconds
        self._recovery_batch_size = recovery_batch_size
        self._logger = logging.getLogger(__name__)

    async def run_once(self) -> bool:
        """Run one maintenance-and-claim cycle; return whether a job was executed."""
        stale_before = datetime.now(UTC) - timedelta(seconds=self._stale_after_seconds)
        recovery = await self._queue.recover_stale(
            stale_before=stale_before, limit=self._recovery_batch_size
        )
        if recovery.requeued or recovery.failed or recovery.cancelled:
            self._logger.warning(
                "stale_jobs_recovered",
                extra={
                    "event": "stale_jobs_recovered",
                    "requeued": recovery.requeued,
                    "failed": recovery.failed,
                    "cancelled": recovery.cancelled,
                },
            )
        await self._queue.acknowledge_unclaimed_cancellations(limit=self._recovery_batch_size)
        job = await self._queue.claim_next(self._worker_id, self._registry.supported_types)
        if job is None:
            return False
        await self._execute(job)
        return True

    async def run_forever(self) -> None:
        self._logger.info(
            "worker_started",
            extra={"event": "worker_started", "worker_id": self._worker_id},
        )
        while True:
            executed = await self.run_once()
            if not executed:
                await asyncio.sleep(self._poll_interval_seconds)

    async def _execute(self, job: JobRecord) -> None:
        context = JobExecutionContext(self._queue, job, self._worker_id)
        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(context, stop_heartbeat),
            name=f"job-heartbeat-{job.id}",
        )
        handler = self._registry.get(job.job_type)
        self._logger.info(
            "job_started",
            extra={
                "event": "job_started",
                "job_id": str(job.id),
                "job_type": job.job_type.value,
                "attempt": job.attempt,
                "worker_id": self._worker_id,
            },
        )
        try:
            result = await handler(context)
            completed = await self._queue.succeed(job.id, self._worker_id, result)
        except JobCancellationRequested:
            completed = await self._queue.acknowledge_cancellation(job.id, self._worker_id)
        except Exception as exc:
            self._logger.exception(
                "job_failed",
                extra={
                    "event": "job_failed",
                    "job_id": str(job.id),
                    "job_type": job.job_type.value,
                    "error_code": "handler_failed",
                },
            )
            completed = await self._queue.fail(
                job.id,
                self._worker_id,
                error_code="handler_failed",
                error_detail=str(exc) or type(exc).__name__,
            )
        finally:
            stop_heartbeat.set()
            await heartbeat_task
        self._logger.info(
            "job_finished",
            extra={
                "event": "job_finished",
                "job_id": str(job.id),
                "status": completed.status.value,
                "worker_id": self._worker_id,
            },
        )

    async def _heartbeat_loop(self, context: JobExecutionContext, stop: asyncio.Event) -> None:
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._heartbeat_interval_seconds)
                return
            except TimeoutError:
                status = await self._queue.heartbeat(context.job_id, self._worker_id)
                if status is JobStatus.CANCEL_REQUESTED:
                    context._mark_cancel_requested()
