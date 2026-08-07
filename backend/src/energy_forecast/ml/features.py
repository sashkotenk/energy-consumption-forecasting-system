"""Pure, versioned construction of leakage-safe hourly forecasting features."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd
from numpy.typing import NDArray

FORECAST_HORIZON = 24
FIXED_LAGS = (1, 2, 3, 6, 12, 24, 48, 168)
ROLLING_WINDOWS = (3, 6, 12, 24, 168)
FEATURE_SCHEMA_BASE_V1 = "base_v1"
FEATURE_SCHEMA_QUALITY_V1 = "base_quality_v1"

LAG_FEATURES = tuple(f"lag_{lag}" for lag in FIXED_LAGS)
ROLLING_FEATURES = (
    *(f"rolling_mean_{window}" for window in ROLLING_WINDOWS),
    "rolling_std_24",
    "rolling_min_24",
    "rolling_max_24",
)
CALENDAR_FEATURES = (
    "hour",
    "day_of_week",
    "day_of_month",
    "month",
    "is_weekend",
    "hour_sin",
    "hour_cos",
    "day_of_week_sin",
    "day_of_week_cos",
    "month_sin",
    "month_cos",
)
QUALITY_FEATURES = (
    "past_24h_coverage_mean",
    "past_168h_missing_hours",
    "last_hour_imputed",
)


@dataclass(frozen=True, slots=True)
class FeaturePipelineConfig:
    timezone: str = "UTC"
    include_quality_features: bool = False

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown IANA timezone: {self.timezone}") from error


@dataclass(frozen=True, slots=True)
class FeatureSchema:
    version: str
    names: tuple[str, ...]
    dtypes: tuple[str, ...]
    forecast_horizon: int
    sha256: str

    @classmethod
    def create(cls, *, include_quality_features: bool) -> FeatureSchema:
        version = FEATURE_SCHEMA_QUALITY_V1 if include_quality_features else FEATURE_SCHEMA_BASE_V1
        names = (*LAG_FEATURES, *ROLLING_FEATURES, *CALENDAR_FEATURES)
        if include_quality_features:
            names = (*names, *QUALITY_FEATURES)
        dtypes = tuple("float64" for _ in names)
        canonical = json.dumps(
            {
                "version": version,
                "names": names,
                "dtypes": dtypes,
                "forecast_horizon": FORECAST_HORIZON,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return cls(
            version=version,
            names=names,
            dtypes=dtypes,
            forecast_horizon=FORECAST_HORIZON,
            sha256=hashlib.sha256(canonical).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class FeatureRows:
    origins: tuple[datetime, ...]
    values: NDArray[np.float64]
    schema: FeatureSchema


@dataclass(frozen=True, slots=True)
class FeatureMatrix:
    origins: tuple[datetime, ...]
    features: NDArray[np.float64]
    targets: NDArray[np.float64]
    schema: FeatureSchema


class FeaturePipeline:
    """Build deterministic features and direct 24-output targets from hourly facts."""

    def __init__(self, config: FeaturePipelineConfig | None = None) -> None:
        self.config = config or FeaturePipelineConfig()
        self.schema = FeatureSchema.create(
            include_quality_features=self.config.include_quality_features
        )

    def build_features(self, hourly: pd.DataFrame) -> FeatureRows:
        source = self._normalized_hourly(hourly)
        features = self._feature_frame(source)
        eligible = features.notna().all(axis=1)
        selected = features.loc[eligible, self.schema.names]
        return FeatureRows(
            origins=tuple(selected.index.to_pydatetime()),
            values=_as_float_matrix(selected, columns=len(self.schema.names)),
            schema=self.schema,
        )

    def build_supervised(self, hourly: pd.DataFrame) -> FeatureMatrix:
        source = self._normalized_hourly(hourly)
        features = self._feature_frame(source)
        energy = source["energy_kwh"]
        targets = pd.DataFrame(
            {f"target_h{horizon:02d}": energy.shift(-horizon) for horizon in range(1, 25)},
            index=source.index,
        )
        eligible = features.notna().all(axis=1) & targets.notna().all(axis=1)
        selected_features = features.loc[eligible, self.schema.names]
        selected_targets = targets.loc[eligible]
        return FeatureMatrix(
            origins=tuple(selected_features.index.to_pydatetime()),
            features=_as_float_matrix(selected_features, columns=len(self.schema.names)),
            targets=_as_float_matrix(selected_targets, columns=FORECAST_HORIZON),
            schema=self.schema,
        )

    def _normalized_hourly(self, hourly: pd.DataFrame) -> pd.DataFrame:
        if "energy_kwh" not in hourly:
            raise ValueError("hourly data must contain energy_kwh")
        if not isinstance(hourly.index, pd.DatetimeIndex):
            raise ValueError("hourly data must use a DatetimeIndex")
        if hourly.index.tz is None:
            raise ValueError("hourly timestamps must be timezone-aware")
        if hourly.index.has_duplicates:
            raise ValueError("hourly timestamps must be unique")
        if hourly.empty:
            return hourly.copy()

        source = hourly.copy()
        source.index = source.index.tz_convert("UTC")
        source = source.sort_index()
        complete_index = pd.date_range(
            start=source.index[0], end=source.index[-1], freq="h", tz="UTC"
        )
        source = source.reindex(complete_index)
        source["energy_kwh"] = pd.to_numeric(source["energy_kwh"], errors="raise")
        finite = source["energy_kwh"].dropna().map(math.isfinite)
        if not finite.all() or (source["energy_kwh"].dropna() < 0).any():
            raise ValueError("energy_kwh values must be finite and non-negative")
        if self.config.include_quality_features:
            missing = {"coverage_ratio", "quality_status"}.difference(source.columns)
            if missing:
                raise ValueError(f"quality features require columns: {', '.join(sorted(missing))}")
            source["coverage_ratio"] = pd.to_numeric(source["coverage_ratio"], errors="raise")
            coverage = source["coverage_ratio"].dropna()
            if ((coverage < 0) | (coverage > 1)).any():
                raise ValueError("coverage_ratio values must be between 0 and 1")
        return source

    def _feature_frame(self, source: pd.DataFrame) -> pd.DataFrame:
        energy = source["energy_kwh"]
        features = pd.DataFrame(index=source.index)
        for lag in FIXED_LAGS:
            features[f"lag_{lag}"] = energy.shift(lag)

        past = energy.shift(1)
        for window in ROLLING_WINDOWS:
            features[f"rolling_mean_{window}"] = past.rolling(
                window=window, min_periods=window
            ).mean()
        rolling_24 = past.rolling(window=24, min_periods=24)
        features["rolling_std_24"] = rolling_24.std(ddof=0)
        features["rolling_min_24"] = rolling_24.min()
        features["rolling_max_24"] = rolling_24.max()

        local_index = source.index.tz_convert(self.config.timezone)
        hour = local_index.hour.astype(float)
        weekday = local_index.dayofweek.astype(float)
        month = local_index.month.astype(float)
        features["hour"] = hour
        features["day_of_week"] = weekday
        features["day_of_month"] = local_index.day.astype(float)
        features["month"] = month
        features["is_weekend"] = (weekday >= 5).astype(float)
        features["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        features["hour_cos"] = np.cos(2 * np.pi * hour / 24)
        features["day_of_week_sin"] = np.sin(2 * np.pi * weekday / 7)
        features["day_of_week_cos"] = np.cos(2 * np.pi * weekday / 7)
        features["month_sin"] = np.sin(2 * np.pi * (month - 1) / 12)
        features["month_cos"] = np.cos(2 * np.pi * (month - 1) / 12)

        if self.config.include_quality_features:
            coverage = source["coverage_ratio"].shift(1)
            missing = energy.isna().astype(float).shift(1)
            status = source["quality_status"].shift(1)
            features["past_24h_coverage_mean"] = coverage.rolling(window=24, min_periods=24).mean()
            features["past_168h_missing_hours"] = missing.rolling(window=168, min_periods=168).sum()
            features["last_hour_imputed"] = status.eq("imputed_short_gap").astype(float)

        return features.loc[:, self.schema.names]


def _as_float_matrix(frame: pd.DataFrame, *, columns: int) -> NDArray[np.float64]:
    if frame.empty:
        return np.empty((0, columns), dtype=np.float64)
    return np.asarray(frame.to_numpy(dtype=np.float64, copy=True), dtype=np.float64)
