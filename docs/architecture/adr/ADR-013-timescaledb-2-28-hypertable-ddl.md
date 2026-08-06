# ADR-013: Use the TimescaleDB 2.28 hypertable DDL

## Status

Accepted on 2026-08-07.

## Context

The design baseline converted ordinary PostgreSQL tables with `create_hypertable()`. TimescaleDB
marks that API as old starting with version 2.20 and documents `CREATE TABLE ... WITH
(tsdb.hypertable, tsdb.partition_column = ...)` for new hypertables. EnergyForecast also requires a
reproducible database image rather than a mutable `latest` tag.

## Decision

Use `timescale/timescaledb:2.28.3-pg17`, containing PostgreSQL 17 and TimescaleDB 2.28.3. Create the
three `ts` tables directly as hypertables with the current syntax. Set
`tsdb.create_default_indexes = false` so Alembic creates only the explicitly designed indexes.

Primary and unique keys on every hypertable include its time partition column:

- `raw_measurements`: `(dataset_version_id, observed_at, source_row_number)`;
- `hourly_observations`: `(dataset_version_id, hour_start)`;
- `weather_observations`: `(location_id, observed_at)`.

## Consequences

The implemented DDL differs syntactically from the original draft but preserves its logical model.
The database baseline requires TimescaleDB 2.20 or newer and is verified specifically against
2.28.3. Changing the image version requires migration recreation and metadata integration tests.
