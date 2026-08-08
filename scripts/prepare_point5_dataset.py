#!/usr/bin/env python3
"""Prepare the real UCI source through EnergyForecast persistence for Point 5.

The script intentionally uses the same repository, artifact, quality and transformation
adapters as the application worker.  It creates a real database-backed raw dataset
version and one immutable hourly version, then emits their identifiers and provenance.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select

from energy_forecast.artifacts.local import LocalArtifactStore
from energy_forecast.artifacts.service import ArtifactService
from energy_forecast.database import (
    SqlAlchemyArtifactMetadataRepository,
    SqlAlchemyDatasetCatalogRepository,
    SqlAlchemyDatasetImportRepository,
    SqlAlchemyExperimentRepository,
    SqlAlchemyJobQueue,
    SqlAlchemyQualityRepository,
    SqlAlchemyTransformationRepository,
    create_database_engine,
    create_session_factory,
)
from energy_forecast.database.models import DatasetVersion
from energy_forecast.datasets.importing import DatasetImportHandler
from energy_forecast.datasets.models import ImportProfile
from energy_forecast.datasets.service import DatasetService
from energy_forecast.jobs.domain import JobType
from energy_forecast.jobs.worker import JobHandlerRegistry, JobWorker
from energy_forecast.quality.service import QualityService
from energy_forecast.transformations.models import DuplicatePolicy, TransformationPolicy
from energy_forecast.transformations.service import TransformationHandler, TransformationService

MAX_UPLOAD_BYTES = 300 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    uci_path = args.uci_path.resolve()
    if not uci_path.is_file():
        raise SystemExit(f"UCI source does not exist: {uci_path}")
    if uci_path.name != "household_power_consumption.txt":
        raise SystemExit("Point-5 UCI source must be household_power_consumption.txt")

    artifact_root = args.artifact_root.resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(args.database_url)
    session_factory = create_session_factory(engine)
    queue = SqlAlchemyJobQueue(session_factory)
    artifacts = ArtifactService(
        LocalArtifactStore(artifact_root),
        SqlAlchemyArtifactMetadataRepository(session_factory),
    )
    dataset_service = DatasetService(
        SqlAlchemyDatasetCatalogRepository(session_factory),
        artifacts,
        max_upload_bytes=MAX_UPLOAD_BYTES,
    )
    quality_service = QualityService(SqlAlchemyQualityRepository(session_factory))
    transformation_repository = SqlAlchemyTransformationRepository(session_factory)
    transformation_service = TransformationService(transformation_repository)

    registry = JobHandlerRegistry()
    registry.register(
        JobType.DATASET_IMPORT,
        DatasetImportHandler(
            SqlAlchemyDatasetImportRepository(session_factory),
            artifacts,
            batch_size=args.import_batch_size,
            quality_evaluator=quality_service,
        ),
    )
    registry.register(
        JobType.DATA_TRANSFORMATION,
        TransformationHandler(
            transformation_repository,
            batch_size=args.transform_batch_size,
        ),
    )
    worker = JobWorker(
        queue,
        registry,
        worker_id="point5-preparation",
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=60.0,
        stale_after_seconds=1800.0,
        recovery_batch_size=20,
    )

    try:
        dataset = await dataset_service.create(
            name="UCI household power — Point 5",
            description="Full UCI source prepared for the final ML study.",
        )
        with uci_path.open("rb") as source:
            staged_import = await dataset_service.stage_import(
                dataset_id=dataset.id,
                stream=source,
                original_name=uci_path.name,
                import_profile=ImportProfile.UCI,
                import_options={
                    "timezone": "Europe/Paris",
                    "unit": "kw",
                    "target_semantic": "active_power",
                    "duplicate_policy": "reject",
                },
            )
        local_sha = _sha256(uci_path)
        if staged_import.artifact_sha256 != local_sha:
            raise RuntimeError("Artifact SHA-256 does not match the external UCI source")
        if not await worker.run_once():
            raise RuntimeError("Dataset import job was not claimed")
        import_record = await dataset_service.get_import(staged_import.import_record.id)
        if import_record.status.value != "completed":
            raise RuntimeError(f"UCI import did not complete: {import_record.status.value}")

        transformation = await transformation_service.stage(
            import_record.dataset_version_id,
            TransformationPolicy(
                short_gap_limit_minutes=5,
                minimum_hour_coverage=0.9,
                duplicate_policy=DuplicatePolicy.REJECT,
            ),
        )
        if not await worker.run_once():
            raise RuntimeError("Hourly transformation job was not claimed")

        async with session_factory() as session:
            prepared = await session.scalar(
                select(DatasetVersion).where(DatasetVersion.id == transformation.target_version_id)
            )
            if prepared is None or prepared.status != "ready" or prepared.interval_seconds != 3600:
                state = None if prepared is None else prepared.status
                raise RuntimeError(f"Prepared UCI version is not ready hourly data: {state}")
            transformation_manifest = dict(prepared.transformation_manifest or {})
            quality_policy = dict(prepared.quality_policy or {})

        hourly = await SqlAlchemyExperimentRepository(session_factory).load_hourly(
            transformation.target_version_id
        )
        if len(hourly) < 30_000:
            raise RuntimeError(f"Prepared UCI version has unexpectedly few hourly rows: {len(hourly)}")
        statuses = Counter(str(value) for value in hourly["quality_status"].tolist())
        coverage = hourly["coverage_ratio"].astype(float)
        energy = hourly["energy_kwh"]
        payload: dict[str, Any] = {
            "schema": "energyforecast-point5-dataset-preparation/v1",
            "dataset_id": str(dataset.id),
            "raw_dataset_version_id": str(import_record.dataset_version_id),
            "prepared_dataset_version_id": str(transformation.target_version_id),
            "source_filename": uci_path.name,
            "source_bytes": uci_path.stat().st_size,
            "source_sha256": local_sha,
            "import_id": str(import_record.id),
            "import_job_id": str(import_record.job_id),
            "import_report": import_record.import_report,
            "hourly_rows": int(len(hourly)),
            "hourly_start": hourly.index.min().isoformat(),
            "hourly_end": hourly.index.max().isoformat(),
            "energy_non_null_hours": int(energy.notna().sum()),
            "quality_status_counts": dict(sorted(statuses.items())),
            "coverage": {
                "mean": float(coverage.mean()),
                "minimum": float(coverage.min()),
                "hours_gte_80pct": int(coverage.ge(0.8).sum()),
                "hours_gte_90pct": int(coverage.ge(0.9).sum()),
                "hours_100pct": int(coverage.eq(1.0).sum()),
            },
            "transformation_policy": {
                "short_gap_limit_minutes": 5,
                "minimum_hour_coverage": 0.9,
                "duplicate_policy": "reject",
            },
            "quality_policy": quality_policy,
            "transformation_manifest": transformation_manifest,
        }
        return payload
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--uci-path", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--import-batch-size", type=int, default=10_000)
    parser.add_argument("--transform-batch-size", type=int, default=2_000)
    args = parser.parse_args()
    if args.import_batch_size <= 0 or args.transform_batch_size <= 0:
        raise SystemExit("Batch sizes must be positive")
    payload = asyncio.run(_prepare(args))
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
