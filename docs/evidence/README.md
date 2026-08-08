# Release-readiness evidence pack

This directory contains public, reproducible evidence for the EnergyForecast coursework release. It intentionally contains no private planning material, raw UCI data, user uploads, generated model bundles, database volumes or secrets.

The checksum-locked files in this directory are the historical TASK-22 handoff pack. The current pull-request **Release Evidence** workflow reruns the evidence classes on the current code and uploads fresh benchmark/browser/startup artifacts without silently rewriting the historical pack. This keeps old measurements auditable while still detecting regressions after later release-polish changes.

## Contents

- `security-review.md` — final review of upload, path, SQL, CORS, secret, deserialization and container trust boundaries.
- `release-benchmark.json` — the measured deterministic TASK-22 synthetic benchmark committed from its referenced CI run.
- `verification.md` — exact commands, test counts, CI run references, migration/contract results and known warnings for the TASK-22 release-candidate verification run.
- `screenshots/` — representative browser screenshots captured by the deterministic Playwright primary flow.
- `handoff-manifest.json` — checksum-locked historical TASK-22 handoff metadata.
- `point5-handoff.json` — current public experimental handoff protocol when present; unlike the historical checksum manifest, it is regenerated from executable feature/split/dependency contracts.
- `point5/` — final-result templates and instructions for binding the external full-UCI source/version before the scientific run.

## Generate current performance evidence

The CPU/parser/ML benchmark is generated from `backend` after locked dependency synchronization:

```bash
uv run --frozen python ../scripts/generate_release_benchmark.py --output ../build/release-benchmark.json
```

The deterministic benchmark (`energyforecast-release-benchmark/v2`) records the runner CPU, logical CPU count, total memory, Python version, seed/profile semantics and measured values for:

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

After Alembic migrations are applied to a real PostgreSQL/TimescaleDB service, database-backed evidence is generated with:

```bash
uv run --frozen python ../scripts/generate_system_benchmark.py --output ../build/system-benchmark.json
```

This records two measurements that must exercise persistence rather than pure in-memory helpers:

- chunked `RawMeasurement` insert throughput through the real import repository, including one committed transaction per batch;
- full `/dataset-versions/{versionId}/analytics/series` request latency through FastAPI, SQLAlchemy and PostgreSQL/TimescaleDB while enforcing `max_points` on a deterministic 20,000-hour fixture.

Cold/warm product startup is measured separately because it requires control over Docker project volumes:

```bash
bash scripts/benchmark_compose_startup.sh build/compose-startup.json
```

Images are built before timing. The **cold** measurement starts with no project containers, networks or volumes and therefore includes PostgreSQL initialization plus migrations. The **warm** measurement preserves initialized database/artifact volumes but recreates containers and networks. Both measurements terminate on real Compose/HTTP health and migration states; no fixed sleeps or invented performance thresholds are used.

A production frontend build records bundle bytes and deterministic gzip sizes with:

```bash
python scripts/measure_frontend_bundle.py --dist frontend/dist --output build/frontend-bundle.json
```

The Release Evidence workflow runs all of these evidence classes and also executes `pytest -m performance`, including the maximum-range analytics regression and parser-memory regression. These are engineering performance measurements, not final scientific model-quality results.

## Point-5 handoff contract

The current handoff is generated from executable repository definitions rather than copied from planning text:

```bash
cd backend
uv run --frozen python ../scripts/generate_point5_handoff.py \
  --output ../build/point5-handoff.json
uv run --frozen python ../scripts/verify_point5_handoff.py \
  --path ../build/point5-handoff.json
```

It directly records the release candidate, exact locked direct dependencies and lockfile SHA-256 values, feature schema versions/hashes, the four-fold chronological split and 24-hour purge, the E00-E32 experiment matrix, selection protocol, benchmark-machine profile, reproduction scripts, empty result templates and an explicit final-test-isolation declaration.

The full UCI file remains external to Git. Therefore the committed protocol baseline may contain `null` for only two runtime bindings: the external source SHA-256 and the prepared hourly dataset-version UUID. Immediately before the final full-dataset experiment, bind both real values with `--dataset-sha256`, `--prepared-dataset-version` and `--require-dataset-binding`. The generator refuses a partial binding, and the verifier rejects invented or malformed values. See [`point5/README.md`](point5/README.md).

W1 rows E20-E22 stay explicitly blocked until a real weather source exists. Their presence in the experiment matrix defines the research protocol; it is not a claim that weather experiments have already been executed.

## Capture browser and frontend evidence

The Playwright primary flow uses deterministic synthetic API responses and writes screenshots at stable workflow checkpoints. Release Evidence performs the production frontend build first, records bundle-size evidence, then runs Chromium E2E and uploads `test-results`. The committed screenshot in this directory remains the checksum-locked TASK-22 capture; current PR artifacts provide fresh evidence for later code changes without rewriting history.

## Verify documentation and evidence

From the repository root:

```bash
python scripts/verify_documentation.py
python scripts/verify_evidence.py
python scripts/verify_point5_handoff.py
```

The first command validates repository-local Markdown links and Mermaid source structure. The second recomputes SHA-256 values in the historical `handoff-manifest.json`. The third validates the current Point-5 protocol: experiment coverage, exact feature/split identifiers, dependency lock metadata, reproduction paths, result templates and final-test isolation.

The repository-wide `scripts/verify.ps1` gate invokes the applicable evidence checks in addition to backend, database, OpenAPI/SDK, frontend and private-file verification.

## Provenance rule

Committed measured evidence must always identify the workflow run from which it was collected. Historical handoff files are not edited merely to make them look current. Fresh current measurements are uploaded by Release Evidence; if a future committed evidence snapshot replaces a historical file, copy the actual successful-run artifact, record its run/commit provenance and recompute every affected SHA-256 entry together.
