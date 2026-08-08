# Point-5 experimental handoff

This directory contains the public, reproducible handoff contract for the final experimental stage.
It does not contain the private coursework plan, the UCI source file, generated model bundles or local
database identifiers.

The repository commits the complete experiment protocol, feature/split definitions, dependency
baseline, reproduction entry points, result templates and the explicit final-test isolation rule. The
only values that cannot be truthfully committed in advance are the SHA-256 of the externally supplied
full UCI file and the UUID of the prepared hourly dataset version created in the local database.
Those two values are bound immediately before the final full-dataset run rather than invented.

## Finalize the handoff for a full UCI run

1. Supply the original UCI file outside Git and run the supported import/quality/hourly preparation
   flow.
2. Record the immutable source SHA-256 reported by EnergyForecast and the resulting ready hourly
   dataset-version UUID.
3. From `backend/`, generate a bound handoff document:

```bash
uv run --frozen python ../scripts/generate_point5_handoff.py \
  --dataset-sha256 <64-hex-source-sha256> \
  --prepared-dataset-version <uuid> \
  --require-dataset-binding \
  --output ../build/point5-handoff.json
```

Use `--benchmark-json` to associate a fresh release/system benchmark artifact with that run when
available. The generated document records the current Git commit unless `--release-candidate-sha` is
provided explicitly.

The committed `docs/evidence/point5-handoff.json` is the protocol baseline. Its dataset-binding fields
remain `null` with status `pending_external_uci_profile` until a real external UCI source has been
prepared. This is intentional: repository evidence must never fabricate a dataset checksum or a
runtime database UUID.

## Reproduction entry points

- `scripts/run_uci_profile.ps1` — validates the externally supplied full UCI source profile;
- `scripts/generate_point5_handoff.py` — binds the final source/version and emits the handoff;
- `scripts/generate_release_benchmark.py` — deterministic CPU/ML/parser benchmark;
- `scripts/generate_system_benchmark.py` — database batch-insert and full analytics endpoint latency;
- `scripts/benchmark_compose_startup.sh` — cold/warm Compose startup readiness benchmark;
- `scripts/measure_frontend_bundle.py` — production frontend bundle-size evidence;
- `scripts/verify.ps1` — repository-wide verification gate.

## Result templates

`final-results-template.csv` is the one-row-per-experiment/model summary template.
`horizon-results-template.csv` is the horizon-level (1..24) reporting template. They intentionally
contain headers only before the final scientific run.

The final 2010 test period must stay isolated from feature decisions, tuning and model selection.
Recommendation is persisted from chronological cross-validation evidence first; only then may the
selected model request final-test indexes. See ADR-022 and the mandatory `ml_guard` regression suite.
