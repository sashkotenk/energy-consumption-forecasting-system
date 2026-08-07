"""Framework-independent values and controlled errors for datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ImportProfile(StrEnum):
    UCI = "uci"
    GENERIC_CSV = "generic_csv"


class DatasetImportStatus(StrEnum):
    STAGED = "staged"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DatasetRecord:
    id: UUID
    name: str
    description: str | None
    version_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DatasetPage:
    items: tuple[DatasetRecord, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class DatasetChanges:
    set_name: bool = False
    name: str | None = None
    set_description: bool = False
    description: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetImportRecord:
    id: UUID
    dataset_id: UUID
    dataset_version_id: UUID
    job_id: UUID
    import_profile: ImportProfile
    status: DatasetImportStatus
    import_options: dict[str, Any]
    detected_format: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class StagedDatasetImport:
    import_record: DatasetImportRecord
    artifact_id: UUID
    artifact_sha256: str


class DatasetError(Exception):
    """Base class for controlled dataset failures."""


class DatasetNotFoundError(DatasetError):
    """The requested dataset or import does not exist."""


class DatasetInUseError(DatasetError):
    """Dataset metadata has dependent imports or versions."""


class DatasetSourceConflictError(DatasetError):
    """The same immutable source is already staged for this dataset."""


class DatasetUploadError(DatasetError, ValueError):
    """Uploaded bytes do not satisfy the staging contract."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class UploadTooLargeError(DatasetUploadError):
    def __init__(self, limit: int) -> None:
        super().__init__(
            "dataset_upload_too_large",
            f"Файл перевищує дозволений розмір {limit} байтів.",
        )
