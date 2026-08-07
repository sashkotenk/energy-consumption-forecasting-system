from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from energy_forecast.database import (
    SqlAlchemyExperimentRepository,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.database.models import Dataset, DatasetVersion, Experiment, Job, ModelRun
from energy_forecast.database.session import transactional_session
from energy_forecast.experiments.models import ExperimentDefinition
from energy_forecast.ml.registry import AlgorithmType
from tests.integration.conftest import upgrade_database


@pytest.mark.integration
def test_stage_experiment_creates_one_job_and_immutable_model_run_configuration(
    temporary_database_url: str,
) -> None:
    upgrade_database(temporary_database_url)
    result = asyncio.run(_stage_and_inspect(temporary_database_url))

    assert result == {
        "job_type": "experiment",
        "job_status": "queued",
        "experiment_status": "queued",
        "algorithms": ("ridge", "seasonal_naive_24"),
        "model_run_count": 2,
        "selection_rule": "cv-mae-1pct-std-5pct-time-simplicity/v1",
    }


async def _stage_and_inspect(database_url: str) -> dict[str, object]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    dataset_id, version_id = uuid4(), uuid4()
    try:
        async with transactional_session(factory) as session:
            session.add(Dataset(id=dataset_id, name="Experiment fixture"))
            session.add(
                DatasetVersion(
                    id=version_id,
                    dataset_id=dataset_id,
                    version_no=1,
                    status="ready",
                    timezone_context="UTC",
                    interval_seconds=3600,
                    quality_policy={},
                    transformation_manifest={"schema_version": "transformation-manifest/v1"},
                )
            )
        staged = await SqlAlchemyExperimentRepository(factory).stage(
            ExperimentDefinition(
                dataset_version_id=version_id,
                name="Models for the report",
                algorithms=(AlgorithmType.RIDGE, AlgorithmType.SEASONAL_NAIVE_24),
            ),
            code_commit="abcdef1",
        )
        async with transactional_session(factory) as session:
            experiment = await session.get(Experiment, staged.experiment_id)
            job = await session.get(Job, staged.job_id)
            assert experiment is not None
            assert job is not None
            algorithms = tuple(
                (
                    await session.scalars(
                        select(ModelRun.algorithm)
                        .where(ModelRun.experiment_id == staged.experiment_id)
                        .order_by(ModelRun.algorithm)
                    )
                ).all()
            )
            count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(ModelRun)
                    .where(ModelRun.experiment_id == staged.experiment_id)
                )
                or 0
            )
            return {
                "job_type": job.job_type,
                "job_status": job.status,
                "experiment_status": experiment.status,
                "algorithms": algorithms,
                "model_run_count": count,
                "selection_rule": experiment.selection_rule_version,
            }
    finally:
        await engine.dispose()
