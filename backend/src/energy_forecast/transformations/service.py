"""Application service and restart-safe worker handler for transformations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from energy_forecast.jobs.domain import JobCancellationRequested
from energy_forecast.jobs.worker import JobExecutionContext
from energy_forecast.transformations.engine import TransformationEngine
from energy_forecast.transformations.models import (
    DuplicatePolicy,
    StagedTransformation,
    TransformationPolicy,
)
from energy_forecast.transformations.ports import TransformationRepository


class TransformationService:
    def __init__(self, repository: TransformationRepository) -> None:
        self._repository = repository

    async def stage(
        self, source_version_id: UUID, policy: TransformationPolicy
    ) -> StagedTransformation:
        return await self._repository.stage(source_version_id, policy)


class TransformationHandler:
    def __init__(
        self,
        repository: TransformationRepository,
        engine: TransformationEngine | None = None,
        *,
        batch_size: int = 2_000,
    ) -> None:
        self._repository = repository
        self._engine = engine or TransformationEngine()
        self._batch_size = batch_size

    async def __call__(self, context: JobExecutionContext) -> dict[str, Any]:
        run_id = UUID(_required(context.payload, "transformation_run_id"))
        target_id = UUID(_required(context.payload, "target_version_id"))
        raw_policy = context.payload.get("policy")
        if not isinstance(raw_policy, dict):
            raise ValueError("Transformation payload is missing policy")
        policy = TransformationPolicy(
            short_gap_limit_minutes=int(raw_policy["short_gap_limit_minutes"]),
            minimum_hour_coverage=float(raw_policy["minimum_hour_coverage"]),
            duplicate_policy=DuplicatePolicy(str(raw_policy.get("duplicate_policy", "reject"))),
        )
        try:
            (
                source_id,
                prepared_target_id,
                interval_seconds,
                timezone_context,
            ) = await self._repository.prepare(run_id=run_id, job_id=context.job_id)
            if prepared_target_id != target_id:
                raise ValueError("Transformation target does not match its job payload")
            context.raise_if_cancel_requested()
            source = await self._repository.load_source(source_id)
            result = self._engine.transform(
                source,
                interval_seconds=interval_seconds,
                timezone_context=timezone_context,
                policy=policy,
            )
            for start in range(0, len(result.rows), self._batch_size):
                context.raise_if_cancel_requested()
                await self._repository.insert_batch(
                    target_id, result.rows[start : start + self._batch_size]
                )
                await context.report_progress(
                    min(95, int((start + self._batch_size) / max(1, len(result.rows)) * 95))
                )
            await context.report_progress(99)
            await self._repository.complete(
                run_id=run_id,
                target_version_id=target_id,
                policy=policy,
                summary=result.summary,
                rows=result.rows,
            )
        except JobCancellationRequested:
            await self._repository.fail(run_id=run_id, target_version_id=target_id, cancelled=True)
            raise
        except BaseException:
            await self._repository.fail(run_id=run_id, target_version_id=target_id, cancelled=False)
            raise
        return {**result.summary, "target_version_id": str(target_id), "run_id": str(run_id)}


def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Transformation payload is missing {key}")
    return value
