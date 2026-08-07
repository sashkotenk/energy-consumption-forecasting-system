# ADR-021: Direct model execution profiles

## Status

Accepted.

## Context

The research protocol compares Ridge, Random Forest and HistGradientBoosting as 24 direct horizon
models. Scikit-learn defaults can introduce random validation or nested parallelism, making temporal
evaluation and runtime measurements inconsistent.

## Decision

- One façade fits and predicts with exactly 24 independent estimators.
- Ridge fits one `StandardScaler` on the supplied training partition and applies it to every horizon.
- Random Forest uses the bounded protocol grid, seed 42 and `n_jobs=1` inside each forest.
- HistGradientBoosting uses the bounded protocol grid, seed 42 and `early_stopping=false`. Random
  internal validation is not permitted.
- The benchmark profile uses one horizon worker and limits native thread pools to one. The production
  profile has separately configured horizon-level joblib parallelism.
- Ridge candidates are exhaustive. Random Forest and HistGradientBoosting sample no more than 20
  configurations reproducibly with seed 42.
- Benchmark evidence uses one warm-up, three measured fits, one prediction warm-up and 30 measured
  predictions. It records median fit time, median/p95 prediction time and compressed joblib size.

## Consequences

All algorithms return `(n_origins, 24)` and can use the same fold rows. Production may be faster than
the benchmark but its timing is reported separately. Any future early stopping implementation must
receive an explicit chronological tail from orchestration rather than use a model's random internal
split.
