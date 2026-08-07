"""Framework-independent experiment records and controlled failures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from energy_forecast.ml.registry import AlgorithmType

SELECTION_RULE_V1 = "cv-mae-1pct-std-5pct-time-simplicity/v1"


class WeatherMode(StrEnum):
    WITHOUT_WEATHER = "W0"
    WITH_WEATHER = "W1"


class SensitivityMode(StrEnum):
    COMPLETE_ONLY = "complete_only"
    COVERAGE_90 = "coverage_90"


class ExperimentStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExperimentDefinition:
    dataset_version_id: UUID
    name: str
    algorithms: tuple[AlgorithmType, ...]
    weather_mode: WeatherMode = WeatherMode.WITHOUT_WEATHER
    sensitivity_mode: SensitivityMode = SensitivityMode.COMPLETE_ONLY

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name or len(normalized_name) > 160:
            raise ValueError("experiment name must contain between 1 and 160 characters")
        if not self.algorithms or len(set(self.algorithms)) != len(self.algorithms):
            raise ValueError("algorithms must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class StagedExperiment:
    experiment_id: UUID
    job_id: UUID
    status: ExperimentStatus


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    id: UUID
    dataset_version_id: UUID
    job_id: UUID
    name: str
    status: ExperimentStatus
    weather_mode: WeatherMode
    sensitivity_mode: SensitivityMode
    algorithms: tuple[AlgorithmType, ...]
    result_manifest: dict[str, Any] | None
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExperimentPage:
    items: tuple[ExperimentRecord, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class ExperimentWork:
    experiment_id: UUID
    job_id: UUID
    dataset_version_id: UUID
    algorithms: tuple[AlgorithmType, ...]
    model_run_ids: dict[AlgorithmType, UUID]
    weather_mode: WeatherMode
    sensitivity_mode: SensitivityMode
    timezone: str
    code_commit: str


class ExperimentError(Exception):
    """Base class for expected experiment failures."""


class ExperimentNotFoundError(ExperimentError, LookupError):
    """No experiment exists for an identifier."""


class DatasetVersionNotTrainableError(ExperimentError):
    """The selected version is not an immutable hourly version ready for training."""


class ExperimentConfigurationError(ExperimentError):
    """The requested mode is represented but cannot yet be executed truthfully."""


class ExperimentNotCancellableError(ExperimentError):
    """The experiment has already reached a terminal state."""
