# EnergyForecast Software Architecture Document

**Document status:** Final v1.0  
**Release scope:** coursework release candidate through TASK-22  
**Language:** English  
**Architecture style:** modular monolith with separate API and worker processes

## 1. Purpose and scope

EnergyForecast is a single-user client-server system for importing electricity-consumption time series, preserving source/version provenance, evaluating data quality, producing immutable hourly transformations, analysing hourly consumption, running leakage-safe forecasting experiments, comparing required forecasting methods, generating a direct 24-hour forecast and exporting controlled result artifacts.

This document describes only implemented release behavior. It intentionally excludes speculative services and future extensions. In particular, the operational release does not contain authentication, a message broker, a weather-data adapter, online learning, Kubernetes or public cloud infrastructure.

### 1.1 Stakeholders

- **Analyst / building operator:** imports data, reviews quality, analyses consumption, compares models and creates forecasts.
- **Researcher / reviewer:** inspects experiment provenance, chronological evaluation, metrics and reproducibility evidence.
- **Developer / maintainer:** evolves the modular monolith, migrations, API contract and generated client while preserving invariants.
- **Coursework reviewer:** evaluates engineering quality, architectural documentation, test evidence and reproducibility.

### 1.2 Main functional requirements

The release supports UCI and mapped generic CSV import, explicit quality reporting, immutable hourly transformations, bounded analytics, Seasonal Naive/Ridge/Random Forest/Histogram Gradient Boosting experiments, common-origin comparison, 24-hour forecasting, artifact-backed exports, persistent history and a REST API consumed by a React UI.

The authoritative requirement-to-code/test mapping is [traceability.csv](../architecture/traceability.csv).

### 1.3 Main non-functional requirements

The architecture prioritizes reproducibility, provenance, leakage prevention, bounded resource use, typed contracts, deterministic tests, explicit transaction boundaries, controlled artifact access and repeatable container deployment. A missing measurement is never treated as zero, and model deserialization is limited to checksum-verified internal bundles.

## 2. Architecture overview

### 2.1 System structure

EnergyForecast is one repository and one backend codebase, deployed as multiple runtime processes:

- **React/TypeScript web client** built by Vite and served as static assets;
- **FastAPI API process** for synchronous HTTP request handling;
- **worker process** for durable asynchronous jobs;
- **PostgreSQL 17 + TimescaleDB 2.28.3** for relational metadata and time-series facts;
- **local artifact-store adapter** for immutable raw files, model bundles and exports;
- **Nginx edge proxy** for same-origin browser access and bounded proxy behavior.

The backend is a modular monolith. Domain/application modules communicate through typed ports and repositories instead of through network calls. API and worker processes share the same package but have separate lifecycles and database sessions.

See the system, container, component and deployment views in [docs/diagrams](../diagrams/).

### 2.2 Runtime deployment

The production-like Compose topology contains exactly six services: `db`, `migrate`, `api`, `worker`, `web` and `nginx`.

The one-shot `migrate` service applies Alembic migrations before API/worker readiness. PostgreSQL is not published in the production-like overlay. Database, migration and worker services remain on backend-only networks. The API bridges the backend and edge networks. Only API and worker mount the persistent artifact volume.

Application and proxy containers run non-root with read-only root filesystems, dropped Linux capabilities and `no-new-privileges`. Required temporary write locations are bounded tmpfs mounts. The edge proxy forwards `/api/v1` to the existing unprefixed FastAPI routes and rejects direct `/artifacts/` access.

Deployment details are in [deployment.md](../deployment.md) and ADR-025.

## 3. Main components

### 3.1 Dataset ingestion

`energy_forecast.datasets` owns dataset catalog operations, upload validation, UCI/generic parsing and import orchestration. Parsers stream batches rather than loading the complete UCI source into memory. The raw source is immutable and its SHA-256, size and import metadata are persisted before derived processing.

Uploaded filenames are not filesystem paths. Server-generated storage keys keep user input outside the storage-path trust boundary.

### 3.2 Quality evaluation

`energy_forecast.quality` reports parse issues, missing values, exact/conflicting duplicates, gaps, ordering violations, physical invalidity and informational robust anomalies. Quality evidence is versioned and machine-readable. Missing values and legitimate zeros remain distinct.

### 3.3 Hourly transformation

`energy_forecast.transformations` applies an explicit duplicate policy and converts supported source quantities to hourly active energy in kWh. A 1 kW minute-level series integrates through `P/60`. Linear interpolation is restricted to bounded gaps of at most five minutes with valid neighbors. Longer or boundary gaps remain explicit. Transformation creates a new immutable version rather than mutating the source.

### 3.4 Analytics

`energy_forecast.analytics` exposes bounded summary, series, profile, heatmap and distribution operations. The service calculates a server-side bucket size so a caller-supplied range cannot force an unbounded point response. PostgreSQL/TimescaleDB performs aggregate queries over ready hourly facts.

### 3.5 Experiment and ML pipeline

`energy_forecast.ml` implements feature construction, chronological splits, metrics, required models, bounded search, model-bundle validation and benchmark helpers. `energy_forecast.experiments` persists experiment state, model runs, manifests and selection evidence.

The target is a direct vector of 24 hourly values. ML algorithms use one regressor per horizon. Feature values at forecast origin `t` can use only information available at or before `t`; rolling features are shifted before calculation. Preprocessing is fit only on each fold's train rows. Validation uses chronological expanding folds with a 24-hour purge. Final 2010 test indexes are requested only after selection has been completed from pre-final-test evidence.

Required algorithms are Seasonal Naive-24, Ridge, Random Forest and Histogram Gradient Boosting; Seasonal Naive-168 is a diagnostic baseline. W0 is the implemented operational feature mode. W1 is rejected unless actual weather observations are present; no absent weather integration is represented as implemented.

### 3.6 Model bundles and forecasting

`energy_forecast.ml.bundles` serializes internal model bundles with checksums and compatibility metadata. Forecasting accepts only completed eligible model runs and verifies artifact checksum, model algorithm, feature schema and runtime compatibility before loading the internal joblib payload.

`energy_forecast.forecasting` builds features from persisted history at an explicit or latest eligible origin and returns exactly 24 ordered points plus total expected daily energy. Missing required lag history is an error, not an invitation to fabricate values.

### 3.7 Jobs

The PostgreSQL-backed job queue provides idempotency keys, attempt history, retry, cancellation and stale-worker recovery. Claiming uses short transactions and row locking with `FOR UPDATE SKIP LOCKED`. Long import/training work runs outside database transactions. REST clients poll durable job state and stop at terminal states.

### 3.8 Exports and artifacts

`energy_forecast.exports` creates bounded forecast/experiment exports in the artifact store and exposes controlled downloads by artifact ID. Artifact metadata records media type, size and SHA-256. Direct storage locations are not public contract fields. CSV serialization neutralizes text values beginning with spreadsheet-formula prefixes while preserving numeric values as numeric output.

### 3.9 Frontend

The React/TypeScript client provides datasets/import, quality/transformation, analysis, experiments, comparison and forecast screens. It consumes the generated TypeScript SDK derived from committed runtime OpenAPI. TanStack Query handles server state and terminal-state polling. ECharts instances are keyboard-focusable, disposed on cleanup and paired with accessible text/table information.

## 4. Data architecture

PostgreSQL stores catalog metadata, immutable dataset versions, import/quality/transformation evidence, jobs and attempts, experiment/model-run metrics, forecasts and artifact metadata. TimescaleDB hypertables store time-series facts where appropriate.

The physical reference DDL is [schema-design.sql](../database/schema-design.sql), and Alembic is the executable migration source of truth. The release migration head is `c3d9a5f27410`. CI applies migrations to an empty TimescaleDB instance and executes `alembic check` to detect metadata drift.

Core invariants include:

- raw artifacts and dataset versions are immutable provenance anchors;
- derived hourly facts belong to a specific immutable version;
- missing energy can remain SQL `NULL` and is not rewritten to zero;
- experiment manifests bind dataset/version, schema, parameters, seed and code commit;
- model/export artifact metadata includes cryptographic checksum and purpose.

## 5. API and contract management

FastAPI produces the runtime OpenAPI 3.1 document committed at [openapi.json](../api/openapi.json). [openapi-design.yaml](../api/openapi-design.yaml) documents the design contract. Unit assertions check design/runtime invariants, and `scripts/export_openapi.py --check` rejects runtime drift.

The React client uses generated TypeScript code under `frontend/src/generated/api`. `npm run api:check` regenerates the client from runtime OpenAPI and fails on tracked drift. Hand-written duplicate API DTOs are not the source of truth.

TASK-22 changes no API contract and no database schema.

## 6. Security and trust boundaries

The implemented controls relevant to this release are summarized in [security-review.md](../evidence/security-review.md). Important boundaries are:

- bounded and validated uploads;
- generated artifact storage keys and path validation;
- SQLAlchemy parameter binding and explicit session/transaction lifetimes;
- allowlisted CORS configuration rather than wildcard edge behavior;
- Gitleaks and private-path scans in CI;
- checksum-verified internal model deserialization only;
- controlled artifact downloads;
- non-root/read-only containers and private PostgreSQL networking;
- locked dependencies plus dependency/container vulnerability scans.

The coursework release deliberately has no authentication. It must not be exposed directly to untrusted networks without an external authenticated TLS gateway.

## 7. Quality attributes and testing

### 7.1 Reproducibility

Experiment manifests capture dataset/version identity, code commit, feature schema, split definition, parameters, seed and metrics. Deterministic synthetic fixtures exercise data-quality and ML invariants without committing the UCI dataset.

### 7.2 Scientific integrity

Mandatory `ml_guard` tests cover shifted features, future-value perturbation, train/validation target separation, common-origin evaluation, final-test isolation, deterministic seed behavior and manifest completion rules. Assertions are not weakened to pass CI.

### 7.3 Reliability

Unit tests isolate domain logic. PostgreSQL/TimescaleDB integration tests exercise persistence, migrations, APIs, artifacts and workers. Playwright covers the primary browser journey from import through controlled forecast export. A clean-volume Compose smoke validates migration completion, service health, SPA delivery and proxied API readiness.

### 7.4 Performance

`backend/tests/unit/test_parser_performance.py` enforces bounded incremental parser memory. `scripts/generate_release_benchmark.py` records machine profile plus measured parser, quality, transformation, bounded-analytics, API and direct-24 Ridge train/predict timings on deterministic synthetic input. The complete UCI profile remains an explicitly external-source check.

Detailed verification is documented in [testing.md](../testing.md) and the evidence pack under [docs/evidence](../evidence/).

## 8. Architectural decisions and constraints

ADRs under [docs/architecture/adr](../architecture/adr/) record accepted decisions for TimescaleDB DDL, job semantics, import timezone/restart behavior, quality/version evidence, immutable transformations, bounded analytics, leakage-safe ML, verified model bundles, execution profiles, pre-final-test selection, synchronous verified forecasting, bounded exports and hardened Compose deployment.

The system remains intentionally a modular monolith. Adding Redis/Celery, microservices or a broker would increase operational complexity without solving a baseline requirement.

## 9. Known limitations

- No authentication/authorization in the coursework release.
- Full UCI data is not committed and must be supplied externally for the manual full-dataset profile.
- W1 weather mode is not operational without a real weather dataset/source; no final weather-benefit result is claimed.
- Final UCI model-ranking/accuracy findings belong to the later experimental stage and are not invented in this release-readiness document.
- The frontend production build has a known non-blocking chunk-size warning.
- External Internet deployment requires TLS/authentication/rate-limiting controls outside the supplied Compose baseline.

## 10. Release-readiness references

- [Architecture overview](../../ARCHITECTURE.md)
- [User guide](../user-guide.md)
- [Testing](../testing.md)
- [Deployment](../deployment.md)
- [Traceability matrix](../architecture/traceability.csv)
- [Runtime OpenAPI](../api/openapi.json)
- [Database reference DDL](../database/schema-design.sql)
- [Evidence pack](../evidence/README.md)
- [Implementation log](../implementation-log.md)
