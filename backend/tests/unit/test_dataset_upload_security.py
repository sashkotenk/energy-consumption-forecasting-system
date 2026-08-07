from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.models import (
    ArtifactMetadata,
    ArtifactPurpose,
    StoredArtifact,
)
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.datasets.models import (
    DatasetChanges,
    DatasetImportRecord,
    DatasetImportStatus,
    DatasetPage,
    DatasetRecord,
    DatasetUploadError,
    ImportProfile,
    UploadTooLargeError,
)
from energy_forecast.datasets.service import DatasetService


class MemoryArtifactMetadataRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, ArtifactMetadata] = {}

    async def add(
        self,
        stored: StoredArtifact,
        *,
        purpose: ArtifactPurpose,
        media_type: str,
        original_name: str | None,
    ) -> ArtifactMetadata:
        item = ArtifactMetadata(
            id=uuid4(),
            purpose=purpose,
            storage_key=stored.storage_key,
            original_name=original_name,
            media_type=media_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            created_at=datetime.now(UTC),
        )
        self.items[item.id] = item
        return item

    async def get(self, artifact_id: UUID) -> ArtifactMetadata | None:
        return self.items.get(artifact_id)

    async def find_by_sha256(self, sha256: str) -> Sequence[ArtifactMetadata]:
        return tuple(item for item in self.items.values() if item.sha256 == sha256)

    async def delete_if_unreferenced(self, artifact_id: UUID) -> ArtifactMetadata | None:
        return self.items.pop(artifact_id, None)


class MemoryDatasetRepository:
    def __init__(self) -> None:
        self.dataset = DatasetRecord(
            id=uuid4(),
            name="Meter readings",
            description=None,
            version_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.staged: DatasetImportRecord | None = None

    async def create(self, *, name: str, description: str | None) -> DatasetRecord:
        raise NotImplementedError

    async def list(self, *, page: int, page_size: int) -> DatasetPage:
        raise NotImplementedError

    async def get(self, dataset_id: UUID) -> DatasetRecord | None:
        return self.dataset if dataset_id == self.dataset.id else None

    async def update(self, dataset_id: UUID, changes: DatasetChanges) -> DatasetRecord | None:
        raise NotImplementedError

    async def delete_if_empty(self, dataset_id: UUID) -> bool:
        raise NotImplementedError

    async def stage_import(
        self,
        *,
        dataset_id: UUID,
        artifact: ArtifactMetadata,
        import_profile: ImportProfile,
        import_options: Mapping[str, Any],
        detected_format: Mapping[str, Any],
    ) -> DatasetImportRecord:
        self.staged = DatasetImportRecord(
            id=uuid4(),
            dataset_id=dataset_id,
            dataset_version_id=uuid4(),
            job_id=uuid4(),
            import_profile=import_profile,
            status=DatasetImportStatus.QUEUED,
            import_options=dict(import_options),
            detected_format=dict(detected_format),
            created_at=datetime.now(UTC),
        )
        return self.staged

    async def get_import(self, import_id: UUID) -> DatasetImportRecord | None:
        return self.staged if self.staged is not None and self.staged.id == import_id else None


def _service(
    artifact_root: Path, *, max_upload_bytes: int = 314_572_800
) -> tuple[DatasetService, MemoryDatasetRepository, MemoryArtifactMetadataRepository]:
    datasets = MemoryDatasetRepository()
    metadata = MemoryArtifactMetadataRepository()
    service = DatasetService(
        datasets,
        ArtifactService(LocalArtifactStore(artifact_root), metadata),
        max_upload_bytes=max_upload_bytes,
    )
    return service, datasets, metadata


def test_staging_sanitizes_filename_and_persists_actual_checksum(tmp_path: Path) -> None:
    service, datasets, metadata = _service(tmp_path)
    content = b"timestamp;value\n2026-01-01 00:00;1.25\n"

    staged = asyncio.run(
        service.stage_import(
            dataset_id=datasets.dataset.id,
            stream=BytesIO(content),
            original_name=r"..\..\meter.CSV",
            import_profile=ImportProfile.UCI,
            import_options={},
        )
    )

    artifact = metadata.items[staged.artifact_id]
    assert artifact.original_name == "meter.CSV"
    assert artifact.storage_key != artifact.original_name
    assert "/" not in artifact.storage_key and "\\" not in artifact.storage_key
    assert artifact.sha256 == hashlib.sha256(content).hexdigest()
    assert artifact.size_bytes == len(content)
    assert (tmp_path / artifact.storage_key).read_bytes() == content
    assert datasets.staged is not None
    assert datasets.staged.detected_format == {
        "encoding": "utf-8",
        "delimiter": ";",
        "column_count": 2,
    }


@pytest.mark.parametrize(
    ("filename", "content", "expected_code"),
    [
        ("empty.csv", b"", "dataset_upload_empty"),
        ("data.exe", b"timestamp,value\n2026-01-01,1\n", "dataset_file_type_unsupported"),
        ("fake.csv", b"%PDF-1.7\nnot,csv\n", "dataset_content_unsupported"),
        ("page.csv", b"<html>\n<body>value</body>\n", "dataset_content_unsupported"),
        ("binary.txt", b"timestamp,value\nA,\x00B\n", "dataset_content_unsupported"),
        ("one-line.csv", b"timestamp,value", "dataset_content_unsupported"),
    ],
)
def test_staging_rejects_unsafe_or_non_csv_content(
    tmp_path: Path,
    filename: str,
    content: bytes,
    expected_code: str,
) -> None:
    service, datasets, metadata = _service(tmp_path)

    with pytest.raises(DatasetUploadError) as caught:
        asyncio.run(
            service.stage_import(
                dataset_id=datasets.dataset.id,
                stream=BytesIO(content),
                original_name=filename,
                import_profile=ImportProfile.GENERIC_CSV,
                import_options={},
            )
        )

    assert caught.value.code == expected_code
    assert metadata.items == {}
    assert list(tmp_path.iterdir()) == []


def test_staging_enforces_streamed_application_limit_and_cleans_partial_file(
    tmp_path: Path,
) -> None:
    service, datasets, metadata = _service(tmp_path, max_upload_bytes=24)
    content = b"timestamp,value\n2026-01-01,123456789\n"

    with pytest.raises(UploadTooLargeError):
        asyncio.run(
            service.stage_import(
                dataset_id=datasets.dataset.id,
                stream=BytesIO(content),
                original_name="readings.csv",
                import_profile=ImportProfile.GENERIC_CSV,
                import_options={"delimiter": ","},
            )
        )

    assert metadata.items == {}
    assert list(tmp_path.iterdir()) == []


def test_staging_rejects_unsafe_import_metadata(tmp_path: Path) -> None:
    service, datasets, metadata = _service(tmp_path)

    with pytest.raises(DatasetUploadError) as caught:
        asyncio.run(
            service.stage_import(
                dataset_id=datasets.dataset.id,
                stream=BytesIO(b"timestamp,value\n2026-01-01,1\n"),
                original_name="readings.csv",
                import_profile=ImportProfile.GENERIC_CSV,
                import_options={"timestamp_column": "timestamp\runsafe"},
            )
        )

    assert caught.value.code == "dataset_import_options_invalid"
    assert metadata.items == {}


def test_default_application_upload_limit_is_300_megabytes(tmp_path: Path) -> None:
    service, _, _ = _service(tmp_path)
    assert service._max_upload_bytes == 300 * 1024 * 1024
