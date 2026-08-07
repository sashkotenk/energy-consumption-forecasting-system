from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from numpy.typing import NDArray
from pydantic import SecretStr
from sqlalchemy import func, select

from energy_forecast.api import create_app
from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.config import Settings
from energy_forecast.database import (
    SqlAlchemyArtifactMetadataRepository,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.database.models import (
    Dataset,
    DatasetVersion,
    Experiment,
    Forecast,
    ForecastPoint,
    HourlyObservation,
    Job,
    ModelRun,
)
from energy_forecast.database.session import transactional_session
from energy_forecast.ml.bundles import BundleManifestInput, ModelBundleService
from energy_forecast.ml.features import FeatureSchema
from energy_forecast.ml.registry import AlgorithmType
from tests.integration.conftest import upgrade_database

pytestmark = pytest.mark.integration


class _ForecastFixture(TypedDict):
    version_id: UUID
    other_version_id: UUID
    model_run_id: UUID
    artifact_id: UUID
    latest_origin: datetime
    early_origin: datetime


class _Ready:
    async def check(self) -> None:
        return None


@dataclass
class _ConstantPredictor:
    value: float

    def predict(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        return np.full((features.shape[0], 24), self.value, dtype=np.float64)


def test_forecast_api_loads_verified_bundle_and_persists_24_points_atomically(
    temporary_database_url: str,
    tmp_path: Path,
) -> None:
    upgrade_database(temporary_database_url)
    fixture = asyncio.run(_seed_forecast_fixture(temporary_database_url, tmp_path))
    app = create_app(
        Settings(
            database_url=SecretStr(temporary_database_url),
            artifact_root=tmp_path,
        ),
        readiness_check=_Ready(),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/forecasts",
            json={
                "model_run_id": str(fixture["model_run_id"]),
                "dataset_version_id": str(fixture["version_id"]),
                "origin": fixture["latest_origin"].isoformat(),
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        fetched = client.get(f"/forecasts/{body['id']}")
        listed = client.get("/forecasts")
        incompatible = client.post(
            "/forecasts",
            json={
                "model_run_id": str(fixture["model_run_id"]),
                "dataset_version_id": str(fixture["other_version_id"]),
            },
        )
        missing_history = client.post(
            "/forecasts",
            json={
                "model_run_id": str(fixture["model_run_id"]),
                "dataset_version_id": str(fixture["version_id"]),
                "origin": fixture["early_origin"].isoformat(),
            },
        )

    assert body["status"] == "completed"
    assert body["timezone"] == "UTC"
    assert body["algorithm"] == "ridge"
    assert body["artifact_id"] == str(fixture["artifact_id"])
    assert len(body["points"]) == 24
    assert [point["horizon"] for point in body["points"]] == list(range(1, 25))
    assert body["total_energy_kwh"] == pytest.approx(48.0)
    assert sum(point["predicted_energy_kwh"] for point in body["points"]) == pytest.approx(
        body["total_energy_kwh"]
    )
    assert fetched.status_code == 200
    assert fetched.json() == body
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert incompatible.status_code == 409
    assert incompatible.json()["code"] == "forecast_bundle_incompatible"
    assert missing_history.status_code == 422
    assert missing_history.json()["code"] == "forecast_history_missing"
    assert asyncio.run(_persisted_counts(temporary_database_url)) == (1, 24)


async def _seed_forecast_fixture(database_url: str, artifact_root: Path) -> _ForecastFixture:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    dataset_id, version_id, other_version_id = uuid4(), uuid4(), uuid4()
    experiment_id, job_id, model_run_id = uuid4(), uuid4(), uuid4()
    start = datetime(2025, 1, 1, tzinfo=UTC)
    try:
        async with transactional_session(factory) as session:
            session.add(Dataset(id=dataset_id, name="Forecast fixture"))
            session.add_all(
                (
                    DatasetVersion(
                        id=version_id,
                        dataset_id=dataset_id,
                        version_no=1,
                        status="ready",
                        timezone_context="UTC",
                        interval_seconds=3600,
                        quality_policy={},
                        transformation_manifest={},
                    ),
                    DatasetVersion(
                        id=other_version_id,
                        dataset_id=dataset_id,
                        version_no=2,
                        status="ready",
                        timezone_context="UTC",
                        interval_seconds=3600,
                        quality_policy={},
                        transformation_manifest={},
                    ),
                )
            )
            await session.flush()
            session.add_all(
                HourlyObservation(
                    dataset_version_id=version_id,
                    hour_start=start + timedelta(hours=hour),
                    timezone_context="UTC",
                    energy_kwh=10 + float(np.sin(hour * 2 * np.pi / 24)),
                    observed_samples=60,
                    expected_samples=60,
                    coverage_ratio=1.0,
                    imputed_samples=0,
                    max_missing_run=0,
                    quality_status="complete",
                    quality_flags=[],
                )
                for hour in range(240)
            )
        bundles = ModelBundleService(
            ArtifactService(
                LocalArtifactStore(artifact_root),
                SqlAlchemyArtifactMetadataRepository(factory),
            )
        )
        schema = FeatureSchema.create(include_quality_features=False)
        bundle = await bundles.save(
            _ConstantPredictor(2.0),
            BundleManifestInput(
                algorithm=AlgorithmType.RIDGE,
                implementation_version="v1",
                feature_schema=schema,
                training_dataset_version_id=version_id,
                split_definition="uci_2009_quarters_2010_test_v1",
                code_commit="abcdef1",
                model_parameters={"alpha": 1.0},
                quality_policy={"sensitivity_mode": "complete_only"},
            ),
        )
        async with transactional_session(factory) as session:
            session.add(
                Job(
                    id=job_id,
                    job_type="experiment",
                    status="succeeded",
                    priority=0,
                    payload={"experiment_id": str(experiment_id)},
                    result={},
                    progress_pct=100,
                    attempt=1,
                    max_attempts=3,
                    finished_at=datetime.now(UTC),
                )
            )
            await session.flush()
            session.add(
                Experiment(
                    id=experiment_id,
                    dataset_version_id=version_id,
                    job_id=job_id,
                    name="Completed forecast model",
                    status="completed",
                    weather_mode="W0",
                    forecast_horizon=24,
                    feature_schema_version=schema.version,
                    split_definition={"definition": "uci_2009_quarters_2010_test_v1"},
                    selection_rule_version="selection_v1",
                    code_commit="abcdef1",
                    environment_manifest={},
                    result_manifest={"schema_version": "experiment-result/v1"},
                    final_test_opened_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
            )
            await session.flush()
            session.add(
                ModelRun(
                    id=model_run_id,
                    experiment_id=experiment_id,
                    algorithm="ridge",
                    status="completed",
                    hyperparameters={"alpha": 1.0},
                    random_seed=42,
                    artifact_id=bundle.artifact_id,
                    artifact_size_bytes=bundle.size_bytes,
                    is_recommended=True,
                    completed_at=datetime.now(UTC),
                )
            )
        return {
            "version_id": version_id,
            "other_version_id": other_version_id,
            "model_run_id": model_run_id,
            "artifact_id": bundle.artifact_id,
            "latest_origin": start + timedelta(hours=239),
            "early_origin": start + timedelta(hours=100),
        }
    finally:
        await engine.dispose()


async def _persisted_counts(database_url: str) -> tuple[int, int]:
    engine = create_database_engine(database_url)
    factory = create_session_factory(engine)
    try:
        async with transactional_session(factory) as session:
            forecasts = int(await session.scalar(select(func.count()).select_from(Forecast)) or 0)
            points = int(await session.scalar(select(func.count()).select_from(ForecastPoint)) or 0)
            return forecasts, points
    finally:
        await engine.dispose()
