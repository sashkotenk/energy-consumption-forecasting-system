"""PostgreSQL adapter for dataset catalog and import staging."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import exists, func, select

from energy_forecast.artifacts.models import ArtifactMetadata
from energy_forecast.database.models import Dataset, DatasetImport, DatasetVersion, Job
from energy_forecast.database.session import AsyncSessionFactory, transactional_session
from energy_forecast.datasets.models import (
    DatasetChanges,
    DatasetImportRecord,
    DatasetImportStatus,
    DatasetInUseError,
    DatasetNotFoundError,
    DatasetPage,
    DatasetRecord,
    DatasetSourceConflictError,
    ImportProfile,
)


class SqlAlchemyDatasetCatalogRepository:
    """Persist catalog changes in one short transaction per operation."""

    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def create(self, *, name: str, description: str | None) -> DatasetRecord:
        async with transactional_session(self._session_factory) as session:
            row = Dataset(name=name, description=description, source_type="uploaded")
            session.add(row)
            await session.flush()
            return _to_dataset_record(row, version_count=0)

    async def list(self, *, page: int, page_size: int) -> DatasetPage:
        async with transactional_session(self._session_factory) as session:
            version_count = (
                select(func.count(DatasetVersion.id))
                .where(DatasetVersion.dataset_id == Dataset.id)
                .correlate(Dataset)
                .scalar_subquery()
            )
            statement = (
                select(Dataset, version_count)
                .order_by(Dataset.created_at.desc(), Dataset.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await session.execute(statement)).all()
            total = int(await session.scalar(select(func.count(Dataset.id))) or 0)
            return DatasetPage(
                items=tuple(
                    _to_dataset_record(dataset, version_count=int(count)) for dataset, count in rows
                ),
                page=page,
                page_size=page_size,
                total=total,
            )

    async def get(self, dataset_id: UUID) -> DatasetRecord | None:
        async with transactional_session(self._session_factory) as session:
            row = await session.get(Dataset, dataset_id)
            if row is None:
                return None
            count = int(
                await session.scalar(
                    select(func.count(DatasetVersion.id)).where(
                        DatasetVersion.dataset_id == dataset_id
                    )
                )
                or 0
            )
            return _to_dataset_record(row, version_count=count)

    async def update(self, dataset_id: UUID, changes: DatasetChanges) -> DatasetRecord | None:
        async with transactional_session(self._session_factory) as session:
            row = await session.scalar(
                select(Dataset).where(Dataset.id == dataset_id).with_for_update()
            )
            if row is None:
                return None
            if changes.set_name:
                if changes.name is None:
                    raise ValueError("Dataset name cannot be null")
                row.name = changes.name
            if changes.set_description:
                row.description = changes.description
            row.updated_at = datetime.now(UTC)
            count = int(
                await session.scalar(
                    select(func.count(DatasetVersion.id)).where(
                        DatasetVersion.dataset_id == dataset_id
                    )
                )
                or 0
            )
            await session.flush()
            return _to_dataset_record(row, version_count=count)

    async def delete_if_empty(self, dataset_id: UUID) -> bool:
        async with transactional_session(self._session_factory) as session:
            row = await session.scalar(
                select(Dataset).where(Dataset.id == dataset_id).with_for_update()
            )
            if row is None:
                return False
            has_version = bool(
                await session.scalar(
                    select(exists().where(DatasetVersion.dataset_id == dataset_id))
                )
            )
            has_import = bool(
                await session.scalar(select(exists().where(DatasetImport.dataset_id == dataset_id)))
            )
            if has_version or has_import:
                raise DatasetInUseError("Dataset has immutable imports or versions")
            await session.delete(row)
            await session.flush()
            return True

    async def stage_import(
        self,
        *,
        dataset_id: UUID,
        artifact: ArtifactMetadata,
        import_profile: ImportProfile,
        import_options: Mapping[str, Any],
        detected_format: Mapping[str, Any],
        preview: Mapping[str, Any],
    ) -> DatasetImportRecord:
        async with transactional_session(self._session_factory) as session:
            dataset = await session.scalar(
                select(Dataset).where(Dataset.id == dataset_id).with_for_update()
            )
            if dataset is None:
                raise DatasetNotFoundError("Dataset was not found")
            duplicate = await session.scalar(
                select(DatasetVersion.id).where(
                    DatasetVersion.dataset_id == dataset_id,
                    DatasetVersion.source_sha256 == artifact.sha256,
                )
            )
            if duplicate is not None:
                raise DatasetSourceConflictError("Dataset source checksum already exists")

            version_no = (
                int(
                    await session.scalar(
                        select(func.coalesce(func.max(DatasetVersion.version_no), 0)).where(
                            DatasetVersion.dataset_id == dataset_id
                        )
                    )
                    or 0
                )
                + 1
            )
            version_id = uuid4()
            import_id = uuid4()
            job_id = uuid4()
            options = dict(import_options)
            detected = dict(detected_format)
            version = DatasetVersion(
                id=version_id,
                dataset_id=dataset_id,
                version_no=version_no,
                status="uploaded",
                raw_artifact_id=artifact.id,
                source_sha256=artifact.sha256,
                timezone_context=_optional_string(options.get("timezone")),
                quality_policy={},
                transformation_manifest={},
            )
            job = Job(
                id=job_id,
                job_type="dataset_import",
                status="queued",
                priority=0,
                payload={
                    "dataset_id": str(dataset_id),
                    "dataset_version_id": str(version_id),
                    "import_id": str(import_id),
                    "artifact_id": str(artifact.id),
                    "import_profile": import_profile.value,
                    "import_options": options,
                    "detected_format": detected,
                },
                progress_pct=0,
                attempt=0,
                max_attempts=3,
            )
            import_row = DatasetImport(
                id=import_id,
                dataset_id=dataset_id,
                dataset_version_id=version_id,
                job_id=job_id,
                import_profile=import_profile.value,
                status=DatasetImportStatus.QUEUED.value,
                import_options=options,
                detected_format=detected,
                preview=dict(preview),
            )
            session.add_all((version, job))
            await session.flush()
            session.add(import_row)
            await session.flush()
            return _to_import_record(import_row)

    async def get_import(self, import_id: UUID) -> DatasetImportRecord | None:
        async with transactional_session(self._session_factory) as session:
            row = await session.get(DatasetImport, import_id)
            return None if row is None else _to_import_record(row)


def _to_dataset_record(row: Dataset, *, version_count: int) -> DatasetRecord:
    return DatasetRecord(
        id=row.id,
        name=row.name,
        description=row.description,
        version_count=version_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_import_record(row: DatasetImport) -> DatasetImportRecord:
    if row.dataset_version_id is None:
        raise ValueError("A staged dataset import must reference a dataset version")
    return DatasetImportRecord(
        id=row.id,
        dataset_id=row.dataset_id,
        dataset_version_id=row.dataset_version_id,
        job_id=row.job_id,
        import_profile=ImportProfile(row.import_profile),
        status=DatasetImportStatus(row.status),
        import_options=dict(row.import_options),
        detected_format=dict(row.detected_format or {}),
        preview=dict(row.preview) if row.preview is not None else None,
        import_report=dict(row.import_report) if row.import_report is not None else None,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
