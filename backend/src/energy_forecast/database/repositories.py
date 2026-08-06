"""Small persistence adapters built around caller-owned async sessions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from energy_forecast.database.models import Dataset


class DatasetRepository:
    """Persist dataset catalog rows without owning transaction boundaries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, dataset: Dataset) -> None:
        self._session.add(dataset)
        await self._session.flush()

    async def get(self, dataset_id: UUID) -> Dataset | None:
        return await self._session.get(Dataset, dataset_id)

    async def list_recent(self, *, limit: int = 100) -> list[Dataset]:
        statement = select(Dataset).order_by(Dataset.created_at.desc()).limit(limit)
        return list((await self._session.scalars(statement)).all())
