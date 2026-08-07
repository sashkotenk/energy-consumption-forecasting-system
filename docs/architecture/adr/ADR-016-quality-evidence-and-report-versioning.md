# ADR-016: Quality evidence and report versioning

- Status: Accepted
- Date: 2026-08-07

## Context

The baseline raw-measurement table rejected negative power, energy and current and non-positive
voltage with database checks. Those constraints discard the exact observations that the Data Quality
Engine must classify and preserve as evidence. Re-running a quality algorithm also needs to retain
which engine version and aggregate set produced an API response.

## Decision

Raw time-series storage enforces structural validity (partition key, source row, interval and parse
status) but does not enforce physical plausibility. The quality domain owns physical validation and
never mutates or deletes raw observations.

Every evaluation creates an immutable `app.data_quality_reports` row with a monotonically increasing
version per dataset version, the engine version, expected interval and deterministic summary. Issue
groups reference their report and store issue type, severity, bounded time range, occurrence count and
at most ten machine-readable evidence examples. Older reports remain queryable by `report_version`.

Statistical anomalies use an informational robust-z threshold and remain in the source data. Exact and
conflicting duplicates are separate issue categories. Report issue lists are ordered and paginated by
the server.

## Consequences

- Physically impossible values can be imported, audited and handled by an explicit later
  transformation policy.
- Database integrity no longer substitutes for domain-quality evidence on raw numeric values.
- Re-evaluation is reproducible and auditable without overwriting earlier reports.
- Quality storage grows per evaluation; later retention policy must remain explicit rather than
  silently deleting evidence.
