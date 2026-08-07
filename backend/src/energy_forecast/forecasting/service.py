"""Create and query forecasts through verified model bundles."""

from __future__ import annotations

from uuid import UUID

from energy_forecast.forecasting.engine import ForecastEngine
from energy_forecast.forecasting.models import (
    ForecastCompatibilityError,
    ForecastPage,
    ForecastRecord,
    ForecastRequest,
)
from energy_forecast.forecasting.ports import ForecastRepository
from energy_forecast.ml.bundles import (
    BundleCompatibilityPolicy,
    IncompatibleModelBundleError,
    ModelBundleError,
    ModelBundleService,
)
from energy_forecast.ml.features import FeatureSchema


class ForecastService:
    def __init__(
        self,
        repository: ForecastRepository,
        bundles: ModelBundleService,
        engine: ForecastEngine | None = None,
    ) -> None:
        self._repository = repository
        self._bundles = bundles
        self._engine = engine or ForecastEngine()

    async def create(self, request: ForecastRequest) -> ForecastRecord:
        context = await self._repository.prepare(request)
        include_quality = context.feature_schema_version == "base_quality_v1"
        schema = FeatureSchema.create(include_quality_features=include_quality)
        if schema.version != context.feature_schema_version:
            raise ForecastCompatibilityError("Unknown feature schema version")
        try:
            loaded = await self._bundles.load(
                context.artifact_id,
                BundleCompatibilityPolicy(
                    feature_schema_version=schema.version,
                    feature_schema_sha256=schema.sha256,
                    training_dataset_version_id=context.requested_dataset_version_id,
                    algorithm=context.algorithm,
                    implementation_version=context.implementation_version,
                ),
            )
        except (IncompatibleModelBundleError, ModelBundleError) as error:
            raise ForecastCompatibilityError(str(error)) from error
        hourly = await self._repository.load_hourly(context.requested_dataset_version_id)
        try:
            computation = self._engine.create(
                hourly,
                origin=request.origin,
                predictor=loaded.predictor,
                manifest=loaded.manifest,
                timezone=context.timezone,
            )
        except ValueError as error:
            raise ForecastCompatibilityError(str(error)) from error
        return await self._repository.save(
            context,
            computation,
            bundle_sha256=loaded.artifact.sha256,
        )

    async def get(self, forecast_id: UUID) -> ForecastRecord:
        return await self._repository.get(forecast_id)

    async def list(self, *, page: int, page_size: int) -> ForecastPage:
        return await self._repository.list(page=page, page_size=page_size)
