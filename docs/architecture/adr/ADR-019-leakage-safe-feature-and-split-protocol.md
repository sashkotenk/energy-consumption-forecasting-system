# ADR-019: Leakage-safe feature and split protocol

## Status

Accepted.

## Context

The forecast origin is the end of a completed hour. A direct forecast contains the next 24 hourly
targets. Ordinary rolling and randomly shuffled validation helpers can expose the current target,
future targets, or final-test rows to training.

## Decision

- `base_v1` contains the fixed lag, shifted rolling and local calendar features from the research
  protocol. `base_quality_v1` adds only summaries of quality information available before origin.
- Rolling inputs are shifted by one hour before aggregation. Missing timestamps are inserted as
  missing facts, never zero-filled, so incomplete lag history excludes an origin.
- Direct targets are ordered as `t+1` through `t+24`.
- Validation uses the four 2009 calendar quarters. A training origin is eligible only when its last
  target is strictly earlier than the first validation origin, which removes the preceding 24
  origins from training.
- Cross-validation and final-test indexes are exposed by separate methods. Cross-validation never
  returns an origin from 2010.
- A fresh preprocessing object is created and fitted from the training rows of each fold.
- A SHA-256 digest over feature names, order, dtypes, horizon and version identifies the schema.

## Consequences

The first 168 hours cannot produce a complete feature vector. Any missing required historical value
can remove later origins until the relevant lag and rolling windows are complete again. Calendar
features are computed in the dataset timezone while chronological continuity is checked in UTC.
Model bundles and forecast requests must compare both the schema version and its digest.
