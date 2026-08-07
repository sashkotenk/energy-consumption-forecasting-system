from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from energy_forecast.forecasting.engine import ForecastEngine
from energy_forecast.forecasting.models import (
    ForecastHistoryMissingError,
    ForecastOriginError,
)
from energy_forecast.ml.bundles import ModelBundleManifest
from energy_forecast.ml.features import FeatureSchema
from energy_forecast.ml.registry import AlgorithmType


@dataclass
class _FixedPredictor:
    values: NDArray[np.float64]

    def predict(self, features: NDArray[np.float64]) -> NDArray[np.float64]:
        assert features.shape[0] == 1
        return self.values.copy()


def test_forecast_has_24_ordered_nonnegative_points_total_and_timezone() -> None:
    hourly = _hourly(240)
    origin = hourly.index[-1].to_pydatetime()
    raw = np.arange(-1.0, 23.0, dtype=np.float64).reshape(1, 24)

    forecast = ForecastEngine().create(
        hourly,
        origin=origin,
        predictor=_FixedPredictor(raw),
        manifest=_manifest(),
        timezone="Europe/Kyiv",
    )

    assert forecast.origin == origin
    assert len(forecast.points) == 24
    assert [point.horizon for point in forecast.points] == list(range(1, 25))
    assert forecast.points[0].target_time == origin + pd.Timedelta(hours=1)
    assert forecast.points[-1].target_time == origin + pd.Timedelta(hours=24)
    assert all(point.target_time.tzinfo is not None for point in forecast.points)
    assert all(point.predicted_energy_kwh >= 0 for point in forecast.points)
    assert forecast.total_energy_kwh == pytest.approx(
        sum(point.predicted_energy_kwh for point in forecast.points)
    )


def test_forecast_is_reproducible_for_same_bundle_history_and_origin() -> None:
    hourly = _hourly(240)
    predictor = _FixedPredictor(np.full((1, 24), 2.5, dtype=np.float64))
    arguments = {
        "origin": hourly.index[-1].to_pydatetime(),
        "predictor": predictor,
        "manifest": _manifest(),
        "timezone": "UTC",
    }

    first = ForecastEngine().create(hourly, **arguments)
    second = ForecastEngine().create(hourly, **arguments)

    assert first == second


def test_missing_required_168_hour_history_is_not_filled() -> None:
    hourly = _hourly(100)

    with pytest.raises(ForecastHistoryMissingError, match="lag or rolling history"):
        ForecastEngine().create(
            hourly,
            origin=hourly.index[-1].to_pydatetime(),
            predictor=_FixedPredictor(np.ones((1, 24))),
            manifest=_manifest(),
            timezone="UTC",
        )


def test_origin_must_be_an_aware_stored_hour_boundary() -> None:
    hourly = _hourly(240)

    with pytest.raises(ForecastOriginError, match="timezone"):
        ForecastEngine().create(
            hourly,
            origin=datetime(2026, 1, 1),
            predictor=_FixedPredictor(np.ones((1, 24))),
            manifest=_manifest(),
            timezone="UTC",
        )


def _hourly(hours: int) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=hours, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "energy_kwh": 10 + np.sin(np.arange(hours) * 2 * np.pi / 24),
            "coverage_ratio": np.ones(hours),
            "quality_status": ["complete"] * hours,
        },
        index=index,
    )


def _manifest() -> ModelBundleManifest:
    schema = FeatureSchema.create(include_quality_features=False)
    return ModelBundleManifest(
        algorithm=AlgorithmType.RIDGE,
        implementation_version="v1",
        feature_schema_version=schema.version,
        feature_schema_sha256=schema.sha256,
        feature_names=schema.names,
        training_dataset_version_id=uuid4(),
        split_definition="uci_2009_quarters_2010_test_v1",
        code_commit="abcdef1",
        random_seed=42,
        created_at=datetime.now(UTC),
        library_versions={
            "joblib": "1.5.3",
            "numpy": "2.4.6",
            "pandas": "3.0.5",
            "scikit-learn": "1.9.0",
        },
        model_parameters={"alpha": 1.0},
        quality_policy={"sensitivity_mode": "complete_only"},
        weather_mode="W0",
        model_sha256="0" * 64,
    )
