"""Checksum-verified lifecycle for trusted internal model bundles."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

import joblib
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from energy_forecast.artifacts.models import ArtifactMetadata, ArtifactPurpose
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.ml.features import FeatureSchema
from energy_forecast.ml.ports import Predictor
from energy_forecast.ml.registry import AlgorithmType

BUNDLE_FORMAT_VERSION = "model-bundle/v1"
BUNDLE_MEDIA_TYPE = "application/vnd.energyforecast.model-bundle+zip"
_MANIFEST_NAME = "manifest.json"
_MODEL_NAME = "model.joblib"
_MAX_MANIFEST_BYTES = 1024 * 1024


class ModelBundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal["model-bundle/v1"] = "model-bundle/v1"
    algorithm: AlgorithmType
    implementation_version: str = Field(min_length=1, max_length=80)
    forecast_horizon: Literal[24] = 24
    feature_schema_version: str = Field(min_length=1, max_length=80)
    feature_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_names: tuple[str, ...] = Field(min_length=1)
    training_dataset_version_id: UUID
    split_definition: str = Field(min_length=1, max_length=160)
    code_commit: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    random_seed: int
    created_at: datetime
    library_versions: dict[str, str]
    model_parameters: dict[str, JsonValue]
    quality_policy: dict[str, JsonValue]
    weather_mode: Literal["W0", "W1"]
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("created_at")
    @classmethod
    def _created_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class BundleManifestInput:
    algorithm: AlgorithmType
    implementation_version: str
    feature_schema: FeatureSchema
    training_dataset_version_id: UUID
    split_definition: str
    code_commit: str
    random_seed: int = 42
    model_parameters: dict[str, JsonValue] = field(default_factory=dict)
    quality_policy: dict[str, JsonValue] = field(default_factory=dict)
    weather_mode: Literal["W0", "W1"] = "W0"
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BundleCompatibilityPolicy:
    feature_schema_version: str
    feature_schema_sha256: str
    training_dataset_version_id: UUID | None = None
    algorithm: AlgorithmType | None = None
    implementation_version: str | None = None
    enforce_library_major_versions: bool = True


@dataclass(frozen=True, slots=True)
class SavedModelBundle:
    artifact_id: UUID
    bundle_sha256: str
    size_bytes: int
    manifest: ModelBundleManifest


@dataclass(frozen=True, slots=True)
class LoadedModelBundle:
    artifact: ArtifactMetadata
    manifest: ModelBundleManifest
    predictor: Predictor


class ModelBundleService:
    """Save and load model objects only through the internal artifact boundary."""

    def __init__(self, artifacts: ArtifactService) -> None:
        self._artifacts = artifacts

    async def save(self, model: Predictor, details: BundleManifestInput) -> SavedModelBundle:
        if not callable(getattr(model, "predict", None)):
            raise InvalidModelBundleError("model must expose predict")
        model_bytes = await asyncio.to_thread(_serialize_model, model)
        model_sha256 = hashlib.sha256(model_bytes).hexdigest()
        manifest = ModelBundleManifest(
            algorithm=details.algorithm,
            implementation_version=details.implementation_version,
            feature_schema_version=details.feature_schema.version,
            feature_schema_sha256=details.feature_schema.sha256,
            feature_names=details.feature_schema.names,
            training_dataset_version_id=details.training_dataset_version_id,
            split_definition=details.split_definition,
            code_commit=details.code_commit,
            random_seed=details.random_seed,
            created_at=details.created_at or datetime.now(UTC),
            library_versions=_library_versions(),
            model_parameters=details.model_parameters,
            quality_policy=details.quality_policy,
            weather_mode=details.weather_mode,
            model_sha256=model_sha256,
        )
        bundle_bytes = _build_archive(manifest, model_bytes)
        metadata = await self._artifacts.create(
            io.BytesIO(bundle_bytes),
            purpose=ArtifactPurpose.MODEL,
            media_type=BUNDLE_MEDIA_TYPE,
            suffix=".zip",
        )
        return SavedModelBundle(
            artifact_id=metadata.id,
            bundle_sha256=metadata.sha256,
            size_bytes=metadata.size_bytes,
            manifest=manifest,
        )

    async def load(
        self,
        artifact_id: UUID,
        policy: BundleCompatibilityPolicy,
    ) -> LoadedModelBundle:
        metadata = await self._artifacts.get_metadata(artifact_id)
        if (
            metadata.purpose is not ArtifactPurpose.MODEL
            or metadata.media_type != BUNDLE_MEDIA_TYPE
        ):
            raise UntrustedModelBundleError("artifact is not an internal model bundle")
        stream = await self._artifacts.open(artifact_id)
        try:
            bundle_bytes = await asyncio.to_thread(stream.read)
        finally:
            stream.close()
        if hashlib.sha256(bundle_bytes).hexdigest() != metadata.sha256:
            raise ModelBundleChecksumError("bundle checksum does not match artifact metadata")
        manifest, model_bytes = _read_archive(bundle_bytes)
        if hashlib.sha256(model_bytes).hexdigest() != manifest.model_sha256:
            raise ModelBundleChecksumError("model payload checksum does not match manifest")
        _enforce_policy(manifest, policy)
        model = await asyncio.to_thread(joblib.load, io.BytesIO(model_bytes))
        if not callable(getattr(model, "predict", None)):
            raise InvalidModelBundleError("deserialized object does not expose predict")
        return LoadedModelBundle(
            artifact=metadata,
            manifest=manifest,
            predictor=cast(Predictor, model),
        )


class ModelBundleError(Exception):
    """Base class for controlled model-bundle failures."""


class UntrustedModelBundleError(ModelBundleError):
    """Raised before deserialization for non-model artifacts."""


class InvalidModelBundleError(ModelBundleError):
    """Raised for an unknown or malformed archive/manifest/model."""


class ModelBundleChecksumError(ModelBundleError):
    """Raised when persisted or embedded checksums differ."""


class IncompatibleModelBundleError(ModelBundleError):
    """Raised when a valid bundle violates the caller's compatibility policy."""


def _serialize_model(model: Predictor) -> bytes:
    target = io.BytesIO()
    joblib.dump(model, target, compress=3)
    return target.getvalue()


def _build_archive(manifest: ModelBundleManifest, model_bytes: bytes) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(target, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_zip_info(_MANIFEST_NAME), manifest.model_dump_json(indent=2))
        archive.writestr(_zip_info(_MODEL_NAME), model_bytes)
    return target.getvalue()


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def _read_archive(bundle_bytes: bytes) -> tuple[ModelBundleManifest, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(bundle_bytes), mode="r") as archive:
            names = archive.namelist()
            if names != [_MANIFEST_NAME, _MODEL_NAME]:
                raise InvalidModelBundleError(
                    "bundle must contain only manifest.json and model.joblib"
                )
            if archive.getinfo(_MANIFEST_NAME).file_size > _MAX_MANIFEST_BYTES:
                raise InvalidModelBundleError("bundle manifest is too large")
            manifest_bytes = archive.read(_MANIFEST_NAME)
            model_bytes = archive.read(_MODEL_NAME)
    except (zipfile.BadZipFile, KeyError, OSError) as error:
        raise InvalidModelBundleError("bundle archive is invalid") from error
    try:
        manifest = ModelBundleManifest.model_validate_json(manifest_bytes)
    except ValueError as error:
        raise InvalidModelBundleError("bundle manifest is invalid or unsupported") from error
    return manifest, model_bytes


def _enforce_policy(
    manifest: ModelBundleManifest,
    policy: BundleCompatibilityPolicy,
) -> None:
    mismatches: list[str] = []
    if manifest.feature_schema_version != policy.feature_schema_version:
        mismatches.append("feature schema version")
    if manifest.feature_schema_sha256 != policy.feature_schema_sha256:
        mismatches.append("feature schema checksum")
    if (
        policy.training_dataset_version_id is not None
        and manifest.training_dataset_version_id != policy.training_dataset_version_id
    ):
        mismatches.append("training dataset version")
    if policy.algorithm is not None and manifest.algorithm is not policy.algorithm:
        mismatches.append("algorithm")
    if (
        policy.implementation_version is not None
        and manifest.implementation_version != policy.implementation_version
    ):
        mismatches.append("implementation version")
    if policy.enforce_library_major_versions:
        current = _library_versions()
        for package, recorded_version in manifest.library_versions.items():
            if package not in current or _major(current[package]) != _major(recorded_version):
                mismatches.append(f"{package} major version")
    if mismatches:
        raise IncompatibleModelBundleError(
            "incompatible model bundle: " + ", ".join(sorted(mismatches))
        )


def _library_versions() -> dict[str, str]:
    return {
        package: importlib.metadata.version(package)
        for package in ("joblib", "numpy", "pandas", "scikit-learn")
    }


def _major(version: str) -> str:
    return version.split(".", maxsplit=1)[0]
