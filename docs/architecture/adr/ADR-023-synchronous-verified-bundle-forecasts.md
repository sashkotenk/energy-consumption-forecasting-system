# ADR-023: Synchronous verified-bundle forecasts

## Status

Accepted.

## Context

Creating one 24-hour forecast loads one internal bundle and builds one feature vector. The work is
bounded, unlike model search, while reproducibility depends on rejecting incompatible artifacts and
missing history.

## Decision

- `POST /forecasts` completes synchronously with `201`; it does not create a queue job.
- The model run must be completed and reference an internal immutable artifact. The requested dataset
  must be a ready hourly version.
- Before deserialization, bundle checks cover the artifact checksum, manifest, model checksum,
  feature schema, training dataset version, algorithm, implementation and library-major versions.
- The forecast origin is an aware hour boundary backed by a valid stored hourly bucket. If omitted,
  the latest eligible bucket is used.
- Features use the bundle's quality policy and the same versioned pipeline as training. Missing lag or
  rolling history is an error and is never imputed by the forecast service.
- A valid model output has shape `(1, 24)` and finite values. Negative regression outputs are clipped
  to zero because persisted energy cannot be negative.
- The forecast row and its 24 ordered points are committed in one database transaction. The response
  joins model-run, artifact, dataset and schema provenance and states the dataset timezone.

## Consequences

Interactive forecasts avoid queue latency while retaining a small predictable workload. A later
batch-forecast feature may use jobs without changing the pure forecast engine. Exact dataset matching
means a model must be retrained before forecasting another immutable dataset version.
