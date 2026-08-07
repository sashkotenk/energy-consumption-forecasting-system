"""PostgreSQL-backed worker process entrypoint."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from uuid import uuid4

from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.config import Service, Settings
from energy_forecast.database import (
    SqlAlchemyArtifactMetadataRepository,
    SqlAlchemyDatasetImportRepository,
    SqlAlchemyJobQueue,
    SqlAlchemyQualityRepository,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.datasets.importing import DatasetImportHandler
from energy_forecast.jobs.domain import JobType
from energy_forecast.jobs.worker import JobHandlerRegistry, JobWorker
from energy_forecast.logging_config import configure_logging
from energy_forecast.quality.service import QualityService


async def run_worker(settings: Settings, registry: JobHandlerRegistry | None = None) -> None:
    """Run the worker loop against the configured PostgreSQL queue."""
    configure_logging(settings)
    if settings.database_url is None:
        raise ValueError("DATABASE_URL is required by the worker process")

    engine = create_database_engine(settings.database_url.get_secret_value())
    worker_id = _worker_id()
    session_factory = create_session_factory(engine)
    queue = SqlAlchemyJobQueue(session_factory)
    if registry is None:
        resolved_registry = JobHandlerRegistry()
        artifacts = ArtifactService(
            LocalArtifactStore(settings.artifact_root),
            SqlAlchemyArtifactMetadataRepository(session_factory),
        )
        quality_service = QualityService(SqlAlchemyQualityRepository(session_factory))
        resolved_registry.register(
            JobType.DATASET_IMPORT,
            DatasetImportHandler(
                SqlAlchemyDatasetImportRepository(session_factory),
                artifacts,
                quality_evaluator=quality_service,
            ),
        )
    else:
        resolved_registry = registry
    worker = JobWorker(
        queue,
        resolved_registry,
        worker_id=worker_id,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
        heartbeat_interval_seconds=settings.worker_heartbeat_interval_seconds,
        stale_after_seconds=settings.worker_stale_after_seconds,
        recovery_batch_size=settings.worker_recovery_batch_size,
    )
    logger = logging.getLogger(__name__)
    logger.info(
        "worker_initialized",
        extra={
            "event": "worker_initialized",
            "worker_id": worker_id,
            "run_once": settings.worker_run_once,
            "handler_count": len(resolved_registry.supported_types),
        },
    )
    try:
        if settings.worker_run_once:
            await worker.run_once()
        else:
            await worker.run_forever()
    finally:
        await engine.dispose()
        logger.info(
            "worker_stopped",
            extra={"event": "worker_stopped", "worker_id": worker_id},
        )


def main() -> None:
    """Start the worker as a process separate from the API."""
    asyncio.run(run_worker(Settings(service=Service.WORKER)))


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:12]}"
