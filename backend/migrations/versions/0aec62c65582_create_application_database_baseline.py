"""create application database baseline

Revision ID: 0aec62c65582
Revises:
Create Date: 2026-08-07 01:00:44.671639
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0aec62c65582"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS ts")
    op.execute("CREATE SCHEMA IF NOT EXISTS ml")

    op.create_table(
        "artifacts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=True),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('raw_dataset', 'model', 'metrics', 'predictions', 'forecast_export', 'chart', 'manifest', 'other')"
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),
        sa.CheckConstraint("size_bytes >= 0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
        schema="app",
    )
    op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"], unique=False, schema="app")
    op.create_table(
        "datasets",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column(
            "source_type",
            sa.String(length=32),
            server_default=sa.text("'uploaded'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source_type IN ('uploaded', 'uci')"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'queued'"), nullable=False
        ),
        sa.Column("priority", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("progress_pct", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("worker_id", sa.String(length=120), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "job_type IN ('dataset_import', 'data_validation', 'data_transformation', 'weather_import', 'experiment', 'forecast', 'export')"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'cancel_requested', 'cancelled', 'succeeded', 'failed', 'stale')"
        ),
        sa.CheckConstraint("attempt <= max_attempts"),
        sa.CheckConstraint("attempt >= 0"),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at"
        ),
        sa.CheckConstraint("max_attempts >= 1"),
        sa.CheckConstraint("progress_pct BETWEEN 0 AND 100"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_jobs_claim",
        "jobs",
        [sa.literal_column("priority DESC"), "created_at"],
        unique=False,
        schema="app",
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "ix_jobs_status_created",
        "jobs",
        ["status", sa.literal_column("created_at DESC")],
        unique=False,
        schema="app",
    )
    op.create_table(
        "weather_locations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180"),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("parent_version_id", sa.UUID(), nullable=True),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("raw_artifact_id", sa.UUID(), nullable=True),
        sa.Column("source_sha256", sa.CHAR(length=64), nullable=True),
        sa.Column("timezone_context", sa.String(length=80), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("valid_row_count", sa.BigInteger(), nullable=True),
        sa.Column("min_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "quality_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "transformation_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'importing', 'imported', 'validating', 'ready_for_transformation', 'transforming', 'ready', 'failed')"
        ),
        sa.CheckConstraint("interval_seconds IS NULL OR interval_seconds > 0"),
        sa.CheckConstraint(
            "min_timestamp IS NULL OR max_timestamp IS NULL OR min_timestamp <= max_timestamp"
        ),
        sa.CheckConstraint("row_count IS NULL OR row_count >= 0"),
        sa.CheckConstraint(
            "row_count IS NULL OR valid_row_count IS NULL OR valid_row_count <= row_count"
        ),
        sa.CheckConstraint("valid_row_count IS NULL OR valid_row_count >= 0"),
        sa.CheckConstraint("version_no >= 1"),
        sa.ForeignKeyConstraint(["dataset_id"], ["app.datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_version_id"], ["app.dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["raw_artifact_id"], ["app.artifacts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "version_no"),
        schema="app",
    )
    op.create_index(
        "ix_dataset_versions_dataset_created",
        "dataset_versions",
        ["dataset_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="app",
    )
    op.create_index(
        "ux_dataset_versions_source",
        "dataset_versions",
        ["dataset_id", "source_sha256"],
        unique=True,
        schema="app",
        postgresql_where=sa.text("source_sha256 IS NOT NULL"),
    )
    op.execute(
        """
        CREATE TABLE ts.weather_observations (
            location_id uuid NOT NULL
                REFERENCES app.weather_locations(id) ON DELETE CASCADE,
            observed_at timestamptz NOT NULL,
            temperature_2m_c double precision,
            relative_humidity_2m_pct double precision
                CHECK (relative_humidity_2m_pct IS NULL
                    OR relative_humidity_2m_pct BETWEEN 0 AND 100),
            apparent_temperature_c double precision,
            precipitation_mm double precision
                CHECK (precipitation_mm IS NULL OR precipitation_mm >= 0),
            wind_speed_10m_kmh double precision
                CHECK (wind_speed_10m_kmh IS NULL OR wind_speed_10m_kmh >= 0),
            source_model varchar(80) NOT NULL,
            source_resolution varchar(40) NOT NULL,
            retrieved_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (location_id, observed_at)
        ) WITH (
            tsdb.hypertable,
            tsdb.partition_column = 'observed_at',
            tsdb.create_default_indexes = false
        )
        """
    )
    op.create_index(
        "ix_weather_location_time",
        "weather_observations",
        ["location_id", sa.literal_column("observed_at DESC")],
        unique=False,
        schema="ts",
    )
    op.create_table(
        "data_quality_issues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("dataset_version_id", sa.UUID(), nullable=False),
        sa.Column("issue_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_row_number", sa.BigInteger(), nullable=True),
        sa.Column("column_name", sa.String(length=100), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "issue_type IN ('missing', 'exact_duplicate', 'conflicting_duplicate', 'time_gap', 'invalid_value', 'statistical_anomaly', 'timezone_ambiguity', 'parse_error')"
        ),
        sa.CheckConstraint("severity IN ('info', 'warning', 'error')"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["app.dataset_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="app",
    )
    op.create_index(
        "ix_quality_issues_version_time",
        "data_quality_issues",
        ["dataset_version_id", "observed_at"],
        unique=False,
        schema="app",
        postgresql_where=sa.text("observed_at IS NOT NULL"),
    )
    op.create_index(
        "ix_quality_issues_version_type",
        "data_quality_issues",
        ["dataset_version_id", "issue_type"],
        unique=False,
        schema="app",
    )
    op.create_table(
        "dataset_imports",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_id", sa.UUID(), nullable=False),
        sa.Column("dataset_version_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("import_profile", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("import_options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_format", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("preview", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("import_profile IN ('uci', 'generic_csv')"),
        sa.CheckConstraint(
            "status IN ('staged', 'queued', 'running', 'completed', 'failed', 'cancelled')"
        ),
        sa.ForeignKeyConstraint(["dataset_id"], ["app.datasets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["app.dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["app.jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        schema="app",
    )
    op.create_table(
        "transformation_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_version_id", sa.UUID(), nullable=False),
        sa.Column("target_version_id", sa.UUID(), nullable=True),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')"),
        sa.ForeignKeyConstraint(["job_id"], ["app.jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_version_id"], ["app.dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["target_version_id"], ["app.dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        sa.UniqueConstraint("target_version_id"),
        schema="app",
    )
    op.create_table(
        "experiments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("dataset_version_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("weather_mode", sa.String(length=2), nullable=False),
        sa.Column(
            "forecast_horizon", sa.SmallInteger(), server_default=sa.text("24"), nullable=False
        ),
        sa.Column("feature_schema_version", sa.String(length=80), nullable=False),
        sa.Column("split_definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selection_rule_version", sa.String(length=80), nullable=False),
        sa.Column("code_commit", sa.String(length=64), nullable=True),
        sa.Column(
            "environment_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("final_test_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'queued', 'running', 'cancelling', 'cancelled', 'completed', 'failed')"
        ),
        sa.CheckConstraint("weather_mode IN ('W0', 'W1')"),
        sa.CheckConstraint("forecast_horizon = 24"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["app.dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["app.jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        schema="ml",
    )
    op.create_index(
        "ix_experiments_version_created",
        "experiments",
        ["dataset_version_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="ml",
    )
    op.execute(
        """
        CREATE TABLE ts.hourly_observations (
            dataset_version_id uuid NOT NULL
                REFERENCES app.dataset_versions(id) ON DELETE CASCADE,
            hour_start timestamptz NOT NULL,
            timezone_context varchar(80),
            energy_kwh double precision NOT NULL CHECK (energy_kwh >= 0),
            mean_active_power_kw double precision
                CHECK (mean_active_power_kw IS NULL OR mean_active_power_kw >= 0),
            mean_reactive_power_kw double precision
                CHECK (mean_reactive_power_kw IS NULL OR mean_reactive_power_kw >= 0),
            mean_voltage_v double precision
                CHECK (mean_voltage_v IS NULL OR mean_voltage_v > 0),
            min_voltage_v double precision CHECK (min_voltage_v IS NULL OR min_voltage_v > 0),
            max_voltage_v double precision CHECK (max_voltage_v IS NULL OR max_voltage_v > 0),
            mean_current_a double precision
                CHECK (mean_current_a IS NULL OR mean_current_a >= 0),
            max_current_a double precision
                CHECK (max_current_a IS NULL OR max_current_a >= 0),
            observed_samples smallint NOT NULL CHECK (observed_samples >= 0),
            expected_samples smallint NOT NULL CHECK (expected_samples > 0),
            coverage_ratio double precision NOT NULL CHECK (coverage_ratio BETWEEN 0 AND 1),
            imputed_samples smallint NOT NULL DEFAULT 0 CHECK (imputed_samples >= 0),
            max_missing_run smallint NOT NULL DEFAULT 0 CHECK (max_missing_run >= 0),
            quality_status varchar(32) NOT NULL CHECK (quality_status IN (
                'complete', 'imputed_short_gap', 'valid_partial',
                'invalid_missing', 'invalid_conflict', 'invalid_value'
            )),
            quality_flags text[] NOT NULL DEFAULT '{}'::text[],
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (dataset_version_id, hour_start),
            CHECK (observed_samples <= expected_samples),
            CHECK (imputed_samples <= expected_samples)
        ) WITH (
            tsdb.hypertable,
            tsdb.partition_column = 'hour_start',
            tsdb.create_default_indexes = false
        )
        """
    )
    op.create_index(
        "ix_hourly_training_ready",
        "hourly_observations",
        ["dataset_version_id", sa.literal_column("hour_start DESC")],
        unique=False,
        schema="ts",
        postgresql_where=sa.text("quality_status IN ('complete', 'imputed_short_gap')"),
    )
    op.create_index(
        "ix_hourly_version_time",
        "hourly_observations",
        ["dataset_version_id", sa.literal_column("hour_start DESC")],
        unique=False,
        schema="ts",
    )
    op.execute(
        """
        CREATE TABLE ts.raw_measurements (
            dataset_version_id uuid NOT NULL
                REFERENCES app.dataset_versions(id) ON DELETE CASCADE,
            observed_at timestamptz NOT NULL,
            source_row_number bigint NOT NULL CHECK (source_row_number >= 1),
            timestamp_original varchar(80),
            timezone_context varchar(80),
            interval_seconds integer
                CHECK (interval_seconds IS NULL OR interval_seconds > 0),
            energy_kwh double precision CHECK (energy_kwh IS NULL OR energy_kwh >= 0),
            active_power_kw double precision
                CHECK (active_power_kw IS NULL OR active_power_kw >= 0),
            reactive_power_kw double precision
                CHECK (reactive_power_kw IS NULL OR reactive_power_kw >= 0),
            voltage_v double precision CHECK (voltage_v IS NULL OR voltage_v > 0),
            current_a double precision CHECK (current_a IS NULL OR current_a >= 0),
            sub_metering_1_wh double precision
                CHECK (sub_metering_1_wh IS NULL OR sub_metering_1_wh >= 0),
            sub_metering_2_wh double precision
                CHECK (sub_metering_2_wh IS NULL OR sub_metering_2_wh >= 0),
            sub_metering_3_wh double precision
                CHECK (sub_metering_3_wh IS NULL OR sub_metering_3_wh >= 0),
            parse_status varchar(20) NOT NULL
                CHECK (parse_status IN ('valid', 'warning', 'invalid')),
            quality_flags text[] NOT NULL DEFAULT '{}'::text[],
            imported_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (dataset_version_id, observed_at, source_row_number)
        ) WITH (
            tsdb.hypertable,
            tsdb.partition_column = 'observed_at',
            tsdb.create_default_indexes = false
        )
        """
    )
    op.create_index(
        "ix_raw_version_time",
        "raw_measurements",
        ["dataset_version_id", sa.literal_column("observed_at DESC")],
        unique=False,
        schema="ts",
    )
    op.create_table(
        "model_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("experiment_id", sa.UUID(), nullable=False),
        sa.Column("algorithm", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "hyperparameters",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("random_seed", sa.Integer(), server_default=sa.text("42"), nullable=False),
        sa.Column("mean_cv_mae", sa.Double(), nullable=True),
        sa.Column("std_cv_mae", sa.Double(), nullable=True),
        sa.Column("final_mae", sa.Double(), nullable=True),
        sa.Column("final_rmse", sa.Double(), nullable=True),
        sa.Column("final_smape", sa.Double(), nullable=True),
        sa.Column("train_seconds", sa.Double(), nullable=True),
        sa.Column("predict_ms_median", sa.Double(), nullable=True),
        sa.Column("artifact_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("artifact_id", sa.UUID(), nullable=True),
        sa.Column("is_recommended", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "algorithm IN ('seasonal_naive_24', 'seasonal_naive_168', 'ridge', 'random_forest', 'hist_gradient_boosting')"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'tuning', 'selected_parameters', 'fitting_final', 'evaluating', 'completed', 'failed', 'cancelled')"
        ),
        sa.CheckConstraint("artifact_size_bytes IS NULL OR artifact_size_bytes >= 0"),
        sa.CheckConstraint("final_mae IS NULL OR final_mae >= 0"),
        sa.CheckConstraint("final_rmse IS NULL OR final_rmse >= 0"),
        sa.CheckConstraint("final_smape IS NULL OR final_smape >= 0"),
        sa.CheckConstraint("mean_cv_mae IS NULL OR mean_cv_mae >= 0"),
        sa.CheckConstraint("predict_ms_median IS NULL OR predict_ms_median >= 0"),
        sa.CheckConstraint("std_cv_mae IS NULL OR std_cv_mae >= 0"),
        sa.CheckConstraint("train_seconds IS NULL OR train_seconds >= 0"),
        sa.ForeignKeyConstraint(["artifact_id"], ["app.artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["experiment_id"], ["ml.experiments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="ml",
    )
    op.create_index(
        "ix_model_runs_experiment",
        "model_runs",
        ["experiment_id", "created_at"],
        unique=False,
        schema="ml",
    )
    op.create_index(
        "ux_one_recommended_model_per_experiment",
        "model_runs",
        ["experiment_id"],
        unique=True,
        schema="ml",
        postgresql_where=sa.text("is_recommended"),
    )
    op.create_table(
        "fold_metrics",
        sa.Column("model_run_id", sa.UUID(), nullable=False),
        sa.Column("fold_no", sa.SmallInteger(), nullable=False),
        sa.Column("train_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validation_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validation_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation_rows", sa.Integer(), nullable=False),
        sa.Column("mae", sa.Double(), nullable=False),
        sa.Column("rmse", sa.Double(), nullable=False),
        sa.Column("smape", sa.Double(), nullable=False),
        sa.Column("train_seconds", sa.Double(), nullable=False),
        sa.CheckConstraint("evaluation_rows > 0"),
        sa.CheckConstraint("fold_no BETWEEN 1 AND 4"),
        sa.CheckConstraint("mae >= 0"),
        sa.CheckConstraint("rmse >= 0"),
        sa.CheckConstraint("smape >= 0"),
        sa.CheckConstraint("train_end < validation_start"),
        sa.CheckConstraint("train_seconds >= 0"),
        sa.CheckConstraint("train_start <= train_end"),
        sa.CheckConstraint("validation_start <= validation_end"),
        sa.ForeignKeyConstraint(["model_run_id"], ["ml.model_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("model_run_id", "fold_no"),
        schema="ml",
    )
    op.create_table(
        "forecasts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("model_run_id", sa.UUID(), nullable=False),
        sa.Column("dataset_version_id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=True),
        sa.Column("origin", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_energy_kwh", sa.Double(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'failed', 'cancelled')"),
        sa.CheckConstraint("total_energy_kwh IS NULL OR total_energy_kwh >= 0"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"], ["app.dataset_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["app.jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_run_id"], ["ml.model_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        schema="ml",
    )
    op.create_index(
        "ix_forecasts_version_created",
        "forecasts",
        ["dataset_version_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="ml",
    )
    op.create_table(
        "horizon_metrics",
        sa.Column("model_run_id", sa.UUID(), nullable=False),
        sa.Column("evaluation_scope", sa.String(length=20), nullable=False),
        sa.Column("horizon", sa.SmallInteger(), nullable=False),
        sa.Column("mae", sa.Double(), nullable=False),
        sa.Column("rmse", sa.Double(), nullable=False),
        sa.Column("smape", sa.Double(), nullable=False),
        sa.CheckConstraint("evaluation_scope IN ('cv', 'final_test')"),
        sa.CheckConstraint("horizon BETWEEN 1 AND 24"),
        sa.CheckConstraint("mae >= 0"),
        sa.CheckConstraint("rmse >= 0"),
        sa.CheckConstraint("smape >= 0"),
        sa.ForeignKeyConstraint(["model_run_id"], ["ml.model_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("model_run_id", "evaluation_scope", "horizon"),
        schema="ml",
    )
    op.create_table(
        "forecast_points",
        sa.Column("forecast_id", sa.UUID(), nullable=False),
        sa.Column("horizon", sa.SmallInteger(), nullable=False),
        sa.Column("target_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_energy_kwh", sa.Double(), nullable=False),
        sa.Column("actual_energy_kwh", sa.Double(), nullable=True),
        sa.CheckConstraint("actual_energy_kwh IS NULL OR actual_energy_kwh >= 0"),
        sa.CheckConstraint("horizon BETWEEN 1 AND 24"),
        sa.CheckConstraint("predicted_energy_kwh >= 0"),
        sa.ForeignKeyConstraint(["forecast_id"], ["ml.forecasts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("forecast_id", "horizon"),
        sa.UniqueConstraint("forecast_id", "target_time"),
        schema="ml",
    )


def downgrade() -> None:
    op.drop_table("forecast_points", schema="ml")
    op.drop_table("horizon_metrics", schema="ml")
    op.drop_index("ix_forecasts_version_created", table_name="forecasts", schema="ml")
    op.drop_table("forecasts", schema="ml")
    op.drop_table("fold_metrics", schema="ml")
    op.drop_index(
        "ux_one_recommended_model_per_experiment",
        table_name="model_runs",
        schema="ml",
        postgresql_where=sa.text("is_recommended"),
    )
    op.drop_index("ix_model_runs_experiment", table_name="model_runs", schema="ml")
    op.drop_table("model_runs", schema="ml")
    op.drop_index("ix_raw_version_time", table_name="raw_measurements", schema="ts")
    op.drop_table("raw_measurements", schema="ts")
    op.drop_index("ix_hourly_version_time", table_name="hourly_observations", schema="ts")
    op.drop_index(
        "ix_hourly_training_ready",
        table_name="hourly_observations",
        schema="ts",
        postgresql_where=sa.text("quality_status IN ('complete', 'imputed_short_gap')"),
    )
    op.drop_table("hourly_observations", schema="ts")
    op.drop_index("ix_experiments_version_created", table_name="experiments", schema="ml")
    op.drop_table("experiments", schema="ml")
    op.drop_table("transformation_runs", schema="app")
    op.drop_table("dataset_imports", schema="app")
    op.drop_index("ix_quality_issues_version_type", table_name="data_quality_issues", schema="app")
    op.drop_index(
        "ix_quality_issues_version_time",
        table_name="data_quality_issues",
        schema="app",
        postgresql_where=sa.text("observed_at IS NOT NULL"),
    )
    op.drop_table("data_quality_issues", schema="app")
    op.drop_index("ix_weather_location_time", table_name="weather_observations", schema="ts")
    op.drop_table("weather_observations", schema="ts")
    op.drop_index(
        "ux_dataset_versions_source",
        table_name="dataset_versions",
        schema="app",
        postgresql_where=sa.text("source_sha256 IS NOT NULL"),
    )
    op.drop_index(
        "ix_dataset_versions_dataset_created", table_name="dataset_versions", schema="app"
    )
    op.drop_table("dataset_versions", schema="app")
    op.drop_table("weather_locations", schema="app")
    op.drop_index("ix_jobs_status_created", table_name="jobs", schema="app")
    op.drop_index(
        "ix_jobs_claim",
        table_name="jobs",
        schema="app",
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.drop_table("jobs", schema="app")
    op.drop_table("datasets", schema="app")
    op.drop_index("ix_artifacts_sha256", table_name="artifacts", schema="app")
    op.drop_table("artifacts", schema="app")
    op.execute("DROP SCHEMA ml")
    op.execute("DROP SCHEMA ts")
    op.execute("DROP SCHEMA app")
