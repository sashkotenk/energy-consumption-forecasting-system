"""Experiment API use cases."""

from __future__ import annotations

from uuid import UUID

from energy_forecast.experiments.models import (
    ExperimentConfigurationError,
    ExperimentDefinition,
    ExperimentPage,
    ExperimentRecord,
    StagedExperiment,
    WeatherMode,
)
from energy_forecast.experiments.ports import ExperimentRepository
from energy_forecast.jobs.ports import JobQueue


class ExperimentService:
    def __init__(
        self, repository: ExperimentRepository, jobs: JobQueue, *, code_commit: str
    ) -> None:
        self._repository = repository
        self._jobs = jobs
        self._code_commit = code_commit

    async def stage(self, definition: ExperimentDefinition) -> StagedExperiment:
        if definition.weather_mode is WeatherMode.WITH_WEATHER:
            raise ExperimentConfigurationError(
                "W1 requires a weather dataset and is not executable in this release"
            )
        return await self._repository.stage(definition, code_commit=self._code_commit)

    async def list(self, *, page: int, page_size: int) -> ExperimentPage:
        return await self._repository.list(page=page, page_size=page_size)

    async def get(self, experiment_id: UUID) -> ExperimentRecord:
        return await self._repository.get(experiment_id)

    async def comparison(self, experiment_id: UUID) -> tuple[dict[str, object], ...]:
        return await self._repository.comparison(experiment_id)

    async def cancel(self, experiment_id: UUID) -> ExperimentRecord:
        job_id = await self._repository.mark_cancelling(experiment_id)
        await self._jobs.request_cancel(job_id)
        return await self._repository.get(experiment_id)
