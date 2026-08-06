"""Application service coordinating artifact bytes and metadata."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import BinaryIO
from uuid import UUID

from energy_forecast.artifacts.models import (
    ArtifactContentMissingError,
    ArtifactMetadata,
    ArtifactNotFoundError,
    ArtifactPurpose,
)
from energy_forecast.artifacts.ports import ArtifactMetadataRepository, ArtifactStore


class ArtifactService:
    """Expose controlled artifact operations to API and worker application services."""

    def __init__(
        self,
        store: ArtifactStore,
        metadata: ArtifactMetadataRepository,
    ) -> None:
        self._store = store
        self._metadata = metadata

    async def create(
        self,
        stream: BinaryIO,
        *,
        purpose: ArtifactPurpose,
        media_type: str,
        suffix: str = "",
        original_name: str | None = None,
    ) -> ArtifactMetadata:
        """Write bytes before opening a short metadata transaction."""
        self._validate_metadata(media_type=media_type, original_name=original_name)
        stored = await asyncio.to_thread(self._store.put, stream, suffix=suffix)
        try:
            return await self._metadata.add(
                stored,
                purpose=purpose,
                media_type=media_type,
                original_name=original_name,
            )
        except BaseException:
            await asyncio.to_thread(self._store.delete, stored.storage_key)
            raise

    async def open(self, artifact_id: UUID) -> BinaryIO:
        """Resolve metadata to an internal key and return a read stream."""
        metadata = await self._metadata.get(artifact_id)
        if metadata is None:
            raise ArtifactNotFoundError("Artifact metadata was not found")
        try:
            return self._store.open(metadata.storage_key)
        except FileNotFoundError as error:
            raise ArtifactContentMissingError("Artifact content is unavailable") from error

    async def find_by_sha256(self, sha256: str) -> Sequence[ArtifactMetadata]:
        """Identify every artifact row that has the given content checksum."""
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ValueError("SHA-256 must contain 64 lowercase hexadecimal characters")
        return await self._metadata.find_by_sha256(sha256)

    async def delete(self, artifact_id: UUID) -> None:
        """Remove metadata only after its DB references are checked, then clean up bytes."""
        metadata = await self._metadata.delete_if_unreferenced(artifact_id)
        if metadata is None:
            raise ArtifactNotFoundError("Artifact metadata was not found")
        await asyncio.to_thread(self._store.delete, metadata.storage_key)

    @staticmethod
    def _validate_metadata(*, media_type: str, original_name: str | None) -> None:
        if not media_type or len(media_type) > 120 or any(ord(char) < 32 for char in media_type):
            raise ValueError("media_type must be a non-empty safe value up to 120 characters")
        if original_name is not None and len(original_name) > 255:
            raise ValueError("original_name must not exceed 255 characters")
