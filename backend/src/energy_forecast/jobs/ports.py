"""Application-owned ports for persistent job operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from energy_forecast.jobs.domain import (
    EnqueueJob,
    EnqueueResult,
    JobRecord,
    JobStatus,
    JobType,
    RecoverySummary,
)


class JobQueue(Protocol):
    async def enqueue(self, request: EnqueueJob) -> EnqueueResult: ...

    async def get(self, job_id: UUID) -> JobRecord | None: ...

    async def request_cancel(self, job_id: UUID) -> JobRecord: ...

    async def retry(self, job_id: UUID) -> JobRecord: ...

    async def claim_next(
        self, worker_id: str, supported_types: frozenset[JobType]
    ) -> JobRecord | None: ...

    async def heartbeat(
        self, job_id: UUID, worker_id: str, *, progress_pct: int | None = None
    ) -> JobStatus: ...

    async def succeed(self, job_id: UUID, worker_id: str, result: dict[str, Any]) -> JobRecord: ...

    async def fail(
        self,
        job_id: UUID,
        worker_id: str,
        *,
        error_code: str,
        error_detail: str,
    ) -> JobRecord: ...

    async def acknowledge_cancellation(self, job_id: UUID, worker_id: str) -> JobRecord: ...

    async def acknowledge_unclaimed_cancellations(self, *, limit: int) -> int: ...

    async def recover_stale(self, *, stale_before: datetime, limit: int) -> RecoverySummary: ...
