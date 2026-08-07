# ADR-022: Experiment selection before final test

## Status

Accepted.

## Context

An experiment compares five algorithms over four chronological folds. Reading the 2010 test period
while tuning or choosing an algorithm would make the reported result optimistic. A failed candidate
must also remain distinguishable from a failed experiment.

## Decision

- Experiment configuration and one pending model run per algorithm are staged with the queue job in
  one transaction.
- One feature matrix defines the eligible origins shared by every algorithm. The four 2009 folds and
  24-hour purge come from the versioned split protocol.
- Each successful model run stores its chosen bounded parameters, four fold metrics, mean/std CV MAE,
  prediction time and 24 aggregated horizon metrics. A candidate failure records its own evidence and
  does not delete successful runs.
- Recommendation first limits candidates to 1% of the best mean CV MAE, then 5% of the best standard
  deviation, then uses prediction time and the fixed simplicity order.
- Only after recommendation is persisted may the worker request final-test indexes. Only that model
  receives final-test metrics and a bundle.
- A database constraint requires `result_manifest` before an experiment can become `completed`.
- W1 is part of the public vocabulary but returns a conflict until real weather observations are
  connected; no placeholder weather result is produced.

## Consequences

The final test cannot influence tuning or recommendation through the orchestration API. Partial model
failure remains inspectable, while an all-model failure marks the experiment failed. Retrying a job
can reuse the immutable definition and replace metrics only for the same model-run identifiers.
