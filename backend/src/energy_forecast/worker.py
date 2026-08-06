"""Worker process entrypoint; queue processing arrives in a later task."""

from __future__ import annotations

import logging

from energy_forecast.config import Service, Settings
from energy_forecast.logging_config import configure_logging


def run_worker(settings: Settings) -> None:
    """Validate worker configuration and initialize its process boundary."""
    configure_logging(settings)
    logging.getLogger(__name__).info(
        "worker_initialized",
        extra={"event": "worker_initialized"},
    )


def main() -> None:
    """Console entrypoint for the future PostgreSQL-backed worker loop."""
    run_worker(Settings(service=Service.WORKER))
