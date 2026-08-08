"""PostgreSQL/TimescaleDB persistence for immutable transformation runs."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from energy_forecast.database.models import (
    Dataset,
    DatasetVersion,
    HourlyObservation,
    Job,
    RawMeasurement,
    TransformationRun,
)
from energy_forecast.database.session import AsyncSessionFactory, transactional_session
from energy_forecast.transformations.models import (
    HourlyValue,
    HourQualityStatus,
    SourceMeasurement,
    SourceVersionNotReadyError,
    StagedTransformation,
    TransformationPolicy,
)

_INTERVAL_INFERENCE_SAMPLE_SIZE = 4_097


class SqlAlchemyTransformationRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def stage(
        self, source_version_id: UUID, policy: TransformationPolicy
    ) -> StagedTransformation:
        async with transactional_session(self._session_factory) as session:
            source = await session.scalar(
                select(DatasetVersion)
                .where(DatasetVersion.id == source_version_id)
                .with_for_update()
            )
            if source is None or source.status != "ready_for_transformation":
                raise SourceVersionNotReadyError("Dataset version is not ready for transformation")
            await session.scalar(
                select(Dataset).where(Dataset.id == source.dataset_id).with_for_update()
            )
            version_no = (
                int(
                    await session.scalar(
                        select(func.coalesce(func.max(DatasetVersion.version_no), 0)).where(
                            DatasetVersion.dataset_id == source.dataset_id
                        )
                    )
                    or 0
                )
                + 1
            )
            run_id, job_id, target_id = uuid4(), uuid4(), uuid4()
            policy_values = policy.as_dict()
            target = DatasetVersion(
                id=target_id,
                dataset_id=source.dataset_id,
                parent_version_id=source.id,
                version_no=version_no,
                status="transforming",
                raw_artifact_id=source.raw_artifact_id,
                source_sha256=None,
                timezone_context=source.timezone_context,
                interval_seconds=3600,
                quality_policy=dict(source.quality_policy),
                transformation_manifest={
                    "schema_version": "transformation-manifest/v1",
                    "source_version_id": str(source.id),
                    "policy": policy_values,
                },
            )
            job = Job(
                id=job_id,
                job_type="data_transformation",
                status="queued",
                priority=0,
                payload={
                    "transformation_run_id": str(run_id),
                    "source_version_id": str(source.id),
                    "target_version_id": str(target_id),
                    "policy": policy_values,
                },
                progress_pct=0,
                attempt=0,
                max_attempts=3,
            )
            run = TransformationRun(
                id=run_id,
                source_version_id=source.id,
                target_version_id=target_id,
                job_id=job_id,
                status="queued",
                policy=policy_values,
            )
            session.add_all((target, job))
            await session.flush()
            session.add(run)
            await session.flush()
            return StagedTransformation(run_id, job_id, source.id, target_id)

    async def prepare(self, *, run_id: UUID, job_id: UUID) -> tuple[UUID, UUID, int, str | None]:
        async with transactional_session(self._session_factory) as session:
            run = await session.scalar(
                select(TransformationRun).where(TransformationRun.id == run_id).with_for_update()
            )
            if run is None or run.job_id != job_id or run.target_version_id is None:
                raise ValueError("Transformation payload references inconsistent resources")
            source = await session.get(DatasetVersion, run.source_version_id)
            target = await session.get(DatasetVersion, run.target_version_id)
            if source is None or target is None:
                raise ValueError("Transformation source metadata is incomplete")
            interval_seconds = source.interval_seconds
            if interval_seconds is None:
                interval_seconds = await _infer_source_interval_seconds(
                    session, source_version_id=source.id
                )
            if interval_seconds is None:
                raise ValueError(
                    "Transformation source interval is unknown; provide interval_seconds during "
                    "import or use a regular timestamp cadence that can be inferred"
                )
            await session.execute(
                delete(HourlyObservation).where(
                    HourlyObservation.dataset_version_id == run.target_version_id
                )
            )
            run.status = "running"
            run.summary = None
            run.completed_at = None
            target.status = "transforming"
            target.row_count = None
            target.valid_row_count = None
            return source.id, target.id, interval_seconds, source.timezone_context

    async def load_source(self, source_version_id: UUID) -> tuple[SourceMeasurement, ...]:
        async with transactional_session(self._session_factory) as session:
            rows = (
                await session.scalars(
                    select(RawMeasurement)
                    .where(RawMeasurement.dataset_version_id == source_version_id)
                    .order_by(RawMeasurement.observed_at, RawMeasurement.source_row_number)
                )
            ).all()
            return tuple(
                SourceMeasurement(
                    observed_at=row.observed_at,
                    source_row_number=row.source_row_number,
                    interval_seconds=row.interval_seconds,
                    energy_kwh=row.energy_kwh,
                    active_power_kw=row.active_power_kw,
                    reactive_power_kw=row.reactive_power_kw,
                    voltage_v=row.voltage_v,
                    current_a=row.current_a,
                    parse_status=row.parse_status,
                    quality_flags=tuple(row.quality_flags),
                )
                for row in rows
            )

    async def insert_batch(self, target_version_id: UUID, rows: tuple[HourlyValue, ...]) -> None:
        if not rows:
            return
        async with transactional_session(self._session_factory) as session:
            await session.execute(
                insert(HourlyObservation),
                [_hourly_values(target_version_id, row) for row in rows],
            )

    async def complete(
        self,
        *,
        run_id: UUID,
        target_version_id: UUID,
        policy: TransformationPolicy,
        summary: dict[str, object],
        rows: tuple[HourlyValue, ...],
    ) -> None:
        async with transactional_session(self._session_factory) as session:
            run = await session.get(TransformationRun, run_id)
            target = await session.get(DatasetVersion, target_version_id)
            if run is None or target is None:
                raise ValueError("Transformation disappeared before completion")
            now = datetime.now(UTC)
            run.status = "completed"
            run.summary = summary
            run.completed_at = now
            target.status = "ready"
            target.row_count = len(rows)
            target.valid_row_count = sum(
                row.quality_status
                in {HourQualityStatus.COMPLETE, HourQualityStatus.IMPUTED_SHORT_GAP}
                for row in rows
            )
            target.min_timestamp = rows[0].hour_start if rows else None
            target.max_timestamp = rows[-1].hour_start if rows else None
            target.transformation_manifest = {
                "schema_version": "transformation-manifest/v1",
                "source_version_id": str(run.source_version_id),
                "run_id": str(run.id),
                "policy": policy.as_dict(),
                "summary": summary,
            }

    async def fail(self, *, run_id: UUID, target_version_id: UUID, cancelled: bool) -> None:
        async with transactional_session(self._session_factory) as session:
            run = await session.get(TransformationRun, run_id)
            target = await session.get(DatasetVersion, target_version_id)
            if run is not None:
                run.status = "cancelled" if cancelled else "failed"
                run.completed_at = datetime.now(UTC)
            if target is not None:
                target.status = "failed"


async def _infer_source_interval_seconds(
    session: AsyncSession, *, source_version_id: UUID
) -> int | None:
    timestamps = (
        await session.scalars(
            select(RawMeasurement.observed_at)
            .where(RawMeasurement.dataset_version_id == source_version_id)
            .distinct()
            .order_by(RawMeasurement.observed_at)
            .limit(_INTERVAL_INFERENCE_SAMPLE_SIZE)
        )
    ).all()
    if len(timestamps) < 2:
        return None

    deltas: list[int] = []
    for previous, current in pairwise(timestamps):
        seconds = (current - previous).total_seconds()
        if seconds <= 0 or not seconds.is_integer():
            return None
        deltas.append(int(seconds))

    candidates = Counter(
        delta for delta in deltas if delta <= 3600 and 3600 % delta == 0
    )
    if not candidates:
        return None
    interval_seconds, occurrences = candidates.most_common(1)[0]
    if occurrences * 2 < len(deltas):
        return None
    if any(delta % interval_seconds != 0 for delta in deltas):
        return None
    return interval_seconds


def _hourly_values(dataset_version_id: UUID, row: HourlyValue) -> dict[str, object]:
    return {
        "dataset_version_id": dataset_version_id,
        "hour_start": row.hour_start,
        "timezone_context": row.timezone_context,
        "energy_kwh": row.energy_kwh,
        "mean_active_power_kw": row.mean_active_power_kw,
        "mean_reactive_power_kw": row.mean_reactive_power_kw,
        "mean_voltage_v": row.mean_voltage_v,
        "min_voltage_v": row.min_voltage_v,
        "max_voltage_v": row.max_voltage_v,
        "mean_current_a": row.mean_current_a,
        "max_current_a": row.max_current_a,
        "observed_samples": row.observed_samples,
        "expected_samples": row.expected_samples,
        "coverage_ratio": row.coverage_ratio,
        "imputed_samples": row.imputed_samples,
        "max_missing_run": row.max_missing_run,
        "quality_status": row.quality_status.value,
        "quality_flags": list(row.quality_flags),
    }
