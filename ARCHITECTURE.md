# EnergyForecast architecture

## Implemented snapshot

EnergyForecast is an implemented modular monolith with one Python backend codebase deployed as separate FastAPI and worker processes. The complete product flow covers dataset ingestion, immutable provenance, quality evaluation, hourly transformation, bounded analytics, leakage-safe forecasting experiments, common-origin model comparison, verified direct 24-hour forecasting and controlled result exports. The React client exposes the corresponding Ukrainian user workflows.

```text
Browser -> Nginx edge -> React SPA / FastAPI API
                                  |
                                  v
                         PostgreSQL/TimescaleDB
                                  ^
                                  |
                         background worker
                                  <-> artifact store
```

The production-like Docker Compose topology contains six services: `db`, `migrate`, `api`, `worker`, `web` and `nginx`. The one-shot migration service is an explicit gate before API/worker readiness. PostgreSQL is private, only the API bridges backend and edge networks, and only API/worker mount the persistent artifact volume. Application/proxy containers use non-root users where compatible, read-only root filesystems, dropped capabilities, `no-new-privileges` and bounded tmpfs paths.

## Backend boundaries

### Datasets and artifacts

`energy_forecast.datasets` owns dataset catalog operations, UCI/generic CSV parsing and import orchestration. Raw uploads are immutable provenance anchors: the system records source metadata, size and SHA-256 before derived work. User filenames are metadata only; generated opaque storage keys keep caller-controlled values outside the filesystem path boundary.

`energy_forecast.artifacts` provides an application-owned port with a local filesystem adapter and PostgreSQL metadata. Writes use generated keys, checksum tracking and controlled publication. Public downloads resolve an artifact ID through metadata and never expose storage paths.

### Quality and transformation

`energy_forecast.quality` distinguishes parse failures, missing values, zeros, exact/conflicting duplicates, time gaps, ordering violations, physical invalidity and informational statistical anomalies.

`energy_forecast.transformations` creates a child immutable dataset version and persists hourly facts. Minute active power is integrated to kWh; short interpolation is limited to bounded gaps of at most five minutes with valid neighbors. Longer or boundary gaps are not silently filled or scaled. Quality status, coverage, interpolation counts and transformation policy remain traceable to the derived version.

### Analytics

`energy_forecast.analytics` performs version-scoped indexed aggregate queries for summary statistics, bounded series, hourly/weekday profiles, heatmaps and distributions. The service calculates server-side bucket sizes and enforces range/point bounds so UI requests cannot force unbounded result sets.

### Jobs

Long-running import/transformation/experiment work uses a PostgreSQL-backed queue. Short claim transactions use `FOR UPDATE SKIP LOCKED`; the database transaction is not held while the handler performs parsing or ML work. Job state includes idempotency, attempt history, heartbeat, cancellation, retry and stale-worker recovery. The browser polls durable REST job state and stops at terminal states.

### ML experiments

`energy_forecast.ml` owns feature construction, chronological split rules, metrics, required model implementations, model-bundle integrity and benchmarking. The feature boundary uses fixed lags, shifted rolling values, calendar cycles and optional past-quality signals. A feature at forecast origin `t` uses only information available at or before `t`.

The target is direct 24-hour forecasting. Ridge, Random Forest and Histogram Gradient Boosting use 24 direct regressors; Seasonal Naive-24 is the mandatory baseline and Seasonal Naive-168 is retained as a diagnostic. Validation uses four expanding chronological folds with a 24-hour purge. Preprocessing is fitted on train rows only. Selection is completed from pre-final-test evidence before final-2010 indexes are opened. Compared models use common eligible origins.

W0 (consumption history plus calendar features) is implemented. W1 is represented as an explicit mode but rejected until a real weather dataset is connected; no planned weather adapter is described as part of the release architecture.

### Model bundles and forecasts

Internal model bundles carry checksums and compatibility metadata. Forecasting resolves only a completed model run, verifies artifact/payload integrity plus dataset/algorithm/schema/runtime compatibility before deserializing joblib bytes, rebuilds features from persisted history and persists exactly 24 ordered forecast points plus the daily total. Missing required history fails explicitly instead of being fabricated.

### Exports

Forecast and experiment exports are bounded and created synchronously through the existing Artifact Service. Supported artifacts include forecast CSV/chart data and experiment metrics/manifest data. Controlled download routes allow only export-purpose artifacts. CSV text cells that begin with spreadsheet-formula prefixes are neutralized while numeric output remains numeric.

## Frontend boundaries

The React/TypeScript client follows the dependency direction:

```text
app/pages/widgets -> features/entities/shared -> generated API client
```

TanStack Query owns server state and terminal-state polling, React Hook Form and Zod own form state/validation, and route state remains in URLs. The FastAPI runtime OpenAPI artifact generates `frontend/src/generated/api`; API DTOs are not duplicated by hand.

Dataset/import, quality/transformation, analysis, experiment, comparison and forecast pages consume the generated client. ECharts is wrapped once, disposed on cleanup, keyboard-focusable and paired with captions or numeric/table alternatives. Shared loading, empty and error states are user-facing Ukrainian components.

## Persistence and transaction model

PostgreSQL stores catalog metadata, immutable dataset/version provenance, imports, quality/transformation evidence, durable jobs/attempts, experiment/model-run results, forecasts and artifact metadata. TimescaleDB hypertables store time-series facts. Alembic is the executable schema source of truth; `docs/database/schema-design.sql` is the synchronized reference DDL.

Async sessions are operation-scoped. Long parsing or model training is never performed inside an open database transaction. Mutations that must be atomic—such as staging a dataset version/import/job—use short explicit transactions and compensating cleanup where external artifact publication has already occurred.

## API and generated-client contract

FastAPI runtime OpenAPI 3.1 is exported deterministically to `docs/api/openapi.json`. The design reference is `docs/api/openapi-design.yaml`. CI checks runtime export drift, design/runtime assertions and generated TypeScript SDK drift before compilation. The runtime OpenAPI is authoritative for implemented routes.

## Deployment trust boundaries

The pinned backend image is reused for `migrate`, `api` and `worker`; separate static-web and edge-Nginx images complete the topology. The edge forwards same-origin `/api/v1/` requests to the unprefixed API runtime, aligns its 300 MiB body limit with the application upload boundary, streams request bodies and applies bounded proxy timeouts/security headers without wildcard CORS. Direct `/artifacts/` edge paths are rejected and the edge cannot mount the artifact volume.

The coursework release has no built-in authentication. Direct Internet exposure requires an external authenticated TLS gateway and an additional deployment-specific threat review.

## Authoritative technical baselines

- `docs/api/openapi.json` — authoritative implemented REST contract;
- `docs/api/openapi-design.yaml` — design/runtime traceability reference;
- `docs/database/schema-design.sql` — synchronized physical-schema reference;
- `backend/migrations/versions/` — executable schema migrations;
- `docs/deployment.md` — supported container topology and operations;
- `docs/diagrams/` — C4/UML/sequence/ER/deployment/ML diagrams;
- `docs/sad/SAD_v1.0.md` — final English Software Architecture Document;
- `docs/architecture/adr/README.md` — accepted architectural decisions;
- `docs/architecture/traceability.csv` — requirement-to-code/data/API/test/evidence mapping;
- `docs/evidence/` — measured release-readiness and handoff evidence.

Alembic migrations, passing tests and recorded ADRs supersede remaining design assumptions. Any implementation deviation must be documented in the same change that introduces it.

## Reproducibility and safety constraints

- Python, Node, Nginx and TimescaleDB/PostgreSQL versions are pinned and dependency lockfiles are committed.
- Raw data, uploads, model binaries, exports, secrets, database volumes and local artifacts are excluded from Git.
- Missing measurements are not converted to zero.
- Dataset transformations never mutate source versions or raw artifacts.
- Uploaded filenames cannot select storage paths.
- Model loading accepts only internally produced checksum-verified compatible bundles.
- Time-series preprocessing preserves chronological order, shifted rolling features, train-only preprocessing and the 24-hour purge.
- Final-test data cannot participate in tuning/feature/threshold/model selection.
- Model comparison uses common forecast origins.
- Controlled exports do not expose `storage_key` or filesystem roots and neutralize spreadsheet-formula text.
- PostgreSQL remains private in the production-like topology.
- CI verifies migrations, OpenAPI/SDK drift, backend/frontend tests, ML guards, Compose smoke, dependency/secret/container scanning, documentation links/diagrams and evidence checksums.

For component-level detail and constraints see [`docs/sad/SAD_v1.0.md`](docs/sad/SAD_v1.0.md). For supported user behavior see [`docs/user-guide.md`](docs/user-guide.md), and for release evidence see [`docs/evidence/README.md`](docs/evidence/README.md).
