"""Pure construction of one leakage-safe 24-hour forecast."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from energy_forecast.forecasting.models import (
    ForecastComputation,
    ForecastHistoryMissingError,
    ForecastOriginError,
    ForecastPoint,
)
from energy_forecast.ml.baselines import SeasonalNaive
from energy_forecast.ml.bundles import ModelBundleManifest
from energy_forecast.ml.features import (
    FEATURE_SCHEMA_QUALITY_V1,
    FeaturePipeline,
    FeaturePipelineConfig,
)
from energy_forecast.ml.ports import Predictor
from energy_forecast.ml.registry import AlgorithmType


class ForecastEngine:
    def create(
        self,
        hourly: pd.DataFrame,
        *,
        origin: datetime | None,
        predictor: Predictor,
        manifest: ModelBundleManifest,
        timezone: str,
    ) -> ForecastComputation:
        source = _quality_view(hourly, manifest.quality_policy)
        resolved_origin = _resolve_origin(source, origin)
        pipeline = FeaturePipeline(
            FeaturePipelineConfig(
                timezone=timezone,
                include_quality_features=(
                    manifest.feature_schema_version == FEATURE_SCHEMA_QUALITY_V1
                ),
            )
        )
        rows = pipeline.build_features(source)
        try:
            row_index = rows.origins.index(resolved_origin)
        except ValueError as error:
            raise ForecastHistoryMissingError(
                "Required lag or rolling history is missing at the requested origin"
            ) from error
        if rows.schema.sha256 != manifest.feature_schema_sha256:
            raise ForecastHistoryMissingError(
                "Constructed feature schema does not match the model bundle"
            )
        if manifest.algorithm in {
            AlgorithmType.SEASONAL_NAIVE_24,
            AlgorithmType.SEASONAL_NAIVE_168,
        }:
            baseline = cast(SeasonalNaive, predictor)
            raw = baseline.predict(source["energy_kwh"], (resolved_origin,))
        else:
            raw = predictor.predict(rows.values[[row_index]])
        values = _validated_predictions(raw)
        clipped = np.maximum(values[0], 0.0)
        points = tuple(
            ForecastPoint(
                horizon=horizon,
                target_time=resolved_origin + timedelta(hours=horizon),
                predicted_energy_kwh=float(clipped[horizon - 1]),
            )
            for horizon in range(1, 25)
        )
        return ForecastComputation(
            origin=resolved_origin,
            points=points,
            total_energy_kwh=float(np.sum(clipped)),
        )


def _resolve_origin(hourly: pd.DataFrame, origin: datetime | None) -> datetime:
    if not isinstance(hourly.index, pd.DatetimeIndex) or hourly.index.tz is None or hourly.empty:
        raise ForecastHistoryMissingError("Hourly history is empty or has no timezone")
    if origin is None:
        eligible = hourly.loc[
            hourly["energy_kwh"].notna()
            & hourly["quality_status"].isin(("complete", "imputed_short_gap", "valid_partial"))
        ]
        if eligible.empty:
            raise ForecastHistoryMissingError("No completed hourly origin is available")
        latest = cast(pd.Timestamp, eligible.index.max())
        return cast(datetime, latest.to_pydatetime()).astimezone(UTC)
    if origin.tzinfo is None:
        raise ForecastOriginError("Forecast origin must include a timezone")
    normalized = origin.astimezone(UTC)
    if normalized.minute or normalized.second or normalized.microsecond:
        raise ForecastOriginError("Forecast origin must be aligned to an hour boundary")
    timestamp = pd.Timestamp(normalized)
    if timestamp not in hourly.index:
        raise ForecastOriginError("Forecast origin is not a stored completed hour")
    row = hourly.loc[timestamp]
    if pd.isna(row["energy_kwh"]) or row["quality_status"] not in {
        "complete",
        "imputed_short_gap",
        "valid_partial",
    }:
        raise ForecastOriginError("Forecast origin is not a valid completed hour")
    return normalized


def _quality_view(hourly: pd.DataFrame, policy: Mapping[str, object]) -> pd.DataFrame:
    selected = hourly.copy()
    sensitivity = str(policy.get("sensitivity_mode", "complete_only"))
    if sensitivity == "coverage_90":
        eligible = selected["coverage_ratio"].ge(0.9) & selected["quality_status"].isin(
            ("complete", "imputed_short_gap", "valid_partial")
        )
    else:
        eligible = selected["quality_status"].eq("complete")
    selected.loc[~eligible, "energy_kwh"] = np.nan
    return selected


def _validated_predictions(values: NDArray[np.float64]) -> NDArray[np.float64]:
    predictions = np.asarray(values, dtype=np.float64)
    if predictions.shape != (1, 24) or not np.isfinite(predictions).all():
        raise ValueError("Model bundle must produce one finite 24-horizon prediction")
    return predictions
