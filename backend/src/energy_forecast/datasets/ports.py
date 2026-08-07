"""Ports owned by the dataset application boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from energy_forecast.artifacts.models import ArtifactMetadata
from energy_forecast.datasets.models import (
    DatasetChanges,
    DatasetImportRecord,
    DatasetPage,
    DatasetRecord,
    ImportProfile,
)


class DatasetCatalogRepository(Protocol):
    async def create(self, *, name: str, description: str | None) -> DatasetRecord: ...

    async def list(self, *, page: int, page_size: int) -> DatasetPage: ...

    async def get(self, dataset_id: UUID) -> DatasetRecord | None: ...

    async def update(self, dataset_id: UUID, changes: DatasetChanges) -> DatasetRecord | None: ...

    async def delete_if_empty(self, dataset_id: UUID) -> bool: ...

    async def stage_import(
        self,
        *,
        dataset_id: UUID,
        artifact: ArtifactMetadata,
        import_profile: ImportProfile,
        import_options: Mapping[str, Any],
        detected_format: Mapping[str, Any],
        preview: Mapping[str, Any],
    ) -> DatasetImportRecord: ...

    async def get_import(self, import_id: UUID) -> DatasetImportRecord | None: ...
