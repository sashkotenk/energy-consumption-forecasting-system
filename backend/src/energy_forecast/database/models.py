"""SQLAlchemy 2.x mappings for the app, ts, and ml PostgreSQL schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import CHAR, JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from energy_forecast.database.base import Base

JSON: Any = JSONB
UUID_TYPE: Any = PostgreSQLUUID


def uuid_primary_key() -> Mapped[UUID]:
    return mapped_column(
        UUID_TYPE(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def created_timestamp() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        CheckConstraint("source_type IN ('uploaded', 'uci')"),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000))
    source_type: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'uploaded'")
    )
    created_at: Mapped[datetime] = created_timestamp()
    updated_at: Mapped[datetime] = created_timestamp()


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('raw_dataset', 'model', 'metrics', 'predictions', "
            "'forecast_export', 'chart', 'manifest', 'other')"
        ),
        CheckConstraint("size_bytes >= 0"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),
        Index("ix_artifacts_sha256", "sha256"),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    original_name: Mapped[str | None] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = created_timestamp()


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version_no"),
        CheckConstraint("version_no >= 1"),
        CheckConstraint(
            "status IN ('uploaded', 'importing', 'imported', 'validating', "
            "'ready_for_transformation', 'transforming', 'ready', 'failed')"
        ),
        CheckConstraint("source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'"),
        CheckConstraint("interval_seconds IS NULL OR interval_seconds > 0"),
        CheckConstraint("row_count IS NULL OR row_count >= 0"),
        CheckConstraint("valid_row_count IS NULL OR valid_row_count >= 0"),
        CheckConstraint(
            "min_timestamp IS NULL OR max_timestamp IS NULL OR min_timestamp <= max_timestamp"
        ),
        CheckConstraint(
            "row_count IS NULL OR valid_row_count IS NULL OR valid_row_count <= row_count"
        ),
        Index(
            "ux_dataset_versions_source",
            "dataset_id",
            "source_sha256",
            unique=True,
            postgresql_where=text("source_sha256 IS NOT NULL"),
        ),
        Index("ix_dataset_versions_dataset_created", "dataset_id", desc("created_at")),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    dataset_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.datasets.id", ondelete="CASCADE"), nullable=False
    )
    parent_version_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.dataset_versions.id", ondelete="RESTRICT")
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_artifact_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.artifacts.id", ondelete="RESTRICT")
    )
    source_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    timezone_context: Mapped[str | None] = mapped_column(String(80))
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    valid_row_count: Mapped[int | None] = mapped_column(BigInteger)
    min_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_policy: Mapped[dict[str, Any]] = mapped_column(
        JSON(), nullable=False, server_default=text("'{}'::jsonb")
    )
    transformation_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON(), nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_timestamp()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ('dataset_import', 'data_validation', 'data_transformation', "
            "'weather_import', 'experiment', 'forecast', 'export')"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', 'cancelled', "
            "'succeeded', 'failed', 'stale')"
        ),
        CheckConstraint("progress_pct BETWEEN 0 AND 100"),
        CheckConstraint("attempt >= 0"),
        CheckConstraint("max_attempts >= 1"),
        CheckConstraint("attempt <= max_attempts"),
        CheckConstraint("finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at"),
        Index(
            "ix_jobs_claim",
            desc("priority"),
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "ux_jobs_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_jobs_status_created", "status", desc("created_at")),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    worker_id: Mapped[str | None] = mapped_column(String(120))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp()
    updated_at: Mapped[datetime] = created_timestamp()


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt"),
        CheckConstraint("attempt >= 1"),
        CheckConstraint("status IN ('running', 'cancelled', 'succeeded', 'failed', 'stale')"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at"),
        Index("ix_job_attempts_job_started", "job_id", "started_at"),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    job_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.jobs.id", ondelete="CASCADE"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(120), nullable=False)
    started_at: Mapped[datetime] = created_timestamp()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)


class DatasetImport(Base):
    __tablename__ = "dataset_imports"
    __table_args__ = (
        UniqueConstraint("job_id"),
        CheckConstraint("import_profile IN ('uci', 'generic_csv')"),
        CheckConstraint(
            "status IN ('staged', 'queued', 'running', 'completed', 'failed', 'cancelled')"
        ),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    dataset_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.datasets.id", ondelete="CASCADE"), nullable=False
    )
    dataset_version_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.dataset_versions.id", ondelete="RESTRICT")
    )
    job_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.jobs.id", ondelete="RESTRICT"), nullable=False
    )
    import_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    import_options: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    detected_format: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    preview: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    import_report: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = created_timestamp()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetImportError(Base):
    __tablename__ = "dataset_import_errors"
    __table_args__ = (
        CheckConstraint("source_row_number >= 1"),
        CheckConstraint("parse_status = 'invalid'"),
        Index("ix_import_errors_import_row", "import_id", "source_row_number"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    import_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.dataset_imports.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_row_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parse_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'invalid'")
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSON(), nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_timestamp()


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"
    __table_args__ = (
        CheckConstraint(
            "issue_type IN ('missing', 'non_finite', 'physical_invalidity', "
            "'exact_duplicate', 'conflicting_duplicate', 'time_gap', "
            "'timestamp_order', 'statistical_anomaly', 'timezone_ambiguity', 'parse_error')"
        ),
        CheckConstraint("severity IN ('info', 'warning', 'error')"),
        CheckConstraint("occurrence_count >= 1"),
        CheckConstraint("range_end IS NULL OR observed_at IS NULL OR range_end >= observed_at"),
        Index("ix_quality_issues_version_type", "dataset_version_id", "issue_type"),
        Index(
            "ix_quality_issues_version_time",
            "dataset_version_id",
            "observed_at",
            postgresql_where=text("observed_at IS NOT NULL"),
        ),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    dataset_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.data_quality_reports.id", ondelete="CASCADE")
    )
    issue_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    range_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurrence_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("1")
    )
    source_row_number: Mapped[int | None] = mapped_column(BigInteger)
    column_name: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON(), nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_timestamp()


class DataQualityReport(Base):
    __tablename__ = "data_quality_reports"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "report_version"),
        CheckConstraint("report_version >= 1"),
        CheckConstraint("expected_interval_seconds IS NULL OR expected_interval_seconds > 0"),
        Index(
            "ix_quality_reports_version_latest",
            "dataset_version_id",
            desc("report_version"),
        ),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    dataset_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.dataset_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    expected_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    created_at: Mapped[datetime] = created_timestamp()


class TransformationRun(Base):
    __tablename__ = "transformation_runs"
    __table_args__ = (
        UniqueConstraint("job_id"),
        UniqueConstraint("target_version_id"),
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')"),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    source_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_version_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.dataset_versions.id", ondelete="RESTRICT")
    )
    job_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.jobs.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON())
    created_at: Mapped[datetime] = created_timestamp()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeatherLocation(Base):
    __tablename__ = "weather_locations"
    __table_args__ = (
        CheckConstraint("latitude BETWEEN -90 AND 90"),
        CheckConstraint("longitude BETWEEN -180 AND 180"),
        {"schema": "app"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    latitude: Mapped[float] = mapped_column(Double, nullable=False)
    longitude: Mapped[float] = mapped_column(Double, nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)
    source_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp()


class RawMeasurement(Base):
    __tablename__ = "raw_measurements"
    __table_args__ = (
        CheckConstraint("source_row_number >= 1"),
        CheckConstraint("interval_seconds IS NULL OR interval_seconds > 0"),
        CheckConstraint("parse_status IN ('valid', 'warning', 'invalid')"),
        Index("ix_raw_version_time", "dataset_version_id", desc("observed_at")),
        {"schema": "ts"},
    )

    dataset_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.dataset_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    source_row_number: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    timestamp_original: Mapped[str | None] = mapped_column(String(80))
    timezone_context: Mapped[str | None] = mapped_column(String(80))
    interval_seconds: Mapped[int | None] = mapped_column(Integer)
    energy_kwh: Mapped[float | None] = mapped_column(Double)
    active_power_kw: Mapped[float | None] = mapped_column(Double)
    reactive_power_kw: Mapped[float | None] = mapped_column(Double)
    voltage_v: Mapped[float | None] = mapped_column(Double)
    current_a: Mapped[float | None] = mapped_column(Double)
    sub_metering_1_wh: Mapped[float | None] = mapped_column(Double)
    sub_metering_2_wh: Mapped[float | None] = mapped_column(Double)
    sub_metering_3_wh: Mapped[float | None] = mapped_column(Double)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    imported_at: Mapped[datetime] = created_timestamp()


class HourlyObservation(Base):
    __tablename__ = "hourly_observations"
    __table_args__ = (
        CheckConstraint("energy_kwh >= 0"),
        CheckConstraint("mean_active_power_kw IS NULL OR mean_active_power_kw >= 0"),
        CheckConstraint("mean_reactive_power_kw IS NULL OR mean_reactive_power_kw >= 0"),
        CheckConstraint("mean_voltage_v IS NULL OR mean_voltage_v > 0"),
        CheckConstraint("min_voltage_v IS NULL OR min_voltage_v > 0"),
        CheckConstraint("max_voltage_v IS NULL OR max_voltage_v > 0"),
        CheckConstraint("mean_current_a IS NULL OR mean_current_a >= 0"),
        CheckConstraint("max_current_a IS NULL OR max_current_a >= 0"),
        CheckConstraint("observed_samples >= 0"),
        CheckConstraint("expected_samples > 0"),
        CheckConstraint("coverage_ratio BETWEEN 0 AND 1"),
        CheckConstraint("imputed_samples >= 0"),
        CheckConstraint("max_missing_run >= 0"),
        CheckConstraint(
            "quality_status IN ('complete', 'imputed_short_gap', 'valid_partial', "
            "'invalid_missing', 'invalid_conflict', 'invalid_value')"
        ),
        CheckConstraint("observed_samples <= expected_samples"),
        CheckConstraint("imputed_samples <= expected_samples"),
        Index("ix_hourly_version_time", "dataset_version_id", desc("hour_start")),
        Index(
            "ix_hourly_training_ready",
            "dataset_version_id",
            desc("hour_start"),
            postgresql_where=text("quality_status IN ('complete', 'imputed_short_gap')"),
        ),
        {"schema": "ts"},
    )

    dataset_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.dataset_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    hour_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    timezone_context: Mapped[str | None] = mapped_column(String(80))
    energy_kwh: Mapped[float] = mapped_column(Double, nullable=False)
    mean_active_power_kw: Mapped[float | None] = mapped_column(Double)
    mean_reactive_power_kw: Mapped[float | None] = mapped_column(Double)
    mean_voltage_v: Mapped[float | None] = mapped_column(Double)
    min_voltage_v: Mapped[float | None] = mapped_column(Double)
    max_voltage_v: Mapped[float | None] = mapped_column(Double)
    mean_current_a: Mapped[float | None] = mapped_column(Double)
    max_current_a: Mapped[float | None] = mapped_column(Double)
    observed_samples: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    expected_samples: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    coverage_ratio: Mapped[float] = mapped_column(Double, nullable=False)
    imputed_samples: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    max_missing_run: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    quality_status: Mapped[str] = mapped_column(String(32), nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    created_at: Mapped[datetime] = created_timestamp()


class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    __table_args__ = (
        CheckConstraint(
            "relative_humidity_2m_pct IS NULL OR relative_humidity_2m_pct BETWEEN 0 AND 100"
        ),
        CheckConstraint("precipitation_mm IS NULL OR precipitation_mm >= 0"),
        CheckConstraint("wind_speed_10m_kmh IS NULL OR wind_speed_10m_kmh >= 0"),
        Index("ix_weather_location_time", "location_id", desc("observed_at")),
        {"schema": "ts"},
    )

    location_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.weather_locations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    temperature_2m_c: Mapped[float | None] = mapped_column(Double)
    relative_humidity_2m_pct: Mapped[float | None] = mapped_column(Double)
    apparent_temperature_c: Mapped[float | None] = mapped_column(Double)
    precipitation_mm: Mapped[float | None] = mapped_column(Double)
    wind_speed_10m_kmh: Mapped[float | None] = mapped_column(Double)
    source_model: Mapped[str] = mapped_column(String(80), nullable=False)
    source_resolution: Mapped[str] = mapped_column(String(40), nullable=False)
    retrieved_at: Mapped[datetime] = created_timestamp()


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        UniqueConstraint("job_id"),
        CheckConstraint(
            "status IN ('draft', 'queued', 'running', 'cancelling', "
            "'cancelled', 'completed', 'failed')"
        ),
        CheckConstraint("weather_mode IN ('W0', 'W1')"),
        CheckConstraint("forecast_horizon = 24"),
        Index("ix_experiments_version_created", "dataset_version_id", desc("created_at")),
        {"schema": "ml"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    dataset_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.jobs.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    weather_mode: Mapped[str] = mapped_column(String(2), nullable=False)
    forecast_horizon: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("24")
    )
    feature_schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    split_definition: Mapped[dict[str, Any]] = mapped_column(JSON(), nullable=False)
    selection_rule_version: Mapped[str] = mapped_column(String(80), nullable=False)
    code_commit: Mapped[str | None] = mapped_column(String(64))
    environment_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON(), nullable=False, server_default=text("'{}'::jsonb")
    )
    final_test_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_timestamp()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelRun(Base):
    __tablename__ = "model_runs"
    __table_args__ = (
        CheckConstraint(
            "algorithm IN ('seasonal_naive_24', 'seasonal_naive_168', 'ridge', "
            "'random_forest', 'hist_gradient_boosting')"
        ),
        CheckConstraint(
            "status IN ('pending', 'tuning', 'selected_parameters', 'fitting_final', "
            "'evaluating', 'completed', 'failed', 'cancelled')"
        ),
        CheckConstraint("mean_cv_mae IS NULL OR mean_cv_mae >= 0"),
        CheckConstraint("std_cv_mae IS NULL OR std_cv_mae >= 0"),
        CheckConstraint("final_mae IS NULL OR final_mae >= 0"),
        CheckConstraint("final_rmse IS NULL OR final_rmse >= 0"),
        CheckConstraint("final_smape IS NULL OR final_smape >= 0"),
        CheckConstraint("train_seconds IS NULL OR train_seconds >= 0"),
        CheckConstraint("predict_ms_median IS NULL OR predict_ms_median >= 0"),
        CheckConstraint("artifact_size_bytes IS NULL OR artifact_size_bytes >= 0"),
        Index(
            "ux_one_recommended_model_per_experiment",
            "experiment_id",
            unique=True,
            postgresql_where=text("is_recommended"),
        ),
        Index("ix_model_runs_experiment", "experiment_id", "created_at"),
        {"schema": "ml"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    experiment_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("ml.experiments.id", ondelete="CASCADE"), nullable=False
    )
    algorithm: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(
        JSON(), nullable=False, server_default=text("'{}'::jsonb")
    )
    random_seed: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("42"))
    mean_cv_mae: Mapped[float | None] = mapped_column(Double)
    std_cv_mae: Mapped[float | None] = mapped_column(Double)
    final_mae: Mapped[float | None] = mapped_column(Double)
    final_rmse: Mapped[float | None] = mapped_column(Double)
    final_smape: Mapped[float | None] = mapped_column(Double)
    train_seconds: Mapped[float | None] = mapped_column(Double)
    predict_ms_median: Mapped[float | None] = mapped_column(Double)
    artifact_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    artifact_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.artifacts.id", ondelete="RESTRICT")
    )
    is_recommended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = created_timestamp()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FoldMetric(Base):
    __tablename__ = "fold_metrics"
    __table_args__ = (
        CheckConstraint("fold_no BETWEEN 1 AND 4"),
        CheckConstraint("evaluation_rows > 0"),
        CheckConstraint("mae >= 0"),
        CheckConstraint("rmse >= 0"),
        CheckConstraint("smape >= 0"),
        CheckConstraint("train_seconds >= 0"),
        CheckConstraint("train_start <= train_end"),
        CheckConstraint("validation_start <= validation_end"),
        CheckConstraint("train_end < validation_start"),
        {"schema": "ml"},
    )

    model_run_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("ml.model_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fold_no: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    train_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluation_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    mae: Mapped[float] = mapped_column(Double, nullable=False)
    rmse: Mapped[float] = mapped_column(Double, nullable=False)
    smape: Mapped[float] = mapped_column(Double, nullable=False)
    train_seconds: Mapped[float] = mapped_column(Double, nullable=False)


class HorizonMetric(Base):
    __tablename__ = "horizon_metrics"
    __table_args__ = (
        CheckConstraint("evaluation_scope IN ('cv', 'final_test')"),
        CheckConstraint("horizon BETWEEN 1 AND 24"),
        CheckConstraint("mae >= 0"),
        CheckConstraint("rmse >= 0"),
        CheckConstraint("smape >= 0"),
        {"schema": "ml"},
    )

    model_run_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("ml.model_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    evaluation_scope: Mapped[str] = mapped_column(String(20), primary_key=True)
    horizon: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    mae: Mapped[float] = mapped_column(Double, nullable=False)
    rmse: Mapped[float] = mapped_column(Double, nullable=False)
    smape: Mapped[float] = mapped_column(Double, nullable=False)


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint("job_id"),
        CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')"),
        CheckConstraint("total_energy_kwh IS NULL OR total_energy_kwh >= 0"),
        Index("ix_forecasts_version_created", "dataset_version_id", desc("created_at")),
        {"schema": "ml"},
    )

    id: Mapped[UUID] = uuid_primary_key()
    model_run_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("ml.model_runs.id", ondelete="RESTRICT"), nullable=False
    )
    dataset_version_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True),
        ForeignKey("app.dataset_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("app.jobs.id", ondelete="RESTRICT")
    )
    origin: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    total_energy_kwh: Mapped[float | None] = mapped_column(Double)
    created_at: Mapped[datetime] = created_timestamp()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ForecastPoint(Base):
    __tablename__ = "forecast_points"
    __table_args__ = (
        UniqueConstraint("forecast_id", "target_time"),
        CheckConstraint("horizon BETWEEN 1 AND 24"),
        CheckConstraint("predicted_energy_kwh >= 0"),
        CheckConstraint("actual_energy_kwh IS NULL OR actual_energy_kwh >= 0"),
        {"schema": "ml"},
    )

    forecast_id: Mapped[UUID] = mapped_column(
        UUID_TYPE(as_uuid=True), ForeignKey("ml.forecasts.id", ondelete="CASCADE"), primary_key=True
    )
    horizon: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    target_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    predicted_energy_kwh: Mapped[float] = mapped_column(Double, nullable=False)
    actual_energy_kwh: Mapped[float | None] = mapped_column(Double)
