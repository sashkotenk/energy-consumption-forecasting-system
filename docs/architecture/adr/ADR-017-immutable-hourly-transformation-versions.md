# ADR-017: Immutable hourly transformation versions

- Status: Accepted
- Date: 2026-08-07

## Context

Raw measurements are immutable evidence, while cleaning, duplicate resolution, interpolation and
hourly aggregation are policy-dependent. Rewriting an imported version would lose provenance and
make model inputs irreproducible. A non-null hourly energy column would also force a missing hour to
look like measured zero consumption.

## Decision

Every accepted transformation atomically creates a queued job, a transformation run, and a child
dataset version linked by `parent_version_id`. The child reuses the immutable raw-artifact reference
but has no source checksum of its own and never copies or edits raw measurements. Its manifest stores
the source version, engine version, complete policy and deterministic summary.

The transformation resolves duplicates only through the requested policy. Linear interpolation is
limited to bounded gaps of at most five minutes with valid observations on both sides; dataset
boundaries are never imputed. Active power is integrated using the source interval and energy samples
are summed. Incomplete hours are never coverage-scaled.

Hourly rows retain observed and expected counts, coverage, imputed count, maximum missing run,
quality flags and one explicit status. Only `complete` and `imputed_short_gap` are training-ready.
`energy_kwh` is nullable so an hour with no usable energy remains missing rather than becoming zero.

## Consequences

- Multiple policy runs over one source remain independently reproducible and auditable.
- Raw rows and artifact bytes stay unchanged across retries and derived versions.
- Consumers must filter by quality status and handle nullable energy explicitly.
- A downgrade that restores the former non-null constraint must remove rows with missing energy and
  is therefore intentionally documented in the migration.
