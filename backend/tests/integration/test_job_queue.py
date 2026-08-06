from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from energy_forecast.database import (
    SqlAlchemyJobQueue,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.jobs.domain import (
    EnqueueJob,
    IdempotencyConflictError,
    InvalidJobTransitionError,
    JobStatus,
    JobType,
)
from tests.integration.conftest import upgrade_database

pytestmark = pytest.mark.integration


async def _exercise_atomic_claim_and_idempotency(database_url: str) -> None:
    engine = create_database_engine(database_url)
    queue = SqlAlchemyJobQueue(create_session_factory(engine))
    request = EnqueueJob(
        job_type=JobType.EXPORT,
        payload={"forecast_id": "synthetic-1"},
        max_attempts=2,
        idempotency_key="export-synthetic-1",
    )
    try:
        first, replay = await asyncio.gather(queue.enqueue(request), queue.enqueue(request))
        assert first.job.id == replay.job.id
        assert sorted([first.created, replay.created]) == [False, True]

        with pytest.raises(IdempotencyConflictError):
            await queue.enqueue(
                EnqueueJob(
                    job_type=JobType.EXPORT,
                    payload={"forecast_id": "different"},
                    idempotency_key="export-synthetic-1",
                )
            )

        claims = await asyncio.gather(
            queue.claim_next("worker-a", frozenset({JobType.EXPORT})),
            queue.claim_next("worker-b", frozenset({JobType.EXPORT})),
        )
        claimed = [job for job in claims if job is not None]
        assert len(claimed) == 1
        assert claimed[0].id == first.job.id
        assert claimed[0].attempt == 1
        assert claimed[0].status is JobStatus.RUNNING
        assert len(claimed[0].attempts) == 1
    finally:
        await engine.dispose()


def test_atomic_claim_and_idempotent_enqueue(temporary_database_url: str) -> None:
    upgrade_database(temporary_database_url)
    asyncio.run(_exercise_atomic_claim_and_idempotency(temporary_database_url))


async def _exercise_stale_recovery_and_retry_history(database_url: str) -> None:
    engine = create_database_engine(database_url)
    queue = SqlAlchemyJobQueue(create_session_factory(engine))
    try:
        stale_job = (
            await queue.enqueue(
                EnqueueJob(
                    job_type=JobType.FORECAST,
                    payload={"origin": "2026-01-01T00:00:00Z"},
                    max_attempts=2,
                )
            )
        ).job
        claimed = await queue.claim_next("crashed-worker", frozenset({JobType.FORECAST}))
        assert claimed is not None and claimed.id == stale_job.id

        recovery = await queue.recover_stale(
            stale_before=datetime.now(UTC) + timedelta(seconds=1), limit=10
        )
        assert recovery.requeued == 1
        recovered = await queue.get(stale_job.id)
        assert recovered is not None
        assert recovered.status is JobStatus.QUEUED
        assert recovered.attempts[0].status is JobStatus.STALE
        assert recovered.attempts[0].error_code == "worker_heartbeat_timeout"

        reclaimed = await queue.claim_next("worker-b", frozenset({JobType.FORECAST}))
        assert reclaimed is not None and reclaimed.attempt == 2
        completed = await queue.succeed(reclaimed.id, "worker-b", {"forecast_id": "done"})
        assert completed.status is JobStatus.SUCCEEDED
        assert [attempt.status for attempt in completed.attempts] == [
            JobStatus.STALE,
            JobStatus.SUCCEEDED,
        ]

        second_recovery = await queue.recover_stale(
            stale_before=datetime.now(UTC) + timedelta(days=1), limit=10
        )
        assert second_recovery.requeued == 0
        assert (await queue.get(completed.id)).status is JobStatus.SUCCEEDED  # type: ignore[union-attr]
        with pytest.raises(InvalidJobTransitionError):
            await queue.retry(completed.id)

        failed_job = (
            await queue.enqueue(
                EnqueueJob(
                    job_type=JobType.EXPERIMENT,
                    payload={"experiment_id": "synthetic"},
                    max_attempts=2,
                )
            )
        ).job
        failed_claim = await queue.claim_next("worker-c", frozenset({JobType.EXPERIMENT}))
        assert failed_claim is not None and failed_claim.id == failed_job.id
        failed = await queue.fail(
            failed_job.id,
            "worker-c",
            error_code="synthetic_failure",
            error_detail="first attempt evidence",
        )
        assert failed.status is JobStatus.FAILED
        retried = await queue.retry(failed.id)
        assert retried.status is JobStatus.QUEUED
        assert retried.attempts[0].error_detail == "first attempt evidence"
        second_claim = await queue.claim_next("worker-d", frozenset({JobType.EXPERIMENT}))
        assert second_claim is not None and second_claim.attempt == 2
    finally:
        await engine.dispose()


def test_stale_recovery_completed_guard_and_retry_evidence(
    temporary_database_url: str,
) -> None:
    upgrade_database(temporary_database_url)
    asyncio.run(_exercise_stale_recovery_and_retry_history(temporary_database_url))


async def _exercise_cancellation(database_url: str) -> None:
    engine = create_database_engine(database_url)
    queue = SqlAlchemyJobQueue(create_session_factory(engine))
    try:
        queued = (await queue.enqueue(EnqueueJob(job_type=JobType.DATA_VALIDATION, payload={}))).job
        requested = await queue.request_cancel(queued.id)
        assert requested.status is JobStatus.CANCEL_REQUESTED
        assert await queue.acknowledge_unclaimed_cancellations(limit=10) == 1
        cancelled = await queue.get(queued.id)
        assert cancelled is not None and cancelled.status is JobStatus.CANCELLED
        assert (await queue.request_cancel(queued.id)).status is JobStatus.CANCELLED

        running = (
            await queue.enqueue(EnqueueJob(job_type=JobType.DATA_TRANSFORMATION, payload={}))
        ).job
        claim = await queue.claim_next("worker-cancel", frozenset({JobType.DATA_TRANSFORMATION}))
        assert claim is not None and claim.id == running.id
        assert (await queue.request_cancel(running.id)).status is JobStatus.CANCEL_REQUESTED
        assert await queue.heartbeat(running.id, "worker-cancel") is JobStatus.CANCEL_REQUESTED
        acknowledged = await queue.acknowledge_cancellation(running.id, "worker-cancel")
        assert acknowledged.status is JobStatus.CANCELLED
        assert acknowledged.attempts[0].status is JobStatus.CANCELLED
    finally:
        await engine.dispose()


def test_queued_and_running_cancellation(temporary_database_url: str) -> None:
    upgrade_database(temporary_database_url)
    asyncio.run(_exercise_cancellation(temporary_database_url))
