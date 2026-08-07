"""Framework-independent export records and controlled failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import BinaryIO

from energy_forecast.artifacts.models import ArtifactMetadata


class ForecastExportFormat(StrEnum):
    """Bounded export representations for one persisted forecast."""

    CSV = "csv"
    CHART_JSON = "chart_json"


class ExperimentExportFormat(StrEnum):
    """Bounded export representations for one experiment."""

    METRICS_CSV = "metrics_csv"
    METRICS_JSON = "metrics_json"
    MANIFEST_JSON = "manifest_json"


@dataclass(frozen=True, slots=True)
class ExportDownload:
    """Validated export metadata plus a controlled read stream."""

    metadata: ArtifactMetadata
    filename: str
    stream: BinaryIO


class ExportError(Exception):
    """Base class for expected export failures."""


class ExportSourceNotFoundError(ExportError, LookupError):
    """The forecast or experiment selected for export does not exist."""


class ExportSourceUnavailableError(ExportError):
    """The selected source has not reached an exportable terminal state."""


class ExportSourceFailedError(ExportError):
    """The selected experiment failed and has no successful result to export."""


class ExportArtifactNotFoundError(ExportError, LookupError):
    """No artifact metadata exists for the requested download identifier."""


class ExportArtifactPurposeError(ExportError):
    """The requested artifact is not a downloadable export purpose."""


class ExportArtifactUnavailableError(ExportError):
    """Export metadata exists, but its stored bytes are unavailable."""
