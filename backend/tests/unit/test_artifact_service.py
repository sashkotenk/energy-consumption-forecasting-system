from __future__ import annotations

import asyncio
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from uuid import UUID

from energy_forecast.artifacts import (
    ArtifactMetadata,
    ArtifactPurpose,
    ArtifactService,
    LocalArtifactStore,
)
from energy_forecast.artifacts.models import StoredArtifact
from energy_forecast.artifacts.ports import ArtifactMetadataRepository


class FailingMetadataRepository(ArtifactMetadataRepository):
    async def add(
        self,
        stored: StoredArtifact,
        *,
        purpose: ArtifactPurpose,
        media_type: str,
        original_name: str | None,
    ) -> ArtifactMetadata:
        raise RuntimeError("simulated metadata failure")

    async def get(self, artifact_id: UUID) -> ArtifactMetadata | None:
        raise AssertionError("not used")

    async def find_by_sha256(self, sha256: str) -> Sequence[ArtifactMetadata]:
        raise AssertionError("not used")

    async def delete_if_unreferenced(self, artifact_id: UUID) -> ArtifactMetadata | None:
        raise AssertionError("not used")


def test_metadata_failure_compensates_completed_file_write(tmp_path: Path) -> None:
    service = ArtifactService(LocalArtifactStore(tmp_path), FailingMetadataRepository())

    async def exercise() -> None:
        try:
            await service.create(
                BytesIO(b"must be removed"),
                purpose=ArtifactPurpose.OTHER,
                media_type="application/octet-stream",
            )
        except RuntimeError as error:
            assert str(error) == "simulated metadata failure"
        else:
            raise AssertionError("metadata failure must propagate")

    asyncio.run(exercise())
    assert list(tmp_path.iterdir()) == []
