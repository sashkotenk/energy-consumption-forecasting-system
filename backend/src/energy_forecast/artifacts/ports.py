"""Ports owned by the artifact application boundary."""

from __future__ import annotations

from collections.abc import Sequence
from typing import BinaryIO, Protocol
from uuid import UUID

from energy_forecast.artifacts.models import (
    ArtifactMetadata,
    ArtifactPurpose,
    StoredArtifact,
)


class ArtifactStore(Protocol):
    """Store bytes by generated opaque keys without exposing filesystem paths."""

    def put(self, stream: BinaryIO, *, suffix: str = "") -> StoredArtifact: ...

    def open(self, storage_key: str) -> BinaryIO: ...

    def delete(self, storage_key: str) -> bool: ...


class ArtifactMetadataRepository(Protocol):
    """Persist and query artifact metadata using short database transactions."""

    async def add(
        self,
        stored: StoredArtifact,
        *,
        purpose: ArtifactPurpose,
        media_type: str,
        original_name: str | None,
    ) -> ArtifactMetadata: ...

    async def get(self, artifact_id: UUID) -> ArtifactMetadata | None: ...

    async def find_by_sha256(self, sha256: str) -> Sequence[ArtifactMetadata]: ...

    async def delete_if_unreferenced(self, artifact_id: UUID) -> ArtifactMetadata | None: ...
