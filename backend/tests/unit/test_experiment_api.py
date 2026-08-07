from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient

from energy_forecast.api import create_app
from energy_forecast.config import Settings
from energy_forecast.experiments.ports import ExperimentRepository
from energy_forecast.experiments.service import ExperimentService
from energy_forecast.jobs.ports import JobQueue


class _Ready:
    async def check(self) -> None:
        return None


def test_w1_is_visible_but_rejected_without_fabricated_weather_results() -> None:
    service = ExperimentService(
        cast(ExperimentRepository, object()),
        cast(JobQueue, object()),
        code_commit="abcdef1",
    )
    app = create_app(
        Settings(),
        readiness_check=_Ready(),
        experiment_service=service,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/experiments",
            json={
                "dataset_version_id": str(uuid4()),
                "name": "Weather comparison",
                "algorithms": ["ridge"],
                "weather_mode": "W1",
                "sensitivity_mode": "coverage_90",
            },
        )

    assert response.status_code == 409
    assert response.json()["code"] == "experiment_mode_unavailable"


def test_running_experiment_configuration_has_no_mutation_route() -> None:
    with TestClient(create_app(Settings(), readiness_check=_Ready())) as client:
        response = client.patch(
            f"/experiments/{uuid4()}",
            json={"algorithms": ["random_forest"]},
        )

    assert response.status_code == 405
