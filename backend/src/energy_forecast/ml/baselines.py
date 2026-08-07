"""Seasonal baselines evaluated on caller-supplied forecast origins."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class SeasonalNaive:
    period_hours: int

    def __post_init__(self) -> None:
        if self.period_hours not in {24, 168}:
            raise ValueError("seasonal period must be 24 or 168 hours")

    def predict(
        self,
        hourly_energy: pd.Series,
        origins: tuple[datetime, ...],
    ) -> NDArray[np.float64]:
        series = _validated_series(hourly_energy)
        predictions = np.empty((len(origins), 24), dtype=np.float64)
        for row, origin in enumerate(origins):
            timestamp = pd.Timestamp(origin)
            if timestamp.tzinfo is None:
                raise ValueError("forecast origins must be timezone-aware")
            origin_utc = timestamp.tz_convert("UTC")
            for horizon in range(1, 25):
                source_time = origin_utc + pd.Timedelta(hours=horizon - self.period_hours)
                try:
                    value = series.at[source_time]
                except KeyError as error:
                    raise MissingBaselineHistoryError(
                        f"missing seasonal history at {source_time.isoformat()}"
                    ) from error
                if pd.isna(value):
                    raise MissingBaselineHistoryError(
                        f"missing seasonal history at {source_time.isoformat()}"
                    )
                predictions[row, horizon - 1] = float(value)
        return predictions


class MissingBaselineHistoryError(ValueError):
    """Raised instead of filling unavailable seasonal history."""


def _validated_series(hourly_energy: pd.Series) -> pd.Series:
    if not isinstance(hourly_energy.index, pd.DatetimeIndex) or hourly_energy.index.tz is None:
        raise ValueError("hourly energy must use a timezone-aware DatetimeIndex")
    if hourly_energy.index.has_duplicates:
        raise ValueError("hourly energy timestamps must be unique")
    series = pd.to_numeric(hourly_energy.copy(), errors="raise")
    series.index = series.index.tz_convert("UTC")
    series = series.sort_index()
    present = series.dropna().to_numpy(dtype=np.float64)
    if not np.isfinite(present).all() or (present < 0).any():
        raise ValueError("hourly energy values must be finite and non-negative")
    return series
