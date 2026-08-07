# ADR-018: Bounded server-side analytics

- Status: Accepted
- Date: 2026-08-07

## Context

Analysis screens need summary, time-series, profile, heatmap and distribution data without sending a
complete multi-year hourly series to the browser. Queries must remain reproducible across clients,
preserve quality context and use the existing version/time access path.

## Decision

Analytics reads only materialized `ts.hourly_observations` belonging to a ready dataset version. Every
endpoint requires timezone-aware `from` and `to` values, treats the interval as `[from, to)`, and
rejects reversed or longer-than-five-year ranges. Empty valid ranges return a typed empty `200`
response; unknown versions return `404`, and versions without ready hourly facts return `409`.

Series requests accept hour, day or week resolution and `max_points` from 100 to 10,000. The server
chooses the smallest multiple of the requested resolution whose exact bucket count is within the
limit. Buckets are deterministic in UTC and anchored to Monday 1970-01-05; profiles and heatmaps use
the dataset's recorded IANA timezone. Weekly buckets therefore begin on Monday. Aggregates never
coverage-scale energy. Every response declares `kWh`, timezone, coverage and quality metadata.

Summary, profile, heatmap and histogram aggregation stays in PostgreSQL. Main range queries use the
existing `ix_hourly_version_time (dataset_version_id, hour_start DESC)` index, so this decision needs
no schema migration.

## Consequences

- Browser payload size is bounded independently of the stored period.
- Adaptive aggregation can return a coarser bucket than requested; `bucket_seconds` and
  `downsampled` make that explicit.
- UTC series buckets and local-time profiles have intentionally different time semantics, both stated
  in response metadata.
- PostgreSQL performs percentile and histogram work; future very high concurrency may require
  caching or continuous aggregates, but neither is justified by the coursework workload.
