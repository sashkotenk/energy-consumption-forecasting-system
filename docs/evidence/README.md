# Release-readiness evidence pack

This directory contains public, reproducible evidence for the EnergyForecast coursework release. It intentionally contains no private planning material, raw UCI data, user uploads, generated model bundles, database volumes or secrets.

The checksum-locked files in this directory are the historical TASK-22 handoff pack. The current pull-request **Release Evidence** workflow reruns the same evidence classes on the current code and uploads fresh benchmark/browser artifacts without silently rewriting the historical pack. This keeps old measurements auditable while still detecting regressions after later release-polish changes.

## Contents

- `security-review.md` — final review of upload, path, SQL, CORS, secret, deserialization and container trust boundaries.
- `release-benchmark.json` — the measured deterministic TASK-22 synthetic benchmark committed from its referenced CI run.
- `verification.md` — exact commands, test counts, CI run references, migration/contract results and known warnings for the TASK-22 release-candidate verification run.
- `screenshots/` — representative browser screenshots captured by the deterministic Playwright primary flow.
- `handoff-manifest.json` — TASK-22 handoff metadata and SHA-256 checksums for the committed evidence files.

## Generate current performance evidence

From `backend` after locked dependency synchronization:

```bash
uv run --frozen python ../scripts/generate_release_benchmark.py --output ../build/release-benchmark.json
```

The current deterministic benchmark (`energyforecast-release-benchmark/v2`) records the runner CPU,
logical CPU count, total memory, Python version, seed/profile semantics and measured values for:

- streaming parser throughput on 50,000 deterministic UCI-shaped rows;
- parser peak incremental memory;
- quality evaluation on 10,000 deterministic minute records;
- 24 hours of minute-to-hour transformation;
- combined quality plus transformation for a deterministic day;
- bounded analytics bucket selection;
- FastAPI liveness request latency through the ASGI stack;
- direct-24 Ridge training/prediction/artifact size;
- direct-24 Random Forest training/prediction/artifact size;
- direct-24 Histogram Gradient Boosting training/prediction/artifact size.

The Release Evidence workflow also provisions the pinned PostgreSQL/TimescaleDB service and runs the
complete `pytest -m performance` marker, including the maximum-range analytics regression and parser
memory regression. The benchmark is engineering performance evidence, not the final UCI scientific
experiment. Full-dataset profiling requires an external `ENERGYFORECAST_UCI_PATH` and remains outside
Git because the original UCI file is intentionally not committed.

## Capture browser and frontend evidence

The Playwright primary flow uses deterministic synthetic API responses and writes screenshots at stable workflow checkpoints. Release Evidence performs the production frontend build first, then runs Chromium E2E and uploads `test-results` as an artifact. The committed screenshot in this directory remains the checksum-locked TASK-22 capture; current PR artifacts provide fresh evidence for later code changes without rewriting history.

## Verify documentation and evidence

From the repository root:

```bash
python scripts/verify_documentation.py
python scripts/verify_evidence.py
```

The first command validates repository-local Markdown links and Mermaid source structure. The second recomputes SHA-256 values in `handoff-manifest.json` and fails on missing or modified checksum-locked evidence files.

The repository-wide `scripts/verify.ps1` gate invokes both checks in addition to backend, database, OpenAPI/SDK, frontend and private-file verification.

## Provenance rule

Committed measured evidence must always identify the GitHub Actions run from which it was collected. Historical handoff files are not edited merely to make them look current. If a future handoff must replace those files, collect a successful fresh run, copy the actual artifacts, update the run/commit metadata and recompute every affected SHA-256 entry in `handoff-manifest.json` together.
