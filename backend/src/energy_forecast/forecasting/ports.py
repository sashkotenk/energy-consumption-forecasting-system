"""Persistence port for synchronous forecast creation and queries."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

import pandas as pd

from energy_forecast.forecasting.models import (
    ForecastComputation,
    ForecastModelContext,
    ForecastPage,
    ForecastRecord,
    ForecastRequest,
)


class ForecastRepository(Protocol):
    async def prepare(self, request: ForecastRequest) -> ForecastModelContext: ...

    async def load_hourly(self, dataset_version_id: UUID) -> pd.DataFrame: ...

    async def save(
        self,
        context: ForecastModelContext,
        computation: ForecastComputation,
        *,
        bundle_sha256: str,
    ) -> ForecastRecord: ...

    async def get(self, forecast_id: UUID) -> ForecastRecord: ...

    async def list(self, *, page: int, page_size: int) -> ForecastPage: ...
