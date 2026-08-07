"""Persistence port owned by the transformation application boundary."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from energy_forecast.transformations.models import (
    HourlyValue,
    SourceMeasurement,
    StagedTransformation,
    TransformationPolicy,
)


class TransformationRepository(Protocol):
    async def stage(
        self, source_version_id: UUID, policy: TransformationPolicy
    ) -> StagedTransformation: ...

    async def prepare(
        self, *, run_id: UUID, job_id: UUID
    ) -> tuple[UUID, UUID, int, str | None]: ...

    async def load_source(self, source_version_id: UUID) -> tuple[SourceMeasurement, ...]: ...

    async def insert_batch(
        self, target_version_id: UUID, rows: tuple[HourlyValue, ...]
    ) -> None: ...

    async def complete(
        self,
        *,
        run_id: UUID,
        target_version_id: UUID,
        policy: TransformationPolicy,
        summary: dict[str, object],
        rows: tuple[HourlyValue, ...],
    ) -> None: ...

    async def fail(self, *, run_id: UUID, target_version_id: UUID, cancelled: bool) -> None: ...
