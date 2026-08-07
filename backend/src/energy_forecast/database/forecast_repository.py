"""PostgreSQL persistence for completed 24-point forecasts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
from sqlalchemy import func, select

from energy_forecast.database.models import (
    Artifact,
    DatasetVersion,
    Experiment,
    Forecast,
    HourlyObservation,
    ModelRun,
)
from energy_forecast.database.models import (
    ForecastPoint as ForecastPointRow,
)
from energy_forecast.database.session import AsyncSessionFactory, transactional_session
from energy_forecast.forecasting.models import (
    ForecastComputation,
    ForecastModelContext,
    ForecastModelUnavailableError,
    ForecastNotFoundError,
    ForecastPage,
    ForecastPoint,
    ForecastRecord,
    ForecastRequest,
)
from energy_forecast.ml.registry import AlgorithmRegistry, AlgorithmType


class SqlAlchemyForecastRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def prepare(self, request: ForecastRequest) -> ForecastModelContext:
        async with transactional_session(self._session_factory) as session:
            run = await session.get(ModelRun, request.model_run_id)
            version = await session.get(DatasetVersion, request.dataset_version_id)
            if run is None or version is None:
                raise ForecastNotFoundError("Model run or dataset version was not found")
            experiment = await session.get(Experiment, run.experiment_id)
            if experiment is None:
                raise ForecastNotFoundError("Model experiment was not found")
            if run.status != "completed" or run.artifact_id is None:
                raise ForecastModelUnavailableError(
                    "Model run must be completed and reference an immutable bundle"
                )
            if version.status != "ready" or version.interval_seconds != 3600:
                raise ForecastModelUnavailableError(
                    "Dataset version must be a ready hourly version"
                )
            algorithm = AlgorithmType(run.algorithm)
            return ForecastModelContext(
                model_run_id=run.id,
                artifact_id=run.artifact_id,
                algorithm=algorithm,
                implementation_version=AlgorithmRegistry().get(algorithm).implementation_version,
                feature_schema_version=experiment.feature_schema_version,
                training_dataset_version_id=experiment.dataset_version_id,
                requested_dataset_version_id=version.id,
                timezone=version.timezone_context or "UTC",
            )

    async def load_hourly(self, dataset_version_id: UUID) -> pd.DataFrame:
        async with transactional_session(self._session_factory) as session:
            rows = (
                await session.scalars(
                    select(HourlyObservation)
                    .where(HourlyObservation.dataset_version_id == dataset_version_id)
                    .order_by(HourlyObservation.hour_start)
                )
            ).all()
        return pd.DataFrame(
            {
                "energy_kwh": [row.energy_kwh for row in rows],
                "coverage_ratio": [row.coverage_ratio for row in rows],
                "quality_status": [row.quality_status for row in rows],
            },
            index=pd.DatetimeIndex([row.hour_start for row in rows]),
        )

    async def save(
        self,
        context: ForecastModelContext,
        computation: ForecastComputation,
        *,
        bundle_sha256: str,
    ) -> ForecastRecord:
        if len(computation.points) != 24:
            raise ValueError("A completed forecast requires exactly 24 points")
        async with transactional_session(self._session_factory) as session:
            now = datetime.now(UTC)
            row = Forecast(
                id=uuid4(),
                model_run_id=context.model_run_id,
                dataset_version_id=context.requested_dataset_version_id,
                origin=computation.origin,
                status="completed",
                total_energy_kwh=computation.total_energy_kwh,
                completed_at=now,
            )
            session.add(row)
            await session.flush()
            session.add_all(
                ForecastPointRow(
                    forecast_id=row.id,
                    horizon=point.horizon,
                    target_time=point.target_time,
                    predicted_energy_kwh=point.predicted_energy_kwh,
                    actual_energy_kwh=point.actual_energy_kwh,
                )
                for point in computation.points
            )
            await session.flush()
            return ForecastRecord(
                id=row.id,
                model_run_id=context.model_run_id,
                dataset_version_id=context.requested_dataset_version_id,
                artifact_id=context.artifact_id,
                bundle_sha256=bundle_sha256,
                algorithm=context.algorithm,
                feature_schema_version=context.feature_schema_version,
                origin=computation.origin,
                timezone=context.timezone,
                status="completed",
                total_energy_kwh=computation.total_energy_kwh,
                points=computation.points,
                created_at=row.created_at,
                completed_at=now,
            )

    async def get(self, forecast_id: UUID) -> ForecastRecord:
        async with transactional_session(self._session_factory) as session:
            row = await session.get(Forecast, forecast_id)
            if row is None:
                raise ForecastNotFoundError("Forecast was not found")
            return await self._record(session, row)

    async def list(self, *, page: int, page_size: int) -> ForecastPage:
        async with transactional_session(self._session_factory) as session:
            total = int(await session.scalar(select(func.count()).select_from(Forecast)) or 0)
            rows = (
                await session.scalars(
                    select(Forecast)
                    .order_by(Forecast.created_at.desc(), Forecast.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            records = []
            for row in rows:
                records.append(await self._record(session, row))
            return ForecastPage(tuple(records), page, page_size, total)

    async def _record(self, session: Any, row: Forecast) -> ForecastRecord:
        run = await session.get(ModelRun, row.model_run_id)
        version = await session.get(DatasetVersion, row.dataset_version_id)
        if run is None or version is None or run.artifact_id is None:
            raise ValueError("Forecast provenance is incomplete")
        artifact = await session.get(Artifact, run.artifact_id)
        experiment = await session.get(Experiment, run.experiment_id)
        if artifact is None or experiment is None or row.completed_at is None:
            raise ValueError("Forecast provenance metadata is incomplete")
        points = (
            await session.scalars(
                select(ForecastPointRow)
                .where(ForecastPointRow.forecast_id == row.id)
                .order_by(ForecastPointRow.horizon)
            )
        ).all()
        if row.total_energy_kwh is None:
            raise ValueError("Completed forecast is missing its total")
        return ForecastRecord(
            id=row.id,
            model_run_id=row.model_run_id,
            dataset_version_id=row.dataset_version_id,
            artifact_id=artifact.id,
            bundle_sha256=artifact.sha256,
            algorithm=AlgorithmType(run.algorithm),
            feature_schema_version=experiment.feature_schema_version,
            origin=row.origin,
            timezone=version.timezone_context or "UTC",
            status=row.status,
            total_energy_kwh=row.total_energy_kwh,
            points=tuple(
                ForecastPoint(
                    horizon=point.horizon,
                    target_time=point.target_time,
                    predicted_energy_kwh=point.predicted_energy_kwh,
                    actual_energy_kwh=point.actual_energy_kwh,
                )
                for point in points
            ),
            created_at=row.created_at,
            completed_at=row.completed_at,
        )
