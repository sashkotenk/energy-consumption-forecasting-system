"""Storage-independent artifact value objects and errors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ArtifactPurpose(StrEnum):
    """Supported artifact purposes, persisted as ``app.artifacts.kind``."""

    RAW_DATASET = "raw_dataset"
    MODEL = "model"
    METRICS = "metrics"
    PREDICTIONS = "predictions"
    FORECAST_EXPORT = "forecast_export"
    CHART = "chart"
    MANIFEST = "manifest"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Result of publishing bytes to an artifact store."""

    storage_key: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactMetadata:
    """Application representation of one persisted artifact row."""

    id: UUID
    purpose: ArtifactPurpose
    storage_key: str
    original_name: str | None
    media_type: str
    size_bytes: int
    sha256: str
    created_at: datetime


class ArtifactError(Exception):
    """Base class for controlled artifact failures."""


class UnsafeArtifactPathError(ArtifactError, ValueError):
    """A caller supplied an absolute path, traversal, or invalid suffix/key."""


class ArtifactNotFoundError(ArtifactError, LookupError):
    """No artifact metadata exists for the requested identifier."""


class ArtifactContentMissingError(ArtifactError, FileNotFoundError):
    """Metadata exists, but the corresponding stored bytes are unavailable."""


class ArtifactInUseError(ArtifactError):
    """An artifact is still referenced by persistent product data."""
