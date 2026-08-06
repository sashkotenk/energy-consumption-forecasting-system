-- EnergyForecast physical schema design draft
-- Production schema changes must be applied through Alembic migrations.
-- Verify TimescaleDB syntax against the pinned implementation image.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS app;
CREATE SCHEMA IF NOT EXISTS ts;
CREATE SCHEMA IF NOT EXISTS ml;

CREATE TABLE app.datasets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(160) NOT NULL,
    description varchar(2000),
    source_type varchar(32) NOT NULL DEFAULT 'uploaded'
        CHECK (source_type IN ('uploaded', 'uci')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.artifacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind varchar(40) NOT NULL CHECK (kind IN (
        'raw_dataset', 'model', 'metrics', 'predictions',
        'forecast_export', 'chart', 'manifest', 'other'
    )),
    storage_key varchar(500) NOT NULL UNIQUE,
    original_name varchar(255),
    media_type varchar(120) NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_artifacts_sha256 ON app.artifacts (sha256);

CREATE TABLE app.dataset_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id uuid NOT NULL REFERENCES app.datasets(id) ON DELETE CASCADE,
    parent_version_id uuid REFERENCES app.dataset_versions(id) ON DELETE RESTRICT,
    version_no integer NOT NULL CHECK (version_no >= 1),
    status varchar(40) NOT NULL CHECK (status IN (
        'uploaded', 'importing', 'imported', 'validating',
        'ready_for_transformation', 'transforming', 'ready', 'failed'
    )),
    raw_artifact_id uuid REFERENCES app.artifacts(id) ON DELETE RESTRICT,
    source_sha256 char(64) CHECK (
        source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'
    ),
    timezone_context varchar(80),
    interval_seconds integer CHECK (interval_seconds IS NULL OR interval_seconds > 0),
    row_count bigint CHECK (row_count IS NULL OR row_count >= 0),
    valid_row_count bigint CHECK (valid_row_count IS NULL OR valid_row_count >= 0),
    min_timestamp timestamptz,
    max_timestamp timestamptz,
    quality_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    transformation_manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (dataset_id, version_no),
    CHECK (min_timestamp IS NULL OR max_timestamp IS NULL OR min_timestamp <= max_timestamp),
    CHECK (row_count IS NULL OR valid_row_count IS NULL OR valid_row_count <= row_count)
);

CREATE UNIQUE INDEX ux_dataset_versions_source
    ON app.dataset_versions (dataset_id, source_sha256)
    WHERE source_sha256 IS NOT NULL;

CREATE INDEX ix_dataset_versions_dataset_created
    ON app.dataset_versions (dataset_id, created_at DESC);

CREATE TABLE app.jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type varchar(50) NOT NULL CHECK (job_type IN (
        'dataset_import', 'data_validation', 'data_transformation',
        'weather_import', 'experiment', 'forecast', 'export'
    )),
    status varchar(32) NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'running', 'cancel_requested', 'cancelled',
        'succeeded', 'failed', 'stale'
    )),
    priority integer NOT NULL DEFAULT 0,
    payload jsonb NOT NULL,
    result jsonb,
    progress_pct integer NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts integer NOT NULL DEFAULT 1 CHECK (max_attempts >= 1),
    worker_id varchar(120),
    heartbeat_at timestamptz,
    cancel_requested_at timestamptz,
    started_at timestamptz,
    finished_at timestamptz,
    error_code varchar(100),
    error_detail text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (attempt <= max_attempts),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX ix_jobs_claim
    ON app.jobs (priority DESC, created_at)
    WHERE status = 'queued';

CREATE INDEX ix_jobs_status_created
    ON app.jobs (status, created_at DESC);

CREATE TABLE app.dataset_imports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id uuid NOT NULL REFERENCES app.datasets(id) ON DELETE CASCADE,
    dataset_version_id uuid REFERENCES app.dataset_versions(id) ON DELETE RESTRICT,
    job_id uuid NOT NULL REFERENCES app.jobs(id) ON DELETE RESTRICT,
    import_profile varchar(32) NOT NULL
        CHECK (import_profile IN ('uci', 'generic_csv')),
    status varchar(32) NOT NULL CHECK (status IN (
        'staged', 'queued', 'running', 'completed', 'failed', 'cancelled'
    )),
    import_options jsonb NOT NULL,
    detected_format jsonb,
    preview jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id)
);

CREATE TABLE app.data_quality_issues (
    id bigserial PRIMARY KEY,
    dataset_version_id uuid NOT NULL
        REFERENCES app.dataset_versions(id) ON DELETE CASCADE,
    issue_type varchar(50) NOT NULL CHECK (issue_type IN (
        'missing', 'exact_duplicate', 'conflicting_duplicate',
        'time_gap', 'invalid_value', 'statistical_anomaly',
        'timezone_ambiguity', 'parse_error'
    )),
    severity varchar(16) NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    observed_at timestamptz,
    source_row_number bigint,
    column_name varchar(100),
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_quality_issues_version_type
    ON app.data_quality_issues (dataset_version_id, issue_type);

CREATE INDEX ix_quality_issues_version_time
    ON app.data_quality_issues (dataset_version_id, observed_at)
    WHERE observed_at IS NOT NULL;

CREATE TABLE app.transformation_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_version_id uuid NOT NULL
        REFERENCES app.dataset_versions(id) ON DELETE RESTRICT,
    target_version_id uuid
        REFERENCES app.dataset_versions(id) ON DELETE RESTRICT,
    job_id uuid NOT NULL REFERENCES app.jobs(id) ON DELETE RESTRICT,
    status varchar(32) NOT NULL CHECK (status IN (
        'queued', 'running', 'completed', 'failed', 'cancelled'
    )),
    policy jsonb NOT NULL,
    summary jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (job_id),
    UNIQUE (target_version_id)
);

CREATE TABLE ts.raw_measurements (
    dataset_version_id uuid NOT NULL
        REFERENCES app.dataset_versions(id) ON DELETE CASCADE,
    observed_at timestamptz NOT NULL,
    source_row_number bigint NOT NULL CHECK (source_row_number >= 1),
    timestamp_original varchar(80),
    timezone_context varchar(80),
    interval_seconds integer CHECK (interval_seconds IS NULL OR interval_seconds > 0),
    energy_kwh double precision CHECK (energy_kwh IS NULL OR energy_kwh >= 0),
    active_power_kw double precision CHECK (active_power_kw IS NULL OR active_power_kw >= 0),
    reactive_power_kw double precision CHECK (reactive_power_kw IS NULL OR reactive_power_kw >= 0),
    voltage_v double precision CHECK (voltage_v IS NULL OR voltage_v > 0),
    current_a double precision CHECK (current_a IS NULL OR current_a >= 0),
    sub_metering_1_wh double precision CHECK (sub_metering_1_wh IS NULL OR sub_metering_1_wh >= 0),
    sub_metering_2_wh double precision CHECK (sub_metering_2_wh IS NULL OR sub_metering_2_wh >= 0),
    sub_metering_3_wh double precision CHECK (sub_metering_3_wh IS NULL OR sub_metering_3_wh >= 0),
    parse_status varchar(20) NOT NULL CHECK (parse_status IN ('valid', 'warning', 'invalid')),
    quality_flags text[] NOT NULL DEFAULT '{}',
    imported_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_version_id, observed_at, source_row_number)
) WITH (
    tsdb.hypertable,
    tsdb.partition_column = 'observed_at',
    tsdb.create_default_indexes = false
);

CREATE INDEX ix_raw_version_time
    ON ts.raw_measurements (dataset_version_id, observed_at DESC);

CREATE TABLE ts.hourly_observations (
    dataset_version_id uuid NOT NULL
        REFERENCES app.dataset_versions(id) ON DELETE CASCADE,
    hour_start timestamptz NOT NULL,
    timezone_context varchar(80),
    energy_kwh double precision NOT NULL CHECK (energy_kwh >= 0),
    mean_active_power_kw double precision CHECK (mean_active_power_kw IS NULL OR mean_active_power_kw >= 0),
    mean_reactive_power_kw double precision CHECK (mean_reactive_power_kw IS NULL OR mean_reactive_power_kw >= 0),
    mean_voltage_v double precision CHECK (mean_voltage_v IS NULL OR mean_voltage_v > 0),
    min_voltage_v double precision CHECK (min_voltage_v IS NULL OR min_voltage_v > 0),
    max_voltage_v double precision CHECK (max_voltage_v IS NULL OR max_voltage_v > 0),
    mean_current_a double precision CHECK (mean_current_a IS NULL OR mean_current_a >= 0),
    max_current_a double precision CHECK (max_current_a IS NULL OR max_current_a >= 0),
    observed_samples smallint NOT NULL CHECK (observed_samples >= 0),
    expected_samples smallint NOT NULL CHECK (expected_samples > 0),
    coverage_ratio double precision NOT NULL CHECK (coverage_ratio BETWEEN 0 AND 1),
    imputed_samples smallint NOT NULL DEFAULT 0 CHECK (imputed_samples >= 0),
    max_missing_run smallint NOT NULL DEFAULT 0 CHECK (max_missing_run >= 0),
    quality_status varchar(32) NOT NULL CHECK (quality_status IN (
        'complete', 'imputed_short_gap', 'valid_partial',
        'invalid_missing', 'invalid_conflict', 'invalid_value'
    )),
    quality_flags text[] NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_version_id, hour_start),
    CHECK (observed_samples <= expected_samples),
    CHECK (imputed_samples <= expected_samples)
) WITH (
    tsdb.hypertable,
    tsdb.partition_column = 'hour_start',
    tsdb.create_default_indexes = false
);

CREATE INDEX ix_hourly_version_time
    ON ts.hourly_observations (dataset_version_id, hour_start DESC);

CREATE INDEX ix_hourly_training_ready
    ON ts.hourly_observations (dataset_version_id, hour_start DESC)
    WHERE quality_status IN ('complete', 'imputed_short_gap');

CREATE TABLE app.weather_locations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(160) NOT NULL,
    latitude double precision NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude double precision NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    timezone varchar(80) NOT NULL,
    source_note text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ts.weather_observations (
    location_id uuid NOT NULL
        REFERENCES app.weather_locations(id) ON DELETE CASCADE,
    observed_at timestamptz NOT NULL,
    temperature_2m_c double precision,
    relative_humidity_2m_pct double precision
        CHECK (relative_humidity_2m_pct IS NULL OR relative_humidity_2m_pct BETWEEN 0 AND 100),
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
);

CREATE INDEX ix_weather_location_time
    ON ts.weather_observations (location_id, observed_at DESC);

CREATE TABLE ml.experiments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version_id uuid NOT NULL
        REFERENCES app.dataset_versions(id) ON DELETE RESTRICT,
    job_id uuid REFERENCES app.jobs(id) ON DELETE RESTRICT,
    name varchar(160) NOT NULL,
    status varchar(32) NOT NULL CHECK (status IN (
        'draft', 'queued', 'running', 'cancelling',
        'cancelled', 'completed', 'failed'
    )),
    weather_mode varchar(2) NOT NULL CHECK (weather_mode IN ('W0', 'W1')),
    forecast_horizon smallint NOT NULL DEFAULT 24 CHECK (forecast_horizon = 24),
    feature_schema_version varchar(80) NOT NULL,
    split_definition jsonb NOT NULL,
    selection_rule_version varchar(80) NOT NULL,
    code_commit varchar(64),
    environment_manifest jsonb NOT NULL DEFAULT '{}'::jsonb,
    final_test_opened_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    UNIQUE (job_id)
);

CREATE INDEX ix_experiments_version_created
    ON ml.experiments (dataset_version_id, created_at DESC);

CREATE TABLE ml.model_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id uuid NOT NULL
        REFERENCES ml.experiments(id) ON DELETE CASCADE,
    algorithm varchar(60) NOT NULL CHECK (algorithm IN (
        'seasonal_naive_24', 'seasonal_naive_168', 'ridge',
        'random_forest', 'hist_gradient_boosting'
    )),
    status varchar(32) NOT NULL CHECK (status IN (
        'pending', 'tuning', 'selected_parameters', 'fitting_final',
        'evaluating', 'completed', 'failed', 'cancelled'
    )),
    hyperparameters jsonb NOT NULL DEFAULT '{}'::jsonb,
    random_seed integer NOT NULL DEFAULT 42,
    mean_cv_mae double precision CHECK (mean_cv_mae IS NULL OR mean_cv_mae >= 0),
    std_cv_mae double precision CHECK (std_cv_mae IS NULL OR std_cv_mae >= 0),
    final_mae double precision CHECK (final_mae IS NULL OR final_mae >= 0),
    final_rmse double precision CHECK (final_rmse IS NULL OR final_rmse >= 0),
    final_smape double precision CHECK (final_smape IS NULL OR final_smape >= 0),
    train_seconds double precision CHECK (train_seconds IS NULL OR train_seconds >= 0),
    predict_ms_median double precision CHECK (predict_ms_median IS NULL OR predict_ms_median >= 0),
    artifact_size_bytes bigint CHECK (artifact_size_bytes IS NULL OR artifact_size_bytes >= 0),
    artifact_id uuid REFERENCES app.artifacts(id) ON DELETE RESTRICT,
    is_recommended boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE UNIQUE INDEX ux_one_recommended_model_per_experiment
    ON ml.model_runs (experiment_id)
    WHERE is_recommended;

CREATE INDEX ix_model_runs_experiment
    ON ml.model_runs (experiment_id, created_at);

CREATE TABLE ml.fold_metrics (
    model_run_id uuid NOT NULL
        REFERENCES ml.model_runs(id) ON DELETE CASCADE,
    fold_no smallint NOT NULL CHECK (fold_no BETWEEN 1 AND 4),
    train_start timestamptz NOT NULL,
    train_end timestamptz NOT NULL,
    validation_start timestamptz NOT NULL,
    validation_end timestamptz NOT NULL,
    evaluation_rows integer NOT NULL CHECK (evaluation_rows > 0),
    mae double precision NOT NULL CHECK (mae >= 0),
    rmse double precision NOT NULL CHECK (rmse >= 0),
    smape double precision NOT NULL CHECK (smape >= 0),
    train_seconds double precision NOT NULL CHECK (train_seconds >= 0),
    PRIMARY KEY (model_run_id, fold_no),
    CHECK (train_start <= train_end),
    CHECK (validation_start <= validation_end),
    CHECK (train_end < validation_start)
);

CREATE TABLE ml.horizon_metrics (
    model_run_id uuid NOT NULL
        REFERENCES ml.model_runs(id) ON DELETE CASCADE,
    evaluation_scope varchar(20) NOT NULL
        CHECK (evaluation_scope IN ('cv', 'final_test')),
    horizon smallint NOT NULL CHECK (horizon BETWEEN 1 AND 24),
    mae double precision NOT NULL CHECK (mae >= 0),
    rmse double precision NOT NULL CHECK (rmse >= 0),
    smape double precision NOT NULL CHECK (smape >= 0),
    PRIMARY KEY (model_run_id, evaluation_scope, horizon)
);

CREATE TABLE ml.forecasts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_run_id uuid NOT NULL
        REFERENCES ml.model_runs(id) ON DELETE RESTRICT,
    dataset_version_id uuid NOT NULL
        REFERENCES app.dataset_versions(id) ON DELETE RESTRICT,
    job_id uuid REFERENCES app.jobs(id) ON DELETE RESTRICT,
    origin timestamptz NOT NULL,
    status varchar(20) NOT NULL CHECK (status IN (
        'queued', 'running', 'completed', 'failed', 'cancelled'
    )),
    total_energy_kwh double precision
        CHECK (total_energy_kwh IS NULL OR total_energy_kwh >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (job_id)
);

CREATE TABLE ml.forecast_points (
    forecast_id uuid NOT NULL
        REFERENCES ml.forecasts(id) ON DELETE CASCADE,
    horizon smallint NOT NULL CHECK (horizon BETWEEN 1 AND 24),
    target_time timestamptz NOT NULL,
    predicted_energy_kwh double precision NOT NULL
        CHECK (predicted_energy_kwh >= 0),
    actual_energy_kwh double precision
        CHECK (actual_energy_kwh IS NULL OR actual_energy_kwh >= 0),
    PRIMARY KEY (forecast_id, horizon),
    UNIQUE (forecast_id, target_time)
);

CREATE INDEX ix_forecasts_version_created
    ON ml.forecasts (dataset_version_id, created_at DESC);

-- PostgreSQL-backed job claim example. Execute inside one transaction.
--
-- WITH candidate AS (
--     SELECT id
--     FROM app.jobs
--     WHERE status = 'queued'
--       AND cancel_requested_at IS NULL
--       AND attempt < max_attempts
--     ORDER BY priority DESC, created_at
--     FOR UPDATE SKIP LOCKED
--     LIMIT 1
-- )
-- UPDATE app.jobs j
-- SET status = 'running',
--     worker_id = :worker_id,
--     started_at = COALESCE(started_at, now()),
--     heartbeat_at = now(),
--     attempt = attempt + 1,
--     updated_at = now()
-- FROM candidate
-- WHERE j.id = candidate.id
-- RETURNING j.*;
