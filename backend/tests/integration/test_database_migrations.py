from __future__ import annotations

import asyncio

import pytest
from alembic import command
from sqlalchemy import text

from energy_forecast.database import create_database_engine
from tests.integration.conftest import alembic_config, upgrade_database

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "app": {
        "artifacts",
        "data_quality_issues",
        "data_quality_reports",
        "dataset_import_errors",
        "dataset_imports",
        "dataset_versions",
        "datasets",
        "job_attempts",
        "jobs",
        "transformation_runs",
        "weather_locations",
    },
    "ts": {"hourly_observations", "raw_measurements", "weather_observations"},
    "ml": {
        "experiments",
        "fold_metrics",
        "forecast_points",
        "forecasts",
        "horizon_metrics",
        "model_runs",
    },
}

EXPECTED_INDEXES = {
    "ix_artifacts_sha256",
    "ix_dataset_versions_dataset_created",
    "ix_import_errors_import_row",
    "ix_experiments_version_created",
    "ix_forecasts_version_created",
    "ix_hourly_training_ready",
    "ix_hourly_version_time",
    "ix_jobs_claim",
    "ix_jobs_status_created",
    "ix_job_attempts_job_started",
    "ix_model_runs_experiment",
    "ix_quality_issues_version_time",
    "ix_quality_issues_version_type",
    "ix_quality_reports_version_latest",
    "ix_raw_version_time",
    "ix_weather_location_time",
    "ux_dataset_versions_source",
    "ux_jobs_idempotency_key",
    "ux_one_recommended_model_per_experiment",
}


async def _inspect_database(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        async with engine.connect() as connection:
            extension_rows = await connection.execute(
                text(
                    "SELECT extname, extversion FROM pg_extension "
                    "WHERE extname IN ('pgcrypto', 'timescaledb')"
                )
            )
            extensions: dict[str, str] = {
                str(name): str(version) for name, version in extension_rows
            }
            assert set(extensions) == {"pgcrypto", "timescaledb"}
            assert extensions["timescaledb"] == "2.28.3"

            table_rows = await connection.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema IN ('app', 'ts', 'ml')"
                )
            )
            tables_by_schema: dict[str, set[str]] = {schema: set() for schema in EXPECTED_TABLES}
            for schema, table in table_rows:
                tables_by_schema[schema].add(table)
            assert tables_by_schema == EXPECTED_TABLES

            hypertable_rows = await connection.execute(
                text(
                    "SELECT hypertable_schema, hypertable_name "
                    "FROM timescaledb_information.hypertables"
                )
            )
            assert set(hypertable_rows) == {
                ("ts", "hourly_observations"),
                ("ts", "raw_measurements"),
                ("ts", "weather_observations"),
            }

            index_rows = await connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname IN ('app', 'ts', 'ml')")
            )
            assert set(index_rows.scalars()) >= EXPECTED_INDEXES

            partitioned_keys = await connection.execute(
                text(
                    """
                    SELECT n.nspname, c.relname, array_agg(a.attname ORDER BY key.ordinality)
                    FROM pg_constraint con
                    JOIN pg_class c ON c.oid = con.conrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS key(attnum, ordinality)
                    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = key.attnum
                    WHERE con.contype IN ('p', 'u') AND n.nspname = 'ts'
                    GROUP BY n.nspname, c.relname, con.oid
                    """
                )
            )
            keys = {(schema, table): columns for schema, table, columns in partitioned_keys}
            assert "observed_at" in keys[("ts", "raw_measurements")]
            assert "hour_start" in keys[("ts", "hourly_observations")]
            assert "observed_at" in keys[("ts", "weather_observations")]
    finally:
        await engine.dispose()


def test_empty_database_upgrades_to_complete_timescale_schema(
    temporary_database_url: str,
) -> None:
    upgrade_database(temporary_database_url)
    asyncio.run(_inspect_database(temporary_database_url))


async def _application_schemas(database_url: str) -> set[str]:
    engine = create_database_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name IN ('app', 'ts', 'ml')"
                )
            )
            return set(rows.scalars())
    finally:
        await engine.dispose()


def test_initial_migration_downgrades_empty_schema_and_reupgrades(
    temporary_database_url: str,
) -> None:
    config = alembic_config(temporary_database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert asyncio.run(_application_schemas(temporary_database_url)) == set()

    command.upgrade(config, "head")
    assert asyncio.run(_application_schemas(temporary_database_url)) == {"app", "ts", "ml"}
