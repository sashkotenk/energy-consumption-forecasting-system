# ADR-015: Import timezone and restart policy

- Status: Accepted
- Date: 2026-08-07

## Context

TimescaleDB requires a non-null `timestamptz` partition key for normalized raw measurements. The UCI
control dataset publishes local civil timestamps for a household near Paris but does not publish a
formal timezone contract. Chunked imports can also be interrupted after one or more committed batch
transactions.

## Decision

The fixed UCI profile interprets source timestamps in `Europe/Paris` and records that value as an
explicit timezone assumption. Generic CSV imports require either an offset in every timestamp or an
explicit IANA timezone mapping. Source text is retained in `timestamp_original`; the raw artifact is
never changed.

Each import attempt first locks its import/version resources, removes normalized rows and parse errors
from an earlier incomplete attempt, and marks the version `importing`. Batches commit independently.
Only the final short transaction writes row statistics and marks the version `imported`. Exceptions or
cooperative cancellation mark the version `failed`, so partial rows are never advertised as valid.

Malformed rows without a usable time partition key are stored in `app.dataset_import_errors` with the
source row number and bounded evidence. Rows with a usable timestamp retain their parse status and null
numeric fields in `ts.raw_measurements`.

## Consequences

- UCI imports work without manual file editing while the timezone uncertainty remains machine-visible.
- Retry has deterministic replace-on-attempt semantics for normalized rows; immutable source bytes and
  checksum metadata are preserved.
- Batch transactions bound memory and lock duration, at the cost of deleting incomplete normalized
  rows before a retry.
- Downstream quality reports must distinguish timezone assumptions from verified source timezone data.
