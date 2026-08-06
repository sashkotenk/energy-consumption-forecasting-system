from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import pytest

from energy_forecast.database import (
    SqlAlchemyJobQueue,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.jobs.domain import EnqueueJob, JobStatus, JobType
from energy_forecast.jobs.worker import (
    JobExecutionContext,
    JobHandlerRegistry,
    JobWorker,
)
from tests.integration.conftest import BACKEND_ROOT, upgrade_database

pytestmark = pytest.mark.integration


async def _exercise_worker_lifecycle(database_url: str) -> None:
    engine = create_database_engine(database_url)
    queue = SqlAlchemyJobQueue(create_session_factory(engine))
    handler_started = asyncio.Event()

    async def export_handler(context: JobExecutionContext) -> dict[str, object]:
        if context.payload.get("mode") == "cancel":
            handler_started.set()
            while True:
                await asyncio.sleep(0.01)
                await context.report_progress(25)
        await context.report_progress(60)
        return {"artifact_id": "synthetic-export"}

    registry = JobHandlerRegistry()
    registry.register(JobType.EXPORT, export_handler)
    worker = JobWorker(
        queue,
        registry,
        worker_id="integration-worker",
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=0.05,
        stale_after_seconds=1,
        recovery_batch_size=10,
    )
    try:
        successful = (
            await queue.enqueue(EnqueueJob(job_type=JobType.EXPORT, payload={"mode": "success"}))
        ).job
        assert await worker.run_once() is True
        successful_result = await queue.get(successful.id)
        assert successful_result is not None
        assert successful_result.status is JobStatus.SUCCEEDED
        assert successful_result.progress_pct == 100
        assert successful_result.result == {"artifact_id": "synthetic-export"}

        cancellable = (
            await queue.enqueue(EnqueueJob(job_type=JobType.EXPORT, payload={"mode": "cancel"}))
        ).job
        worker_task = asyncio.create_task(worker.run_once())
        await asyncio.wait_for(handler_started.wait(), timeout=2)
        await queue.request_cancel(cancellable.id)
        assert await asyncio.wait_for(worker_task, timeout=2) is True
        cancelled_result = await queue.get(cancellable.id)
        assert cancelled_result is not None
        assert cancelled_result.status is JobStatus.CANCELLED
        assert cancelled_result.attempts[0].status is JobStatus.CANCELLED
    finally:
        await engine.dispose()


def test_registered_handler_progress_and_cooperative_cancellation(
    temporary_database_url: str,
) -> None:
    upgrade_database(temporary_database_url)
    asyncio.run(_exercise_worker_lifecycle(temporary_database_url))


def test_worker_process_run_once_smoke(temporary_database_url: str) -> None:
    upgrade_database(temporary_database_url)
    environment = os.environ.copy()
    environment.update(
        {
            "APP_ENV": "test",
            "APP_SERVICE": "worker",
            "DATABASE_URL": temporary_database_url,
            "WORKER_RUN_ONCE": "true",
            "PYTHONUTF8": "1",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from energy_forecast.worker import main; main()",
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"event":"worker_initialized"' in completed.stderr
    assert '"event":"worker_stopped"' in completed.stderr
