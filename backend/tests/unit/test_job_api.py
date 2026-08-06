from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from energy_forecast.api import create_app
from energy_forecast.config import Environment, Service, Settings
from energy_forecast.jobs.domain import (
    EnqueueJob,
    EnqueueResult,
    IdempotencyConflictError,
    InvalidJobTransitionError,
    JobNotFoundError,
    JobRecord,
    JobStatus,
    JobType,
    RecoverySummary,
)


class PassingReadinessCheck:
    async def check(self) -> None:
        return None


class FakeJobQueue:
    def __init__(self) -> None:
        self.jobs: dict[UUID, JobRecord] = {}
        self.keys: dict[str, UUID] = {}

    async def enqueue(self, request: EnqueueJob) -> EnqueueResult:
        if request.idempotency_key is not None and request.idempotency_key in self.keys:
            existing = self.jobs[self.keys[request.idempotency_key]]
            if existing.payload != request.payload:
                raise IdempotencyConflictError("Idempotency key payload differs")
            return EnqueueResult(existing, created=False)
        now = datetime.now(UTC)
        job = JobRecord(
            id=uuid4(),
            job_type=request.job_type,
            status=JobStatus.QUEUED,
            priority=request.priority,
            payload=request.payload,
            result=None,
            progress_pct=0,
            attempt=0,
            max_attempts=request.max_attempts,
            idempotency_key=request.idempotency_key,
            worker_id=None,
            heartbeat_at=None,
            cancel_requested_at=None,
            started_at=None,
            finished_at=None,
            error_code=None,
            error_detail=None,
            created_at=now,
            updated_at=now,
        )
        self.jobs[job.id] = job
        if request.idempotency_key is not None:
            self.keys[request.idempotency_key] = job.id
        return EnqueueResult(job, created=True)

    async def get(self, job_id: UUID) -> JobRecord | None:
        return self.jobs.get(job_id)

    async def request_cancel(self, job_id: UUID) -> JobRecord:
        job = self._required(job_id)
        if job.status is not JobStatus.QUEUED:
            raise InvalidJobTransitionError(job.status, JobStatus.CANCEL_REQUESTED)
        updated = replace(
            job,
            status=JobStatus.CANCEL_REQUESTED,
            cancel_requested_at=datetime.now(UTC),
        )
        self.jobs[job_id] = updated
        return updated

    async def retry(self, job_id: UUID) -> JobRecord:
        job = self._required(job_id)
        raise InvalidJobTransitionError(job.status, JobStatus.QUEUED)

    async def claim_next(
        self, worker_id: str, supported_types: frozenset[JobType]
    ) -> JobRecord | None:
        raise NotImplementedError

    async def heartbeat(
        self, job_id: UUID, worker_id: str, *, progress_pct: int | None = None
    ) -> JobStatus:
        raise NotImplementedError

    async def succeed(self, job_id: UUID, worker_id: str, result: dict[str, Any]) -> JobRecord:
        raise NotImplementedError

    async def fail(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        error_code: str,
        error_detail: str,
    ) -> JobRecord:
        raise NotImplementedError

    async def acknowledge_cancellation(self, job_id: UUID, worker_id: str) -> JobRecord:
        raise NotImplementedError

    async def acknowledge_unclaimed_cancellations(self, *, limit: int) -> int:
        raise NotImplementedError

    async def recover_stale(self, *, stale_before: datetime, limit: int) -> RecoverySummary:
        raise NotImplementedError

    def _required(self, job_id: UUID) -> JobRecord:
        try:
            return self.jobs[job_id]
        except KeyError as exc:
            raise JobNotFoundError from exc


def _settings() -> Settings:
    return Settings(
        environment=Environment.TEST,
        service=Service.API,
        code_commit="test",
    )


def test_enqueue_replay_poll_cancel_and_conflicts_use_stable_contract() -> None:
    queue = FakeJobQueue()
    app = create_app(_settings(), PassingReadinessCheck(), queue)
    with TestClient(app, raise_server_exceptions=False) as client:
        request = {
            "job_type": "export",
            "payload": {"forecast_id": "synthetic"},
            "idempotency_key": "export-synthetic",
        }
        created = client.post("/jobs", json=request)
        replay = client.post("/jobs", json=request)
        job_id = created.json()["id"]
        polled = client.get(f"/jobs/{job_id}")
        cancelled = client.post(f"/jobs/{job_id}/cancel")
        invalid_retry = client.post(f"/jobs/{job_id}/retry")
        conflicting_replay = client.post(
            "/jobs",
            json={**request, "payload": {"forecast_id": "different"}},
        )

    assert created.status_code == 202
    assert replay.status_code == 200
    assert replay.json()["id"] == job_id
    assert polled.status_code == 200
    assert polled.json()["attempts"] == []
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancel_requested"
    assert invalid_retry.status_code == 409
    assert invalid_retry.headers["content-type"] == "application/problem+json"
    assert invalid_retry.json()["code"] == "invalid_job_transition"
    assert conflicting_replay.status_code == 409
    assert conflicting_replay.json()["code"] == "idempotency_conflict"


def test_missing_jobs_and_unconfigured_queue_return_problem_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = FakeJobQueue()
    configured_app = create_app(_settings(), PassingReadinessCheck(), queue)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    unavailable_app = create_app(_settings(), PassingReadinessCheck())
    with TestClient(configured_app, raise_server_exceptions=False) as client:
        missing = client.get(f"/jobs/{uuid4()}")
    with TestClient(unavailable_app, raise_server_exceptions=False) as client:
        unavailable = client.post("/jobs", json={"job_type": "export", "payload": {}})

    assert missing.status_code == 404
    assert missing.headers["content-type"] == "application/problem+json"
    assert missing.json()["code"] == "job_not_found"
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "job_queue_unavailable"


def test_runtime_openapi_documents_job_control_operations() -> None:
    schema = create_app(_settings(), PassingReadinessCheck(), FakeJobQueue()).openapi()

    assert schema["paths"]["/jobs"]["post"]["operationId"] == "enqueueJob"
    assert schema["paths"]["/jobs/{jobId}"]["get"]["operationId"] == "getJob"
    assert schema["paths"]["/jobs/{jobId}/cancel"]["post"]["operationId"] == "cancelJob"
    assert schema["paths"]["/jobs/{jobId}/retry"]["post"]["operationId"] == "retryJob"
    assert set(schema["components"]["schemas"]["JobStatus"]["enum"]) == {
        status.value for status in JobStatus
    }
