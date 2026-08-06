from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select

from energy_forecast.database import (
    create_database_engine,
    create_session_factory,
    transactional_session,
)
from energy_forecast.database.models import Dataset
from energy_forecast.database.repositories import DatasetRepository
from tests.integration.conftest import upgrade_database

pytestmark = pytest.mark.integration


async def _exercise_repository_transactions(database_url: str) -> None:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with transactional_session(factory) as session:
            repository = DatasetRepository(session)
            dataset = Dataset(name="Synthetic demonstration dataset")
            await repository.add(dataset)
            dataset_id = dataset.id

        async with transactional_session(factory) as session:
            stored = await DatasetRepository(session).get(dataset_id)
            assert stored is not None
            assert stored.name == "Synthetic demonstration dataset"

        with pytest.raises(RuntimeError, match="rollback demonstration"):
            async with transactional_session(factory) as session:
                await DatasetRepository(session).add(Dataset(name="Must be rolled back"))
                raise RuntimeError("rollback demonstration")

        async with transactional_session(factory) as session:
            count = await session.scalar(select(func.count()).select_from(Dataset))
            assert count == 1
    finally:
        await engine.dispose()


def test_repository_uses_explicit_commit_and_rollback_boundaries(
    temporary_database_url: str,
) -> None:
    upgrade_database(temporary_database_url)
    asyncio.run(_exercise_repository_transactions(temporary_database_url))
