from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from numpy.typing import NDArray

from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.models import (
    ArtifactMetadata,
    ArtifactPurpose,
    StoredArtifact,
)
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.ml.bundles import (
    BUNDLE_MEDIA_TYPE,
    BundleCompatibilityPolicy,
    BundleManifestInput,
    IncompatibleModelBundleError,
    InvalidModelBundleError,
    ModelBundleChecksumError,
    ModelBundleService,
    UntrustedModelBundleError,
)
from energy_forecast.ml.features import FeatureSchema
from energy_forecast.ml.registry import AlgorithmType

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_model_bundle_save_load_round_trip_persists_manifest_and_checksums(
    tmp_path: Path,
) -> None:
    service, repository = _bundle_service(tmp_path)
    schema = FeatureSchema.create(include_quality_features=False)
    dataset_version_id = uuid4()
    saved = await service.save(
        _DirectPredictor(scale=2.0),
        _details(schema, dataset_version_id),
    )

    loaded = await service.load(
        saved.artifact_id,
        _policy(schema, dataset_version_id),
    )

    features = np.asarray([[1.0, 3.0], [2.0, 4.0]], dtype=np.float64)
    assert loaded.predictor.predict(features) == pytest.approx(
        np.tile(np.asarray([[2.0], [4.0]]), (1, 24))
    )
    assert loaded.manifest.model_sha256 == saved.manifest.model_sha256
    assert loaded.manifest.library_versions.keys() == {
        "joblib",
        "numpy",
        "pandas",
        "scikit-learn",
    }
    assert loaded.manifest.feature_names == schema.names
    assert loaded.manifest.training_dataset_version_id == dataset_version_id
    assert repository.rows[saved.artifact_id].sha256 == saved.bundle_sha256
    assert repository.rows[saved.artifact_id].size_bytes == saved.size_bytes


@pytest.mark.anyio
async def test_model_bundle_load_rejects_tampered_artifact_before_deserialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository = _bundle_service(tmp_path)
    schema = FeatureSchema.create(include_quality_features=False)
    dataset_version_id = uuid4()
    saved = await service.save(_DirectPredictor(), _details(schema, dataset_version_id))
    metadata = repository.rows[saved.artifact_id]
    (tmp_path / metadata.storage_key).write_bytes(b"tampered")

    def unexpected_load(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("joblib.load must not run for an invalid checksum")

    monkeypatch.setattr("energy_forecast.ml.bundles.joblib.load", unexpected_load)
    with pytest.raises(ModelBundleChecksumError, match="checksum"):
        await service.load(saved.artifact_id, _policy(schema, dataset_version_id))


@pytest.mark.anyio
async def test_model_bundle_load_rejects_schema_and_version_policy_mismatch(
    tmp_path: Path,
) -> None:
    service, _ = _bundle_service(tmp_path)
    schema = FeatureSchema.create(include_quality_features=False)
    saved = await service.save(_DirectPredictor(), _details(schema, uuid4()))
    incompatible = BundleCompatibilityPolicy(
        feature_schema_version="base_v2",
        feature_schema_sha256="0" * 64,
        implementation_version="v2",
    )

    with pytest.raises(IncompatibleModelBundleError, match="implementation version"):
        await service.load(saved.artifact_id, incompatible)


@pytest.mark.anyio
async def test_model_bundle_load_rejects_forecast_dataset_mismatch(tmp_path: Path) -> None:
    service, _ = _bundle_service(tmp_path)
    schema = FeatureSchema.create(include_quality_features=False)
    saved = await service.save(_DirectPredictor(), _details(schema, uuid4()))

    with pytest.raises(IncompatibleModelBundleError, match="training dataset version"):
        await service.load(saved.artifact_id, _policy(schema, uuid4()))


@pytest.mark.anyio
async def test_model_bundle_load_refuses_non_model_artifact(tmp_path: Path) -> None:
    service, repository = _bundle_service(tmp_path)
    artifacts = ArtifactService(LocalArtifactStore(tmp_path), repository)
    artifact = await artifacts.create(
        io.BytesIO(b"not a bundle"),
        purpose=ArtifactPurpose.OTHER,
        media_type=BUNDLE_MEDIA_TYPE,
        suffix=".zip",
    )
    schema = FeatureSchema.create(include_quality_features=False)

    with pytest.raises(UntrustedModelBundleError, match="not an internal"):
        await service.load(artifact.id, _policy(schema, uuid4()))


@pytest.mark.anyio
async def test_unknown_manifest_is_rejected_before_joblib_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, repository = _bundle_service(tmp_path)
    artifacts = ArtifactService(LocalArtifactStore(tmp_path), repository)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, mode="w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"format_version": "model-bundle/v999"}))
        bundle.writestr("model.joblib", b"untrusted pickle bytes")
    artifact = await artifacts.create(
        io.BytesIO(archive.getvalue()),
        purpose=ArtifactPurpose.MODEL,
        media_type=BUNDLE_MEDIA_TYPE,
        suffix=".zip",
    )

    def unexpected_load(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("joblib.load must not run for an unknown manifest")

    monkeypatch.setattr("energy_forecast.ml.bundles.joblib.load", unexpected_load)
    schema = FeatureSchema.create(include_quality_features=False)
    with pytest.raises(InvalidModelBundleError, match="manifest"):
        await service.load(artifact.id, _policy(schema, uuid4()))


@dataclass
class _DirectPredictor:
    scale: float = 1.0

    def predict(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        first_feature = np.asarray(features[:, :1] * self.scale, dtype=np.float64)
        return np.tile(first_feature, (1, 24))


class _InMemoryMetadataRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, ArtifactMetadata] = {}

    async def add(
        self,
        stored: StoredArtifact,
        *,
        purpose: ArtifactPurpose,
        media_type: str,
        original_name: str | None,
    ) -> ArtifactMetadata:
        metadata = ArtifactMetadata(
            id=uuid4(),
            purpose=purpose,
            storage_key=stored.storage_key,
            original_name=original_name,
            media_type=media_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            created_at=datetime.now(UTC),
        )
        self.rows[metadata.id] = metadata
        return metadata

    async def get(self, artifact_id: UUID) -> ArtifactMetadata | None:
        return self.rows.get(artifact_id)

    async def find_by_sha256(self, sha256: str) -> Sequence[ArtifactMetadata]:
        return tuple(row for row in self.rows.values() if row.sha256 == sha256)

    async def delete_if_unreferenced(self, artifact_id: UUID) -> ArtifactMetadata | None:
        return self.rows.pop(artifact_id, None)


def _bundle_service(
    tmp_path: Path,
) -> tuple[ModelBundleService, _InMemoryMetadataRepository]:
    repository = _InMemoryMetadataRepository()
    artifacts = ArtifactService(LocalArtifactStore(tmp_path), repository)
    return ModelBundleService(artifacts), repository


def _details(schema: FeatureSchema, dataset_version_id: UUID) -> BundleManifestInput:
    return BundleManifestInput(
        algorithm=AlgorithmType.RIDGE,
        implementation_version="v1",
        feature_schema=schema,
        training_dataset_version_id=dataset_version_id,
        split_definition="uci_2009_quarters_2010_test_v1",
        code_commit="a17216e",
        model_parameters={"alpha": 1.0},
        quality_policy={"minimum_coverage": 0.9},
    )


def _policy(schema: FeatureSchema, dataset_version_id: UUID) -> BundleCompatibilityPolicy:
    return BundleCompatibilityPolicy(
        feature_schema_version=schema.version,
        feature_schema_sha256=schema.sha256,
        training_dataset_version_id=dataset_version_id,
        algorithm=AlgorithmType.RIDGE,
        implementation_version="v1",
    )
