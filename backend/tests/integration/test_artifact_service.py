from __future__ import annotations

import asyncio
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from energy_forecast.artifacts import (
    ArtifactInUseError,
    ArtifactNotFoundError,
    ArtifactPurpose,
    ArtifactService,
    LocalArtifactStore,
)
from energy_forecast.database import (
    SqlAlchemyArtifactMetadataRepository,
    create_database_engine,
    create_session_factory,
    transactional_session,
)
from energy_forecast.database.models import Artifact, Dataset, DatasetVersion
from tests.integration.conftest import upgrade_database

pytestmark = pytest.mark.integration


class InterruptedStream(BytesIO):
    def __init__(self) -> None:
        super().__init__(b"partial bytes")
        self._reads = 0

    def read(self, size: int | None = -1) -> bytes:
        self._reads += 1
        if self._reads == 2:
            raise OSError("stream interrupted")
        return super().read(4)


async def _exercise_artifact_service(database_url: str, artifact_root: Path) -> None:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    store = LocalArtifactStore(artifact_root)
    service = ArtifactService(store, SqlAlchemyArtifactMetadataRepository(factory))
    content = b"timestamp,energy_kwh\n2026-01-01T00:00:00Z,1.5\n"

    try:
        first = await service.create(
            BytesIO(content),
            purpose=ArtifactPurpose.RAW_DATASET,
            media_type="text/csv",
            suffix=".csv",
            original_name="../../household.csv",
        )
        second = await service.create(
            BytesIO(content),
            purpose=ArtifactPurpose.RAW_DATASET,
            media_type="text/csv",
            suffix=".csv",
        )

        assert first.id != second.id
        assert first.storage_key != second.storage_key
        assert first.purpose is ArtifactPurpose.RAW_DATASET
        assert first.original_name == "../../household.csv"
        assert first.size_bytes == len(content)
        assert first.sha256 == sha256(content).hexdigest()
        assert first.created_at.tzinfo is not None
        assert str(artifact_root.resolve()) not in repr(first)

        matches = await service.find_by_sha256(first.sha256)
        assert {metadata.id for metadata in matches} == {first.id, second.id}

        with await service.open(first.id) as artifact_stream:
            assert artifact_stream.read() == content

        async with transactional_session(factory) as session:
            dataset = Dataset(name="Artifact reference test")
            session.add(dataset)
            await session.flush()
            session.add(
                DatasetVersion(
                    dataset_id=dataset.id,
                    version_no=1,
                    status="uploaded",
                    raw_artifact_id=first.id,
                )
            )

        with pytest.raises(ArtifactInUseError):
            await service.delete(first.id)
        with await service.open(first.id) as artifact_stream:
            assert artifact_stream.read() == content

        await service.delete(second.id)
        with pytest.raises(ArtifactNotFoundError):
            await service.open(second.id)
        with pytest.raises(ArtifactNotFoundError):
            await service.delete(uuid4())

        async with transactional_session(factory) as session:
            count_before = await session.scalar(select(func.count()).select_from(Artifact))
        with pytest.raises(OSError, match="stream interrupted"):
            await service.create(
                InterruptedStream(),
                purpose=ArtifactPurpose.OTHER,
                media_type="application/octet-stream",
            )
        async with transactional_session(factory) as session:
            count_after = await session.scalar(select(func.count()).select_from(Artifact))

        assert count_before == count_after == 1
        assert all(not path.name.startswith(".write-") for path in artifact_root.iterdir())
    finally:
        await engine.dispose()


def test_artifact_lifecycle_with_postgresql_and_filesystem(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    asyncio.run(_exercise_artifact_service(temporary_database_url, tmp_path / "artifacts"))
