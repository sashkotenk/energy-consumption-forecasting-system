"""Forecast application records and controlled failures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from energy_forecast.ml.registry import AlgorithmType


@dataclass(frozen=True, slots=True)
class ForecastRequest:
    model_run_id: UUID
    dataset_version_id: UUID
    origin: datetime | None = None


@dataclass(frozen=True, slots=True)
class ForecastModelContext:
    model_run_id: UUID
    artifact_id: UUID
    algorithm: AlgorithmType
    implementation_version: str
    feature_schema_version: str
    training_dataset_version_id: UUID
    requested_dataset_version_id: UUID
    timezone: str


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    horizon: int
    target_time: datetime
    predicted_energy_kwh: float
    actual_energy_kwh: float | None = None


@dataclass(frozen=True, slots=True)
class ForecastComputation:
    origin: datetime
    points: tuple[ForecastPoint, ...]
    total_energy_kwh: float


@dataclass(frozen=True, slots=True)
class ForecastRecord:
    id: UUID
    model_run_id: UUID
    dataset_version_id: UUID
    artifact_id: UUID
    bundle_sha256: str
    algorithm: AlgorithmType
    feature_schema_version: str
    origin: datetime
    timezone: str
    status: str
    total_energy_kwh: float
    points: tuple[ForecastPoint, ...]
    created_at: datetime
    completed_at: datetime


@dataclass(frozen=True, slots=True)
class ForecastPage:
    items: tuple[ForecastRecord, ...]
    page: int
    page_size: int
    total: int


class ForecastError(Exception):
    """Base class for expected forecast failures."""


class ForecastNotFoundError(ForecastError, LookupError):
    """The forecast, model run, or dataset version does not exist."""


class ForecastModelUnavailableError(ForecastError):
    """The model run is incomplete or has no immutable artifact."""


class ForecastCompatibilityError(ForecastError):
    """The bundle is incompatible with the requested dataset/model/schema."""


class ForecastOriginError(ForecastError):
    """The origin is not an aware completed-hour boundary."""


class ForecastHistoryMissingError(ForecastError):
    """Required lag or rolling history is absent rather than silently filled."""
