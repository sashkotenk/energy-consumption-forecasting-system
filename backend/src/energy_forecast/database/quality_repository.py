"""PostgreSQL persistence adapter for versioned data-quality reports."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, insert, select

from energy_forecast.database.models import (
    DataQualityIssue,
    DataQualityReport,
    DatasetVersion,
    RawMeasurement,
)
from energy_forecast.database.session import AsyncSessionFactory, transactional_session
from energy_forecast.quality.models import (
    EvaluatedQualityReport,
    QualityMeasurement,
    QualityReportPage,
    StoredQualityIssue,
    StoredQualityReport,
)


class SqlAlchemyQualityRepository:
    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def load_measurements(self, dataset_version_id: UUID) -> tuple[QualityMeasurement, ...]:
        async with transactional_session(self._session_factory) as session:
            if await session.get(DatasetVersion, dataset_version_id) is None:
                raise LookupError("Dataset version was not found")
            rows = (
                await session.scalars(
                    select(RawMeasurement)
                    .where(RawMeasurement.dataset_version_id == dataset_version_id)
                    .order_by(RawMeasurement.source_row_number, RawMeasurement.observed_at)
                )
            ).all()
            return tuple(_to_quality_measurement(row) for row in rows)

    async def save_report(
        self, dataset_version_id: UUID, report: EvaluatedQualityReport
    ) -> StoredQualityReport:
        async with transactional_session(self._session_factory) as session:
            version = await session.scalar(
                select(DatasetVersion)
                .where(DatasetVersion.id == dataset_version_id)
                .with_for_update()
            )
            if version is None:
                raise LookupError("Dataset version was not found")
            report_version = (
                int(
                    await session.scalar(
                        select(func.coalesce(func.max(DataQualityReport.report_version), 0)).where(
                            DataQualityReport.dataset_version_id == dataset_version_id
                        )
                    )
                    or 0
                )
                + 1
            )
            report_row = DataQualityReport(
                id=uuid4(),
                dataset_version_id=dataset_version_id,
                report_version=report_version,
                engine_version=report.engine_version,
                expected_interval_seconds=report.expected_interval_seconds,
                summary=report.summary,
            )
            session.add(report_row)
            await session.flush()
            if report.issues:
                await session.execute(
                    insert(DataQualityIssue),
                    [
                        {
                            "dataset_version_id": dataset_version_id,
                            "report_id": report_row.id,
                            "issue_type": issue.issue_type,
                            "severity": issue.severity,
                            "observed_at": issue.range_start,
                            "range_end": issue.range_end,
                            "occurrence_count": issue.occurrence_count,
                            "column_name": issue.column_name,
                            "details": {"evidence": list(issue.evidence)},
                        }
                        for issue in report.issues
                    ],
                )
            version.status = "ready_for_transformation"
            version.quality_policy = {
                "report_id": str(report_row.id),
                "report_version": report_version,
                "engine_version": report.engine_version,
            }
            await session.flush()
            return _to_stored_report(report_row)

    async def get_report_page(
        self,
        dataset_version_id: UUID,
        *,
        report_version: int | None,
        page: int,
        page_size: int,
    ) -> QualityReportPage | None:
        async with transactional_session(self._session_factory) as session:
            report_query = select(DataQualityReport).where(
                DataQualityReport.dataset_version_id == dataset_version_id
            )
            if report_version is None:
                report_query = report_query.order_by(DataQualityReport.report_version.desc()).limit(
                    1
                )
            else:
                report_query = report_query.where(
                    DataQualityReport.report_version == report_version
                )
            report = await session.scalar(report_query)
            if report is None:
                return None
            issue_filter = DataQualityIssue.report_id == report.id
            total = int(
                await session.scalar(select(func.count(DataQualityIssue.id)).where(issue_filter))
                or 0
            )
            issues = (
                await session.scalars(
                    select(DataQualityIssue)
                    .where(issue_filter)
                    .order_by(
                        DataQualityIssue.issue_type,
                        DataQualityIssue.column_name,
                        DataQualityIssue.observed_at,
                        DataQualityIssue.id,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            return QualityReportPage(
                report=_to_stored_report(report),
                items=tuple(_to_stored_issue(issue) for issue in issues),
                page=page,
                page_size=page_size,
                total=total,
            )


def _to_quality_measurement(row: RawMeasurement) -> QualityMeasurement:
    return QualityMeasurement(
        source_row_number=row.source_row_number,
        observed_at=row.observed_at,
        energy_kwh=row.energy_kwh,
        active_power_kw=row.active_power_kw,
        reactive_power_kw=row.reactive_power_kw,
        voltage_v=row.voltage_v,
        current_a=row.current_a,
        sub_metering_1_wh=row.sub_metering_1_wh,
        sub_metering_2_wh=row.sub_metering_2_wh,
        sub_metering_3_wh=row.sub_metering_3_wh,
        parse_status=row.parse_status,
        quality_flags=tuple(row.quality_flags),
    )


def _to_stored_report(row: DataQualityReport) -> StoredQualityReport:
    return StoredQualityReport(
        id=row.id,
        dataset_version_id=row.dataset_version_id,
        report_version=row.report_version,
        engine_version=row.engine_version,
        expected_interval_seconds=row.expected_interval_seconds,
        summary=dict(row.summary),
        created_at=row.created_at,
    )


def _to_stored_issue(row: DataQualityIssue) -> StoredQualityIssue:
    raw_evidence = row.details.get("evidence", [])
    evidence = tuple(item for item in raw_evidence if isinstance(item, dict))
    return StoredQualityIssue(
        id=row.id,
        issue_type=row.issue_type,
        severity=row.severity,
        range_start=row.observed_at,
        range_end=row.range_end,
        occurrence_count=row.occurrence_count,
        column_name=row.column_name,
        evidence=evidence,
    )
