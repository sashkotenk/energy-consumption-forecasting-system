"""FastAPI application factory and API process entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from sqlalchemy.ext.asyncio import AsyncEngine

from energy_forecast import __version__
from energy_forecast.config import Service, Settings
from energy_forecast.database import (
    SqlAlchemyJobQueue,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.errors import PROBLEM_MEDIA_TYPE, install_exception_handlers
from energy_forecast.health import (
    DatabaseReadinessCheck,
    MissingDatabaseReadinessCheck,
    ReadinessCheck,
    create_health_router,
)
from energy_forecast.jobs.api import create_job_router
from energy_forecast.jobs.ports import JobQueue
from energy_forecast.logging_config import configure_logging
from energy_forecast.request_context import RequestContextMiddleware


def create_app(
    settings: Settings | None = None,
    readiness_check: ReadinessCheck | None = None,
    job_queue: JobQueue | None = None,
) -> FastAPI:
    """Build an API application with explicit, replaceable infrastructure ports."""
    resolved_settings = settings or Settings(service=Service.API)
    configure_logging(resolved_settings)
    resolved_check = readiness_check or _default_readiness_check(resolved_settings)
    engine, resolved_queue = _default_job_queue(resolved_settings, job_queue)

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
        description="Energy consumption analysis and forecasting API",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.add_middleware(RequestContextMiddleware)
    install_exception_handlers(application)
    application.include_router(create_health_router(resolved_check))
    application.include_router(create_job_router(resolved_queue))
    _install_openapi_contract(application)
    return application


def _default_job_queue(
    settings: Settings, queue: JobQueue | None
) -> tuple[AsyncEngine | None, JobQueue | None]:
    if queue is not None or settings.database_url is None:
        return None, queue
    engine = create_database_engine(settings.database_url.get_secret_value())
    return engine, SqlAlchemyJobQueue(create_session_factory(engine))


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
        readiness_response = schema["paths"]["/health/ready"]["get"]["responses"]["503"]
        readiness_response["content"] = {
            PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/Problem"}}
        }
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi  # type: ignore[method-assign]


app = create_app()


def main() -> None:
    """Run the API using the typed host and port configuration."""
    settings = app.state.settings
    uvicorn.run(app, host=settings.app_host, port=settings.app_port, log_config=None)
