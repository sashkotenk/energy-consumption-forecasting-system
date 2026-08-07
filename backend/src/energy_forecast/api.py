"""FastAPI application factory and API process entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from sqlalchemy.ext.asyncio import AsyncEngine

from energy_forecast import __version__
from energy_forecast.analytics.api import create_analytics_router
from energy_forecast.analytics.service import AnalyticsService
from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.config import Service, Settings
from energy_forecast.database import (
    SqlAlchemyAnalyticsRepository,
    SqlAlchemyArtifactMetadataRepository,
    SqlAlchemyDatasetCatalogRepository,
    SqlAlchemyExperimentRepository,
    SqlAlchemyForecastRepository,
    SqlAlchemyJobQueue,
    SqlAlchemyQualityRepository,
    SqlAlchemyTransformationRepository,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.datasets.api import create_dataset_router
from energy_forecast.datasets.service import DatasetService
from energy_forecast.errors import PROBLEM_MEDIA_TYPE, install_exception_handlers
from energy_forecast.experiments.api import create_experiment_router
from energy_forecast.experiments.service import ExperimentService
from energy_forecast.exports.api import create_export_router
from energy_forecast.exports.service import ExportService
from energy_forecast.forecasting.api import create_forecast_router
from energy_forecast.forecasting.service import ForecastService
from energy_forecast.health import (
    DatabaseReadinessCheck,
    MissingDatabaseReadinessCheck,
    ReadinessCheck,
    create_health_router,
)
from energy_forecast.jobs.api import create_job_router
from energy_forecast.jobs.ports import JobQueue
from energy_forecast.logging_config import configure_logging
from energy_forecast.ml.bundles import ModelBundleService
from energy_forecast.quality.api import create_quality_router
from energy_forecast.quality.service import QualityService
from energy_forecast.request_context import RequestContextMiddleware
from energy_forecast.transformations.api import create_transformation_router
from energy_forecast.transformations.service import TransformationService


def create_app(
    settings: Settings | None = None,
    readiness_check: ReadinessCheck | None = None,
    job_queue: JobQueue | None = None,
    dataset_service: DatasetService | None = None,
    quality_service: QualityService | None = None,
    transformation_service: TransformationService | None = None,
    analytics_service: AnalyticsService | None = None,
    experiment_service: ExperimentService | None = None,
    forecast_service: ForecastService | None = None,
    export_service: ExportService | None = None,
) -> FastAPI:
    """Build an API application with explicit, replaceable infrastructure ports."""
    resolved_settings = settings or Settings(service=Service.API)
    configure_logging(resolved_settings)
    resolved_check = readiness_check or _default_readiness_check(resolved_settings)
    (
        engine,
        resolved_queue,
        resolved_dataset_service,
        resolved_quality_service,
        resolved_transformation_service,
        resolved_analytics_service,
        resolved_experiment_service,
        resolved_forecast_service,
        resolved_export_service,
    ) = _default_application_services(
        resolved_settings,
        job_queue,
        dataset_service,
        quality_service,
        transformation_service,
        analytics_service,
        experiment_service,
        forecast_service,
        export_service,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    application = FastAPI(
        title="EnergyForecast API",
        version=__version__,
        openapi_version="3.1.0",
        description="Energy consumption analysis and forecasting API",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.add_middleware(RequestContextMiddleware)
    install_exception_handlers(application)
    application.include_router(create_health_router(resolved_check))
    application.include_router(create_job_router(resolved_queue))
    application.include_router(create_dataset_router(resolved_dataset_service))
    application.include_router(create_quality_router(resolved_quality_service))
    application.include_router(create_transformation_router(resolved_transformation_service))
    application.include_router(create_analytics_router(resolved_analytics_service))
    application.include_router(create_experiment_router(resolved_experiment_service))
    application.include_router(create_forecast_router(resolved_forecast_service))
    application.include_router(create_export_router(resolved_export_service))
    _install_openapi_contract(application)
    return application


def _default_application_services(
    settings: Settings,
    queue: JobQueue | None,
    dataset_service: DatasetService | None,
    quality_service: QualityService | None,
    transformation_service: TransformationService | None,
    analytics_service: AnalyticsService | None,
    experiment_service: ExperimentService | None,
    forecast_service: ForecastService | None,
    export_service: ExportService | None,
) -> tuple[
    AsyncEngine | None,
    JobQueue | None,
    DatasetService | None,
    QualityService | None,
    TransformationService | None,
    AnalyticsService | None,
    ExperimentService | None,
    ForecastService | None,
    ExportService | None,
]:
    if settings.database_url is None:
        return (
            None,
            queue,
            dataset_service,
            quality_service,
            transformation_service,
            analytics_service,
            experiment_service,
            forecast_service,
            export_service,
        )
    engine = create_database_engine(settings.database_url.get_secret_value())
    session_factory = create_session_factory(engine)
    resolved_queue = queue or SqlAlchemyJobQueue(session_factory)
    resolved_quality_service = quality_service or QualityService(
        SqlAlchemyQualityRepository(session_factory)
    )
    resolved_transformation_service = transformation_service or TransformationService(
        SqlAlchemyTransformationRepository(session_factory)
    )
    resolved_analytics_service = analytics_service or AnalyticsService(
        SqlAlchemyAnalyticsRepository(session_factory)
    )
    resolved_experiment_service = experiment_service or ExperimentService(
        SqlAlchemyExperimentRepository(session_factory),
        resolved_queue,
        code_commit=settings.code_commit,
    )
    artifacts = ArtifactService(
        LocalArtifactStore(settings.artifact_root),
        SqlAlchemyArtifactMetadataRepository(session_factory),
    )
    resolved_forecast_service = forecast_service or ForecastService(
        SqlAlchemyForecastRepository(session_factory),
        ModelBundleService(artifacts),
    )
    resolved_export_service = export_service or ExportService(
        resolved_forecast_service,
        resolved_experiment_service,
        artifacts,
    )
    if dataset_service is not None:
        return (
            engine,
            resolved_queue,
            dataset_service,
            resolved_quality_service,
            resolved_transformation_service,
            resolved_analytics_service,
            resolved_experiment_service,
            resolved_forecast_service,
            resolved_export_service,
        )
    resolved_dataset_service = DatasetService(
        SqlAlchemyDatasetCatalogRepository(session_factory),
        artifacts,
        max_upload_bytes=settings.max_upload_bytes,
    )
    return (
        engine,
        resolved_queue,
        resolved_dataset_service,
        resolved_quality_service,
        resolved_transformation_service,
        resolved_analytics_service,
        resolved_experiment_service,
        resolved_forecast_service,
        resolved_export_service,
    )


def _default_readiness_check(settings: Settings) -> ReadinessCheck:
    if settings.database_url is None:
        return MissingDatabaseReadinessCheck()
    return DatabaseReadinessCheck(settings.database_url.get_secret_value())


def _install_openapi_contract(application: FastAPI) -> None:
    """Keep generated error media types aligned with actual Problem Details responses."""

    def custom_openapi() -> dict[str, object]:
        if application.openapi_schema is not None:
            return application.openapi_schema
        schema = get_openapi(
            title=application.title,
            version=application.version,
            description=application.description,
            routes=application.routes,
        )
        problem_schema = {"schema": {"$ref": "#/components/schemas/Problem"}}
        for path_item in schema["paths"].values():
            if not isinstance(path_item, dict):
                continue
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                responses = operation.get("responses")
                if not isinstance(responses, dict):
                    continue
                for response in responses.values():
                    if not isinstance(response, dict):
                        continue
                    content = response.get("content")
                    if not isinstance(content, dict) or PROBLEM_MEDIA_TYPE not in content:
                        continue
                    content[PROBLEM_MEDIA_TYPE] = problem_schema
                    application_json = content.get("application/json")
                    if (
                        isinstance(application_json, dict)
                        and application_json.get("schema", {}).get("$ref")
                        == "#/components/schemas/Problem"
                    ):
                        content.pop("application/json", None)
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi  # type: ignore[method-assign]


app = create_app()


def main() -> None:
    """Run the API using the typed host and port configuration."""
    settings = app.state.settings
    uvicorn.run(app, host=settings.app_host, port=settings.app_port, log_config=None)
