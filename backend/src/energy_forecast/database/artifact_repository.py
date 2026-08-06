"""PostgreSQL adapter for artifact metadata operations."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import exists, select

from energy_forecast.artifacts.models import (
    ArtifactInUseError,
    ArtifactMetadata,
    ArtifactPurpose,
    StoredArtifact,
)
from energy_forecast.database.models import Artifact, DatasetVersion, ModelRun
from energy_forecast.database.session import AsyncSessionFactory, transactional_session


class SqlAlchemyArtifactMetadataRepository:
    """Use one short transaction per metadata operation."""

    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def add(
        self,
        stored: StoredArtifact,
        *,
        purpose: ArtifactPurpose,
        media_type: str,
        original_name: str | None,
    ) -> ArtifactMetadata:
        async with transactional_session(self._session_factory) as session:
            row = Artifact(
                kind=purpose.value,
                storage_key=stored.storage_key,
                original_name=original_name,
                media_type=media_type,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
            )
            session.add(row)
            await session.flush()
            return _to_metadata(row)

    async def get(self, artifact_id: UUID) -> ArtifactMetadata | None:
        async with transactional_session(self._session_factory) as session:
            row = await session.get(Artifact, artifact_id)
            return None if row is None else _to_metadata(row)

    async def find_by_sha256(self, sha256: str) -> Sequence[ArtifactMetadata]:
        async with transactional_session(self._session_factory) as session:
            statement = (
                select(Artifact).where(Artifact.sha256 == sha256).order_by(Artifact.created_at)
            )
            rows = (await session.scalars(statement)).all()
            return tuple(_to_metadata(row) for row in rows)

    async def delete_if_unreferenced(self, artifact_id: UUID) -> ArtifactMetadata | None:
        async with transactional_session(self._session_factory) as session:
            statement = select(Artifact).where(Artifact.id == artifact_id).with_for_update()
            row = await session.scalar(statement)
            if row is None:
                return None

            dataset_reference = await session.scalar(
                select(exists().where(DatasetVersion.raw_artifact_id == artifact_id))
            )
            model_reference = await session.scalar(
                select(exists().where(ModelRun.artifact_id == artifact_id))
            )
            if dataset_reference or model_reference:
                raise ArtifactInUseError("Artifact is referenced and cannot be deleted")

            metadata = _to_metadata(row)
            await session.delete(row)
            await session.flush()
            return metadata


def _to_metadata(row: Artifact) -> ArtifactMetadata:
    return ArtifactMetadata(
        id=row.id,
        purpose=ArtifactPurpose(row.kind),
        storage_key=row.storage_key,
        original_name=row.original_name,
        media_type=row.media_type,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        created_at=row.created_at,
    )
